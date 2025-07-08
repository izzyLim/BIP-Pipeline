from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.db import upsert_stock_info
from utils.config import PG_CONN_INFO

import requests
import pandas as pd

def get_naver_nasdaq_stocks(page=1, pageSize=100):
    url = "https://api.stock.naver.com/stock/exchange/NASDAQ/marketValue"
    params = {
        "page": page,
        "pageSize": pageSize
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://stock.naver.com/"
    }

    res = requests.get(url, headers=headers, params=params)
    return res.json()

def get_all_nasdaq_stocks():
    all_items = []
    page = 1
    while True:
        data = get_naver_nasdaq_stocks(page)
        items = data.get("stocks", [])
        if not items:
            break
        all_items.extend(items)
        print(f"{page} 페이지 처리 완료")
        page += 1

    return pd.DataFrame(all_items)

def parse_numeric(value):
    if value is None or value == '-' or value == '':
        return None
    try:
        return float(value.replace(',', ''))
    except ValueError:
        return None

def fetch_and_upsert_naver_nasdaq_stocks(**context):
    df = get_all_nasdaq_stocks()

    if df.empty:
        print("[INFO] No NASDAQ stock data found.")
        return

    # 데이터 파싱 및 정리
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "ticker": row.get("symbolCode"),                         # 예: NVDA
            "stock_name": row.get("stockName"),                     # 예: 엔비디아
            "stock_name_eng": row.get("stockNameEng"),              # 예: NVIDIA
            "market_type": row.get("stockExchangeType", {}).get("name"),
            "exchange_code": row.get("stockExchangeType", {}).get("code"),
            "currency_code": row.get("currencyType", {}).get("code"),
            "listing_date": None,                                  # 정보 없음
            "par_value": None,
            "total_shares": None,
            "market_value": parse_numeric(row.get("marketValue")),
            "data_source": "NAVER"
        })

    upsert_stock_info(rows, PG_CONN_INFO)

default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
}

with DAG(
    dag_id="load_naver_nasdaq_stock_info",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule_interval="0 8 * * *",  # 매일 오전 8시
    catchup=False,
    tags=["NAVER", "NASDAQ", "stock_info"]
) as dag:

    fetch_and_store = PythonOperator(
        task_id="fetch_naver_nasdaq_stocks",
        python_callable=fetch_and_upsert_naver_nasdaq_stocks,
        provide_context=True,
    ) 