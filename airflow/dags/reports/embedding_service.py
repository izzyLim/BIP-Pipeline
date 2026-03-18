"""
임베딩 서비스
- OpenAI text-embedding-3-large 사용
- 뉴스 텍스트 → 벡터 변환
- PostgreSQL pgvector에 저장
"""

import os
import logging
from typing import List, Dict, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

# 설정
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536  # HNSW 인덱스 호환
BATCH_SIZE = 100  # OpenAI 배치 크기


def get_openai_client() -> OpenAI:
    """OpenAI 클라이언트 생성"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
    return OpenAI(api_key=api_key)


def create_embedding(text: str, client: Optional[OpenAI] = None) -> List[float]:
    """단일 텍스트 임베딩 생성"""
    if client is None:
        client = get_openai_client()

    # 텍스트 정제 (빈 문자열 방지)
    text = text.strip()
    if not text:
        return [0.0] * EMBEDDING_DIMENSIONS

    # 토큰 제한 (약 8000자로 제한)
    if len(text) > 8000:
        text = text[:8000]

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        dimensions=EMBEDDING_DIMENSIONS
    )

    return response.data[0].embedding


def create_embeddings_batch(texts: List[str], client: Optional[OpenAI] = None) -> List[List[float]]:
    """배치 임베딩 생성"""
    if client is None:
        client = get_openai_client()

    # 텍스트 정제
    cleaned_texts = []
    for text in texts:
        text = text.strip() if text else ""
        if len(text) > 8000:
            text = text[:8000]
        if not text:
            text = " "  # 빈 문자열 방지
        cleaned_texts.append(text)

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=cleaned_texts,
        dimensions=EMBEDDING_DIMENSIONS
    )

    # 순서 보장
    embeddings = [None] * len(cleaned_texts)
    for item in response.data:
        embeddings[item.index] = item.embedding

    return embeddings


def embed_news_batch(conn, batch_size: int = BATCH_SIZE, limit: Optional[int] = None) -> int:
    """
    임베딩이 없는 뉴스들을 배치로 처리

    Args:
        conn: PostgreSQL 연결
        batch_size: 배치 크기
        limit: 처리할 최대 개수 (None이면 전체)

    Returns:
        처리된 뉴스 수
    """
    client = get_openai_client()
    processed = 0

    with conn.cursor() as cur:
        # 임베딩이 없는 뉴스 조회
        query = """
            SELECT id, title, COALESCE(body, '') as body
            FROM news
            WHERE embedding IS NULL
            ORDER BY id
        """
        if limit:
            query += f" LIMIT {limit}"

        cur.execute(query)
        rows = cur.fetchall()

        if not rows:
            logger.info("임베딩할 뉴스가 없습니다.")
            return 0

        logger.info(f"임베딩 대상: {len(rows)}건")

        # 배치 처리
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]

            # 텍스트 준비 (제목 + 본문)
            texts = []
            ids = []
            for row in batch:
                news_id, title, body = row
                # 제목과 본문 결합 (제목에 가중치)
                text = f"{title}\n\n{body}" if body else title
                texts.append(text)
                ids.append(news_id)

            try:
                # 임베딩 생성
                embeddings = create_embeddings_batch(texts, client)

                # DB 업데이트
                for news_id, embedding in zip(ids, embeddings):
                    cur.execute(
                        "UPDATE news SET embedding = %s WHERE id = %s",
                        (embedding, news_id)
                    )

                conn.commit()
                processed += len(batch)
                logger.info(f"진행: {processed}/{len(rows)} ({processed * 100 // len(rows)}%)")

            except Exception as e:
                logger.error(f"배치 처리 실패: {e}")
                conn.rollback()
                raise

    return processed


def search_similar_news(
    conn,
    query_text: str,
    top_k: int = 10,
    client: Optional[OpenAI] = None
) -> List[Dict]:
    """
    쿼리 텍스트와 유사한 뉴스 검색

    Args:
        conn: PostgreSQL 연결
        query_text: 검색 쿼리 텍스트
        top_k: 반환할 결과 수
        client: OpenAI 클라이언트

    Returns:
        유사한 뉴스 목록
    """
    if client is None:
        client = get_openai_client()

    # 쿼리 임베딩 생성
    query_embedding = create_embedding(query_text, client)

    with conn.cursor() as cur:
        # 벡터 유사도 검색 (코사인 유사도)
        cur.execute("""
            SELECT
                id, title, body, source, published_at,
                1 - (embedding <=> %s::vector) as similarity
            FROM news
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (query_embedding, query_embedding, top_k))

        results = []
        for row in cur.fetchall():
            results.append({
                "id": row[0],
                "title": row[1],
                "body": row[2],
                "source": row[3],
                "published_at": row[4],
                "similarity": row[5]
            })

        return results


if __name__ == "__main__":
    # 테스트
    import sys
    sys.path.insert(0, '/opt/airflow/dags')
    from utils.db import get_pg_conn
    from utils.config import PG_CONN_INFO

    print("=== 임베딩 서비스 테스트 ===")

    # 단일 임베딩 테스트
    client = get_openai_client()
    emb = create_embedding("삼성전자 반도체 실적 발표", client)
    print(f"임베딩 차원: {len(emb)}")
    print(f"샘플 값: {emb[:5]}")
