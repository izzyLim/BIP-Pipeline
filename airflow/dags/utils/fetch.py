import requests
import pandas as pd
from datetime import datetime, timezone
import pytz


def fetch_price_data(ticker: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """
    Yahoo Finance REST API 호출을 통해 주가 데이터를 수집하고,
    timestamp_ny (미국 동부), timestamp_kst (한국 시간) 포함해서 반환.
    """
    interval_map = {
        "1m": "1m",
        "1d": "1d",
        "1wk": "1wk",
        "1mo": "1mo"
    }

    if interval not in interval_map:
        raise ValueError(f"[ERROR] Unsupported interval: {interval}")

    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "interval": interval_map[interval],
        "period1": int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()),
        "period2": int(datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    }
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        print(f"[ERROR] {ticker} 요청 실패: {response.status_code}")
        return pd.DataFrame()

    try:
        result = response.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        indicators = result["indicators"]["quote"][0]

        df = pd.DataFrame(indicators)
        df["timestamp"] = pd.to_datetime(timestamps, unit="s", utc=True)
        df["timestamp_ny"] = df["timestamp"].dt.tz_convert("America/New_York")
        df["timestamp_kst"] = df["timestamp"].dt.tz_convert("Asia/Seoul")

        # 여기서 타임존 제거 (중요!!)
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
        df["timestamp_ny"] = df["timestamp_ny"].dt.tz_localize(None)
        df["timestamp_kst"] = df["timestamp_kst"].dt.tz_localize(None)
        df["ticker"] = ticker

        print(df[["timestamp", "timestamp_ny", "timestamp_kst"]].head(3))

        df = df[[
            "ticker", "timestamp", "timestamp_ny", "timestamp_kst",
            "open", "high", "low", "close", "volume"
        ]]

        return df

    except Exception as e:
        print(f"[ERROR] {ticker} 파싱 실패: {e}")
        return pd.DataFrame()
