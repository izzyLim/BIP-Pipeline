"""
거시경제 지표 수집
- 환율: Yahoo Finance (yfinance)
- 금리, PMI 등: FRED API
"""

import pandas as pd
import psycopg2
from datetime import datetime, timedelta
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "user",
    "password": "pw1234",
    "dbname": "stockdb"
}

# 권역별 통화/지표 매핑
REGION_INDICATORS = {
    "North America": {
        "exchange_rate": "DX-Y.NYB",  # US Dollar Index
        "interest_rate": "^TNX",       # 10-Year Treasury Yield
    },
    "Western Europe": {
        "exchange_rate": "EURUSD=X",
        "interest_rate": None,
    },
    "China": {
        "exchange_rate": "USDCNY=X",
        "interest_rate": None,
    },
    "Japan": {
        "exchange_rate": "USDJPY=X",
        "interest_rate": None,
    },
    "South Korea": {
        "exchange_rate": "USDKRW=X",
        "interest_rate": None,
    },
    "India": {
        "exchange_rate": "USDINR=X",
        "interest_rate": None,
    },
    "Southeast Asia": {
        "exchange_rate": "USDTHB=X",  # Thai Baht as proxy
        "interest_rate": None,
    },
    "CALA": {
        "exchange_rate": "USDBRL=X",  # Brazilian Real as proxy
        "interest_rate": None,
    },
    "MEA": {
        "exchange_rate": "USDSAR=X",  # Saudi Riyal as proxy
        "interest_rate": None,
    },
    "Central Europe": {
        "exchange_rate": "USDPLN=X",  # Polish Zloty as proxy
        "interest_rate": None,
    },
    "Asia Pacific Others": {
        "exchange_rate": "AUDUSD=X",  # Australian Dollar
        "interest_rate": None,
    },
}


def get_connection():
    try:
        config = DB_CONFIG.copy()
        config["host"] = "bip-postgres"
        return psycopg2.connect(**config)
    except:
        return psycopg2.connect(**DB_CONFIG)


def collect_exchange_rates(start_date: str, end_date: str):
    """Yahoo Finance에서 환율 데이터 수집"""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return []

    all_data = []

    for region, indicators in REGION_INDICATORS.items():
        symbol = indicators.get("exchange_rate")
        if not symbol:
            continue

        logger.info(f"Fetching {symbol} for {region}...")

        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=start_date, end=end_date)

            if hist.empty:
                logger.warning(f"No data for {symbol}")
                continue

            for date, row in hist.iterrows():
                all_data.append({
                    "indicator_date": date.strftime("%Y-%m-%d"),
                    "region": region,
                    "indicator_type": "exchange_rate",
                    "value": float(row["Close"]),
                    "change_pct": None  # 나중에 계산
                })

        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            continue

    # change_pct 계산
    df = pd.DataFrame(all_data)
    if not df.empty:
        df = df.sort_values(["region", "indicator_date"])
        df["change_pct"] = df.groupby("region")["value"].pct_change() * 100
        all_data = df.to_dict("records")

    return all_data


def collect_treasury_yields(start_date: str, end_date: str):
    """미국 국채 수익률 수집"""
    try:
        import yfinance as yf
    except ImportError:
        return []

    logger.info("Fetching US Treasury Yields...")

    all_data = []
    symbols = {
        "^TNX": "interest_rate_10y",  # 10-Year
        "^FVX": "interest_rate_5y",   # 5-Year
        "^IRX": "interest_rate_3m",   # 3-Month
    }

    for symbol, indicator_type in symbols.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=start_date, end=end_date)

            for date, row in hist.iterrows():
                all_data.append({
                    "indicator_date": date.strftime("%Y-%m-%d"),
                    "region": "North America",
                    "indicator_type": indicator_type,
                    "value": float(row["Close"]),
                    "change_pct": None
                })
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")

    return all_data


def collect_stock_indices(start_date: str, end_date: str):
    """주요 주가지수 수집"""
    try:
        import yfinance as yf
    except ImportError:
        return []

    indices = {
        "^GSPC": ("North America", "sp500"),           # S&P 500
        "^IXIC": ("North America", "nasdaq"),          # NASDAQ
        "^STOXX50E": ("Western Europe", "eurostoxx"),  # Euro Stoxx 50
        "000001.SS": ("China", "shanghai"),            # Shanghai Composite
        "^N225": ("Japan", "nikkei"),                  # Nikkei 225
        "^KS11": ("South Korea", "kospi"),             # KOSPI
        "^BSESN": ("India", "sensex"),                 # BSE Sensex
    }

    all_data = []

    for symbol, (region, indicator_type) in indices.items():
        logger.info(f"Fetching {symbol} ({indicator_type}) for {region}...")

        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=start_date, end=end_date)

            if hist.empty:
                continue

            for date, row in hist.iterrows():
                all_data.append({
                    "indicator_date": date.strftime("%Y-%m-%d"),
                    "region": region,
                    "indicator_type": f"stock_index_{indicator_type}",
                    "value": float(row["Close"]),
                    "change_pct": None
                })
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")

    # change_pct 계산
    df = pd.DataFrame(all_data)
    if not df.empty:
        df = df.sort_values(["region", "indicator_type", "indicator_date"])
        df["change_pct"] = df.groupby(["region", "indicator_type"])["value"].pct_change() * 100
        all_data = df.to_dict("records")

    return all_data


def save_to_db(data: list):
    """DB에 저장"""
    if not data:
        logger.warning("No data to save")
        return 0

    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    for record in data:
        try:
            cur.execute("""
                INSERT INTO macro_indicators
                    (indicator_date, region, indicator_type, value, change_pct)
                VALUES (%s, %s::region_type, %s, %s, %s)
                ON CONFLICT (indicator_date, region, indicator_type)
                DO UPDATE SET value = EXCLUDED.value, change_pct = EXCLUDED.change_pct
            """, (
                record["indicator_date"],
                record["region"],
                record["indicator_type"],
                record["value"],
                record["change_pct"]
            ))
            inserted += 1
        except Exception as e:
            logger.debug(f"Error inserting: {e}")
            conn.rollback()
            continue

    conn.commit()
    conn.close()

    logger.info(f"Saved {inserted} records to macro_indicators")
    return inserted


def collect_all(start_date: str = "2020-01-01", end_date: str = None):
    """모든 지표 수집"""
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Collecting macro indicators from {start_date} to {end_date}")

    # 환율
    exchange_data = collect_exchange_rates(start_date, end_date)
    save_to_db(exchange_data)

    # 금리
    yield_data = collect_treasury_yields(start_date, end_date)
    save_to_db(yield_data)

    # 주가지수
    index_data = collect_stock_indices(start_date, end_date)
    save_to_db(index_data)

    # 결과 확인
    check_stats()


def check_stats():
    """통계 확인"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM macro_indicators")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT indicator_type, COUNT(*), MIN(indicator_date), MAX(indicator_date)
        FROM macro_indicators
        GROUP BY indicator_type
        ORDER BY COUNT(*) DESC
    """)
    by_type = cur.fetchall()

    cur.execute("""
        SELECT region, COUNT(*)
        FROM macro_indicators
        GROUP BY region
        ORDER BY COUNT(*) DESC
    """)
    by_region = cur.fetchall()

    conn.close()

    print(f"\n=== Macro Indicators Stats ===")
    print(f"Total records: {total}")
    print(f"\nBy type:")
    for t, c, min_d, max_d in by_type:
        print(f"  {t}: {c} ({min_d} ~ {max_d})")
    print(f"\nBy region:")
    for r, c in by_region:
        print(f"  {r}: {c}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        check_stats()
    elif len(sys.argv) == 3:
        collect_all(sys.argv[1], sys.argv[2])
    else:
        # 기본: 2020년부터 현재까지
        collect_all("2020-01-01")
