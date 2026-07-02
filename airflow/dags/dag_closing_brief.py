"""
장 마감 브리핑 DAG
- 평일 16:10 KST (16:00 뉴스 다이제스트 수집 완료 후)
- 마감 지수 + 수급 + 장중 알림 + 뉴스를 LLM이 종합해 "오늘 변동 원인" 정리
- 텔레그램 발송 + closing_brief_log 저장
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

from utils.lineage import register_table_lineage_async

default_args = {
    "owner": "bip",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 0,  # 재시도 시 텔레그램 중복 발송 방지
}


def load_env_vars():
    """Airflow Variable → 환경변수 설정"""
    var_map = {
        "TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID": "TELEGRAM_CHAT_ID",
        "TELEGRAM_CHANNEL_ID": "TELEGRAM_CHANNEL_ID",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
    }
    for var_key, env_key in var_map.items():
        try:
            val = Variable.get(var_key, default_var="")
            if val:
                os.environ[env_key] = val
        except Exception:
            pass


def run_closing_brief(**context):
    from utils.market_calendar import is_market_open
    if not is_market_open():
        print("📅 휴장일 — 마감 브리핑 스킵")
        return {"skipped": True, "reason": "market_closed"}

    load_env_vars()

    from reports.closing_brief import send_closing_brief
    result = send_closing_brief(test=False)
    print(f"✅ 마감 브리핑: {result}")
    return result


with DAG(
    dag_id="closing_brief_daily",
    default_args=default_args,
    description="장 마감 브리핑 — 오늘 변동 원인 분석 (텔레그램)",
    schedule_interval="50 16 * * 1-5",  # 평일 16:50 KST (뉴스 16:00 + KRX 업종 16:35 수집 후)
    start_date=datetime(2026, 7, 1),
    catchup=False,
    tags=["monitor", "telegram", "brief"],
) as dag:

    brief_task = PythonOperator(
        task_id="send_closing_brief",
        python_callable=run_closing_brief,
        execution_timeout=timedelta(minutes=10),
    )

    lineage_task = PythonOperator(
        task_id="register_lineage",
        python_callable=lambda: register_table_lineage_async("closing_brief_log"),
        execution_timeout=timedelta(minutes=5),
    )

    brief_task >> lineage_task
