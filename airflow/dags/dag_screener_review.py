"""
종목 추천 주간 리뷰 DAG
- 월요일 09:00 KST
- 프리셋/등급/스코어 구간별 성과 집계 → 텔레그램 리포트
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "bip",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=5),
}


def generate_weekly_review(**context):
    """주간 성과 리뷰 생성 + 텔레그램 발송"""
    import os
    from sqlalchemy import create_engine, text
    from airflow.models import Variable

    # 텔레그램 환경변수
    for key in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
        try:
            val = Variable.get(key, default_var="")
            if val:
                os.environ[key] = val
        except Exception:
            pass

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pg_pw = os.getenv("PG_PASSWORD", "")
        database_url = f"postgresql+psycopg2://user:{pg_pw}@bip-postgres:5432/stockdb"
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # 전체 요약
        summary = conn.execute(text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE p.status IN ('closed', 'done')) AS closed,
                ROUND(AVG(p.d5_return_pct)::numeric, 2) AS avg_d5,
                ROUND(AVG(p.d20_return_pct)::numeric, 2) AS avg_d20,
                ROUND(100.0 * COUNT(*) FILTER (WHERE p.target_hit) / NULLIF(COUNT(*) FILTER (WHERE p.status IN ('closed', 'done')), 0), 1) AS target_rate,
                ROUND(100.0 * COUNT(*) FILTER (WHERE p.stop_hit) / NULLIF(COUNT(*) FILTER (WHERE p.status IN ('closed', 'done')), 0), 1) AS stop_rate,
                ROUND(100.0 * COUNT(*) FILTER (WHERE p.scenario_result = 'target_first') / NULLIF(COUNT(*) FILTER (WHERE p.status IN ('closed', 'done')), 0), 1) AS win_rate
            FROM recommendation_performance p
            JOIN stock_recommendations r USING (run_date, ticker, recommendation_type)
        """)).fetchone()

        # 등급별 성과 (closed 기준으로 통일)
        by_grade = conn.execute(text("""
            SELECT r.grade,
                   COUNT(*) AS cnt,
                   ROUND(AVG(p.d5_return_pct)::numeric, 2) AS avg_d5,
                   ROUND(AVG(p.d20_return_pct)::numeric, 2) AS avg_d20,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE p.scenario_result = 'target_first') / NULLIF(COUNT(*), 0), 1) AS win_rate
            FROM recommendation_performance p
            JOIN stock_recommendations r USING (run_date, ticker, recommendation_type)
            WHERE p.status IN ('closed', 'done')
            GROUP BY r.grade
            ORDER BY CASE r.grade
                WHEN 'Buy' THEN 1 WHEN 'Overweight' THEN 2
                WHEN 'Hold' THEN 3 WHEN 'Underweight' THEN 4 ELSE 5 END
        """)).fetchall()

        # 프리셋별 성과 (closed 기준)
        by_preset = conn.execute(text("""
            SELECT preset,
                   COUNT(*) AS cnt,
                   ROUND(AVG(p.d5_return_pct)::numeric, 2) AS avg_d5,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE p.scenario_result = 'target_first') / NULLIF(COUNT(*), 0), 1) AS win_rate
            FROM recommendation_performance p
            JOIN stock_recommendations r USING (run_date, ticker, recommendation_type),
                 UNNEST(r.preset_tags) AS preset
            WHERE p.status IN ('closed', 'done')
            GROUP BY preset
            ORDER BY win_rate DESC NULLS LAST
        """)).fetchall()

        # 최근 종목별 성과 (10건)
        recent = conn.execute(text("""
            SELECT r.run_date, r.stock_name, r.ticker, r.grade,
                   p.d1_return_pct, p.d5_return_pct, p.d20_return_pct,
                   p.scenario_result, p.status
            FROM recommendation_performance p
            JOIN stock_recommendations r USING (run_date, ticker, recommendation_type)
            WHERE p.d1_return_pct IS NOT NULL
            ORDER BY r.run_date DESC, r.total_score DESC
            LIMIT 10
        """)).fetchall()

    # 메시지 생성
    GRADE_LABEL = {
        "Buy": "적극 매수", "Overweight": "매수 추천", "Hold": "관망",
        "Underweight": "매수 주의", "Sell": "매도",
    }
    SCENARIO_LABEL = {
        "target_first": "목표 도달", "stop_first": "손절", "neither": "미도달",
    }

    lines = [f"📊 *BIP 종목 추천 주간 성과*\n"]
    lines.append(f"누적 {summary.total}건 (확정 {summary.closed}건)\n")

    # 전체 요약
    if summary.closed and summary.closed > 0:
        lines.append("━━━ 전체 요약 ━━━")
        if summary.avg_d5 is not None:
            lines.append(f"평균 D+5 수익률: {summary.avg_d5:+.1f}%")
        if summary.avg_d20 is not None:
            lines.append(f"평균 D+20 수익률: {summary.avg_d20:+.1f}%")
        if summary.win_rate is not None:
            lines.append(f"승률 (목표 선도달): {summary.win_rate:.0f}%")
        if summary.stop_rate is not None:
            lines.append(f"손절률: {summary.stop_rate:.0f}%")
        lines.append("")

    # 등급별
    if by_grade:
        lines.append("━━━ 등급별 ━━━")
        for g in by_grade:
            label = GRADE_LABEL.get(g.grade, g.grade)
            d5 = f"D+5 {g.avg_d5:+.1f}%" if g.avg_d5 is not None else ""
            d20 = f"D+20 {g.avg_d20:+.1f}%" if g.avg_d20 is not None else ""
            wr = f"승률 {g.win_rate:.0f}%" if g.win_rate is not None else ""
            lines.append(f"{label}: {g.cnt}건 {d5} {d20} {wr}")
        lines.append("")

    # 프리셋별
    if by_preset:
        lines.append("━━━ 프리셋별 ━━━")
        for p in by_preset:
            wr = f"승률 {p.win_rate:.0f}%" if p.win_rate is not None else ""
            lines.append(f"{p.preset}: {p.cnt}건 D+5 {p.avg_d5:+.1f}% {wr}")
        lines.append("")

    # 최근 종목
    if recent:
        lines.append("━━━ 최근 종목 ━━━")
        for r in recent:
            label = GRADE_LABEL.get(r.grade, r.grade)
            scenario = SCENARIO_LABEL.get(r.scenario_result, r.status or "")
            d5 = f"D+5 {r.d5_return_pct:+.1f}%" if r.d5_return_pct is not None else ""
            lines.append(f"{r.run_date} {r.stock_name} ({label}) {d5} [{scenario}]")
        lines.append("")

    lines.append("———————————————")
    lines.append("_자동 생성된 성과 리포트입니다._")

    message = "\n".join(lines)
    print(message)

    # 텔레그램 발송 (DM만)
    from reports.telegram_sender import send_telegram_message
    success = send_telegram_message(message, test=True)
    print(f"텔레그램 발송: {success}")

    return {"sent": success, "total": summary.total, "closed": summary.closed}


with DAG(
    dag_id="screener_weekly_review",
    default_args=default_args,
    description="종목 추천 주간 성과 리뷰 — 등급/프리셋별 집계 + 텔레그램",
    schedule_interval="0 9 * * 1",  # 월요일 09:00 KST
    start_date=datetime(2026, 4, 19),
    catchup=False,
    tags=["screener", "backtest", "review"],
) as dag:

    review_task = PythonOperator(
        task_id="generate_weekly_review",
        python_callable=generate_weekly_review,
    )
