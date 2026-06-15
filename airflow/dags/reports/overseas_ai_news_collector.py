"""
해외 AI 뉴스 다이제스트 수집기
- RSS 소스(TechCrunch AI / VentureBeat AI / The Verge AI 등) 수집
- 최근 24h 필터 + 중복 제거
- Haiku 1회 호출로 한국어 시장영향 중심 요약 (3~5건)
- overseas_ai_news_digest 테이블 저장
- 모닝리포트 report_builder에서 최근 다이제스트를 read-only 조회
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# RSS 소스 (Airflow Variable 'OVERSEAS_AI_RSS_FEEDS' 로 override 가능)
# ──────────────────────────────────────────────

DEFAULT_FEEDS: List[Dict[str, str]] = [
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
]

# 시장 영향 관점 키워드 — 비즈니스/모델/규제 위주, 단순 리뷰·튜토리얼 제외
RELEVANT_KEYWORDS = [
    # 기업/모델
    "openai", "anthropic", "google", "deepmind", "meta", "microsoft", "nvidia",
    "amd", "intel", "tsm", "samsung", "apple", "xai", "mistral", "cohere",
    "claude", "gpt", "gemini", "llama", "grok",
    # 시장/투자
    "funding", "ipo", "valuation", "earnings", "revenue", "acquisition", "merger",
    "billion", "raise", "stock", "shares",
    # 정책/규제
    "regulation", "antitrust", "lawsuit", "export control", "ban",
    # 인프라/제품
    "data center", "chip", "gpu", "semiconductor", "foundry", "agent",
]


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


def _load_feeds() -> List[Dict[str, str]]:
    """Airflow Variable에서 RSS 소스 override 시도 → 실패 시 DEFAULT_FEEDS"""
    try:
        from airflow.models import Variable
        raw = Variable.get("OVERSEAS_AI_RSS_FEEDS", default_var=None)
        if raw:
            feeds = json.loads(raw)
            if isinstance(feeds, list) and feeds:
                return feeds
    except Exception:
        pass
    return DEFAULT_FEEDS


# ──────────────────────────────────────────────
# 수집 + 필터
# ──────────────────────────────────────────────

def _strip_html(s: str) -> str:
    """간단한 HTML 태그 제거"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _parse_pub_date(entry) -> datetime:
    """feedparser entry에서 발행시각 추출 (UTC), 없으면 epoch"""
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(entry, key, None) or entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _is_relevant(title: str, summary: str) -> bool:
    """시장영향 관점 키워드 기반 필터 — 너무 좁히지 않고 한 단어라도 매치되면 통과"""
    text_lower = (title + " " + summary).lower()
    return any(kw in text_lower for kw in RELEVANT_KEYWORDS)


def _collect_rss(feeds: List[Dict[str, str]], hours: int = 24, per_feed_limit: int = 15) -> List[Dict]:
    """RSS 수집 → 최근 N시간 + 키워드 필터 + 중복 제거.
    각 피드의 가장 오래된 항목이 cutoff에 못 미치면 WARN (RSS 롤오버 의심)."""
    import feedparser

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    rollover_warn_threshold_hours = max(2, int(hours * 0.85))  # 24h 요청 시 ~20h 미만이면 의심
    all_items: List[Dict] = []
    seen_titles = set()

    for feed in feeds:
        name = feed.get("name", "?")
        url = feed.get("url")
        if not url:
            continue
        try:
            parsed = feedparser.parse(url)
            count_added = 0
            feed_oldest_in_window: Optional[datetime] = None
            feed_oldest_entry: Optional[datetime] = None

            for entry in parsed.entries[:per_feed_limit * 2]:
                title = _strip_html(getattr(entry, "title", "") or "")
                if not title or title in seen_titles:
                    continue
                summary = _strip_html(getattr(entry, "summary", "") or getattr(entry, "description", "") or "")
                pub_dt = _parse_pub_date(entry)

                # 피드 전체의 가장 오래된 entry 추적 (관련성 무관)
                if pub_dt.year > 1970:
                    if feed_oldest_entry is None or pub_dt < feed_oldest_entry:
                        feed_oldest_entry = pub_dt

                if pub_dt < cutoff:
                    continue
                if not _is_relevant(title, summary):
                    continue
                seen_titles.add(title)
                all_items.append({
                    "source": name,
                    "title": title,
                    "summary": summary[:300],
                    "link": getattr(entry, "link", "") or "",
                    "pub_date": pub_dt.isoformat(),
                })
                count_added += 1
                if feed_oldest_in_window is None or pub_dt < feed_oldest_in_window:
                    feed_oldest_in_window = pub_dt
                if count_added >= per_feed_limit:
                    break

            logger.info(f"  {name}: {count_added}건 (총 {len(parsed.entries)}건 중)")

            # RSS 롤오버 경고 — 피드의 가장 오래된 entry조차 cutoff 안에 있으면 RSS가 24h 다 안 보여줬다는 뜻
            if feed_oldest_entry is not None and feed_oldest_entry > cutoff:
                gap_hours = (now - feed_oldest_entry).total_seconds() / 3600
                if gap_hours < rollover_warn_threshold_hours:
                    logger.warning(
                        f"⚠️  [{name}] RSS 롤오버 의심: 피드의 가장 오래된 항목이 "
                        f"{gap_hours:.1f}h 전 (요청 {hours}h). "
                        f"그 이전 기사가 RSS에서 밀려났을 수 있음 → 누락 가능."
                    )
        except Exception as e:
            logger.warning(f"RSS 수집 실패 [{name}]: {e}")

    # 최신순 정렬
    all_items.sort(key=lambda x: x["pub_date"], reverse=True)
    logger.info(f"해외 AI 뉴스 수집: {len(all_items)}건 (소스 {len(feeds)}개, 최근 {hours}h)")
    return all_items


# ──────────────────────────────────────────────
# Haiku 번역·요약
# ──────────────────────────────────────────────

def _summarize_overseas(items: List[Dict]) -> str:
    """Haiku로 한국어 시장영향 요약 (3~5건)"""
    import anthropic
    from utils.audited_llm import audited_anthropic_call

    if not items:
        return "[수집된 해외 AI 뉴스 없음]"

    lines = []
    for i, it in enumerate(items[:40], 1):
        lines.append(f"{i}. [{it['source']}] {it['title']} — {it['summary'][:160]}")
    news_text = "\n".join(lines)

    system = """글로벌 AI/테크 시장 분석가입니다.

아래는 영문 RSS에서 수집한 최근 24시간 해외 AI 관련 뉴스 목록입니다.
**한국·미국 증시(반도체/빅테크/AI 인프라)에 영향 줄 핵심 이슈 3~5건**을 선별하여 한국어로 요약하세요.

## 출력 형식 (반드시 따를 것)
[중요도] 이슈 제목 (영문 원제 → 한국어) — 핵심 내용 1~2줄 (시장영향 방향, 관련 섹터/종목)

중요도: 상/중/하
영향 방향: 긍정/부정/중립
관련 섹터/종목 예: 반도체(NVDA/AMD/SK하이닉스), 빅테크(MSFT/GOOG), AI 모델사 등

## 예시
[상] OpenAI, 차세대 모델 발표 — 추론 성능 2배·가격 30% 인하, MS/NVDA 수혜 (긍정, 빅테크/반도체)
[중] EU AI Act 추가 규제안 — 범용 AI 라이선스 의무화 검토 (부정, 글로벌 빅테크)
[하] 스타트업 X 시리즈C 5억$ — AI 에이전트 분야 자금 유입 지속 (긍정, AI 인프라)

## 규칙
- 동일 이슈를 다룬 기사는 통합
- 단순 제품 리뷰·튜토리얼·인물 가십은 제외
- 숫자(매출/펀딩/모델 파라미터)는 가능하면 포함
- 한국 증시 관점에서 가장 임팩트 큰 이슈 우선
- 서두/해설 금지, 위 형식 줄만 출력"""

    client = anthropic.Anthropic()
    try:
        resp = audited_anthropic_call(
            agent_name="overseas_ai_news",
            agent_type="collector",
            prompt_class="overseas_ai_summarize",
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": f"뉴스 목록:\n{news_text}"}],
            client=client,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"해외 AI 뉴스 요약 실패: {e}")
        # fallback: 상위 5건 제목만 그대로
        return "\n".join(f"- [{it['source']}] {it['title']}" for it in items[:5])


# ──────────────────────────────────────────────
# 메인: 수집 → 요약 → 저장
# ──────────────────────────────────────────────

def collect_and_save_overseas_digest(hours: int = 24) -> Dict:
    """RSS 수집 → Haiku 요약 → DB 저장"""
    feeds = _load_feeds()
    items = _collect_rss(feeds, hours=hours)

    if not items:
        logger.warning("해외 AI 뉴스 0건 — 저장 건너뜀")
        return {"success": False, "raw_count": 0, "digest": ""}

    digest = _summarize_overseas(items)
    logger.info(f"해외 AI 뉴스 다이제스트 생성: {len(digest)}자")

    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO overseas_ai_news_digest (collected_at, sources, raw_count, digest, raw_items)
            VALUES (now(), :sources, :raw_count, :digest, :raw_items)
        """), {
            "sources": json.dumps(feeds, ensure_ascii=False),
            "raw_count": len(items),
            "digest": digest,
            "raw_items": json.dumps(items, ensure_ascii=False),
        })

    logger.info(f"DB 저장 완료: {len(items)}건 → {len(digest)}자 요약")

    try:
        from utils.lineage import register_table_lineage_async
        register_table_lineage_async("overseas_ai_news_digest", source_tables=[])
    except Exception:
        pass

    return {"success": True, "raw_count": len(items), "digest": digest}


# ──────────────────────────────────────────────
# 조회: 최근 다이제스트 (모닝리포트용)
# ──────────────────────────────────────────────

def get_latest_overseas_digest(hours: int = 24) -> str:
    """최근 N시간 내 가장 최신 다이제스트 1건 반환 (없으면 빈 문자열)"""
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT digest
            FROM overseas_ai_news_digest
            WHERE collected_at > now() - make_interval(hours => :hours)
            ORDER BY collected_at DESC
            LIMIT 1
        """), {"hours": hours}).fetchone()
    return row[0] if row else ""


def get_recent_overseas_digests(hours: int = 24) -> List[Dict]:
    """최근 N시간 내 다이제스트 행 전체 반환 (시간 역순)"""
    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT collected_at, digest, raw_count
            FROM overseas_ai_news_digest
            WHERE collected_at > now() - make_interval(hours => :hours)
            ORDER BY collected_at DESC
        """), {"hours": hours}).fetchall()
    return [
        {"collected_at": str(r[0]), "digest": r[1], "raw_count": r[2]}
        for r in rows
    ]


def get_consolidated_overseas_digest(hours: int = 24) -> str:
    """최근 N시간의 여러 스냅샷을 Haiku로 1건으로 통합.
    - 1건만 있으면 그대로 반환 (Haiku 호출 절약)
    - 여러 건이면 Haiku로 머지 (RSS 롤오버 대비 누락 방지)
    """
    digests = get_recent_overseas_digests(hours)
    if not digests:
        return ""
    if len(digests) == 1:
        return digests[0]["digest"]

    combined = "\n\n".join(
        f"[{d['collected_at'][:16]}]\n{d['digest']}" for d in digests
    )

    import anthropic
    from utils.audited_llm import audited_anthropic_call

    client = anthropic.Anthropic()
    try:
        resp = audited_anthropic_call(
            agent_name="overseas_ai_news",
            agent_type="collector",
            prompt_class="overseas_ai_consolidate",
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=(
                "아래는 최근 8시간 간격으로 수집된 해외 AI 뉴스 요약 스냅샷들입니다.\n"
                "한국 증시(반도체/빅테크)에 영향 줄 **핵심 이슈 4~6건**을 추려 통합 정리하세요.\n"
                "중복 이슈는 가장 최신 정보로 통합. 이미 시장에 다 반영된 옛 이슈는 제외.\n"
                "형식: [상/중/하] 이슈 (영문→한국어) — 핵심 1~2줄 (방향, 관련 섹터/종목)\n"
                "서두/해설 금지. 위 형식 줄만 출력."
            ),
            messages=[{"role": "user", "content": combined}],
            client=client,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"해외 AI 다이제스트 통합 실패: {e}")
        return digests[0]["digest"]
