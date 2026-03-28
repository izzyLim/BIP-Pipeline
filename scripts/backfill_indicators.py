"""
기술 지표 히스토리컬 백필 스크립트
전체 종목에 대해 최근 N일간의 지표를 계산하여 저장
"""

import sys
sys.path.insert(0, 'airflow/dags')

import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timedelta
import logging
from typing import List, Dict
import time

from indicators.calculator import calculate_all_indicators

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "user",
    "password": "pw1234",
    "dbname": "stockdb"
}

LOOKBACK_DAYS = 300  # 지표 계산용 과거 데이터
SAVE_DAYS = 1        # 저장할 최근 일수 (최신 데이터만)
BATCH_SIZE = 100     # 한 번에 처리할 종목 수


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def get_active_tickers(skip_existing: bool = True) -> List[str]:
    """활성 종목 목록"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if skip_existing:
                # 이미 처리된 종목 제외
                cur.execute("""
                    SELECT si.ticker FROM stock_info si
                    LEFT JOIN stock_indicators ind ON si.ticker = ind.ticker
                    WHERE si.active = true AND ind.ticker IS NULL
                    ORDER BY si.ticker
                """)
            else:
                cur.execute("""
                    SELECT ticker FROM stock_info
                    WHERE active = true
                    ORDER BY ticker
                """)
            return [row[0] for row in cur.fetchall()]


def get_stock_data(conn, ticker: str) -> pd.DataFrame:
    """종목 가격 데이터 조회"""
    query = """
        SELECT
            DATE(timestamp_ny) as trade_date,
            open::float, high::float, low::float, close::float, volume
        FROM stock_price_1d
        WHERE ticker = %s
          AND timestamp_ny >= NOW() - INTERVAL '%s days'
        ORDER BY timestamp_ny
    """
    return pd.read_sql(query, conn, params=(ticker, LOOKBACK_DAYS))


def prepare_row(ticker: str, row: pd.Series) -> tuple:
    """DB 저장용 튜플 준비"""
    def safe_float(val):
        if pd.isna(val) or (isinstance(val, float) and not np.isfinite(val)):
            return None
        return float(val)

    def safe_int(val):
        if pd.isna(val):
            return None
        return int(val)

    def safe_bool(val):
        if pd.isna(val):
            return None
        return bool(val)

    return (
        ticker,
        row['trade_date'],
        safe_float(row.get('open')),
        safe_float(row.get('high')),
        safe_float(row.get('low')),
        safe_float(row.get('close')),
        safe_int(row.get('volume')),
        safe_float(row.get('ma5')),
        safe_float(row.get('ma10')),
        safe_float(row.get('ma20')),
        safe_float(row.get('ma60')),
        safe_float(row.get('ma120')),
        safe_float(row.get('ma200')),
        safe_float(row.get('ema12')),
        safe_float(row.get('ema26')),
        safe_float(row.get('macd')),
        safe_float(row.get('macd_signal')),
        safe_float(row.get('macd_hist')),
        safe_float(row.get('rsi14')),
        safe_float(row.get('bb_upper')),
        safe_float(row.get('bb_middle')),
        safe_float(row.get('bb_lower')),
        safe_float(row.get('bb_width')),
        safe_float(row.get('bb_pctb')),
        safe_float(row.get('stoch_k')),
        safe_float(row.get('stoch_d')),
        safe_int(row.get('volume_ma20')),
        safe_float(row.get('volume_ratio')),
        safe_float(row.get('atr14')),
        row.get('trend_ma') if pd.notna(row.get('trend_ma')) else None,
        safe_bool(row.get('golden_cross')),
        safe_bool(row.get('death_cross')),
        safe_float(row.get('high_52w')),
        safe_float(row.get('low_52w')),
        safe_float(row.get('pct_from_52w_high')),
        safe_float(row.get('pct_from_52w_low')),
    )


def save_indicators_batch(conn, records: List[tuple]):
    """배치로 지표 저장"""
    if not records:
        return

    # 중복 제거 (ticker, trade_date 기준)
    seen = set()
    unique_records = []
    for r in records:
        key = (r[0], r[1])  # ticker, trade_date
        if key not in seen:
            seen.add(key)
            unique_records.append(r)
    records = unique_records

    insert_query = """
        INSERT INTO stock_indicators (
            ticker, trade_date,
            open, high, low, close, volume,
            ma5, ma10, ma20, ma60, ma120, ma200,
            ema12, ema26,
            macd, macd_signal, macd_hist,
            rsi14,
            bb_upper, bb_middle, bb_lower, bb_width, bb_pctb,
            stoch_k, stoch_d,
            volume_ma20, volume_ratio,
            atr14,
            trend_ma, golden_cross, death_cross,
            high_52w, low_52w, pct_from_52w_high, pct_from_52w_low
        ) VALUES %s
        ON CONFLICT (ticker, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            ma5 = EXCLUDED.ma5,
            ma10 = EXCLUDED.ma10,
            ma20 = EXCLUDED.ma20,
            ma60 = EXCLUDED.ma60,
            ma120 = EXCLUDED.ma120,
            ma200 = EXCLUDED.ma200,
            ema12 = EXCLUDED.ema12,
            ema26 = EXCLUDED.ema26,
            macd = EXCLUDED.macd,
            macd_signal = EXCLUDED.macd_signal,
            macd_hist = EXCLUDED.macd_hist,
            rsi14 = EXCLUDED.rsi14,
            bb_upper = EXCLUDED.bb_upper,
            bb_middle = EXCLUDED.bb_middle,
            bb_lower = EXCLUDED.bb_lower,
            bb_width = EXCLUDED.bb_width,
            bb_pctb = EXCLUDED.bb_pctb,
            stoch_k = EXCLUDED.stoch_k,
            stoch_d = EXCLUDED.stoch_d,
            volume_ma20 = EXCLUDED.volume_ma20,
            volume_ratio = EXCLUDED.volume_ratio,
            atr14 = EXCLUDED.atr14,
            trend_ma = EXCLUDED.trend_ma,
            golden_cross = EXCLUDED.golden_cross,
            death_cross = EXCLUDED.death_cross,
            high_52w = EXCLUDED.high_52w,
            low_52w = EXCLUDED.low_52w,
            pct_from_52w_high = EXCLUDED.pct_from_52w_high,
            pct_from_52w_low = EXCLUDED.pct_from_52w_low
    """

    with conn.cursor() as cur:
        execute_values(cur, insert_query, records)
    conn.commit()


def process_ticker(conn, ticker: str) -> int:
    """단일 종목 처리"""
    try:
        df = get_stock_data(conn, ticker)

        if df.empty or len(df) < 30:
            return 0

        # 지표 계산
        df_ind = calculate_all_indicators(df)

        # 최근 N일만 저장
        df_recent = df_ind.tail(SAVE_DAYS)

        records = [prepare_row(ticker, row) for _, row in df_recent.iterrows()]
        return records

    except Exception as e:
        logger.error(f"Error processing {ticker}: {e}")
        return []


def main():
    """메인 실행"""
    start_time = time.time()

    tickers = get_active_tickers()
    total = len(tickers)
    logger.info(f"총 {total}개 종목 처리 시작")

    processed = 0
    saved_records = 0
    errors = 0

    conn = get_connection()

    try:
        for i in range(0, total, BATCH_SIZE):
            batch_tickers = tickers[i:i+BATCH_SIZE]
            batch_records = []

            for ticker in batch_tickers:
                records = process_ticker(conn, ticker)
                if records:
                    batch_records.extend(records)
                    processed += 1
                else:
                    errors += 1

            # 배치 저장
            if batch_records:
                save_indicators_batch(conn, batch_records)
                saved_records += len(batch_records)

            # 진행 상황 출력
            progress = (i + len(batch_tickers)) / total * 100
            elapsed = time.time() - start_time
            eta = elapsed / (i + len(batch_tickers)) * (total - i - len(batch_tickers)) if i > 0 else 0

            logger.info(
                f"진행: {i + len(batch_tickers)}/{total} ({progress:.1f}%) | "
                f"저장: {saved_records:,}건 | "
                f"경과: {elapsed:.0f}초 | ETA: {eta:.0f}초"
            )

    finally:
        conn.close()

    elapsed = time.time() - start_time
    logger.info(f"완료! 처리: {processed}, 에러: {errors}, 저장: {saved_records:,}건, 소요: {elapsed:.1f}초")


if __name__ == "__main__":
    main()
