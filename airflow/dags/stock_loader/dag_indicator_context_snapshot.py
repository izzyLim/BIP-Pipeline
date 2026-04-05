"""
[10_indicator_context_snapshot_daily]
체크리스트 모니터링 에이전트용 지표 시장 맥락 스냅샷
- macro_indicators 90일 히스토리 → 통계 사전 계산
- 매일 장 마감 후 갱신 (실시간값과 merge하여 에이전트가 활용)
"""

import logging
import statistics
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from utils.db import get_pg_conn
from utils.config import PG_CONN_INFO
from utils.lineage import register_table_lineage_async

logger = logging.getLogger(__name__)

# 대상 지표 (indicator_type, region, family, direction)
TARGETS = [
    ("exchange_rate", "South Korea", "fx", "higher_is_risk"),
    ("stock_index_kospi", "South Korea", "index", "higher_is_positive"),
    ("stock_index_kosdaq", "South Korea", "index", "higher_is_positive"),
    ("stock_index_sp500", "North America", "index", "higher_is_positive"),
    ("stock_index_nasdaq", "North America", "index", "higher_is_positive"),
    ("stock_index_nikkei", "Japan", "index", "higher_is_positive"),
    ("commodity_oil", "North America", "commodity", "neutral"),
    ("commodity_gold", "North America", "commodity", "neutral"),
    ("crypto_btc", "North America", "crypto", "neutral"),
    ("vix", "North America", "sentiment", "higher_is_risk"),
]


def _trend_label(current, avg_5d, avg_20d):
    if avg_5d > avg_20d and current > avg_5d:
        return "상승"
    if avg_5d < avg_20d and current < avg_5d:
        return "하락"
    return "횡보"


def _quantile(sorted_vals, q):
    """간단한 선형 보간 quantile"""
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    pos = (n - 1) * q
    low = int(pos)
    high = min(low + 1, n - 1)
    frac = pos - low
    return sorted_vals[low] + frac * (sorted_vals[high] - sorted_vals[low])


def compute_snapshot(**context):
    """90일 통계 계산 + indicator_context_snapshot 테이블에 upsert"""
    today = datetime.now().date()
    upserted = 0
    skipped = 0

    with get_pg_conn(PG_CONN_INFO) as conn:
        for indicator_type, region, family, direction in TARGETS:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT indicator_date, value
                    FROM macro_indicators
                    WHERE indicator_type = %s AND region = %s
                      AND indicator_date >= CURRENT_DATE - INTERVAL '90 days'
                      AND value IS NOT NULL
                    ORDER BY indicator_date ASC
                """, (indicator_type, region))
                rows = cur.fetchall()

            if not rows or len(rows) < 5:
                logger.warning(f"{indicator_type}/{region}: 표본 부족 ({len(rows)})")
                skipped += 1
                continue

            dates = [r[0] for r in rows]
            values = [float(r[1]) for r in rows]
            sample_size = len(values)

            latest_value = values[-1]
            latest_value_date = dates[-1]

            sorted_vals = sorted(values)
            min_val = sorted_vals[0]
            max_val = sorted_vals[-1]
            avg_val = statistics.mean(values)
            median_val = statistics.median(values)
            stddev_val = statistics.stdev(values) if len(values) >= 2 else 0

            # 근사 percentile (p10, p25, p50, p75, p90, p95)
            p10 = _quantile(sorted_vals, 0.10)
            p25 = _quantile(sorted_vals, 0.25)
            p50 = _quantile(sorted_vals, 0.50)
            p75 = _quantile(sorted_vals, 0.75)
            p90 = _quantile(sorted_vals, 0.90)
            p95 = _quantile(sorted_vals, 0.95)

            recent_5 = values[-5:] if len(values) >= 5 else values
            recent_20 = values[-20:] if len(values) >= 20 else values
            avg_5d = statistics.mean(recent_5)
            avg_20d = statistics.mean(recent_20)

            vol_20d = 0.0
            if len(recent_20) >= 2 and avg_20d > 0:
                vol_20d = statistics.stdev(recent_20) / avg_20d * 100

            trend = _trend_label(latest_value, avg_5d, avg_20d)

            max_idx = values.index(max_val)
            min_idx = values.index(min_val)
            days_from_high = (dates[-1] - dates[max_idx]).days
            days_from_low = (dates[-1] - dates[min_idx]).days

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO indicator_context_snapshot
                        (snapshot_date, indicator_type, region, family, direction, lookback_days, sample_size,
                         latest_value, latest_value_date,
                         min_val, max_val, avg_val, median_val, stddev_val,
                         p10, p25, p50, p75, p90, p95,
                         avg_5d, avg_20d, volatility_20d_pct, trend_label,
                         days_from_high, days_from_low)
                    VALUES (%s, %s, %s, %s, %s, 90, %s,
                            %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s)
                    ON CONFLICT (snapshot_date, indicator_type, region) DO UPDATE SET
                        sample_size = EXCLUDED.sample_size,
                        latest_value = EXCLUDED.latest_value,
                        latest_value_date = EXCLUDED.latest_value_date,
                        min_val = EXCLUDED.min_val,
                        max_val = EXCLUDED.max_val,
                        avg_val = EXCLUDED.avg_val,
                        median_val = EXCLUDED.median_val,
                        stddev_val = EXCLUDED.stddev_val,
                        p10 = EXCLUDED.p10,
                        p25 = EXCLUDED.p25,
                        p50 = EXCLUDED.p50,
                        p75 = EXCLUDED.p75,
                        p90 = EXCLUDED.p90,
                        p95 = EXCLUDED.p95,
                        avg_5d = EXCLUDED.avg_5d,
                        avg_20d = EXCLUDED.avg_20d,
                        volatility_20d_pct = EXCLUDED.volatility_20d_pct,
                        trend_label = EXCLUDED.trend_label,
                        days_from_high = EXCLUDED.days_from_high,
                        days_from_low = EXCLUDED.days_from_low
                """, (
                    today, indicator_type, region, family, direction, sample_size,
                    latest_value, latest_value_date,
                    min_val, max_val, avg_val, median_val, stddev_val,
                    p10, p25, p50, p75, p90, p95,
                    avg_5d, avg_20d, vol_20d, trend,
                    days_from_high, days_from_low,
                ))
            upserted += 1

        conn.commit()

    logger.info(f"snapshot upsert 완료: {upserted}건 성공 / {skipped}건 스킵 (표본 부족) / 전체 {len(TARGETS)}")
    register_table_lineage_async("indicator_context_snapshot", source_tables=["macro_indicators"])
    return {"upserted": upserted, "skipped": skipped, "total": len(TARGETS)}


default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="10_indicator_context_snapshot_daily",
    default_args=default_args,
    description="지표 시장 맥락 사전 계산 (체크리스트 모니터링용)",
    schedule_interval="0 17 * * 1-5",  # 평일 17:00 KST (한국 장 마감 + 여유)
    catchup=False,
    tags=["analytics", "snapshot", "daily"],
) as dag:

    compute_task = PythonOperator(
        task_id="compute_snapshot",
        python_callable=compute_snapshot,
    )
