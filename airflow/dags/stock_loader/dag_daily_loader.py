from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.fetch import fetch_price_data
from utils.db import get_pg_conn, get_new_active_tickers, insert_to_postgres
from utils.config import PG_CONN_INFO
from time import sleep
import logging

logger = logging.getLogger(__name__)

SLEEP_SEC = 0.3
BATCH_SIZE = 500  # 한 번에 처리할 티커 수
NUM_PARALLEL_BATCHES = 4  # 병렬 실행할 배치 그룹 수



def load_incremental_batch(batch_num: int = 0):
    """
    티커별 가장 최근 적재 날짜 이후의 증분 데이터를 배치 단위로 적재하는 함수
    batch_num: 처리할 배치 번호 (0부터 시작)
    """
    today = datetime.utcnow().date()
    end_date = today.strftime("%Y-%m-%d")

    # 티커별 가장 최근 적재 날짜를 가져오는 쿼리
    last_date_query = """
        SELECT ticker, MAX(timestamp) AS last_date
        FROM stock_price_1d
        GROUP BY ticker
        ORDER BY ticker
    """

    with get_pg_conn(PG_CONN_INFO) as conn:
        # 티커별 마지막 적재 날짜 조회
        with conn.cursor() as cur:
            cur.execute(last_date_query)
            last_dates = {row[0]: row[1] for row in cur.fetchall()}

        tickers = list(last_dates.keys())
        if not tickers:
            logger.info("No tickers found for incremental load.")
            return

        # 배치 범위 계산
        total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        start_idx = batch_num * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(tickers))

        if start_idx >= len(tickers):
            logger.info(f"Batch {batch_num} is out of range (total batches: {total_batches})")
            return

        batch_tickers = tickers[start_idx:end_idx]
        logger.info(f"Processing batch {batch_num + 1}/{total_batches}: tickers {start_idx + 1}-{end_idx} of {len(tickers)}")

        success_count = 0
        skip_count = 0
        error_count = 0

        for idx, ticker in enumerate(batch_tickers, 1):
            start_date = last_dates.get(ticker)
            if start_date:
                start_date = (start_date + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                skip_count += 1
                continue

            try:
                if idx % 100 == 0:
                    logger.info(f"Batch {batch_num + 1}: Progress {idx}/{len(batch_tickers)}")

                df = fetch_price_data(
                    ticker=ticker,
                    interval="1d",
                    start=start_date,
                    end=end_date
                )
                if df.empty:
                    skip_count += 1
                else:
                    insert_to_postgres(df, "stock_price_1d", conn, batch_size=100, max_retries=3)
                    success_count += 1
                sleep(SLEEP_SEC)
            except Exception as e:
                logger.warning(f"{ticker} incremental load error: {e}")
                error_count += 1
                continue

        logger.info(f"Batch {batch_num + 1} completed: {success_count} success, {skip_count} skipped, {error_count} errors")


def load_incremental_group(group_id: int):
    """
    병렬 그룹별 배치 처리
    group_id: 0 ~ NUM_PARALLEL_BATCHES-1
    각 그룹은 자신에게 할당된 배치들만 처리
    """
    with get_pg_conn(PG_CONN_INFO) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT ticker) FROM stock_price_1d")
            total_tickers = cur.fetchone()[0]

    total_batches = (total_tickers + BATCH_SIZE - 1) // BATCH_SIZE

    # 이 그룹이 처리할 배치 번호들 계산
    batches_for_group = [b for b in range(total_batches) if b % NUM_PARALLEL_BATCHES == group_id]

    logger.info(f"Group {group_id}: Processing batches {batches_for_group} (total {len(batches_for_group)} batches)")

    for batch_num in batches_for_group:
        load_incremental_batch(batch_num)


# 각 그룹별 함수 생성
def load_group_0():
    load_incremental_group(0)

def load_group_1():
    load_incremental_group(1)

def load_group_2():
    load_incremental_group(2)

def load_group_3():
    load_incremental_group(3)


default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="daily_stock_data_loader",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["stock", "daily", "incremental"],
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=3),  # 병렬 실행으로 시간 단축
    concurrency=4,  # DAG 내 동시 실행 태스크 수
) as dag:

    # 4개의 병렬 태스크로 분할 실행
    task_group_0 = PythonOperator(
        task_id="load_incremental_group_0",
        python_callable=load_group_0,
        execution_timeout=timedelta(hours=2),
        pool="default_pool",
    )
    task_group_1 = PythonOperator(
        task_id="load_incremental_group_1",
        python_callable=load_group_1,
        execution_timeout=timedelta(hours=2),
        pool="default_pool",
    )
    task_group_2 = PythonOperator(
        task_id="load_incremental_group_2",
        python_callable=load_group_2,
        execution_timeout=timedelta(hours=2),
        pool="default_pool",
    )
    task_group_3 = PythonOperator(
        task_id="load_incremental_group_3",
        python_callable=load_group_3,
        execution_timeout=timedelta(hours=2),
        pool="default_pool",
    )

    # 병렬 실행 (의존성 없음)
    [task_group_0, task_group_1, task_group_2, task_group_3]