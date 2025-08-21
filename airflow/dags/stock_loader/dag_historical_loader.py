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

LOOKBACK_YEARS = 5
SLEEP_SEC = 0.5  # 조금 줄여도 무난하면 조정


def _load_interval(interval: str, table_name: str):
    """
    interval: yfinance 스타일 ('1d','1wk','1mo')
    table_name: 대응 테이블
    모든 DB 호출은 하나의 커넥션 재사용
    """
    today = datetime.utcnow().date()
    start_date = (today - timedelta(days=LOOKBACK_YEARS * 365)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    with get_pg_conn(PG_CONN_INFO) as conn:
        # 변경: ticker 조회도 conn 사용
        ticker_df = get_new_active_tickers(conn, table_name=table_name)
        tickers = ticker_df["ticker"].tolist() if not ticker_df.empty else []
        if not tickers:
            print(f"[INFO] No new tickers for {table_name}")
            return

        for ticker in tickers:
            try:
                df = fetch_price_data(
                    ticker=ticker,
                    interval=interval,
                    start=start_date,
                    end=end_date
                )
                if df.empty:
                    print(f"[INFO] {ticker} {interval}: no data")
                else:
                    insert_to_postgres(df, table_name, conn)
                sleep(SLEEP_SEC)
            except Exception as e:
                print(f"[WARN] {ticker} {interval} load error: {e}")


def load_1d():
    _load_interval("1d", "stock_price_1d")


def load_1wk():
    _load_interval("1wk", "stock_price_1wk")


def load_1mo():
    _load_interval("1mo", "stock_price_1mo")


with DAG(
    dag_id="load_historical_stock_data",
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["stock", "historical"]
) as dag:
    task_1d = PythonOperator(
        task_id="load_1d_data",
        python_callable=load_1d
    )
    task_1wk = PythonOperator(
        task_id="load_1wk_data",
        python_callable=load_1wk
    )
    task_1mo = PythonOperator(
        task_id="load_1mo_data",
        python_callable=load_1mo
    )

    task_1d, task_1wk, task_1mo