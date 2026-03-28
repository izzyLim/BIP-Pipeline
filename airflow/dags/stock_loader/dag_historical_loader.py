"""
[02_price_us_historical_manual]
미국 주식 히스토리컬 적재 (신규 종목 전용, 수동 실행)
- stock_info에는 있으나 stock_price_1d에 없는 신규 종목만 처리
- 최근 5년치 일봉 적재 (주봉/월봉은 1d로부터 계산 가능하므로 수집 제외)
- 스케줄 없음 (수동 트리거): 신규 종목 대량 등록 시 1회 실행
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from time import sleep
from utils.fetch import fetch_price_data
from utils.db import get_new_active_tickers, get_pg_conn, insert_to_postgres
from utils.config import PG_CONN_INFO
import logging

logger = logging.getLogger(__name__)

LOOKBACK_YEARS = 5
SLEEP_SEC = 0.3


def _load_interval(interval: str, table_name: str):
    """
    신규 종목에 대해 interval 단위 히스토리컬 데이터 적재
    - DB 연결 1회 재사용
    - 이미 데이터 있는 종목은 자동 제외 (get_new_active_tickers)
    """
    today = datetime.utcnow().date()
    start_date = (today - timedelta(days=LOOKBACK_YEARS * 365)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    with get_pg_conn(PG_CONN_INFO) as conn:
        ticker_df = get_new_active_tickers(conn, table_name=table_name)
        tickers = ticker_df["ticker"].tolist() if not ticker_df.empty else []

        if not tickers:
            logger.info(f"{table_name}: 신규 티커 없음, 스킵")
            return

        logger.info(f"{table_name}: {len(tickers)}개 신규 티커 적재 시작")

        success_count = skip_count = error_count = 0

        for idx, ticker in enumerate(tickers, 1):
            try:
                if idx % 50 == 0 or idx == 1:
                    logger.info(f"{table_name}: {idx}/{len(tickers)} ({ticker})")

                df = fetch_price_data(ticker=ticker, interval=interval, start=start_date, end=end_date)
                if df.empty:
                    skip_count += 1
                else:
                    insert_to_postgres(df, table_name, conn, batch_size=300, max_retries=5)
                    success_count += 1
                sleep(SLEEP_SEC)

            except Exception as e:
                logger.warning(f"{ticker} {interval} 적재 실패: {e}")
                error_count += 1

        logger.info(f"{table_name} 완료: 성공 {success_count}, 스킵 {skip_count}, 실패 {error_count}")


def load_1d(): _load_interval("1d", "stock_price_1d")


default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="02_price_us_historical_manual",
    default_args=default_args,
    description="신규 종목 일봉 최대 5년 히스토리컬 적재 (수동 트리거 전용)",
    schedule_interval=None,  # 수동 실행 전용 — 신규 종목 대량 등록 시 트리거
    catchup=False,
    tags=["price", "historical", "manual"],
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=6),
    concurrency=1,
) as dag:

    task_1d = PythonOperator(task_id="load_1d_data", python_callable=load_1d, execution_timeout=timedelta(hours=5), pool="default_pool")
