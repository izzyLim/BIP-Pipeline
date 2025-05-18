import requests
from datetime import datetime

def fetch_historical_data(ticker: str, start_date: str, end_date: str):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "interval": "1m",
        "range": "5d"    }
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    response = requests.get(url, params=params, headers=headers)
    #response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"[ERROR] API 요청 실패: {response.status_code}")
        return []

    chart = response.json().get("chart", {})
    result = chart.get("result", [{}])[0]
    if not result:
        return []

    timestamps = result.get("timestamp", [])
    indicators = result.get("indicators", {}).get("quote", [{}])[0]

    records = []
    for i, ts in enumerate(timestamps):
        dt = datetime.utcfromtimestamp(ts)
        if not (start_date <= dt.strftime("%Y-%m-%d") <= end_date):
            continue
        records.append({
            "ticker": ticker,
            "timestamp": dt.isoformat(),
            "open": indicators["open"][i],
            "high": indicators["high"][i],
            "low": indicators["low"][i],
            "close": indicators["close"][i],
            "volume": indicators["volume"][i],
        })

    return records
