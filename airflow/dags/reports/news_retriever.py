"""
뉴스 검색 모듈 (RAG)
- 시장 데이터 기반 관련 뉴스 검색
- pgvector 벡터 유사도 검색
"""

import os
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_openai_client():
    """OpenAI 클라이언트 생성"""
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    return OpenAI(api_key=api_key)


def create_query_embedding(text: str, client=None) -> List[float]:
    """쿼리 텍스트 임베딩 생성"""
    if client is None:
        client = get_openai_client()

    response = client.embeddings.create(
        model="text-embedding-3-large",
        input=text,
        dimensions=1536
    )
    return response.data[0].embedding


def generate_search_queries(market_data: Dict[str, Any]) -> List[str]:
    """
    시장 데이터에서 검색 쿼리 생성

    Args:
        market_data: collect_all_macro_data()의 결과

    Returns:
        검색 쿼리 리스트
    """
    queries = []

    # 1. 주요 지수 변동
    indices = market_data.get("indices", {})
    for key, data in indices.items():
        if data and abs(data.get("change_pct", 0)) >= 1.0:
            direction = "상승" if data.get("change_pct", 0) > 0 else "하락"
            name_map = {"kospi": "코스피", "kosdaq": "코스닥", "sp500": "S&P500", "nasdaq": "나스닥"}
            name = name_map.get(key, key)
            queries.append(f"{name} {direction} 원인 배경")

    # 2. 주요 종목 움직임 (한국)
    korea = market_data.get("korea", {})
    if korea.get("stocks"):
        # 급등/급락 종목
        for stock in korea["stocks"][:10]:
            change = stock.get("change_pct", 0)
            if abs(change) >= 3.0:
                direction = "급등" if change > 0 else "급락"
                queries.append(f"{stock['stock_name']} {direction}")

    # 3. 섹터 동향
    if korea.get("sector_summary"):
        for sector in korea["sector_summary"][:3]:
            change = sector.get("change_pct", 0)
            if abs(change) >= 1.5:
                direction = "강세" if change > 0 else "약세"
                queries.append(f"{sector['sector']} 섹터 {direction}")

    # 4. 매크로 지표
    # 환율
    exchange = market_data.get("exchange_rates", {})
    if exchange.get("usd_krw"):
        change = exchange["usd_krw"].get("change_pct", 0)
        if abs(change) >= 0.5:
            direction = "상승" if change > 0 else "하락"
            queries.append(f"원달러 환율 {direction}")

    # 금리
    rates = market_data.get("interest_rates", {})
    if rates.get("us_10y"):
        change = rates["us_10y"].get("change_pct", 0)
        if abs(change) >= 2.0:
            queries.append("미국 금리 연준 통화정책")

    # 5. 외국인 동향
    investor_flow = market_data.get("investor_flow", [])
    if investor_flow:
        latest = investor_flow[0]
        foreign = latest.get("foreign_amount", 0) or 0
        if abs(foreign) >= 500000000000:  # 5000억 이상
            direction = "순매수" if foreign > 0 else "순매도"
            queries.append(f"외국인 {direction}")

    # 6. 반도체 (항상 포함 - 한국 시장 핵심)
    queries.append("반도체 메모리 DRAM HBM")

    # 7. 일반 시황
    queries.append("증시 전망 투자 전략")

    # 중복 제거
    return list(dict.fromkeys(queries))


def search_relevant_news(
    conn,
    queries: List[str],
    top_k_per_query: int = 3,
    max_total: int = 15,
    days_back: int = 7,
    client=None
) -> List[Dict]:
    """
    여러 쿼리로 관련 뉴스 검색

    Args:
        conn: PostgreSQL 연결
        queries: 검색 쿼리 리스트
        top_k_per_query: 쿼리당 결과 수
        max_total: 최대 총 결과 수
        days_back: 며칠 전까지 검색
        client: OpenAI 클라이언트

    Returns:
        관련 뉴스 목록 (중복 제거, 유사도 순)
    """
    if client is None:
        client = get_openai_client()

    all_results = {}
    cutoff_date = datetime.now() - timedelta(days=days_back)

    for query in queries:
        try:
            # 쿼리 임베딩
            query_embedding = create_query_embedding(query, client)

            with conn.cursor() as cur:
                # 벡터 유사도 검색
                cur.execute("""
                    SELECT
                        id, title, body, source, published_at, created_at,
                        1 - (embedding <=> %s::vector) as similarity
                    FROM news
                    WHERE embedding IS NOT NULL
                      AND (published_at >= %s OR created_at >= %s)
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (query_embedding, cutoff_date, cutoff_date, query_embedding, top_k_per_query))

                for row in cur.fetchall():
                    news_id = row[0]
                    if news_id not in all_results or row[6] > all_results[news_id]["similarity"]:
                        all_results[news_id] = {
                            "id": news_id,
                            "title": row[1],
                            "body": row[2][:500] if row[2] else None,  # 본문 500자 제한
                            "source": row[3],
                            "published_at": row[4],
                            "created_at": row[5],
                            "similarity": row[6],
                            "matched_query": query
                        }
        except Exception as e:
            logger.warning(f"쿼리 '{query}' 검색 실패: {e}")
            continue

    # 유사도 순 정렬 및 상위 N개 반환
    sorted_results = sorted(all_results.values(), key=lambda x: x["similarity"], reverse=True)
    return sorted_results[:max_total]


def format_news_for_llm(news_list: List[Dict]) -> str:
    """
    LLM 분석용 뉴스 포맷팅

    Args:
        news_list: 뉴스 목록

    Returns:
        포맷팅된 텍스트
    """
    if not news_list:
        return "관련 뉴스 없음"

    lines = []
    for i, news in enumerate(news_list, 1):
        title = news.get("title", "제목 없음")
        body = news.get("body", "")
        # 본문 요약 (첫 200자)
        summary = body[:200] + "..." if body and len(body) > 200 else body

        lines.append(f"{i}. {title}")
        if summary:
            lines.append(f"   {summary}")
        lines.append("")

    return "\n".join(lines)


def retrieve_news_for_report(conn, market_data: Dict[str, Any], client=None) -> Dict[str, Any]:
    """
    모닝 리포트용 뉴스 검색 (통합 함수)

    Args:
        conn: PostgreSQL 연결
        market_data: 시장 데이터
        client: OpenAI 클라이언트

    Returns:
        {
            "queries": [...],
            "news": [...],
            "formatted": "..."
        }
    """
    if client is None:
        client = get_openai_client()

    # 검색 쿼리 생성
    queries = generate_search_queries(market_data)
    logger.info(f"생성된 검색 쿼리: {queries}")

    # 뉴스 검색
    news = search_relevant_news(conn, queries, client=client)
    logger.info(f"검색된 뉴스: {len(news)}건")

    # 포맷팅
    formatted = format_news_for_llm(news)

    return {
        "queries": queries,
        "news": news,
        "formatted": formatted
    }


if __name__ == "__main__":
    # 테스트
    import sys
    sys.path.insert(0, '/opt/airflow/dags')
    from utils.db import get_pg_conn
    from utils.config import PG_CONN_INFO

    # 테스트용 시장 데이터
    test_market_data = {
        "indices": {
            "kospi": {"value": 2500, "change_pct": -1.5},
            "nasdaq": {"value": 15000, "change_pct": 2.0}
        },
        "korea": {
            "stocks": [
                {"stock_name": "삼성전자", "change_pct": -3.5},
                {"stock_name": "SK하이닉스", "change_pct": -4.2}
            ],
            "sector_summary": [
                {"sector": "반도체", "change_pct": -2.5}
            ]
        }
    }

    print("=== 뉴스 검색 테스트 ===")

    # 쿼리 생성
    queries = generate_search_queries(test_market_data)
    print(f"\n생성된 쿼리: {queries}")

    # 뉴스 검색
    conn = get_pg_conn(PG_CONN_INFO)
    try:
        result = retrieve_news_for_report(conn, test_market_data)
        print(f"\n검색된 뉴스 수: {len(result['news'])}")
        print(f"\n포맷팅된 뉴스:\n{result['formatted'][:1000]}...")
    finally:
        conn.close()
