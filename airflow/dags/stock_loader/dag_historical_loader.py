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

LOOKBACK_YEARS = 5
SLEEP_SEC = 0.3
BATCH_SIZE = 100  # 히스토리컬은 데이터량이 많으므로 더 작은 배치


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
        ticker_df = get_new_active_tickers(conn, table_name=table_name)
        tickers = ticker_df["ticker"].tolist() if not ticker_df.empty else []
        if not tickers:
            logger.info(f"No new tickers for {table_name}")
            return

        total_tickers = len(tickers)
        logger.info(f"Processing {total_tickers} new tickers for {table_name}")

        success_count = 0
        skip_count = 0
        error_count = 0

        for idx, ticker in enumerate(tickers, 1):
            try:
                # 진행상황 로깅 (매 50개마다)
                if idx % 50 == 0 or idx == 1:
                    logger.info(f"{table_name}: Processing {idx}/{total_tickers} ({ticker})")

                df = fetch_price_data(
                    ticker=ticker,
                    interval=interval,
                    start=start_date,
                    end=end_date
                )
                if df.empty:
                    skip_count += 1
                else:
                    insert_to_postgres(df, table_name, conn, batch_size=300, max_retries=5)
                    success_count += 1
                sleep(SLEEP_SEC)
            except Exception as e:
                logger.warning(f"{ticker} {interval} load error: {e}")
                error_count += 1
                continue

        logger.info(f"{table_name} completed: {success_count} success, {skip_count} skipped, {error_count} errors")


def load_1d():
    _load_interval("1d", "stock_price_1d")


def load_1wk():
    _load_interval("1wk", "stock_price_1wk")


def load_1mo():
    _load_interval("1mo", "stock_price_1mo")


default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="load_historical_stock_data",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["stock", "historical"],
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=6),  # 병렬 실행이므로 가장 긴 태스크 기준
    concurrency=3,  # DAG 내 동시 실행 태스크 수
) as dag:
    task_1d = PythonOperator(
        task_id="load_1d_data",
        python_callable=load_1d,
        execution_timeout=timedelta(hours=5),
        pool="default_pool",
    )
    task_1wk = PythonOperator(
        task_id="load_1wk_data",
        python_callable=load_1wk,
        execution_timeout=timedelta(hours=2),
        pool="default_pool",
    )
    task_1mo = PythonOperator(
        task_id="load_1mo_data",
        python_callable=load_1mo,
        execution_timeout=timedelta(hours=1),
        pool="default_pool",
    )

    # 병렬 실행: 각 테이블은 독립적이므로 동시에 처리 가능
    # 의존성 없음 = 자동으로 병렬 실행
    [task_1d, task_1wk, task_1mo]