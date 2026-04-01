"""
OpenMetadata 테이블/컬럼 설명 일괄 등록 스크립트

사용법:
    python scripts/om_enrich_metadata.py [--dry-run] [--table TABLE_NAME]

옵션:
    --dry-run       실제 API 호출 없이 업데이트할 내용만 출력
    --table NAME    특정 테이블만 처리 (예: --table stock_info)

환경변수:
    OM_HOST         OpenMetadata 서버 주소 (기본값: http://localhost:8585)
    OM_BOT_TOKEN    ingestion-bot JWT 토큰
    OM_SERVICE_DB   DB 서비스명 (기본값: bip-postgres)
    OM_DB_NAME      DB 이름 (기본값: stockdb)
    OM_DB_SCHEMA    스키마 이름 (기본값: public)
"""

import argparse
import json
import os
import sys

import requests

# ─── 환경변수 ──────────────────────────────────────────────────────────────────

OM_HOST = os.getenv("OM_HOST", "http://localhost:8585")
OM_BOT_TOKEN = os.getenv("OM_BOT_TOKEN", "")
OM_SERVICE_DB = os.getenv("OM_SERVICE_DB", "bip-postgres")
OM_DB_NAME = os.getenv("OM_DB_NAME", "stockdb")
OM_DB_SCHEMA = os.getenv("OM_DB_SCHEMA", "public")

# ─── 메타데이터 정의 ────────────────────────────────────────────────────────────
#
# 구조:
#   TABLE_METADATA = {
#       "table_name": {
#           "description": "테이블 설명",
#           "columns": {
#               "column_name": "컬럼 설명",
#               ...
#           }
#       }
#   }
#
TABLE_METADATA = {

    # ──────────────────────────────────────────────────────────
    # 종목 마스터
    # ──────────────────────────────────────────────────────────
    "stock_info": {
        "description": (
            "종목 마스터 테이블. KOSPI·KOSDAQ·미국(NASDAQ·NYSE) 전 종목의 기본 정보를 관리합니다. "
            "모든 시세·지표·재무 테이블의 기준 테이블이며 ticker를 공통 키로 사용합니다. "
            "수집 출처: Naver Mobile API(한국), Naver Securities API(미국)."
        ),
        "columns": {
            "ticker":                "종목코드. Yahoo Finance 형식 통일 — 한국: '005930.KS'(KOSPI), '035720.KQ'(KOSDAQ), 미국: 'NVDA'. UNIQUE 제약.",
            "stock_name":            "한글 종목명 (예: 삼성전자, SK하이닉스)",
            "stock_name_eng":        "영문 종목명 (예: Samsung Electronics Co Ltd)",
            "market_type":           "시장 구분. 값: KOSPI, KOSDAQ, NASDAQ, NYSE",
            "exchange_code":         "거래소 코드. 값: KS(KOSPI), KQ(KOSDAQ), NSQ(NASDAQ), NYS(NYSE)",
            "currency_code":         "거래 통화. 값: KRW(한국), USD(미국)",
            "listing_date":          "상장일",
            "par_value":             "액면가. 단위: 원(KRW)",
            "total_shares":          "상장 주식수. 단위: 주(株)",
            "market_value":          "시가총액. ⚠️ 단위: 억원(×1억 = 원). PER·PBR 계산 시 ×100,000,000 변환 필요.",
            "data_source":           "데이터 출처. 값: naver, krx, yfinance",
            "active":                "현재 활성 종목 여부. 상장 폐지·거래 정지 종목은 FALSE.",
            "created_at":            "레코드 최초 생성 시각",
            "updated_at":            "최근 정보 갱신 시각",
            "industry_code":         "산업 분류 코드 (KRX·GICS 기준)",
            "industry_name":         "산업명 (예: 반도체및반도체장비, 소프트웨어)",
            "sector":                "섹터명 (예: 정보기술, 소재, 헬스케어)",
            "per":                   "현재 PER(주가수익비율). 단위: 배수(x). 시가총액 ÷ 당기순이익 기준",
            "pbr":                   "현재 PBR(주가순자산비율). 단위: 배수(x). 시가총액 ÷ 자본총계 기준",
            "eps":                   "주당순이익(EPS). 단위: 원(KRW) 또는 달러(USD)",
            "foreign_ownership_pct": "외국인 지분율. 단위: %(퍼센트)",
            "target_price":          "애널리스트 컨센서스 목표주가. 단위: 원(KRW) 또는 달러(USD)",
            "logo_url":              "종목 로고 이미지 URL",
        },
    },

    "stock_metadata": {
        "description": (
            "⚠️ 구버전 종목 테이블 (폐기 예정). 초기 5개 미국 주식만 하드코딩되어 있습니다. "
            "신규 개발 시 stock_info를 사용하세요."
        ),
        "columns": {
            "id":         "자동 증가 기본키",
            "ticker":     "종목코드 (UNIQUE). 예: AAPL, MSFT",
            "name":       "종목명",
            "market":     "시장 구분. 예: NASDAQ",
            "is_active":  "활성 여부",
            "created_at": "레코드 생성 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 시세 데이터 (OHLCV)
    # ──────────────────────────────────────────────────────────
    "stock_price_1d": {
        "description": (
            "일봉(일별 OHLCV) 시세 테이블. 한국·미국 전 종목의 일별 시가·고가·저가·종가·거래량을 저장합니다. "
            "수집 출처: Yahoo Finance(해외·국내 일반), Naver Securities(한국 장중·장후). "
            "UNIQUE(ticker, timestamp). "
            "⚠️ timestamp는 UTC 기준. 한국 주식은 timestamp_kst, 미국 주식은 timestamp_ny 사용 권장."
        ),
        "columns": {
            "id":            "자동 증가 기본키",
            "ticker":        "종목코드. stock_info.ticker 참조 (FK)",
            "timestamp":     "기준 타임스탬프 (UTC). ⚠️ 일봉이지만 시간 포함 — 날짜 비교 시 DATE() 변환 필요",
            "timestamp_ny":  "뉴욕 현지 시각 (미국 주식용, EST/EDT)",
            "timestamp_kst": "한국 표준시 (KST, UTC+9) — 한국 주식 거래일 기준",
            "open":          "시가. 단위: 원(KRW) 또는 달러(USD)",
            "high":          "고가. 단위: 원(KRW) 또는 달러(USD)",
            "low":           "저가. 단위: 원(KRW) 또는 달러(USD)",
            "close":         "종가. 단위: 원(KRW) 또는 달러(USD)",
            "volume":                   "거래량. 단위: 주(株)",
            "created_at":               "레코드 수집 시각",
            "updated_at":               "레코드 마지막 수정 시각",
            "foreign_buy_volume":        "외국인 순매수 수량. 양수=순매수(매수>매도), 음수=순매도. 단위: 주",
            "institution_buy_volume":    "기관 순매수 수량. 양수=순매수, 음수=순매도. 단위: 주",
            "individual_buy_volume":     "개인 순매수 수량. 양수=순매수, 음수=순매도. 단위: 주",
            "foreign_ownership_pct":     "외국인 보유비중(%). 해당 거래일 기준 외국인 보유주식수 ÷ 상장주식수 × 100",
            "after_hours_close":         "시간외 종가. 미국 주식 전용. 정규장 마감(16:00 ET) 이후 거래된 마지막 가격",
            "after_hours_change_pct":    "시간외 등락률(%) = (시간외종가 - 종가) ÷ 종가 × 100",
        },
    },

    "stock_price_1m": {
        "description": (
            "1분봉 시세 테이블. 장중 실시간 모니터링 및 고빈도 분석 용도. "
            "데이터 크기가 매우 크므로 조회 시 ticker + 날짜 범위 조건 필수. "
            "UNIQUE(ticker, timestamp)."
        ),
        "columns": {
            "id":            "자동 증가 기본키",
            "ticker":        "종목코드. stock_info.ticker 참조 (FK)",
            "timestamp":     "봉 기준 타임스탬프 (UTC)",
            "timestamp_ny":  "뉴욕 현지 시각",
            "timestamp_kst": "한국 표준시",
            "open":          "시가",
            "high":          "고가",
            "low":           "저가",
            "close":         "종가",
            "volume":        "거래량. 단위: 주(株)",
            "created_at":    "레코드 수집 시각",
            "updated_at":    "레코드 마지막 수정 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 기술적 지표
    # ──────────────────────────────────────────────────────────
    "stock_indicators": {
        "description": (
            "종목별 기술적 지표 테이블. 매 거래일 장 마감 후 stock_price_1d를 기반으로 pandas-ta 라이브러리로 계산됩니다. "
            "이동평균(MA·EMA), MACD, RSI, 볼린저밴드, 스토캐스틱, ATR, 52주 고저 등 포함. "
            "DAG: dag_daily_indicators(미국), dag_kr_daily_indicators(한국). "
            "UNIQUE(ticker, trade_date)."
        ),
        "columns": {
            "id":                 "자동 증가 기본키 (BIGSERIAL)",
            "ticker":             "종목코드. stock_info.ticker 참조 (FK)",
            "trade_date":         "거래일 (DATE). 지표 계산 기준일.",
            "open":               "당일 시가 (참조용)",
            "high":               "당일 고가 (참조용)",
            "low":                "당일 저가 (참조용)",
            "close":              "당일 종가 (참조용)",
            "volume":             "당일 거래량 (참조용)",
            "ma5":                "5일 단순이동평균(SMA). 단기 추세 파악",
            "ma10":               "10일 단순이동평균",
            "ma20":               "20일 단순이동평균. 단기 지지·저항 기준선",
            "ma60":               "60일 단순이동평균. 중기 추세선",
            "ma120":              "120일 단순이동평균. 중장기 추세선",
            "ma200":              "200일 단순이동평균. 장기 추세선 — 골든크로스/데드크로스 기준",
            "ema12":              "12일 지수이동평균(EMA). MACD 계산에 사용",
            "ema26":              "26일 지수이동평균(EMA). MACD 계산에 사용",
            "macd":               "MACD 값 = EMA12 - EMA26. 양수=상승모멘텀, 음수=하락모멘텀",
            "macd_signal":        "MACD 시그널선 = MACD 9일 EMA",
            "macd_hist":          "MACD 히스토그램 = MACD - Signal. 추세 전환 신호",
            "rsi14":              "14일 RSI(상대강도지수). 범위: 0~100. 70 초과=과매수, 30 미만=과매도",
            "bb_upper":           "볼린저밴드 상단 (MA20 + 2σ)",
            "bb_middle":          "볼린저밴드 중간선 (MA20)",
            "bb_lower":           "볼린저밴드 하단 (MA20 - 2σ)",
            "bb_width":           "볼린저밴드 폭 = (상단 - 하단) / 중간선. 변동성 척도",
            "bb_pctb":            "볼린저밴드 %B. 0~1이 밴드 내, 1 초과=상단 돌파, 0 미만=하단 이탈",
            "stoch_k":            "스토캐스틱 %K (빠른선). 범위: 0~100",
            "stoch_d":            "스토캐스틱 %D (느린선, %K의 3일 SMA)",
            "volume_ma20":        "20일 평균 거래량. 단위: 주(株)",
            "volume_ratio":       "거래량 비율 = 당일 거래량 / 20일 평균 거래량. 1.5 초과=거래량 급증",
            "atr14":              "14일 ATR(Average True Range). 가격 변동폭 절대값 — 손절매·포지션 사이징에 활용",
            "trend_ma":           "이동평균 기반 추세 구분. 값: UP(상승), DOWN(하락), SIDEWAYS(횡보)",
            "golden_cross":       "골든크로스 발생 여부. TRUE = 당일 MA5가 MA20을 상향 돌파 (단기 매수 신호)",
            "death_cross":        "데드크로스 발생 여부. TRUE = 당일 MA5가 MA20을 하향 돌파 (단기 매도 신호)",
            "high_52w":           "52주(약 1년) 최고가",
            "low_52w":            "52주(약 1년) 최저가",
            "pct_from_52w_high":  "52주 고가 대비 현재가 등락률(%). 음수 = 고가 대비 하락. -5% 이내 = 52주 고가 근접",
            "pct_from_52w_low":   "52주 저가 대비 현재가 등락률(%). 양수 = 저가 대비 상승",
            "created_at":         "레코드 생성 시각",
        },
    },

    "market_daily_summary": {
        "description": (
            "시장 전체 일일 요약 테이블. 매 거래일 stock_indicators 계산 후 시장 breadth 지표를 집계합니다. "
            "상승/하락/보합 종목 수, 52주 신고가·신저가, 이동평균 위·아래 종목 비율 등을 포함합니다. "
            "UNIQUE(trade_date)."
        ),
        "columns": {
            "id":                 "자동 증가 기본키",
            "trade_date":         "거래일 (UNIQUE)",
            "total_stocks":       "분석 대상 전체 종목 수",
            "advancing":          "전일 대비 상승 종목 수",
            "declining":          "전일 대비 하락 종목 수",
            "unchanged":          "전일 대비 보합(등락 없음) 종목 수",
            "advance_decline_ratio": "등락 비율 = advancing / declining. 1 초과=시장 강세",
            "total_volume":       "전체 시장 거래량 합계. 단위: 주(株)",
            "avg_volume_ratio":   "종목별 거래량비율(volume_ratio)의 평균. 1.0=평상시, 1.5 초과=거래 활발",
            "new_high_52w":       "당일 52주 신고가 달성 종목 수",
            "new_low_52w":        "당일 52주 신저가 기록 종목 수",
            "above_ma20":         "20일 이동평균선 위에 있는 종목 수",
            "above_ma50":         "50일 이동평균선 위에 있는 종목 수",
            "above_ma200":        "200일 이동평균선 위에 있는 종목 수",
            "pct_above_ma20":     "20일선 위 종목 비율(%). 50% 이상=단기 상승 추세",
            "pct_above_ma200":    "200일선 위 종목 비율(%). 시장 장기 건강도 지표",
            "rsi_oversold":       "RSI 30 미만(과매도) 종목 수",
            "rsi_overbought":     "RSI 70 초과(과매수) 종목 수",
            "avg_atr_pct":        "종목별 ATR%의 평균. 시장 전반 변동성 수준",
            "created_at":         "레코드 생성 시각",
        },
    },

    "sector_daily_performance": {
        "description": (
            "KRX 섹터별 일일 성과 테이블. KRX 섹터 ETF를 기반으로 수집됩니다. "
            "UNIQUE(trade_date, sector)."
        ),
        "columns": {
            "id":           "자동 증가 기본키",
            "trade_date":   "거래일",
            "sector":       "섹터명. 예: 반도체, 은행, 자동차, IT",
            "avg_return":   "섹터 평균 수익률(%). 단위: %",
            "total_volume": "섹터 전체 거래량. 단위: 주(株)",
            "advancing":    "섹터 내 상승 종목 수",
            "declining":    "섹터 내 하락 종목 수",
            "created_at":   "레코드 생성 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 컨센서스·애널리스트 추정
    # ──────────────────────────────────────────────────────────
    "consensus_estimates": {
        "description": (
            "애널리스트 컨센서스(투자의견·목표주가·실적 추정) 테이블. "
            "Naver 금융 WiseReport(FnGuide 집계)에서 수집합니다. "
            "수집 주기: 매주 월요일 또는 실시간 조회 후 업데이트. "
            "UNIQUE(ticker, estimate_year)."
        ),
        "columns": {
            "id":             "자동 증가 기본키",
            "ticker":         "종목코드 (Yahoo Finance 형식). 예: 005930.KS. stock_info.ticker 참조 (FK)",
            "stock_code":     "6자리 순수 종목코드. 예: 005930. ⚠️ ticker에서 파생 가능 — 중복 컬럼",
            "rating":         "투자의견 점수. 범위: 1.0(Sell)~5.0(Strong Buy). ⚠️ 높을수록 긍정적 의견",
            "target_price":   "12개월 목표주가. 단위: 원(KRW)",
            "analyst_count":  "추정에 참여한 애널리스트 수 (커버리지 기관 수)",
            "estimate_year":  "추정 대상 회계연도. 예: 2025",
            "est_eps":        "예상 주당순이익(EPS). 단위: 원(KRW)",
            "est_per":        "예상 주가수익비율(PER). 단위: 배수(x). 목표주가 ÷ 예상 EPS 기준",
            "est_pbr":        "예상 주가순자산비율(PBR). 단위: 배수(x)",
            "est_roe":        "예상 자기자본이익률(ROE). 단위: %(퍼센트)",
            "est_dividend":          "예상 배당금. 단위: 원(KRW)",
            "data_source":           "데이터 출처. 고정값: wisereport",
            "collected_at":          "수집 시각",
            "updated_at":            "최근 갱신 시각",
            "est_revenue":           "애널리스트 추정 매출액. 단위: 억원(KRW). ⚠️ 재무제표의 revenue(원 단위)와 단위 다름",
            "est_operating_profit":  "애널리스트 추정 영업이익. 단위: 억원(KRW)",
            "est_net_income":        "애널리스트 추정 당기순이익. 단위: 억원(KRW)",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 재무제표 (DART)
    # ──────────────────────────────────────────────────────────
    "company_dart_info": {
        "description": (
            "종목코드(ticker)와 DART 기업코드(corp_code)의 매핑 테이블. "
            "DART API는 ticker 대신 10자리 corp_code를 사용하므로 이 테이블이 연결 고리 역할을 합니다. "
            "financial_statements 및 모든 company_* 테이블 조회 시 필수 JOIN 테이블. "
            "UNIQUE(ticker)."
        ),
        "columns": {
            "id":          "자동 증가 기본키",
            "ticker":      "종목코드 (Yahoo Finance 형식). stock_info.ticker 참조 (FK)",
            "corp_code":   "DART 기업고유번호 (10자리). DART API 모든 호출의 기준 키",
            "corp_name":    "DART 공시 기준 법인명",
            "stock_code":   "DART 기준 6자리 주식코드 (ticker에서 '.KS'/'.KQ' 제거한 값)",
            "market":       "상장 시장. 값: KOSPI, KOSDAQ",
            "sector":       "업종 분류 (DART 기준). 예: 전기전자, 화학",
            "fiscal_month": "결산월. 12=12월 결산(대부분 한국 기업), 3=3월 결산(일부 금융사)",
            "created_at":   "레코드 최초 생성 시각",
            "updated_at":   "최근 동기화 시각",
        },
    },

    "financial_statements": {
        "description": (
            "한국 상장기업 재무제표 테이블. DART(전자공시시스템) API를 통해 수집됩니다. "
            "연결재무제표(CFS) 우선, 없을 경우 별도재무제표(OFS) 사용. "
            "손익계산서·재무상태표·현금흐름표 항목이 정규화된 컬럼으로 통합 저장됩니다. "
            "⚠️ 구 DART RAW 방식(sj_div 컬럼)과 달리 컬럼 직접 조회 방식. "
            "수집 DAG: 05_kr_financial_stmt_weekly(주 1회), 05_kr_financial_stmt_manual(수동 5년치). "
            "UNIQUE(corp_code, fiscal_year, fiscal_quarter, report_type)."
        ),
        "columns": {
            "id":                    "자동 증가 기본키",
            "corp_code":             "DART 기업고유번호 (10자리). company_dart_info.corp_code 참조 (FK)",
            "ticker":                "종목코드 (참조용)",
            "fiscal_year":           "회계연도. 예: 2024",
            "fiscal_quarter":        "분기 구분. 1=1분기(Q1), 2=반기(H1), 3=3분기(Q3), 4=연간(Full Year)",
            "report_type":           "보고서 유형. 값: annual(사업보고서), Q1(1분기), half(반기), Q3(3분기)",
            "revenue":               "매출액(영업수익). 단위: 원(KRW)",
            "cost_of_sales":         "매출원가. 단위: 원(KRW)",
            "gross_profit":          "매출총이익 = 매출액 - 매출원가. 단위: 원(KRW)",
            "operating_expense":     "판매비·관리비(판관비). 단위: 원(KRW)",
            "operating_profit":      "영업이익 = 매출총이익 - 판관비. 단위: 원(KRW)",
            "net_income":            "당기순이익(지배주주 귀속). 단위: 원(KRW)",
            "total_assets":          "자산총계(재무상태표). 단위: 원(KRW)",
            "current_assets":        "유동자산. 단위: 원(KRW)",
            "non_current_assets":    "비유동자산. 단위: 원(KRW)",
            "total_liabilities":     "부채총계. 단위: 원(KRW)",
            "current_liabilities":   "유동부채. 단위: 원(KRW)",
            "non_current_liabilities": "비유동부채. 단위: 원(KRW)",
            "total_equity":          "자본총계(순자산). 단위: 원(KRW). PBR 계산 분모.",
            "cash_from_operating":   "영업활동 현금흐름. 양수=현금 창출, 음수=현금 소비. 단위: 원(KRW)",
            "cash_from_investing":   "투자활동 현금흐름. 음수=자본지출(CAPEX). 단위: 원(KRW)",
            "cash_from_financing":   "재무활동 현금흐름. 음수=차입 상환·배당 지급. 단위: 원(KRW)",
            "shares_outstanding":    "발행주식수. 단위: 주(株). EPS = 당기순이익 ÷ shares_outstanding",
            "report_date":           "DART 공시 제출일 (DATE)",
            "created_at":            "레코드 최초 생성 시각",
            "updated_at":            "최근 업데이트 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 기업 정보 (DART 사업보고서)
    # ──────────────────────────────────────────────────────────
    "company_dividend": {
        "description": (
            "기업 배당 정보 테이블. DART 사업보고서에서 연간 배당 내역을 수집합니다. "
            "보통주·우선주 구분으로 저장됩니다. "
            "UNIQUE(ticker, fiscal_year, stock_type)."
        ),
        "columns": {
            "id":                     "자동 증가 기본키",
            "ticker":                 "종목코드. stock_info.ticker 참조 (FK)",
            "corp_code":              "DART 기업고유번호",
            "fiscal_year":            "배당 기준 회계연도",
            "stock_type":             "주식 종류. 값: 보통주, 우선주",
            "cash_dividend_per_share": "주당 현금배당금. 단위: 원(KRW)",
            "dividend_yield":         "시가배당률(배당수익률). 단위: %(퍼센트)",
            "payout_ratio":           "배당성향 = 배당금 / 당기순이익. 단위: %(퍼센트)",
            "created_at":             "레코드 생성 시각",
            "updated_at":             "최근 갱신 시각",
        },
    },

    "company_employees": {
        "description": (
            "기업 직원 현황 테이블. DART 사업보고서에서 부문·성별·고용형태별 직원 수를 수집합니다. "
            "UNIQUE(ticker, fiscal_year, department, gender, employee_type)."
        ),
        "columns": {
            "id":                  "자동 증가 기본키",
            "ticker":              "종목코드. stock_info.ticker 참조 (FK)",
            "corp_code":           "DART 기업고유번호",
            "fiscal_year":         "회계연도",
            "department":          "사업 부문명 (예: 반도체, CE 부문)",
            "gender":              "성별. 값: 남, 여",
            "employee_type":       "고용 형태. 값: 정규직, 계약직",
            "employee_count":      "직원 수. 단위: 명",
            "avg_service_years":   "평균 근속연수. 단위: 년",
            "avg_salary":          "평균 급여. ⚠️ 단위: 천원(×1,000 = 원)",
            "created_at":          "레코드 생성 시각",
        },
    },

    "company_executives": {
        "description": (
            "기업 임원 현황 테이블. DART 사업보고서에서 등기·비등기 임원 정보를 수집합니다. "
            "UNIQUE(ticker, fiscal_year, name, position)."
        ),
        "columns": {
            "id":              "자동 증가 기본키",
            "ticker":          "종목코드. stock_info.ticker 참조 (FK)",
            "corp_code":       "DART 기업고유번호",
            "fiscal_year":     "회계연도",
            "name":            "임원 성명",
            "gender":          "성별",
            "position":        "직위 (예: 대표이사, 사외이사, CFO)",
            "is_ceo":          "대표이사 여부 (TRUE/FALSE)",
            "is_registered":   "등기임원 여부. TRUE=등기임원, FALSE=비등기임원",
            "tenure_start":    "임기 시작일",
            "tenure_end":      "임기 종료일",
            "created_at":      "레코드 생성 시각",
        },
    },

    "company_audit": {
        "description": (
            "외부 감사의견 테이블. DART 사업보고서에서 감사인 및 감사의견을 수집합니다. "
            "감사의견이 '적정'이 아닌 경우 투자 위험 신호가 될 수 있습니다. "
            "UNIQUE(ticker, fiscal_year)."
        ),
        "columns": {
            "id":          "자동 증가 기본키",
            "ticker":      "종목코드. stock_info.ticker 참조 (FK)",
            "corp_code":   "DART 기업고유번호",
            "fiscal_year": "회계연도",
            "auditor":     "감사법인명 (예: 삼일회계법인, 한영회계법인)",
            "opinion":     "감사의견. 값: 적정(정상), 한정, 부적정, 의견거절(위험)",
            "emphasis":    "강조사항 또는 핵심감사사항 (텍스트)",
            "created_at":  "레코드 생성 시각",
            "updated_at":  "최근 갱신 시각",
        },
    },

    "company_treasury_stock": {
        "description": (
            "자기주식(자사주) 변동 현황 테이블. DART 사업보고서에서 연간 자사주 취득·처분·소각 내역을 수집합니다. "
            "자사주 소각은 주당 가치를 높이는 주주환원 지표입니다. "
            "UNIQUE(ticker, fiscal_year, stock_type)."
        ),
        "columns": {
            "id":               "자동 증가 기본키",
            "ticker":           "종목코드. stock_info.ticker 참조 (FK)",
            "corp_code":        "DART 기업고유번호",
            "fiscal_year":      "회계연도",
            "stock_type":       "주식 종류. 값: 보통주, 우선주",
            "beginning_shares": "기초(연초) 자기주식 수량. 단위: 주",
            "acquired":         "당기 취득 수량. 단위: 주",
            "disposed":         "당기 처분 수량. 단위: 주",
            "retired":          "당기 소각 수량. 단위: 주",
            "ending_shares":    "기말(연말) 자기주식 수량. 단위: 주",
            "created_at":       "레코드 생성 시각",
        },
    },

    "company_shareholders": {
        "description": (
            "최대주주 및 주요 주주 현황 테이블. DART 사업보고서에서 최대주주 및 5% 이상 주주 내역을 수집합니다. "
            "UNIQUE(ticker, fiscal_year, shareholder_name)."
        ),
        "columns": {
            "id":               "자동 증가 기본키",
            "ticker":           "종목코드. stock_info.ticker 참조 (FK)",
            "corp_code":        "DART 기업고유번호",
            "fiscal_year":      "회계연도",
            "shareholder_name": "주주명 (법인명 또는 개인명)",
            "relation":         "최대주주와의 관계 (예: 본인, 임원, 계열회사)",
            "shares":           "보유 주식 수. 단위: 주",
            "ownership_ratio":  "지분율. 단위: %(퍼센트)",
            "created_at":       "레코드 생성 시각",
        },
    },

    "company_exec_compensation": {
        "description": (
            "임원 개별 보수 공시 테이블. DART 사업보고서에서 연간 보수 5억원 이상 임원의 개별 보수를 수집합니다. "
            "5억원 미만 임원은 공시 대상이 아니므로 미포함. "
            "UNIQUE(ticker, fiscal_year, name)."
        ),
        "columns": {
            "id":                 "자동 증가 기본키",
            "ticker":             "종목코드. stock_info.ticker 참조 (FK)",
            "corp_code":          "DART 기업고유번호",
            "fiscal_year":        "보수 기준 회계연도",
            "name":               "임원 성명",
            "position":           "직위 (예: 대표이사, 사장)",
            "total_compensation": "총 보수액 (급여 + 상여 + 주식보상 등). 단위: 원(KRW)",
            "created_at":         "레코드 생성 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 매크로 지표 (통합)
    # ──────────────────────────────────────────────────────────
    "macro_indicators": {
        "description": (
            "글로벌 매크로·금리·시장지수·감성 지수 통합 테이블 (EAV 패턴). "
            "indicator_type으로 지표 종류를, region으로 지역을 구분합니다. "
            "수집 DAG: 04_macro_global_hourly(VIX·환율·원자재·채권·지수·섹터ETF), "
            "05_kr_ecos_weekly(기준금리·CPI·GDP·M2), 05_kr_rates_daily(CD금리·COFIX·국고채), "
            "05_kr_investor_trend(투자자 매매동향), 04_macro_risk_daily(GDELT 리스크 지수), "
            "06_news_sentiment_daily(뉴스 감성 지수). "
            "UNIQUE(indicator_date, region, indicator_type)."
        ),
        "columns": {
            "id":             "자동 증가 기본키",
            "indicator_date": "지표 기준일",
            "region":         (
                "지역 구분. 값: North America, South Korea, Japan, China, "
                "Western Europe, Central Europe, MEA(중동·아프리카), India 등"
            ),
            "indicator_type": (
                "지표 유형 식별자. 카테고리별 실제 값 목록:\n"
                "【시장 변동성】 vix(CBOE VIX), vkospi(한국 변동성지수)\n"
                "【공포·탐욕】 fear_greed_index(CNN Fear & Greed, 0=극도공포~100=극도탐욕)\n"
                "【글로벌 리스크】 global_risk_index, epu_index(경제정책불확실성지수)\n"
                "【환율 (vs USD)】 exchange_rate — region으로 통화 구분: South Korea(KRW), Japan(JPY), China(CNY), Western Europe(EUR), India(INR), Southeast Asia(THB 등), CALA(BRL 등), MEA(ZAR 등), North America(CAD)\n"
                "【달러 지수】 dollar_index(DXY)\n"
                "【원자재】 commodity_gold(금), commodity_oil(WTI), commodity_copper(구리), commodity_silver(은)\n"
                "【암호화폐】 crypto_btc(비트코인, USD)\n"
                "【미국 국채 금리】 interest_rate_10y, interest_rate_5y, interest_rate_3m, treasury_10y, treasury_5y, treasury_3m\n"
                "【주요 지수】 stock_index_sp500, stock_index_nasdaq, stock_index_kospi, stock_index_kosdaq, stock_index_nikkei, stock_index_shanghai, stock_index_eurostoxx, stock_index_sensex\n"
                "【미국 섹터 ETF】 sector_technology(XLK), sector_financials(XLF), sector_healthcare(XLV), sector_energy(XLE), sector_consumer_disc(XLY), sector_consumer_staples(XLP), sector_industrials(XLI), sector_materials(XLB), sector_utilities(XLU), sector_realestate(XLRE), sector_communication(XLC)\n"
                "【반도체 관련】 index_sox(필라델피아 반도체지수), etf_soxx, etf_smh, etf_soxl, stock_samsung(삼성전자), stock_skhynix(SK하이닉스)\n"
                "【한국 금리】 korea_base_rate(기준금리), korea_call_rate(콜금리), korea_cd_91d(CD91일), korea_govt_3y(국고채3년), korea_corp_3y(회사채3년), korea_cofix_new(신규취급액 COFIX), korea_cofix_bal(잔액기준 COFIX)\n"
                "【한국 거시경제 (ECOS)】 korea_cpi, korea_cpi_yoy, korea_gdp, korea_gdp_growth, korea_m2, korea_export, korea_import, korea_trade_balance, korea_unemployment, korea_forex_reserves, korea_consumer_confidence, korea_business_confidence\n"
                "【한국 부동산】 korea_housing_price_index, korea_jeonse_price_index, korea_apartment_price_seoul, korea_jeonse_price_seoul, korea_housing_index, korea_housing_price_change, korea_housing_transaction, korea_price_to_rent, korea_home_ownership\n"
                "【KRX 섹터 지수】 krx_sector_25~krx_sector_299 (KRX 업종코드 기반)\n"
                "【DRAM 현물가격 (DRAMeXchange)】 dram_ddr3_4gb, dram_ddr4_8gb/16gb, dram_ddr4_8gb_ett/16gb_ett, dram_ddr5_16gb/16gb_ett — 각각 _daily_high/low, _session_high/low 파생값 포함\n"
                "【NAND 현물가격】 nand_mlc_32gb/64gb, nand_tlc_128gb/256gb/512gb, nand_slc_1gb/2gb — 각각 _daily_high/low, _session_high/low 파생값 포함\n"
                "【지정학 리스크 점수 (국가별)】 risk_score_{cc}(0~100 정규화 점수), risk_ratio_{cc}(리스크 기사 비율%), risk_news_count_{cc}(리스크 기사 수) — cc: us, kr, cn, jp, ru, ua, ir, il, tw, eu\n"
                "【지정학 헤드라인 수】 risk_headlines_{cc} — 해당 국가 상위 리스크 헤드라인 건수\n"
                "【뉴스 감성 지수 (0~100, 50=중립)】 news_sentiment_overall(전체), news_sentiment_geopolitical(지정학), news_sentiment_economic(경제), news_sentiment_regions(지역별 키워드), news_sentiment_regional(지역별 — region 컬럼으로 구분)\n"
                "【뉴스 감성 부가】 news_count_geopolitical/economic/regions(수집 기사 수), news_positive_ratio/negative_ratio(긍정·부정 기사 비율%)\n"
                "【분쟁 카운트】 conflict_count_{cc}(국가별 분쟁 이벤트 수)"
            ),
            "value":          "지표 값. 단위는 indicator_type에 따라 상이 — 환율(원/달러), 금리(%), 감성지수(0~100), 가격(달러)",
            "change_pct":     "전일 대비 변화율(%). 양수=상승, 음수=하락. NULL이면 전일 데이터 없음",
            "created_at":     "레코드 수집 시각",
        },
    },

    "risk_headlines": {
        "description": (
            "지정학 리스크 헤드라인 테이블. Google News RSS를 통해 수집한 국가별 위험 뉴스 헤드라인을 저장합니다. "
            "DAG: 04_macro_risk_daily. 키워드 가중치 기반 위험 점수로 정렬된 상위 헤드라인 보존. "
            "UNIQUE(headline_date, country_code, title)."
        ),
        "columns": {
            "id":           "자동 증가 기본키",
            "headline_date": "헤드라인 수집 날짜",
            "country_code": "국가 코드 (ISO 2자리). 예: US, KR, CN, RU, IR",
            "country_name": "국가명. 예: United States, South Korea",
            "title":        "뉴스 헤드라인 원문 (영어)",
            "url":          "기사 원문 URL",
            "source":       "뉴스 출처 매체명",
            "risk_score":   "리스크 점수 (0~100). 키워드 가중치 합산 후 정규화. 높을수록 위험",
            "created_at":   "레코드 수집 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 뉴스
    # ──────────────────────────────────────────────────────────
    "news": {
        "description": (
            "뉴스 기사 테이블. Naver 뉴스 API 및 RSS를 통해 수집한 한국·글로벌 경제 뉴스를 저장합니다. "
            "embedding 컬럼은 OpenAI text-embedding-3-small 모델로 생성된 1536차원 벡터입니다. "
            "NL2SQL 시맨틱 검색·유사 기사 추천에 활용됩니다. "
            "DAG: 06_naver_news_api_daily, 06_naver_news_daily."
        ),
        "columns": {
            "id":           "자동 증가 기본키",
            "title":        "뉴스 제목",
            "url":          "기사 원문 URL",
            "body":         "기사 본문 전문 (HTML 태그 제거)",
            "summary":      "LLM이 생성한 기사 요약문 또는 리드 문단",
            "published_at": "기사 발행 일시",
            "source":       "뉴스 매체명 (예: 한국경제, 연합뉴스)",
            "created_at":   "레코드 수집 시각",
            "updated_at":   "최근 갱신 시각",
            "embedding":    "OpenAI text-embedding-3-small 벡터 (1536차원). pgvector 타입. 시맨틱 검색에 사용",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 포트폴리오
    # ──────────────────────────────────────────────────────────
    "portfolio": {
        "description": (
            "사용자 포트폴리오 계정 테이블. 한국투자증권(KIS) API 연동 정보와 현재 보유 현금을 관리합니다. "
            "portfolio_snapshot 테이블과 1:N 관계입니다."
        ),
        "columns": {
            "id":              "자동 증가 기본키",
            "user_id":         "포트폴리오 소유자 ID. users.id 참조 (FK)",
            "name":            "포트폴리오 이름 (사용자 지정)",
            "broker":          "증권사명. 예: 한국투자증권(KIS)",
            "currency":        "포트폴리오 기준 통화. 값: KRW, USD",
            "description":     "포트폴리오 메모 또는 전략 설명",
            "kis_app_key":     "한국투자증권 Open API App Key (암호화 저장 권장)",
            "kis_app_secret":  "한국투자증권 Open API App Secret (암호화 저장 권장)",
            "kis_account_no":  "증권 계좌번호 (하이픈 포함 형식. 예: 12345678-01)",
            "kis_account_type": "KIS 계좌 유형 코드. 01=국내주식, 01F=해외주식",
            "cash_krw":        "국내 예수금(원화). 단위: 원(KRW). 07_portfolio_snapshot_daily DAG이 업데이트",
            "cash_usd":        "해외 예수금(달러). 단위: 달러(USD). 07_portfolio_snapshot_daily DAG이 업데이트",
            "last_synced_at":  "KIS API와 마지막으로 동기화된 시각",
            "created_at":      "포트폴리오 최초 생성 시각",
            "updated_at":      "마지막 수정 시각",
        },
    },

    "portfolio_snapshot": {
        "description": (
            "포트폴리오 일별 가치 스냅샷 테이블. 매일 미국 장 마감 후 KIS API에서 잔고를 조회하여 저장합니다. "
            "국내주식·해외주식·현금을 원화로 환산한 통합 자산 가치를 기록합니다. "
            "DAG: 07_portfolio_snapshot_daily (화~토 07:00 KST). "
            "UNIQUE(portfolio_id, snapshot_date)."
        ),
        "columns": {
            "id":              "자동 증가 기본키",
            "portfolio_id":    "포트폴리오 ID. portfolio.id 참조",
            "snapshot_date":   "스냅샷 기준 일시 (TIMESTAMP)",
            "total_value_krw": "총 자산 가치 (주식 + 현금, 원화 환산). 단위: 원(KRW)",
            "stock_value_krw": "보유 주식 평가액 합계 (국내 + 해외, 원화 환산). 단위: 원(KRW)",
            "cash_value_krw":  "보유 현금 합계 (KRW + USD×환율). 단위: 원(KRW)",
            "daily_pnl":       "당일 손익 = 오늘 총자산 - 어제 총자산. 단위: 원(KRW)",
            "daily_pnl_pct":   "당일 수익률(%). 단위: %(퍼센트)",
            "total_pnl":       "미실현 평가손익 합계 (매입가 대비). 단위: 원(KRW)",
            "total_pnl_pct":   "누적 손익률(%) = total_pnl ÷ 총 매입금액 × 100",
            "exchange_rate":   "스냅샷 시점 원/달러 환율. 출처: macro_indicators. 단위: 원(KRW/USD)",
            "created_at":      "스냅샷 생성 시각",
        },
    },

    "holding": {
        "description": (
            "포트폴리오 보유 종목 테이블. KIS API에서 실시간 잔고를 조회해 저장합니다. "
            "portfolio_id + ticker UNIQUE. synced_at이 최신일수록 현재 시세에 가까운 값."
        ),
        "columns": {
            "id":            "자동 증가 기본키",
            "portfolio_id":  "포트폴리오 ID. portfolio.id 참조 (FK)",
            "ticker":        "종목코드. stock_info.ticker 참조 (FK)",
            "name":          "종목명 (조회 당시 기준)",
            "quantity":      "보유 수량. 단위: 주(株)",
            "avg_price":     "평균 매수가. 단위: 통화별 (원/달러)",
            "current_price": "현재가 (KIS API 조회 시점 기준). 단위: 통화별",
            "market_value":  "평가금액 = 현재가 × 보유수량. 단위: 통화별",
            "pnl_amount":    "평가손익 = 평가금액 - (평균매수가 × 수량). 단위: 통화별",
            "pnl_percent":   "손익률(%) = pnl_amount ÷ 매입금액 × 100",
            "currency":      "통화 구분. 값: KRW(국내), USD(해외)",
            "market":        "거래소. 값: KRX, NASDAQ, NYSE",
            "synced_at":     "KIS API에서 잔고를 마지막으로 동기화한 시각",
            "updated_at":    "레코드 마지막 수정 시각",
        },
    },

    "consensus_history": {
        "description": (
            "애널리스트 컨센서스 변화 이력 테이블. consensus_estimates의 일별 스냅샷 형태로 "
            "컨센서스 변화 추이를 추적합니다. "
            "UNIQUE(ticker, collected_date, estimate_year)."
        ),
        "columns": {
            "id":                  "자동 증가 기본키",
            "ticker":              "종목코드. stock_info.ticker 참조 (FK)",
            "stock_code":          "6자리 순수 종목코드",
            "collected_date":      "컨센서스 수집 기준일 (DATE)",
            "estimate_year":       "추정 대상 회계연도",
            "rating":              "투자의견 점수. 1.0(Sell)~5.0(Strong Buy). 높을수록 긍정적",
            "target_price":        "12개월 목표주가. 단위: 원(KRW)",
            "analyst_count":       "추정 참여 애널리스트 수",
            "est_eps":             "예상 EPS(주당순이익). 단위: 원(KRW)",
            "est_per":             "예상 PER(주가수익비율). 단위: 배수(x)",
            "est_revenue":         "애널리스트 추정 매출액. 단위: 억원(KRW)",
            "est_operating_profit": "애널리스트 추정 영업이익. 단위: 억원(KRW)",
            "est_net_income":      "애널리스트 추정 당기순이익. 단위: 억원(KRW)",
            "data_source":         "데이터 출처. 고정값: wisereport",
            "created_at":          "레코드 수집 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 미국 주식
    # ──────────────────────────────────────────────────────────
    "us_financial_statements": {
        "description": (
            "미국 주식 재무제표 테이블. yfinance에서 수집한 NASDAQ·NYSE 상장 기업의 연간 손익계산서·재무상태표·현금흐름표를 저장합니다. "
            "DAG: 05_us_fundamentals_weekly (매주 토요일). "
            "UNIQUE(ticker, fiscal_year, period_type)."
        ),
        "columns": {
            "ticker":              "종목코드. stock_info.ticker 참조 (FK). 예: AAPL, NVDA",
            "fiscal_year":         "회계연도. 예: 2024",
            "period_type":         "보고 기간 유형. 값: annual(연간), quarterly(분기)",
            "revenue":             "매출액. 단위: 달러(USD)",
            "gross_profit":        "매출총이익 = 매출액 - 매출원가. 단위: 달러(USD)",
            "operating_income":    "영업이익. 단위: 달러(USD)",
            "net_income":          "당기순이익. 단위: 달러(USD)",
            "ebitda":              "EBITDA = 이자·세금·감가상각 전 영업이익. 단위: 달러(USD)",
            "total_assets":        "자산총계. 단위: 달러(USD)",
            "total_liabilities":   "부채총계. 단위: 달러(USD)",
            "total_equity":        "자본총계 = 자산총계 - 부채총계. 단위: 달러(USD)",
            "total_debt":          "총차입금(단기+장기+사채). 단위: 달러(USD)",
            "total_cash":          "현금및현금성자산. 단위: 달러(USD)",
            "operating_cashflow":  "영업활동 현금흐름. 단위: 달러(USD)",
            "free_cashflow":       "잉여현금흐름(FCF) = 영업현금흐름 - CAPEX. 단위: 달러(USD)",
            "updated_at":          "최근 갱신 시각",
        },
    },

    "us_fundamentals": {
        "description": (
            "미국 주식 펀더멘털 지표 테이블. yfinance에서 수집한 밸류에이션·수익성·성장성 지표를 종목별로 저장합니다. "
            "DAG: 05_us_fundamentals_weekly (매주 토요일). "
            "PRIMARY KEY: ticker."
        ),
        "columns": {
            "ticker":              "종목코드. stock_info.ticker 참조 (FK). 예: AAPL, NVDA",
            "trailing_pe":         "후행 PER(Trailing PE). 과거 12개월 실적 기준. 단위: 배수(x)",
            "forward_pe":          "선행 PER(Forward PE). 향후 12개월 예상 이익 기준. 단위: 배수(x)",
            "price_to_book":       "PBR(주가순자산비율). 단위: 배수(x)",
            "ev_to_ebitda":        "EV/EBITDA. 기업가치 ÷ EBITDA. 단위: 배수(x)",
            "peg_ratio":           "PEG Ratio = PER ÷ 이익성장률. 1.0 이하: 성장 대비 저평가",
            "beta":                "베타계수. 시장 대비 변동성 민감도. 1.0=시장과 동일",
            "target_mean_price":   "애널리스트 평균 목표주가. 단위: 달러(USD)",
            "target_high_price":   "애널리스트 최고 목표주가. 단위: 달러(USD)",
            "target_low_price":    "애널리스트 최저 목표주가. 단위: 달러(USD)",
            "recommendation_mean": "애널리스트 평균 투자의견. 1.0(Strong Buy)~5.0(Sell). ⚠️ 한국 rating과 방향 반대",
            "analyst_count":       "투자의견 제시 애널리스트 수",
            "operating_margin":    "영업이익률 = 영업이익 ÷ 매출액. 소수 형태(0.25 = 25%)",
            "profit_margin":       "순이익률 = 당기순이익 ÷ 매출액. 소수 형태",
            "return_on_equity":    "ROE(자기자본이익률). 소수 형태",
            "return_on_assets":    "ROA(총자산이익률). 소수 형태",
            "revenue_growth":      "매출성장률(전년 동기 대비). 소수 형태(0.15 = 15% 성장)",
            "earnings_growth":     "이익성장률(전년 동기 대비). 소수 형태",
            "market_cap":          "시가총액. 단위: 달러(USD)",
            "total_revenue":       "최근 12개월 총매출액. 단위: 달러(USD)",
            "total_debt":          "총차입금. 단위: 달러(USD)",
            "total_cash":          "현금및현금성자산. 단위: 달러(USD)",
            "free_cashflow":       "잉여현금흐름(FCF). 단위: 달러(USD)",
            "trailing_eps":        "후행 EPS. 과거 12개월 실적 기준 주당순이익. 단위: 달러(USD)",
            "forward_eps":         "선행 EPS. 향후 12개월 예상 주당순이익. 단위: 달러(USD)",
            "updated_at":          "최근 갱신 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 사용자 / 포트폴리오 거래
    # ──────────────────────────────────────────────────────────
    "users": {
        "description": (
            "사용자 계정 테이블. BIP 서비스에 가입한 사용자 정보를 저장합니다. "
            "Google OAuth 등 소셜 로그인으로 가입. portfolio 테이블과 1:N 관계."
        ),
        "columns": {
            "id":           "자동 증가 기본키",
            "email":        "사용자 이메일 (고유값, 로그인 식별자)",
            "name":         "사용자 이름",
            "picture":      "프로필 사진 URL",
            "organization": "소속 조직명",
            "phone":        "연락처",
            "timezone":     "사용자 타임존. 예: Asia/Seoul",
            "locale":       "언어/지역 설정. 예: ko-KR",
            "created_at":   "계정 생성 시각",
            "updated_at":   "최근 정보 수정 시각",
        },
    },

    "user_watchlist": {
        "description": (
            "사용자 관심종목(위시리스트) 테이블. 사용자가 즐겨찾기한 종목 목록과 순서를 저장합니다. "
            "UNIQUE(user_id, ticker)."
        ),
        "columns": {
            "id":         "자동 증가 기본키",
            "user_id":    "사용자 ID. users.id 참조 (FK)",
            "ticker":     "관심 종목코드. stock_info.ticker 참조 (FK)",
            "position":   "목록 내 표시 순서 (1부터 시작)",
            "note":       "사용자 메모 (선택)",
            "created_at": "관심종목 추가 시각",
            "updated_at": "최근 수정 시각",
        },
    },

    "transaction": {
        "description": (
            "매매 거래 내역 테이블. 포트폴리오 내 주식 매수·매도 거래를 기록합니다. "
            "KIS API 연동 또는 수동 입력. UNIQUE 제약 없음 (동일 종목 복수 거래 가능)."
        ),
        "columns": {
            "id":            "자동 증가 기본키",
            "portfolio_id":  "포트폴리오 ID. portfolio.id 참조 (FK)",
            "ticker":        "종목코드. stock_info.ticker 참조 (FK)",
            "type":          "거래 유형. 값: buy(매수), sell(매도)",
            "quantity":      "거래 수량. 단위: 주(株)",
            "price":         "거래 단가. 단위: 통화별 (원/달러)",
            "fee":           "수수료. 단위: 통화별",
            "tax":           "세금(거래세 등). 단위: 통화별",
            "currency":      "통화 구분. 값: KRW, USD",
            "exchange_rate": "거래 시점 원/달러 환율 (해외주식 거래 시)",
            "traded_at":     "실제 체결 일시",
            "memo":          "거래 메모 (선택)",
            "external_id":   "KIS API 거래 고유번호 (외부 시스템 연동용)",
            "created_at":    "레코드 생성 시각",
        },
    },

    "cash_transaction": {
        "description": (
            "현금 거래 내역 테이블. 포트폴리오 계좌의 입금·출금·환전 내역을 기록합니다. "
            "예수금 변동 추적 및 수익률 계산의 기초 데이터."
        ),
        "columns": {
            "id":            "자동 증가 기본키",
            "portfolio_id":  "포트폴리오 ID. portfolio.id 참조 (FK)",
            "type":          "거래 유형. 값: deposit(입금), withdrawal(출금), exchange(환전)",
            "amount":        "거래 금액. 양수=입금, 음수=출금. 단위: 통화별",
            "currency":      "통화 구분. 값: KRW, USD",
            "exchange_rate": "환전 시 적용 환율 (환전 거래에만 해당)",
            "transacted_at": "실제 거래 일시",
            "memo":          "거래 메모 (선택)",
            "created_at":    "레코드 생성 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 뉴스 (GDELT 기반)
    # ──────────────────────────────────────────────────────────
    "news_raw": {
        "description": (
            "GDELT 뉴스 원본 데이터 테이블. GDELT(Global Database of Events, Language, and Tone)에서 "
            "수집한 원본 뉴스 메타데이터를 저장합니다. news_article 테이블의 소스 데이터."
        ),
        "columns": {
            "id":              "자동 증가 기본키",
            "url":             "기사 원문 URL (고유값)",
            "source":          "뉴스 출처 매체명",
            "collection_date": "GDELT에서 수집한 날짜",
            "published_date":  "기사 발행 날짜",
            "themes":          "GDELT 테마 태그 목록 (세미콜론 구분, 예: ECON_STOCKMARKET;ENV_CLIMATECHANGE)",
            "organizations":   "기사에 등장하는 조직명 목록 (GDELT 추출)",
            "locations":       "기사에 등장하는 지명 목록 (GDELT 추출)",
            "tone_raw":        "GDELT 감성 점수 원본 문자열 (tone,positive,negative,... 형태)",
            "created_at":      "레코드 수집 시각",
        },
    },

    "news_article": {
        "description": (
            "뉴스 기사 분류 테이블. news_raw에서 가공하여 스마트폰 수요예측 관련 기사를 "
            "유형(news_type)·팩터(factor)·지역별로 분류 저장합니다. "
            "DAG: GDELT 스마트폰 수요 분석 파이프라인."
        ),
        "columns": {
            "id":             "자동 증가 기본키",
            "raw_id":         "원본 news_raw.id 참조 (FK)",
            "url":            "기사 원문 URL",
            "source":         "뉴스 출처 매체명",
            "title":          "기사 제목",
            "published_date": "기사 발행 날짜",
            "news_type":      "기사 유형 분류. ENUM: demand(수요), supply(공급), macro(거시경제) 등",
            "brands":         "관련 브랜드 목록. 예: ['Apple', 'Samsung']",
            "factor":         "수요 팩터 분류. ENUM: consumer_confidence, launch, promotion, etc.",
            "regions":        "관련 지역 목록. 예: ['North America', 'Asia Pacific']",
            "country_codes":  "관련 국가 코드 목록. ISO 2자리. 예: ['US', 'KR', 'CN']",
            "tone_score":     "감성 점수. 양수=긍정, 음수=부정. GDELT tone 기반",
            "created_at":     "레코드 생성 시각",
            "updated_at":     "최근 갱신 시각",
        },
    },

    "news_daily_summary": {
        "description": (
            "일별 뉴스 감성 요약 테이블. news_article을 날짜·지역별로 집계한 요약 통계. "
            "스마트폰 수요예측 팩터별 기사 수·평균 감성을 일별로 집계합니다. "
            "UNIQUE(summary_date, region)."
        ),
        "columns": {
            "id":                    "자동 증가 기본키",
            "summary_date":          "집계 기준 날짜",
            "region":                "지역 구분. ENUM: North America, Asia Pacific, Europe, etc.",
            "smartphone_count":      "스마트폰 관련 기사 수",
            "smartphone_avg_tone":   "스마트폰 관련 기사 평균 감성 점수",
            "geopolitics_count":     "지정학 관련 기사 수",
            "geopolitics_avg_tone":  "지정학 관련 기사 평균 감성",
            "economy_count":         "경제 관련 기사 수",
            "economy_avg_tone":      "경제 관련 기사 평균 감성",
            "supply_chain_count":    "공급망 관련 기사 수",
            "supply_chain_avg_tone": "공급망 관련 기사 평균 감성",
            "regulation_count":      "규제 관련 기사 수",
            "regulation_avg_tone":   "규제 관련 기사 평균 감성",
            "disaster_count":        "재해·재난 관련 기사 수",
            "disaster_avg_tone":     "재해·재난 관련 기사 평균 감성",
            "created_at":            "레코드 생성 시각",
        },
    },

    # ──────────────────────────────────────────────────────────
    # 제품 (스마트폰 수요예측)
    # ──────────────────────────────────────────────────────────
    "product_price": {
        "description": (
            "스마트폰 제품 가격 테이블. 애플·삼성 등 주요 브랜드의 스마트폰 모델별 지역·날짜별 가격을 저장합니다. "
            "반도체 수요예측 모델의 입력 팩터로 활용. "
            "UNIQUE(brand, product_name, price_date, region)."
        ),
        "columns": {
            "id":           "자동 증가 기본키",
            "product_id":   "제품 ID (product_release.id 참조)",
            "brand":        "브랜드명. 예: Apple, Samsung",
            "product_name": "제품명. 예: iPhone 16 Pro, Galaxy S25 Ultra",
            "price_date":   "가격 기준 날짜",
            "region":       "판매 지역. ENUM: North America, Asia Pacific, Europe, etc.",
            "price_usd":    "달러(USD) 환산 가격",
            "price_local":  "현지 통화 가격",
            "currency":     "현지 통화 코드. 예: KRW, JPY, EUR",
            "price_type":   "가격 유형. 예: retail(소비자가), launch(출시가)",
            "created_at":   "레코드 수집 시각",
        },
    },

    "product_release": {
        "description": (
            "스마트폰 제품 출시 일정 테이블. 주요 브랜드의 신제품 발표·출시 일정을 저장합니다. "
            "반도체 수요예측에서 출시 이벤트 팩터로 활용."
        ),
        "columns": {
            "id":            "자동 증가 기본키",
            "brand":         "브랜드명. 예: Apple, Samsung",
            "product_name":  "제품명. 예: iPhone 17, Galaxy S26",
            "segment":       "제품 세그먼트. ENUM: flagship(플래그십), mid-range(중급), budget(보급)",
            "announce_date": "제품 발표 날짜",
            "release_date":  "실제 출시(판매 시작) 날짜",
            "regions":       "출시 지역 목록. 예: ['Global', 'North America', 'Korea']",
            "created_at":    "레코드 수집 시각",
        },
    },
}


# ─── API 유틸리티 ────────────────────────────────────────────────────────────────

def get_headers():
    if not OM_BOT_TOKEN:
        print("❌ OM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {OM_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


# ─── 컬럼 → Glossary Term 매핑 ───────────────────────────────────────────────
#
# 형식: { "table.column": ["glossary_term_fqn", ...] }
# OM session consolidation 버그로 인해 description과 tag ops를 단일 PATCH로 보내야 함
#
COLUMN_TERM_MAP = {
    # stock_info
    "stock_info.market_value":              ["investment-terms.price.market-cap"],
    "stock_info.per":                       ["investment-terms.valuation.per"],
    "stock_info.pbr":                       ["investment-terms.valuation.pbr"],
    "stock_info.eps":                       ["investment-terms.valuation.eps"],
    "stock_info.target_price":              ["investment-terms.consensus.target-price"],
    "stock_info.foreign_ownership_pct":     ["investment-terms.price.foreign-ownership"],  # 수정: trading-volume→foreign-ownership
    # stock_price_1d
    "stock_price_1d.open":            ["investment-terms.price.ohlcv"],
    "stock_price_1d.high":            ["investment-terms.price.ohlcv"],
    "stock_price_1d.low":             ["investment-terms.price.ohlcv"],
    "stock_price_1d.close":           ["investment-terms.price.close-price", "investment-terms.price.ohlcv"],
    "stock_price_1d.volume":                ["investment-terms.price.trading-volume", "investment-terms.price.ohlcv"],
    "stock_price_1d.foreign_buy_volume":    ["investment-terms.price.investor-trend"],
    "stock_price_1d.institution_buy_volume": ["investment-terms.price.investor-trend"],
    "stock_price_1d.individual_buy_volume": ["investment-terms.price.investor-trend"],
    "stock_price_1d.foreign_ownership_pct": ["investment-terms.price.foreign-ownership"],
    "stock_price_1m.close":           ["investment-terms.price.close-price"],
    "stock_price_1m.volume":          ["investment-terms.price.trading-volume"],
    # stock_indicators
    "stock_indicators.open":          ["investment-terms.price.ohlcv"],
    "stock_indicators.high":          ["investment-terms.price.ohlcv"],
    "stock_indicators.low":           ["investment-terms.price.ohlcv"],
    "stock_indicators.close":         ["investment-terms.price.close-price", "investment-terms.price.ohlcv"],
    "stock_indicators.volume":        ["investment-terms.price.trading-volume", "investment-terms.price.ohlcv"],
    "stock_indicators.ma5":           ["investment-terms.technical.moving-average"],
    "stock_indicators.ma10":          ["investment-terms.technical.moving-average"],
    "stock_indicators.ma20":          ["investment-terms.technical.moving-average"],
    "stock_indicators.ma60":          ["investment-terms.technical.moving-average"],
    "stock_indicators.ma120":         ["investment-terms.technical.moving-average"],
    "stock_indicators.ma200":         ["investment-terms.technical.moving-average"],
    "stock_indicators.ema12":         ["investment-terms.technical.ema"],
    "stock_indicators.ema26":         ["investment-terms.technical.ema"],
    "stock_indicators.macd":          ["investment-terms.technical.macd", "investment-terms.technical.macd-components"],
    "stock_indicators.macd_signal":   ["investment-terms.technical.macd-components"],
    "stock_indicators.macd_hist":     ["investment-terms.technical.macd-components"],
    "stock_indicators.rsi14":         ["investment-terms.technical.rsi"],
    "stock_indicators.bb_upper":      ["investment-terms.technical.bollinger-band"],
    "stock_indicators.bb_middle":     ["investment-terms.technical.bollinger-band"],
    "stock_indicators.bb_lower":      ["investment-terms.technical.bollinger-band"],
    "stock_indicators.bb_width":      ["investment-terms.technical.bb-indicators"],
    "stock_indicators.bb_pctb":       ["investment-terms.technical.bb-indicators"],
    "stock_indicators.stoch_k":       ["investment-terms.technical.stochastic"],
    "stock_indicators.stoch_d":       ["investment-terms.technical.stochastic"],
    "stock_indicators.atr14":         ["investment-terms.technical.atr"],
    "stock_indicators.golden_cross":  ["investment-terms.technical.golden-cross"],
    "stock_indicators.death_cross":   ["investment-terms.technical.death-cross"],
    "stock_indicators.high_52w":      ["investment-terms.technical.52w-high-low"],
    "stock_indicators.low_52w":       ["investment-terms.technical.52w-high-low"],
    "stock_indicators.pct_from_52w_high": ["investment-terms.technical.52w-high-low"],
    "stock_indicators.pct_from_52w_low":  ["investment-terms.technical.52w-high-low"],
    # financial_statements
    "financial_statements.revenue":            ["investment-terms.financial.revenue"],
    "financial_statements.operating_profit":   ["investment-terms.financial.operating-profit"],
    "financial_statements.net_income":         ["investment-terms.financial.net-income"],
    "financial_statements.total_assets":       ["investment-terms.financial.total-assets"],
    "financial_statements.total_equity":       ["investment-terms.financial.total-equity"],
    "financial_statements.cash_from_operating": ["investment-terms.financial.operating-cashflow"],
    # us_fundamentals
    "us_fundamentals.trailing_pe":       ["investment-terms.valuation.trailing-forward-pe"],
    "us_fundamentals.forward_pe":        ["investment-terms.valuation.trailing-forward-pe"],
    "us_fundamentals.price_to_book":     ["investment-terms.valuation.pbr"],
    "us_fundamentals.ev_to_ebitda":      ["investment-terms.valuation.ev-ebitda"],
    "us_fundamentals.peg_ratio":         ["investment-terms.valuation.peg-ratio"],
    "us_fundamentals.beta":              ["investment-terms.valuation.beta"],
    "us_fundamentals.return_on_equity":  ["investment-terms.valuation.roe"],
    "us_fundamentals.market_cap":        ["investment-terms.price.market-cap"],
    "us_fundamentals.free_cashflow":     ["investment-terms.financial.fcf"],
    # consensus_estimates
    "consensus_estimates.rating":        ["investment-terms.consensus.analyst-rating"],
    "consensus_estimates.target_price":  ["investment-terms.consensus.target-price"],
    "consensus_estimates.est_eps":       ["investment-terms.valuation.eps"],
    "consensus_estimates.est_per":       ["investment-terms.valuation.per"],
    "consensus_estimates.est_pbr":       ["investment-terms.valuation.pbr"],
    "consensus_estimates.est_roe":       ["investment-terms.valuation.roe"],
    # consensus_history
    "consensus_history.rating":          ["investment-terms.consensus.analyst-rating"],
    "consensus_history.target_price":    ["investment-terms.consensus.target-price"],
    "consensus_history.est_eps":         ["investment-terms.valuation.eps"],
    "consensus_history.est_per":         ["investment-terms.valuation.per"],
    # company_dividend
    "company_dividend.dividend_yield":          ["investment-terms.valuation.dividend-yield"],
    "company_dividend.cash_dividend_per_share": ["investment-terms.valuation.dps"],  # 수정: eps→dps
    # holding
    "holding.market_value":              ["investment-terms.price.market-cap"],
    "holding.pnl_amount":                ["investment-terms.price.pnl"],
    "holding.pnl_percent":               ["investment-terms.price.pnl"],
    # portfolio_snapshot
    "portfolio_snapshot.daily_pnl":      ["investment-terms.price.pnl"],
    "portfolio_snapshot.daily_pnl_pct":  ["investment-terms.price.pnl"],
    "portfolio_snapshot.total_pnl":      ["investment-terms.price.pnl"],
    "portfolio_snapshot.total_pnl_pct":  ["investment-terms.price.pnl"],
    # market_daily_summary
    "market_daily_summary.advancing":           ["investment-terms.market.advance-decline"],
    "market_daily_summary.declining":           ["investment-terms.market.advance-decline"],
    "market_daily_summary.advance_decline_ratio": ["investment-terms.market.advance-decline"],
    "market_daily_summary.new_high_52w":        ["investment-terms.technical.52w-high-low"],
    "market_daily_summary.new_low_52w":         ["investment-terms.technical.52w-high-low"],
    "market_daily_summary.above_ma20":          ["investment-terms.technical.moving-average"],
    "market_daily_summary.above_ma200":         ["investment-terms.technical.moving-average"],
    "market_daily_summary.avg_atr_pct":         ["investment-terms.technical.atr"],
    "market_daily_summary.rsi_oversold":        ["investment-terms.technical.rsi"],
    "market_daily_summary.rsi_overbought":      ["investment-terms.technical.rsi"],
    "market_daily_summary.pct_above_ma20":      ["investment-terms.market.pct-above-ma"],
    "market_daily_summary.pct_above_ma200":     ["investment-terms.market.pct-above-ma"],
    "market_daily_summary.avg_volume_ratio":    ["investment-terms.technical.volume-ratio"],
    "market_daily_summary.total_volume":        ["investment-terms.price.trading-volume"],
    # stock_info 추가
    "stock_info.par_value":              ["investment-terms.price.par-value"],
    "stock_info.total_shares":           ["investment-terms.financial.shares-outstanding"],
    # stock_price_1d 시간외
    "stock_price_1d.after_hours_close":       ["investment-terms.price.after-hours"],
    "stock_price_1d.after_hours_change_pct":  ["investment-terms.price.after-hours"],
    # stock_indicators 거래량
    "stock_indicators.volume_ratio":     ["investment-terms.technical.volume-ratio"],
    "stock_indicators.volume_ma20":      ["investment-terms.technical.moving-average"],
    # financial_statements 추가
    "financial_statements.gross_profit":        ["investment-terms.financial.gross-profit"],
    "financial_statements.cost_of_sales":       ["investment-terms.financial.cost-of-sales"],
    "financial_statements.total_liabilities":   ["investment-terms.financial.total-liabilities"],
    "financial_statements.cash_from_investing": ["investment-terms.financial.investing-cashflow"],
    "financial_statements.cash_from_financing": ["investment-terms.financial.financing-cashflow"],
    "financial_statements.shares_outstanding":  ["investment-terms.financial.shares-outstanding"],
    # us_financial_statements 추가
    "us_financial_statements.revenue":          ["investment-terms.financial.revenue"],
    "us_financial_statements.operating_income": ["investment-terms.financial.operating-profit"],
    "us_financial_statements.net_income":       ["investment-terms.financial.net-income"],
    "us_financial_statements.total_assets":     ["investment-terms.financial.total-assets"],
    "us_financial_statements.total_equity":     ["investment-terms.financial.total-equity"],
    "us_financial_statements.ebitda":           ["investment-terms.financial.ebitda"],
    "us_financial_statements.free_cashflow":    ["investment-terms.financial.fcf"],
    "us_financial_statements.operating_cashflow": ["investment-terms.financial.operating-cashflow"],
    "us_financial_statements.gross_profit":     ["investment-terms.financial.gross-profit"],
    "us_financial_statements.total_liabilities": ["investment-terms.financial.total-liabilities"],
    "us_financial_statements.total_debt":       ["investment-terms.financial.total-debt"],
    "us_financial_statements.total_cash":       ["investment-terms.financial.total-cash"],
    # us_fundamentals 추가
    "us_fundamentals.trailing_pe":       ["investment-terms.valuation.trailing-forward-pe"],
    "us_fundamentals.forward_pe":        ["investment-terms.valuation.trailing-forward-pe"],
    "us_fundamentals.trailing_eps":      ["investment-terms.valuation.eps"],
    "us_fundamentals.forward_eps":       ["investment-terms.valuation.eps"],
    "us_fundamentals.price_to_book":     ["investment-terms.valuation.pbr"],
    "us_fundamentals.ev_to_ebitda":      ["investment-terms.valuation.ev-ebitda"],
    "us_fundamentals.peg_ratio":         ["investment-terms.valuation.peg-ratio"],
    "us_fundamentals.beta":              ["investment-terms.valuation.beta"],
    "us_fundamentals.return_on_equity":  ["investment-terms.valuation.roe"],
    "us_fundamentals.return_on_assets":  ["investment-terms.valuation.roa"],
    "us_fundamentals.operating_margin":  ["investment-terms.valuation.operating-margin"],
    "us_fundamentals.profit_margin":     ["investment-terms.valuation.profit-margin"],
    "us_fundamentals.revenue_growth":    ["investment-terms.valuation.revenue-growth"],
    "us_fundamentals.earnings_growth":   ["investment-terms.valuation.earnings-growth"],
    "us_fundamentals.total_debt":        ["investment-terms.financial.total-debt"],
    "us_fundamentals.total_cash":        ["investment-terms.financial.total-cash"],
    "us_fundamentals.market_cap":        ["investment-terms.price.market-cap"],
    "us_fundamentals.free_cashflow":     ["investment-terms.financial.fcf"],
    "us_fundamentals.recommendation_mean": ["investment-terms.consensus.recommendation-mean"],
    # company_dividend 추가
    "company_dividend.payout_ratio":     ["investment-terms.financial.payout-ratio"],
    # consensus_estimates 추가
    "consensus_estimates.est_revenue":          ["investment-terms.financial.revenue"],
    "consensus_estimates.est_operating_profit": ["investment-terms.financial.operating-profit"],
    "consensus_estimates.est_net_income":       ["investment-terms.financial.net-income"],
    # consensus_history 추가
    "consensus_history.est_pbr":         ["investment-terms.valuation.pbr"],
    "consensus_history.est_roe":         ["investment-terms.valuation.roe"],
}


def get_table(fqn: str, headers: dict) -> dict | None:
    """FQN으로 테이블 정보 (컬럼 포함) 조회"""
    url = f"{OM_HOST}/api/v1/tables/name/{fqn}"
    resp = requests.get(url, headers=headers, params={"fields": "columns"}, timeout=10)
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        return None
    print(f"  ⚠️  GET {fqn} 실패: {resp.status_code} {resp.text[:200]}")
    return None


def patch_table(table_id: str, ops: list, headers: dict) -> bool:
    """JSON Patch로 테이블 메타데이터 업데이트"""
    patch_headers = {**headers, "Content-Type": "application/json-patch+json"}
    url = f"{OM_HOST}/api/v1/tables/{table_id}"
    resp = requests.patch(url, headers=patch_headers, data=json.dumps(ops), timeout=10)
    return resp.status_code in (200, 201)


# ─── 메인 로직 ───────────────────────────────────────────────────────────────────

def enrich_table(table_name: str, meta: dict, headers: dict, dry_run: bool) -> dict:
    """단일 테이블의 설명·컬럼 설명을 OM에 등록"""
    fqn = f"{OM_SERVICE_DB}.{OM_DB_NAME}.{OM_DB_SCHEMA}.{table_name}"

    table_data = get_table(fqn, headers) if not dry_run else {"id": "dry-run", "columns": []}
    if table_data is None:
        print(f"  ⚠️  OM에서 테이블을 찾을 수 없음: {fqn}")
        return {"table": table_name, "status": "not_found"}

    ops = []

    # 테이블 설명
    table_desc = meta.get("description", "")
    if table_desc:
        ops.append({"op": "add", "path": "/description", "value": table_desc})

    # 컬럼 설명 (인덱스 기반)
    col_descriptions = meta.get("columns", {})
    columns = table_data.get("columns", [])
    col_index_map = {col["name"]: idx for idx, col in enumerate(columns)}

    matched_cols = 0
    unmatched_cols = []
    for col_name, col_desc in col_descriptions.items():
        if col_name in col_index_map:
            idx = col_index_map[col_name]
            ops.append({
                "op": "add",
                "path": f"/columns/{idx}/description",
                "value": col_desc,
            })
            matched_cols += 1
        else:
            unmatched_cols.append(col_name)

    # Glossary Term 태그 ops (description과 동일 PATCH에 포함 - session consolidation 버그 우회)
    col_existing_tags = {col["name"]: col.get("tags", []) for col in columns}
    tag_count = 0
    for key, term_fqns in COLUMN_TERM_MAP.items():
        t_name, c_name = key.split(".", 1)
        if t_name != table_name:
            continue
        if c_name not in col_index_map:
            continue
        idx = col_index_map[c_name]
        existing_fqns = {t["tagFQN"] for t in col_existing_tags.get(c_name, [])}
        new_fqns = [f for f in term_fqns if f not in existing_fqns]
        for i, fqn in enumerate(new_fqns):
            tag_idx = len(col_existing_tags.get(c_name, [])) + i
            ops.append({
                "op": "add",
                "path": f"/columns/{idx}/tags/{tag_idx}",
                "value": {"tagFQN": fqn, "source": "Glossary", "labelType": "Manual", "state": "Confirmed"},
            })
            tag_count += 1

    if dry_run:
        print(f"  [dry-run] {table_name}: {len(ops)} 패치 작업")
        print(f"    테이블 설명: {table_desc[:60]}{'...' if len(table_desc) > 60 else ''}")
        print(f"    컬럼 매핑: {matched_cols}/{len(col_descriptions)}개 매치")
        if unmatched_cols:
            print(f"    ⚠️  미매칭 컬럼: {unmatched_cols}")
        return {"table": table_name, "status": "dry_run", "ops": len(ops)}

    if not ops:
        print(f"  ⏭️  {table_name}: 업데이트할 내용 없음")
        return {"table": table_name, "status": "skipped"}

    success = patch_table(table_data["id"], ops, headers)
    if success:
        msg = f"  ✅ {table_name}: 테이블 설명 + {matched_cols}개 컬럼 설명 + {tag_count}개 태그 등록"
        if unmatched_cols:
            msg += f" (미매칭 컬럼: {unmatched_cols})"
        print(msg)
        return {"table": table_name, "status": "success", "cols_updated": matched_cols}
    else:
        print(f"  ❌ {table_name}: PATCH 실패")
        return {"table": table_name, "status": "error"}


def main():
    parser = argparse.ArgumentParser(description="OpenMetadata 테이블/컬럼 설명 일괄 등록")
    parser.add_argument("--dry-run", action="store_true", help="실제 API 호출 없이 내용만 출력")
    parser.add_argument("--table", help="특정 테이블만 처리")
    args = parser.parse_args()

    headers = get_headers()

    tables_to_process = TABLE_METADATA
    if args.table:
        if args.table not in TABLE_METADATA:
            print(f"❌ '{args.table}'는 TABLE_METADATA에 정의되지 않은 테이블입니다.")
            print(f"정의된 테이블 목록: {', '.join(TABLE_METADATA.keys())}")
            sys.exit(1)
        tables_to_process = {args.table: TABLE_METADATA[args.table]}

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"\n{'='*60}")
    print(f"OpenMetadata 메타데이터 일괄 등록 ({mode})")
    print(f"대상: {OM_HOST} / {OM_SERVICE_DB}.{OM_DB_NAME}.{OM_DB_SCHEMA}")
    print(f"처리 테이블: {len(tables_to_process)}개")
    print(f"{'='*60}\n")

    results = []
    for table_name, meta in tables_to_process.items():
        print(f"▶ {table_name}")
        result = enrich_table(table_name, meta, headers, dry_run=args.dry_run)
        results.append(result)

    print(f"\n{'='*60}")
    success = sum(1 for r in results if r["status"] in ("success", "dry_run"))
    not_found = sum(1 for r in results if r["status"] == "not_found")
    errors = sum(1 for r in results if r["status"] == "error")
    print(f"완료: {success}개 성공 / {not_found}개 미발견 / {errors}개 오류")
    if not_found > 0:
        missing = [r["table"] for r in results if r["status"] == "not_found"]
        print(f"미발견 테이블 (OM에 아직 수집되지 않은 테이블): {missing}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
