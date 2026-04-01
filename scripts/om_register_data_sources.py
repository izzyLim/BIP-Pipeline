"""
OpenMetadata 외부 데이터 소스 등록 스크립트
============================================================
BIP-Pipeline에서 사용하는 외부 API/스크래핑 소스를 OM에 등록하고
apiEndpoint → DAG pipeline 리니지 엣지를 생성합니다.

OM 엔티티 구조:
    apiService (서비스 컨테이너)
      └─ apiCollection (API 그룹)
           └─ apiEndpoint (개별 엔드포인트) ← 이것이 lineage에 표시됨

전체 리니지 체인:
    apiEndpoint → pipeline (DAG) → table (stockdb) → consumer pipeline

사용법:
    OM_HOST=http://localhost:8585 OM_BOT_TOKEN=<jwt> python scripts/om_register_data_sources.py
    python scripts/om_register_data_sources.py --dry-run

환경변수:
    OM_HOST        : OpenMetadata 서버 주소 (기본값: http://openmetadata-server:8585)
    OM_BOT_TOKEN   : ingestion-bot JWT 토큰
"""

import argparse
import os
import sys

import requests

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
OM_HOST = os.getenv("OM_HOST", "http://openmetadata-server:8585")
OM_BOT_TOKEN = os.getenv("OM_BOT_TOKEN", "")
OM_SERVICE_PIPELINE = os.getenv("OM_SERVICE_PIPELINE", "bip-airflow")


def get_headers():
    if not OM_BOT_TOKEN:
        print("OM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {OM_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


# ─────────────────────────────────────────────
# 외부 데이터 소스 정의
# ─────────────────────────────────────────────
# 구조: apiService > apiCollection > apiEndpoint(들) → pipeline(들)

DATA_SOURCES = [
    {
        "service_name": "yahoo-finance",
        "service_display": "Yahoo Finance (yfinance)",
        "service_desc": "미국 주식 시세 및 기업정보. yfinance 라이브러리로 수집.",
        "endpoints": [
            {
                "name": "stock-ohlcv",
                "displayName": "US Stock OHLCV",
                "description": "미국 주식 일봉 시세 (OHLCV) 수집",
                "url": "https://query1.finance.yahoo.com/v8/finance/chart",
                "method": "GET",
                "pipelines": [
                    "02_price_us_ohlcv_daily",
                    "02_price_us_historical_manual",
                    "02_price_1m_historical_manual",
                ],
            },
            {
                "name": "stock-fundamentals",
                "displayName": "US Stock Fundamentals",
                "description": "미국 기업 재무/기본정보 (PER, PBR, 시총 등)",
                "url": "https://query1.finance.yahoo.com/v10/finance/quoteSummary",
                "method": "GET",
                "pipelines": [
                    "05_us_fundamentals_weekly",
                    "01_info_nasdaq_stocks_daily",
                    "01_info_nyse_stocks_daily",
                ],
            },
        ],
    },
    {
        "service_name": "naver-finance",
        "service_display": "Naver Finance / WiseReport",
        "service_desc": "한국 주식 시세, 종목 기본정보, 애널리스트 컨센서스. Naver Finance 및 WiseReport 스크래핑.",
        "endpoints": [
            {
                "name": "kr-stock-info",
                "displayName": "KR Stock Info & Price",
                "description": "한국 주식 종목정보 및 시세",
                "url": "https://finance.naver.com/item/main.naver",
                "method": "GET",
                "pipelines": [
                    "01_info_kr_stocks_daily",
                    "01_info_kr_detail_daily",
                    "02_price_kr_ohlcv_daily",
                    "03_price_kr_after_hours",
                ],
            },
            {
                "name": "kr-consensus",
                "displayName": "KR Analyst Consensus",
                "description": "애널리스트 투자의견/목표주가/EPS/PER 컨센서스 (WiseReport)",
                "url": "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx",
                "method": "GET",
                "pipelines": [
                    "05_kr_consensus_weekly",
                    "05_kr_consensus_manual",
                ],
            },
        ],
    },
    {
        "service_name": "dart-api",
        "service_display": "DART API (전자공시시스템)",
        "service_desc": "한국 상장기업 재무제표 (BS/IS/CF), 기업코드. 금융감독원 DART Open API.",
        "endpoints": [
            {
                "name": "financial-statements",
                "displayName": "Financial Statements",
                "description": "재무제표 (재무상태표/손익계산서/현금흐름표)",
                "url": "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                "method": "GET",
                "pipelines": [
                    "05_kr_financial_stmt_weekly",
                    "05_kr_financial_stmt_manual",
                ],
            },
            {
                "name": "company-info",
                "displayName": "Company Info",
                "description": "기업코드, 기본 정보 (업종, 설립일 등)",
                "url": "https://opendart.fss.or.kr/api/company.json",
                "method": "GET",
                "pipelines": [
                    "08_company_info_annual",
                    "08_company_info_manual",
                ],
            },
        ],
    },
    {
        "service_name": "krx-api",
        "service_display": "KRX (한국거래소)",
        "service_desc": "KOSPI/KOSDAQ 섹터 분류 및 시가총액, 거래량 데이터.",
        "endpoints": [
            {
                "name": "sector-data",
                "displayName": "KRX Sector Data",
                "description": "업종별 시세/시가총액/거래량",
                "url": "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                "method": "POST",
                "pipelines": [
                    "05_kr_sectors_daily",
                ],
            },
            {
                "name": "investor-trend",
                "displayName": "KRX Investor Trend",
                "description": "투자자별 매매동향 (개인/외국인/기관)",
                "url": "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                "method": "POST",
                "pipelines": [
                    "05_kr_investor_trend_daily",
                ],
            },
        ],
    },
    {
        "service_name": "ecos-bok-api",
        "service_display": "ECOS BOK API (한국은행)",
        "service_desc": "한국 거시경제 지표 — 기준금리, M2, CPI, 환율, GDP. 한국은행 경제통계시스템(ECOS) Open API.",
        "endpoints": [
            {
                "name": "macro-indicators",
                "displayName": "Macro Indicators",
                "description": "거시경제 지표 (기준금리, CPI, GDP, M2, 환율 등)",
                "url": "https://ecos.bok.or.kr/api/StatisticSearch",
                "method": "GET",
                "pipelines": [
                    "05_kr_ecos_weekly",
                    "05_kr_ecos_manual",
                    "05_kr_rates_daily",
                    "05_kr_rates_manual",
                ],
            },
        ],
    },
    {
        "service_name": "gdelt-api",
        "service_display": "GDELT (Global Database of Events)",
        "service_desc": "전 세계 뉴스 이벤트 데이터베이스. 지정학적 리스크 지수, 톤 지표, 지역별 이벤트 수 집계.",
        "endpoints": [
            {
                "name": "gdelt-events",
                "displayName": "GDELT Events",
                "description": "글로벌 이벤트 데이터 (CAMEO 코드, 톤, GoldsteinScale)",
                "url": "https://api.gdeltproject.org/api/v2/doc/doc",
                "method": "GET",
                "pipelines": [
                    "04_macro_global_hourly",
                    "04_macro_global_manual",
                ],
            },
            {
                "name": "geopolitical-indices",
                "displayName": "Geopolitical Risk Indices",
                "description": "지정학적 리스크 지수 계산용 헤드라인 수집",
                "url": "https://api.gdeltproject.org/api/v2/doc/doc",
                "method": "GET",
                "pipelines": [
                    "04_macro_geopolitical_weekly",
                    "04_macro_risk_daily",
                ],
            },
        ],
    },
    {
        "service_name": "kis-api",
        "service_display": "KIS API (한국투자증권)",
        "service_desc": "포트폴리오 보유 종목 현황, 평가금액, 손익. 한국투자증권 Open Trading API.",
        "endpoints": [
            {
                "name": "portfolio-snapshot",
                "displayName": "Portfolio Snapshot",
                "description": "보유 종목/평가금액/수익률 스냅샷",
                "url": "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/trading/inquire-balance",
                "method": "GET",
                "pipelines": [
                    "07_portfolio_snapshot_daily",
                ],
            },
        ],
    },
    {
        "service_name": "naver-news-api",
        "service_display": "Naver News API",
        "service_desc": "한국 주식/경제 뉴스 수집. Naver Search API (뉴스 검색) 및 RSS 피드.",
        "endpoints": [
            {
                "name": "news-search",
                "displayName": "News Search API",
                "description": "뉴스 키워드 검색 (Naver Search API v1)",
                "url": "https://openapi.naver.com/v1/search/news.json",
                "method": "GET",
                "pipelines": [
                    "06_news_naver_api_daily",
                    "06_news_naver_scrape_daily",
                    "06_news_sentiment_daily",
                ],
            },
        ],
    },
    {
        "service_name": "semiconductor-market",
        "service_display": "반도체 시장 가격 (DRAM/NAND)",
        "service_desc": "DRAM, NAND 플래시 현물/계약 가격. DRAMeXchange / TrendForce 공개 데이터.",
        "endpoints": [
            {
                "name": "dram-nand-prices",
                "displayName": "DRAM/NAND Spot Prices",
                "description": "DRAM/NAND 현물 및 계약 가격",
                "url": "https://www.dramexchange.com",
                "method": "GET",
                "pipelines": [
                    "04_macro_semiconductor_daily",
                ],
            },
        ],
    },
]


# ─────────────────────────────────────────────
# OM API 함수
# ─────────────────────────────────────────────

def upsert_api_service(name: str, display: str, desc: str, headers: dict) -> str | None:
    resp = requests.put(
        f"{OM_HOST}/api/v1/services/apiServices",
        headers=headers,
        json={
            "name": name,
            "displayName": display,
            "description": desc,
            "serviceType": "Rest",
            "connection": {"config": {"type": "Rest"}},
        },
        timeout=15,
    )
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    print(f"    apiService 생성 실패: {name} — {resp.status_code} {resp.text[:200]}")
    return None


def upsert_api_collection(svc_name: str, headers: dict) -> str | None:
    col_name = "apis"
    resp = requests.put(
        f"{OM_HOST}/api/v1/apiCollections",
        headers=headers,
        json={
            "name": col_name,
            "displayName": f"{svc_name} APIs",
            "description": f"{svc_name} API collection",
            "service": svc_name,
        },
        timeout=15,
    )
    if resp.status_code in (200, 201):
        return resp.json().get("fullyQualifiedName")
    print(f"    apiCollection 생성 실패: {svc_name}.{col_name} — {resp.status_code} {resp.text[:200]}")
    return None


def upsert_api_endpoint(ep: dict, collection_fqn: str, headers: dict) -> str | None:
    resp = requests.put(
        f"{OM_HOST}/api/v1/apiEndpoints",
        headers=headers,
        json={
            "name": ep["name"],
            "displayName": ep["displayName"],
            "description": ep["description"],
            "endpointURL": ep["url"],
            "requestMethod": ep["method"],
            "apiCollection": collection_fqn,
        },
        timeout=15,
    )
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    print(f"    apiEndpoint 생성 실패: {ep['name']} — {resp.status_code} {resp.text[:200]}")
    return None


def get_pipeline_id(dag_id: str, headers: dict) -> str | None:
    fqn = f"{OM_SERVICE_PIPELINE}.{dag_id}"
    try:
        resp = requests.get(
            f"{OM_HOST}/api/v1/pipelines/name/{fqn}",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("id")
    except Exception:
        pass
    return None


def create_lineage(from_id: str, from_type: str, to_id: str, to_type: str, headers: dict) -> bool:
    try:
        resp = requests.put(
            f"{OM_HOST}/api/v1/lineage",
            headers=headers,
            json={
                "edge": {
                    "fromEntity": {"id": from_id, "type": from_type},
                    "toEntity":   {"id": to_id,   "type": to_type},
                }
            },
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def main(dry_run: bool = False):
    headers = None if dry_run else get_headers()

    stats = {"services": 0, "endpoints": 0, "edges": 0}
    skipped = []

    print(f"\n{'=' * 60}")
    print(f"BIP-Pipeline 외부 데이터 소스 OM 등록")
    print(f"OM_HOST: {OM_HOST}")
    print(f"DRY-RUN: {dry_run}")
    print(f"{'=' * 60}\n")

    for src in DATA_SOURCES:
        svc_name = src["service_name"]
        print(f"[{svc_name}] {src['service_display']}")

        if dry_run:
            print(f"  [DRY-RUN] apiService: {svc_name}")
            for ep in src["endpoints"]:
                print(f"  [DRY-RUN] apiEndpoint: {ep['name']}")
                for dag_id in ep["pipelines"]:
                    print(f"    [DRY-RUN] lineage: {ep['name']} -> {dag_id}")
            stats["services"] += 1
            stats["endpoints"] += len(src["endpoints"])
            stats["edges"] += sum(len(ep["pipelines"]) for ep in src["endpoints"])
            print()
            continue

        # 1) apiService
        svc_id = upsert_api_service(svc_name, src["service_display"], src["service_desc"], headers)
        if not svc_id:
            print(f"  SKIP (apiService 실패)\n")
            continue
        stats["services"] += 1
        print(f"  apiService: {svc_id[:12]}...")

        # 2) apiCollection
        col_fqn = upsert_api_collection(svc_name, headers)
        if not col_fqn:
            print(f"  SKIP (apiCollection 실패)\n")
            continue
        print(f"  apiCollection: {col_fqn}")

        # 3) apiEndpoints + lineage
        for ep in src["endpoints"]:
            ep_id = upsert_api_endpoint(ep, col_fqn, headers)
            if not ep_id:
                continue
            stats["endpoints"] += 1
            print(f"  apiEndpoint: {ep['displayName']} ({ep_id[:12]}...)")

            for dag_id in ep["pipelines"]:
                pipeline_id = get_pipeline_id(dag_id, headers)
                if not pipeline_id:
                    skipped.append(f"{ep['name']} -> {dag_id}")
                    print(f"    SKIP lineage: {dag_id} (OM에 없음)")
                    continue

                ok = create_lineage(ep_id, "apiEndpoint", pipeline_id, "pipeline", headers)
                if ok:
                    stats["edges"] += 1
                    print(f"    lineage: {ep['name']} -> {dag_id}")
                else:
                    print(f"    FAIL lineage: {ep['name']} -> {dag_id}")

        print()

    # 요약
    print(f"{'=' * 60}")
    print(f"완료: apiService {stats['services']}개, "
          f"apiEndpoint {stats['endpoints']}개, "
          f"lineage edge {stats['edges']}개")
    if skipped:
        print(f"\n건너뜀 ({len(skipped)}개 — pipeline이 OM에 없음):")
        for item in skipped:
            print(f"  - {item}")
        print(f"\nAirflow ingestion 먼저 실행 후 재실행:")
        print(f"  docker exec openmetadata-ingestion metadata ingest -c /connectors/bip_airflow.yaml")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BIP 외부 데이터 소스 OM 등록")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 등록 목록만 출력")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
