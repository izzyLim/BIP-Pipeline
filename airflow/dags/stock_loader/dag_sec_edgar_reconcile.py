"""
[06b_sec_edgar_reconcile]
SEC EDGAR 공시 nightly full reconcile — UI 주 경로
- us_cik_mapping 전체 CIK(6,151개)에 대해 submissions/CIK{cik}.json 조회
- 최근 N일 공시를 sec_filings에 upsert (기존 레코드는 빈 필드만 보강)
- 신규 보충분은 alert_decision='suppressed_backfill'로 마킹 (재알림 방지)
- UI의 전 종목 공시 내역 completeness를 보장
- 스케줄: 매일 03:00 UTC = 23:00 ET (장 마감 후)
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta, date
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
INGEST_SOURCE = "submissions_nightly"
LOOKBACK_DAYS = 3

default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def reconcile_recent_filings(**context):
    """
    us_cik_mapping의 전 CIK에 대해 submissions/CIK.json 조회 →
    최근 N일 공시를 upsert (기존 레코드는 빈 필드만 보강).
    신규 보충분은 alert_decision='suppressed_backfill' + telegram_sent_at=NOW() 로 재알림 차단.
    """
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)

    conn = get_pg_conn(PG_CONN_INFO)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, cik FROM us_cik_mapping ORDER BY ticker")
            rows = cur.fetchall()

        logger.info(f"보정 대상 CIK: {len(rows)}개, cutoff: {cutoff}")

        sess = requests.Session()
        sess.headers.update({
            "User-Agent": SEC_USER_AGENT,
            "Accept": "application/json",
        })

        polled = 0
        added = 0
        failed = 0

        for ticker, cik in rows:
            try:
                url = f"{SEC_BASE}/submissions/CIK{cik}.json"
                resp = sess.get(url, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                failed += 1
                if failed <= 10:
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

            with conn.cursor() as cur:
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
                    filing_url = (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{cik.lstrip('0')}/{acc_clean}/"
                        f"{docs[i] if i < len(docs) else ''}"
                    )

                    cur.execute("""
                        INSERT INTO sec_filings
                            (ticker, cik, accession_no, form_type, filing_date,
                             accepted_dt, description, filing_url,
                             ingest_source, alert_decision, telegram_sent_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'suppressed_backfill', NOW())
                        ON CONFLICT (accession_no) DO UPDATE SET
                            description = COALESCE(EXCLUDED.description, sec_filings.description),
                            filing_url = COALESCE(EXCLUDED.filing_url, sec_filings.filing_url),
                            accepted_dt = COALESCE(EXCLUDED.accepted_dt, sec_filings.accepted_dt)
                        RETURNING (xmax = 0) AS inserted
                    """, (
                        ticker, cik, acc_no, forms[i], dates[i],
                        accepted[i] if i < len(accepted) else None,
                        descs[i] if i < len(descs) else None,
                        filing_url, INGEST_SOURCE,
                    ))
                    r = cur.fetchone()
                    if r and r[0]:
                        added += 1

            polled += 1
            if polled % 500 == 0:
                conn.commit()
                logger.info(f"[{polled}/{len(rows)}] 진행 중 — 보충 {added}건, 실패 {failed}건")

            time.sleep(0.12)

        conn.commit()
        logger.info(f"완료 — polled {polled}, added {added}, failed {failed}")
        return {"polled": polled, "added": added, "failed": failed}

    finally:
        conn.close()


with DAG(
    dag_id="06b_sec_edgar_reconcile",
    default_args=default_args,
    description="SEC EDGAR 공시 보정 배치 (current feed 누락 보충)",
    schedule_interval="0 3 * * 2-6",  # 03:00 UTC = 23:00 ET 전일
    catchup=False,
    tags=["US", "SEC", "edgar", "reconcile"],
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
) as dag:

    reconcile_task = PythonOperator(
        task_id="reconcile_recent_filings",
        python_callable=reconcile_recent_filings,
        execution_timeout=timedelta(minutes=90),
    )
