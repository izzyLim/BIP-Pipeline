"""
실시간 뉴스 수집 모듈
- 모닝 리포트 생성 시점에 최신 뉴스 검색
- 네이버 뉴스 검색 API 활용
- RAG 대신 실시간 검색으로 항상 최신 뉴스 제공
"""

import os
import logging
import html
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import quote
import requests

logger = logging.getLogger(__name__)


def get_naver_credentials():
    """네이버 API 인증 정보"""
    return {
        "client_id": os.getenv("NAVER_CLIENT_ID", ""),
        "client_secret": os.getenv("NAVER_CLIENT_SECRET", "")
    }


def clean_html_tags(text: str) -> str:
    """HTML 태그 및 엔티티 제거"""
    if not text:
        return ""
    # HTML 태그 제거
    text = re.sub(r'<[^>]+>', '', text)
    # HTML 엔티티 디코딩
    text = html.unescape(text)
    # 여러 공백을 하나로
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def search_naver_news(
    query: str,
    display: int = 10,
    sort: str = "date"
) -> List[Dict]:
    """
    네이버 뉴스 검색 API 호출

    Args:
        query: 검색어
        display: 결과 개수 (최대 100)
        sort: 정렬 (date: 최신순, sim: 관련도순)

    Returns:
        뉴스 목록
    """
    creds = get_naver_credentials()
    if not creds["client_id"] or not creds["client_secret"]:
        logger.warning("네이버 API 인증 정보 없음")
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": creds["client_id"],
        "X-Naver-Client-Secret": creds["client_secret"]
    }
    params = {
        "query": query,
        "display": display,
        "sort": sort
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        news_list = []
        for item in data.get("items", []):
            news_list.append({
                "title": clean_html_tags(item.get("title", "")),
                "description": clean_html_tags(item.get("description", "")),
                "link": item.get("link", ""),
                "pub_date": item.get("pubDate", ""),
                "query": query
            })

        return news_list

    except Exception as e:
        logger.error(f"네이버 뉴스 검색 실패 ({query}): {e}")
        return []


def generate_news_queries(market_data: Dict[str, Any]) -> List[str]:
    """
    시장 데이터 기반 검색 쿼리 생성

    Returns:
        검색 쿼리 리스트 (우선순위 순)
    """
    queries = []

    # 1. 핵심 시장 키워드
    queries.append("코스피 증시 시황")
    queries.append("미국 증시 나스닥")

    # 2. 주요 움직임 기반
    indices = market_data.get("indices", {})

    # 코스피/코스닥 변동
    kospi = indices.get("kospi", {})
    if kospi and abs(kospi.get("change_pct", 0)) >= 1.0:
        direction = "상승" if kospi.get("change_pct", 0) > 0 else "하락"
        queries.append(f"코스피 {direction} 원인")

    # 3. 섹터 기반
    korea = market_data.get("korea", {})
    if korea.get("sector_summary"):
        for sector in korea["sector_summary"][:2]:
            if abs(sector.get("change_pct", 0)) >= 1.5:
                queries.append(f"{sector['sector']} 관련주")

    # 4. 주요 종목 기반
    if korea.get("stocks"):
        for stock in korea["stocks"][:3]:
            if abs(stock.get("change_pct", 0)) >= 3.0:
                queries.append(stock["stock_name"])

    # 5. 매크로 키워드
    exchange = market_data.get("exchange_rates", {})
    if exchange.get("usd_krw"):
        if abs(exchange["usd_krw"].get("change_pct", 0)) >= 0.5:
            queries.append("원달러 환율")

    # 6. 테마 키워드
    queries.extend([
        "반도체 HBM AI",
        "외국인 기관 수급",
        "금리 연준 통화정책"
    ])

    # 7. 주요 이벤트 (일반적인 검색어로 현재 이슈 탐지)
    event_queries = [
        "이번주 증시 이벤트",       # 주간 이벤트
        "글로벌 테크 컨퍼런스",     # 테크 이벤트 (GTC, WWDC 등)
        "빅테크 실적 발표",        # 실적 시즌
        "중앙은행 통화정책",       # FOMC, BOJ, ECB 등
        "지정학 리스크 증시",      # 전쟁, 갈등 이슈
    ]
    queries.extend(event_queries)

    # 중복 제거
    return list(dict.fromkeys(queries))[:15]


def fetch_realtime_news(
    market_data: Dict[str, Any],
    max_per_query: int = 5,
    max_total: int = 20
) -> Dict[str, Any]:
    """
    실시간 뉴스 수집 (메인 함수)

    Args:
        market_data: 시장 데이터
        max_per_query: 쿼리당 최대 뉴스 수
        max_total: 총 최대 뉴스 수

    Returns:
        {
            "queries": [...],
            "news": [...],
            "formatted": "..."
        }
    """
    # 검색 쿼리 생성
    queries = generate_news_queries(market_data)
    logger.info(f"실시간 뉴스 검색 쿼리: {queries}")

    # 뉴스 검색
    all_news = []
    seen_titles = set()

    for query in queries:
        news_list = search_naver_news(query, display=max_per_query, sort="date")

        for news in news_list:
            # 중복 제거 (제목 기준)
            title_key = news["title"][:30]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                all_news.append(news)

        if len(all_news) >= max_total:
            break

    all_news = all_news[:max_total]
    logger.info(f"실시간 뉴스 수집 완료: {len(all_news)}건")

    # LLM용 포맷팅
    formatted = format_news_for_analysis(all_news)

    return {
        "queries": queries,
        "news": all_news,
        "formatted": formatted
    }


def format_news_for_analysis(news_list: List[Dict]) -> str:
    """
    LLM 분석용 뉴스 포맷팅
    """
    if not news_list:
        return "최신 뉴스 없음"

    lines = []
    for i, news in enumerate(news_list, 1):
        title = news.get("title", "")
        desc = news.get("description", "")
        pub_date = news.get("pub_date", "")

        # 시간 추출 (Mon, 16 Mar 2026 21:10:00 +0900 형식)
        time_str = ""
        if pub_date:
            try:
                # 시간 부분만 추출
                time_match = re.search(r'\d{2}:\d{2}:\d{2}', pub_date)
                if time_match:
                    time_str = f"[{time_match.group()[:5]}]"
            except:
                pass

        lines.append(f"{i}. {time_str} {title}")
        if desc:
            lines.append(f"   → {desc[:150]}...")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # 테스트
    test_market_data = {
        "indices": {
            "kospi": {"value": 2500, "change_pct": -1.5}
        },
        "korea": {
            "stocks": [
                {"stock_name": "삼성전자", "change_pct": -3.5}
            ],
            "sector_summary": [
                {"sector": "반도체", "change_pct": -2.5}
            ]
        }
    }

    print("=== 실시간 뉴스 수집 테스트 ===")
    result = fetch_realtime_news(test_market_data)
    print(f"\n쿼리: {result['queries']}")
    print(f"뉴스 수: {len(result['news'])}")
    print(f"\n포맷팅된 뉴스:\n{result['formatted']}")
