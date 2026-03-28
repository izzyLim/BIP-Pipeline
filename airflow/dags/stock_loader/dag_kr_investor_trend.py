"""
[05_kr_investor_trend_daily]
한국 주식 투자자별 거래 데이터 일일 수집 (네이버 금융)
- 외국인·기관 순매수량
- 외국인 보유 비중 (지분율)
- stock_price_1d 테이블 업데이트
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.db import get_pg_conn
from utils.config import PG_CONN_INFO
from utils.lineage import register_table_lineage_async
import logging
import requests
from bs4 import BeautifulSoup
from time import sleep
import re

logger = logging.getLogger(__name__)

BATCH_SIZE = 100  # 한 번에 처리할 종목 수
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}


def get_kr_tickers_with_prices():
    """주가 데이터가 있는 한국 종목 목록 조회 (최근 7일 내 데이터 있는 것만)"""
    query = """
        SELECT DISTINCT sp.ticker
        FROM stock_price_1d sp
        JOIN stock_info si ON sp.ticker = si.ticker
        WHERE (sp.ticker LIKE '%%.KS' OR sp.ticker LIKE '%%.KQ')
        AND sp.timestamp >= NOW() - INTERVAL '7 days'
        ORDER BY sp.ticker
    """
    with get_pg_conn(PG_CONN_INFO) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return [row[0] for row in cur.fetchall()]


def convert_ticker_to_krx(yahoo_ticker: str) -> str:
    """
    Yahoo 티커를 KRX 종목코드로 변환
    005930.KS -> 005930
    035720.KQ -> 035720
    """
    return yahoo_ticker.split('.')[0]


def parse_number(text: str) -> int:
    """
    네이버 금융 숫자 파싱
    '+1,534,865' -> 1534865
    '-3,721,894' -> -3721894
    """
    if not text:
        return None
    text = text.strip().replace(',', '')
    if text in ['', '-']:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def fetch_investor_data_naver(ticker: str) -> list:
    """
    네이버 금융에서 투자자별 순매수 데이터 조회
    Returns: list of dict [{date, foreign, institution, foreign_ownership_pct}, ...]
    """
    krx_code = convert_ticker_to_krx(ticker)
    url = f'https://finance.naver.com/item/frgn.naver?code={krx_code}'

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 외국인 보유율 추출
        foreign_pct = None
        pct_elem = soup.select_one('table.lwidth tr:nth-child(3) td')
        if pct_elem:
            pct_text = pct_elem.get_text(strip=True).replace('%', '')
            try:
                foreign_pct = float(pct_text)
            except:
                pass

        # 투자자별 매매동향 테이블
        tables = soup.find_all('table', class_='type2')
        if len(tables) < 2:
            return []

        table = tables[1]
        rows = table.find_all('tr')

        result = []
        for row in rows[2:]:  # 헤더 건너뛰기
            cells = row.find_all('td')
            if len(cells) < 7:
                continue

            date_text = cells[0].get_text(strip=True)
            if not date_text or '.' not in date_text:
                continue

            # 날짜 파싱 (2026.03.04 -> 2026-03-04)
            try:
                date_parts = date_text.split('.')
                trade_date = f"{date_parts[0]}-{date_parts[1].zfill(2)}-{date_parts[2].zfill(2)}"
            except:
                continue

            institution = parse_number(cells[5].get_text(strip=True))
            foreign = parse_number(cells[6].get_text(strip=True))

            result.append({
                'trade_date': trade_date,
                'foreign_buy_volume': foreign,
                'institution_buy_volume': institution,
                'foreign_ownership_pct': foreign_pct,  # 현재 보유율 (모든 날짜에 동일)
            })

        return result

    except Exception as e:
        logger.warning(f"Failed to fetch investor data for {ticker}: {e}")
        return []


def update_investor_volumes(batch_num: int = 0, **context):
    """투자자별 거래량 및 외국인 보유 비중 데이터 업데이트 (네이버 금융)"""

    tickers = get_kr_tickers_with_prices()
    if not tickers:
        logger.info("No Korean tickers with price data found")
        return

    total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
    start_idx = batch_num * BATCH_SIZE
    end_idx = min(start_idx + BATCH_SIZE, len(tickers))

    if start_idx >= len(tickers):
        logger.info(f"Batch {batch_num} out of range")
        return

    batch_tickers = tickers[start_idx:end_idx]
    logger.info(f"Processing batch {batch_num + 1}/{total_batches}: {len(batch_tickers)} tickers")

    update_count = 0
    row_count = 0
    error_count = 0

    with get_pg_conn(PG_CONN_INFO) as conn:
        for ticker in batch_tickers:
            try:
                # 네이버 금융에서 데이터 조회
                investor_data = fetch_investor_data_naver(ticker)
                if not investor_data:
                    continue

                with conn.cursor() as cur:
                    for data in investor_data:
                        trade_date = data['trade_date']
                        foreign_vol = data['foreign_buy_volume']
                        inst_vol = data['institution_buy_volume']
                        foreign_pct = data['foreign_ownership_pct']

                        # 개인 순매수 = -(외국인 + 기관) 으로 추정
                        indiv_vol = None
                        if foreign_vol is not None and inst_vol is not None:
                            indiv_vol = -(foreign_vol + inst_vol)

                        cur.execute("""
                            UPDATE stock_price_1d
                            SET foreign_buy_volume = COALESCE(%s, foreign_buy_volume),
                                institution_buy_volume = COALESCE(%s, institution_buy_volume),
                                individual_buy_volume = COALESCE(%s, individual_buy_volume),
                                foreign_ownership_pct = COALESCE(%s, foreign_ownership_pct)
                            WHERE ticker = %s
                            AND DATE(timestamp_kst) = %s
                        """, (foreign_vol, inst_vol, indiv_vol, foreign_pct, ticker, trade_date))
                        row_count += cur.rowcount

                conn.commit()
                update_count += 1

                # Rate limiting
                sleep(0.1)

            except Exception as e:
                logger.error(f"Error updating {ticker}: {e}")
                error_count += 1
                continue

    logger.info(f"Batch {batch_num}: Updated {update_count} tickers, {row_count} rows, {error_count} errors")


NUM_BATCHES = 45   # KOSPI+KOSDAQ 약 4,500종목 / 100 = 45배치


default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="05_kr_investor_trend_daily",
    default_args=default_args,
    description="한국 주식 투자자별 거래량 일일 수집 (외국인·기관 순매수, 네이버 금융)",
    schedule_interval="30 18 * * 1-5",  # 평일 18:30 KST (KRX 수급 데이터 확정 후)
    catchup=False,
    max_active_runs=1,
    max_active_tasks=5,  # 45개 배치 중 동시 실행 5개로 제한 → OOM 방지
    dagrun_timeout=timedelta(hours=3),
    tags=["kr", "investor", "daily", "KOSPI", "KOSDAQ"],
) as dag:

    tasks = []
    for i in range(NUM_BATCHES):
        task = PythonOperator(
            task_id=f"update_investor_batch_{i:02d}",
            python_callable=update_investor_volumes,
            op_kwargs={"batch_num": i},
            execution_timeout=timedelta(minutes=30),
        )
        tasks.append(task)

    lineage_task = PythonOperator(
        task_id="register_lineage",
        python_callable=lambda: register_table_lineage_async("stock_price_1d"),
        execution_timeout=timedelta(minutes=5),
    )

    # 모든 배치 병렬 실행, 완료 후 lineage 등록
    tasks >> lineage_task
