"""
뉴스 다이제스트 수집 DAG
- 4시간마다 네이버 뉴스 수집 → Haiku 요약 → news_digest 테이블 저장
- 주말 포함 (월요일 모닝리포트에 주말 이슈 반영)
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
            "NAVER_CLIENT_ID": "naver_client_id",
            "NAVER_CLIENT_SECRET": "naver_client_secret",
            "ANTHROPIC_API_KEY": "anthropic_api_key",
        }
        for env_key, var_key in env_map.items():
            val = Variable.get(var_key, default_var="")
            if val:
                os.environ[env_key] = val
    except Exception as e:
        print(f"⚠️ Variable 로드 실패: {e}")


def collect_news_digest_task(**context):
    """뉴스 다이제스트 수집 + 요약 + DB 저장"""
    _load_env_vars()

    from reports.news_digest_collector import collect_and_save_digest

    result = collect_and_save_digest()

    if result["success"]:
        print(f"✅ 뉴스 다이제스트 수집 완료: {result['raw_count']}건 → 요약 저장")
        print(f"   다이제스트:\n{result['digest']}")
    else:
        print(f"⚠️ 뉴스 다이제스트 수집 실패 (뉴스 0건)")

    return result


with DAG(
    dag_id="news_digest_collector",
    default_args=default_args,
    description="4시간마다 뉴스 수집 + Haiku 요약 → news_digest 저장 (주말 포함)",
    schedule_interval="0 */4 * * *",  # 매일 4시간마다 (00, 04, 08, 12, 16, 20 KST)
    start_date=datetime(2026, 4, 1),
    catchup=False,
    tags=["news", "digest", "haiku"],
) as dag:

    collect_task = PythonOperator(
        task_id="collect_news_digest",
        python_callable=collect_news_digest_task,
        provide_context=True,
    )
