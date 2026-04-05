"""
[06a_sec_edgar_hot]
SEC EDGAR hot universe 준실시간 수집 — UI freshness 경로
- 핫 유니버스(시총 상위 100 ∪ user_watchlist(US) ∪ holding(US))에 대해
  submissions/CIK{cik}.json을 10분 주기로 호출하여 신규 공시를 빠르게 적재
- 주 UI 표시 데이터는 06b_sec_edgar_reconcile의 nightly full reconcile이 담당하며,
  이 DAG는 주요/관심 종목에 대해 nightly 이전에도 당일 공시가 UI에 보이도록 보장
- 스케줄: 평일 10분 간격 (NYSE 영업시간 내 자동 필터)
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import logging
import os
import time
import requests

from utils.db import get_pg_conn
from utils.config import PG_CONN_INFO

logger = logging.getLogger(__name__)

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "BIP-Pipeline admin@bip-pipeline.com")
SEC_BASE = "https://data.sec.gov"
TARGET_FORMS = {"8-K", "10-K", "10-Q", "4", "4/A", "8-K/A", "10-K/A", "10-Q/A"}
EASTERN = ZoneInfo("America/New_York")
INGEST_SOURCE = "submissions_hot"
LOOKBACK_DAYS = 3

default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
}


def _is_sec_hours() -> bool:
    now_et = datetime.now(EASTERN)
    if now_et.weekday() >= 5:
        return False
    return 6 <= now_et.hour <= 22


def _load_hot_universe(cur) -> list:
    """시총 상위 100 ∪ user_watchlist(US) ∪ holding(US) → (ticker, cik) 리스트"""
    cur.execute("""
        WITH alert_universe AS (
            (SELECT ticker FROM stock_info
             WHERE exchange_code IN ('NSQ','NYS') AND active = TRUE
               AND market_value IS NOT NULL
             ORDER BY market_value DESC
             LIMIT 100)
            UNION
            SELECT w.ticker FROM user_watchlist w
            JOIN stock_info s ON w.ticker = s.ticker
            WHERE s.exchange_code IN ('NSQ','NYS')
            UNION
            SELECT h.ticker FROM holding h
            JOIN stock_info s ON h.ticker = s.ticker
            WHERE s.exchange_code IN ('NSQ','NYS')
        )
        SELECT u.ticker, m.cik
        FROM alert_universe u
        JOIN us_cik_mapping m ON u.ticker = m.ticker
        ORDER BY u.ticker
    """)
    return cur.fetchall()


def poll_hot_universe(**context):
    """
    hot universe의 각 CIK에 대해 submissions/CIK.json 조회 →
    최근 N일 공시 중 sec_filings에 없거나 미완성인 건 upsert.
    이 태스크는 DB만 다룸 (텔레그램은 send_hot_alerts에서).
    """
    if not _is_sec_hours():
        logger.info("SEC 영업시간 외 — 스킵")
        return {"new_filings": 0, "skipped": True}

    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    conn = get_pg_conn(PG_CONN_INFO)
    try:
        with conn.cursor() as cur:
            universe = _load_hot_universe(cur)

        logger.info(f"hot universe: {len(universe)}개 CIK, cutoff: {cutoff}")

        sess = requests.Session()
        sess.headers.update({
            "User-Agent": SEC_USER_AGENT,
            "Accept": "application/json",
        })

        polled = 0
        inserted = 0
        updated = 0
        failed = 0

        with conn.cursor() as cur:
            for ticker, cik in universe:
                try:
                    url = f"{SEC_BASE}/submissions/CIK{cik}.json"
                    resp = sess.get(url, timeout=15)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    failed += 1
                    if failed <= 5:
                        logger.warning(f"{ticker} ({cik}) 조회 실패: {e}")
                    time.sleep(0.12)
                    continue

                recent = data.get("filings", {}).get("recent", {})
                forms = recent.get("form", [])
                accessions = recent.get("accessionNumber", [])
                dates = recent.get("filingDate", [])
                accepted = recent.get("acceptanceDateTime", [])
                docs = recent.get("primaryDocument", [])
                descs = recent.get("primaryDocDescription", [])

                for i in range(len(forms)):
                    if forms[i] not in TARGET_FORMS:
                        continue
                    try:
                        fdate = datetime.strptime(dates[i], "%Y-%m-%d").date()
                    except Exception:
                        continue
                    if fdate < cutoff:
                        continue

                    acc_no = accessions[i]
                    acc_clean = acc_no.replace("-", "")
                    doc = docs[i] if i < len(docs) else ""
                    filing_url = (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{cik.lstrip('0')}/{acc_clean}/{doc}"
                    )
                    desc = descs[i] if i < len(descs) else None

                    cur.execute("""
                        INSERT INTO sec_filings
                            (ticker, cik, accession_no, form_type, filing_date,
                             accepted_dt, description, filing_url, ingest_source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (accession_no) DO UPDATE SET
                            description = COALESCE(EXCLUDED.description, sec_filings.description),
                            filing_url = COALESCE(EXCLUDED.filing_url, sec_filings.filing_url),
                            accepted_dt = COALESCE(EXCLUDED.accepted_dt, sec_filings.accepted_dt)
                        RETURNING (xmax = 0) AS inserted
                    """, (
                        ticker, cik, acc_no, forms[i], dates[i],
                        accepted[i] if i < len(accepted) else None,
                        desc, filing_url, INGEST_SOURCE,
                    ))
                    r = cur.fetchone()
                    if r and r[0]:
                        inserted += 1
                    else:
                        updated += 1

                polled += 1
                time.sleep(0.12)

                if polled % 50 == 0:
                    conn.commit()

        conn.commit()
        logger.info(
            f"완료 — polled {polled}, inserted {inserted}, updated {updated}, failed {failed}"
        )
        return {
            "polled": polled,
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
        }

    finally:
        conn.close()


with DAG(
    dag_id="06a_sec_edgar_hot",
    default_args=default_args,
    description="SEC EDGAR hot universe 준실시간 수집 (UI freshness)",
    schedule_interval="*/10 * * * 1-5",
    catchup=False,
    tags=["US", "SEC", "edgar"],
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=8),
) as dag:

    poll_task = PythonOperator(
        task_id="poll_hot_universe",
        python_callable=poll_hot_universe,
        execution_timeout=timedelta(minutes=5),
    )
