import requests
from datetime import datetime

API_KEY = "b61c0d4f76074b2a8bb4b9479a241fad"  # ↔ 여기에 발급받은 키를 넣으세요
TICKER  = "AAPL"

def fetch_news(q, page=1, page_size=10):
    url = "https://newsapi.org/v2/everything"
    params = {
        "q":         q,
        "language":  "en",
        "sortBy":    "publishedAt",
        "pageSize":  page_size,
        "page":      page,
        "apiKey":    API_KEY,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("articles", [])

def print_news_list(articles):
    for art in articles:
        t = datetime.fromisoformat(art["publishedAt"].replace("Z", "+00:00"))
        print(f"- [{t:%Y-%m-%d %H:%M}] {art['title']}\n  ({art['source']['name']})\n  {art['url']}\n")

if __name__ == "__main__":
    print(f"\n=== '{TICKER}' 관련 최신 뉴스 ===\n")
    articles = fetch_news(TICKER, page_size=5)
    print_news_list(articles)
