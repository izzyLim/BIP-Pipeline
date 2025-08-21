from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.fetch import fetch_price_data
from utils.db import get_pg_conn, get_new_active_tickers, insert_to_postgres
from utils.config import PG_CONN_INFO
from time import sleep


SLEEP_SEC = 0.5



def load_incremental():
    """
    티커별 가장 최근 적재 날짜 이후의 증분 데이터를 적재하는 함수
    """
    today = datetime.utcnow().date()
    end_date = today.strftime("%Y-%m-%d")

    # 티커별 가장 최근 적재 날짜를 가져오는 쿼리
    last_date_query = """
        SELECT ticker, MAX(timestamp) AS last_date
        FROM stock_price_1d
        GROUP BY ticker
    """

    with get_pg_conn(PG_CONN_INFO) as conn:
        # 티커별 마지막 적재 날짜 조회
        with conn.cursor() as cur:
            cur.execute(last_date_query)
            last_dates = {row[0]: row[1] for row in cur.fetchall()}

        # last_date_query로 가져온 모든 티커를 tickers로 설정
        tickers = list(last_dates.keys())
        if not tickers:
            print("[INFO] No tickers found for incremental load.")
            return

        for ticker in tickers:
            # 티커별 시작 날짜 계산
            start_date = last_dates.get(ticker)
            if start_date:
                start_date = (start_date + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                print(f"[INFO] No existing data for {ticker}, skipping.")
                continue

            # 증분 데이터 적재
            try:
                df = fetch_price_data(
                    ticker=ticker,
                    interval="1d",
                    start=start_date,
                    end=end_date
                )
                if df.empty:
                    print(f"[INFO] {ticker}: No data for incremental load.")
                else:
                    insert_to_postgres(df, "stock_price_1d", conn)
                sleep(SLEEP_SEC)
            except Exception as e:
                print(f"[WARN] {ticker} incremental load error: {e}")


with DAG(
    dag_id="daily_stock_data_loader",
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["stock", "daily", "incremental"]
) as dag:


    incremental_load_task = PythonOperator(
        task_id="load_incremental",
        python_callable=load_incremental
    )

incremental_load_task