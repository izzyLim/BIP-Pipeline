"""
매크로 데이터 수집기
- DB에서 시장 데이터 조회
- KOSPI 200 / S&P 500 종목 데이터
- 투자자 동향, 반도체 가격 등
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pandas as pd
from sqlalchemy import create_engine, text


# DB 연결
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://user:pw1234@bip-postgres:5432/stockdb"
)


def get_engine():
    return create_engine(DATABASE_URL)


def get_latest_trading_date(engine, market: str = "KS") -> Optional[str]:
    """최근 거래일 조회 (주말/휴일 제외)"""
    suffix = f"%.{market}"
    query = text("""
        SELECT MAX(timestamp::date) as latest_date
        FROM stock_price_1d
        WHERE ticker LIKE :suffix
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"suffix": suffix}).fetchone()
        return str(result[0]) if result and result[0] else None


def get_korea_market_data(date: Optional[str] = None) -> Dict[str, Any]:
    """
    한국 시장 데이터 수집 (KOSPI 시총 상위 200)

    Returns:
        {
            "date": "2026-03-14",
            "stocks": [
                {"ticker": "005930.KS", "name": "삼성전자", "sector": "반도체",
                 "market_cap": 400조, "close": 58000, "change_pct": 1.5},
                ...
            ],
            "sector_summary": [
                {"sector": "반도체", "change_pct": 1.8, "market_cap": 500조},
                ...
            ]
        }
    """
    engine = get_engine()

    # 최근 거래일 조회
    if date is None:
        date = get_latest_trading_date(engine, "KS")

    if not date:
        return {"date": None, "stocks": [], "sector_summary": []}

    # KOSPI 시총 상위 200 종목 + 당일/전일 가격 데이터 (시간외 종가 우선)
    query = text("""
        WITH top200 AS (
            SELECT ticker, stock_name, industry_name as sector, market_value
            FROM stock_info
            WHERE market_type = 'KOSPI' AND active = true AND market_value IS NOT NULL
              AND stock_name NOT LIKE '%ETF%'
              AND stock_name NOT LIKE '%etf%'
            ORDER BY market_value DESC
            LIMIT 200
        ),
        -- 최근 2 거래일 목록
        recent_dates AS (
            SELECT DISTINCT timestamp::date as trade_date
            FROM stock_price_1d
            WHERE ticker LIKE '%.KS'
              AND timestamp::date <= CAST(:trade_date AS date)
            ORDER BY trade_date DESC
            LIMIT 2
        ),
        -- 당일 종가 (시간외 종가 우선, 없으면 정규장 종가)
        today_price AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                COALESCE(after_hours_close, close) as close,
                close as regular_close,
                after_hours_close
            FROM stock_price_1d
            WHERE ticker LIKE '%.KS'
              AND timestamp::date = (SELECT MAX(trade_date) FROM recent_dates)
            ORDER BY ticker, timestamp DESC
        ),
        -- 전일 종가 (시간외 종가 우선)
        prev_price AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                COALESCE(after_hours_close, close) as prev_close
            FROM stock_price_1d
            WHERE ticker LIKE '%.KS'
              AND timestamp::date = (SELECT MIN(trade_date) FROM recent_dates)
            ORDER BY ticker, timestamp DESC
        )
        SELECT
            t.ticker, t.stock_name, t.sector, t.market_value,
            tp.close, tp.regular_close, tp.after_hours_close, pp.prev_close,
            CASE WHEN pp.prev_close > 0
                 THEN ROUND(((tp.close - pp.prev_close) / pp.prev_close * 100)::numeric, 2)
                 ELSE 0 END as change_pct
        FROM top200 t
        LEFT JOIN today_price tp ON t.ticker = tp.ticker
        LEFT JOIN prev_price pp ON t.ticker = pp.ticker
        WHERE tp.close IS NOT NULL
        ORDER BY t.market_value DESC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"trade_date": date})

    if df.empty:
        return {"date": date, "stocks": [], "sector_summary": []}

    # 섹터별 집계
    sector_df = df.groupby("sector").agg({
        "market_value": "sum",
        "change_pct": "mean"
    }).reset_index()
    sector_df = sector_df.sort_values("market_value", ascending=False)

    return {
        "date": date,
        "stocks": df.to_dict("records"),
        "sector_summary": sector_df.to_dict("records"),
    }


def get_us_market_data(date: Optional[str] = None) -> Dict[str, Any]:
    """
    미국 시장 데이터 수집 (S&P 500)
    """
    engine = get_engine()

    # 최근 거래일 조회 (미국 종목은 .KS로 끝나지 않음)
    if date is None:
        date_query = text("""
            SELECT MAX(timestamp::date) as latest_date
            FROM stock_price_1d
            WHERE ticker IN (SELECT ticker FROM stock_info WHERE sector IS NOT NULL)
        """)
        with engine.connect() as conn:
            result = conn.execute(date_query).fetchone()
            date = str(result[0]) if result else None

    if not date:
        return {"date": None, "stocks": [], "sector_summary": []}

    # S&P 500 종목 + 당일/전일 가격 데이터
    query = text("""
        WITH sp500 AS (
            SELECT ticker, stock_name, sector, market_value
            FROM stock_info
            WHERE sector IS NOT NULL AND active = true
        ),
        -- 최근 2 거래일
        recent_dates AS (
            SELECT DISTINCT timestamp::date as trade_date
            FROM stock_price_1d
            WHERE ticker IN (SELECT ticker FROM sp500)
              AND timestamp::date <= CAST(:trade_date AS date)
            ORDER BY trade_date DESC
            LIMIT 2
        ),
        -- 당일 종가 (최근 거래일)
        today_price AS (
            SELECT DISTINCT ON (ticker) ticker, close
            FROM stock_price_1d
            WHERE ticker IN (SELECT ticker FROM sp500)
              AND timestamp::date = (SELECT MAX(trade_date) FROM recent_dates)
            ORDER BY ticker, timestamp DESC
        ),
        -- 전일 종가 (전 거래일)
        prev_price AS (
            SELECT DISTINCT ON (ticker) ticker, close as prev_close
            FROM stock_price_1d
            WHERE ticker IN (SELECT ticker FROM sp500)
              AND timestamp::date = (SELECT MIN(trade_date) FROM recent_dates)
            ORDER BY ticker, timestamp DESC
        )
        SELECT
            s.ticker, s.stock_name, s.sector, s.market_value,
            tp.close, pp.prev_close,
            CASE WHEN pp.prev_close > 0
                 THEN ROUND(((tp.close - pp.prev_close) / pp.prev_close * 100)::numeric, 2)
                 ELSE 0 END as change_pct
        FROM sp500 s
        LEFT JOIN today_price tp ON s.ticker = tp.ticker
        LEFT JOIN prev_price pp ON s.ticker = pp.ticker
        WHERE tp.close IS NOT NULL
        ORDER BY s.market_value DESC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"trade_date": date})

    if df.empty:
        return {"date": date, "stocks": [], "sector_summary": []}

    # 섹터별 집계
    sector_df = df.groupby("sector").agg({
        "market_value": "sum",
        "change_pct": "mean"
    }).reset_index()
    sector_df = sector_df.sort_values("market_value", ascending=False)

    return {
        "date": date,
        "stocks": df.to_dict("records"),
        "sector_summary": sector_df.to_dict("records"),
    }


def get_kosdaq_market_data(date: Optional[str] = None) -> Dict[str, Any]:
    """
    코스닥 시장 데이터 수집 (시총 상위 200)
    """
    engine = get_engine()

    if date is None:
        date = get_latest_trading_date(engine, "KQ")

    if not date:
        return {"date": None, "stocks": [], "sector_summary": []}

    query = text("""
        WITH top200 AS (
            SELECT ticker, stock_name, industry_name as sector, market_value
            FROM stock_info
            WHERE market_type = 'KOSDAQ' AND active = true AND market_value IS NOT NULL
              AND stock_name NOT LIKE '%ETF%'
              AND stock_name NOT LIKE '%etf%'
            ORDER BY market_value DESC
            LIMIT 200
        ),
        recent_dates AS (
            SELECT DISTINCT timestamp::date as trade_date
            FROM stock_price_1d
            WHERE ticker LIKE '%.KQ'
              AND timestamp::date <= CAST(:trade_date AS date)
            ORDER BY trade_date DESC
            LIMIT 2
        ),
        today_price AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                COALESCE(after_hours_close, close) as close
            FROM stock_price_1d
            WHERE ticker LIKE '%.KQ'
              AND timestamp::date = (SELECT MAX(trade_date) FROM recent_dates)
            ORDER BY ticker, timestamp DESC
        ),
        prev_price AS (
            SELECT DISTINCT ON (ticker)
                ticker,
                COALESCE(after_hours_close, close) as prev_close
            FROM stock_price_1d
            WHERE ticker LIKE '%.KQ'
              AND timestamp::date = (SELECT MIN(trade_date) FROM recent_dates)
            ORDER BY ticker, timestamp DESC
        )
        SELECT
            t.ticker, t.stock_name, t.sector, t.market_value,
            tp.close, pp.prev_close,
            CASE WHEN pp.prev_close > 0
                 THEN ROUND(((tp.close - pp.prev_close) / pp.prev_close * 100)::numeric, 2)
                 ELSE 0 END as change_pct
        FROM top200 t
        LEFT JOIN today_price tp ON t.ticker = tp.ticker
        LEFT JOIN prev_price pp ON t.ticker = pp.ticker
        WHERE tp.close IS NOT NULL
        ORDER BY t.market_value DESC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"trade_date": date})

    if df.empty:
        return {"date": date, "stocks": [], "sector_summary": []}

    sector_df = df.groupby("sector").agg({
        "market_value": "sum",
        "change_pct": "mean"
    }).reset_index()
    sector_df = sector_df.sort_values("market_value", ascending=False)

    return {
        "date": date,
        "stocks": df.to_dict("records"),
        "sector_summary": sector_df.to_dict("records"),
    }


def get_nasdaq_market_data(date: Optional[str] = None) -> Dict[str, Any]:
    """
    나스닥 시장 데이터 수집 (시총 상위 200)
    """
    engine = get_engine()

    if date is None:
        date_query = text("""
            SELECT MAX(timestamp::date) as latest_date
            FROM stock_price_1d
            WHERE ticker IN (SELECT ticker FROM stock_info WHERE market_type = 'NASDAQ')
        """)
        with engine.connect() as conn:
            result = conn.execute(date_query).fetchone()
            date = str(result[0]) if result else None

    if not date:
        return {"date": None, "stocks": [], "sector_summary": []}

    query = text("""
        WITH nasdaq200 AS (
            SELECT ticker, stock_name, sector, market_value
            FROM stock_info
            WHERE market_type = 'NASDAQ' AND active = true AND market_value IS NOT NULL
            ORDER BY market_value DESC
            LIMIT 200
        ),
        recent_dates AS (
            SELECT DISTINCT timestamp::date as trade_date
            FROM stock_price_1d
            WHERE ticker IN (SELECT ticker FROM nasdaq200)
              AND timestamp::date <= CAST(:trade_date AS date)
            ORDER BY trade_date DESC
            LIMIT 2
        ),
        today_price AS (
            SELECT DISTINCT ON (ticker) ticker, close
            FROM stock_price_1d
            WHERE ticker IN (SELECT ticker FROM nasdaq200)
              AND timestamp::date = (SELECT MAX(trade_date) FROM recent_dates)
            ORDER BY ticker, timestamp DESC
        ),
        prev_price AS (
            SELECT DISTINCT ON (ticker) ticker, close as prev_close
            FROM stock_price_1d
            WHERE ticker IN (SELECT ticker FROM nasdaq200)
              AND timestamp::date = (SELECT MIN(trade_date) FROM recent_dates)
            ORDER BY ticker, timestamp DESC
        )
        SELECT
            n.ticker, n.stock_name, n.sector, n.market_value,
            tp.close, pp.prev_close,
            CASE WHEN pp.prev_close > 0
                 THEN ROUND(((tp.close - pp.prev_close) / pp.prev_close * 100)::numeric, 2)
                 ELSE 0 END as change_pct
        FROM nasdaq200 n
        LEFT JOIN today_price tp ON n.ticker = tp.ticker
        LEFT JOIN prev_price pp ON n.ticker = pp.ticker
        WHERE tp.close IS NOT NULL
        ORDER BY n.market_value DESC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"trade_date": date})

    if df.empty:
        return {"date": date, "stocks": [], "sector_summary": []}

    sector_df = df.groupby("sector").agg({
        "market_value": "sum",
        "change_pct": "mean"
    }).reset_index()
    sector_df = sector_df.sort_values("market_value", ascending=False)

    return {
        "date": date,
        "stocks": df.to_dict("records"),
        "sector_summary": sector_df.to_dict("records"),
    }


def get_investor_flow(days: int = 5) -> List[Dict]:
    """
    투자자별 매매 동향 (외국인, 기관, 개인)
    """
    engine = get_engine()

    query = text("""
        SELECT
            timestamp::date as date,
            SUM(foreign_buy_volume * close) as foreign_amount,
            SUM(institution_buy_volume * close) as institution_amount,
            SUM(individual_buy_volume * close) as individual_amount
        FROM stock_price_1d
        WHERE ticker LIKE '%.KS'
          AND timestamp::date >= CURRENT_DATE - :days
        GROUP BY timestamp::date
        ORDER BY date DESC
        LIMIT :days
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"days": days})

    return df.to_dict("records") if not df.empty else []


def get_semiconductor_prices() -> List[Dict]:
    """
    반도체 가격 데이터 (DRAM, NAND) - 전일/1주/1개월/3개월 변동률 포함
    """
    engine = get_engine()

    # 최신 날짜의 주요 반도체 가격 조회 (추세 포함)
    query = text("""
        WITH latest AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type LIKE 'dram%' OR indicator_type LIKE 'nand%'
        ),
        prev AS (
            SELECT indicator_type, value
            FROM macro_indicators
            WHERE (indicator_type LIKE 'dram%' OR indicator_type LIKE 'nand%')
              AND indicator_date = (
                  SELECT MAX(indicator_date)
                  FROM macro_indicators
                  WHERE (indicator_type LIKE 'dram%' OR indicator_type LIKE 'nand%')
                    AND indicator_date < (SELECT max_date FROM latest)
              )
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE (indicator_type LIKE 'dram%' OR indicator_type LIKE 'nand%')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE (indicator_type LIKE 'dram%' OR indicator_type LIKE 'nand%')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE (indicator_type LIKE 'dram%' OR indicator_type LIKE 'nand%')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT
            t.indicator_type as product_type,
            t.value as price,
            CASE WHEN p.value > 0 THEN ROUND(((t.value - p.value) / p.value * 100)::numeric, 2) ELSE 0 END as price_change_pct,
            CASE WHEN w.value > 0 THEN ROUND(((t.value - w.value) / w.value * 100)::numeric, 2) ELSE NULL END as week_change_pct,
            CASE WHEN m.value > 0 THEN ROUND(((t.value - m.value) / m.value * 100)::numeric, 2) ELSE NULL END as month_change_pct,
            CASE WHEN q.value > 0 THEN ROUND(((t.value - q.value) / q.value * 100)::numeric, 2) ELSE NULL END as quarter_change_pct,
            t.indicator_date as date
        FROM macro_indicators t
        LEFT JOIN prev p ON t.indicator_type = p.indicator_type
        LEFT JOIN week_ago w ON t.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON t.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON t.indicator_type = q.indicator_type
        WHERE t.indicator_date = (SELECT max_date FROM latest)
          AND (t.indicator_type LIKE 'dram%' OR t.indicator_type LIKE 'nand%')
        ORDER BY t.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)
        return df.to_dict("records") if not df.empty else []
    except Exception as e:
        print(f"반도체 가격 조회 오류: {e}")
        return []


def get_index_summary() -> Dict[str, Any]:
    """
    주요 지수 요약 (KOSPI, KOSDAQ, S&P500, NASDAQ) - 전일/1주/1개월/3개월 변동률 포함
    """
    engine = get_engine()

    query = text("""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'stock_index_kospi'
        ),
        latest AS (
            SELECT indicator_type, value, change_pct
            FROM macro_indicators
            WHERE indicator_type IN ('stock_index_kospi', 'stock_index_kosdaq',
                                      'stock_index_sp500', 'stock_index_nasdaq')
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('stock_index_kospi', 'stock_index_kosdaq',
                                      'stock_index_sp500', 'stock_index_nasdaq')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('stock_index_kospi', 'stock_index_kosdaq',
                                      'stock_index_sp500', 'stock_index_nasdaq')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('stock_index_kospi', 'stock_index_kosdaq',
                                      'stock_index_sp500', 'stock_index_nasdaq')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT DISTINCT ON (l.indicator_type)
            l.indicator_type,
            l.value,
            l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)

        result = {}
        type_map = {
            'stock_index_kospi': 'kospi',
            'stock_index_kosdaq': 'kosdaq',
            'stock_index_sp500': 'sp500',
            'stock_index_nasdaq': 'nasdaq'
        }

        for _, row in df.iterrows():
            key = type_map.get(row['indicator_type'])
            if key:
                result[key] = {
                    "value": row['value'] or 0,
                    "change_pct": row['change_pct'] or 0,
                    "week_change_pct": round(row['week_change'], 2) if pd.notna(row['week_change']) else None,
                    "month_change_pct": round(row['month_change'], 2) if pd.notna(row['month_change']) else None,
                    "quarter_change_pct": round(row['quarter_change'], 2) if pd.notna(row['quarter_change']) else None,
                }

        return result
    except Exception:
        return {
            "kospi": {"value": 0, "change_pct": 0},
            "kosdaq": {"value": 0, "change_pct": 0},
            "sp500": {"value": 0, "change_pct": 0},
            "nasdaq": {"value": 0, "change_pct": 0},
        }


def get_exchange_rates() -> Dict[str, Any]:
    """환율 데이터 (USD/KRW) - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    query = text("""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'exchange_rate'
        ),
        latest AS (
            SELECT value, change_pct, indicator_date
            FROM macro_indicators
            WHERE indicator_type = 'exchange_rate'
              AND region = 'South Korea'
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT value
            FROM macro_indicators
            WHERE indicator_type = 'exchange_rate'
              AND region = 'South Korea'
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
            ORDER BY indicator_date DESC
            LIMIT 1
        ),
        month_ago AS (
            SELECT value
            FROM macro_indicators
            WHERE indicator_type = 'exchange_rate'
              AND region = 'South Korea'
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
            ORDER BY indicator_date DESC
            LIMIT 1
        ),
        quarter_ago AS (
            SELECT value
            FROM macro_indicators
            WHERE indicator_type = 'exchange_rate'
              AND region = 'South Korea'
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
            ORDER BY indicator_date DESC
            LIMIT 1
        )
        SELECT
            l.value,
            l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON true
        LEFT JOIN month_ago m ON true
        LEFT JOIN quarter_ago q ON true
    """)

    try:
        with engine.connect() as conn:
            result = conn.execute(query).fetchone()

        if result:
            return {
                "usd_krw": {
                    "value": result[0],
                    "change_pct": result[1] or 0,
                    "week_change_pct": round(result[2], 2) if result[2] else None,
                    "month_change_pct": round(result[3], 2) if result[3] else None,
                    "quarter_change_pct": round(result[4], 2) if result[4] else None,
                }
            }
        return {}
    except Exception:
        return {}


def get_fear_greed() -> Dict[str, Any]:
    """공포/탐욕 지수 (VIX, Fear & Greed, VKOSPI) - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    query = text("""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'vix'
        ),
        latest AS (
            SELECT indicator_type, value, change_pct
            FROM macro_indicators
            WHERE indicator_type IN ('vix', 'fear_greed_index', 'vkospi')
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('vix', 'fear_greed_index', 'vkospi')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('vix', 'fear_greed_index', 'vkospi')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('vix', 'fear_greed_index', 'vkospi')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT DISTINCT ON (l.indicator_type)
            l.indicator_type,
            l.value,
            l.change_pct,
            (l.value - w.value) as week_change,
            (l.value - m.value) as month_change,
            (l.value - q.value) as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)

        result = {}
        for _, row in df.iterrows():
            result[row['indicator_type']] = {
                "value": row['value'],
                "change_pct": row['change_pct'] or 0,
                "week_change": round(row['week_change'], 1) if pd.notna(row['week_change']) else None,
                "month_change": round(row['month_change'], 1) if pd.notna(row['month_change']) else None,
                "quarter_change": round(row['quarter_change'], 1) if pd.notna(row['quarter_change']) else None,
            }

        return result
    except Exception:
        return {}


def get_bitcoin() -> Dict[str, Any]:
    """비트코인 가격 (전일/1주/1개월/3개월 변동률 포함)"""
    engine = get_engine()

    query = text("""
        WITH latest AS (
            SELECT value, change_pct, indicator_date
            FROM macro_indicators
            WHERE indicator_type = 'crypto_btc'
            ORDER BY indicator_date DESC
            LIMIT 1
        ),
        week_ago AS (
            SELECT value
            FROM macro_indicators
            WHERE indicator_type = 'crypto_btc'
              AND indicator_date <= (SELECT indicator_date - INTERVAL '7 days' FROM latest)
            ORDER BY indicator_date DESC
            LIMIT 1
        ),
        month_ago AS (
            SELECT value
            FROM macro_indicators
            WHERE indicator_type = 'crypto_btc'
              AND indicator_date <= (SELECT indicator_date - INTERVAL '30 days' FROM latest)
            ORDER BY indicator_date DESC
            LIMIT 1
        ),
        quarter_ago AS (
            SELECT value
            FROM macro_indicators
            WHERE indicator_type = 'crypto_btc'
              AND indicator_date <= (SELECT indicator_date - INTERVAL '90 days' FROM latest)
            ORDER BY indicator_date DESC
            LIMIT 1
        )
        SELECT
            l.value,
            l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON true
        LEFT JOIN month_ago m ON true
        LEFT JOIN quarter_ago q ON true
    """)

    try:
        with engine.connect() as conn:
            result = conn.execute(query).fetchone()

        if result:
            return {
                "value": result[0],
                "change_pct": result[1] or 0,
                "week_change_pct": round(result[2], 2) if result[2] else None,
                "month_change_pct": round(result[3], 2) if result[3] else None,
                "quarter_change_pct": round(result[4], 2) if result[4] else None,
            }
        return {}
    except Exception as e:
        return {}


def get_commodities() -> Dict[str, Any]:
    """원자재 가격 (금, 유가) - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    query = text("""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'commodity_gold'
        ),
        latest AS (
            SELECT indicator_type, value, change_pct, indicator_date
            FROM macro_indicators
            WHERE indicator_type IN ('commodity_gold', 'commodity_oil')
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('commodity_gold', 'commodity_oil')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
              AND indicator_date >= (SELECT max_date - INTERVAL '10 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('commodity_gold', 'commodity_oil')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
              AND indicator_date >= (SELECT max_date - INTERVAL '35 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('commodity_gold', 'commodity_oil')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
              AND indicator_date >= (SELECT max_date - INTERVAL '95 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT DISTINCT ON (l.indicator_type)
            l.indicator_type,
            l.value,
            l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)

        result = {}
        for _, row in df.iterrows():
            key = row['indicator_type'].replace('commodity_', '')
            result[key] = {
                "value": row['value'],
                "change_pct": row['change_pct'] or 0,
                "week_change_pct": round(row['week_change'], 2) if pd.notna(row['week_change']) else None,
                "month_change_pct": round(row['month_change'], 2) if pd.notna(row['month_change']) else None,
                "quarter_change_pct": round(row['quarter_change'], 2) if pd.notna(row['quarter_change']) else None,
            }

        return result
    except Exception:
        return {}


def get_interest_rates() -> Dict[str, Any]:
    """금리 데이터 (미국 10년물, 한국 3년물) - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    query = text("""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'interest_rate_10y'
        ),
        latest AS (
            SELECT indicator_type, value, change_pct
            FROM macro_indicators
            WHERE indicator_type IN ('interest_rate_10y', 'korea_govt_3y')
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('interest_rate_10y', 'korea_govt_3y')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('interest_rate_10y', 'korea_govt_3y')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('interest_rate_10y', 'korea_govt_3y')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT
            l.indicator_type,
            l.value,
            l.change_pct,
            (l.value - w.value) as week_change,
            (l.value - m.value) as month_change,
            (l.value - q.value) as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)

        result = {}
        for _, row in df.iterrows():
            data = {
                "value": row['value'],
                "change_pct": row['change_pct'] or 0,
                "week_change": round(row['week_change'], 2) if pd.notna(row['week_change']) else None,
                "month_change": round(row['month_change'], 2) if pd.notna(row['month_change']) else None,
                "quarter_change": round(row['quarter_change'], 2) if pd.notna(row['quarter_change']) else None,
            }
            if row['indicator_type'] == 'interest_rate_10y':
                result['us_10y'] = data
            elif row['indicator_type'] == 'korea_govt_3y':
                result['kr_3y'] = data

        return result
    except Exception:
        return {}


def get_dollar_index() -> Dict[str, Any]:
    """달러 인덱스 (DXY) - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    query = text("""
        WITH latest AS (
            SELECT value, change_pct, indicator_date
            FROM macro_indicators
            WHERE indicator_type = 'dollar_index'
            ORDER BY indicator_date DESC
            LIMIT 1
        ),
        week_ago AS (
            SELECT value FROM macro_indicators
            WHERE indicator_type = 'dollar_index'
              AND indicator_date <= (SELECT indicator_date - INTERVAL '7 days' FROM latest)
            ORDER BY indicator_date DESC LIMIT 1
        ),
        month_ago AS (
            SELECT value FROM macro_indicators
            WHERE indicator_type = 'dollar_index'
              AND indicator_date <= (SELECT indicator_date - INTERVAL '30 days' FROM latest)
            ORDER BY indicator_date DESC LIMIT 1
        ),
        quarter_ago AS (
            SELECT value FROM macro_indicators
            WHERE indicator_type = 'dollar_index'
              AND indicator_date <= (SELECT indicator_date - INTERVAL '90 days' FROM latest)
            ORDER BY indicator_date DESC LIMIT 1
        )
        SELECT l.value, l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON true
        LEFT JOIN month_ago m ON true
        LEFT JOIN quarter_ago q ON true
    """)

    try:
        with engine.connect() as conn:
            result = conn.execute(query).fetchone()
        if result:
            return {
                "value": result[0],
                "change_pct": result[1] or 0,
                "week_change_pct": round(result[2], 2) if result[2] else None,
                "month_change_pct": round(result[3], 2) if result[3] else None,
                "quarter_change_pct": round(result[4], 2) if result[4] else None,
            }
        return {}
    except Exception:
        return {}


def get_semiconductor_index() -> Dict[str, Any]:
    """반도체 지수/ETF (SOX, SMH, SOXX) - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    query = text("""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'index_sox'
        ),
        latest AS (
            SELECT indicator_type, value, change_pct
            FROM macro_indicators
            WHERE indicator_type IN ('index_sox', 'etf_smh', 'etf_soxx')
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('index_sox', 'etf_smh', 'etf_soxx')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('index_sox', 'etf_smh', 'etf_soxx')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('index_sox', 'etf_smh', 'etf_soxx')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT
            l.indicator_type, l.value, l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)

        result = {}
        name_map = {'index_sox': 'sox', 'etf_smh': 'smh', 'etf_soxx': 'soxx'}
        for _, row in df.iterrows():
            key = name_map.get(row['indicator_type'], row['indicator_type'])
            result[key] = {
                "value": row['value'],
                "change_pct": row['change_pct'] or 0,
                "week_change_pct": round(row['week_change'], 2) if pd.notna(row['week_change']) else None,
                "month_change_pct": round(row['month_change'], 2) if pd.notna(row['month_change']) else None,
                "quarter_change_pct": round(row['quarter_change'], 2) if pd.notna(row['quarter_change']) else None,
            }
        return result
    except Exception:
        return {}


def get_global_indices() -> Dict[str, Any]:
    """글로벌 지수 (닛케이, 상하이, 유로스톡스) - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    query = text("""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'stock_index_nikkei'
        ),
        latest AS (
            SELECT indicator_type, value, change_pct
            FROM macro_indicators
            WHERE indicator_type IN ('stock_index_nikkei', 'stock_index_shanghai', 'stock_index_eurostoxx', 'stock_index_sensex')
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('stock_index_nikkei', 'stock_index_shanghai', 'stock_index_eurostoxx', 'stock_index_sensex')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('stock_index_nikkei', 'stock_index_shanghai', 'stock_index_eurostoxx', 'stock_index_sensex')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('stock_index_nikkei', 'stock_index_shanghai', 'stock_index_eurostoxx', 'stock_index_sensex')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT
            l.indicator_type, l.value, l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)

        result = {}
        name_map = {
            'stock_index_nikkei': 'nikkei',
            'stock_index_shanghai': 'shanghai',
            'stock_index_eurostoxx': 'eurostoxx',
            'stock_index_sensex': 'sensex'
        }
        for _, row in df.iterrows():
            key = name_map.get(row['indicator_type'], row['indicator_type'])
            result[key] = {
                "value": row['value'],
                "change_pct": row['change_pct'] or 0,
                "week_change_pct": round(row['week_change'], 2) if pd.notna(row['week_change']) else None,
                "month_change_pct": round(row['month_change'], 2) if pd.notna(row['month_change']) else None,
                "quarter_change_pct": round(row['quarter_change'], 2) if pd.notna(row['quarter_change']) else None,
            }
        return result
    except Exception:
        return {}


def get_us_sectors() -> Dict[str, Any]:
    """미국 섹터 지수 - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    sectors = [
        'sector_technology', 'sector_financials', 'sector_healthcare',
        'sector_consumer_disc', 'sector_communication', 'sector_industrials',
        'sector_consumer_staples', 'sector_energy', 'sector_materials',
        'sector_realestate', 'sector_utilities'
    ]
    sectors_str = "', '".join(sectors)

    query = text(f"""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'sector_technology'
        ),
        latest AS (
            SELECT indicator_type, value, change_pct
            FROM macro_indicators
            WHERE indicator_type IN ('{sectors_str}')
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('{sectors_str}')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('{sectors_str}')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('{sectors_str}')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT
            l.indicator_type, l.value, l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)

        result = {}
        name_map = {
            'sector_technology': 'technology',
            'sector_financials': 'financials',
            'sector_healthcare': 'healthcare',
            'sector_consumer_disc': 'consumer_disc',
            'sector_communication': 'communication',
            'sector_industrials': 'industrials',
            'sector_consumer_staples': 'consumer_staples',
            'sector_energy': 'energy',
            'sector_materials': 'materials',
            'sector_realestate': 'realestate',
            'sector_utilities': 'utilities'
        }
        for _, row in df.iterrows():
            key = name_map.get(row['indicator_type'], row['indicator_type'])
            result[key] = {
                "value": row['value'],
                "change_pct": row['change_pct'] or 0,
                "week_change_pct": round(row['week_change'], 2) if pd.notna(row['week_change']) else None,
                "month_change_pct": round(row['month_change'], 2) if pd.notna(row['month_change']) else None,
                "quarter_change_pct": round(row['quarter_change'], 2) if pd.notna(row['quarter_change']) else None,
            }
        return result
    except Exception:
        return {}


def get_kr_sectors() -> Dict[str, Any]:
    """한국 섹터 지수 - 전일/1주/1개월/3개월 변동률 포함"""
    engine = get_engine()

    sectors = [
        'sector_kr_semiconductor', 'sector_kr_auto', 'sector_kr_banks',
        'sector_kr_construction', 'sector_kr_consumer', 'sector_kr_energy',
        'sector_kr_healthcare', 'sector_kr_insurance', 'sector_kr_it', 'sector_kr_steel'
    ]
    sectors_str = "', '".join(sectors)

    query = text(f"""
        WITH latest_date AS (
            SELECT MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type = 'sector_kr_semiconductor'
        ),
        latest AS (
            SELECT indicator_type, value, change_pct
            FROM macro_indicators
            WHERE indicator_type IN ('{sectors_str}')
              AND indicator_date = (SELECT max_date FROM latest_date)
        ),
        week_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('{sectors_str}')
              AND indicator_date <= (SELECT max_date - INTERVAL '7 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('{sectors_str}')
              AND indicator_date <= (SELECT max_date - INTERVAL '30 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value FROM macro_indicators
            WHERE indicator_type IN ('{sectors_str}')
              AND indicator_date <= (SELECT max_date - INTERVAL '90 days' FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
        )
        SELECT
            l.indicator_type, l.value, l.change_pct,
            CASE WHEN w.value > 0 THEN ((l.value - w.value) / w.value * 100) ELSE NULL END as week_change,
            CASE WHEN m.value > 0 THEN ((l.value - m.value) / m.value * 100) ELSE NULL END as month_change,
            CASE WHEN q.value > 0 THEN ((l.value - q.value) / q.value * 100) ELSE NULL END as quarter_change
        FROM latest l
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn)

        result = {}
        name_map = {
            'sector_kr_semiconductor': '반도체',
            'sector_kr_auto': '자동차',
            'sector_kr_banks': '은행',
            'sector_kr_construction': '건설',
            'sector_kr_consumer': '소비재',
            'sector_kr_energy': '에너지',
            'sector_kr_healthcare': '헬스케어',
            'sector_kr_insurance': '보험',
            'sector_kr_it': 'IT',
            'sector_kr_steel': '철강'
        }
        for _, row in df.iterrows():
            key = name_map.get(row['indicator_type'], row['indicator_type'])
            result[key] = {
                "value": row['value'],
                "change_pct": row['change_pct'] or 0,
                "week_change_pct": round(row['week_change'], 2) if pd.notna(row['week_change']) else None,
                "month_change_pct": round(row['month_change'], 2) if pd.notna(row['month_change']) else None,
                "quarter_change_pct": round(row['quarter_change'], 2) if pd.notna(row['quarter_change']) else None,
            }
        return result
    except Exception:
        return {}


def collect_all_macro_data() -> Dict[str, Any]:
    """
    모든 매크로 데이터 수집
    """
    return {
        "collected_at": datetime.now().isoformat(),
        "korea": get_korea_market_data(),
        "kosdaq": get_kosdaq_market_data(),
        "us": get_us_market_data(),
        "nasdaq": get_nasdaq_market_data(),
        "investor_flow": get_investor_flow(),
        "semiconductor": get_semiconductor_prices(),
        "indices": get_index_summary(),
        "exchange_rates": get_exchange_rates(),
        "fear_greed": get_fear_greed(),
        "commodities": get_commodities(),
        "interest_rates": get_interest_rates(),
        "bitcoin": get_bitcoin(),
        # 새로 추가된 지표들
        "dollar_index": get_dollar_index(),
        "semiconductor_index": get_semiconductor_index(),
        "global_indices": get_global_indices(),
        "us_sectors": get_us_sectors(),
        "kr_sectors": get_kr_sectors(),
    }


if __name__ == "__main__":
    # 테스트
    import json

    print("=== 한국 시장 데이터 ===")
    korea = get_korea_market_data()
    print(f"날짜: {korea['date']}")
    print(f"종목 수: {len(korea['stocks'])}")
    print(f"섹터 수: {len(korea['sector_summary'])}")
    if korea['stocks']:
        print(f"샘플: {korea['stocks'][:3]}")

    print("\n=== 미국 시장 데이터 ===")
    us = get_us_market_data()
    print(f"날짜: {us['date']}")
    print(f"종목 수: {len(us['stocks'])}")
    if us['stocks']:
        print(f"샘플: {us['stocks'][:3]}")
