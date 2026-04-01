"""
OpenMetadata 투자 비즈니스 용어집(Glossary) 구축 스크립트

사용법:
    python scripts/om_build_glossary.py [--dry-run] [--reset]

옵션:
    --dry-run   실제 API 호출 없이 등록할 용어 목록만 출력
    --reset     기존 Glossary 삭제 후 재생성

환경변수:
    OM_HOST, OM_BOT_TOKEN
"""

import argparse
import json
import os
import sys
import time

import requests

OM_HOST = os.getenv("OM_HOST", "http://localhost:8585")
OM_BOT_TOKEN = os.getenv("OM_BOT_TOKEN", "")
GLOSSARY_NAME = "investment-terms"
GLOSSARY_DISPLAY = "투자 비즈니스 용어집"

# ─── 용어 정의 ──────────────────────────────────────────────────────────────────
#
# 구조:
#   {
#     "name": str,            # 영문 식별자 (slug)
#     "displayName": str,     # 표시 이름
#     "description": str,     # 상세 설명 (계산식, 해석 방법, DB 컬럼 매핑 포함)
#     "synonyms": list[str],  # 동의어
#     "parent": str | None,   # 상위 용어 name (계층 구조)
#   }
#
GLOSSARY_TERMS = [

    # ══════════════════════════════════════════════════════════════
    # 카테고리 루트 노드
    # ══════════════════════════════════════════════════════════════
    {
        "name": "valuation",
        "displayName": "밸류에이션 지표",
        "description": "기업의 주가 수준이 적정한지 판단하는 지표 그룹. 시가총액과 재무 데이터를 비교해 계산합니다.",
        "synonyms": ["가치평가 지표"],
        "parent": None,
    },
    {
        "name": "technical",
        "displayName": "기술적 지표",
        "description": "주가·거래량의 과거 패턴을 분석해 미래 방향성을 예측하는 지표 그룹. stock_indicators 테이블에 저장됩니다.",
        "synonyms": ["차트 지표", "보조 지표"],
        "parent": None,
    },
    {
        "name": "financial",
        "displayName": "재무제표 지표",
        "description": "기업의 손익·자산·현금흐름을 나타내는 지표 그룹. DART 공시 기반 financial_statements 테이블에 저장됩니다.",
        "synonyms": ["펀더멘털 지표"],
        "parent": None,
    },
    {
        "name": "stock-classification",
        "displayName": "종목 분류",
        "description": "시가총액·투자 성격·배당 성향 등에 따른 종목 분류 체계.",
        "synonyms": ["종목 유형"],
        "parent": None,
    },
    {
        "name": "market",
        "displayName": "시장·매크로 지표",
        "description": "개별 종목이 아닌 시장 전체 또는 거시경제를 나타내는 지표 그룹. macro_indicators 테이블에 저장됩니다.",
        "synonyms": ["거시경제 지표", "매크로"],
        "parent": None,
    },
    {
        "name": "consensus",
        "displayName": "컨센서스 지표",
        "description": "증권사 애널리스트들의 투자의견·목표주가·실적 추정치 집계. consensus_estimates 테이블에 저장됩니다.",
        "synonyms": ["애널리스트 추정치", "시장 컨센서스"],
        "parent": None,
    },
    {
        "name": "price",
        "displayName": "주가·시세 지표",
        "description": "개별 종목의 가격 관련 지표. stock_price_1d 등 시세 테이블에 저장됩니다.",
        "synonyms": ["시세", "주가"],
        "parent": None,
    },

    # ══════════════════════════════════════════════════════════════
    # 주가·시세
    # ══════════════════════════════════════════════════════════════
    {
        "name": "close-price",
        "displayName": "종가",
        "description": (
            "해당 거래일의 마지막 체결 가격.\n"
            "- DB: stock_price_1d.close\n"
            "- 단위: 원(KRW, 한국주식) 또는 달러(USD, 미국주식)\n"
            "- 주의: 수정주가 기준 (액면분할·배당 조정 반영)"
        ),
        "synonyms": ["closing price", "당일 종가"],
        "parent": "price",
    },
    {
        "name": "market-cap",
        "displayName": "시가총액",
        "description": (
            "현재 주가 × 상장 주식수. 기업의 시장 평가 가치.\n"
            "- DB: stock_info.market_value × 100,000,000\n"
            "- ⚠️ stock_info.market_value는 억원 단위. 원 단위로 사용 시 반드시 ×1억 변환 필요.\n"
            "- 예시: market_value=100,000 → 시총 100,000억원 = 10조원"
        ),
        "synonyms": ["시총", "market capitalization", "Market Cap"],
        "parent": "price",
    },
    {
        "name": "trading-volume",
        "displayName": "거래량",
        "description": (
            "해당 거래일에 체결된 총 주식 수.\n"
            "- DB: stock_price_1d.volume\n"
            "- 단위: 주(株)\n"
            "- 거래량이 평균(volume_ma20) 대비 급증하면 추세 변화 신호일 수 있음"
        ),
        "synonyms": ["volume", "일 거래량"],
        "parent": "price",
    },

    # ══════════════════════════════════════════════════════════════
    # 밸류에이션
    # ══════════════════════════════════════════════════════════════
    {
        "name": "per",
        "displayName": "PER (주가수익비율)",
        "description": (
            "Price-to-Earnings Ratio. 주가가 주당순이익(EPS)의 몇 배인지 나타냄.\n"
            "- 계산식: 시가총액(원) ÷ 당기순이익(원) = 시총 ÷ (EPS × 상장주식수)\n"
            "- DB(실제): (stock_info.market_value × 1억) ÷ financial_statements.net_income\n"
            "- DB(추정): consensus_estimates.est_per (애널리스트 추정 기준)\n"
            "- 단위: 배수(x). 예: PER 15 = 현재 주가가 EPS의 15배\n"
            "- 해석: 낮을수록 저평가 가능성. 단, 업종 평균과 비교 필수.\n"
            "- ⚠️ 적자 기업은 PER 계산 불가(음수 또는 N/A)"
        ),
        "synonyms": ["주가수익배율", "Price Earnings Ratio", "이익승수"],
        "parent": "valuation",
    },
    {
        "name": "pbr",
        "displayName": "PBR (주가순자산비율)",
        "description": (
            "Price-to-Book Ratio. 주가가 주당순자산(BPS)의 몇 배인지 나타냄.\n"
            "- 계산식: 시가총액(원) ÷ 자본총계(원)\n"
            "- DB(실제): (stock_info.market_value × 1억) ÷ financial_statements.total_equity\n"
            "- DB(추정): consensus_estimates.est_pbr\n"
            "- 단위: 배수(x). PBR 1.0 = 시총이 순자산과 동일\n"
            "- 해석: 1 미만이면 청산가치보다 낮게 거래됨 (자산 관점 저평가)\n"
            "- 활용: 금융주·제조업 등 자산 중심 업종에서 특히 유용"
        ),
        "synonyms": ["주가장부가치비율", "Price Book Ratio"],
        "parent": "valuation",
    },
    {
        "name": "roe",
        "displayName": "ROE (자기자본이익률)",
        "description": (
            "Return on Equity. 자기자본 대비 순이익의 비율. 주주 관점 수익성 지표.\n"
            "- 계산식: 당기순이익 ÷ 자본총계 × 100\n"
            "- DB: financial_statements.net_income ÷ financial_statements.total_equity × 100\n"
            "- DB(추정): consensus_estimates.est_roe\n"
            "- 단위: %(퍼센트)\n"
            "- 해석: 높을수록 자본 효율성 우수. 15% 이상이면 우량 기업으로 평가.\n"
            "- 주의: 과도한 부채로 자본을 줄여도 ROE가 높아질 수 있음 (부채비율 함께 확인)"
        ),
        "synonyms": ["자기자본수익률", "Return on Equity"],
        "parent": "valuation",
    },
    {
        "name": "eps",
        "displayName": "EPS (주당순이익)",
        "description": (
            "Earnings Per Share. 당기순이익을 발행 주식수로 나눈 1주당 이익.\n"
            "- 계산식: 당기순이익 ÷ 상장주식수\n"
            "- DB(추정): consensus_estimates.est_eps\n"
            "- 단위: 원(KRW) 또는 달러(USD)\n"
            "- 활용: PER = 주가 ÷ EPS. EPS 성장률이 높을수록 성장주 특성"
        ),
        "synonyms": ["주당순이익", "Earnings Per Share"],
        "parent": "valuation",
    },
    {
        "name": "dividend-yield",
        "displayName": "배당수익률",
        "description": (
            "현재 주가 대비 연간 배당금의 비율.\n"
            "- 계산식: 주당 현금배당금 ÷ 현재 주가 × 100\n"
            "- DB: company_dividend.cash_dividend_per_share ÷ stock_price_1d.close × 100\n"
            "- DB(직접): company_dividend.dividend_yield (DART 공시 기준)\n"
            "- 단위: %(퍼센트)\n"
            "- 해석: 높을수록 배당 매력도 높음. 단, 주가 하락으로 높아진 경우 구분 필요"
        ),
        "synonyms": ["시가배당률", "배당률", "dividend yield"],
        "parent": "valuation",
    },

    # ══════════════════════════════════════════════════════════════
    # 기술적 지표
    # ══════════════════════════════════════════════════════════════
    {
        "name": "moving-average",
        "displayName": "이동평균선 (MA)",
        "description": (
            "Moving Average. 일정 기간의 종가 평균을 연결한 선. 추세 파악에 사용.\n"
            "- DB: stock_indicators.ma5 / ma20 / ma60 / ma120 / ma200\n"
            "- 단기: MA5(1주), MA20(1개월)\n"
            "- 중기: MA60(3개월), MA120(6개월)\n"
            "- 장기: MA200(약 10개월)\n"
            "- 해석: 주가가 MA 위 = 해당 기간 평균 대비 강세, 아래 = 약세"
        ),
        "synonyms": ["MA", "SMA", "단순이동평균", "이평선"],
        "parent": "technical",
    },
    {
        "name": "golden-cross",
        "displayName": "골든크로스",
        "description": (
            "단기 이동평균선이 장기 이동평균선을 아래에서 위로 돌파하는 신호. 상승 추세 전환 신호.\n"
            "- DB: stock_indicators.golden_cross = TRUE\n"
            "- BIP 기준: MA5가 MA20을 상향 돌파한 당일\n"
            "- 해석: 단기 매수 신호로 해석. 거래량 동반 시 신뢰도 높음\n"
            "- 주의: 추세가 이미 많이 진행된 후 발생하면 후행 신호일 수 있음"
        ),
        "synonyms": ["골크", "golden cross"],
        "parent": "technical",
    },
    {
        "name": "death-cross",
        "displayName": "데드크로스",
        "description": (
            "단기 이동평균선이 장기 이동평균선을 위에서 아래로 돌파하는 신호. 하락 추세 전환 신호.\n"
            "- DB: stock_indicators.death_cross = TRUE\n"
            "- BIP 기준: MA5가 MA20을 하향 돌파한 당일\n"
            "- 해석: 단기 매도·경계 신호. 골든크로스의 반대 개념"
        ),
        "synonyms": ["데크", "death cross"],
        "parent": "technical",
    },
    {
        "name": "rsi",
        "displayName": "RSI (상대강도지수)",
        "description": (
            "Relative Strength Index. 일정 기간 상승/하락 강도를 0~100으로 나타냄.\n"
            "- DB: stock_indicators.rsi14 (14일 기준)\n"
            "- 범위: 0~100\n"
            "- 해석:\n"
            "  70 초과 = 과매수 구간 (단기 조정 가능성)\n"
            "  30 미만 = 과매도 구간 (단기 반등 가능성)\n"
            "  50 기준 = 추세 판단 (50 이상 상승, 이하 하락 모멘텀)"
        ),
        "synonyms": ["상대강도지수", "Relative Strength Index"],
        "parent": "technical",
    },
    {
        "name": "macd",
        "displayName": "MACD",
        "description": (
            "Moving Average Convergence Divergence. 단기·장기 지수이동평균 차이로 모멘텀 측정.\n"
            "- DB: stock_indicators.macd (EMA12 - EMA26)\n"
            "      stock_indicators.macd_signal (MACD의 9일 EMA)\n"
            "      stock_indicators.macd_hist (MACD - Signal, 히스토그램)\n"
            "- 해석:\n"
            "  MACD > Signal = 상승 모멘텀\n"
            "  MACD < Signal = 하락 모멘텀\n"
            "  히스토그램이 0선 돌파 = 추세 전환 신호"
        ),
        "synonyms": ["MACD 지표", "Moving Average Convergence Divergence"],
        "parent": "technical",
    },
    {
        "name": "bollinger-band",
        "displayName": "볼린저밴드",
        "description": (
            "이동평균선 ± 2 표준편차로 구성된 밴드. 가격 변동성과 상대적 위치 파악.\n"
            "- DB: stock_indicators.bb_upper / bb_middle / bb_lower\n"
            "      stock_indicators.bb_pctb (%B: 밴드 내 현재가 위치)\n"
            "- 해석:\n"
            "  %B > 1.0 = 상단 밴드 돌파 (과매수 가능성)\n"
            "  %B < 0.0 = 하단 밴드 이탈 (과매도 가능성)\n"
            "  밴드폭 축소 = 변동성 감소, 곧 큰 움직임 예고"
        ),
        "synonyms": ["BB", "Bollinger Bands"],
        "parent": "technical",
    },
    {
        "name": "52w-high-low",
        "displayName": "52주 신고가·신저가",
        "description": (
            "최근 52주(약 1년) 동안의 최고가·최저가.\n"
            "- DB: stock_indicators.high_52w / low_52w\n"
            "      stock_indicators.pct_from_52w_high (52주 고가 대비 현재가 등락률, %)\n"
            "      stock_indicators.pct_from_52w_low  (52주 저가 대비 현재가 등락률, %)\n"
            "- 해석:\n"
            "  pct_from_52w_high > -5% = 52주 신고가 근접 (강세 신호)\n"
            "  신저가 경신 = 하락 추세 심화 주의"
        ),
        "synonyms": ["52주 고가", "52주 저가", "연고점", "연저점"],
        "parent": "technical",
    },

    # ══════════════════════════════════════════════════════════════
    # 재무제표
    # ══════════════════════════════════════════════════════════════
    {
        "name": "revenue",
        "displayName": "매출액",
        "description": (
            "기업의 주된 영업활동에서 발생한 수익. 손익계산서 최상단 항목.\n"
            "- DB: financial_statements.revenue\n"
            "- 단위: 원(KRW)\n"
            "- 동의어: 영업수익(금융업), 매출(유통업)"
        ),
        "synonyms": ["매출", "영업수익", "revenue", "top line"],
        "parent": "financial",
    },
    {
        "name": "operating-profit",
        "displayName": "영업이익",
        "description": (
            "매출액에서 매출원가와 판매비·관리비를 차감한 이익. 본업 수익성 척도.\n"
            "- 계산식: 매출액 - 매출원가 - 판관비\n"
            "- DB: financial_statements.operating_profit\n"
            "- 단위: 원(KRW)\n"
            "- 해석: 영업이익률 = 영업이익 ÷ 매출액 × 100. 높을수록 수익성 우수."
        ),
        "synonyms": ["영업이익", "operating income", "EBIT(세전이자차감전이익과 유사)"],
        "parent": "financial",
    },
    {
        "name": "net-income",
        "displayName": "당기순이익",
        "description": (
            "영업이익에서 영업외손익·세금을 모두 반영한 최종 이익.\n"
            "- DB: financial_statements.net_income (지배주주 귀속 기준)\n"
            "- 단위: 원(KRW)\n"
            "- EPS 계산 기준. 배당 재원."
        ),
        "synonyms": ["순이익", "net profit", "bottom line", "세후이익"],
        "parent": "financial",
    },
    {
        "name": "total-assets",
        "displayName": "자산총계",
        "description": (
            "기업이 보유한 모든 자산의 합계. 재무상태표 기준.\n"
            "- DB: financial_statements.total_assets\n"
            "- 단위: 원(KRW)\n"
            "- 유동자산 + 비유동자산 = 자산총계"
        ),
        "synonyms": ["총자산", "total assets"],
        "parent": "financial",
    },
    {
        "name": "total-equity",
        "displayName": "자본총계",
        "description": (
            "자산총계에서 부채총계를 차감한 순자산. 주주 귀속 가치.\n"
            "- DB: financial_statements.total_equity\n"
            "- 단위: 원(KRW)\n"
            "- PBR 계산 분모. BPS = 자본총계 ÷ 상장주식수"
        ),
        "synonyms": ["순자산", "자기자본", "stockholders equity", "book value"],
        "parent": "financial",
    },
    {
        "name": "operating-cashflow",
        "displayName": "영업활동 현금흐름",
        "description": (
            "실제 영업에서 발생한 현금 유출입. 이익의 현금화 여부 판단.\n"
            "- DB: financial_statements.cash_from_operating\n"
            "- 단위: 원(KRW)\n"
            "- 양수 = 현금 창출, 음수 = 현금 소비\n"
            "- 순이익 > 0인데 현금흐름이 음수면 회계상 이익을 의심"
        ),
        "synonyms": ["OCF", "operating cash flow", "영업현금흐름"],
        "parent": "financial",
    },

    # ══════════════════════════════════════════════════════════════
    # 종목 분류
    # ══════════════════════════════════════════════════════════════
    {
        "name": "large-cap",
        "displayName": "대형주",
        "description": (
            "시가총액이 큰 상위 종목군.\n"
            "- BIP 기준: market_value >= 10,000 (억원) → 시총 1조원 이상\n"
            "- DB: stock_info.market_value >= 10000\n"
            "- KOSPI200 편입 종목 대부분이 해당\n"
            "- 특징: 유동성 높음, 기관·외국인 비중 높음, 변동성 상대적 낮음"
        ),
        "synonyms": ["대형 종목", "large cap", "블루칩"],
        "parent": "stock-classification",
    },
    {
        "name": "mid-cap",
        "displayName": "중형주",
        "description": (
            "대형주와 소형주의 중간 시가총액 종목군.\n"
            "- BIP 기준: 2,000 <= market_value < 10,000 (억원) → 시총 2천억~1조원\n"
            "- DB: stock_info.market_value BETWEEN 2000 AND 9999"
        ),
        "synonyms": ["중형 종목", "mid cap"],
        "parent": "stock-classification",
    },
    {
        "name": "small-cap",
        "displayName": "소형주",
        "description": (
            "시가총액이 작은 종목군. 높은 성장 가능성과 높은 변동성.\n"
            "- BIP 기준: market_value < 2,000 (억원) → 시총 2천억원 미만\n"
            "- DB: stock_info.market_value < 2000"
        ),
        "synonyms": ["소형 종목", "small cap", "스몰캡"],
        "parent": "stock-classification",
    },
    {
        "name": "value-stock",
        "displayName": "가치주",
        "description": (
            "내재가치 대비 저평가된 종목. 낮은 PER·PBR, 높은 배당수익률이 특징.\n"
            "- 일반적 기준: PER < 15 AND PBR < 1.5\n"
            "- 투자 철학: 워런 버핏 스타일. 장기 보유, 안전마진 추구."
        ),
        "synonyms": ["가치투자 종목", "value stock", "저평가주"],
        "parent": "stock-classification",
    },
    {
        "name": "growth-stock",
        "displayName": "성장주",
        "description": (
            "매출·이익이 시장 평균보다 빠르게 성장하는 종목. 높은 PER을 감수.\n"
            "- 특징: 높은 PER(미래 이익 선반영), 낮거나 없는 배당, 높은 재투자율\n"
            "- 대표: 테크·바이오·2차전지 섹터 기업들"
        ),
        "synonyms": ["성장 종목", "growth stock", "성장형 주식"],
        "parent": "stock-classification",
    },
    {
        "name": "dividend-stock",
        "displayName": "배당주",
        "description": (
            "높고 안정적인 배당을 지급하는 종목.\n"
            "- 일반적 기준: 배당수익률 3% 이상, 3년 이상 배당 지속\n"
            "- DB: company_dividend.dividend_yield >= 3.0\n"
            "- 특징: 방어적 성격, 금리 상승기에 상대적 부진"
        ),
        "synonyms": ["고배당주", "배당 종목", "dividend stock"],
        "parent": "stock-classification",
    },

    # ══════════════════════════════════════════════════════════════
    # 시장·매크로
    # ══════════════════════════════════════════════════════════════
    {
        "name": "vix",
        "displayName": "VIX (공포지수)",
        "description": (
            "CBOE Volatility Index. S&P500 옵션 가격에서 산출한 향후 30일 변동성 예상치.\n"
            "- DB: macro_indicators WHERE indicator_type='vix' AND region='North America'\n"
            "- 단위: 포인트\n"
            "- 해석:\n"
            "  20 미만 = 안정적 시장\n"
            "  20~30 = 불안 고조\n"
            "  30 초과 = 공포 국면 (역발상 매수 기회로 보는 시각도 있음)\n"
            "  80 이상 = 극단적 공포 (2008, 2020 사례)"
        ),
        "synonyms": ["변동성지수", "공포지수", "CBOE VIX"],
        "parent": "market",
    },
    {
        "name": "fear-greed-index",
        "displayName": "공포탐욕지수",
        "description": (
            "CNN Fear & Greed Index. 시장 투자심리를 0~100으로 나타냄.\n"
            "- DB: macro_indicators WHERE indicator_type='fear_greed_index'\n"
            "- 범위: 0(극도 공포) ~ 100(극도 탐욕)\n"
            "- 해석: 25 이하 = 공포(저가 매수 고려), 75 이상 = 탐욕(고평가 주의)"
        ),
        "synonyms": ["CNN 공포탐욕지수", "Fear and Greed Index"],
        "parent": "market",
    },
    {
        "name": "exchange-rate",
        "displayName": "환율",
        "description": (
            "자국 통화 대비 달러(USD) 환율.\n"
            "- DB: macro_indicators WHERE indicator_type='exchange_rate'\n"
            "      region으로 통화 구분: South Korea(KRW/USD), Japan(JPY/USD), China(CNY/USD) 등\n"
            "- 단위: 원/달러, 엔/달러 등\n"
            "- 투자 영향: 원화 강세(환율 하락) = 수입주 유리, 수출주 불리"
        ),
        "synonyms": ["FX", "외환", "환율"],
        "parent": "market",
    },
    {
        "name": "geopolitical-risk",
        "displayName": "지정학적 리스크",
        "description": (
            "전쟁·분쟁·제재 등 지정학적 사건이 시장에 미치는 위험.\n"
            "- DB: macro_indicators WHERE indicator_type LIKE 'risk_score_%'\n"
            "      국가별: risk_score_us, risk_score_kr, risk_score_cn, risk_score_ru 등\n"
            "- 범위: 0(안전) ~ 100(고위험)\n"
            "- 관련 헤드라인: risk_headlines 테이블"
        ),
        "synonyms": ["지정학 리스크", "geopolitical risk", "지정학적 위험"],
        "parent": "market",
    },

    # ══════════════════════════════════════════════════════════════
    # 컨센서스
    # ══════════════════════════════════════════════════════════════
    {
        "name": "analyst-rating",
        "displayName": "투자의견",
        "description": (
            "증권사 애널리스트의 종목 투자 추천 등급.\n"
            "- DB: consensus_estimates.rating\n"
            "- 범위: 1.0(Sell) ~ 5.0(Strong Buy)\n"
            "- ⚠️ 높을수록 긍정적. 1이 좋은 게 아님.\n"
            "- 기준:\n"
            "  5.0 = Strong Buy (적극 매수)\n"
            "  4.0 = Buy (매수)\n"
            "  3.0 = Hold (중립·보유)\n"
            "  2.0 = Underperform (비중 축소)\n"
            "  1.0 = Sell (매도)\n"
            "- '컨센서스 매수' 기준: rating >= 4.0"
        ),
        "synonyms": ["투자의견", "analyst rating", "추천등급", "투자등급"],
        "parent": "consensus",
    },
    {
        "name": "target-price",
        "displayName": "목표주가",
        "description": (
            "애널리스트가 향후 12개월 내 도달할 것으로 예상하는 주가.\n"
            "- DB: consensus_estimates.target_price\n"
            "- 단위: 원(KRW)\n"
            "- 업사이드 = (목표주가 - 현재가) ÷ 현재가 × 100"
        ),
        "synonyms": ["TP", "target price", "적정주가"],
        "parent": "consensus",
    },

    # ══════════════════════════════════════════════════════════════
    # 기술적 지표 추가 (EMA, ATR, Stochastic, MACD 파생)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "ema",
        "displayName": "EMA (지수이동평균)",
        "description": (
            "Exponential Moving Average. 최근 데이터에 더 높은 가중치를 부여하는 이동평균.\n"
            "- DB: stock_indicators.ema12 (12일), stock_indicators.ema26 (26일)\n"
            "- MACD 계산의 기초: MACD = EMA12 - EMA26\n"
            "- 단순이동평균(SMA)보다 최근 추세에 민감하게 반응"
        ),
        "synonyms": ["지수이동평균", "Exponential Moving Average"],
        "parent": "technical",
    },
    {
        "name": "stochastic",
        "displayName": "스토캐스틱 오실레이터",
        "description": (
            "현재 종가가 일정 기간 가격 범위 내 어느 위치인지 나타내는 모멘텀 지표.\n"
            "- DB: stock_indicators.stoch_k (%K선), stock_indicators.stoch_d (%D선, %K의 이동평균)\n"
            "- 범위: 0 ~ 100\n"
            "- 해석: 80 이상 = 과매수, 20 이하 = 과매도\n"
            "- %K가 %D를 상향 돌파하면 매수 신호"
        ),
        "synonyms": ["스토캐스틱", "Stochastic", "%K", "%D"],
        "parent": "technical",
    },
    {
        "name": "atr",
        "displayName": "ATR (평균진폭)",
        "description": (
            "Average True Range. 일정 기간 동안의 평균 가격 변동 범위. 변동성 측정 지표.\n"
            "- DB: stock_indicators.atr14 (14일 ATR), market_daily_summary.avg_atr_pct\n"
            "- 단위: 원(절대값) 또는 % (비율)\n"
            "- ATR이 클수록 변동성 높음. 손절·목표가 설정에 활용"
        ),
        "synonyms": ["Average True Range", "평균실제범위", "변동성지표"],
        "parent": "technical",
    },
    {
        "name": "bb-indicators",
        "displayName": "볼린저밴드 파생 지표",
        "description": (
            "볼린저밴드에서 파생된 세부 지표들.\n"
            "- DB: stock_indicators.bb_pctb (%B: 현재가의 밴드 내 상대 위치, 0=하단 1=상단)\n"
            "- DB: stock_indicators.bb_width (Bandwidth: 밴드 폭 = (상단-하단)/중간선, 변동성 확장 측정)\n"
            "- %B > 1: 상단밴드 돌파(과열), %B < 0: 하단밴드 이탈(침체)\n"
            "- Bandwidth 급등 = 변동성 확장 구간 진입"
        ),
        "synonyms": ["%B", "bb_pctb", "bb_width", "Bandwidth"],
        "parent": "technical",
    },
    {
        "name": "macd-components",
        "displayName": "MACD 구성 요소",
        "description": (
            "MACD 지표의 세부 구성 요소.\n"
            "- DB: stock_indicators.macd (MACD선 = EMA12 - EMA26)\n"
            "- DB: stock_indicators.macd_signal (Signal선 = MACD의 9일 EMA)\n"
            "- DB: stock_indicators.macd_hist (히스토그램 = MACD - Signal, 막대 차트)\n"
            "- 매수 신호: MACD가 Signal선 상향 돌파 (히스토그램 양전환)"
        ),
        "synonyms": ["MACD Signal", "MACD Histogram", "macd_signal", "macd_hist"],
        "parent": "technical",
    },

    # ══════════════════════════════════════════════════════════════
    # 밸류에이션 추가 (미국주식 지표)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "ebitda",
        "displayName": "EBITDA",
        "description": (
            "Earnings Before Interest, Taxes, Depreciation and Amortization.\n"
            "이자·세금·감가상각 전 영업이익. 기업의 실질 현금창출 능력 지표.\n"
            "- DB: us_financial_statements.ebitda\n"
            "- 단위: 달러(USD)\n"
            "- 글로벌 기업 비교 시 회계 기준 차이를 줄여주는 장점"
        ),
        "synonyms": ["에비타", "상각전영업이익"],
        "parent": "financial",
    },
    {
        "name": "fcf",
        "displayName": "FCF (잉여현금흐름)",
        "description": (
            "Free Cash Flow. 영업활동 현금흐름에서 자본적 지출(CAPEX)을 뺀 값.\n"
            "기업이 실제로 자유롭게 사용 가능한 현금.\n"
            "- DB: us_financial_statements.free_cashflow\n"
            "- 계산: 영업현금흐름 - 설비투자(CAPEX)\n"
            "- FCF가 지속적으로 양수인 기업 = 재무 건전성 우수"
        ),
        "synonyms": ["잉여현금흐름", "Free Cash Flow", "자유현금흐름"],
        "parent": "financial",
    },
    {
        "name": "ev-ebitda",
        "displayName": "EV/EBITDA",
        "description": (
            "Enterprise Value to EBITDA. 기업가치(EV)를 EBITDA로 나눈 밸류에이션 배수.\n"
            "- DB: us_fundamentals.ev_to_ebitda\n"
            "- EV = 시가총액 + 순부채\n"
            "- 낮을수록 저평가. 국제 비교에 많이 사용\n"
            "- 업종별 기준이 다름 (제조 5~10배, 기술 15~25배)"
        ),
        "synonyms": ["EV/EBITDA", "기업가치배수"],
        "parent": "valuation",
    },
    {
        "name": "peg-ratio",
        "displayName": "PEG Ratio",
        "description": (
            "Price/Earnings to Growth Ratio. PER을 이익성장률로 나눈 지표.\n"
            "- DB: us_fundamentals.peg_ratio\n"
            "- 계산: PER ÷ 연간 EPS 성장률(%)\n"
            "- 1.0 이하 = 성장 대비 저평가, 1.0 초과 = 고평가\n"
            "- 고성장주 평가에 PER보다 적합"
        ),
        "synonyms": ["PEG", "주가이익성장비율"],
        "parent": "valuation",
    },
    {
        "name": "beta",
        "displayName": "베타 (Beta)",
        "description": (
            "시장 전체 움직임에 대한 개별 주식의 민감도(변동성).\n"
            "- DB: us_fundamentals.beta\n"
            "- Beta = 1.0: 시장과 동일하게 움직임\n"
            "- Beta > 1.0: 시장보다 더 크게 움직임 (고위험·고수익)\n"
            "- Beta < 1.0: 시장보다 덜 움직임 (방어주)\n"
            "- Beta < 0: 시장과 반대로 움직임 (금, 일부 채권)"
        ),
        "synonyms": ["베타계수", "시장민감도", "체계적위험"],
        "parent": "valuation",
    },
    {
        "name": "trailing-forward-pe",
        "displayName": "후행/선행 PER",
        "description": (
            "Trailing PE: 과거 12개월 실적 기반 PER (확정치).\n"
            "Forward PE: 향후 12개월 예상 실적 기반 PER (추정치).\n"
            "- DB: us_fundamentals.trailing_pe, us_fundamentals.forward_pe\n"
            "- Trailing PE > Forward PE: 이익 성장 기대\n"
            "- Trailing PE < Forward PE: 이익 감소 우려\n"
            "- ⚠️ 한국 stock_info.per은 Trailing PE에 해당"
        ),
        "synonyms": ["Trailing PE", "Forward PE", "선행PER", "후행PER"],
        "parent": "valuation",
    },

    # ══════════════════════════════════════════════════════════════
    # 포트폴리오 / 공통 약어
    # ══════════════════════════════════════════════════════════════
    {
        "name": "pnl",
        "displayName": "P&L (손익)",
        "description": (
            "Profit and Loss. 보유 종목의 평가손익.\n"
            "- DB: holding.pnl_amount (손익 금액), holding.pnl_percent (손익률 %)\n"
            "- DB: portfolio_snapshot.daily_pnl (일간 손익), portfolio_snapshot.total_pnl (누적 손익)\n"
            "- 계산: (현재가 - 평균매수가) × 보유수량\n"
            "- 양수 = 수익(이익), 음수 = 손실"
        ),
        "synonyms": ["손익", "평가손익", "Profit and Loss", "수익률"],
        "parent": "price",
    },
    {
        "name": "ohlcv",
        "displayName": "OHLCV (주가 기본 데이터)",
        "description": (
            "Open·High·Low·Close·Volume. 주가 캔들 차트의 기본 5개 데이터.\n"
            "- DB: stock_price_1d, stock_price_1m의 open/high/low/close/volume 컬럼\n"
            "- DB: stock_indicators.open/high/low/close/volume\n"
            "- Open: 시가, High: 고가, Low: 저가, Close: 종가, Volume: 거래량\n"
            "- 모든 기술적 지표의 원천 데이터"
        ),
        "synonyms": ["시고저종거래량", "캔들 데이터", "OHLC"],
        "parent": "price",
    },
    {
        "name": "gics",
        "displayName": "GICS (글로벌산업분류기준)",
        "description": (
            "Global Industry Classification Standard. S&P와 MSCI가 공동 개발한 표준 산업 분류 체계.\n"
            "- 11개 섹터: Energy, Materials, Industrials, Consumer Discretionary, Consumer Staples,\n"
            "  Health Care, Financials, Information Technology, Communication Services, Utilities, Real Estate\n"
            "- ⚠️ 한국주식은 GICS 대신 KRX 업종 분류 사용 (stock_info.sector, industry_name)"
        ),
        "synonyms": ["글로벌산업분류", "섹터분류", "GICS Sector"],
        "parent": "stock-classification",
    },
    {
        "name": "advance-decline",
        "displayName": "등락비율 (ADR)",
        "description": (
            "Advance/Decline Ratio. 상승 종목 수 대비 하락 종목 수의 비율. 시장 전반의 건강도 지표.\n"
            "- DB: market_daily_summary.advancing (상승 종목 수), market_daily_summary.declining (하락 종목 수)\n"
            "- DB: market_daily_summary.advance_decline_ratio\n"
            "- 1.0 초과: 상승 종목이 더 많음 (강세)\n"
            "- 1.0 미만: 하락 종목이 더 많음 (약세)"
        ),
        "synonyms": ["ADR", "Advance Decline Ratio", "등락비율"],
        "parent": "market",
    },

    # ══════════════════════════════════════════════════════════════
    # 추가: 잘못된 태그 수정용 신규 용어
    # ══════════════════════════════════════════════════════════════
    {
        "name": "foreign-ownership",
        "displayName": "외국인보유비중",
        "description": (
            "외국인 투자자가 보유한 주식 수 ÷ 상장주식수 × 100. 단위: %.\n"
            "- DB: stock_info.foreign_ownership_pct (최근 기준)\n"
            "- DB: stock_price_1d.foreign_ownership_pct (일별 변화 추적)\n"
            "- 외국인 보유비중이 높을수록 글로벌 기관의 관심도가 높음\n"
            "- 외국인 한도 소진율과 다름 (한도는 별도 규정 존재)"
        ),
        "synonyms": ["외국인비중", "외국인보유율", "foreign ownership ratio"],
        "parent": "price",
    },
    {
        "name": "dps",
        "displayName": "DPS (주당배당금)",
        "description": (
            "Dividend Per Share. 1주당 지급되는 현금 배당금.\n"
            "- DB: company_dividend.cash_dividend_per_share\n"
            "- 단위: 원(KRW)\n"
            "- 배당수익률 = DPS ÷ 현재주가 × 100\n"
            "- EPS와 다름: EPS는 이익 기준, DPS는 실제 지급액 기준"
        ),
        "synonyms": ["주당배당금", "Dividend Per Share", "배당금"],
        "parent": "valuation",
    },
    {
        "name": "investor-trend",
        "displayName": "투자자별 매매동향",
        "description": (
            "외국인·기관·개인 투자자별 순매수 수량. 시장 수급 분석의 핵심 지표.\n"
            "- DB: stock_price_1d.foreign_buy_volume (외국인 순매수량)\n"
            "- DB: stock_price_1d.institution_buy_volume (기관 순매수량)\n"
            "- DB: stock_price_1d.individual_buy_volume (개인 순매수량)\n"
            "- 양수 = 순매수(매수 > 매도), 음수 = 순매도(매도 > 매수)\n"
            "- 외국인·기관 동시 순매수 = 강세 신호"
        ),
        "synonyms": ["수급", "투자자수급", "매매동향"],
        "parent": "price",
    },

    # ══════════════════════════════════════════════════════════════
    # 재무제표 보완 (손익계산서 세부 / 부채 / 현금흐름)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "gross-profit",
        "displayName": "매출총이익",
        "description": (
            "매출액에서 매출원가를 뺀 이익. 제품·서비스의 직접 수익성을 나타냄.\n"
            "- DB: financial_statements.gross_profit, us_financial_statements.gross_profit\n"
            "- 계산: 매출액(revenue) - 매출원가(cost_of_sales)\n"
            "- 단위: 원(KRW) 또는 달러(USD)\n"
            "- 매출총이익률 = gross_profit ÷ revenue × 100"
        ),
        "synonyms": ["Gross Profit", "매출총이익", "gross margin amount"],
        "parent": "financial",
    },
    {
        "name": "cost-of-sales",
        "displayName": "매출원가 (COGS)",
        "description": (
            "제품·서비스 생산에 직접 투입된 비용. 판관비는 제외.\n"
            "- DB: financial_statements.cost_of_sales\n"
            "- 단위: 원(KRW)\n"
            "- COGS = Cost of Goods Sold\n"
            "- 제조업·유통업에서 높고, 소프트웨어·플랫폼 업체에서 낮은 경향"
        ),
        "synonyms": ["COGS", "Cost of Goods Sold", "매출원가"],
        "parent": "financial",
    },
    {
        "name": "total-liabilities",
        "displayName": "부채총계",
        "description": (
            "기업이 상환해야 할 모든 부채의 합계. 유동부채 + 비유동부채.\n"
            "- DB: financial_statements.total_liabilities, us_financial_statements.total_liabilities\n"
            "- 단위: 원(KRW) 또는 달러(USD)\n"
            "- 부채비율 = total_liabilities ÷ total_equity × 100\n"
            "- 자산총계 = 부채총계 + 자본총계 (회계 항등식)"
        ),
        "synonyms": ["부채총계", "Total Liabilities", "총부채"],
        "parent": "financial",
    },
    {
        "name": "total-debt",
        "displayName": "총차입금",
        "description": (
            "단기차입금 + 장기차입금 + 사채. 실질적인 금융 부채.\n"
            "- DB: us_financial_statements.total_debt, us_fundamentals.total_debt\n"
            "- 단위: 달러(USD)\n"
            "- 순차입금(Net Debt) = total_debt - total_cash\n"
            "- ⚠️ total_liabilities(부채총계)와 다름 — 영업부채(매입채무 등) 제외"
        ),
        "synonyms": ["총차입금", "Total Debt", "금융부채"],
        "parent": "financial",
    },
    {
        "name": "total-cash",
        "displayName": "현금및현금성자산",
        "description": (
            "즉시 사용 가능한 현금 + 단기금융상품.\n"
            "- DB: us_financial_statements.total_cash, us_fundamentals.total_cash\n"
            "- 단위: 달러(USD)\n"
            "- 순차입금 = total_debt - total_cash (음수면 순현금 보유)"
        ),
        "synonyms": ["현금성자산", "Cash and Equivalents", "Cash"],
        "parent": "financial",
    },
    {
        "name": "investing-cashflow",
        "displayName": "투자활동 현금흐름",
        "description": (
            "설비투자(CAPEX), 인수합병, 금융자산 매매 등 투자 활동의 현금 변동.\n"
            "- DB: financial_statements.cash_from_investing\n"
            "- 단위: 원(KRW)\n"
            "- 일반적으로 음수(투자 지출) — 성장 기업일수록 음수 폭 큼\n"
            "- FCF = 영업활동현금흐름 + 투자활동현금흐름(CAPEX 부분)"
        ),
        "synonyms": ["투자활동현금흐름", "Cash from Investing", "CFI"],
        "parent": "financial",
    },
    {
        "name": "financing-cashflow",
        "displayName": "재무활동 현금흐름",
        "description": (
            "차입금 조달·상환, 주식 발행·자사주 매입, 배당금 지급 등 재무 활동의 현금 변동.\n"
            "- DB: financial_statements.cash_from_financing\n"
            "- 단위: 원(KRW)\n"
            "- 음수 = 부채 상환 또는 배당·자사주 매입 (주주 환원)\n"
            "- 양수 = 신규 차입 또는 유상증자"
        ),
        "synonyms": ["재무활동현금흐름", "Cash from Financing", "CFF"],
        "parent": "financial",
    },
    {
        "name": "shares-outstanding",
        "displayName": "발행주식수 (주식수)",
        "description": (
            "현재 시장에서 유통 중인 총 주식 수. EPS·시가총액 계산의 분모.\n"
            "- DB: financial_statements.shares_outstanding (DART 공시 기준)\n"
            "- DB: stock_info.total_shares (현재 상장주식수)\n"
            "- 단위: 주(株)\n"
            "- EPS = 당기순이익 ÷ shares_outstanding\n"
            "- 시가총액 = 현재주가 × shares_outstanding\n"
            "- ⚠️ 자기주식(Treasury Stock) 제외 여부 확인 필요"
        ),
        "synonyms": ["발행주식수", "상장주식수", "Shares Outstanding", "주식수"],
        "parent": "financial",
    },
    {
        "name": "payout-ratio",
        "displayName": "배당성향",
        "description": (
            "당기순이익 중 배당금으로 지급한 비율.\n"
            "- DB: company_dividend.payout_ratio\n"
            "- 계산: 총배당금 ÷ 당기순이익 × 100. 단위: %(퍼센트)\n"
            "- 50% 이하: 배당 여력 충분, 재투자 중심\n"
            "- 100% 초과: 이익보다 많은 배당 — 지속 가능성 검토 필요\n"
            "- 배당주 투자 시 배당수익률과 함께 확인"
        ),
        "synonyms": ["배당성향", "Payout Ratio", "배당지급률"],
        "parent": "financial",
    },

    # ══════════════════════════════════════════════════════════════
    # 수익성·성장성 지표
    # ══════════════════════════════════════════════════════════════
    {
        "name": "roa",
        "displayName": "ROA (총자산이익률)",
        "description": (
            "Return on Assets. 총자산 대비 당기순이익 비율. 자산 활용 효율성 지표.\n"
            "- DB: us_fundamentals.return_on_assets\n"
            "- 계산: 당기순이익 ÷ 자산총계 × 100. 단위: %(퍼센트)\n"
            "- ROE(자기자본이익률)보다 레버리지 영향 덜 받음\n"
            "- 업종별 기준이 다름 (금융주는 낮고, 경자산 IT는 높은 경향)\n"
            "- ⚠️ ROE가 높아도 ROA가 낮으면 과도한 레버리지 의심"
        ),
        "synonyms": ["총자산이익률", "Return on Assets", "자산수익률"],
        "parent": "valuation",
    },
    {
        "name": "operating-margin",
        "displayName": "영업이익률",
        "description": (
            "매출액 대비 영업이익 비율. 본업의 수익성을 나타내는 핵심 지표.\n"
            "- DB: us_fundamentals.operating_margin\n"
            "- 계산: 영업이익 ÷ 매출액 × 100. 단위: %(퍼센트)\n"
            "- 한국 기업은 financial_statements에서 직접 계산: operating_profit ÷ revenue × 100\n"
            "- 영업이익률 10% 이상 = 우수, 업종 평균 대비 비교 필수"
        ),
        "synonyms": ["영업이익률", "Operating Margin", "OPM"],
        "parent": "valuation",
    },
    {
        "name": "profit-margin",
        "displayName": "순이익률 (Net Margin)",
        "description": (
            "매출액 대비 당기순이익 비율. 영업외손익·세금 포함한 최종 수익성.\n"
            "- DB: us_fundamentals.profit_margin\n"
            "- 계산: 당기순이익 ÷ 매출액 × 100. 단위: %(퍼센트)\n"
            "- 영업이익률보다 낮으면 금융비용·세금 부담이 큰 것\n"
            "- ⚠️ 일회성 손익으로 왜곡될 수 있어 영업이익률과 함께 확인"
        ),
        "synonyms": ["순이익률", "Net Margin", "Net Profit Margin"],
        "parent": "valuation",
    },
    {
        "name": "revenue-growth",
        "displayName": "매출성장률",
        "description": (
            "전년 동기 대비 매출액 증가율.\n"
            "- DB: us_fundamentals.revenue_growth\n"
            "- 단위: %(퍼센트, 소수 형태로 저장 — 0.15 = 15% 성장)\n"
            "- 성장주 선별의 핵심 지표\n"
            "- ⚠️ 단기 급성장보다 3~5년 연속 성장이 더 중요"
        ),
        "synonyms": ["매출성장률", "Revenue Growth", "매출증가율"],
        "parent": "valuation",
    },
    {
        "name": "earnings-growth",
        "displayName": "이익성장률",
        "description": (
            "전년 동기 대비 당기순이익(EPS) 증가율.\n"
            "- DB: us_fundamentals.earnings_growth\n"
            "- 단위: %(퍼센트, 소수 형태)\n"
            "- PEG Ratio의 분모: PEG = PER ÷ earnings_growth(%)\n"
            "- 이익성장률 > 매출성장률: 비용 효율화 진행 중"
        ),
        "synonyms": ["이익성장률", "Earnings Growth", "EPS Growth"],
        "parent": "valuation",
    },

    # ══════════════════════════════════════════════════════════════
    # 기술적 지표 보완 (거래량 파생)
    # ══════════════════════════════════════════════════════════════
    {
        "name": "volume-ratio",
        "displayName": "거래량비율 (VR)",
        "description": (
            "당일 거래량 ÷ 20일 평균거래량. 평소 대비 거래 활성화 정도.\n"
            "- DB: stock_indicators.volume_ratio\n"
            "- DB: market_daily_summary.avg_volume_ratio (시장 전체 평균)\n"
            "- 1.0 = 평균 수준, 2.0 이상 = 급등 신호(거래량 폭발)\n"
            "- 주가 급등 + 거래량비율 급증 = 추세 전환 확인 신호"
        ),
        "synonyms": ["거래량비율", "Volume Ratio", "거래량배수"],
        "parent": "technical",
    },

    # ══════════════════════════════════════════════════════════════
    # 주가 / 시간외 거래
    # ══════════════════════════════════════════════════════════════
    {
        "name": "after-hours",
        "displayName": "시간외 거래",
        "description": (
            "미국 주식 정규장(09:30~16:00 ET) 마감 이후 또는 개장 전 거래.\n"
            "- DB: stock_price_1d.after_hours_close (시간외 종가)\n"
            "- DB: stock_price_1d.after_hours_change_pct (시간외 등락률 = (시간외종가 - 종가) ÷ 종가 × 100)\n"
            "- 프리마켓(Pre-market): 04:00~09:30 ET\n"
            "- 애프터마켓(After-market): 16:00~20:00 ET\n"
            "- ⚠️ 한국 주식(KRX)에는 해당 없음. 미국 주식(NASDAQ·NYSE) 전용"
        ),
        "synonyms": ["시간외거래", "After-Hours Trading", "Pre-market", "애프터마켓"],
        "parent": "price",
    },
    {
        "name": "par-value",
        "displayName": "액면가",
        "description": (
            "주식에 표시된 법적 가액. 주식 발행 시의 기준 금액.\n"
            "- DB: stock_info.par_value\n"
            "- 단위: 원(KRW). 한국 상장사 대부분 100원 또는 500원\n"
            "- 현재 주가와 무관 (삼성전자 주가 7만원, 액면가 100원)\n"
            "- 액면분할 시 par_value가 낮아지고 total_shares가 늘어남"
        ),
        "synonyms": ["액면가", "Par Value", "Face Value", "액면금액"],
        "parent": "price",
    },

    # ══════════════════════════════════════════════════════════════
    # 시장 지표 보완
    # ══════════════════════════════════════════════════════════════
    {
        "name": "pct-above-ma",
        "displayName": "MA 상단 종목 비중",
        "description": (
            "전체 종목 중 특정 이동평균선 위에 있는 종목의 비율(%).\n"
            "- DB: market_daily_summary.pct_above_ma20 (MA20 상단 비중)\n"
            "- DB: market_daily_summary.pct_above_ma200 (MA200 상단 비중)\n"
            "- 시장 전반의 기술적 건강도 지표\n"
            "- pct_above_ma200 > 70%: 강세장, < 30%: 약세장 경계"
        ),
        "synonyms": ["MA 상단 비중", "Percent Above MA", "이동평균 상단 비율"],
        "parent": "market",
    },
    {
        "name": "recommendation-mean",
        "displayName": "애널리스트 평균 추천",
        "description": (
            "미국 주식 애널리스트 투자의견의 평균 점수.\n"
            "- DB: us_fundamentals.recommendation_mean\n"
            "- 범위: 1.0(Strong Buy) ~ 5.0(Sell) — ⚠️ 한국 consensus.rating과 방향 반대!\n"
            "- 1.0~1.5: 강력 매수, 2.0~2.5: 매수, 3.0: 중립, 4.0~5.0: 매도\n"
            "- 출처: Yahoo Finance (IBES 집계)"
        ),
        "synonyms": ["애널리스트 추천", "Recommendation Mean", "Analyst Consensus"],
        "parent": "consensus",
    },
]


# ─── API 유틸리티 ─────────────────────────────────────────────────────────────

def get_headers():
    if not OM_BOT_TOKEN:
        print("❌ OM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {OM_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


def get_or_create_glossary(headers: dict, dry_run: bool) -> str | None:
    """Glossary ID를 반환. 없으면 생성."""
    resp = requests.get(
        f"{OM_HOST}/api/v1/glossaries/name/{GLOSSARY_NAME}",
        headers=headers, timeout=10
    )
    if resp.status_code == 200:
        gid = resp.json()["id"]
        print(f"  기존 Glossary 사용: {GLOSSARY_NAME} (id: {gid})")
        return gid

    if dry_run:
        print(f"  [dry-run] Glossary 생성 예정: {GLOSSARY_NAME}")
        return "dry-run-id"

    resp = requests.post(
        f"{OM_HOST}/api/v1/glossaries",
        headers=headers,
        json={
            "name": GLOSSARY_NAME,
            "displayName": GLOSSARY_DISPLAY,
            "description": "BIP-Pipeline 주식 투자 분석에 사용되는 비즈니스 용어 정의. NL2SQL 시맨틱 레이어의 기초.",
        },
        timeout=10
    )
    if resp.status_code in (200, 201):
        gid = resp.json()["id"]
        print(f"  ✅ Glossary 생성: {GLOSSARY_NAME} (id: {gid})")
        return gid
    print(f"  ❌ Glossary 생성 실패: {resp.status_code} {resp.text[:200]}")
    return None


def get_term_id(name: str, headers: dict) -> str | None:
    """용어 FQN으로 ID 조회."""
    fqn = f"{GLOSSARY_NAME}.{name}"
    resp = requests.get(
        f"{OM_HOST}/api/v1/glossaryTerms/name/{fqn}",
        headers=headers, timeout=10
    )
    if resp.status_code == 200:
        return resp.json()["id"]
    return None


def create_or_update_term(term: dict, glossary_id: str, term_id_cache: dict, headers: dict, dry_run: bool) -> bool:
    """용어 생성 또는 업데이트."""
    name = term["name"]
    parent_name = term.get("parent")

    if dry_run:
        parent_str = f" (상위: {parent_name})" if parent_name else " (루트)"
        print(f"    {term['displayName']} [{name}]{parent_str}")
        return True

    payload = {
        "glossary": GLOSSARY_NAME,
        "name": name,
        "displayName": term["displayName"],
        "description": term["description"],
        "synonyms": term.get("synonyms", []),
    }

    if parent_name:
        payload["parent"] = f"{GLOSSARY_NAME}.{parent_name}"

    # 기존 용어 확인
    existing_id = get_term_id(name, headers)

    if existing_id:
        # 업데이트 (PATCH)
        patch_headers = {**headers, "Content-Type": "application/json-patch+json"}
        ops = [
            {"op": "add", "path": "/description", "value": term["description"]},
            {"op": "add", "path": "/synonyms", "value": term.get("synonyms", [])},
        ]
        resp = requests.patch(
            f"{OM_HOST}/api/v1/glossaryTerms/{existing_id}",
            headers=patch_headers,
            data=json.dumps(ops),
            timeout=10
        )
        if resp.status_code in (200, 201):
            term_id_cache[name] = existing_id
            return True
    else:
        # 신규 생성
        resp = requests.post(
            f"{OM_HOST}/api/v1/glossaryTerms",
            headers=headers,
            json=payload,
            timeout=10
        )
        if resp.status_code in (200, 201):
            term_id_cache[name] = resp.json()["id"]
            return True

    print(f"      ❌ 실패: {resp.status_code} {resp.text[:150]}")
    return False


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OM 투자 용어집 구축")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true", help="기존 Glossary 삭제 후 재생성")
    args = parser.parse_args()

    headers = get_headers()
    mode = "DRY-RUN" if args.dry_run else "LIVE"

    print(f"\n{'='*60}")
    print(f"투자 비즈니스 용어집 구축 ({mode})")
    print(f"등록 용어 수: {len(GLOSSARY_TERMS)}개")
    print(f"{'='*60}\n")

    # Glossary 준비
    print("▶ Glossary 준비")
    glossary_id = get_or_create_glossary(headers, args.dry_run)
    if not glossary_id:
        sys.exit(1)

    # 용어 등록 (루트 → 하위 순서로)
    term_id_cache = {}  # name → id 캐시 (parent 참조용)
    success, fail = 0, 0

    # 루트 노드 먼저
    roots = [t for t in GLOSSARY_TERMS if t.get("parent") is None]
    children = [t for t in GLOSSARY_TERMS if t.get("parent") is not None]

    print(f"\n▶ 카테고리 루트 ({len(roots)}개)")
    for term in roots:
        ok = create_or_update_term(term, glossary_id, term_id_cache, headers, args.dry_run)
        if ok:
            success += 1
            if not args.dry_run:
                print(f"  ✅ {term['displayName']}")
        else:
            fail += 1
        if not args.dry_run:
            time.sleep(0.2)

    print(f"\n▶ 하위 용어 ({len(children)}개)")
    # 카테고리별 그룹화 출력
    current_parent = None
    for term in children:
        if term.get("parent") != current_parent:
            current_parent = term.get("parent")
            if not args.dry_run:
                print(f"\n  [{current_parent}]")

        ok = create_or_update_term(term, glossary_id, term_id_cache, headers, args.dry_run)
        if ok:
            success += 1
            if not args.dry_run:
                print(f"    ✅ {term['displayName']}")
        else:
            fail += 1
        if not args.dry_run:
            time.sleep(0.2)

    print(f"\n{'='*60}")
    print(f"완료: {success}개 성공 / {fail}개 실패")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
