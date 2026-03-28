"""
[09_analytics_stock_daily]
Gold layer: stock_price_1d + stock_indicators + consensus_estimates + stock_info
→ analytics_stock_daily (ticker, trade_date) 와이드 테이블

- 복잡한 멀티조인 제거 — 단일 테이블로 시세/기술지표/컨센서스 조회 가능
- 증분 적재: analytics_stock_daily 마지막 날짜 이후 데이터만 처리
- 초기 적재 시작: stock_indicators 최초 날짜 (2025-06-24)
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta, date
from utils.db import get_pg_conn
from utils.config import PG_CONN_INFO
from utils.lineage import register_table_lineage_async
import logging

logger = logging.getLogger(__name__)

INDICATORS_START = date(2025, 6, 24)   # stock_indicators 최초 데이터
BATCH_DAYS = 30                         # 한 번에 처리할 날짜 범위 (일)


UPSERT_SQL = """
INSERT INTO analytics_stock_daily (
    ticker, trade_date,
    stock_name, market_type, market_value,
    open, high, low, close, volume, change_pct,
    after_hours_close, after_hours_change_pct,
    foreign_buy_volume, institution_buy_volume, individual_buy_volume, foreign_ownership_pct,
    ma5, ma20, ma60, ma120, ma200,
    rsi14, macd, macd_signal, macd_hist,
    bb_upper, bb_middle, bb_lower, bb_pctb,
    atr14, golden_cross, death_cross,
    high_52w, low_52w, pct_from_52w_high, volume_ma20, volume_ratio,
    analyst_rating, target_price, analyst_count,
    est_eps, est_per, est_pbr, est_roe,
    updated_at
)
WITH
-- 컨센서스: 티커별 최신 1건 (올해 또는 가장 최신 estimate_year)
latest_consensus AS (
    SELECT DISTINCT ON (ticker)
        ticker,
        rating          AS analyst_rating,
        target_price,
        analyst_count,
        est_eps,
        est_per,
        est_pbr,
        est_roe
    FROM consensus_estimates
    ORDER BY ticker, estimate_year DESC, collected_at DESC
),
-- 동일 (ticker, date) 중복 제거: 가장 최신 timestamp 1건만 사용
deduped AS (
    SELECT DISTINCT ON (ticker, DATE(timestamp))
        ticker,
        DATE(timestamp)         AS trade_date,
        timestamp,
        open, high, low, close, volume,
        after_hours_close,
        after_hours_change_pct,
        foreign_buy_volume,
        institution_buy_volume,
        individual_buy_volume,
        foreign_ownership_pct
    FROM stock_price_1d
    WHERE DATE(timestamp) >= %(lookback_date)s
      AND DATE(timestamp) <= %(end_date)s
    ORDER BY ticker, DATE(timestamp), timestamp DESC
),
-- 전일 종가: change_pct 계산용
price_with_prev AS (
    SELECT
        d.ticker,
        d.trade_date,
        si.stock_name,
        si.market_type,
        si.market_value,
        d.open, d.high, d.low, d.close, d.volume,
        -- 극단적 등락률(페니스톡 등) NULL 처리
        CASE
            WHEN ABS(
                (d.close - LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.trade_date))
                / NULLIF(LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.trade_date), 0) * 100
            ) > 9999 THEN NULL
            ELSE ROUND(
                ((d.close - LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.trade_date))
                 / NULLIF(LAG(d.close) OVER (PARTITION BY d.ticker ORDER BY d.trade_date), 0) * 100
                )::numeric, 4
            )
        END                                                                AS change_pct,
        d.after_hours_close,
        d.after_hours_change_pct::numeric,
        d.foreign_buy_volume,
        d.institution_buy_volume,
        d.individual_buy_volume,
        d.foreign_ownership_pct
    FROM deduped d
    JOIN stock_info si ON d.ticker = si.ticker
)
SELECT
    p.ticker,
    p.trade_date,
    p.stock_name,
    p.market_type,
    p.market_value,
    p.open, p.high, p.low, p.close, p.volume, p.change_pct,
    p.after_hours_close,
    p.after_hours_change_pct,
    p.foreign_buy_volume,
    p.institution_buy_volume,
    p.individual_buy_volume,
    p.foreign_ownership_pct,
    -- 기술적 지표
    ind.ma5, ind.ma20, ind.ma60, ind.ma120, ind.ma200,
    ind.rsi14, ind.macd, ind.macd_signal, ind.macd_hist,
    ind.bb_upper, ind.bb_middle, ind.bb_lower, ind.bb_pctb,
    ind.atr14, ind.golden_cross, ind.death_cross,
    ind.high_52w, ind.low_52w, ind.pct_from_52w_high,
    ind.volume_ma20, ind.volume_ratio,
    -- 컨센서스
    ce.analyst_rating, ce.target_price, ce.analyst_count,
    ce.est_eps, ce.est_per, ce.est_pbr, ce.est_roe,
    NOW()
FROM price_with_prev p
LEFT JOIN stock_indicators ind
    ON p.ticker = ind.ticker AND p.trade_date = ind.trade_date
LEFT JOIN latest_consensus ce ON p.ticker = ce.ticker
WHERE p.trade_date >= %(start_date)s    -- start_date부터만 INSERT
ON CONFLICT (ticker, trade_date) DO UPDATE SET
    stock_name              = EXCLUDED.stock_name,
    market_type             = EXCLUDED.market_type,
    market_value            = EXCLUDED.market_value,
    open                    = EXCLUDED.open,
    high                    = EXCLUDED.high,
    low                     = EXCLUDED.low,
    close                   = EXCLUDED.close,
    volume                  = EXCLUDED.volume,
    change_pct              = EXCLUDED.change_pct,
    after_hours_close       = EXCLUDED.after_hours_close,
    after_hours_change_pct  = EXCLUDED.after_hours_change_pct,
    foreign_buy_volume      = EXCLUDED.foreign_buy_volume,
    institution_buy_volume  = EXCLUDED.institution_buy_volume,
    individual_buy_volume   = EXCLUDED.individual_buy_volume,
    foreign_ownership_pct   = EXCLUDED.foreign_ownership_pct,
    ma5                     = EXCLUDED.ma5,
    ma20                    = EXCLUDED.ma20,
    ma60                    = EXCLUDED.ma60,
    ma120                   = EXCLUDED.ma120,
    ma200                   = EXCLUDED.ma200,
    rsi14                   = EXCLUDED.rsi14,
    macd                    = EXCLUDED.macd,
    macd_signal             = EXCLUDED.macd_signal,
    macd_hist               = EXCLUDED.macd_hist,
    bb_upper                = EXCLUDED.bb_upper,
    bb_middle               = EXCLUDED.bb_middle,
    bb_lower                = EXCLUDED.bb_lower,
    bb_pctb                 = EXCLUDED.bb_pctb,
    atr14                   = EXCLUDED.atr14,
    golden_cross            = EXCLUDED.golden_cross,
    death_cross             = EXCLUDED.death_cross,
    high_52w                = EXCLUDED.high_52w,
    low_52w                 = EXCLUDED.low_52w,
    pct_from_52w_high       = EXCLUDED.pct_from_52w_high,
    volume_ma20             = EXCLUDED.volume_ma20,
    volume_ratio            = EXCLUDED.volume_ratio,
    analyst_rating          = EXCLUDED.analyst_rating,
    target_price            = EXCLUDED.target_price,
    analyst_count           = EXCLUDED.analyst_count,
    est_eps                 = EXCLUDED.est_eps,
    est_per                 = EXCLUDED.est_per,
    est_pbr                 = EXCLUDED.est_pbr,
    est_roe                 = EXCLUDED.est_roe,
    updated_at              = NOW()
"""


def build_analytics_stock(**context):
    """stock_price_1d + indicators + consensus → analytics_stock_daily 증분 적재"""
    today = datetime.utcnow().date()

    with get_pg_conn(PG_CONN_INFO) as conn:
        # 마지막 적재일 조회
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(trade_date) FROM analytics_stock_daily")
            last_date = cur.fetchone()[0]

        if last_date is None:
            start_date = INDICATORS_START
        else:
            start_date = last_date  # 당일 재처리 (장 마감 후 지표 업데이트 반영)

        total_inserted = 0
        batch_start = start_date

        while batch_start <= today:
            batch_end = min(batch_start + timedelta(days=BATCH_DAYS - 1), today)
            # change_pct 계산을 위해 하루 전 데이터도 조회
            lookback = batch_start - timedelta(days=3)

            logger.info(f"배치 처리: {batch_start} ~ {batch_end}")

            with conn.cursor() as cur:
                cur.execute(UPSERT_SQL, {
                    "start_date":    batch_start,
                    "end_date":      batch_end,
                    "lookback_date": lookback,
                })
                row_count = cur.rowcount
                total_inserted += row_count

            conn.commit()
            logger.info(f"  → {row_count}행 upsert")
            batch_start = batch_end + timedelta(days=1)

        logger.info(f"analytics_stock_daily 총 {total_inserted}행 완료")

    register_table_lineage_async(
        "analytics_stock_daily",
        source_tables=["stock_price_1d", "stock_indicators", "consensus_estimates", "stock_info"]
    )


default_args = {
    "owner": "airflow",
    "start_date": datetime(2025, 6, 24),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="09_analytics_stock_daily",
    default_args=default_args,
    description="Gold layer: stock_price_1d + indicators + consensus → analytics_stock_daily",
    schedule_interval="30 20 * * 1-5",   # 평일 20:30 KST (지표 계산 DAG 완료 후)
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
    tags=["gold", "market", "daily"],
) as dag:

    build_task = PythonOperator(
        task_id="build_analytics_stock",
        python_callable=build_analytics_stock,
        execution_timeout=timedelta(hours=1, minutes=30),
    )
