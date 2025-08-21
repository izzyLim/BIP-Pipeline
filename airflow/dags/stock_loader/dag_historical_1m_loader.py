# dags/dag_historical_1m_loader.py

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from time import sleep
from utils.fetch import fetch_price_data
from utils.db import (
    get_new_active_tickers,   # dict 기반 기존
    get_pg_conn,
    insert_to_postgres,  # 새로 추가한다고 가정 (conn 재사용)
)
from utils.config import PG_CONN_INFO


def load_1m():
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=30)

    with get_pg_conn(PG_CONN_INFO) as conn:
        ticker_df = get_new_active_tickers(conn, table_name="stock_price_1m")
        tickers = ticker_df["ticker"].tolist()

        for ticker in tickers:
            for offset in range(30):
                day = start_date + timedelta(days=offset)
                start_str = day.strftime("%Y-%m-%d")
                end_str = (day + timedelta(days=1)).strftime("%Y-%m-%d")
                try:
                    df = fetch_price_data(
                        ticker=ticker,
                        interval="1m",
                        start=start_str,
                        end=end_str
                    )
                    if df.empty:
                        print(f"[INFO] {ticker} {start_str}: 데이터 없음")
                        continue
                    insert_to_postgres(df, "stock_price_1m", conn)
                    sleep(0.3)
                except Exception as e:
                    print(f"[WARN] {ticker} {start_str} 오류: {e}")


with DAG(
    dag_id="load_historical_1m_data",
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["stock", "historical", "ohlcv", "1m"]
) as dag:
    task_1m = PythonOperator(
        task_id="load_1m_data",
        python_callable=load_1m
    )
