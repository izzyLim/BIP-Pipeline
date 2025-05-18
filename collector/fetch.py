import requests
import pandas as pd

def fetch_historical_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Yahoo Finance API를 사용해 특정 기간 동안의 주가 데이터를 조회.
    날짜 형식: 'YYYY-MM-DD'
    """
    import datetime as dt
    import time

    try:
        start_dt = dt.datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = dt.datetime.strptime(end_date, "%Y-%m-%d")

        # UNIX timestamp (초 단위)
        period1 = int(time.mktime(start_dt.timetuple()))
        period2 = int(time.mktime(end_dt.timetuple()))

        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {
            "period1": period1,
            "period2": period2,
            "interval": "1d",  # 또는 "1m", "5m" 등
            "includePrePost": "false"
        }
        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(url, params=params, headers=headers)
        if response.status_code != 200:
            print(f"[ERROR] Yahoo API 요청 실패: {response.status_code}")
            return None

        data = response.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        indicators = result["indicators"]["quote"][0]

        df = pd.DataFrame(indicators)
        df["timestamp"] = pd.to_datetime(timestamps, unit="s", utc=True)
        df["ticker"] = ticker
        df["timestamp_kst"] = df["timestamp"].dt.tz_convert("Asia/Seoul")

        # 컬럼 순서 정리
        df = df[["ticker", "timestamp", "timestamp_kst", "open", "high", "low", "close", "volume"]]

        return df

    except Exception as e:
        print(f"[ERROR] 데이터 파싱 실패: {e}")
        return None
