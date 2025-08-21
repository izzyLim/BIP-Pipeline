from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from utils.db import get_pg_conn, upsert_news
from utils.config import PG_CONN_INFO
from time import sleep
from urllib.parse import urljoin

DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://stock.naver.com/"}

def fetch_naver_news(**context):
    base = "https://finance.naver.com"
    candidate_urls = [
        base + "/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258",
        base + "/news/mainnews.naver",
        "https://news.naver.com/main/main.naver?mode=LSD&mid=shm&sid1=101",  # 일반 경제/증권
        "https://news.naver.com"  # fallback
    ]

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Referer": "https://www.naver.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    html = None
    final_url = None
    for list_url in candidate_urls:
        try:
            r = session.get(list_url, timeout=15, allow_redirects=True)
            r.raise_for_status()
            html = r.text
            final_url = r.url
            print(f"[DEBUG] tried {list_url} -> {final_url} status={r.status_code} len={len(html)}")
            break
        except Exception as e:
            print(f"[WARN] list fetch failed for {list_url}: {e}")
            continue

    if not html:
        print("[ERROR] All list_url candidates failed")
        return

    # debug meta info
    soup = BeautifulSoup(html, "html.parser")
    og_title = (soup.select_one("meta[property='og:title']") or {}).get("content") if soup.select_one("meta[property='og:title']") else None
    page_title = soup.title.string.strip() if soup.title else None
    print(f"[DEBUG] page_title={page_title} og_title={og_title} final_url={final_url}")

    # 여러 후보 리스트 선택자 시도 (추가 후보 포함)
    list_selectors = [
        ".newsList li", ".section_latest li", ".articleList li", "ul.type01 li",
        ".main_news_list li", ".cluster_body .cluster_text a", ".list_news li", ".section_body li"
    ]
    lis = []
    for sel in list_selectors:
        lis = soup.select(sel)
        print(f"[DEBUG] selector '{sel}' matched {len(lis)} items")
        if lis:
            break

    if not lis:
        # 시도: news.naver.com 페이지의 기사 링크 패턴에서 a[href*="/read.naver"] 수집
        anchors = soup.select("a[href*='/read.naver'], a[href*='/news/']")
        print(f"[DEBUG] fallback anchors matched {len(anchors)}")
        lis = anchors

    # 수집 결과를 담을 리스트 초기화 (필수)
    items = []

    if not lis:
        print("[WARN] No list items found with known selectors. Page structure may have changed or content requires JS.")
        return

    seen_urls = set()
    for node in lis:
        # node가 <a> 태그일 수도 있고, li 등 컨테이너일 수도 있음
        a = node if getattr(node, "name", "") == "a" else node.select_one("a")
        if not a or not a.get("href"):
            continue
        href = a.get("href")
        # 상대/프로토콜-상대 경로 처리
        url = urljoin(final_url or base, href)
        # 스크립트 링크 등 무의미한 링크 건너뜀
        if url.startswith("javascript:") or url.startswith("#"):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = (a.get_text(strip=True) or a.get("title") or "").strip()

        # 상세 본문 가져오기 (세션 재사용)
        body = None
        try:
            ar = session.get(url, timeout=12)
            ar.raise_for_status()
            asoup = BeautifulSoup(ar.text, "html.parser")
            body_selectors = [".articleCont", "#content", ".news_end", ".article_body", ".newsArticle"]
            paragraphs = []
            for bsel in body_selectors:
                body_el = asoup.select_one(bsel)
                if body_el:
                    for p in body_el.select("p"):
                        text = p.get_text(strip=True)
                        if text:
                            paragraphs.append(text)
                    if paragraphs:
                        break
            if not paragraphs:
                for p in asoup.select("p"):
                    t = p.get_text(strip=True)
                    if t:
                        paragraphs.append(t)
                        if len(paragraphs) >= 10:
                            break
            body = "\n".join(paragraphs).strip() if paragraphs else None
        except Exception as e:
            print(f"[WARN] article fetch failed {url}: {e}")
            body = None

        items.append({
            "title": title,
            "url": url,
            "body": body,
            "summary": None,
            "published_at": None,
            "source": "NAVER"
        })

        # 샘플 로그(처음 몇개만)
        if len(items) <= 5:
            print(f"[DEBUG] item #{len(items)} title={title[:120]} url={url} body_len={len(body) if body else 0}")

        sleep(0.2)

    if not items:
        print("[INFO] No news items found after parsing.")
        return

    with get_pg_conn(PG_CONN_INFO) as conn:
        inserted = upsert_news(conn, items)
        print(f"[INFO] upsert_news inserted/updated {inserted} rows")

default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
}

with DAG(
    dag_id="load_naver_news",
    default_args=default_args,
    schedule_interval="0 * * * *",  # 매시 정각
    catchup=False,
    tags=["NAVER", "news"]
) as dag:
    fetch_news = PythonOperator(
        task_id="fetch_naver_news",
        python_callable=fetch_naver_news,
    )