from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from time import sleep
from utils.fetch import fetch_price_data
from utils.db import insert_to_postgres, get_active_tickers, get_new_active_tickers, get_pg_conn
from utils.config import PG_CONN_INFO


def load_1d():
    with get_pg_conn(PG_CONN_INFO) as conn:
        ticker_df = get_new_active_tickers(conn, table_name="stock_price_1d")
        ticker_list = ticker_df["ticker"].tolist()

        
        today = datetime.utcnow().date()
        start_date = (today - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        for ticker in ticker_list:
            df = fetch_price_data(
                ticker=ticker,
                interval='1d',
                start=start_date,
                end=end_date
            )
            insert_to_postgres(df, 'stock_price_1d', PG_CONN_INFO)
            sleep(1)


def load_1wk():
    with get_pg_conn(PG_CONN_INFO) as conn:
        ticker_df = get_new_active_tickers(conn, table_name="stock_price_1wk")
        ticker_list = ticker_df["ticker"].tolist()
    
        today = datetime.utcnow().date()
        start_date = (today - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        for ticker in ticker_list:
            df = fetch_price_data(
                ticker=ticker,
                interval='1wk',
                start=start_date,
                end=end_date
            )
            insert_to_postgres(df, 'stock_price_1wk', PG_CONN_INFO)
            sleep(1)


def load_1mo():
    with get_pg_conn(PG_CONN_INFO) as conn:
        ticker_df = get_new_active_tickers(conn, table_name="stock_price_1mo")
        ticker_list = ticker_df["ticker"].tolist()

        today = datetime.utcnow().date()
        start_date = (today - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        for ticker in ticker_list:
            df = fetch_price_data(
                ticker=ticker,
                interval='1mo',
                start=start_date,
                end=end_date
            )
            insert_to_postgres(df, 'stock_price_1mo', PG_CONN_INFO)
            sleep(1)


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

    task_1d >> task_1wk >> task_1mo