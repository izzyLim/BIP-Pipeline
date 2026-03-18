"""
LLM 분석기 v2
- RAG 기반 뉴스 컨텍스트 통합
- 단계별 심층 분석
- OpenAI GPT / Claude Sonnet / Claude Haiku 지원
"""

import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ============================================================
# LLM 모델 설정
# 환경변수 LLM_MODEL로 선택 가능:
#   - "gpt-5.4"       : OpenAI GPT-5.4 (고품질)
#   - "claude-sonnet" : Claude Sonnet 4 (고품질, Tier 2 이상 필요)
#   - "claude-haiku"  : Claude Haiku 4.5 (빠르고 저렴)
# ============================================================
DEFAULT_LLM_MODEL = "gpt-5.4"

# 모델별 설정
MODEL_CONFIG = {
    "gpt-5.4": {
        "provider": "openai",
        "model_id": "gpt-5.4",
        "max_tokens": 12000,  # GPT-5.4는 긴 응답 가능
    },
    "claude-sonnet": {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-20250514",
        "max_tokens": 8000,
    },
    "claude-haiku": {
        "provider": "anthropic",
        "model_id": "claude-haiku-4-5-20251001",
        "max_tokens": 8000,
    },
}


def get_llm_model():
    """환경변수에서 LLM 모델 설정 가져오기"""
    model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
    if model not in MODEL_CONFIG:
        logger.warning(f"알 수 없는 모델 '{model}', 기본값 '{DEFAULT_LLM_MODEL}' 사용")
        model = DEFAULT_LLM_MODEL
    return model


def get_api_key(provider: str):
    """API 키 로드"""
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY")
    else:
        return os.getenv("ANTHROPIC_API_KEY")


def call_llm(prompt: str) -> str:
    """
    설정된 LLM 모델로 API 호출

    Returns:
        생성된 텍스트
    """
    model_name = get_llm_model()
    config = MODEL_CONFIG[model_name]
    provider = config["provider"]
    model_id = config["model_id"]
    max_tokens = config["max_tokens"]

    api_key = get_api_key(provider)
    if not api_key:
        key_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
        return f"{key_name}가 설정되지 않았습니다."

    logger.info(f"LLM 호출: {model_name} ({provider}/{model_id})")

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model_id,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        # 응답 디버깅
        finish_reason = response.choices[0].finish_reason
        logger.info(f"OpenAI 응답 finish_reason: {finish_reason}")

        content = response.choices[0].message.content
        if content:
            logger.info(f"OpenAI 응답 길이: {len(content)} 글자")
            if finish_reason == "length":
                logger.warning("응답이 토큰 한도로 잘렸습니다. 내용은 있음.")
        else:
            logger.warning("OpenAI 응답이 비어있습니다!")
            # refusal 체크
            if hasattr(response.choices[0].message, 'refusal') and response.choices[0].message.refusal:
                logger.warning(f"OpenAI refusal: {response.choices[0].message.refusal}")
                return f"분석 거부됨: {response.choices[0].message.refusal}"
        return content or "분석 생성 실패"
    else:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text


# 단계별 분석 프롬프트 (v2.3 - 심층 분석 + 국제 정세 + 이벤트 + 데이터 우선)
ANALYSIS_PROMPT_V2 = """당신은 20년 경력의 글로벌 매크로 애널리스트이자 개인 투자자 멘토입니다.
아래 시장 데이터와 최신 뉴스를 분석하여, **깊이 있고 통찰력 있는** 시장 분석 리포트를 작성해주세요.

## 분석 원칙 (중요!)
1. **실제 데이터 우선**: 아래 제공된 시장 데이터(지수, 환율, 주가 등)가 뉴스 내용과 다를 경우, **반드시 실제 데이터를 기준으로 분석**하세요. 뉴스는 참고용이며, 숫자는 아래 데이터를 정확히 인용하세요.
2. **깊이 있는 설명**: 단순 나열이 아닌, "왜 그런지", "어떤 의미인지", "앞으로 어떻게 될 수 있는지" 맥락과 배경을 충분히 설명
3. **구체적 근거 제시**: 뉴스, 데이터, 과거 사례를 인용하며 분석의 근거를 명확히
4. **실행 가능한 인사이트**: 읽고 나서 "그래서 뭘 해야 하지?"가 아닌, 구체적인 행동 지침 제공
5. **균형 잡힌 시각**: 기회와 리스크를 모두 분석
6. **이벤트 감지 필수**: 뉴스에서 테크 컨퍼런스(GTC, WWDC 등), FOMC, 지정학적 이슈, 대형 실적 발표 등 주요 이벤트가 언급되면 반드시 "특별 이벤트" 섹션에서 심층 분석하세요

## 오늘의 시장 데이터

### 주요 지수
{indices_summary}

### 한국 시장
{korea_summary}

### 미국 시장
{us_summary}

### 매크로 지표
{macro_summary}

### 투자자 동향
{investor_flow}

### 반도체 가격
{semiconductor}

### 달러 인덱스 & 반도체 지수
{dollar_semi_index}

### 글로벌 지수 (아시아/유럽)
{global_indices}

### 미국 섹터별 등락
{us_sectors}

### 한국 섹터별 등락
{kr_sectors}

## 최신 뉴스
{news_context}

## 출력 형식 (총 2500자 이상, 충분히 자세하게)

---

### 📌 오늘의 핵심 (2-3문장)
가장 중요한 시장 이슈와 그 의미를 요약. 단순 수치가 아닌 "왜 중요한지" 포함.

---

### 🌍 글로벌 정세 & 매크로 환경

**국제 정세**
- 현재 글로벌 시장에 영향을 미치는 주요 지정학적/경제적 이슈 분석
- (예: 중동 전쟁, 미중 갈등, 각국 통화정책 등)
- 이 이슈들이 금융 시장에 미치는 영향과 향후 전망

**글로벌 매크로 흐름**
- 달러 강세/약세 흐름과 배경
- 글로벌 금리 동향 (연준, ECB, BOJ 등)
- 원자재 시장 동향 (유가, 금 등)
- 비트코인 동향 (위험자산 선호도, 유동성 지표로서의 의미)
- 이러한 흐름이 한국 시장에 미치는 영향

---

### 🔥 특별 이벤트/사건 심층 분석

**※ 중요: 위 뉴스에서 다음과 같은 특별 이벤트가 언급되었는지 반드시 확인하고, 있다면 이 섹션을 작성하세요:**
- 테크 컨퍼런스: NVIDIA GTC, 애플 WWDC, 구글 I/O, MS Build, CES 등
- 중앙은행 이벤트: FOMC, BOJ 회의, ECB 회의, 금리 결정
- 지정학적 이슈: 전쟁, 무역 갈등, 제재, 정상회담
- 기업 이벤트: 대형 실적 발표, M&A, IPO, 파산
- 경제 이벤트: 고용지표 발표, GDP 발표, 물가지표 발표
- 기타: 자연재해, 대규모 해킹, 규제 발표 등

**뉴스에서 위 이벤트가 하나라도 언급되면 반드시 아래 형식으로 분석하세요:**

**🎯 이벤트 개요**
- 이벤트/사건명과 현재 상황 요약
- 언제 발생했고, 현재 어떤 단계인지

**📜 배경 및 맥락**
- 이 이벤트가 발생하게 된 역사적/경제적/정치적 배경
- 관련된 주요 이해관계자들과 그들의 입장
- 과거 유사 사례가 있다면 비교 분석

**💰 시장 영향 분석**
- 직접적으로 영향받는 섹터/종목/자산군
- 수혜 업종과 피해 업종 구분
- 단기적 영향 vs 중장기적 영향

**🔮 향후 시나리오**
- 시나리오 1 (낙관): 어떻게 전개될 경우 시장에 긍정적인지
- 시나리오 2 (비관): 어떻게 전개될 경우 시장에 부정적인지
- 현재 어느 시나리오에 가까운지 판단과 근거

**📌 투자자 대응 전략**
- 이 이벤트를 고려한 포트폴리오 조정 방향
- 주목해야 할 지표나 뉴스
- 관련 종목 매매 시 유의사항

---

### 🇺🇸 미국 시장 심층 분석

**어제 미국 시장 움직임**
- 주요 지수 등락과 그 원인 (단순 수치 나열 X, 왜 그랬는지 설명)
- 섹터별 차별화된 움직임과 배경
- 주요 종목 이슈 (실적 발표, 뉴스 등)

**핵심 포인트**
- 미국 시장에서 주목해야 할 시그널
- 한국 시장에 영향을 줄 요소들

---

### 🇰🇷 한국 시장 심층 분석

**어제 한국 시장 움직임**
- 코스피/코스닥 등락 원인 심층 분석
- 왜 이렇게 움직였는지 뉴스와 연결하여 구체적으로 설명
- 섹터별 등락과 그 배경

**수급 분석**
- 외국인/기관/개인 매매 동향
- 이 수급이 의미하는 바 (단순 숫자가 아닌 해석)
- 특정 섹터나 종목에 대한 수급 특이점

**주목할 섹터/종목**
- 강세 섹터: 왜 강했는지, 지속 가능성은?
- 약세 섹터: 왜 약했는지, 반등 가능성은?
- 개별 종목 이슈 (실적, 뉴스, 수급 등)

---

### 🔗 한국↔미국 연결고리

- 미국 시장의 어떤 움직임이 한국에 어떻게 전이되는지
- 동조화 vs 디커플링 분석
- 오늘 한국 시장 전망에 미치는 영향

---

### 🔬 반도체 섹터 심층 분석

**메모리 현물가격 분석** (위 반도체 가격 데이터를 반드시 인용하여 작성)
- 현재 DRAM/NAND 현물가격: 위 데이터의 정확한 가격과 등락률을 명시
- 최근 가격 추이 (상승/하락/보합)와 그 원인 분석
- 향후 가격 전망과 메모리 업체 실적에 미치는 영향

**HBM/고부가 제품 동향**
- HBM3E, HBM4 등 AI용 고대역폭 메모리 수요와 공급 현황
- DDR5 전환 사이클과 가격 프리미엄 분석
- SK하이닉스, 삼성전자의 HBM 시장 점유율과 경쟁력

**글로벌 반도체 산업**
- AI/데이터센터 수요와 반도체 업황 연결
- 미국 반도체 기업(NVIDIA, AMD, Intel 등) 실적/주가와 한국 영향
- 파운드리/메모리 업황 차별화 분석

**국내 반도체 기업 분석**
- 삼성전자, SK하이닉스 주가 움직임과 원인 (위 종가 데이터 참고)
- 반도체 장비/소재 업체 동향
- 투자 관점에서의 매수/매도 타이밍 시사점

---

### 💡 투자 아이디어 & 전략

**기회 요인**
- 어떤 섹터/종목이 왜 기회인지 구체적으로
- 진입 시 고려할 조건, 목표 수준, 손절 기준
- 관련 종목 (2-3개)과 각각의 투자 포인트

**리스크 요인**
- 현재 시장의 주요 리스크는 무엇인지
- 어떤 섹터/종목을 왜 주의해야 하는지
- 리스크가 현실화될 경우 대응 방안

---

### 📅 이번 주 주요 이벤트

| 날짜 | 이벤트 | 영향 예상 |
|------|--------|-----------|
| (날짜) | (이벤트명) | (어떤 영향이 예상되는지) |
| (날짜) | (이벤트명) | (어떤 영향이 예상되는지) |
| ... | ... | ... |

※ 실적 발표, 경제지표 발표, FOMC, 옵션만기일 등 시장에 영향을 줄 이벤트 포함

---

### ✅ 오늘의 체크리스트

□ (장 시작 전 확인할 것 - 구체적으로)
□ (장 중 모니터링할 것)
□ (주의해야 할 가격 레벨이나 이벤트)

---

참고: 위 분석은 투자 권유가 아닌 정보 제공 목적입니다. 투자 결정은 본인의 판단과 책임하에 이루어져야 합니다.
"""


def format_indices_summary(indices_data: Dict) -> str:
    """주요 지수 포맷팅 (전일/1주/1개월/3개월 추세 포함)"""
    if not indices_data:
        return "데이터 없음"

    lines = []
    name_map = {'kospi': 'KOSPI', 'kosdaq': 'KOSDAQ', 'sp500': 'S&P 500', 'nasdaq': 'NASDAQ'}
    for key, name in name_map.items():
        data = indices_data.get(key, {})
        if data:
            val = data.get('value', 0)
            chg = data.get('change_pct', 0)
            week_chg = data.get('week_change_pct')
            month_chg = data.get('month_change_pct')
            quarter_chg = data.get('quarter_change_pct')

            trend_str = f"전일 {chg:+.2f}%"
            if week_chg is not None:
                trend_str += f", 1주 {week_chg:+.2f}%"
            if month_chg is not None:
                trend_str += f", 1개월 {month_chg:+.2f}%"
            if quarter_chg is not None:
                trend_str += f", 3개월 {quarter_chg:+.2f}%"
            lines.append(f"- {name}: {val:,.2f} ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_korea_summary(korea_data: Dict) -> str:
    """한국 시장 데이터 포맷팅"""
    if not korea_data.get("stocks"):
        return "데이터 없음"

    lines = []

    # 상위 10개 종목 (종가 포함)
    top_stocks = korea_data["stocks"][:10]
    lines.append("시총 상위 종목:")
    for s in top_stocks:
        close = s.get('close', 0)
        if close >= 10000:
            price_str = f"{close:,.0f}원"
        else:
            price_str = f"{close:,.0f}원"
        lines.append(f"  - {s['stock_name']}: {price_str} ({s['change_pct']:+.1f}%)")

    # 섹터 요약
    sectors = korea_data.get("sector_summary", [])[:5]
    if sectors:
        lines.append("\n섹터별 등락:")
        for s in sectors:
            lines.append(f"  - {s['sector']}: {s['change_pct']:+.1f}%")

    return "\n".join(lines)


def format_us_summary(us_data: Dict) -> str:
    """미국 시장 데이터 포맷팅"""
    if not us_data.get("stocks"):
        return "데이터 없음"

    lines = []

    # 상위 10개 종목 (종가 포함)
    top_stocks = us_data["stocks"][:10]
    lines.append("시총 상위 종목:")
    for s in top_stocks:
        close = s.get('close', 0)
        lines.append(f"  - {s['stock_name']}: ${close:,.2f} ({s['change_pct']:+.1f}%)")

    # 섹터 요약
    sectors = us_data.get("sector_summary", [])[:5]
    if sectors:
        lines.append("\n섹터별 등락:")
        for s in sectors:
            lines.append(f"  - {s['sector']}: {s['change_pct']:+.1f}%")

    return "\n".join(lines)


def format_investor_flow(flow_data: list) -> str:
    """투자자 동향 포맷팅"""
    if not flow_data:
        return "데이터 없음"

    lines = []
    for day in flow_data[:5]:
        foreign = (day.get("foreign_amount", 0) or 0) / 100000000
        institution = (day.get("institution_amount", 0) or 0) / 100000000
        individual = (day.get("individual_amount", 0) or 0) / 100000000

        date_str = str(day.get('date', 'N/A'))[:10]
        lines.append(
            f"- {date_str}: 외국인 {foreign:+,.0f}억, "
            f"기관 {institution:+,.0f}억, 개인 {individual:+,.0f}억"
        )

    return "\n".join(lines) if lines else "데이터 없음"


def format_semiconductor(semi_data: list) -> str:
    """반도체 가격 포맷팅 (전일/1주/1개월/3개월 추세 포함)"""
    if not semi_data:
        return "데이터 없음"

    # 제품명 매핑 (가독성 향상)
    product_names = {
        'dram_ddr5_16gb': 'DDR5 16Gb',
        'dram_ddr5_16gb_ett': 'DDR5 16Gb (ETT)',
        'dram_ddr4_8gb': 'DDR4 8Gb',
        'dram_ddr4_8gb_ett': 'DDR4 8Gb (ETT)',
        'dram_ddr4_16gb': 'DDR4 16Gb',
        'dram_ddr4_16gb_ett': 'DDR4 16Gb (ETT)',
        'dram_ddr3_4gb': 'DDR3 4Gb',
        'nand_tlc_512gb': 'NAND TLC 512Gb',
        'nand_tlc_256gb': 'NAND TLC 256Gb',
        'nand_tlc_128gb': 'NAND TLC 128Gb',
        'nand_mlc_64gb': 'NAND MLC 64Gb',
        'nand_mlc_32gb': 'NAND MLC 32Gb',
        'nand_slc_2gb': 'NAND SLC 2Gb',
        'nand_slc_1gb': 'NAND SLC 1Gb',
    }

    # 주요 제품만 선택 (DDR5, DDR4 8Gb, NAND TLC 512Gb 등)
    priority_products = ['dram_ddr5_16gb', 'dram_ddr4_8gb', 'nand_tlc_512gb', 'nand_tlc_256gb']

    lines = []
    shown = set()

    def format_item(item):
        product_key = item.get("product_type", "")
        product = product_names.get(product_key, product_key)
        price = item.get("price", 0)
        change = item.get("price_change_pct", 0) or 0
        week_chg = item.get("week_change_pct")
        month_chg = item.get("month_change_pct")
        quarter_chg = item.get("quarter_change_pct")

        trend_str = f"전일 {change:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        return f"- {product}: ${price:.2f} ({trend_str})"

    # 우선순위 제품 먼저
    for product_key in priority_products:
        for item in semi_data:
            if item.get("product_type") == product_key and product_key not in shown:
                lines.append(format_item(item))
                shown.add(product_key)
                break

    # 나머지 제품 추가 (최대 8개)
    for item in semi_data:
        if len(lines) >= 8:
            break
        product_key = item.get("product_type", "")
        if product_key not in shown:
            lines.append(format_item(item))
            shown.add(product_key)

    return "\n".join(lines) if lines else "데이터 없음"


def format_macro_summary(macro_data: Dict) -> str:
    """매크로 지표 포맷팅 (전일/1주/1개월/3개월 추세 포함)"""
    lines = []

    # 환율 (명확하게 현재 값 표시 + 추세)
    exchange = macro_data.get("exchange_rates", {})
    if exchange.get("usd_krw"):
        val = exchange['usd_krw']['value']
        chg = exchange['usd_krw'].get('change_pct', 0)
        week_chg = exchange['usd_krw'].get('week_change_pct')
        month_chg = exchange['usd_krw'].get('month_change_pct')
        quarter_chg = exchange['usd_krw'].get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- USD/KRW: {val:,.2f}원 ({trend_str})")

    # 금리 (절대값 변동 표시, %p)
    rates = macro_data.get("interest_rates", {})
    if rates.get("us_10y"):
        val = rates['us_10y']['value']
        chg = rates['us_10y'].get('change_pct', 0)
        week_chg = rates['us_10y'].get('week_change')
        month_chg = rates['us_10y'].get('month_change')
        quarter_chg = rates['us_10y'].get('quarter_change')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%p"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%p"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%p"
        lines.append(f"- 미국 10년물: {val:.2f}% ({trend_str})")
    if rates.get("kr_3y"):
        val = rates['kr_3y']['value']
        chg = rates['kr_3y'].get('change_pct', 0)
        week_chg = rates['kr_3y'].get('week_change')
        month_chg = rates['kr_3y'].get('month_change')
        quarter_chg = rates['kr_3y'].get('quarter_change')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%p"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%p"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%p"
        lines.append(f"- 한국 3년물: {val:.2f}% ({trend_str})")

    # VIX / Fear & Greed (절대값 변동 표시)
    fear = macro_data.get("fear_greed", {})
    if fear.get("vix"):
        val = fear['vix']['value']
        week_chg = fear['vix'].get('week_change')
        month_chg = fear['vix'].get('month_change')
        quarter_chg = fear['vix'].get('quarter_change')
        trend_str = ""
        if week_chg is not None:
            trend_str += f"1주 {week_chg:+.1f}"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.1f}"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.1f}"
        if trend_str:
            lines.append(f"- VIX: {val:.1f} ({trend_str.lstrip(', ')})")
        else:
            lines.append(f"- VIX: {val:.1f}")
    if fear.get("fear_greed_index"):
        val = fear['fear_greed_index']['value']
        label = "극단적 공포" if val < 25 else "공포" if val < 45 else "중립" if val < 55 else "탐욕" if val < 75 else "극단적 탐욕"
        week_chg = fear['fear_greed_index'].get('week_change')
        month_chg = fear['fear_greed_index'].get('month_change')
        trend_str = ""
        if week_chg is not None:
            trend_str += f"1주 {week_chg:+.0f}"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.0f}"
        if trend_str:
            lines.append(f"- Fear & Greed: {val:.0f} ({label}, {trend_str.lstrip(', ')})")
        else:
            lines.append(f"- Fear & Greed: {val:.0f} ({label})")

    # 원자재 (추세 포함)
    commodities = macro_data.get("commodities", {})
    if commodities.get("gold"):
        val = commodities['gold']['value']
        chg = commodities['gold'].get('change_pct', 0)
        week_chg = commodities['gold'].get('week_change_pct')
        month_chg = commodities['gold'].get('month_change_pct')
        quarter_chg = commodities['gold'].get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- 금: ${val:,.0f} ({trend_str})")
    if commodities.get("oil"):
        val = commodities['oil']['value']
        chg = commodities['oil'].get('change_pct', 0)
        week_chg = commodities['oil'].get('week_change_pct')
        month_chg = commodities['oil'].get('month_change_pct')
        quarter_chg = commodities['oil'].get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- 원유: ${val:.1f} ({trend_str})")

    # 비트코인 (추세 포함)
    bitcoin = macro_data.get("bitcoin", {})
    if bitcoin.get("value"):
        val = bitcoin['value']
        chg = bitcoin.get('change_pct', 0)
        week_chg = bitcoin.get('week_change_pct')
        month_chg = bitcoin.get('month_change_pct')
        quarter_chg = bitcoin.get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- 비트코인: ${val:,.0f} ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_dollar_semi_index(macro_data: Dict) -> str:
    """달러 인덱스 & 반도체 지수 포맷팅"""
    lines = []

    # 달러 인덱스
    dollar = macro_data.get("dollar_index", {})
    if dollar.get("value"):
        val = dollar['value']
        chg = dollar.get('change_pct', 0)
        week_chg = dollar.get('week_change_pct')
        month_chg = dollar.get('month_change_pct')
        quarter_chg = dollar.get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- 달러인덱스(DXY): {val:.2f} ({trend_str})")

    # 반도체 지수/ETF
    semi = macro_data.get("semiconductor_index", {})
    name_map = {'sox': 'SOX(필라델피아반도체)', 'smh': 'SMH(반도체ETF)', 'soxx': 'SOXX(반도체ETF)'}
    for key in ['sox', 'smh']:  # SOX와 SMH만 표시 (SOXX는 중복)
        if semi.get(key):
            data = semi[key]
            val = data['value']
            chg = data.get('change_pct', 0)
            week_chg = data.get('week_change_pct')
            month_chg = data.get('month_change_pct')
            quarter_chg = data.get('quarter_change_pct')
            trend_str = f"전일 {chg:+.2f}%"
            if week_chg is not None:
                trend_str += f", 1주 {week_chg:+.2f}%"
            if month_chg is not None:
                trend_str += f", 1개월 {month_chg:+.2f}%"
            if quarter_chg is not None:
                trend_str += f", 3개월 {quarter_chg:+.2f}%"
            lines.append(f"- {name_map.get(key, key)}: {val:,.2f} ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_global_indices(macro_data: Dict) -> str:
    """글로벌 지수 포맷팅 (닛케이, 상하이, 유로스톡스)"""
    lines = []
    global_idx = macro_data.get("global_indices", {})

    name_map = {
        'nikkei': '닛케이225(일본)',
        'shanghai': '상하이종합(중국)',
        'eurostoxx': '유로스톡스50(유럽)',
        'sensex': 'SENSEX(인도)'
    }

    for key in ['nikkei', 'shanghai', 'eurostoxx', 'sensex']:
        if global_idx.get(key):
            data = global_idx[key]
            val = data['value']
            chg = data.get('change_pct', 0)
            week_chg = data.get('week_change_pct')
            month_chg = data.get('month_change_pct')
            quarter_chg = data.get('quarter_change_pct')
            trend_str = f"전일 {chg:+.2f}%"
            if week_chg is not None:
                trend_str += f", 1주 {week_chg:+.2f}%"
            if month_chg is not None:
                trend_str += f", 1개월 {month_chg:+.2f}%"
            if quarter_chg is not None:
                trend_str += f", 3개월 {quarter_chg:+.2f}%"
            lines.append(f"- {name_map.get(key, key)}: {val:,.2f} ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_us_sectors(macro_data: Dict) -> str:
    """미국 섹터별 등락 포맷팅"""
    lines = []
    sectors = macro_data.get("us_sectors", {})

    name_map = {
        'technology': '기술',
        'financials': '금융',
        'healthcare': '헬스케어',
        'consumer_disc': '임의소비재',
        'communication': '커뮤니케이션',
        'industrials': '산업재',
        'consumer_staples': '필수소비재',
        'energy': '에너지',
        'materials': '소재',
        'realestate': '부동산',
        'utilities': '유틸리티'
    }

    # 변동률 기준 정렬
    sorted_sectors = sorted(
        [(k, v) for k, v in sectors.items() if v.get('change_pct') is not None],
        key=lambda x: x[1].get('change_pct', 0),
        reverse=True
    )

    for key, data in sorted_sectors:
        chg = data.get('change_pct', 0)
        week_chg = data.get('week_change_pct')
        month_chg = data.get('month_change_pct')
        quarter_chg = data.get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- {name_map.get(key, key)}: ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def format_kr_sectors(macro_data: Dict) -> str:
    """한국 섹터별 등락 포맷팅"""
    lines = []
    sectors = macro_data.get("kr_sectors", {})

    # 변동률 기준 정렬
    sorted_sectors = sorted(
        [(k, v) for k, v in sectors.items() if v.get('change_pct') is not None],
        key=lambda x: x[1].get('change_pct', 0),
        reverse=True
    )

    for key, data in sorted_sectors:
        chg = data.get('change_pct', 0)
        week_chg = data.get('week_change_pct')
        month_chg = data.get('month_change_pct')
        quarter_chg = data.get('quarter_change_pct')
        trend_str = f"전일 {chg:+.2f}%"
        if week_chg is not None:
            trend_str += f", 1주 {week_chg:+.2f}%"
        if month_chg is not None:
            trend_str += f", 1개월 {month_chg:+.2f}%"
        if quarter_chg is not None:
            trend_str += f", 3개월 {quarter_chg:+.2f}%"
        lines.append(f"- {key}: ({trend_str})")

    return "\n".join(lines) if lines else "데이터 없음"


def analyze_market_v2(
    macro_data: Dict[str, Any],
    news_context: str = ""
) -> str:
    """
    시장 분석 생성 (v2 - RAG 통합, 멀티 LLM 지원)

    Args:
        macro_data: collect_all_macro_data()의 결과
        news_context: RAG로 검색한 관련 뉴스 텍스트

    Returns:
        분석 텍스트
    """
    # 데이터 포맷팅
    indices_summary = format_indices_summary(macro_data.get("indices", {}))
    korea_summary = format_korea_summary(macro_data.get("korea", {}))
    us_summary = format_us_summary(macro_data.get("us", {}))
    macro_summary = format_macro_summary(macro_data)
    investor_flow = format_investor_flow(macro_data.get("investor_flow", []))
    semiconductor = format_semiconductor(macro_data.get("semiconductor", []))

    # 새로 추가된 지표들
    dollar_semi_index = format_dollar_semi_index(macro_data)
    global_indices = format_global_indices(macro_data)
    us_sectors = format_us_sectors(macro_data)
    kr_sectors = format_kr_sectors(macro_data)

    # 뉴스 컨텍스트 (없으면 기본값)
    if not news_context:
        news_context = "관련 뉴스 없음"

    # 프롬프트 생성
    prompt = ANALYSIS_PROMPT_V2.format(
        indices_summary=indices_summary,
        korea_summary=korea_summary,
        us_summary=us_summary,
        macro_summary=macro_summary,
        investor_flow=investor_flow,
        semiconductor=semiconductor,
        dollar_semi_index=dollar_semi_index,
        global_indices=global_indices,
        us_sectors=us_sectors,
        kr_sectors=kr_sectors,
        news_context=news_context,
    )

    try:
        return call_llm(prompt)
    except Exception as e:
        logger.error(f"LLM 분석 실패: {e}")
        return f"분석 생성 중 오류 발생: {str(e)}"


if __name__ == "__main__":
    # 테스트
    test_data = {
        "indices": {
            "kospi": {"value": 2500, "change_pct": -1.5},
            "kosdaq": {"value": 800, "change_pct": -2.0},
            "sp500": {"value": 5000, "change_pct": 0.5},
            "nasdaq": {"value": 15000, "change_pct": 1.2}
        },
        "korea": {
            "stocks": [
                {"stock_name": "삼성전자", "change_pct": -2.5},
                {"stock_name": "SK하이닉스", "change_pct": -3.0},
            ],
            "sector_summary": [
                {"sector": "반도체", "change_pct": -2.8},
            ]
        }
    }

    test_news = """
1. 코스피 어디까지 떨어질까…증권가 예상은
   외국인 매도세 지속, 반도체 업황 우려...

2. 삼성전자, 지금이라도 사라...특별배당 전망
   저점 매수 기회라는 분석도...
"""

    print("=== LLM 분석 테스트 ===")
    result = analyze_market_v2(test_data, test_news)
    print(result)
