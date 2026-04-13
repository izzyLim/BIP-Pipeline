"""
실시간 뉴스 수집 모듈
- 모닝 리포트 생성 시점에 최신 뉴스 검색
- 네이버 뉴스 검색 API 활용
- RAG 대신 실시간 검색으로 항상 최신 뉴스 제공
- 품질 필터링: 신뢰도, 제목, 중복 제거
"""

import os
import logging
import html
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import quote
from difflib import SequenceMatcher
import requests

logger = logging.getLogger(__name__)

# 신뢰할 수 있는 언론사 목록 (URL 패턴 또는 제목에 포함된 경우)
TRUSTED_SOURCES = [
    "연합뉴스", "한국경제", "매일경제", "조선비즈", "머니투데이",
    "이데일리", "서울경제", "파이낸셜뉴스", "뉴스1", "아시아경제",
    "한경", "매경", "헤럴드경제", "SBS", "KBS", "MBC", "YTN",
    "블룸버그", "로이터", "CNBC", "WSJ",
]

# 필터링할 스팸/광고 패턴
SPAM_PATTERNS = [
    r'\[광고\]', r'\[AD\]', r'\[PR\]', r'\[제휴\]',
    r'무료상담', r'이벤트', r'할인', r'쿠폰',
    r'주식리딩방', r'종목추천', r'급등주', r'테마주',
    r'비트코인.*투자', r'코인.*추천',
    r'대출', r'카드론', r'신용대출',
]


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


def is_spam_title(title: str) -> bool:
    """스팸/광고성 제목인지 확인"""
    if not title:
        return True

    for pattern in SPAM_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return True
    return False


def calculate_similarity(s1: str, s2: str) -> float:
    """두 문자열의 유사도 계산 (0~1)"""
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1, s2).ratio()


def is_duplicate_news(title: str, existing_titles: List[str], threshold: float = 0.7) -> bool:
    """기존 뉴스와 중복인지 확인 (유사도 기반)"""
    if not title:
        return True

    for existing in existing_titles:
        if calculate_similarity(title, existing) >= threshold:
            return True
    return False


def get_source_priority(news: Dict) -> int:
    """
    뉴스 신뢰도 점수 계산 (높을수록 좋음)
    - 신뢰 언론사: +10
    - 제목 길이 적절 (20~100자): +3
    - 설명 있음: +2
    """
    score = 0
    title = news.get("title", "")
    link = news.get("link", "")
    desc = news.get("description", "")

    # 신뢰 언론사 체크
    for source in TRUSTED_SOURCES:
        if source in title or source in link:
            score += 10
            break

    # 제목 길이
    if 20 <= len(title) <= 100:
        score += 3

    # 설명 유무
    if desc and len(desc) > 30:
        score += 2

    return score


def filter_and_rank_news(news_list: List[Dict], max_count: int = 40) -> List[Dict]:
    """
    뉴스 품질 필터링 및 랭킹

    1. 스팸 제거
    2. 중복 제거 (유사도 기반)
    3. 신뢰도 기반 정렬
    """
    filtered = []
    seen_titles = []

    for news in news_list:
        title = news.get("title", "")

        # 1. 스팸 필터
        if is_spam_title(title):
            logger.debug(f"스팸 필터됨: {title[:50]}")
            continue

        # 2. 중복 필터 (유사도 70% 이상)
        if is_duplicate_news(title, seen_titles, threshold=0.7):
            logger.debug(f"중복 필터됨: {title[:50]}")
            continue

        seen_titles.append(title)

        # 신뢰도 점수 추가
        news["_priority"] = get_source_priority(news)
        filtered.append(news)

    # 3. 신뢰도 기반 정렬 (높은 점수 먼저)
    filtered.sort(key=lambda x: x.get("_priority", 0), reverse=True)

    # 내부 필드 제거 후 반환
    result = []
    for news in filtered[:max_count]:
        news.pop("_priority", None)
        result.append(news)

    logger.info(f"뉴스 필터링: {len(news_list)} → {len(result)}건")
    return result


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

    # 8. 월요일: 주말 동안 발생한 돌발 이슈 탐지 (범용 쿼리)
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        now = datetime.now()
    if now.weekday() == 0:  # 월요일
        weekend_queries = [
            "주말 증시 영향",
            "월요일 증시 전망",
            "글로벌 긴급 속보",
        ]
        # 주말 쿼리를 상위에 배치 (최신 이슈 우선 탐지)
        queries = weekend_queries + queries

    # 중복 제거
    return list(dict.fromkeys(queries))[:15]


def fetch_realtime_news(
    market_data: Dict[str, Any],
    max_per_query: int = 10,
    max_total: int = 40
) -> Dict[str, Any]:
    """
    실시간 뉴스 수집 (메인 함수)

    Args:
        market_data: 시장 데이터
        max_per_query: 쿼리당 최대 뉴스 수 (필터링 전)
        max_total: 총 최대 뉴스 수 (필터링 후)

    Returns:
        {
            "queries": [...],
            "news": [...],
            "news_before_filter": int,
            "formatted": "..."
        }
    """
    # 검색 쿼리 생성
    queries = generate_news_queries(market_data)
    logger.info(f"실시간 뉴스 검색 쿼리: {queries}")

    # 뉴스 검색 (필터링 전 더 많이 수집)
    all_news = []
    seen_titles = set()

    for query in queries:
        news_list = search_naver_news(query, display=max_per_query, sort="date")

        for news in news_list:
            # 기본 중복 제거 (정확히 같은 제목)
            title = news["title"]
            if title not in seen_titles:
                seen_titles.add(title)
                all_news.append(news)

    news_before_filter = len(all_news)
    logger.info(f"뉴스 수집 완료 (필터 전): {news_before_filter}건")

    # 품질 필터링 및 랭킹
    filtered_news = filter_and_rank_news(all_news, max_count=max_total)
    logger.info(f"뉴스 필터링 완료: {len(filtered_news)}건")

    # LLM용 포맷팅
    formatted = format_news_for_analysis(filtered_news)

    return {
        "queries": queries,
        "news": filtered_news,
        "news_before_filter": news_before_filter,
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
