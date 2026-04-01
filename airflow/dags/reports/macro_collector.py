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


# KRX 업종 별칭 (긴 공식명 → 짧은 표현)
KRX_SECTOR_ALIAS = {
    "반도체와반도체장비": "반도체",
    "우주항공과국방": "방산",
    "전자장비와기기": "전자장비",
    "디스플레이패널": "디스플레이",
    "디스플레이장비및부품": "디스플레이장비",
    "가정용기기와용품": "가전",
    "게임엔터테인먼트": "게임",
    "레저용장비와제품": "레저",
    "백화점과일반상점": "유통",
    "컴퓨터와주변기기": "컴퓨터",
    "건강관리장비와용품": "의료기기",
    "건강관리업체및서비스": "의료서비스",
    "건강관리기술": "헬스케어IT",
    "다각화된통신서비스": "통신",
    "무선통신서비스": "무선통신",
    "무역회사와판매업체": "무역",
    "방송과엔터테인먼트": "엔터",
    "상업서비스와공급품": "상업서비스",
    "에너지장비및서비스": "에너지장비",
    "항공화물운송과물류": "물류",
    "다각화된소비자서비스": "소비자서비스",
    "생명과학도구및서비스": "바이오장비",
    "식품과기본식료품소매": "식품유통",
    "양방향미디어와서비스": "인터넷",
    "인터넷과카탈로그소매": "온라인쇼핑",
    "도로와철도운송": "육상운송",
    "사무용전자제품": "사무전자",
    "가스유틸리티": "가스",
    "복합유틸리티": "복합유틸",
    "전기유틸리티": "전력",
    "섬유,의류,신발,호화품": "패션/의류",
    "호텔,레스토랑,레저": "호텔/레저",
    "종이와목재": "제지",
    "석유와가스": "석유/가스",
    "소프트웨어": "SW",
    "운송인프라": "운송인프라",
    "IT서비스": "IT서비스",
}


# DB 연결
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://user:pw1234@bip-postgres:5432/stockdb"
)


def get_engine():
    return create_engine(DATABASE_URL)


def _read_sql(query, conn, params=None) -> pd.DataFrame:
    """SQLAlchemy 2.x + pandas 2.x 호환 read_sql 헬퍼"""
    if params:
        result = conn.execute(query, params)
    else:
        result = conn.execute(query)
    return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def _get_krx_sector_summary(engine, date: str) -> List[Dict]:
    """
    macro_indicators에서 KRX 공식 업종 등락률 조회
    dag_krx_sectors.py가 매일 장 마감 후 수집한 데이터 활용
    """
    query = text("""
        SELECT
            REPLACE(indicator_type, 'krx_sector_', '') as sector,
            change_pct
        FROM macro_indicators
        WHERE indicator_date = CAST(:date AS date)
          AND region = 'South Korea'
          AND indicator_type LIKE 'krx_sector_%'
        ORDER BY ABS(change_pct) DESC
    """)
    with engine.connect() as conn:
        df = _read_sql(query, conn, params={"date": date})
    if df.empty:
        return []
    # 별칭 치환
    df["sector"] = df["sector"].map(lambda s: KRX_SECTOR_ALIAS.get(s, s))
    return df.to_dict("records")


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
        df = _read_sql(query, conn, params={"trade_date": date})

    if df.empty:
        return {"date": date, "stocks": [], "sector_summary": []}

    # KRX 공식 업종 등락률 우선 사용, 없으면 종목 집계로 fallback
    krx_sectors = _get_krx_sector_summary(engine, date)
    if krx_sectors:
        sector_summary = krx_sectors
    else:
        sector_df = df.groupby("sector").agg({
            "market_value": "sum",
            "change_pct": "mean"
        }).reset_index()
        sector_df = sector_df.sort_values("market_value", ascending=False)
        sector_summary = sector_df.to_dict("records")

    return {
        "date": date,
        "stocks": df.to_dict("records"),
        "sector_summary": sector_summary,
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
        df = _read_sql(query, conn, params={"trade_date": date})

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
        df = _read_sql(query, conn, params={"trade_date": date})

    if df.empty:
        return {"date": date, "stocks": [], "sector_summary": []}

    # KRX 공식 업종 등락률 우선 사용, 없으면 종목 집계로 fallback
    krx_sectors = _get_krx_sector_summary(engine, date)
    if krx_sectors:
        sector_summary = krx_sectors
    else:
        sector_df = df.groupby("sector").agg({
            "market_value": "sum",
            "change_pct": "mean"
        }).reset_index()
        sector_df = sector_df.sort_values("market_value", ascending=False)
        sector_summary = sector_df.to_dict("records")

    return {
        "date": date,
        "stocks": df.to_dict("records"),
        "sector_summary": sector_summary,
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
        df = _read_sql(query, conn, params={"trade_date": date})

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
          AND timestamp::date >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY timestamp::date
        ORDER BY date DESC
        LIMIT :days
    """)

    with engine.connect() as conn:
        df = _read_sql(query, conn, params={"days": days})

    return df.to_dict("records") if not df.empty else []


def get_semiconductor_prices() -> List[Dict]:
    """
    반도체 가격 데이터 (DRAM, NAND) - DRAMeXchange 기준
    - 전일 대비: LAG()로 계산 (주말/공휴일 gap 자동 처리)
    - 1주/1개월/3개월 변동률 포함
    - NAND flat 처리: 마지막 유의미한 변동일과 변동률 포함
    """
    engine = get_engine()

    # LAG()를 사용하여 전일 대비 계산 (주말/공휴일 자동 처리)
    # + 마지막 유의미한 변동일/변동률 (NAND flat 처리용)
    query = text("""
        WITH latest AS (
            SELECT indicator_type, MAX(indicator_date) as max_date
            FROM macro_indicators
            WHERE indicator_type LIKE 'dram%' OR indicator_type LIKE 'nand%'
            GROUP BY indicator_type
        ),
        with_prev AS (
            SELECT
                indicator_type,
                indicator_date,
                value,
                LAG(value) OVER (PARTITION BY indicator_type ORDER BY indicator_date) AS prev_value
            FROM macro_indicators
            WHERE indicator_type LIKE 'dram%' OR indicator_type LIKE 'nand%'
        ),
        -- 마지막 유의미한 변동 (가격이 변한 날) 찾기
        with_changes AS (
            SELECT
                indicator_type,
                indicator_date,
                value,
                prev_value,
                CASE WHEN prev_value > 0 AND value != prev_value
                     THEN ROUND(((value - prev_value) / prev_value * 100)::numeric, 2)
                     ELSE NULL
                END as change_pct
            FROM with_prev
            WHERE prev_value IS NOT NULL
        ),
        last_meaningful_change AS (
            SELECT DISTINCT ON (indicator_type)
                indicator_type,
                indicator_date as last_change_date,
                change_pct as last_change_pct
            FROM with_changes
            WHERE change_pct IS NOT NULL AND change_pct != 0
            ORDER BY indicator_type, indicator_date DESC
        ),
        week_ago AS (
            SELECT DISTINCT ON (m.indicator_type) m.indicator_type, m.value
            FROM macro_indicators m
            JOIN latest l ON m.indicator_type = l.indicator_type
            WHERE m.indicator_date <= l.max_date - INTERVAL '7 days'
            ORDER BY m.indicator_type, m.indicator_date DESC
        ),
        month_ago AS (
            SELECT DISTINCT ON (m.indicator_type) m.indicator_type, m.value
            FROM macro_indicators m
            JOIN latest l ON m.indicator_type = l.indicator_type
            WHERE m.indicator_date <= l.max_date - INTERVAL '30 days'
            ORDER BY m.indicator_type, m.indicator_date DESC
        ),
        quarter_ago AS (
            SELECT DISTINCT ON (m.indicator_type) m.indicator_type, m.value
            FROM macro_indicators m
            JOIN latest l ON m.indicator_type = l.indicator_type
            WHERE m.indicator_date <= l.max_date - INTERVAL '90 days'
            ORDER BY m.indicator_type, m.indicator_date DESC
        )
        SELECT
            t.indicator_type as product_type,
            t.value as price,
            t.prev_value as prev_price,
            CASE WHEN t.prev_value > 0
                 THEN ROUND(((t.value - t.prev_value) / t.prev_value * 100)::numeric, 2)
                 ELSE NULL
            END as price_change_pct,
            CASE WHEN w.value > 0
                 THEN ROUND(((t.value - w.value) / w.value * 100)::numeric, 2)
                 ELSE NULL
            END as week_change_pct,
            CASE WHEN m.value > 0
                 THEN ROUND(((t.value - m.value) / m.value * 100)::numeric, 2)
                 ELSE NULL
            END as month_change_pct,
            CASE WHEN q.value > 0
                 THEN ROUND(((t.value - q.value) / q.value * 100)::numeric, 2)
                 ELSE NULL
            END as quarter_change_pct,
            t.indicator_date as date,
            lmc.last_change_date,
            lmc.last_change_pct
        FROM with_prev t
        LEFT JOIN week_ago w ON t.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON t.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON t.indicator_type = q.indicator_type
        LEFT JOIN last_meaningful_change lmc ON t.indicator_type = lmc.indicator_type
        JOIN latest l ON t.indicator_type = l.indicator_type
        WHERE t.indicator_date = l.max_date
        ORDER BY t.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = _read_sql(query, conn)
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
            df = _read_sql(query, conn)

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
        print("⚠️ 환율 데이터 없음 (DB 조회 결과 없음)")
        return {}
    except Exception as e:
        print(f"⚠️ 환율 데이터 조회 실패: {e}")
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
            df = _read_sql(query, conn)

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
            df = _read_sql(query, conn)

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
        prev_day AS (
            SELECT DISTINCT ON (indicator_type) indicator_type, value
            FROM macro_indicators
            WHERE indicator_type IN ('interest_rate_10y', 'korea_govt_3y')
              AND indicator_date < (SELECT max_date FROM latest_date)
            ORDER BY indicator_type, indicator_date DESC
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
            p.value as prev_value,
            (l.value - w.value) as week_change,
            (l.value - m.value) as month_change,
            (l.value - q.value) as quarter_change
        FROM latest l
        LEFT JOIN prev_day p ON l.indicator_type = p.indicator_type
        LEFT JOIN week_ago w ON l.indicator_type = w.indicator_type
        LEFT JOIN month_ago m ON l.indicator_type = m.indicator_type
        LEFT JOIN quarter_ago q ON l.indicator_type = q.indicator_type
    """)

    try:
        with engine.connect() as conn:
            df = _read_sql(query, conn)

        result = {}
        for _, row in df.iterrows():
            # change_pct가 NULL이면 전일 대비 직접 계산 (금리는 bp 단위)
            if pd.notna(row.get('change_pct')):
                day_change = float(row['change_pct'])
            elif pd.notna(row.get('prev_value')) and row['prev_value'] != 0:
                day_change = round(float(row['value']) - float(row['prev_value']), 2)
            else:
                day_change = 0
            data = {
                "value": row['value'],
                "change_pct": day_change,
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
            df = _read_sql(query, conn)

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
            df = _read_sql(query, conn)

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
            df = _read_sql(query, conn)

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
            df = _read_sql(query, conn)

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


def get_night_futures() -> Dict[str, Any]:
    """
    야간 한국 시장 프록시 데이터 수집
    - EWY (iShares MSCI South Korea ETF): 미국에서 거래되는 한국 ETF
    - 한국장 마감 후 미국장에서 거래되므로 갭 예측에 활용
    - 정규장 + 애프터마켓 데이터 모두 수집하여 비교
    - SGX 니케이 선물도 참고용으로 수집
    """
    try:
        import yfinance as yf

        result = {}

        # EWY: 한국 ETF (갭 예측 핵심)
        ewy = yf.Ticker("EWY")
        hist = ewy.history(period="5d")
        info = ewy.info

        if not hist.empty and len(hist) >= 2:
            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            regular_close = latest['Close']
            regular_change_pct = ((regular_close - prev['Close']) / prev['Close'] * 100) if prev['Close'] > 0 else 0

            # 애프터마켓 데이터 확인
            post_market_price = info.get('postMarketPrice')
            post_market_change_pct = info.get('postMarketChangePercent', 0)
            pre_market_price = info.get('preMarketPrice')
            pre_market_change_pct = info.get('preMarketChangePercent', 0)

            # 가장 최신 가격 결정 (애프터마켓 > 프리마켓 > 정규장)
            if post_market_price and post_market_price > 0:
                final_price = post_market_price
                # 전일 종가 대비 변동률 계산
                final_change_pct = ((post_market_price - prev['Close']) / prev['Close'] * 100) if prev['Close'] > 0 else 0
                price_source = "애프터마켓"
            elif pre_market_price and pre_market_price > 0:
                final_price = pre_market_price
                final_change_pct = ((pre_market_price - prev['Close']) / prev['Close'] * 100) if prev['Close'] > 0 else 0
                price_source = "프리마켓"
            else:
                final_price = regular_close
                final_change_pct = regular_change_pct
                price_source = "정규장"

            result["ewy"] = {
                "name": "한국 ETF (EWY)",
                "value": round(final_price, 2),
                "change": round(final_price - prev['Close'], 2),
                "change_pct": round(final_change_pct, 2),
                "timestamp": str(hist.index[-1]),
                "price_source": price_source,
                # 정규장 vs 애프터마켓 비교 데이터
                "regular_close": round(regular_close, 2),
                "regular_change_pct": round(regular_change_pct, 2),
                "post_market_price": round(post_market_price, 2) if post_market_price else None,
                "post_market_change_pct": round(post_market_change_pct * 100, 2) if post_market_change_pct else None,
            }

            # 정규장과 애프터마켓 괴리가 크면 별도 알림
            if post_market_price and abs(final_change_pct - regular_change_pct) > 0.5:
                result["ewy"]["divergence"] = round(final_change_pct - regular_change_pct, 2)
                result["ewy"]["divergence_note"] = f"정규장 {regular_change_pct:+.2f}% → 애프터 {final_change_pct:+.2f}%"

        # SGX 니케이 선물 (아시아 심리 참고)
        nikkei = yf.Ticker("NKD=F")
        hist_nk = nikkei.history(period="5d")

        if not hist_nk.empty and len(hist_nk) >= 2:
            latest = hist_nk.iloc[-1]
            prev = hist_nk.iloc[-2]
            change_pct = ((latest['Close'] - prev['Close']) / prev['Close'] * 100) if prev['Close'] > 0 else 0

            result["nikkei_futures"] = {
                "name": "닛케이 선물",
                "value": round(latest['Close'], 2),
                "change_pct": round(change_pct, 2),
            }

        return result
    except Exception as e:
        print(f"야간 프록시 조회 실패: {e}")
        return {}


def get_short_selling() -> Dict[str, Any]:
    """
    공매도 데이터 수집 (DB에서 조회)
    - KRX 공매도 잔고 데이터
    """
    engine = get_engine()

    # 공매도 데이터가 DB에 있는지 확인
    query = text("""
        SELECT
            trade_date,
            ticker,
            short_balance,
            short_balance_ratio,
            short_volume
        FROM short_selling
        WHERE trade_date >= CURRENT_DATE - INTERVAL '5 days'
        ORDER BY trade_date DESC, short_balance DESC
        LIMIT 100
    """)

    try:
        with engine.connect() as conn:
            df = _read_sql(query, conn)

        if df.empty:
            return {"available": False, "message": "공매도 데이터 테이블 없음"}

        # 공매도 잔고 상위 종목
        latest_date = df['trade_date'].max()
        top_shorts = df[df['trade_date'] == latest_date].head(10).to_dict('records')

        return {
            "available": True,
            "date": str(latest_date),
            "top_shorts": top_shorts,
        }
    except Exception as e:
        # 테이블이 없는 경우
        return {"available": False, "message": str(e)}


def get_etf_flows() -> Dict[str, Any]:
    """
    주요 ETF 자금흐름 데이터 수집
    - SPY, QQQ, SOXX 등 거래량/가격 변화로 추정
    """
    try:
        import yfinance as yf

        etfs = {
            "SPY": "S&P500 ETF",
            "QQQ": "나스닥100 ETF",
            "SOXX": "반도체 ETF",
            "SMH": "반도체 ETF (VanEck)",
            "XLF": "금융 ETF",
            "XLE": "에너지 ETF",
            "TLT": "장기국채 ETF",
            "HYG": "하이일드 ETF",
            "EWY": "한국 ETF (iShares)",
        }

        results = {}

        for ticker, name in etfs.items():
            try:
                etf = yf.Ticker(ticker)
                hist = etf.history(period="5d")

                if hist.empty or len(hist) < 2:
                    continue

                latest = hist.iloc[-1]
                prev = hist.iloc[-2]

                # 가격 변동
                price_change_pct = ((latest['Close'] - prev['Close']) / prev['Close'] * 100) if prev['Close'] > 0 else 0

                # 거래량 변화 (자금흐름 프록시)
                avg_volume = hist['Volume'].mean()
                volume_ratio = latest['Volume'] / avg_volume if avg_volume > 0 else 1

                # 5일 자금흐름 추정 (가격 * 거래량 변화)
                flow_estimate = sum(
                    hist.iloc[i]['Close'] * hist.iloc[i]['Volume'] * (1 if hist.iloc[i]['Close'] > hist.iloc[i]['Open'] else -1)
                    for i in range(len(hist))
                )

                results[ticker] = {
                    "name": name,
                    "price": round(latest['Close'], 2),
                    "change_pct": round(price_change_pct, 2),
                    "volume": int(latest['Volume']),
                    "volume_ratio": round(volume_ratio, 2),  # 1.5 = 평균 대비 50% 증가
                    "flow_direction": "inflow" if flow_estimate > 0 else "outflow",
                }
            except Exception as e:
                continue

        return results
    except Exception as e:
        print(f"ETF 데이터 조회 실패: {e}")
        return {}


def get_investor_trading_data() -> Dict[str, Any]:
    """
    투자자별 수급 데이터 수집 (최근 거래일 기준)

    개별주 (ETF 제외):
      - 거래량 TOP 12
      - 거래대금 TOP 12
      - 외국인/기관/개인 순매수 TOP 5, 순매도 TOP 5

    ETF:
      - 외국인/기관/개인 순매수 TOP 3, 순매도 TOP 3

    순매수 금액 기준 (억원) = net_volume × close / 100,000,000
    """
    engine = get_engine()

    # ETF/ETN 판별 키워드
    etf_keywords = [
        'ETF', 'ETN', 'KODEX', 'TIGER', 'KINDEX', 'KOSEF', 'ARIRANG',
        'HANARO', 'TIMEFOLIO', 'FOCUS', 'SOL ', 'WOORI', 'MASTER',
        'SMART', 'ACE ', 'KBSTAR', 'TREX', 'PLUS ', '선물 ETN', '레버리지', '인버스'
    ]
    etf_condition = " OR ".join([f"si.stock_name LIKE '%{kw}%'" for kw in etf_keywords])

    # 최근 거래일 조회
    date_query = text("""
        SELECT MAX(timestamp::date) as latest_date
        FROM stock_price_1d
        WHERE ticker LIKE '%.KS' OR ticker LIKE '%.KQ'
    """)
    with engine.connect() as conn:
        date_result = conn.execute(date_query).fetchone()
    latest_date = str(date_result[0]) if date_result and date_result[0] else None
    if not latest_date:
        return {}

    # 공통 베이스 쿼리: 개별주 + ETF 구분
    base_query = text(f"""
        WITH daily AS (
            SELECT
                p.ticker,
                si.stock_name,
                si.market_type,
                p.volume,
                p.close,
                COALESCE(p.trading_value, p.volume * p.close) AS trading_amount,
                p.foreign_buy_volume,
                p.institution_buy_volume,
                p.individual_buy_volume,
                (p.foreign_buy_volume * p.close)       AS foreign_net_amount,
                (p.institution_buy_volume * p.close)   AS institution_net_amount,
                (p.individual_buy_volume * p.close)    AS individual_net_amount,
                CASE WHEN ({etf_condition}) THEN 'ETF' ELSE 'STOCK' END AS asset_type
            FROM stock_price_1d p
            JOIN stock_info si ON p.ticker = si.ticker
            WHERE p.timestamp::date = :trade_date
              AND (si.market_type = 'KOSPI' OR si.market_type = 'KOSDAQ')
              AND p.close > 0
              AND p.volume > 0
        )
        SELECT * FROM daily
    """)

    try:
        with engine.connect() as conn:
            df = _read_sql(base_query, conn, params={"trade_date": latest_date})

        if df.empty:
            return {"date": latest_date, "available": False}

        def fmt_amount(val):
            """원 → 억원 변환"""
            return round(float(val) / 100_000_000, 1) if val else 0.0

        def fmt_volume(val):
            return int(val) if val else 0

        def build_top(df_sub, col, n, ascending=False):
            """상위 n개 추출"""
            import math
            sorted_df = df_sub.dropna(subset=[col]).sort_values(col, ascending=ascending).head(n)
            rows = []
            for _, r in sorted_df.iterrows():
                close_val = r["close"]
                col_val = r[col]
                rows.append({
                    "ticker": r["ticker"],
                    "name": r["stock_name"],
                    "market": r["market_type"],
                    "close": int(close_val) if not (isinstance(close_val, float) and math.isnan(close_val)) else 0,
                    "value": round(float(col_val), 1) if col.endswith("amount") else (int(col_val) if not (isinstance(col_val, float) and math.isnan(col_val)) else 0),
                })
            return rows

        stocks = df[df["asset_type"] == "STOCK"].copy()
        etfs = df[df["asset_type"] == "ETF"].copy()

        # 억원 단위 컬럼 추가
        for d in [stocks, etfs]:
            d["trading_amount_eok"] = d["trading_amount"].apply(fmt_amount)
            d["foreign_net_eok"] = d["foreign_net_amount"].apply(fmt_amount)
            d["institution_net_eok"] = d["institution_net_amount"].apply(fmt_amount)
            d["individual_net_eok"] = d["individual_net_amount"].apply(fmt_amount)

        kospi = stocks[stocks["market_type"] == "KOSPI"].copy()
        kosdaq = stocks[stocks["market_type"] == "KOSDAQ"].copy()

        def market_section(mdf):
            return {
                "volume_top12": build_top(mdf, "volume", 12),
                "amount_top12": build_top(mdf, "trading_amount_eok", 12),
                "foreign_buy_top5": build_top(mdf, "foreign_net_eok", 5),
                "foreign_sell_top5": build_top(mdf, "foreign_net_eok", 5, ascending=True),
                "institution_buy_top5": build_top(mdf, "institution_net_eok", 5),
                "institution_sell_top5": build_top(mdf, "institution_net_eok", 5, ascending=True),
                "individual_buy_top5": build_top(mdf, "individual_net_eok", 5),
                "individual_sell_top5": build_top(mdf, "individual_net_eok", 5, ascending=True),
            }

        result = {
            "date": latest_date,
            "available": True,
            "kospi": market_section(kospi),
            "kosdaq": market_section(kosdaq),
            # ETF/ETN 순매수/순매도 TOP 3
            "etf_foreign_buy_top3": build_top(etfs, "foreign_net_eok", 3),
            "etf_foreign_sell_top3": build_top(etfs, "foreign_net_eok", 3, ascending=True),
            "etf_institution_buy_top3": build_top(etfs, "institution_net_eok", 3),
            "etf_institution_sell_top3": build_top(etfs, "institution_net_eok", 3, ascending=True),
            "etf_individual_buy_top3": build_top(etfs, "individual_net_eok", 3),
            "etf_individual_sell_top3": build_top(etfs, "individual_net_eok", 3, ascending=True),
        }
        return result

    except Exception as e:
        print(f"투자자 수급 데이터 조회 실패: {e}")
        return {"date": latest_date, "available": False, "error": str(e)}


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
        "investor_trading": get_investor_trading_data(),
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
        # 추가 데이터 (갭 예측, 수급 분석용)
        "night_futures": get_night_futures(),
        "short_selling": get_short_selling(),
        "etf_flows": get_etf_flows(),
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
