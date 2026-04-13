"""
뉴스 다이제스트 수집기
- 4시간마다 네이버 뉴스 수집 → 필터 → Haiku 요약 → DB 저장
- 모닝리포트 / 체크리스트 에이전트에서 최근 48시간 다이제스트 활용
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


def _get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        pg_user = os.getenv("PG_USER", "user")
        pg_password = os.getenv("PG_PASSWORD")
        pg_host = os.getenv("PG_HOST", "bip-postgres")
        pg_port = os.getenv("PG_PORT", "5432")
        pg_db = os.getenv("PG_DB", "stockdb")
        url = f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
    return create_engine(url)


# ──────────────────────────────────────────────
# 수집 쿼리 (시장 전반 + 테마)
# ──────────────────────────────────────────────

CORE_QUERIES = [
    "코스피 증시 시황",
    "미국 증시 나스닥",
    "반도체 HBM AI",
    "외국인 기관 수급",
    "원달러 환율",
    "금리 연준 통화정책",
    "국제유가 WTI",
    "지정학 리스크",
    "글로벌 증시 전망",
    "2차전지 전기차",
]

WEEKEND_EXTRA_QUERIES = [
    "주말 증시 영향",
    "월요일 증시 전망",
    "글로벌 긴급 속보",
]


def _get_queries() -> List[str]:
    """시간대별 검색 쿼리 생성"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:
        now = datetime.now()

    queries = list(CORE_QUERIES)

    # 주말(토/일) 또는 월요일 새벽: 주말 뉴스 추가 탐지
    if now.weekday() >= 5 or (now.weekday() == 0 and now.hour < 12):
        queries = WEEKEND_EXTRA_QUERIES + queries

    return queries


# ──────────────────────────────────────────────
# 뉴스 수집 + 필터
# ──────────────────────────────────────────────

def _collect_news(queries: List[str], max_per_query: int = 10) -> List[Dict]:
    """네이버 뉴스 API로 수집 + 중복 제거"""
    from reports.realtime_news import search_naver_news

    all_news = []
    seen_titles = set()

    for query in queries:
        try:
            news_list = search_naver_news(query, display=max_per_query, sort="date")
            for news in news_list:
                title = news.get("title", "")
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    all_news.append(news)
        except Exception as e:
            logger.warning(f"뉴스 수집 실패 ({query}): {e}")

    logger.info(f"뉴스 수집: {len(all_news)}건 (쿼리 {len(queries)}개)")
    return all_news


def _summarize_news(news_list: List[Dict]) -> str:
    """Haiku로 뉴스 요약 — 시장 영향 이슈 3~5개"""
    import anthropic
    from utils.audited_llm import audited_anthropic_call

    if not news_list:
        return "[수집된 뉴스 없음]"

    # 뉴스를 텍스트로 변환
    lines = []
    for i, news in enumerate(news_list[:60], 1):  # 최대 60건
        title = news.get("title", "")
        desc = news.get("description", "")[:150]
        pub_date = news.get("pub_date", "")
        lines.append(f"{i}. [{pub_date}] {title} — {desc}")

    news_text = "\n".join(lines)

    system = """주식/금융 시장 뉴스 분석 전문가입니다.

아래 뉴스 목록에서 **한국 증시에 영향을 줄 핵심 이슈 3~5개**를 선별하고 요약하세요.

## 출력 형식 (정확히 따를 것)
[중요도] 이슈 제목 — 핵심 내용 1줄 (영향 방향, 관련 섹터/종목)

중요도: 상/중/하
영향 방향: 긍정/부정/중립

## 예시
[상] 미이란 협상 결렬 — 호르무즈 봉쇄 확정, 유가 $104 급등 예상 (부정, 에너지/운송/화학)
[상] 삼성전자 1Q 실적 — 영업이익 15.8조 사상최대 전망 (긍정, 반도체)
[중] 원/달러 1,480 돌파 — 원화 약세 가속, 외인 수급 우려 (부정, 전체)

## 규칙
- 같은 이슈를 다룬 기사는 하나로 통합
- 시장과 무관한 뉴스(연예, 스포츠, 사건사고 등)는 제외
- 최신 뉴스일수록 중요도 높게
- 숫자가 있으면 반드시 포함 (유가 $XX, 환율 X,XXX원 등)
- 출력은 3~5줄만. 서두/해설 금지"""

    client = anthropic.Anthropic()

    try:
        resp = audited_anthropic_call(
            agent_name="news_digest",
            agent_type="collector",
            prompt_class="news_summarize",
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": f"뉴스 목록:\n{news_text}"}],
            client=client,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"뉴스 요약 실패: {e}")
        # fallback: 상위 5건 제목만
        return "\n".join(f"- {n.get('title', '')}" for n in news_list[:5])


# ──────────────────────────────────────────────
# 메인 함수: 수집 → 요약 → 저장
# ──────────────────────────────────────────────

def collect_and_save_digest() -> Dict:
    """
    뉴스 수집 → Haiku 요약 → DB 저장

    Returns:
        {"success": bool, "raw_count": int, "digest": str}
    """
    queries = _get_queries()
    news_list = _collect_news(queries)

    if not news_list:
        logger.warning("수집된 뉴스 없음 — 저장 건너뜀")
        return {"success": False, "raw_count": 0, "digest": ""}

    # Haiku 요약
    digest = _summarize_news(news_list)
    logger.info(f"뉴스 다이제스트 생성: {len(digest)}자")

    # raw_items (제목+설명+링크만 저장, 전문 제외)
    raw_items = [
        {
            "title": n.get("title", ""),
            "description": n.get("description", "")[:200],
            "link": n.get("link", ""),
            "pub_date": n.get("pub_date", ""),
            "query": n.get("query", ""),
        }
        for n in news_list
    ]

    # DB 저장
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO news_digest (collected_at, queries, raw_count, digest, raw_items)
            VALUES (now(), :queries, :raw_count, :digest, :raw_items)
        """), {
            "queries": json.dumps(queries, ensure_ascii=False),
            "raw_count": len(news_list),
            "digest": digest,
            "raw_items": json.dumps(raw_items, ensure_ascii=False),
        })

    logger.info(f"뉴스 다이제스트 DB 저장 완료: {len(news_list)}건 → {len(digest)}자 요약")

    # lineage 등록
    try:
        from utils.lineage import register_table_lineage_async
        register_table_lineage_async("news_digest", source_tables=[])
    except Exception:
        pass

    return {"success": True, "raw_count": len(news_list), "digest": digest}


# ──────────────────────────────────────────────
# 조회: 최근 N시간 다이제스트
# ──────────────────────────────────────────────

def get_recent_digests(hours: int = 48) -> List[Dict]:
    """최근 N시간 뉴스 다이제스트 조회"""
    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT collected_at, digest, raw_count
            FROM news_digest
            WHERE collected_at > now() - make_interval(hours => :hours)
            ORDER BY collected_at DESC
        """), {"hours": hours}).fetchall()

    return [
        {
            "collected_at": str(row[0]),
            "digest": row[1],
            "raw_count": row[2],
        }
        for row in rows
    ]


def get_consolidated_digest(hours: int = 48) -> str:
    """
    최근 N시간 다이제스트를 하나로 통합
    - Haiku 1회 호출로 "오늘 장에 영향 줄 핵심 3개" 추출
    - 모닝리포트 프롬프트에 직접 주입 가능한 형태
    """
    digests = get_recent_digests(hours)

    if not digests:
        return ""

    # 최근 다이제스트가 1개면 그대로 반환
    if len(digests) == 1:
        return digests[0]["digest"]

    # 여러 개면 Haiku로 통합
    combined = "\n\n".join(
        f"[{d['collected_at'][:16]}]\n{d['digest']}"
        for d in digests
    )

    import anthropic
    from utils.audited_llm import audited_anthropic_call

    client = anthropic.Anthropic()

    try:
        resp = audited_anthropic_call(
            agent_name="news_digest",
            agent_type="collector",
            prompt_class="news_consolidate",
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=(
                "아래는 최근 수집된 뉴스 요약들입니다.\n"
                "오늘 한국 증시에 영향 줄 **핵심 이슈 3~5개**만 추려서 정리하세요.\n"
                "중복 이슈는 최신 정보로 통합. 이미 지나간 이슈는 제외.\n"
                "형식: [상/중/하] 이슈 — 핵심 1줄 (방향, 섹터)\n"
                "서두/해설 금지. 3~5줄만."
            ),
            messages=[{"role": "user", "content": combined}],
            client=client,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"다이제스트 통합 실패: {e}")
        # fallback: 가장 최근 다이제스트
        return digests[0]["digest"] if digests else ""
