"""
장중 시장 모니터링 DAG (Market Pulse Monitor)
- 평일 09:10~15:20, 10분 간격 실행
- Layer 1: 상시 규칙 기반 (지수 급변, 종목 급등락, 환율)
- Layer 2: 모닝리포트 체크리스트 조건 모니터링
- 텔레그램 알림 발송
"""

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable


default_args = {
    "owner": "bip",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 0,  # 알림 중복 발송 방지 — 재시도 시 텔레그램 메시지가 중복으로 나감
    "retry_delay": timedelta(minutes=2),
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


def parse_morning_checklist(**context):
    """
    체크리스트 확인 + 장전 에이전트 분석 발송
    - 체크리스트는 report_builder가 리포트 생성 시점에 DB에 이미 저장
    - 이 task는 DB에서 읽어서 에이전트 분석만 수행
    """
    load_env_vars()

    from reports.market_monitor import load_checklist, send_checklist_status

    checklist_text = load_checklist()
    if not checklist_text:
        print("⚠️ 오늘 체크리스트 없음 (모닝리포트 미생성?)")
        return {"saved": False}

    print(f"📋 DB 체크리스트 로드 완료 ({len(checklist_text)}자)")

    # 장전 체크리스트 에이전트 분석 + 텔레그램 발송
    try:
        result = send_checklist_status(override_hour=8)  # pre_market
        print(f"📢 장전 체크리스트 분석 발송: {result}")
    except Exception as e:
        print(f"⚠️ 장전 분석 발송 실패: {e}")

    return {"saved": True, "length": len(checklist_text)}


def run_market_monitor(**context):
    """
    장중 모니터링 실행 (10분마다)
    - Layer 1: 상시 규칙 체크
    - Layer 2: 체크리스트 룰 체크
    - 조건 충족 시 텔레그램 알림
    - 정기 시간(09:00, 10:00, 12:00, 14:30)에 체크리스트 현황 리포트
    """
    load_env_vars()

    from reports.market_monitor import run_monitor_cycle, send_checklist_status

    result = run_monitor_cycle()

    print(f"📊 모니터링: {result['timestamp']} | "
          f"L1: {result.get('layer1', 0)}건 | "
          f"발송: {result['alerts_sent']}건")

    # 정기 현황 리포트 (09:30, 10:00, 12:00, 14:30 KST)
    # 09:00 → 09:30: 동시호가 체결 + 수급 첫 집계(~20분) 대기
    from zoneinfo import ZoneInfo
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    status_times = [(9, 30), (10, 0), (12, 0), (14, 30)]
    for h, m in status_times:
        if now_kst.hour == h and m <= now_kst.minute < m + 10:
            status = send_checklist_status()
            print(f"📋 정기 현황 발송: {status}")
            break

    return result


def send_market_open_summary(**context):
    """장 시작 알림"""
    load_env_vars()

    from reports.market_monitor import fetch_market_indices
    from reports.telegram_sender import send_telegram_message

    indices = fetch_market_indices()
    kospi = indices.get("kospi", {})
    kosdaq = indices.get("kosdaq", {})
    fx = indices.get("usd_krw", {})

    msg = (
        "🔔 *장 시작 — Market Pulse*\n\n"
        f"KOSPI: {kospi.get('value', 0):,.2f} ({kospi.get('change_pct', 0):+.1f}%)\n"
        f"KOSDAQ: {kosdaq.get('value', 0):,.2f} ({kosdaq.get('change_pct', 0):+.1f}%)\n"
        f"원/달러: {fx.get('value', 0):,.1f}원\n\n"
        "📋 체크리스트 모니터링 시작합니다."
    )

    send_telegram_message(msg)
    print("✅ 장 시작 알림 발송")


def send_checklist_status_report(**context):
    """체크리스트 정기 현황 리포트"""
    load_env_vars()

    from reports.market_monitor import send_checklist_status

    result = send_checklist_status()
    print(f"📋 체크리스트 현황: {result['rules_triggered']}/{result['rules_total']} 달성")
    return result


def send_market_close_summary(**context):
    """장 마감 요약 — 에이전트가 체크리스트 전체 결과 정리"""
    load_env_vars()

    from reports.market_monitor import send_checklist_status

    result = send_checklist_status(override_hour=16)  # close phase
    print(f"✅ 장 마감 요약 발송: {result}")


def run_preopen_analysis_task(**context):
    """
    장 시작 임박 예상 체결가 분석 (08:40 KST)
    - BIP-Agents API 호출 → Haiku 분석 → 텔레그램 발송
    - agent_audit_log 기록 (거버넌스 3-3)
    """
    load_env_vars()

    import requests
    import re as _re
    from reports.telegram_sender import send_telegram_message

    try:
        from utils.audited_llm import record_agent_audit
    except Exception:
        record_agent_audit = None

    agent_url = os.getenv("BIP_AGENTS_API_URL", "http://bip-agents-api:8100")

    try:
        resp = requests.post(f"{agent_url}/api/preopen/analyze", timeout=90)
    except Exception as e:
        print(f"⚠️ preopen API 호출 실패: {e}")
        return {"sent": False, "error": str(e)}

    if resp.status_code != 200:
        print(f"⚠️ preopen API 오류: {resp.status_code} {resp.text[:200]}")
        return {"sent": False, "status_code": resp.status_code}

    body = resp.json()
    analysis = body.get("analysis_result", "")
    audit_meta = body.get("audit") or {}

    # 감사 기록
    if record_agent_audit and audit_meta:
        try:
            record_agent_audit(
                agent_name=audit_meta.get("agent_name", "market_monitor_preopen"),
                agent_type=audit_meta.get("agent_type", "monitor"),
                status=audit_meta.get("status", "success"),
                llm_provider=audit_meta.get("llm_provider"),
                llm_model=audit_meta.get("llm_model"),
                prompt_class=audit_meta.get("prompt_class"),
                prompt_tokens=audit_meta.get("prompt_tokens"),
                completion_tokens=audit_meta.get("completion_tokens"),
                tools_used=audit_meta.get("tools_used"),
                data_sources=audit_meta.get("data_sources"),
                referenced_tables=audit_meta.get("referenced_tables"),
                execution_ms=audit_meta.get("execution_ms"),
                run_id=audit_meta.get("run_id"),
                triggered_by="airflow_schedule",
                error_message=audit_meta.get("error_message") or None,
            )
        except Exception as audit_err:
            print(f"⚠️ 감사 로그 기록 실패: {audit_err}")

    if not analysis:
        print("⚠️ 분석 결과 비어있음")
        return {"sent": False}

    # 텔레그램 마크다운 정리
    analysis = _re.sub(r'\*\*(.+?)\*\*', r'*\1*', analysis)
    analysis = _re.sub(r'^#{1,3}\s+', '', analysis, flags=_re.MULTILINE)
    analysis = _re.sub(r'-{3,}', '———————————————', analysis)

    success = send_telegram_message(analysis)
    print(f"✅ preopen 분석 발송: {success}")
    return {"sent": success, "audit_run_id": audit_meta.get("run_id")}


# ──────────────────────────────────
# DAG 1: 체크리스트 파싱 (1일 1회)
# ──────────────────────────────────
with DAG(
    dag_id="market_monitor_checklist_parse",
    default_args=default_args,
    description="모닝리포트 체크리스트 → 모니터링 룰 파싱 (Haiku)",
    schedule_interval="25 8 * * 1-5",  # 평일 08:25 KST (모닝리포트 08:10+6분 여유)
    start_date=datetime(2026, 4, 1),
    catchup=False,
    tags=["monitor", "checklist", "telegram"],
) as dag_parse:

    parse_task = PythonOperator(
        task_id="parse_morning_checklist",
        python_callable=parse_morning_checklist,
    )


# ──────────────────────────────────
# DAG 1-2: 장 시작 임박 예상 체결가 (08:40 KST)
# ──────────────────────────────────
with DAG(
    dag_id="market_monitor_preopen",
    default_args=default_args,
    description="장 시작 임박 예상 체결가 + 갭 방향 분석 (BIP-Agents)",
    schedule_interval="40 8 * * 1-5",  # 평일 08:40 KST (동시호가 10분 경과)
    start_date=datetime(2026, 4, 1),
    catchup=False,
    tags=["monitor", "preopen", "telegram"],
) as dag_preopen:

    preopen_task = PythonOperator(
        task_id="run_preopen_analysis",
        python_callable=run_preopen_analysis_task,
    )


# ──────────────────────────────────
# DAG 2: 장중 모니터링 (10분 간격)
# ──────────────────────────────────
with DAG(
    dag_id="market_monitor_intraday",
    default_args=default_args,
    description="장중 시장 모니터링 — 10분 간격 (텔레그램 알림)",
    schedule_interval="*/10 9-15 * * 1-5",  # 평일 09:00~15:50, 10분마다
    start_date=datetime(2026, 4, 1),
    catchup=False,
    tags=["monitor", "intraday", "telegram"],
) as dag_monitor:

    monitor_task = PythonOperator(
        task_id="run_market_monitor",
        python_callable=run_market_monitor,
    )


# ──────────────────────────────────
# DAG 3: 장 마감 요약
# ──────────────────────────────────
with DAG(
    dag_id="market_monitor_close",
    default_args=default_args,
    description="장 마감 텔레그램 요약 + 체크리스트 최종 결과",
    schedule_interval="35 15 * * 1-5",  # 평일 15:35 KST
    start_date=datetime(2026, 4, 1),
    catchup=False,
    tags=["monitor", "telegram"],
) as dag_close:

    close_task = PythonOperator(
        task_id="send_market_close",
        python_callable=send_market_close_summary,
    )
