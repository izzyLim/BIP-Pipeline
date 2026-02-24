"""
GSMArena 스마트폰 제품 정보 스크래퍼
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import logging
from datetime import datetime
from typing import List, Dict, Optional
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 요청 헤더 (봇 차단 방지)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

# 브랜드별 GSMArena URL
BRAND_URLS = {
    "Samsung": "https://www.gsmarena.com/samsung-phones-9.php",
    "Apple": "https://www.gsmarena.com/apple-phones-48.php",
    "Xiaomi": "https://www.gsmarena.com/xiaomi-phones-80.php",
    "Huawei": "https://www.gsmarena.com/huawei-phones-58.php",
    "OPPO": "https://www.gsmarena.com/oppo-phones-82.php",
    "Vivo": "https://www.gsmarena.com/vivo-phones-98.php",
    "OnePlus": "https://www.gsmarena.com/oneplus-phones-95.php",
    "Google": "https://www.gsmarena.com/google-phones-107.php",
    "Motorola": "https://www.gsmarena.com/motorola-phones-4.php",
    "Sony": "https://www.gsmarena.com/sony-phones-7.php",
}

# 세그먼트 분류 기준 (USD)
SEGMENT_RULES = {
    "flagship": ["ultra", "pro max", "pro+", "fold", "flip", "s2[0-9]+ ultra", "note", "z fold", "z flip"],
    "mid-range": ["pro", "plus", "a[5-7][0-9]", "reno", "find x", "poco f", "k[0-9]+"],
    "entry": ["a[0-3][0-9]", "m[0-9]+", "c[0-9]+", "y[0-9]+", "redmi [0-9]", "realme c", "moto g", "moto e"]
}


class GSMArenaScraper:
    """GSMArena 스크래퍼"""

    BASE_URL = "https://www.gsmarena.com"

    def __init__(self, delay: float = 2.0):
        """
        Args:
            delay: 요청 간 대기 시간 (초)
        """
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get_page(self, url: str) -> Optional[BeautifulSoup]:
        """페이지 가져오기"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            time.sleep(self.delay)
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def get_brand_phones(self, brand: str, max_pages: int = 3) -> List[Dict]:
        """브랜드의 폰 목록 가져오기"""
        if brand not in BRAND_URLS:
            logger.error(f"Unknown brand: {brand}")
            return []

        base_url = BRAND_URLS[brand]
        phones = []

        for page in range(1, max_pages + 1):
            if page == 1:
                url = base_url
            else:
                # 페이지네이션 URL 패턴
                url = base_url.replace(".php", f"-f-{page}.php")

            logger.info(f"Fetching {brand} page {page}: {url}")
            soup = self._get_page(url)

            if not soup:
                break

            # 폰 목록 파싱
            phone_list = soup.select('.makers ul li')

            if not phone_list:
                break

            for phone in phone_list:
                link = phone.select_one('a')
                if not link:
                    continue

                name_elem = phone.select_one('span')
                img_elem = phone.select_one('img')

                phone_data = {
                    'brand': brand,
                    'name': name_elem.text.strip() if name_elem else '',
                    'url': self.BASE_URL + '/' + link.get('href', ''),
                    'image': img_elem.get('src', '') if img_elem else ''
                }
                phones.append(phone_data)

            logger.info(f"  Found {len(phone_list)} phones on page {page}")

        return phones

    def get_phone_details(self, phone_url: str) -> Optional[Dict]:
        """개별 폰 상세 정보 가져오기"""
        soup = self._get_page(phone_url)

        if not soup:
            return None

        details = {}

        # 제품명
        title = soup.select_one('.specs-phone-name-title')
        details['full_name'] = title.text.strip() if title else ''

        # 출시일
        released = soup.select_one('[data-spec="released-hl"]')
        if released:
            details['released'] = released.text.strip()
            details['release_date'] = self._parse_release_date(released.text.strip())

        # 가격
        price = soup.select_one('[data-spec="price"]')
        if price:
            details['price'] = price.text.strip()
            details['price_usd'] = self._parse_price(price.text.strip())

        # 스펙 테이블 파싱
        spec_tables = soup.select('table')
        for table in spec_tables:
            rows = table.select('tr')
            for row in rows:
                header = row.select_one('.ttl')
                value = row.select_one('.nfo')
                if header and value:
                    key = header.text.strip().lower().replace(' ', '_')
                    details[key] = value.text.strip()

        # 세그먼트 분류
        details['segment'] = self._classify_segment(details.get('full_name', ''), details.get('price_usd'))

        return details

    def _parse_release_date(self, text: str) -> Optional[str]:
        """출시일 파싱 (예: 'Released 2024, January 17')"""
        # 패턴: "Released 2024, January 17" 또는 "Released 2024, January"
        patterns = [
            r'(\d{4}),?\s*(\w+)\s+(\d+)',  # 2024, January 17
            r'(\d{4}),?\s*(\w+)',           # 2024, January
            r'Exp\.\s*release\s*(\d{4}),?\s*(\w+)',  # Expected release
        ]

        months = {
            'january': '01', 'february': '02', 'march': '03', 'april': '04',
            'may': '05', 'june': '06', 'july': '07', 'august': '08',
            'september': '09', 'october': '10', 'november': '11', 'december': '12'
        }

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                year = groups[0]
                month = months.get(groups[1].lower(), '01')
                day = groups[2] if len(groups) > 2 else '01'
                return f"{year}-{month}-{day.zfill(2)}"

        return None

    def _parse_price(self, text: str) -> Optional[float]:
        """가격 파싱 (USD 추출)"""
        # 패턴: "$ 999" 또는 "About 450 EUR"
        usd_match = re.search(r'\$\s*([\d,]+)', text)
        if usd_match:
            return float(usd_match.group(1).replace(',', ''))

        eur_match = re.search(r'([\d,]+)\s*EUR', text)
        if eur_match:
            # EUR to USD 대략 변환
            return float(eur_match.group(1).replace(',', '')) * 1.1

        return None

    def _classify_segment(self, name: str, price: Optional[float]) -> str:
        """세그먼트 분류"""
        name_lower = name.lower()

        # 이름 기반 분류
        for segment, patterns in SEGMENT_RULES.items():
            for pattern in patterns:
                if re.search(pattern, name_lower):
                    return segment

        # 가격 기반 분류
        if price:
            if price >= 800:
                return "flagship"
            elif price >= 300:
                return "mid-range"
            else:
                return "entry"

        return "mid-range"  # 기본값


def scrape_recent_phones(brands: List[str] = None, max_phones_per_brand: int = 20) -> pd.DataFrame:
    """최근 폰 목록 스크래핑"""
    if brands is None:
        brands = list(BRAND_URLS.keys())

    scraper = GSMArenaScraper(delay=2.0)
    all_phones = []

    for brand in brands:
        logger.info(f"\n=== Scraping {brand} ===")

        # 브랜드 폰 목록
        phones = scraper.get_brand_phones(brand, max_pages=2)

        # 상세 정보 (최근 N개만)
        for i, phone in enumerate(phones[:max_phones_per_brand]):
            logger.info(f"  [{i+1}/{min(len(phones), max_phones_per_brand)}] {phone['name']}")

            details = scraper.get_phone_details(phone['url'])
            if details:
                phone.update(details)
                all_phones.append(phone)

            # 너무 많은 요청 방지
            if i > 0 and i % 5 == 0:
                time.sleep(3)

    df = pd.DataFrame(all_phones)
    return df


def save_to_db(df: pd.DataFrame):
    """DB에 저장"""
    import psycopg2

    DB_CONFIG = {
        "host": "localhost",
        "port": 5432,
        "user": "user",
        "password": "pw1234",
        "dbname": "stockdb"
    }

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        try:
            # release_date가 있는 경우만 삽입
            if pd.isna(row.get('release_date')):
                continue

            cur.execute("""
                INSERT INTO product_release (brand, product_name, segment, release_date)
                VALUES (%s, %s, %s::segment_type, %s)
                ON CONFLICT (brand, product_name) DO UPDATE
                SET segment = EXCLUDED.segment, release_date = EXCLUDED.release_date
            """, (
                row['brand'],
                row.get('full_name') or row.get('name'),
                row.get('segment', 'mid-range'),
                row['release_date']
            ))
            inserted += 1
        except Exception as e:
            logger.debug(f"Error inserting {row.get('name')}: {e}")
            conn.rollback()
            continue

    conn.commit()
    conn.close()

    logger.info(f"Inserted {inserted} products to database")
    return inserted


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # 테스트: Samsung 5개만
        print("=== Test Mode: Samsung 5 phones ===")
        df = scrape_recent_phones(brands=["Samsung"], max_phones_per_brand=5)
        print(df[['brand', 'name', 'released', 'segment', 'price']].to_string())

    elif len(sys.argv) > 1 and sys.argv[1] == "full":
        # 전체 스크래핑
        print("=== Full Scraping ===")
        df = scrape_recent_phones(max_phones_per_brand=30)
        df.to_csv("products_gsmarena.csv", index=False)
        print(f"Saved {len(df)} products to products_gsmarena.csv")

        # DB 저장
        save_to_db(df)

    else:
        print("Usage:")
        print("  python gsmarena_scraper.py test   # Test with Samsung 5 phones")
        print("  python gsmarena_scraper.py full   # Full scraping all brands")
