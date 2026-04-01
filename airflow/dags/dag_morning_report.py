"""
BIP 모닝 브리핑 DAG
- 매일 오전 7시 (KST) 실행
- 매크로 데이터 수집 → 히트맵 생성 → LLM 분석 → 이메일 발송
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable


# 기본 설정
default_args = {
    "owner": "bip",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def send_morning_report(**context):
    """모닝 리포트 생성 및 발송"""
    # Airflow Variable에서 설정 로드 → 환경변수로 설정
    try:
        smtp_user = Variable.get("smtp_user", default_var="")
        smtp_password = Variable.get("smtp_password", default_var="")
        anthropic_key = Variable.get("anthropic_api_key", default_var="")
        openai_key = Variable.get("openai_api_key", default_var="")
        # LLM 모델 선택: gpt-5.4, claude-sonnet, claude-haiku
        llm_model = Variable.get("llm_model", default_var="gpt-5.4")

        if smtp_user:
            os.environ["SMTP_USER"] = smtp_user
            os.environ["FROM_EMAIL"] = smtp_user
        if smtp_password:
            os.environ["SMTP_PASSWORD"] = smtp_password
        if anthropic_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key
        if openai_key:
            os.environ["OPENAI_API_KEY"] = openai_key
        if llm_model:
            os.environ["LLM_MODEL"] = llm_model

        # 텔레그램 봇
        telegram_token = Variable.get("TELEGRAM_BOT_TOKEN", default_var="")
        telegram_chat_id = Variable.get("TELEGRAM_CHAT_ID", default_var="")
        telegram_channel_id = Variable.get("TELEGRAM_CHANNEL_ID", default_var="")
        if telegram_token:
            os.environ["TELEGRAM_BOT_TOKEN"] = telegram_token
        if telegram_chat_id:
            os.environ["TELEGRAM_CHAT_ID"] = telegram_chat_id
        if telegram_channel_id:
            os.environ["TELEGRAM_CHANNEL_ID"] = telegram_channel_id

        # 네이버 API (실시간 뉴스용)
        naver_id = Variable.get("naver_client_id", default_var="")
        naver_secret = Variable.get("naver_client_secret", default_var="")
        if naver_id:
            os.environ["NAVER_CLIENT_ID"] = naver_id
        if naver_secret:
            os.environ["NAVER_CLIENT_SECRET"] = naver_secret
    except Exception as e:
        print(f"⚠️ Variable 로드 실패: {e}")

    from reports.report_builder import build_morning_report, save_report_to_file

    # 수신자 이메일 (Airflow Variable에서 가져오기)
    try:
        to_emails_str = Variable.get("morning_report_emails", default_var="")
        to_emails = [e.strip() for e in to_emails_str.split(",") if e.strip()]
    except Exception:
        to_emails = []

    if not to_emails:
        # 환경변수에서 가져오기
        to_emails_str = os.getenv("MORNING_REPORT_EMAILS", "")
        to_emails = [e.strip() for e in to_emails_str.split(",") if e.strip()]

    if not to_emails:
        raise ValueError(
            "수신자 이메일이 설정되지 않았습니다. "
            "Airflow Variable 'morning_report_emails' 또는 "
            "환경변수 'MORNING_REPORT_EMAILS'를 설정하세요."
        )

    print(f"📧 수신자: {to_emails}")

    # 리포트 생성 및 발송
    result = build_morning_report(
        to_emails=to_emails,
        send=True,
    )

    if not result["success"]:
        raise Exception(f"리포트 발송 실패: {result['error']}")

    # 백업용 파일 저장
    if result.get("html"):
        save_report_to_file(result["html"])

    # OM Lineage 등록 (읽기 전용 — 출력 테이블 없음)
    try:
        from utils.lineage import register_table_lineage_async
        register_table_lineage_async(
            target_table=None,
            source_tables=[
                "stock_info",
                "stock_price_1d",
                "macro_indicators",
                "news",
                "analytics_macro_daily",
                "analytics_stock_daily",
            ]
        )
    except Exception:
        pass  # lineage 실패가 리포트 발송에 영향 주지 않음

    return "리포트 발송 완료"


def test_report_generation(**context):
    """리포트 생성 테스트 (발송 안함)"""
    from reports.report_builder import build_morning_report, save_report_to_file

    result = build_morning_report(
        to_emails=["test@example.com"],
        send=False,
    )

    if result["success"]:
        filepath = save_report_to_file(result["html"])
        print(f"✅ 테스트 리포트 저장: {filepath}")
        return filepath
    else:
        raise Exception(f"리포트 생성 실패: {result['error']}")


def test_report_with_send(**context):
    """리포트 생성 및 테스트 이메일 발송 (단일 수신자)"""
    # Airflow Variable에서 설정 로드
    try:
        smtp_user = Variable.get("smtp_user", default_var="")
        smtp_password = Variable.get("smtp_password", default_var="")
        anthropic_key = Variable.get("anthropic_api_key", default_var="")
        openai_key = Variable.get("openai_api_key", default_var="")
        llm_model = Variable.get("llm_model", default_var="gpt-5.4")
        naver_id = Variable.get("naver_client_id", default_var="")
        naver_secret = Variable.get("naver_client_secret", default_var="")
        telegram_token = Variable.get("TELEGRAM_BOT_TOKEN", default_var="")
        telegram_chat_id = Variable.get("TELEGRAM_CHAT_ID", default_var="")

        if smtp_user:
            os.environ["SMTP_USER"] = smtp_user
            os.environ["FROM_EMAIL"] = smtp_user
        if smtp_password:
            os.environ["SMTP_PASSWORD"] = smtp_password
        if anthropic_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key
        if openai_key:
            os.environ["OPENAI_API_KEY"] = openai_key
        if llm_model:
            os.environ["LLM_MODEL"] = llm_model
        if naver_id:
            os.environ["NAVER_CLIENT_ID"] = naver_id
        if naver_secret:
            os.environ["NAVER_CLIENT_SECRET"] = naver_secret
        if telegram_token:
            os.environ["TELEGRAM_BOT_TOKEN"] = telegram_token
        if telegram_chat_id:
            os.environ["TELEGRAM_CHAT_ID"] = telegram_chat_id
    except Exception as e:
        print(f"⚠️ Variable 로드 실패: {e}")

    from reports.report_builder import build_morning_report, save_report_to_file

    # 테스트 수신자 (단일)
    test_email = "izzy253@gmail.com"
    print(f"📧 테스트 발송 대상: {test_email}")

    result = build_morning_report(
        to_emails=[test_email],
        send=True,
    )

    if result["success"]:
        filepath = save_report_to_file(result["html"])
        print(f"✅ 테스트 리포트 발송 완료 및 저장: {filepath}")
        return f"발송 완료: {test_email}"
    else:
        raise Exception(f"리포트 발송 실패: {result['error']}")


# DAG 정의
with DAG(
    dag_id="morning_report",
    default_args=default_args,
    description="BIP 모닝 브리핑 - 매일 오전 7시 발송",
    schedule_interval="10 8 * * 1-5",  # 평일 08:10 KST → 월-금 아침 발송
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["report", "email", "morning"],
) as dag:

    send_report_task = PythonOperator(
        task_id="send_morning_report",
        python_callable=send_morning_report,
        provide_context=True,
    )


# 테스트용 DAG (수동 실행, 발송 안함)
with DAG(
    dag_id="morning_report_test",
    default_args=default_args,
    description="BIP 모닝 브리핑 테스트 (발송 안함)",
    schedule_interval=None,  # 수동 실행만
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["report", "test"],
) as test_dag:

    test_task = PythonOperator(
        task_id="test_report_generation",
        python_callable=test_report_generation,
        provide_context=True,
    )


# 테스트용 DAG (수동 실행, 단일 이메일 발송)
with DAG(
    dag_id="morning_report_test_send",
    default_args=default_args,
    description="BIP 모닝 브리핑 테스트 (izzy253@gmail.com만 발송)",
    schedule_interval=None,  # 수동 실행만
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["report", "test", "email"],
) as test_send_dag:

    test_send_task = PythonOperator(
        task_id="test_report_with_send",
        python_callable=test_report_with_send,
        provide_context=True,
    )
