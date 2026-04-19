"""
종목 추천 에이전트 DAG
- 평일 18:00 KST 자동 실행
- BIP-Agents API 호출 → 스크리닝 + Bull/Bear 토론
- 텔레그램 발송 + stock_recommendations DB 저장
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
    "retries": 0,  # 중복 발송 방지
    "retry_delay": timedelta(minutes=5),
}


def load_env_vars():
    """Airflow Variable → 환경변수"""
    var_map = {
        "TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID": "TELEGRAM_CHAT_ID",
        "TELEGRAM_CHANNEL_ID": "TELEGRAM_CHANNEL_ID",
    }
    for var_key, env_key in var_map.items():
        try:
            val = Variable.get(var_key, default_var="")
            if val:
                os.environ[env_key] = val
        except Exception:
            pass


def run_daily_screener(**context):
    """종목 스크리닝 + 토론 + 텔레그램 발송"""
    load_env_vars()

    import requests
    import re as _re
    from reports.telegram_sender import send_telegram_message

    agent_url = os.getenv("BIP_AGENTS_API_URL", "http://bip-agents-api:8100")
    top_n = int(os.getenv("SCREENER_TOP_N_DEBATE", "10"))

    try:
        resp = requests.post(
            f"{agent_url}/api/screener/daily",
            params={"top_n_debate": top_n},
            timeout=600,
        )
    except Exception as e:
        print(f"스크리너 API 호출 실패: {e}")
        return {"sent": False, "error": str(e)}

    if resp.status_code != 200:
        print(f"스크리너 API 오류: {resp.status_code} {resp.text[:200]}")
        return {"sent": False, "status_code": resp.status_code}

    body = resp.json()
    analysis = body.get("analysis_result", "")
    recs = body.get("recommendations", [])

    print(f"스크리닝 완료: {len(recs)}개 추천")

    if not analysis:
        print("분석 결과 비어있음")
        return {"sent": False}

    # 텔레그램 발송 (DM만 — 채널 발송은 백테스팅 검증 후 전환)
    success = send_telegram_message(analysis, test=True)
    print(f"텔레그램 발송: {success}")

    # stock_recommendations DB 저장
    saved = _save_recommendations(recs, body.get("market_context", {}))
    print(f"DB 저장: {saved}건")

    return {
        "sent": success,
        "count": len(recs),
        "saved": saved,
        "tickers": [r.get("ticker", "") for r in recs],
    }


def _extract_manager_summary(decision: str) -> str:
    """Manager 출력에서 핵심 한 줄 추출"""
    if not decision:
        return ""
    import re
    m = re.search(r'핵심 한 줄:\s*(.+)', decision)
    if m:
        return m.group(1).strip()[:200]
    m = re.search(r'판정 근거:\s*(.+)', decision)
    if m:
        return m.group(1).strip()[:200]
    return ""


def _calc_confidence_for_save(r: dict) -> str:
    """Deterministic 확신도 계산 (DB 저장용)"""
    conditions = [
        r.get("direction", "neutral") in ("bull_strong", "bull_win"),
        (r.get("risk_reward") or 0) >= 2.0,
        (r.get("total_score") or 0) >= 48,
        (r.get("foreign_net_buy") or 0) > 0 or (r.get("institution_net_buy") or 0) > 0,
        (r.get("tech_score") or 0) >= 15,
        (r.get("target_upside_pct") or 0) >= 15,
    ]
    both_buy = (r.get("foreign_net_buy") or 0) > 0 and (r.get("institution_net_buy") or 0) > 0
    met = sum(1 for c in conditions if c) + (1 if both_buy else 0)
    if met >= 5:
        return "높음"
    elif met >= 3:
        return "중간"
    return "낮음"


def _save_recommendations(recs: list, market_context: dict) -> int:
    """추천 결과를 stock_recommendations + recommendation_performance 초기 행 저장"""
    if not recs:
        return 0

    from sqlalchemy import create_engine, text
    from datetime import date

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pg_pw = os.getenv("PG_PASSWORD", "")
        database_url = f"postgresql+psycopg2://user:{pg_pw}@bip-postgres:5432/stockdb"
    engine = create_engine(database_url)
    run_date = date.today().isoformat()
    saved = 0

    for r in recs:
        ticker = r.get("ticker", "")
        if not ticker:
            continue

        # 개별 트랜잭션 (1건 실패해도 나머지 저장)
        try:
            with engine.begin() as conn:
                # stock_recommendations UPSERT (전체 컬럼 갱신)
                conn.execute(text("""
                    INSERT INTO stock_recommendations (
                        run_date, ticker, stock_name, recommendation_type,
                        total_score, signal_level,
                        tech_score, flow_score, valuation_score, macro_score,
                        entry_price, target_price_short, target_price_mid,
                        stop_loss, risk_reward, support_1, resistance_1,
                        grade, direction, preset_tags, close_at_rec, market_type,
                        bull_memo, bear_memo, manager_summary, confidence,
                        signals, comment
                    ) VALUES (
                        :run_date, :ticker, :stock_name, :rec_type,
                        :total_score, :signal_level,
                        :tech_score, :flow_score, :valuation_score, :macro_score,
                        :entry_price, :target_short, :target_mid,
                        :stop_loss, :risk_reward, :support_1, :resistance_1,
                        :grade, :direction, :preset_tags, :close_at_rec, :market_type,
                        :bull_memo, :bear_memo, :manager_summary, :confidence,
                        :signals, :comment
                    )
                    ON CONFLICT (run_date, ticker, recommendation_type) DO UPDATE SET
                        stock_name = EXCLUDED.stock_name,
                        total_score = EXCLUDED.total_score,
                        signal_level = EXCLUDED.signal_level,
                        tech_score = EXCLUDED.tech_score,
                        flow_score = EXCLUDED.flow_score,
                        valuation_score = EXCLUDED.valuation_score,
                        macro_score = EXCLUDED.macro_score,
                        entry_price = EXCLUDED.entry_price,
                        target_price_short = EXCLUDED.target_price_short,
                        target_price_mid = EXCLUDED.target_price_mid,
                        stop_loss = EXCLUDED.stop_loss,
                        risk_reward = EXCLUDED.risk_reward,
                        support_1 = EXCLUDED.support_1,
                        resistance_1 = EXCLUDED.resistance_1,
                        grade = EXCLUDED.grade,
                        direction = EXCLUDED.direction,
                        preset_tags = EXCLUDED.preset_tags,
                        close_at_rec = EXCLUDED.close_at_rec,
                        market_type = EXCLUDED.market_type,
                        bull_memo = EXCLUDED.bull_memo,
                        bear_memo = EXCLUDED.bear_memo,
                        manager_summary = EXCLUDED.manager_summary,
                        confidence = EXCLUDED.confidence
                """), {
                    "run_date": run_date,
                    "ticker": ticker,
                    "stock_name": r.get("stock_name", ""),
                    "rec_type": "daily",
                    "total_score": r.get("total_score"),
                    "signal_level": r.get("signal_level"),
                    "tech_score": r.get("tech_score"),
                    "flow_score": r.get("flow_score"),
                    "valuation_score": r.get("valuation_score"),
                    "macro_score": r.get("macro_score"),
                    "entry_price": r.get("close"),
                    "target_short": r.get("target_short"),
                    "target_mid": r.get("target_mid"),
                    "stop_loss": r.get("stop_loss"),
                    "risk_reward": r.get("risk_reward"),
                    "support_1": r.get("support_1"),
                    "resistance_1": r.get("resistance_1"),
                    "grade": r.get("grade"),
                    "direction": r.get("direction"),
                    "preset_tags": r.get("strategies") or [],
                    "close_at_rec": r.get("close"),
                    "market_type": r.get("market_type"),
                    "bull_memo": r.get("bull_memo"),
                    "bear_memo": r.get("bear_memo"),
                    "manager_summary": _extract_manager_summary(r.get("manager_decision", "")),
                    "confidence": _calc_confidence_for_save(r),
                    "signals": None,
                    "comment": None,
                })

                # recommendation_performance 초기 행 (pending)
                conn.execute(text("""
                    INSERT INTO recommendation_performance (run_date, ticker, recommendation_type, status)
                    VALUES (:run_date, :ticker, :rec_type, 'pending')
                    ON CONFLICT (run_date, ticker, recommendation_type) DO NOTHING
                """), {
                    "run_date": run_date,
                    "ticker": ticker,
                    "rec_type": "daily",
                })

            saved += 1
        except Exception as e:
            print(f"DB 저장 실패 ({ticker}): {e}")

    engine.dispose()
    return saved


# 일일 자동 스크리닝 DAG
with DAG(
    dag_id="stock_screener_daily",
    default_args=default_args,
    description="종목 추천 에이전트 — 스크리닝 + Bull/Bear 토론 + 텔레그램 발송",
    schedule_interval="0 19 * * 1-5",  # 평일 19:00 KST (analytics DAG 17:30 이후 여유)
    start_date=datetime(2026, 4, 12),
    catchup=False,
    tags=["screener", "agent", "telegram"],
) as dag:

    screener_task = PythonOperator(
        task_id="run_daily_screener",
        python_callable=run_daily_screener,
    )
