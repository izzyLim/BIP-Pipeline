"""
[02_price_kr_ohlcv_daily]
한국 주식 일봉 OHLCV 수집 (Yahoo Finance)
- 증분 적재: stock_price_1d 티커별 마지막 적재일 이후 데이터만 수집
- 신규 종목 적재: stock_info에는 있으나 stock_price_1d에 없는 종목 → 최근 2년치 히스토리
- 4개 그룹 병렬 처리
- 실행 조건: 01_info_kr_stocks_daily 완료 후 (한국 종목 등록 전제)
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.fetch import fetch_price_data
from utils.db import get_pg_conn, insert_to_postgres
from utils.config import PG_CONN_INFO
from utils.lineage import register_table_lineage_async
from time import sleep
import logging

logger = logging.getLogger(__name__)

SLEEP_SEC = 0.5
BATCH_SIZE = 200
NUM_PARALLEL_BATCHES = 4


def load_kr_new_tickers():
    """신규 한국 종목 히스토리 적재 (최근 2년)"""
    today = datetime.utcnow().date()
    end_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=730)).strftime("%Y-%m-%d")

    with get_pg_conn(PG_CONN_INFO) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT si.ticker
                FROM stock_info si
                LEFT JOIN (SELECT DISTINCT ticker FROM stock_price_1d) sp ON si.ticker = sp.ticker
                WHERE sp.ticker IS NULL
                  AND (si.ticker LIKE %s OR si.ticker LIKE %s)
                ORDER BY si.ticker
            """, ('%.KS', '%.KQ'))
            new_tickers = [row[0] for row in cur.fetchall()]

        if not new_tickers:
            logger.info("신규 한국 종목 없음")
            return

        logger.info(f"신규 한국 종목 {len(new_tickers)}개 히스토리 적재 시작")

        success_count = error_count = 0
        for idx, ticker in enumerate(new_tickers, 1):
            try:
                if idx % 50 == 0:
                    logger.info(f"신규 종목 진행: {idx}/{len(new_tickers)}")

                df = fetch_price_data(ticker=ticker, interval="1d", start=start_date, end=end_date)
                if not df.empty:
                    insert_to_postgres(df, "stock_price_1d", conn, batch_size=100, max_retries=3)
                    success_count += 1
                sleep(SLEEP_SEC)

            except Exception as e:
                logger.warning(f"{ticker} 신규 적재 실패: {e}")
                error_count += 1

        logger.info(f"신규 종목 완료: 성공 {success_count}, 실패 {error_count}")


def load_kr_incremental_group(group_id: int):
    """
    병렬 그룹별 한국 종목 증분 적재
    - DB 연결 1회만 열고 그룹 전체 처리
    - 티커별 last_date를 초기에 한 번만 조회
    """
    today = datetime.utcnow().date()
    end_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    with get_pg_conn(PG_CONN_INFO) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sp.ticker, MAX(sp.timestamp) AS last_date
                FROM stock_price_1d sp
                JOIN stock_info si ON sp.ticker = si.ticker
                WHERE si.ticker LIKE %s OR si.ticker LIKE %s
                GROUP BY sp.ticker
                ORDER BY sp.ticker
            """, ('%.KS', '%.KQ'))
            last_dates = {row[0]: row[1] for row in cur.fetchall()}

        tickers = list(last_dates.keys())
        if not tickers:
            logger.info("증분 수집할 한국 티커 없음")
            return

        total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        batches_for_group = [b for b in range(total_batches) if b % NUM_PARALLEL_BATCHES == group_id]

        logger.info(f"KR Group {group_id}: {len(batches_for_group)}개 배치 처리 예정")

        success_count = skip_count = error_count = 0

        for batch_num in batches_for_group:
            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, len(tickers))
            batch_tickers = tickers[start_idx:end_idx]

            logger.info(f"KR Group {group_id} / Batch {batch_num + 1}/{total_batches}: {len(batch_tickers)}개 티커")

            for idx, ticker in enumerate(batch_tickers, 1):
                last_date = last_dates.get(ticker)
                if not last_date:
                    skip_count += 1
                    continue

                start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")

                if start_date >= end_date:
                    skip_count += 1
                    continue

                try:
                    if idx % 50 == 0:
                        logger.info(f"KR Group {group_id} / Batch {batch_num + 1}: {idx}/{len(batch_tickers)}")

                    df = fetch_price_data(ticker=ticker, interval="1d", start=start_date, end=end_date)
                    if df.empty:
                        skip_count += 1
                    else:
                        insert_to_postgres(df, "stock_price_1d", conn, batch_size=100, max_retries=3)
                        success_count += 1
                    sleep(SLEEP_SEC)

                except Exception as e:
                    logger.warning(f"{ticker} 적재 실패: {e}")
                    error_count += 1

        logger.info(f"KR Group {group_id} 완료: 성공 {success_count}, 스킵 {skip_count}, 실패 {error_count}")


def load_kr_group_0(): load_kr_incremental_group(0)
def load_kr_group_1(): load_kr_incremental_group(1)
def load_kr_group_2(): load_kr_incremental_group(2)
def load_kr_group_3(): load_kr_incremental_group(3)


default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="02_price_kr_ohlcv_daily",
    default_args=default_args,
    description="한국 주식 일봉 OHLCV 증분 수집 + 신규 종목 히스토리 적재 (Yahoo Finance)",
    schedule_interval="0 16 * * 1-5",  # 평일 16:00 KST (정규장 마감 후)
    catchup=False,
    tags=["price", "daily", "KR", "KOSPI", "KOSDAQ"],
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=3),
    concurrency=4,
) as dag:

    load_new = PythonOperator(
        task_id="load_kr_new_tickers",
        python_callable=load_kr_new_tickers,
        execution_timeout=timedelta(hours=2),
    )

    task_group_0 = PythonOperator(task_id="load_kr_group_0", python_callable=load_kr_group_0, execution_timeout=timedelta(hours=1))
    task_group_1 = PythonOperator(task_id="load_kr_group_1", python_callable=load_kr_group_1, execution_timeout=timedelta(hours=1))
    task_group_2 = PythonOperator(task_id="load_kr_group_2", python_callable=load_kr_group_2, execution_timeout=timedelta(hours=1))
    task_group_3 = PythonOperator(task_id="load_kr_group_3", python_callable=load_kr_group_3, execution_timeout=timedelta(hours=1))

    lineage_task = PythonOperator(
        task_id="register_lineage",
        python_callable=lambda: register_table_lineage_async("stock_price_1d"),
        execution_timeout=timedelta(minutes=5),
    )

    # 신규 종목 먼저, 이후 증분 병렬, 완료 후 lineage 등록
    load_new >> [task_group_0, task_group_1, task_group_2, task_group_3] >> lineage_task
