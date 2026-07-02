"""
장 마감 브리핑 (Closing Brief)
- 마감 지수 + 수급 + 장중 알림 타임라인 + 뉴스 다이제스트를 종합
- LLM(Haiku)이 "오늘 변동의 원인"을 데이터 근거로 정리
- 아침 모닝리포트 전망(report_outlook_log) 대비 실제 결과 리뷰 포함
- 텔레그램 발송 + closing_brief_log 저장 (회고 조회용)
"""

import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

# reports 모듈 간 flat import 지원 (llm_analyzer_v2 등)
_reports_dir = Path(__file__).resolve().parent
if str(_reports_dir) not in sys.path:
    sys.path.insert(0, str(_reports_dir))

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

DDL = """
CREATE TABLE IF NOT EXISTS closing_brief_log (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL UNIQUE,
    kospi_close NUMERIC,
    kospi_change_pct NUMERIC,
    brief_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
)
"""

BRIEF_PROMPT = """당신은 한국 주식시장 마감 브리핑을 작성하는 애널리스트입니다.
아래는 오늘({today}) 장 마감 시점의 실제 데이터입니다.

## 마감 지수
{indices}

## 투자자별 수급 (KOSPI, 억원)
{flows}

## 업종별 등락 (KRX 공식 업종)
{sectors}

## 장중 이상 신호 타임라인 (모니터링 시스템 기록)
{alerts}

## 오늘 수집된 주요 뉴스
{news}

## 오늘 아침 모닝리포트 전망
{outlook}

---

위 데이터만 근거로 마감 브리핑을 작성하세요. 형식:

📉 *오늘 시장 요약* (2~3문장: 지수 움직임과 강도)

🔍 *변동 요인 분석*
- 오늘 변동의 원인으로 **뉴스/데이터에서 확인되는 것만** 2~3개 bullet로.
- 각 요인마다 근거(뉴스 내용, 수급 수치, 타임라인)를 명시.
- 데이터에서 원인이 확인되지 않으면 "수집된 뉴스에서 명확한 원인 미확인"이라고 쓰세요. 추측으로 채우지 마세요.

📋 *아침 전망 대비*
- 아침 전망(방향/예상범위)과 실제 결과를 1~2문장으로 비교.
- 아침에 기회/리스크로 본 섹터가 실제 업종 등락에서 어땠는지 1~2문장으로 리뷰.
  (아침 섹터 표현과 KRX 업종명이 다를 수 있음 — 의미상 대응되는 업종으로 판단. 대응되는 업종이 없으면 언급 생략.)
- 전망 데이터가 없으면 이 섹션 생략.

⚠️ 주의: 텔레그램 발송용이므로 전체 1,500자 이내. 볼드는 *별표 1개*만 사용 (** 금지). 헤더(#) 금지.
"""


def _get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        pg_user = os.getenv("PG_USER", "user")
        pg_password = os.getenv("PG_PASSWORD")
        pg_host = os.getenv("PG_HOST", "bip-postgres")
        pg_port = os.getenv("PG_PORT", "5432")
        pg_db = os.getenv("PG_DB", "stockdb")
        url = f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
    return create_engine(url)


def _today_kst() -> date:
    return datetime.now(KST).date()


def _format_indices(indices: Dict[str, Any]) -> str:
    lines = []
    for key, label in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ"), ("usd_krw", "원/달러")]:
        d = indices.get(key) or {}
        if d.get("value"):
            lines.append(f"- {label}: {d['value']:,.2f} ({d.get('change_pct', 0):+.2f}%)")
    return "\n".join(lines) or "데이터 없음"


def _format_flows(flows: Dict[str, Any]) -> str:
    if not flows:
        return "데이터 없음"
    return (
        f"- 외국인 {flows.get('foreign', 0):+,}억 / "
        f"기관 {flows.get('institution', 0):+,}억 / "
        f"개인 {flows.get('individual', 0):+,}억"
    )


def _fetch_alerts_timeline(conn, target_date: date) -> str:
    rows = conn.execute(
        text("""
            SELECT created_at AT TIME ZONE 'Asia/Seoul' AS t, level, title
            FROM monitor_alerts
            WHERE (created_at AT TIME ZONE 'Asia/Seoul')::date = :d
            ORDER BY created_at
            LIMIT 30
        """),
        {"d": target_date},
    ).fetchall()
    if not rows:
        return "장중 이상 신호 없음"
    return "\n".join(f"- {r[0].strftime('%H:%M')} {r[1]} {r[2]}" for r in rows)


def _fetch_news_digest(conn, target_date: date) -> str:
    """당일 수집된 뉴스 다이제스트 중 가장 최신 1건 (16:00 수집분 우선)"""
    row = conn.execute(
        text("""
            SELECT digest FROM news_digest
            WHERE (collected_at AT TIME ZONE 'Asia/Seoul')::date = :d
            ORDER BY collected_at DESC
            LIMIT 1
        """),
        {"d": target_date},
    ).fetchone()
    if not row:
        return "당일 뉴스 다이제스트 없음"
    digest = row[0]
    return digest[:3000] if digest else "당일 뉴스 다이제스트 없음"


def _fetch_morning_outlook(conn, target_date: date) -> str:
    row = conn.execute(
        text("""
            SELECT llm_bias, llm_confidence, expected_low, expected_high, key_drivers,
                   bullish_sectors, bearish_sectors
            FROM report_outlook_log
            WHERE report_date = :d
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"d": target_date},
    ).fetchone()
    if not row:
        return "오늘 전망 기록 없음"
    bias, conf, low, high, drivers, bull_sectors, bear_sectors = row
    parts = [f"- 방향: {bias} (confidence {conf})"]
    if low is not None and high is not None:
        parts.append(f"- 예상 범위: {float(low):,.0f} ~ {float(high):,.0f}")
    if drivers:
        parts.append(f"- 핵심 변수: {', '.join(drivers)}")
    if bull_sectors:
        parts.append(f"- 기회 섹터: {', '.join(bull_sectors)}")
    if bear_sectors:
        parts.append(f"- 리스크 섹터: {', '.join(bear_sectors)}")
    return "\n".join(parts)


def _fetch_sector_moves(conn, target_date: date) -> str:
    """당일 KRX 업종 등락률 상위/하위 (dag_krx_sectors 16:35 수집분)"""
    rows = conn.execute(
        text("""
            SELECT REPLACE(indicator_type, 'krx_sector_', '') AS sector, value
            FROM macro_indicators
            WHERE indicator_type LIKE 'krx_sector_%'
              AND indicator_date = :d AND value IS NOT NULL
            ORDER BY value
        """),
        {"d": target_date},
    ).fetchall()
    if not rows:
        return "당일 업종 데이터 미수집"
    bottom = rows[:5]
    top = rows[-5:][::-1]
    lines = ["[상승/선방 상위]"]
    lines += [f"- {r[0]}: {float(r[1]):+.2f}%" for r in top]
    lines.append("[하락 상위]")
    lines += [f"- {r[0]}: {float(r[1]):+.2f}%" for r in bottom]
    return "\n".join(lines)


def gather_brief_data(target_date: Optional[date] = None) -> Dict[str, str]:
    """브리핑 프롬프트에 들어갈 데이터 수집"""
    from reports.market_monitor import fetch_market_indices, fetch_investor_flow

    if target_date is None:
        target_date = _today_kst()

    indices = fetch_market_indices()
    flows = fetch_investor_flow()

    engine = _get_engine()
    with engine.connect() as conn:
        alerts = _fetch_alerts_timeline(conn, target_date)
        news = _fetch_news_digest(conn, target_date)
        outlook = _fetch_morning_outlook(conn, target_date)
        sectors = _fetch_sector_moves(conn, target_date)

    return {
        "today": str(target_date),
        "indices": _format_indices(indices),
        "flows": _format_flows(flows),
        "alerts": alerts,
        "news": news,
        "outlook": outlook,
        "sectors": sectors,
        "_kospi": indices.get("kospi") or {},
    }


def save_brief(target_date: date, brief_text: str, kospi: Dict[str, Any]) -> None:
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text(DDL))
        conn.execute(
            text("""
                INSERT INTO closing_brief_log (report_date, kospi_close, kospi_change_pct, brief_text)
                VALUES (:d, :close, :chg, :brief)
                ON CONFLICT (report_date) DO UPDATE
                SET brief_text = EXCLUDED.brief_text,
                    kospi_close = EXCLUDED.kospi_close,
                    kospi_change_pct = EXCLUDED.kospi_change_pct,
                    created_at = NOW()
            """),
            {
                "d": target_date,
                "close": kospi.get("value"),
                "chg": kospi.get("change_pct"),
                "brief": brief_text,
            },
        )


def send_closing_brief(test: bool = False) -> Dict[str, Any]:
    """마감 브리핑 생성 → 텔레그램 발송 → DB 저장"""
    from reports.llm_analyzer_v2 import call_haiku
    from reports.telegram_sender import send_telegram_message

    target_date = _today_kst()
    data = gather_brief_data(target_date)
    kospi = data.pop("_kospi")

    prompt = BRIEF_PROMPT.format(**data)
    brief = call_haiku(prompt, prompt_class="closing_brief")

    chg = kospi.get("change_pct", 0)
    header = f"🏁 *장 마감 브리핑* ({target_date})\n\n"
    message = header + brief.strip()

    sent = send_telegram_message(message, test=test)

    try:
        save_brief(target_date, brief.strip(), kospi)
    except Exception as e:
        logger.warning(f"closing_brief_log 저장 실패: {e}")

    logger.info(f"마감 브리핑 발송: {target_date} (KOSPI {chg:+.2f}%, sent={sent})")
    return {"date": str(target_date), "sent": sent, "kospi_change_pct": chg}
