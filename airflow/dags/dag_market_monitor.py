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
    "retries": 1,
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
    모닝리포트에서 체크리스트 추출 → DB에 원문 저장
    """
    load_env_vars()

    from reports.market_monitor import save_checklist
    from pathlib import Path
    import re

    report_dir = Path("/tmp")
    from zoneinfo import ZoneInfo
    today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")

    checklist_text = ""

    # HTML 리포트에서 체크리스트 섹션 추출
    for f in sorted(report_dir.glob(f"report_{today_str}*.html"), reverse=True):
        try:
            content = f.read_text(encoding="utf-8")
            lines = []
            in_checklist = False
            for line in content.split("\n"):
                if "체크리스트" in line:
                    in_checklist = True
                    continue
                if in_checklist and ("□" in line or "☐" in line):
                    # <br> → 줄바꿈 변환 후 HTML 태그 제거
                    chunk = line.replace("<br>", "\n").replace("<br/>", "\n")
                    chunk = re.sub(r'<[^>]+>', '', chunk)
                    chunk = chunk.replace("☐", "□")
                    for sub in chunk.split("\n"):
                        sub = sub.strip()
                        if sub:
                            lines.append(sub)
                elif in_checklist and lines and ("---" in line or "</div>" in line):
                    break
            if lines:
                checklist_text = "\n".join(lines)
                print(f"📋 리포트에서 체크리스트 추출: {f.name} ({len(lines)}줄)")
                break
        except Exception as e:
            print(f"리포트 파싱 실패: {e}")

    if not checklist_text:
        print("⚠️ 체크리스트 추출 실패")
        return {"saved": False}

    # DB에 원문 저장
    save_checklist(checklist_text)
    print(f"✅ 체크리스트 DB 저장 완료 ({len(checklist_text)}자)")

    # 장전 체크리스트 에이전트 분석 + 텔레그램 발송
    try:
        from reports.market_monitor import send_checklist_status
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
          f"L1: {result['layer1']}건, L2: {result['layer2']}건 | "
          f"발송: {result['alerts_sent']}건")

    # 정기 현황 리포트 (09:00, 10:00, 12:00, 14:30)
    now = datetime.now()
    status_times = [(9, 0), (10, 0), (12, 0), (14, 30)]
    for h, m in status_times:
        if now.hour == h and now.minute < 10:  # 10분 간격이라 :00~:09 사이 매칭
            status = send_checklist_status()
            print(f"📋 정기 현황 발송: {status['rules_triggered']}/{status['rules_total']}")
            break

    return result


def send_market_open_summary(**context):
    """장 시작 알림"""
    load_env_vars()

    from reports.market_monitor import fetch_market_indices, reset_daily_alerts
    from reports.telegram_sender import send_telegram_message

    reset_daily_alerts()

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
