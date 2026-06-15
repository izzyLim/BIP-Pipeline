"""
해외 AI 뉴스 다이제스트 수집 DAG
- 8시간마다 RSS 수집 + Haiku 요약 (06:30 / 14:30 / 22:30 KST)
  - 빅이벤트 날 RSS 롤오버 보험: 여러 스냅샷을 남겨 모닝리포트가 통합 조회
- TechCrunch AI / VentureBeat AI / The Verge AI (Airflow Variable 'OVERSEAS_AI_RSS_FEEDS'로 override)
- 결과: overseas_ai_news_digest 테이블 → 모닝리포트가 최근 24h 다이제스트들을 통합
"""

import os
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "bip",
    "retries": 0,
}


def _load_env_vars():
    """Airflow Variables에서 환경변수 로드"""
    try:
        from airflow.models import Variable
        env_map = {
            "PG_PASSWORD": "pg_password",
            "ANTHROPIC_API_KEY": "anthropic_api_key",
        }
        for env_key, var_key in env_map.items():
            val = Variable.get(var_key, default_var="")
            if val:
                os.environ[env_key] = val
    except Exception as e:
        print(f"⚠️ Variable 로드 실패: {e}")


def collect_overseas_ai_news_task(**context):
    """RSS 수집 + Haiku 요약 + DB 저장"""
    _load_env_vars()

    from reports.overseas_ai_news_collector import collect_and_save_overseas_digest

    result = collect_and_save_overseas_digest(hours=24)

    if result["success"]:
        print(f"✅ 해외 AI 뉴스 다이제스트 수집 완료: {result['raw_count']}건 → 요약 저장")
        print(f"   다이제스트:\n{result['digest']}")
    else:
        print(f"⚠️ 해외 AI 뉴스 수집 실패 또는 0건")

    return result


with DAG(
    dag_id="overseas_ai_news_digest",
    default_args=default_args,
    description="8시간마다 해외 AI 뉴스(RSS) 수집 + Haiku 요약 → overseas_ai_news_digest 저장",
    schedule_interval="30 6,14,22 * * *",   # KST 06:30 / 14:30 / 22:30 (RSS 롤오버 보험)
    start_date=datetime(2026, 6, 1),
    catchup=False,
    tags=["news", "ai", "overseas", "haiku"],
) as dag:

    collect_task = PythonOperator(
        task_id="collect_overseas_ai_news",
        python_callable=collect_overseas_ai_news_task,
        provide_context=True,
    )
