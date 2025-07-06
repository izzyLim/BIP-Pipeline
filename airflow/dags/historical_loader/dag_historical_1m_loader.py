# dags/dag_historical_1m_loader.py

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.fetch import fetch_price_data
from utils.db import insert_to_postgres, get_active_tickers
from utils.config import PG_CONN_INFO




from datetime import datetime, timedelta
from utils.fetch import fetch_price_data
from utils.db import insert_to_postgres, get_active_tickers
from utils.config import PG_CONN_INFO


def load_1m():
    tickers = get_active_tickers(PG_CONN_INFO)
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=30)

    for ticker in tickers:
        for i in range(30):
            day = start_date + timedelta(days=i)
            start_str = day.strftime("%Y-%m-%d")
            end_str = (day + timedelta(days=1)).strftime("%Y-%m-%d")

            try:
                df = fetch_price_data(
                    ticker=ticker,
                    interval='1m',
                    start=start_str,
                    end=end_str
                )
                if df.empty:
                    print(f"[INFO] {ticker} {start_str}: 데이터 없음 (시장 휴장일 등)")
                    continue

                insert_to_postgres(df, 'stock_price_1m', PG_CONN_INFO)

            except Exception as e:
                print(f"[WARN] {ticker} {start_str} 처리 중 오류 발생: {e}")


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
