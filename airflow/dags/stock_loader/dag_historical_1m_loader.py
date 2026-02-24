# dags/dag_historical_1m_loader.py

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from time import sleep
from utils.fetch import fetch_price_data
from utils.db import (
    get_new_active_tickers,
    get_pg_conn,
    insert_to_postgres,
)
from utils.config import PG_CONN_INFO
import logging

logger = logging.getLogger(__name__)


def load_1m_batch(batch_size: int = 5, days_per_batch: int = 7):
    """
    1분봉 데이터를 배치 단위로 처리
    batch_size: 한 번에 처리할 ticker 수
    days_per_batch: 한 번에 처리할 일수
    """
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=30)

    with get_pg_conn(PG_CONN_INFO) as conn:
        ticker_df = get_new_active_tickers(conn, table_name="stock_price_1m")
        tickers = ticker_df["ticker"].tolist()

        if not tickers:
            logger.info("No new tickers for 1m data loading")
            return

        logger.info(f"Processing {len(tickers)} tickers for 1m data")

        success_count = 0
        error_count = 0

        # ticker를 배치로 나누어 처리
        for i in range(0, len(tickers), batch_size):
            batch_tickers = tickers[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(tickers) + batch_size - 1) // batch_size

            logger.info(f"Processing ticker batch {batch_num}/{total_batches}")

            for ticker in batch_tickers:
                try:
                    # 날짜를 작은 단위로 나누어 처리
                    for day_offset in range(0, 30, days_per_batch):
                        batch_start = start_date + timedelta(days=day_offset)
                        batch_end = min(batch_start + timedelta(days=days_per_batch), today)

                        start_str = batch_start.strftime("%Y-%m-%d")
                        end_str = batch_end.strftime("%Y-%m-%d")

                        df = fetch_price_data(
                            ticker=ticker,
                            interval="1m",
                            start=start_str,
                            end=end_str
                        )

                        if df.empty:
                            continue

                        insert_to_postgres(df, "stock_price_1m", conn, batch_size=50, max_retries=3)
                        sleep(1.0)

                    success_count += 1
                except Exception as e:
                    logger.warning(f"{ticker} 1m data load error: {e}")
                    error_count += 1
                    continue

                sleep(0.5)

        logger.info(f"1m data load completed: {success_count} success, {error_count} errors")


def load_1m_limited():
    """
    제한된 리소스로 1분봉 데이터 로드 (소수 ticker만)
    """
    load_1m_batch(batch_size=3, days_per_batch=5)


default_args = {
    "owner": "airflow",
    "retries": 0,  # 1분봉은 양이 많아 재시도 비활성화
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="load_historical_1m_data",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule_interval="@weekly",  # 주간 실행
    catchup=False,
    tags=["stock", "historical", "ohlcv", "1m"],
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=6),  # DAG 전체 타임아웃 6시간
) as dag:
    task_1m = PythonOperator(
        task_id="load_1m_data",
        python_callable=load_1m_limited,
        execution_timeout=timedelta(hours=5),  # 태스크 타임아웃 5시간
    )
