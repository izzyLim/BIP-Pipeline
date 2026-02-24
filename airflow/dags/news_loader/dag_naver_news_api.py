from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import requests
import html
from email.utils import parsedate_to_datetime
from time import sleep

from airflow.hooks.base import BaseHook

from utils.config import PG_CONN_INFO
from utils.db import get_pg_conn, get_active_tickers
from utils.news import fetch_and_upsert_naver_api

DEFAULT_HEADERS = {
    "X-Naver-Client-Id": "IRFLpQeBP9e6JsjwaKCH",
    "X-Naver-Client-Secret": "mcfyo70efz",
    "User-Agent": "Mozilla/5.0"
}
SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"
SLEEP_SEC = 0.2
BATCH_PER_TICKER = 10  # per ticker how many results to fetch

def task_fetch_and_store(**context):
    try:
        conn = BaseHook.get_connection("bip_postgres")
        pg_info = {
            "host": conn.host,
            "port": conn.port or 5432,
            "user": conn.login,
            "password": conn.password,
            "dbname": conn.schema
        }
    except Exception:
        # Airflow Connection이 없으면 utils.config의 PG_CONN_INFO를 사용
        pg_info = PG_CONN_INFO
        print("[WARN] Airflow connection 'bip_postgres' not found — falling back to PG_CONN_INFO")

    with get_pg_conn(pg_info) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM stock_info WHERE COALESCE(active, FALSE) = TRUE;")
            tickers = [row[0] for row in cur.fetchall()]

    if not tickers:
        print("[INFO] No active tickers found.")
        return

    # call orchestrator in utils.news (pass tickers list directly)
    fetch_and_upsert_naver_api(conn_info=pg_info, headers=DEFAULT_HEADERS, tickers=tickers,
                               batch_per_ticker=BATCH_PER_TICKER, sleep_sec=SLEEP_SEC)

default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5)
}

with DAG(
    dag_id="load_naver_news_api",
    default_args=default_args,
    schedule_interval="0 * * * *",  # 매시 정각, 필요에 맞게 조정
    catchup=False,
    tags=["news", "naver", "api"]
) as dag:
    task_fetch_naver_api = PythonOperator(
        task_id="fetch_naver_news_api",
        python_callable=task_fetch_and_store,
    )

task_fetch_naver_api