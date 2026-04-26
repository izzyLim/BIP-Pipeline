"""
[03_indicator_kr_daily]
한국 주식 기술적 지표 일일 계산 (KOSPI/KOSDAQ)
- stock_info.is_active = TRUE 종목 중 .KS/.KQ 티커 대상
- MA5~200, EMA, MACD, RSI14, Bollinger Bands, Stochastic, ATR14, 52주 고저
- KST 기준 날짜로 trade_date 산정
- 실행 조건: 02_price_kr_ohlcv_daily 완료 후
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import logging
from typing import List

from indicators.calculator import calculate_all_indicators
from utils.db import get_pg_conn
from utils.config import PG_CONN_INFO
from utils.lineage import register_table_lineage_async

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
LOOKBACK_DAYS = 300
NUM_BATCHES = 30  # KOSPI+KOSDAQ 약 2,500종목 / 100 = 25배치 (여유 포함)


def get_kr_active_tickers() -> List[str]:
    """한국 활성 종목 목록 조회 (is_active 컬럼 기준)"""
    with get_pg_conn(PG_CONN_INFO) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ticker FROM stock_info
                WHERE active = TRUE
                  AND (ticker LIKE %s OR ticker LIKE %s)
                ORDER BY ticker
            """, ('%.KS', '%.KQ'))
            return [row[0] for row in cur.fetchall()]


def get_kr_stock_data(ticker: str, lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """한국 종목 가격 데이터 조회 (KST 기준 날짜)"""
    with get_pg_conn(PG_CONN_INFO) as conn:
        query = """
            SELECT
                DATE(timestamp_kst) AS trade_date,
                open, high, low, close, volume
            FROM stock_price_1d
            WHERE ticker = %s
              AND timestamp_kst >= NOW() - INTERVAL '%s days'
            ORDER BY timestamp_kst
        """
        return pd.read_sql(query, conn, params=(ticker, lookback_days))


def _prepare_indicator_params(ind: dict) -> dict:
    """DB 저장용 파라미터 준비 (NaN → None, numpy 타입 변환)"""
    result = {}
    for key, value in ind.items():
        if isinstance(value, float) and (pd.isna(value) or not np.isfinite(value)):
            result[key] = None
        elif pd.isna(value) if not isinstance(value, (list, dict)) else False:
            result[key] = None
        elif isinstance(value, (np.integer, np.floating)):
            result[key] = float(value) if np.isfinite(value) else None
        elif isinstance(value, np.bool_):
            result[key] = bool(value)
        else:
            result[key] = value
    return result


def save_kr_indicators_to_db(indicators: List[dict]):
    """한국 주식 지표 DB 저장"""
    with get_pg_conn(PG_CONN_INFO) as conn:
        with conn.cursor() as cur:
            for ind in indicators:
                try:
                    cur.execute("""
                        INSERT INTO stock_indicators (
                            ticker, trade_date,
                            open, high, low, close, volume,
                            ma5, ma10, ma20, ma60, ma120, ma200,
                            ema12, ema26,
                            macd, macd_signal, macd_hist,
                            rsi14,
                            bb_upper, bb_middle, bb_lower, bb_width, bb_pctb,
                            stoch_k, stoch_d,
                            volume_ma5, volume_ma20, volume_ratio, volume_momentum,
                            price_change_1d, price_change_1w, price_change_1m, price_change_1y, price_momentum,
                            atr14,
                            trend_ma, golden_cross, death_cross,
                            high_52w, low_52w, pct_from_52w_high, pct_from_52w_low,
                            vcp_contraction, vcp_vol_dry
                        ) VALUES (
                            %(ticker)s, %(trade_date)s,
                            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s,
                            %(ma5)s, %(ma10)s, %(ma20)s, %(ma60)s, %(ma120)s, %(ma200)s,
                            %(ema12)s, %(ema26)s,
                            %(macd)s, %(macd_signal)s, %(macd_hist)s,
                            %(rsi14)s,
                            %(bb_upper)s, %(bb_middle)s, %(bb_lower)s, %(bb_width)s, %(bb_pctb)s,
                            %(stoch_k)s, %(stoch_d)s,
                            %(volume_ma5)s, %(volume_ma20)s, %(volume_ratio)s, %(volume_momentum)s,
                            %(price_change_1d)s, %(price_change_1w)s, %(price_change_1m)s, %(price_change_1y)s, %(price_momentum)s,
                            %(atr14)s,
                            %(trend_ma)s, %(golden_cross)s, %(death_cross)s,
                            %(high_52w)s, %(low_52w)s, %(pct_from_52w_high)s, %(pct_from_52w_low)s,
                            %(vcp_contraction)s, %(vcp_vol_dry)s
                        )
                        ON CONFLICT (ticker, trade_date) DO UPDATE SET
                            open = EXCLUDED.open, high = EXCLUDED.high,
                            low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume,
                            ma5 = EXCLUDED.ma5, ma10 = EXCLUDED.ma10, ma20 = EXCLUDED.ma20,
                            ma60 = EXCLUDED.ma60, ma120 = EXCLUDED.ma120, ma200 = EXCLUDED.ma200,
                            ema12 = EXCLUDED.ema12, ema26 = EXCLUDED.ema26,
                            macd = EXCLUDED.macd, macd_signal = EXCLUDED.macd_signal,
                            macd_hist = EXCLUDED.macd_hist, rsi14 = EXCLUDED.rsi14,
                            bb_upper = EXCLUDED.bb_upper, bb_middle = EXCLUDED.bb_middle,
                            bb_lower = EXCLUDED.bb_lower, bb_width = EXCLUDED.bb_width,
                            bb_pctb = EXCLUDED.bb_pctb, stoch_k = EXCLUDED.stoch_k,
                            stoch_d = EXCLUDED.stoch_d,
                            volume_ma5 = EXCLUDED.volume_ma5,
                            volume_ma20 = EXCLUDED.volume_ma20,
                            volume_ratio = EXCLUDED.volume_ratio,
                            volume_momentum = EXCLUDED.volume_momentum,
                            price_change_1d = EXCLUDED.price_change_1d,
                            price_change_1w = EXCLUDED.price_change_1w,
                            price_change_1m = EXCLUDED.price_change_1m,
                            price_change_1y = EXCLUDED.price_change_1y,
                            price_momentum = EXCLUDED.price_momentum,
                            atr14 = EXCLUDED.atr14,
                            trend_ma = EXCLUDED.trend_ma, golden_cross = EXCLUDED.golden_cross,
                            death_cross = EXCLUDED.death_cross, high_52w = EXCLUDED.high_52w,
                            low_52w = EXCLUDED.low_52w,
                            pct_from_52w_high = EXCLUDED.pct_from_52w_high,
                            pct_from_52w_low = EXCLUDED.pct_from_52w_low,
                            vcp_contraction = EXCLUDED.vcp_contraction,
                            vcp_vol_dry = EXCLUDED.vcp_vol_dry
                    """, _prepare_indicator_params(ind))
                except Exception as e:
                    logger.error(f"{ind.get('ticker')} KR 지표 저장 실패: {e}")
            conn.commit()


def calculate_kr_indicators_batch(batch_num: int = 0, **context):
    """한국 주식 배치 단위 지표 계산 및 저장"""
    tickers = get_kr_active_tickers()
    total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE

    start_idx = batch_num * BATCH_SIZE
    end_idx = min(start_idx + BATCH_SIZE, len(tickers))

    if start_idx >= len(tickers):
        logger.info(f"KR Batch {batch_num}: 범위 초과 (전체 {total_batches}배치)")
        return

    batch_tickers = tickers[start_idx:end_idx]
    logger.info(f"KR Batch {batch_num + 1}/{total_batches}: {len(batch_tickers)}개 종목")

    results = []
    errors = []

    for ticker in batch_tickers:
        try:
            df = get_kr_stock_data(ticker)
            if df.empty or len(df) < 30:
                continue

            df_with_indicators = calculate_all_indicators(df)
            latest = df_with_indicators.iloc[-1].copy()
            latest["ticker"] = ticker
            results.append(latest.to_dict())

        except Exception as e:
            errors.append(ticker)
            logger.error(f"{ticker} KR 지표 계산 실패: {e}")

    if errors:
        logger.warning(f"KR Batch {batch_num}: {len(errors)}개 종목 실패")
    if results:
        save_kr_indicators_to_db(results)
        logger.info(f"KR Batch {batch_num}: {len(results)}개 저장 완료")
        register_table_lineage_async(
            "stock_indicators",
            source_tables=["stock_price_1d", "stock_info"],
        )

    return {"processed": len(results), "errors": len(errors)}


default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="03_indicator_kr_daily",
    default_args=default_args,
    description="한국 종목 기술적 지표 계산 (KOSPI/KOSDAQ, MA·RSI·MACD·Bollinger 등)",
    schedule_interval="30 16 * * 1-5",  # 평일 16:30 KST (02_price_kr_ohlcv_daily 완료 후)
    catchup=False,
    max_active_runs=1,
    max_active_tasks=7,  # 30배치 중 동시 7개씩
    tags=["indicator", "daily", "KR", "KOSPI", "KOSDAQ"],
) as dag:

    indicator_tasks = []
    for i in range(NUM_BATCHES):
        task = PythonOperator(
            task_id=f"calculate_kr_batch_{i:02d}",
            python_callable=calculate_kr_indicators_batch,
            op_kwargs={"batch_num": i},
        )
        indicator_tasks.append(task)

    # 모든 배치 병렬 실행 (의존성 없음)
    indicator_tasks
