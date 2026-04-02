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

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://user:pw1234@bip-postgres:5432/stockdb"
)


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
    level: str          # "🔴 긴급", "🟡 주의", "🟢 참고"
    category: str       # "index", "stock", "fx", "checklist"
    title: str
    description: str
    data: Dict = field(default_factory=dict)


# 상시 모니터링 임계값 (매크로 + 수급 + 원자재/크립토)
ALERT_RULES = {
    "index_critical": 3.0,       # 지수 ±3% 긴급
    "index_warning": 2.0,        # 지수 ±2% 주의
    "fx_critical": 1.5,          # 환율 ±1.5% 긴급
    "fx_warning": 0.7,           # 환율 ±0.7% 주의
    "flow_critical": 50000,      # 외국인/기관 순매수 ±5조 긴급
    "flow_warning": 40000,       # 외국인/기관 순매수 ±4조 주의
    "wti_critical": 8.0,         # WTI ±8% 긴급
    "wti_warning": 5.0,          # WTI ±5% 주의
    "gold_critical": 5.0,        # 금 ±5% 긴급
    "gold_warning": 3.0,         # 금 ±3% 주의
    "crypto_critical": 12.0,     # BTC/ETH ±12% 긴급
    "crypto_warning": 8.0,       # BTC/ETH ±8% 주의
}


def check_layer1_rules(snapshot: Dict) -> List[Alert]:
    """상시 규칙 기반 이상치 감지 (매크로 지표 + 장중 수급)"""
    alerts = []
    indices = snapshot.get("indices", {})

    # 지수 체크
    for idx_name, idx_key in [("KOSPI", "kospi"), ("KOSDAQ", "kosdaq")]:
        idx = indices.get(idx_key, {})
        pct = abs(idx.get("change_pct", 0))
        direction = "급등" if idx.get("change_pct", 0) > 0 else "급락"

        if pct >= ALERT_RULES["index_critical"]:
            alerts.append(Alert(
                level="🔴 긴급",
                category="index",
                title=f"{idx_name} {direction} {idx.get('change_pct', 0):+.1f}%",
                description=f"{idx_name} 현재 {idx.get('value', 0):,.2f} "
                            f"({idx.get('change_pct', 0):+.1f}%) — 시장 급변동 주의",
                data=idx,
            ))
        elif pct >= ALERT_RULES["index_warning"]:
            alerts.append(Alert(
                level="🟡 주의",
                category="index",
                title=f"{idx_name} {direction} {idx.get('change_pct', 0):+.1f}%",
                description=f"{idx_name} 현재 {idx.get('value', 0):,.2f}",
                data=idx,
            ))

    # 장중 투자자 수급 체크
    flow = snapshot.get("investor_flow", {})
    if flow:
        for investor, key in [("외국인", "foreign"), ("기관", "institution")]:
            amount = flow.get(key, 0)
            abs_amount = abs(amount)
            direction = "순매수" if amount > 0 else "순매도"

            if abs_amount >= ALERT_RULES["flow_critical"]:
                alerts.append(Alert(
                    level="🔴 긴급",
                    category="flow",
                    title=f"{investor} {direction} {abs_amount:,}억원",
                    description=f"{investor} 장중 {direction} {abs_amount:,}억원 — 대규모 수급 이동",
                    data={"investor": investor, "amount": amount},
                ))
            elif abs_amount >= ALERT_RULES["flow_warning"]:
                alerts.append(Alert(
                    level="🟡 주의",
                    category="flow",
                    title=f"{investor} {direction} {abs_amount:,}억원",
                    description=f"{investor} 장중 {direction} {abs_amount:,}억원",
                    data={"investor": investor, "amount": amount},
                ))

    # 원자재 체크
    for name, key, crit, warn in [
        ("WTI", "wti", "wti_critical", "wti_warning"),
        ("금", "gold", "gold_critical", "gold_warning"),
    ]:
        item = indices.get(key, {})
        pct = abs(item.get("change_pct", 0))
        if pct == 0:
            continue
        direction = "급등" if item.get("change_pct", 0) > 0 else "급락"

        if pct >= ALERT_RULES[crit]:
            alerts.append(Alert(
                level="🔴 긴급",
                category="commodity",
                title=f"{name} {direction} {item['change_pct']:+.1f}%",
                description=f"{name} ${item.get('value', 0):,.1f} ({item['change_pct']:+.1f}%)",
                data=item,
            ))
        elif pct >= ALERT_RULES[warn]:
            alerts.append(Alert(
                level="🟡 주의",
                category="commodity",
                title=f"{name} {direction} {item['change_pct']:+.1f}%",
                description=f"{name} ${item.get('value', 0):,.1f}",
                data=item,
            ))

    # 크립토 체크
    for name, key in [("BTC", "btc"), ("ETH", "eth")]:
        item = indices.get(key, {})
        pct = abs(item.get("change_pct", 0))
        if pct == 0:
            continue
        direction = "급등" if item.get("change_pct", 0) > 0 else "급락"

        if pct >= ALERT_RULES["crypto_critical"]:
            alerts.append(Alert(
                level="🔴 긴급",
                category="crypto",
                title=f"{name} {direction} {item['change_pct']:+.1f}%",
                description=f"{name} {item.get('value_krw', 0):,.0f}원 ({item['change_pct']:+.1f}%)",
                data=item,
            ))
        elif pct >= ALERT_RULES["crypto_warning"]:
            alerts.append(Alert(
                level="🟡 주의",
                category="crypto",
                title=f"{name} {direction} {item['change_pct']:+.1f}%",
                description=f"{name} {item.get('value_krw', 0):,.0f}원",
                data=item,
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
    """오늘의 체크리스트 원문 DB에서 로드"""
    if not target_date:
        from zoneinfo import ZoneInfo
        target_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT checklist_text FROM monitor_checklist
            WHERE checklist_date = :d
        """), {"d": target_date}).fetchone()

    return row[0] if row else ""


# ── 하위 호환용 (DAG에서 호출하는 함수명 유지) ──
def parse_checklist_with_llm(checklist_text: str) -> List[Dict]:
    """
    모닝리포트 체크리스트를 Haiku로 구조화 파싱
    Returns: 모니터링 가능한 룰 리스트
    """
    import anthropic

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
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": f"체크리스트:\n{checklist_text}"}],
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
# 4. 알림 발송 (중복 방지 포함)
# ──────────────────────────────────────────────

# 오늘 발송된 알림 키 추적 (메모리)
_sent_alerts: set = set()


def _alert_key(alert: Alert) -> str:
    """알림 중복 방지용 키 생성"""
    return f"{alert.category}:{alert.title}"


def format_alert_message(alerts: List[Alert], snapshot: Dict = None) -> str:
    """알림 리스트를 텔레그램 메시지로 포맷 (시장 현황 포함)"""
    now = datetime.now().strftime("%H:%M")
    lines = [f"⏰ *Market Alert — {now}*\n"]

    for alert in alerts:
        lines.append(f"{alert.level}")
        lines.append(f"*{alert.title}*")
        lines.append(f"{alert.description}\n")

    # 시장 현황 요약
    if snapshot:
        lines.append("— 현재 시장 —")
        lines.extend(_format_market_snapshot(snapshot))

    return "\n".join(lines)


def _save_alert_to_db(alert: Alert):
    """알림 이력 DB 저장"""
    try:
        engine = _get_engine()
        checklist_id = alert.data.get("db_id") if alert.category == "checklist" else None
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO monitor_alerts
                    (alert_date, alert_time, level, category, title, description, data, checklist_id)
                VALUES (CURRENT_DATE, NOW(), :level, :cat, :title, :desc, :data, :cid)
            """), {
                "level": alert.level,
                "cat": alert.category,
                "title": alert.title,
                "desc": alert.description,
                "data": json.dumps(alert.data, ensure_ascii=False, default=str),
                "cid": checklist_id,
            })
        try:
            from utils.lineage import register_table_lineage_async
            register_table_lineage_async("monitor_alerts", source_tables=["monitor_checklist"])
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"알림 DB 저장 실패: {e}")


def send_alerts(alerts: List[Alert], snapshot: Dict = None) -> int:
    """알림 발송 (중복 제거 후 텔레그램 전송 + DB 저장)"""
    from reports.telegram_sender import send_telegram_message

    # 중복 제거
    new_alerts = []
    for alert in alerts:
        key = _alert_key(alert)
        if key not in _sent_alerts:
            _sent_alerts.add(key)
            new_alerts.append(alert)

    if not new_alerts:
        return 0

    message = format_alert_message(new_alerts, snapshot=snapshot)
    success = send_telegram_message(message)

    # DB에 알림 이력 저장
    for alert in new_alerts:
        _save_alert_to_db(alert)

    if success:
        logger.info(f"알림 {len(new_alerts)}건 발송 완료")
    else:
        logger.warning("알림 발송 실패")

    return len(new_alerts)


def reset_daily_alerts():
    """일일 알림 초기화 (매일 장 시작 전 호출)"""
    _sent_alerts.clear()


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

    now = datetime.now()
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

    lines = [f"📋 *{title} — {now.strftime('%H:%M')}*\n"]

    # 시장 현황
    lines.extend(_format_market_snapshot(snapshot))
    lines.append("")

    # 시간대별 체크리스트 필터링
    phase_headers = {
        "pre_market": ["장 시작 전"],
        "intraday": ["장 중", "장중", "모니터링"],
        "close": [],  # 전체
    }
    if phase == "close" and checklist_text:
        # 장 마감: 체크리스트 원문 대신 요약 요청
        checklist_for_agent = (
            "오늘 체크리스트 항목:\n" + checklist_text + "\n\n"
            "위 체크리스트의 최종 결과를 확인하고, "
            "오늘 시장 전체 요약을 작성해주세요. 체크리스트 원문은 반복하지 마세요."
        )
    elif phase != "close" and checklist_text:
        filtered_lines = []
        current_section_match = False
        for line in checklist_text.split("\n"):
            stripped = line.strip()
            # 섹션 헤더 감지
            if stripped and not stripped.startswith("□"):
                keywords = phase_headers.get(phase, [])
                current_section_match = any(k in stripped for k in keywords)
                # 가격 레벨은 장중에도 포함
                if phase == "intraday" and any(k in stripped for k in ["가격", "레벨", "주의"]):
                    current_section_match = True
            if current_section_match and stripped:
                filtered_lines.append(stripped)
        checklist_for_agent = "\n".join(filtered_lines) if filtered_lines else checklist_text
    else:
        checklist_for_agent = checklist_text

    # 체크리스트 + 에이전트 분석 (BIP-Agents API 호출)
    if checklist_for_agent:
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
                analysis = resp.json().get("analysis_result", "")
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
