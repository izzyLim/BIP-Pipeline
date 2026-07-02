"""
모닝리포트 시장 판정(outlook) 추적
- LLM 분석 마지막 줄의 OUTLOOK_JSON을 파싱해 report_outlook_log에 저장
- 장 마감 후 당일 KOSPI 등락률과 비교해 적중 여부(hit) 평가
- 목적: 모델별(Fable/Sonnet/GPT) + 규칙 신호의 방향 판정 적중률 정량 비교
"""

import json
import logging
import os
import re
from datetime import date, datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


def _today_kst() -> date:
    """컨테이너가 UTC라서 date.today()를 쓰면 아침 발송분이 전날로 기록됨 — 반드시 KST 기준."""
    return datetime.now(KST).date()

# neutral 판정 적중 기준: 당일 KOSPI 등락률 ±0.5% 이내
NEUTRAL_BAND_PCT = 0.5

VALID_BIAS = {"bullish", "bearish", "neutral"}

# 규칙 신호(🟢/🔴/🟡) → bias 매핑
RULE_SIGNAL_BIAS = {"🟢": "bullish", "🔴": "bearish", "🟡": "neutral"}

_OUTLOOK_PATTERN = re.compile(
    r"^\s*OUTLOOK_JSON\s*:\s*(\{.*?\})\s*$", re.MULTILINE
)

DDL = """
CREATE TABLE IF NOT EXISTS report_outlook_log (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    llm_model TEXT NOT NULL,
    llm_bias TEXT,
    llm_confidence INT,
    key_drivers TEXT[],
    rule_signal TEXT,
    expected_low NUMERIC,
    expected_high NUMERIC,
    bullish_sectors TEXT[],
    bearish_sectors TEXT[],
    actual_close NUMERIC,
    actual_change_pct NUMERIC,
    range_hit BOOLEAN,
    llm_hit BOOLEAN,
    rule_hit BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    evaluated_at TIMESTAMPTZ,
    UNIQUE (report_date, llm_model)
)
"""

PICKS_DDL = """
CREATE TABLE IF NOT EXISTS report_stock_picks (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    llm_model TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    ticker TEXT,
    stock_name TEXT,
    direction TEXT,
    target_price NUMERIC,
    base_close NUMERIC,
    return_1d NUMERIC,
    return_5d NUMERIC,
    return_20d NUMERIC,
    excess_1d NUMERIC,
    excess_5d NUMERIC,
    excess_20d NUMERIC,
    direction_hit BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (report_date, llm_model, stock_code)
)
"""

PICKS_MIGRATE = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='report_stock_picks' AND column_name='direction') THEN
        ALTER TABLE report_stock_picks ADD COLUMN direction TEXT;
        ALTER TABLE report_stock_picks ADD COLUMN target_price NUMERIC;
        ALTER TABLE report_stock_picks ADD COLUMN direction_hit BOOLEAN;
    END IF;
END $$;
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


def extract_outlook_json(analysis_text: str) -> Tuple[Optional[dict], str]:
    """
    분석 텍스트에서 OUTLOOK_JSON 라인을 추출하고 본문에서 제거.

    Returns:
        (outlook dict 또는 None, OUTLOOK_JSON 라인이 제거된 본문)
    """
    if not analysis_text:
        return None, analysis_text

    match = _OUTLOOK_PATTERN.search(analysis_text)
    if not match:
        logger.warning("OUTLOOK_JSON 라인 없음 — 판정 기록 생략")
        return None, analysis_text

    cleaned = _OUTLOOK_PATTERN.sub("", analysis_text).rstrip()

    try:
        outlook = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        logger.warning(f"OUTLOOK_JSON 파싱 실패: {e}")
        return None, cleaned

    bias = str(outlook.get("bias", "")).lower()
    if bias not in VALID_BIAS:
        logger.warning(f"잘못된 bias 값: {bias}")
        return None, cleaned
    outlook["bias"] = bias

    try:
        confidence = int(outlook.get("confidence", 0))
        outlook["confidence"] = max(1, min(5, confidence))
    except (TypeError, ValueError):
        outlook["confidence"] = None

    drivers = outlook.get("key_drivers")
    if not isinstance(drivers, list):
        outlook["key_drivers"] = []
    else:
        outlook["key_drivers"] = [str(d) for d in drivers][:5]

    # 예상 범위 [하단, 상단]
    rng = outlook.get("expected_range")
    if (isinstance(rng, list) and len(rng) == 2):
        try:
            low, high = float(rng[0]), float(rng[1])
            outlook["expected_range"] = [min(low, high), max(low, high)]
        except (TypeError, ValueError):
            outlook["expected_range"] = None
    else:
        outlook["expected_range"] = None

    # 섹터 (자유 텍스트 그대로 — 채점 없음, 회고 기록용)
    for key in ("bullish_sectors", "bearish_sectors"):
        val = outlook.get(key)
        outlook[key] = [str(s) for s in val][:5] if isinstance(val, list) else []

    # 종목 픽 (6자리 코드만 유효)
    picks = outlook.get("stock_picks")
    valid_picks = []
    if isinstance(picks, list):
        for p in picks[:3]:
            if not isinstance(p, dict):
                continue
            code = str(p.get("code", "")).strip()
            if not re.fullmatch(r"\d{6}", code):
                continue
            direction = str(p.get("direction", "bullish")).lower()
            if direction not in ("bullish", "bearish"):
                direction = "bullish"
            target = None
            try:
                t = p.get("target")
                if t is not None:
                    target = int(float(t))
            except (TypeError, ValueError):
                pass
            valid_picks.append({
                "code": code,
                "name": str(p.get("name", "")),
                "direction": direction,
                "target": target,
            })
    outlook["stock_picks"] = valid_picks

    return outlook, cleaned


def save_outlook(
    outlook: dict,
    rule_signal: Optional[str] = None,
    llm_model: Optional[str] = None,
    report_date: Optional[date] = None,
) -> bool:
    """
    판정을 report_outlook_log에 저장.
    같은 날짜+모델 조합이 이미 있으면 무시 (운영 발송이 테스트보다 먼저 기록됨).
    """
    if report_date is None:
        report_date = _today_kst()
    if llm_model is None:
        llm_model = os.getenv("LLM_MODEL", "unknown")

    rng = outlook.get("expected_range") or [None, None]

    engine = _get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text(DDL))
            conn.execute(
                text("""
                    INSERT INTO report_outlook_log
                        (report_date, llm_model, llm_bias, llm_confidence,
                         key_drivers, rule_signal,
                         expected_low, expected_high,
                         bullish_sectors, bearish_sectors)
                    VALUES (:report_date, :llm_model, :bias, :confidence,
                            :drivers, :rule_signal,
                            :expected_low, :expected_high,
                            :bullish_sectors, :bearish_sectors)
                    ON CONFLICT (report_date, llm_model) DO NOTHING
                """),
                {
                    "report_date": report_date,
                    "llm_model": llm_model,
                    "bias": outlook.get("bias"),
                    "confidence": outlook.get("confidence"),
                    "drivers": outlook.get("key_drivers") or None,
                    "rule_signal": rule_signal,
                    "expected_low": rng[0],
                    "expected_high": rng[1],
                    "bullish_sectors": outlook.get("bullish_sectors") or None,
                    "bearish_sectors": outlook.get("bearish_sectors") or None,
                },
            )

            # 종목 픽 저장 (코드 → ticker/이름 해석)
            conn.execute(text(PICKS_DDL))
            conn.execute(text(PICKS_MIGRATE))
            for pick in outlook.get("stock_picks", []):
                code = pick["code"]
                row = conn.execute(
                    text("""
                        SELECT ticker, stock_name FROM stock_info
                        WHERE ticker IN (:ks, :kq) AND active = TRUE
                        LIMIT 1
                    """),
                    {"ks": f"{code}.KS", "kq": f"{code}.KQ"},
                ).fetchone()
                conn.execute(
                    text("""
                        INSERT INTO report_stock_picks
                            (report_date, llm_model, stock_code, ticker, stock_name,
                             direction, target_price)
                        VALUES (:d, :m, :code, :ticker, :name, :direction, :target)
                        ON CONFLICT (report_date, llm_model, stock_code) DO NOTHING
                    """),
                    {
                        "d": report_date, "m": llm_model, "code": code,
                        "ticker": row[0] if row else None,
                        "name": (row[1] if row else None) or pick.get("name"),
                        "direction": pick.get("direction", "bullish"),
                        "target": pick.get("target"),
                    },
                )

        logger.info(
            f"outlook 저장: {report_date} [{llm_model}] "
            f"{outlook.get('bias')} (confidence {outlook.get('confidence')}, "
            f"picks {len(outlook.get('stock_picks', []))}건)"
        )
        return True
    except Exception as e:
        logger.warning(f"outlook 저장 실패: {e}")
        return False


def _judge_hit(bias: Optional[str], change_pct: float) -> Optional[bool]:
    """판정 적중 여부. bullish=양봉, bearish=음봉, neutral=±0.5% 이내."""
    if bias == "bullish":
        return change_pct > 0
    if bias == "bearish":
        return change_pct < 0
    if bias == "neutral":
        return abs(change_pct) <= NEUTRAL_BAND_PCT
    return None


def _kospi_close_and_change(conn, target_date: date) -> Optional[Tuple[float, float]]:
    """target_date의 KOSPI (종가, 등락률). change_pct 미적재 시 전일 종가로 직접 계산."""
    row = conn.execute(
        text("""
            SELECT change_pct, value FROM macro_indicators
            WHERE indicator_type = 'stock_index_kospi'
              AND indicator_date = :d
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
        """),
        {"d": target_date},
    ).fetchone()

    if not row or row[1] is None:
        return None

    close_value = float(row[1])
    if row[0] is not None:
        return close_value, float(row[0])

    prev = conn.execute(
        text("""
            SELECT value FROM macro_indicators
            WHERE indicator_type = 'stock_index_kospi'
              AND indicator_date < :d AND value IS NOT NULL
            ORDER BY indicator_date DESC LIMIT 1
        """),
        {"d": target_date},
    ).fetchone()
    if not prev:
        return None
    return close_value, (close_value / float(prev[0]) - 1) * 100


def evaluate_outlook(report_date: Optional[date] = None) -> dict:
    """
    미평가 판정 전부를 KOSPI 종가/등락률(macro_indicators)로 채점.
    특정 날짜만 채점하려면 report_date 지정. 기본은 KST 오늘까지의 모든 미평가 행
    (과거에 데이터 지연으로 못 채점한 행도 다음 실행 때 따라잡음).
    """
    engine = _get_engine()
    evaluated = 0
    skipped_dates = []

    with engine.begin() as conn:
        conn.execute(text(DDL))

        if report_date is not None:
            date_cond = "report_date = :d"
            params = {"d": report_date}
        else:
            date_cond = "report_date <= :d"
            params = {"d": _today_kst()}

        targets = conn.execute(
            text(f"""
                SELECT id, report_date, llm_bias, rule_signal, expected_low, expected_high
                FROM report_outlook_log
                WHERE {date_cond} AND evaluated_at IS NULL
                ORDER BY report_date
            """),
            params,
        ).fetchall()

        kospi_cache: dict = {}
        for outlook_id, rdate, llm_bias, rule_signal, exp_low, exp_high in targets:
            if rdate not in kospi_cache:
                kospi_cache[rdate] = _kospi_close_and_change(conn, rdate)
            kospi = kospi_cache[rdate]
            if kospi is None:
                skipped_dates.append(str(rdate))
                continue
            close_value, change_pct = kospi

            llm_hit = _judge_hit(llm_bias, change_pct)
            rule_bias = RULE_SIGNAL_BIAS.get(rule_signal or "")
            rule_hit = _judge_hit(rule_bias, change_pct)

            range_hit = None
            if exp_low is not None and exp_high is not None:
                range_hit = float(exp_low) <= close_value <= float(exp_high)

            conn.execute(
                text("""
                    UPDATE report_outlook_log
                    SET actual_change_pct = :chg,
                        actual_close = :close,
                        range_hit = :range_hit,
                        llm_hit = :llm_hit,
                        rule_hit = :rule_hit,
                        evaluated_at = NOW()
                    WHERE id = :id
                """),
                {"chg": change_pct, "close": close_value, "range_hit": range_hit,
                 "llm_hit": llm_hit, "rule_hit": rule_hit, "id": outlook_id},
            )
            evaluated += 1

    if skipped_dates:
        logger.info(f"KOSPI 미적재로 스킵된 날짜: {set(skipped_dates)}")
    logger.info(f"outlook 평가 완료: {evaluated}건")

    picks_result = evaluate_stock_picks()
    return {
        "evaluated": evaluated,
        "skipped_dates": sorted(set(skipped_dates)),
        "picks_updated": picks_result.get("updated", 0),
    }


# 시차별 평가: 리포트 발행 전일 종가(base) 대비 N번째 거래일 종가
PICK_HORIZONS = {"1d": 1, "5d": 5, "20d": 20}


def _kospi_closes(conn, from_date: date) -> list:
    """from_date 이전 마지막 종가(base) + 이후 종가 시계열 [(date, value), ...]"""
    base = conn.execute(
        text("""
            SELECT indicator_date, value FROM macro_indicators
            WHERE indicator_type = 'stock_index_kospi'
              AND indicator_date < :d AND value IS NOT NULL
            ORDER BY indicator_date DESC LIMIT 1
        """),
        {"d": from_date},
    ).fetchone()
    after = conn.execute(
        text("""
            SELECT indicator_date, value FROM macro_indicators
            WHERE indicator_type = 'stock_index_kospi'
              AND indicator_date >= :d AND value IS NOT NULL
            ORDER BY indicator_date
        """),
        {"d": from_date},
    ).fetchall()
    return ([base] if base else []) + list(after)


def evaluate_stock_picks() -> dict:
    """
    미평가 종목 픽의 1d/5d/20d 수익률 + KOSPI 초과수익 계산.
    base = 리포트 발행 전일 종가 (리포트가 본 마지막 데이터).
    경과 거래일이 부족한 시차는 다음 실행 때 채워짐 (멱등).
    """
    engine = _get_engine()
    updated = 0

    with engine.begin() as conn:
        conn.execute(text(PICKS_DDL))

        conn.execute(text(PICKS_MIGRATE))

        picks = conn.execute(
            text("""
                SELECT id, report_date, ticker, direction FROM report_stock_picks
                WHERE ticker IS NOT NULL AND return_20d IS NULL
                ORDER BY report_date
            """),
        ).fetchall()

        for pick_id, report_date_, ticker, direction in picks:
            # 종목 종가: base(전일) + 이후 거래일 시계열
            rows = conn.execute(
                text("""
                    SELECT DATE(timestamp_kst) AS d, close FROM stock_price_1d
                    WHERE ticker = :t AND close IS NOT NULL
                      AND DATE(timestamp_kst) >= :d - INTERVAL '10 days'
                    ORDER BY d
                """),
                {"t": ticker, "d": report_date_},
            ).fetchall()

            before = [r for r in rows if r[0] < report_date_]
            after = [r for r in rows if r[0] >= report_date_]
            if not before or not after:
                continue
            base_close = float(before[-1][1])

            kospi = _kospi_closes(conn, report_date_)
            kospi_base = float(kospi[0][1]) if kospi and kospi[0][0] < report_date_ else None
            kospi_after = [k for k in kospi if k[0] >= report_date_]

            params = {"id": pick_id, "base": base_close}
            set_parts = ["base_close = :base"]

            for label, n in PICK_HORIZONS.items():
                if len(after) >= n:
                    ret = (float(after[n - 1][1]) / base_close - 1) * 100
                    params[f"r_{label}"] = round(ret, 4)
                    set_parts.append(f"return_{label} = :r_{label}")
                    if kospi_base and len(kospi_after) >= n:
                        kospi_ret = (float(kospi_after[n - 1][1]) / kospi_base - 1) * 100
                        params[f"e_{label}"] = round(ret - kospi_ret, 4)
                        set_parts.append(f"excess_{label} = :e_{label}")

            # direction_hit: 1일 수익률 기준으로 방향 적중 여부
            if "r_1d" in params and direction in ("bullish", "bearish"):
                ret_1d = params["r_1d"]
                if direction == "bullish":
                    params["dir_hit"] = ret_1d > 0
                else:
                    params["dir_hit"] = ret_1d < 0
                set_parts.append("direction_hit = :dir_hit")

            if len(set_parts) > 1:
                conn.execute(
                    text(f"UPDATE report_stock_picks SET {', '.join(set_parts)} WHERE id = :id"),
                    params,
                )
                updated += 1

    if updated:
        logger.info(f"종목 픽 수익률 갱신: {updated}건")
    return {"updated": updated}
