import requests
import html
from email.utils import parsedate_to_datetime
from time import sleep
from typing import List, Dict, Optional

from utils.db import get_pg_conn, upsert_news
from utils.config import PG_CONN_INFO

SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"

def fetch_naver_news_for(query: str, headers: Dict[str, str], display: int = 10, start: int = 1) -> List[Dict]:
    params = {"query": query, "display": display, "start": start, "sort": "date"}
    r = requests.get(SEARCH_URL, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("items", [])


def fetch_and_upsert_naver_api(conn_info: dict, headers: Dict[str, str], tickers: Optional[List[str]] = None,
                               batch_per_ticker: int = 10, sleep_sec: float = 0.2) -> int:
    """
    Orchestrator: for each ticker fetch news via Naver API and upsert into news table.
    Returns number of processed items.
    """
    session = requests.Session()
    session.headers.update(headers)

    all_items = []
    for q in (tickers or []):
        try:
            results = fetch_naver_news_for(q, session.headers, display=batch_per_ticker)
        except Exception as e:
            print(f"[WARN] API fetch failed for {q}: {e}")
            sleep(sleep_sec)
            continue

        for it in results:
            title = html.unescape(it.get("title", "")).strip()
            url = it.get("link") or it.get("originallink")
            body = html.unescape(it.get("description", "")).strip() or None
            pub = None
            try:
                if it.get("pubDate"):
                    pub = parsedate_to_datetime(it.get("pubDate"))
            except Exception:
                pub = None

            all_items.append({
                "title": title,
                "url": url,
                "body": body,
                "summary": None,
                "published_at": pub,
                "source": "NAVER_API"
            })
        sleep(sleep_sec)

    if not all_items:
        print("[INFO] No news items returned from API.")
        return 0

    with get_pg_conn(conn_info) as conn:
        processed = upsert_news(conn, all_items)
        print(f"[INFO] upsert_news processed {processed} items")
        return processed