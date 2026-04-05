"""
장중 시장 모니터링 엔진
- Layer 1: 상시 규칙 기반 모니터링 (지수, 환율, 주요종목)
- Layer 2: 모닝리포트 체크리스트 기반 모니터링
- 네이버 금융 폴링으로 실시간 데이터 수집
"""

import os
import re
import json
import math
import logging
from datetime import datetime, date
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any

import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

def _build_database_url() -> str:
    """DATABASE_URL 해석. 비밀값 하드코딩 금지 (security_governance 1-7)."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    pg_user = os.getenv("PG_USER", "user")
    pg_password = os.getenv("PG_PASSWORD")
    if not pg_password:
        raise RuntimeError(
            "DATABASE_URL 또는 PG_PASSWORD 환경변수가 필요합니다. "
            ".env 또는 Airflow Variable에서 주입하세요."
        )
    pg_host = os.getenv("PG_HOST", "bip-postgres")
    pg_port = os.getenv("PG_PORT", "5432")
    pg_db = os.getenv("PG_DB", "stockdb")
    return f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"


DATABASE_URL = _build_database_url()


def _get_engine():
    return create_engine(DATABASE_URL)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0"
}

# ──────────────────────────────────────────────
# 1. 장중 데이터 수집 (네이버 금융 폴링)
# ──────────────────────────────────────────────

def _parse_naver_index(code: str) -> Optional[Dict]:
    """네이버 금융 지수 페이지 파싱"""
    try:
        url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        now_val = soup.select_one("#now_value")
        if not now_val:
            return None

        val = float(now_val.text.strip().replace(",", ""))
        chg, pct = 0.0, 0.0

        change_el = soup.select_one("#change_value_and_rate")
        if change_el:
            match = re.search(
                r'([\d,.]+)\s*([+-]?[\d.]+)%\s*(상승|하락)',
                change_el.text.strip()
            )
            if match:
                chg = float(match.group(1).replace(",", ""))
                pct = float(match.group(2))
                if match.group(3) == "하락":
                    chg = -chg
                    pct = -abs(pct)

        return {"value": val, "change": chg, "change_pct": pct}
    except Exception as e:
        logger.warning(f"{code} 수집 실패: {e}")
        return None


def fetch_market_indices() -> Dict[str, Any]:
    """KOSPI / KOSDAQ / 원달러 환율 + 원자재/크립토 현재 시세"""
    result = {}

    # KOSPI
    kospi = _parse_naver_index("KOSPI")
    if kospi:
        result["kospi"] = kospi

    # KOSDAQ
    kosdaq = _parse_naver_index("KOSDAQ")
    if kosdaq:
        result["kosdaq"] = kosdaq

    # 원/달러 환율
    try:
        url = "https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.select_one(".no_today")
        if el:
            match = re.search(r'([\d,]+\.?\d*)', el.get_text(strip=True))
            if match:
                val = float(match.group(1).replace(",", ""))
                result["usd_krw"] = {"value": val}
    except Exception as e:
        logger.warning(f"환율 수집 실패: {e}")

    # WTI 원유 (네이버 금융 테이블)
    try:
        url = "https://finance.naver.com/marketindex/worldDailyQuote.naver?marketindexCd=OIL_CL&fdtc=2"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table.tbl_exchange")
        if table:
            row = table.select("tr")[1]
            cells = row.select("td")
            val = float(cells[1].text.strip().replace(",", ""))
            pct_text = cells[3].text.strip().replace("%", "").replace("+", "")
            pct = float(pct_text)
            result["wti"] = {"value": val, "change_pct": pct}
    except Exception as e:
        logger.warning(f"WTI 수집 실패: {e}")

    # 금 (네이버 금융 테이블)
    try:
        url = "https://finance.naver.com/marketindex/worldDailyQuote.naver?marketindexCd=CMDT_GC&fdtc=2"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table.tbl_exchange")
        if table:
            row = table.select("tr")[1]
            cells = row.select("td")
            val = float(cells[1].text.strip().replace(",", ""))
            pct_text = cells[3].text.strip().replace("%", "").replace("+", "")
            pct = float(pct_text)
            result["gold"] = {"value": val, "change_pct": pct}
    except Exception as e:
        logger.warning(f"금 수집 실패: {e}")

    # 크립토 (Upbit API - 실시간, 무료)
    try:
        usd_krw = result.get("usd_krw", {}).get("value", 0)
        resp = requests.get(
            "https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH",
            timeout=10,
        )
        for coin in resp.json():
            market = coin.get("market", "")
            price_krw = coin.get("trade_price", 0)
            change_pct = round(coin.get("signed_change_rate", 0) * 100, 2)
            value_usd = round(price_krw / usd_krw, 0) if usd_krw else 0
            if market == "KRW-BTC":
                result["btc"] = {
                    "value_krw": price_krw,
                    "value": value_usd,
                    "change_pct": change_pct,
                }
            elif market == "KRW-ETH":
                result["eth"] = {
                    "value_krw": price_krw,
                    "value": value_usd,
                    "change_pct": change_pct,
                }
    except Exception as e:
        logger.warning(f"크립토 수집 실패: {e}")

    return result


def fetch_stock_price(code: str) -> Optional[Dict]:
    """개별 종목 현재가 조회 (6자리 종목코드)"""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        price_el = soup.select_one(".no_today .blind")
        if not price_el:
            return None

        price = int(price_el.text.strip().replace(",", ""))

        # 등락률
        change_el = soup.select_one(".no_exday .blind")
        change = int(change_el.text.strip().replace(",", "")) if change_el else 0

        # 상승/하락 판단
        rate_el = soup.select_one(".no_exday em span.blind")
        if rate_el and "하락" in (rate_el.find_previous(text=True) or ""):
            change = -abs(change)

        prev_close = price - change if change else price
        change_pct = round((change / prev_close * 100), 2) if prev_close else 0

        return {
            "code": code,
            "price": price,
            "change": change,
            "change_pct": change_pct,
        }
    except Exception as e:
        logger.warning(f"종목 {code} 수집 실패: {e}")
        return None


def fetch_investor_flow() -> Dict[str, Any]:
    """
    장중 투자자별 매매동향 (KOSPI 전체)
    네이버 금융 투자자별 매매동향 페이지에서 당일 데이터 수집
    Returns: {"foreign": -1500, "institution": 800, "individual": 700} (억원 단위)
    """
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        url = f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={today_str}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.select_one("table.type_1")
        if not table:
            return {}

        # 첫 번째 데이터 행 = 당일
        for row in table.select("tr"):
            cells = row.select("td")
            if len(cells) < 4:
                continue

            def parse_amount(text):
                """네이버 금융 금액 파싱 (억원 단위)"""
                text = text.strip().replace(",", "")
                try:
                    return int(text)
                except ValueError:
                    return 0

            # 개인, 외국인, 기관 순서
            individual = parse_amount(cells[1].get_text(strip=True))
            foreign = parse_amount(cells[2].get_text(strip=True))
            institution = parse_amount(cells[3].get_text(strip=True))

            return {
                "foreign": foreign,           # 외국인 순매수 (억원)
                "institution": institution,   # 기관 순매수 (억원)
                "individual": individual,     # 개인 순매수 (억원)
            }

        return {}
    except Exception as e:
        logger.warning(f"투자자 매매동향 수집 실패: {e}")
        return {}


def fetch_market_snapshot() -> Dict[str, Any]:
    """장중 시장 전체 스냅샷 (체크리스트 종목 자동 포함)"""
    indices = fetch_market_indices()
    investor_flow = fetch_investor_flow()

    # 체크리스트에 있는 종목 자동 조회
    stocks = {}
    try:
        rules = load_checklist_rules()
        for r in rules:
            code = r.get("code", "")
            if code and code not in stocks:
                data = fetch_stock_price(code)
                if data:
                    data["name"] = r.get("name", code)
                    stocks[code] = data
    except Exception:
        pass

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indices": indices,
        "investor_flow": investor_flow,
        "stocks": stocks,
    }


# ──────────────────────────────────────────────
# 2. Layer 1: 상시 규칙 기반 모니터링
# ──────────────────────────────────────────────

@dataclass
class Alert:
    level: str              # "🔴 긴급", "🟡 주의"
    category: str           # "index", "fx", "flow", "commodity", "crypto"
    alert_key: str          # "index:KOSPI", "crypto:BTC", "flow:foreign"
    title: str
    description: str
    metric_type: str = "pct"        # "pct" or "abs"
    alert_value: float = 0          # 알림 시점 값
    alert_change_pct: float = 0     # 알림 시점 등락률
    alert_change_abs: float = 0     # 알림 시점 절대 변동값
    data: Dict = field(default_factory=dict)


# 상시 모니터링 임계값
ALERT_RULES = {
    "index_critical": 3.0,       # 지수 ±3% 긴급
    "index_warning": 2.0,        # 지수 ±2% 주의
    "fx_critical": 1.5,          # 환율 ±1.5% 긴급
    "fx_warning": 0.7,           # 환율 ±0.7% 주의
    "flow_critical": 50000,      # 외국인/기관 ±5조 긴급
    "flow_warning": 40000,       # 외국인/기관 ±4조 주의
    "wti_critical": 8.0,         # WTI ±8% 긴급
    "wti_warning": 5.0,          # WTI ±5% 주의
    "gold_critical": 5.0,        # 금 ±5% 긴급
    "gold_warning": 3.0,         # 금 ±3% 주의
    "crypto_critical": 12.0,     # BTC/ETH ±12% 긴급
    "crypto_warning": 8.0,       # BTC/ETH ±8% 주의
}

# 재알림 delta 기준 (마지막 알림 대비 추가 변동 시 재알림)
REALERT_DELTA = {
    "index": 1.0,        # 지수 1.0%p 추가 변동
    "fx": 0.5,           # 환율 0.5%p
    "flow": 10000,       # 수급 1조 추가 (abs 기준)
    "commodity": 3.0,    # 원자재 3.0%p
    "crypto": 5.0,       # 크립토 5.0%p
}


def _make_alert(level, category, alert_key, title, description,
                 metric_type="pct", value=0, change_pct=0, change_abs=0, data=None):
    """Alert 생성 헬퍼"""
    return Alert(
        level=level, category=category, alert_key=alert_key,
        title=title, description=description,
        metric_type=metric_type, alert_value=value,
        alert_change_pct=change_pct, alert_change_abs=change_abs,
        data=data or {},
    )


def check_layer1_rules(snapshot: Dict) -> List[Alert]:
    """상시 규칙 기반 이상치 감지 (매크로 지표 + 장중 수급)"""
    alerts = []
    indices = snapshot.get("indices", {})

    # 지수 체크
    for idx_name, idx_key in [("KOSPI", "kospi"), ("KOSDAQ", "kosdaq")]:
        idx = indices.get(idx_key, {})
        pct = idx.get("change_pct", 0)
        abs_pct = abs(pct)
        direction = "급등" if pct > 0 else "급락"

        if abs_pct >= ALERT_RULES["index_critical"]:
            alerts.append(_make_alert(
                "🔴 긴급", "index", f"index:{idx_name}",
                f"{idx_name} {direction} {pct:+.1f}%",
                f"{idx_name} 현재 {idx.get('value', 0):,.2f} ({pct:+.1f}%) — 시장 급변동 주의",
                value=idx.get("value", 0), change_pct=pct, data=idx,
            ))
        elif abs_pct >= ALERT_RULES["index_warning"]:
            alerts.append(_make_alert(
                "🟡 주의", "index", f"index:{idx_name}",
                f"{idx_name} {direction} {pct:+.1f}%",
                f"{idx_name} 현재 {idx.get('value', 0):,.2f}",
                value=idx.get("value", 0), change_pct=pct, data=idx,
            ))

    # 장중 투자자 수급 체크
    flow = snapshot.get("investor_flow", {})
    if flow:
        for investor, key in [("외국인", "foreign"), ("기관", "institution")]:
            amount = flow.get(key, 0)
            abs_amount = abs(amount)
            direction = "순매수" if amount > 0 else "순매도"

            if abs_amount >= ALERT_RULES["flow_critical"]:
                alerts.append(_make_alert(
                    "🔴 긴급", "flow", f"flow:{key}",
                    f"{investor} {direction} {abs_amount:,}억원",
                    f"{investor} 장중 {direction} {abs_amount:,}억원 — 대규모 수급 이동",
                    metric_type="abs", value=amount, change_abs=amount,
                    data={"investor": investor, "amount": amount},
                ))
            elif abs_amount >= ALERT_RULES["flow_warning"]:
                alerts.append(_make_alert(
                    "🟡 주의", "flow", f"flow:{key}",
                    f"{investor} {direction} {abs_amount:,}억원",
                    f"{investor} 장중 {direction} {abs_amount:,}억원",
                    metric_type="abs", value=amount, change_abs=amount,
                    data={"investor": investor, "amount": amount},
                ))

    # 원자재 체크
    for name, key, crit, warn in [
        ("WTI", "wti", "wti_critical", "wti_warning"),
        ("금", "gold", "gold_critical", "gold_warning"),
    ]:
        item = indices.get(key, {})
        pct = item.get("change_pct", 0)
        abs_pct = abs(pct)
        if abs_pct == 0:
            continue
        direction = "급등" if pct > 0 else "급락"

        if abs_pct >= ALERT_RULES[crit]:
            alerts.append(_make_alert(
                "🔴 긴급", "commodity", f"commodity:{key}",
                f"{name} {direction} {pct:+.1f}%",
                f"{name} ${item.get('value', 0):,.1f} ({pct:+.1f}%)",
                value=item.get("value", 0), change_pct=pct, data=item,
            ))
        elif abs_pct >= ALERT_RULES[warn]:
            alerts.append(_make_alert(
                "🟡 주의", "commodity", f"commodity:{key}",
                f"{name} {direction} {pct:+.1f}%",
                f"{name} ${item.get('value', 0):,.1f}",
                value=item.get("value", 0), change_pct=pct, data=item,
            ))

    # 크립토 체크
    for name, key in [("BTC", "btc"), ("ETH", "eth")]:
        item = indices.get(key, {})
        pct = item.get("change_pct", 0)
        abs_pct = abs(pct)
        if abs_pct == 0:
            continue
        direction = "급등" if pct > 0 else "급락"

        if abs_pct >= ALERT_RULES["crypto_critical"]:
            alerts.append(_make_alert(
                "🔴 긴급", "crypto", f"crypto:{key}",
                f"{name} {direction} {pct:+.1f}%",
                f"{name} {item.get('value_krw', 0):,.0f}원 ({pct:+.1f}%)",
                value=item.get("value_krw", 0), change_pct=pct, data=item,
            ))
        elif abs_pct >= ALERT_RULES["crypto_warning"]:
            alerts.append(_make_alert(
                "🟡 주의", "crypto", f"crypto:{key}",
                f"{name} {direction} {pct:+.1f}%",
                f"{name} {item.get('value_krw', 0):,.0f}원",
                value=item.get("value_krw", 0), change_pct=pct, data=item,
            ))

    return alerts


# ──────────────────────────────────────────────
# 3. Layer 2: 체크리스트 저장 및 에이전트 분석
# ──────────────────────────────────────────────

def save_checklist(checklist_text: str, target_date: str = None):
    """체크리스트 원문 통째로 DB에 저장"""
    if not target_date:
        from zoneinfo import ZoneInfo
        target_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM monitor_checklist WHERE checklist_date = :d"
        ), {"d": target_date})
        conn.execute(text("""
            INSERT INTO monitor_checklist (checklist_date, checklist_text)
            VALUES (:d, :t)
        """), {"d": target_date, "t": checklist_text})

    logger.info(f"체크리스트 저장: {target_date} ({len(checklist_text)}자)")

    try:
        from utils.lineage import register_table_lineage_async
        register_table_lineage_async("monitor_checklist", source_tables=[])
    except Exception:
        pass


def load_checklist(target_date: str = None) -> str:
    """체크리스트 원문 DB에서 로드 (없으면 가장 최근 것으로 fallback)"""
    if not target_date:
        from zoneinfo import ZoneInfo
        target_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT checklist_text FROM monitor_checklist
            WHERE checklist_date = :d
        """), {"d": target_date}).fetchone()

        # 오늘 데이터 없으면 가장 최근 체크리스트로 fallback
        if not row:
            row = conn.execute(text("""
                SELECT checklist_text FROM monitor_checklist
                ORDER BY checklist_date DESC
                LIMIT 1
            """)).fetchone()
            if row:
                logger.info(f"{target_date} 체크리스트 없음 → 최근 체크리스트 사용")

    return row[0] if row else ""


# ── 하위 호환용 (DAG에서 호출하는 함수명 유지) ──
def parse_checklist_with_llm(checklist_text: str) -> List[Dict]:
    """
    모닝리포트 체크리스트를 Haiku로 구조화 파싱
    Returns: 모니터링 가능한 룰 리스트
    """
    import anthropic
    from utils.audited_llm import audited_anthropic_call

    client = anthropic.Anthropic()

    system = """주식 시장 모닝리포트의 체크리스트를 구조화된 모니터링 룰로 변환하세요.

## 룰 유형
1. index_level: {"type": "index_level", "index": "KOSPI|KOSDAQ", "level": 숫자, "condition": "above|below"}
2. stock_change: {"type": "stock_change", "code": "6자리코드", "name": "종목명", "threshold_pct": 숫자, "condition": "above|below"}
3. fx_level: {"type": "fx_level", "pair": "usd_krw", "level": 숫자, "condition": "above|below"}
4. event: {"type": "event", "time": "HH:MM", "description": "설명"}
5. general: {"type": "general", "description": "원문"}

## 시간대 구분 (phase 필드 필수)
- "pre_market": 장 시작 전 확인 항목 (08:30~09:00)
- "intraday": 장 중 모니터링 항목 (09:00~15:30)
- "price_level": 주의 가격 레벨/이벤트

## 규칙
- 각 항목에 "original" (원문 요약, 20자 이내), "phase" 필드 필수
- "코스피 5,500 돌파/5,300 이탈" 같이 양방향 조건은 1개 룰로 통합 (condition은 더 중요한 쪽)
- 항목당 1개 룰만 생성 (중복 금지)
- 주요 종목코드: 삼성전자=005930, SK하이닉스=000660, LG에너지솔루션=373220, 현대차=005380, NAVER=035420, 카카오=035720

JSON 배열만 출력. 코드블록 없이."""

    try:
        resp = audited_anthropic_call(
            agent_name="market_monitor",
            agent_type="monitor",
            prompt_class="parse_checklist_rules",
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": f"체크리스트:\n{checklist_text}"}],
            client=client,
        )
        text = resp.content[0].text.strip()

        # JSON 추출 (```json ... ``` 코드블록 대응)
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            rules = json.loads(match.group())
            for i, rule in enumerate(rules):
                rule["id"] = i + 1
                rule["triggered"] = False
            return rules
    except Exception as e:
        logger.error(f"체크리스트 파싱 실패: {e}")

    return []


def save_checklist_rules(rules: List[Dict], target_date: str = None):
    """파싱된 체크리스트 룰을 DB에 저장"""
    if not target_date:
        target_date = date.today().isoformat()

    engine = _get_engine()
    with engine.begin() as conn:
        # 기존 룰 삭제 (같은 날짜 재파싱 시)
        conn.execute(text(
            "DELETE FROM monitor_checklist WHERE rule_date = :d"
        ), {"d": target_date})

        for i, rule in enumerate(rules):
            conn.execute(text("""
                INSERT INTO monitor_checklist
                    (rule_date, rule_order, rule_type, original_text, parsed_rule, triggered)
                VALUES (:d, :o, :t, :orig, :rule, false)
            """), {
                "d": target_date,
                "o": i + 1,
                "t": rule.get("type", "general"),
                "orig": rule.get("original", ""),
                "rule": json.dumps(rule, ensure_ascii=False),
            })

    logger.info(f"체크리스트 룰 DB 저장: {target_date} ({len(rules)}건)")

    try:
        from utils.lineage import register_table_lineage_async
        register_table_lineage_async("monitor_checklist", source_tables=[])
    except Exception:
        pass


def load_checklist_rules(target_date: str = None) -> List[Dict]:
    """오늘의 체크리스트 룰 DB에서 로드"""
    if not target_date:
        target_date = date.today().isoformat()

    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, rule_order, rule_type, original_text, parsed_rule, triggered
            FROM monitor_checklist
            WHERE rule_date = :d
            ORDER BY rule_order
        """), {"d": target_date}).fetchall()

    rules = []
    for row in rows:
        raw = row[4]
        rule = json.loads(raw) if isinstance(raw, str) else (raw if raw else {})
        rule["db_id"] = row[0]
        rule["id"] = row[1]
        rule["type"] = row[2]
        rule["original"] = row[3]
        rule["triggered"] = row[5]
        rules.append(rule)

    return rules


def mark_rule_triggered(rule_id: int, triggered_value: str = ""):
    """체크리스트 룰 트리거 상태 업데이트"""
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE monitor_checklist
            SET triggered = true, triggered_at = NOW(), triggered_value = :val
            WHERE id = :id
        """), {"id": rule_id, "val": triggered_value})


def check_layer2_rules(snapshot: Dict, rules: List[Dict]) -> List[Alert]:
    """체크리스트 룰 기반 조건 체크"""
    alerts = []
    indices = snapshot.get("indices", {})

    for rule in rules:
        if rule.get("triggered"):
            continue  # 이미 알림 보낸 룰 스킵

        rtype = rule.get("type")
        original = rule.get("original", "")

        if rtype == "index_level":
            idx = indices.get(rule.get("index", "").lower(), {})
            value = idx.get("value", 0)
            level = rule.get("level", 0)
            condition = rule.get("condition", "above")

            triggered = (condition == "above" and value >= level) or \
                        (condition == "below" and value <= level)

            if triggered:
                rule["triggered"] = True
                direction = "돌파" if condition == "above" else "이탈"
                if rule.get("db_id"):
                    mark_rule_triggered(rule["db_id"], f"{value:,.2f}")
                alerts.append(Alert(
                    level="🟡 체크리스트",
                    category="checklist",
                    title=f"{rule.get('index')} {level:,.0f} {direction}",
                    description=f"📋 {original}\n→ 현재 {value:,.2f}",
                    data=rule,
                ))

        elif rtype == "stock_change":
            code = rule.get("code", "")
            stock = snapshot.get("stocks", {}).get(code, {})
            if not stock:
                continue

            pct = stock.get("change_pct", 0)
            threshold = rule.get("threshold_pct", 0)
            condition = rule.get("condition", "below")

            triggered = (condition == "below" and pct <= threshold) or \
                        (condition == "above" and pct >= threshold)

            if triggered:
                rule["triggered"] = True
                if rule.get("db_id"):
                    mark_rule_triggered(rule["db_id"], f"{stock.get('price', 0):,}원 ({pct:+.1f}%)")
                alerts.append(Alert(
                    level="🟡 체크리스트",
                    category="checklist",
                    title=f"{rule.get('name', code)} {pct:+.1f}%",
                    description=f"📋 {original}\n→ 현재 {stock.get('price', 0):,}원 ({pct:+.1f}%)",
                    data=rule,
                ))

        elif rtype == "fx_level":
            fx = indices.get(rule.get("pair", "usd_krw"), {})
            value = fx.get("value", 0)
            level = rule.get("level", 0)
            condition = rule.get("condition", "above")

            triggered = (condition == "above" and value >= level) or \
                        (condition == "below" and value <= level)

            if triggered:
                rule["triggered"] = True
                if rule.get("db_id"):
                    mark_rule_triggered(rule["db_id"], f"{value:,.1f}원")
                direction = "돌파" if condition == "above" else "이탈"
                alerts.append(Alert(
                    level="🟡 체크리스트",
                    category="checklist",
                    title=f"원/달러 {level:,.0f}원 {direction}",
                    description=f"📋 {original}\n→ 현재 {value:,.1f}원",
                    data=rule,
                ))

        # event/general 타입은 알림 발송 안 함 — 정기 현황에서만 표시

    return alerts


# ──────────────────────────────────────────────
# 4. 알림 발송 (DB 기반 delta 체크)
# ──────────────────────────────────────────────

def _get_last_alert(alert_key: str) -> Optional[Dict]:
    """오늘 해당 항목의 마지막 알림 조회"""
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT alert_change_pct, alert_change_abs, metric_type, event_direction
            FROM monitor_alerts
            WHERE alert_date = CURRENT_DATE
              AND alert_key = :key
            ORDER BY alert_time DESC, id DESC
            LIMIT 1
        """), {"key": alert_key}).fetchone()

    if row:
        return {
            "change_pct": float(row[0]) if row[0] else 0,
            "change_abs": float(row[1]) if row[1] else 0,
            "metric_type": row[2],
            "direction": row[3],
        }
    return None


def _save_alert_to_db(alert: Alert, event_direction: str = "worsen", is_sent: bool = True):
    """알림 이력 DB 저장 (항상 INSERT)"""
    try:
        engine = _get_engine()
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO monitor_alerts
                    (alert_date, alert_time, alert_key, level, category,
                     title, description, metric_type,
                     alert_value, alert_change_pct, alert_change_abs,
                     event_direction, is_sent, data)
                VALUES (CURRENT_DATE, NOW(), :key, :level, :cat,
                        :title, :desc, :metric,
                        :val, :pct, :abs_val,
                        :direction, :sent, :data)
            """), {
                "key": alert.alert_key,
                "level": alert.level,
                "cat": alert.category,
                "title": alert.title,
                "desc": alert.description,
                "metric": alert.metric_type,
                "val": alert.alert_value,
                "pct": alert.alert_change_pct,
                "abs_val": alert.alert_change_abs,
                "direction": event_direction,
                "sent": is_sent,
                "data": json.dumps(alert.data, ensure_ascii=False, default=str),
            })
        try:
            from utils.lineage import register_table_lineage_async
            register_table_lineage_async("monitor_alerts", source_tables=[])
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"알림 DB 저장 실패: {e}")


def _should_send_alert(alert: Alert) -> str:
    """
    알림 발송 여부 판단.
    Returns: "send" (발송), "recover" (DB만 기록), "skip" (무시)
    """
    last = _get_last_alert(alert.alert_key)

    if not last:
        # 오늘 첫 알림 → 발송
        return "send"

    if last["direction"] == "recover":
        # 이전에 recover 기록됨 → 다시 threshold 넘었으면 새 알림
        return "send"

    # 이전 worsen 알림 대비 delta 계산
    delta_threshold = REALERT_DELTA.get(alert.category, 1.0)

    if alert.metric_type == "abs":
        delta = abs(abs(alert.alert_change_abs) - abs(last["change_abs"]))
        if delta >= delta_threshold:
            return "send"
    else:
        delta = abs(abs(alert.alert_change_pct) - abs(last["change_pct"]))
        if delta >= delta_threshold:
            return "send"

    return "skip"


def _check_recover(snapshot: Dict):
    """warning 하회 시 recover 기록 (발송 안 함)"""
    engine = _get_engine()
    indices = snapshot.get("indices", {})

    # 오늘 worsen 알림이 있고, 현재 warning 아래인 항목 찾기
    recover_checks = [
        ("index:KOSPI", abs(indices.get("kospi", {}).get("change_pct", 0)), ALERT_RULES["index_warning"]),
        ("index:KOSDAQ", abs(indices.get("kosdaq", {}).get("change_pct", 0)), ALERT_RULES["index_warning"]),
        ("commodity:wti", abs(indices.get("wti", {}).get("change_pct", 0)), ALERT_RULES["wti_warning"]),
        ("commodity:gold", abs(indices.get("gold", {}).get("change_pct", 0)), ALERT_RULES["gold_warning"]),
        ("crypto:btc", abs(indices.get("btc", {}).get("change_pct", 0)), ALERT_RULES["crypto_warning"]),
        ("crypto:eth", abs(indices.get("eth", {}).get("change_pct", 0)), ALERT_RULES["crypto_warning"]),
    ]

    # flow는 abs 기준
    flow = snapshot.get("investor_flow", {})
    if flow:
        recover_checks.append(("flow:foreign", abs(flow.get("foreign", 0)), ALERT_RULES["flow_warning"]))
        recover_checks.append(("flow:institution", abs(flow.get("institution", 0)), ALERT_RULES["flow_warning"]))

    for alert_key, current_val, warning_threshold in recover_checks:
        if current_val >= warning_threshold:
            continue  # 아직 warning 이상 → recover 아님

        last = _get_last_alert(alert_key)
        if not last or last["direction"] == "recover":
            continue  # 이전 알림 없거나 이미 recover됨

        # warning 하회 → recover 기록
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO monitor_alerts
                    (alert_date, alert_time, alert_key, level, category,
                     title, description, metric_type,
                     alert_value, alert_change_pct, alert_change_abs,
                     event_direction, is_sent, data)
                VALUES (CURRENT_DATE, NOW(), :key, '🟢 반등', :cat,
                        :title, '', :metric,
                        :val, :pct, :abs_val,
                        'recover', false, '{}')
            """), {
                "key": alert_key,
                "cat": alert_key.split(":")[0],
                "title": f"{alert_key} 경계 해제",
                "metric": "abs" if "flow" in alert_key else "pct",
                "val": current_val,
                "pct": current_val if "flow" not in alert_key else 0,
                "abs_val": current_val if "flow" in alert_key else 0,
            })
        logger.info(f"recover 기록: {alert_key} (현재 {current_val})")


def format_alert_message(alerts: List[Alert], snapshot: Dict = None) -> str:
    """알림 리스트를 텔레그램 메시지로 포맷"""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    lines = [f"⏰ *Market Alert — {now}*\n"]

    for alert in alerts:
        lines.append(f"{alert.level}")
        lines.append(f"*{alert.title}*")
        lines.append(f"{alert.description}\n")

    if snapshot:
        lines.append("— 현재 시장 —")
        lines.extend(_format_market_snapshot(snapshot))

    return "\n".join(lines)


def send_alerts(alerts: List[Alert], snapshot: Dict = None) -> int:
    """알림 발송 (DB 기반 delta 체크 + recover 기록)"""
    from reports.telegram_sender import send_telegram_message

    # delta 기반 필터링
    to_send = []
    for alert in alerts:
        decision = _should_send_alert(alert)
        if decision == "send":
            to_send.append(alert)

    # worsen 알림 발송
    if to_send:
        message = format_alert_message(to_send, snapshot=snapshot)
        success = send_telegram_message(message)

        for alert in to_send:
            _save_alert_to_db(alert, event_direction="worsen", is_sent=True)

        if success:
            logger.info(f"알림 {len(to_send)}건 발송 완료")
    else:
        logger.info("발송할 알림 없음 (delta 미달 또는 중복)")

    # recover 체크 (warning 하회 시 DB 기록만)
    if snapshot:
        _check_recover(snapshot)

    return len(to_send)


# ──────────────────────────────────────────────
# 5. 메인 실행 (DAG에서 호출)
# ──────────────────────────────────────────────

def _format_market_snapshot(snapshot: Dict) -> List[str]:
    """시장 현황 포맷 (알림/정기현황 공통)"""
    lines = []
    indices = snapshot.get("indices", {})
    kospi = indices.get("kospi", {})
    kosdaq = indices.get("kosdaq", {})
    fx = indices.get("usd_krw", {})
    wti = indices.get("wti", {})
    gold = indices.get("gold", {})
    btc = indices.get("btc", {})
    eth = indices.get("eth", {})
    flow = snapshot.get("investor_flow", {})

    if kospi.get("value"):
        lines.append(f"*KOSPI* {kospi['value']:,.2f} ({kospi.get('change_pct', 0):+.1f}%)")
    if kosdaq.get("value"):
        lines.append(f"*KOSDAQ* {kosdaq['value']:,.2f} ({kosdaq.get('change_pct', 0):+.1f}%)")
    if fx.get("value"):
        lines.append(f"*원/달러* {fx['value']:,.1f}원")
    if wti.get("value"):
        lines.append(f"*WTI* ${wti['value']:,.1f} ({wti.get('change_pct', 0):+.1f}%)")
    if gold.get("value"):
        lines.append(f"*금* ${gold['value']:,.0f} ({gold.get('change_pct', 0):+.1f}%)")
    if btc.get("value_krw"):
        lines.append(f"*BTC* {btc['value_krw']:,.0f}원 ({btc.get('change_pct', 0):+.1f}%)")
    if eth.get("value_krw"):
        lines.append(f"*ETH* {eth['value_krw']:,.0f}원 ({eth.get('change_pct', 0):+.1f}%)")
    # 수급은 에이전트가 한투 API 실시간으로 가져오므로 상단에서 제외
    return lines


def send_checklist_status(override_hour: int = None) -> Dict:
    """
    체크리스트 현황 정기 리포트 (텔레그램 발송)
    - 체크리스트 원문 + 에이전트 분석 결과
    - override_hour: 테스트용 시간 오버라이드
    """
    from reports.telegram_sender import send_telegram_message

    snapshot = fetch_market_snapshot()
    checklist_text = load_checklist()

    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    hour = override_hour if override_hour is not None else now.hour

    if hour < 9:
        title, phase = "장 시작 전", "pre_market"
    elif hour < 10:
        title, phase = "장 초반", "intraday"
    elif hour < 12:
        title, phase = "오전장", "intraday"
    elif hour < 15:
        title = "장 중반" if hour < 14 else "마감 임박"
        phase = "intraday"
    else:
        title, phase = "장 마감", "close"

    lines = [f"📋 *{title} — {now.strftime('%Y-%m-%d %H:%M')}*\n"]

    # 시장 현황
    lines.extend(_format_market_snapshot(snapshot))
    lines.append("")

    # 전체 체크리스트를 에이전트에 전달 + 시간대 힌트
    # 에이전트가 time_phase에 맞는 항목만 분석하도록 위임
    phase_instructions = {
        "pre_market": "지금은 장 시작 전(08:30~09:00)입니다. 체크리스트에서 '장 시작 전' 관련 항목만 골라서 분석하세요.",
        "intraday": "지금은 장중(09:00~15:30)입니다. 체크리스트에서 '장 중' 관련 항목과 '주의 가격 레벨' 항목을 분석하세요.",
        "close": "지금은 장 마감 시점입니다. 체크리스트 전체 항목의 최종 결과를 정리하고, 오늘 시장 요약을 작성하세요. 체크리스트 원문은 반복하지 마세요.",
    }
    instruction = phase_instructions.get(phase, "")
    checklist_for_agent = (
        f"[시간대: {phase}]\n{instruction}\n\n"
        f"=== 오늘 체크리스트 원문 ===\n{checklist_text}"
    ) if checklist_text else ""

    # 체크리스트 + 에이전트 분석 (BIP-Agents API 호출)
    if checklist_for_agent:
        try:
            from utils.audited_llm import record_agent_audit
        except Exception:
            record_agent_audit = None

        try:
            agent_url = os.getenv("BIP_AGENTS_API_URL", "http://bip-agents-api:8100")
            resp = requests.post(
                f"{agent_url}/api/checklist/analyze",
                json={
                    "checklist_text": checklist_for_agent,
                    "time_phase": phase,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                body = resp.json()
                analysis = body.get("analysis_result", "")
                audit_meta = body.get("audit") or {}

                # BIP-Agents 응답 감사 기록 (거버넌스 3-3, 3-4)
                if record_agent_audit and audit_meta:
                    try:
                        record_agent_audit(
                            agent_name=audit_meta.get("agent_name", "market_monitor_checklist"),
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
                        logger.warning(f"감사 로그 기록 실패: {audit_err}")

                if analysis:
                    # 에이전트 마크다운 → 텔레그램 Markdown 변환
                    analysis = re.sub(r'\*\*(.+?)\*\*', r'*\1*', analysis)  # **bold** → *bold*
                    analysis = re.sub(r'^#{1,3}\s+', '', analysis, flags=re.MULTILINE)  # ## 헤딩 제거
                    analysis = re.sub(r'-{3,}', '———————————————', analysis)  # --- → 구분선
                    analysis = re.sub(r'[━─]{3,}', '———————————————', analysis)  # ━━━ → 구분선
                    # 연속 구분선 제거
                    analysis = re.sub(r'(———————————————\n?){2,}', '———————————————\n', analysis)
                    for line in analysis.split("\n"):
                        stripped = line.strip()
                        if stripped:
                            lines.append(stripped)
                else:
                    lines.append("에이전트 분석 결과 없음")
            else:
                logger.warning(f"에이전트 API 오류: {resp.status_code}")
                # fallback: 원문만 표시
                for line in checklist_text.split("\n"):
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)
        except Exception as e:
            logger.warning(f"에이전트 API 호출 실패: {e}")
            for line in checklist_text.split("\n"):
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
    else:
        lines.append("체크리스트 없음")

    msg = "\n".join(lines)
    success = send_telegram_message(msg)

    return {"sent": success, "has_checklist": bool(checklist_text)}


def run_monitor_cycle() -> Dict:
    """
    모니터링 1 사이클 실행
    Returns: {"alerts_sent": N, "snapshot": {...}, "alerts": [...]}
    """
    # 1. 시장 스냅샷
    snapshot = fetch_market_snapshot()
    logger.info(f"스냅샷: {snapshot.get('timestamp')} | "
                f"KOSPI {snapshot.get('indices', {}).get('kospi', {}).get('value', 'N/A')}")

    all_alerts = []

    # 2. Layer 1: 상시 규칙 체크
    layer1_alerts = check_layer1_rules(snapshot)
    all_alerts.extend(layer1_alerts)

    # Layer 2는 에이전트 기반으로 전환 → 정기 현황에서 처리
    # run_monitor_cycle에서는 Layer 1 이상치만 알림

    # 3. 알림 발송
    sent_count = 0
    if all_alerts:
        sent_count = send_alerts(all_alerts, snapshot=snapshot)

    return {
        "timestamp": snapshot.get("timestamp"),
        "alerts_sent": sent_count,
        "total_alerts": len(all_alerts),
        "layer1": len(layer1_alerts),
    }
