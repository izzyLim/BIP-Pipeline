"""
LLM 분석기
- Claude Sonnet을 사용한 매크로 시장 분석
- 데이터 기반 인사이트 생성
"""

import os
import json
from typing import Dict, Any, Optional
from anthropic import Anthropic


# Claude API 설정
MODEL = "claude-sonnet-4-20250514"


def get_api_key():
    """API 키 로드 (함수 호출 시점에 환경변수 읽기)"""
    return os.getenv("ANTHROPIC_API_KEY")


ANALYSIS_PROMPT = """당신은 20년 경력의 매크로 애널리스트입니다.
아래 시장 데이터를 분석하여 개인 투자자가 이해할 수 있는 시장 해설을 작성해주세요.

## 분석 원칙
1. 숫자 나열이 아닌 "의미"를 설명
2. 서로 연관된 지표는 함께 해석 (예: 환율↔외국인 수급, 금리↔성장주, VIX↔시장 심리)
3. 투자에 참고할 수 있는 시사점 제공
4. 불확실한 예측은 피하고, 팩트 기반 분석
5. 핵심만 간결하게 (400자 내외)

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

## 출력 형식
아래 형식으로 작성해주세요:

**오늘의 핵심**
(1-2문장으로 가장 중요한 포인트)

**주요 포인트**
• (첫 번째 포인트)
• (두 번째 포인트)
• (세 번째 포인트 - 필요시)

**주의할 점**
(리스크나 주의사항이 있다면 - 없으면 생략)
"""


def format_korea_summary(korea_data: Dict) -> str:
    """한국 시장 데이터 포맷팅"""
    if not korea_data.get("stocks"):
        return "데이터 없음"

    # 상위 10개 종목
    top_stocks = korea_data["stocks"][:10]
    stocks_text = "\n".join([
        f"- {s['stock_name']}: {s['change_pct']:+.1f}%"
        for s in top_stocks
    ])

    # 섹터 요약
    sectors = korea_data.get("sector_summary", [])[:5]
    sector_text = "\n".join([
        f"- {s['sector']}: {s['change_pct']:+.1f}%"
        for s in sectors
    ])

    return f"""시총 상위 종목:
{stocks_text}

섹터별 등락:
{sector_text}"""


def format_us_summary(us_data: Dict) -> str:
    """미국 시장 데이터 포맷팅"""
    if not us_data.get("stocks"):
        return "데이터 없음"

    # 상위 10개 종목
    top_stocks = us_data["stocks"][:10]
    stocks_text = "\n".join([
        f"- {s['stock_name']}: {s['change_pct']:+.1f}%"
        for s in top_stocks
    ])

    # 섹터 요약
    sectors = us_data.get("sector_summary", [])[:5]
    sector_text = "\n".join([
        f"- {s['sector']}: {s['change_pct']:+.1f}%"
        for s in sectors
    ])

    return f"""시총 상위 종목:
{stocks_text}

섹터별 등락:
{sector_text}"""


def format_investor_flow(flow_data: list) -> str:
    """투자자 동향 포맷팅"""
    if not flow_data:
        return "데이터 없음"

    lines = []
    for day in flow_data[:5]:
        foreign = day.get("foreign_amount", 0) or 0
        institution = day.get("institution_amount", 0) or 0
        individual = day.get("individual_amount", 0) or 0

        # 억원 단위로 변환
        foreign_b = foreign / 100000000
        institution_b = institution / 100000000
        individual_b = individual / 100000000

        lines.append(
            f"- {day.get('date', 'N/A')}: "
            f"외국인 {foreign_b:+,.0f}억, "
            f"기관 {institution_b:+,.0f}억, "
            f"개인 {individual_b:+,.0f}억"
        )

    return "\n".join(lines) if lines else "데이터 없음"


def format_semiconductor(semi_data: list) -> str:
    """반도체 가격 포맷팅"""
    if not semi_data:
        return "데이터 없음"

    lines = []
    for item in semi_data[:4]:
        product = item.get("product_type", "N/A")
        price = item.get("price", 0)
        change = item.get("price_change_pct", 0) or 0
        lines.append(f"- {product}: ${price:.2f} ({change:+.1f}%)")

    return "\n".join(lines) if lines else "데이터 없음"


def format_indices_summary(indices_data: Dict) -> str:
    """주요 지수 포맷팅"""
    if not indices_data:
        return "데이터 없음"

    lines = []
    name_map = {'kospi': 'KOSPI', 'kosdaq': 'KOSDAQ', 'sp500': 'S&P 500', 'nasdaq': 'NASDAQ'}
    for key, name in name_map.items():
        data = indices_data.get(key, {})
        if data:
            val = data.get('value', 0)
            chg = data.get('change_pct', 0)
            lines.append(f"- {name}: {val:,.2f} ({chg:+.1f}%)")

    return "\n".join(lines) if lines else "데이터 없음"


def format_macro_summary(macro_data: Dict) -> str:
    """매크로 지표 포맷팅 (환율, 금리, VIX, 원자재)"""
    lines = []

    # 환율
    exchange = macro_data.get("exchange_rates", {})
    if exchange.get("usd_krw"):
        val = exchange['usd_krw']['value']
        chg = exchange['usd_krw'].get('change_pct', 0)
        lines.append(f"- USD/KRW: {val:,.0f}원 ({chg:+.1f}%)")

    # 금리
    rates = macro_data.get("interest_rates", {})
    if rates.get("us_10y"):
        val = rates['us_10y']['value']
        chg = rates['us_10y'].get('change_pct', 0)
        lines.append(f"- 미국 10년물 금리: {val:.2f}% ({chg:+.1f}%)")
    if rates.get("kr_3y"):
        val = rates['kr_3y']['value']
        chg = rates['kr_3y'].get('change_pct', 0)
        lines.append(f"- 한국 3년물 금리: {val:.2f}% ({chg:+.1f}%)")

    # VIX / Fear & Greed
    fear = macro_data.get("fear_greed", {})
    if fear.get("vix"):
        val = fear['vix']['value']
        lines.append(f"- VIX (변동성지수): {val:.1f}")
    if fear.get("fear_greed_index"):
        val = fear['fear_greed_index']['value']
        label = "극단적 공포" if val < 25 else "공포" if val < 45 else "중립" if val < 55 else "탐욕" if val < 75 else "극단적 탐욕"
        lines.append(f"- Fear & Greed Index: {val:.0f} ({label})")

    # 원자재
    commodities = macro_data.get("commodities", {})
    if commodities.get("gold"):
        val = commodities['gold']['value']
        chg = commodities['gold'].get('change_pct', 0)
        lines.append(f"- 금: ${val:,.0f} ({chg:+.1f}%)")
    if commodities.get("oil"):
        val = commodities['oil']['value']
        chg = commodities['oil'].get('change_pct', 0)
        lines.append(f"- 원유: ${val:.1f} ({chg:+.1f}%)")

    return "\n".join(lines) if lines else "데이터 없음"


def analyze_market(macro_data: Dict[str, Any]) -> str:
    """
    Claude를 사용하여 시장 분석 생성

    Args:
        macro_data: collect_all_macro_data()의 결과

    Returns:
        분석 텍스트
    """
    api_key = get_api_key()
    if not api_key:
        return "⚠️ ANTHROPIC_API_KEY가 설정되지 않았습니다."

    # 데이터 포맷팅
    indices_summary = format_indices_summary(macro_data.get("indices", {}))
    korea_summary = format_korea_summary(macro_data.get("korea", {}))
    us_summary = format_us_summary(macro_data.get("us", {}))
    macro_summary = format_macro_summary(macro_data)
    investor_flow = format_investor_flow(macro_data.get("investor_flow", []))
    semiconductor = format_semiconductor(macro_data.get("semiconductor", []))

    # 프롬프트 생성
    prompt = ANALYSIS_PROMPT.format(
        indices_summary=indices_summary,
        korea_summary=korea_summary,
        us_summary=us_summary,
        macro_summary=macro_summary,
        investor_flow=investor_flow,
        semiconductor=semiconductor,
    )

    try:
        client = Anthropic(api_key=api_key)

        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        return response.content[0].text

    except Exception as e:
        return f"⚠️ 분석 생성 중 오류 발생: {str(e)}"


if __name__ == "__main__":
    # 테스트용 더미 데이터
    test_data = {
        "korea": {
            "stocks": [
                {"stock_name": "삼성전자", "change_pct": 1.5},
                {"stock_name": "SK하이닉스", "change_pct": 2.8},
                {"stock_name": "현대차", "change_pct": -0.5},
            ],
            "sector_summary": [
                {"sector": "반도체", "change_pct": 2.1},
                {"sector": "자동차", "change_pct": -0.3},
            ]
        },
        "us": {
            "stocks": [
                {"stock_name": "NVIDIA", "change_pct": 3.2},
                {"stock_name": "Apple", "change_pct": 0.5},
            ],
            "sector_summary": [
                {"sector": "Technology", "change_pct": 1.8},
            ]
        },
        "investor_flow": [
            {"date": "2026-03-14", "foreign_amount": 342100000000,
             "institution_amount": -189200000000, "individual_amount": -152900000000}
        ],
        "semiconductor": [
            {"product_type": "DRAM_DDR5_8Gb", "price": 2.85, "price_change_pct": -3.2}
        ]
    }

    print("=== 프롬프트 테스트 ===")
    print(format_korea_summary(test_data["korea"]))
    print("\n=== LLM 분석 ===")
    result = analyze_market(test_data)
    print(result)
