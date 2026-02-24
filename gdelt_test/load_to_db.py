"""
수집된 GDELT 데이터를 PostgreSQL에 적재
"""

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
import glob
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# DB 연결 정보
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "user",
    "password": "pw1234",
    "dbname": "stockdb"
}

# Counterpoint 권역 매핑 (국가코드 -> 권역)
COUNTRY_TO_REGION = {}
REGION_COUNTRIES = {
    "North America": ["US", "CA"],
    "Western Europe": ["GB", "UK", "DE", "FR", "IT", "ES", "NL", "BE", "AT", "CH", "IE", "PT", "SE", "NO", "DK", "FI"],
    "Central Europe": ["PL", "CZ", "HU", "RO", "SK", "BG", "HR", "SI", "UA", "RU"],
    "China": ["CN", "HK", "MO"],
    "India": ["IN"],
    "Japan": ["JP"],
    "South Korea": ["KR"],
    "Southeast Asia": ["ID", "VN", "TH", "PH", "MY", "SG", "MM", "KH", "LA"],
    "MEA": ["AE", "SA", "IL", "TR", "EG", "ZA", "NG", "KE", "MA", "PK", "BD"],
    "CALA": ["BR", "MX", "AR", "CL", "CO", "PE", "VE"],
    "Asia Pacific Others": ["AU", "NZ", "TW"],
}
for region, countries in REGION_COUNTRIES.items():
    for country in countries:
        COUNTRY_TO_REGION[country] = region

# 브랜드 매핑
BRAND_KEYWORDS = {
    "Samsung": ["Samsung", "Galaxy"],
    "Apple": ["Apple", "iPhone", "iPad"],
    "Xiaomi": ["Xiaomi", "Redmi", "POCO"],
    "Huawei": ["Huawei", "Honor"],
    "OPPO": ["OPPO", "Realme"],
    "Vivo": ["Vivo", "iQOO"],
    "OnePlus": ["OnePlus"],
    "Google": ["Google", "Pixel"],
    "Motorola": ["Motorola", "Moto"],
}


def get_connection():
    """Docker 환경에서는 bip-postgres, 로컬에서는 localhost"""
    try:
        # 먼저 Docker 네트워크 시도
        config = DB_CONFIG.copy()
        config["host"] = "bip-postgres"
        return psycopg2.connect(**config)
    except:
        # 로컬 연결
        return psycopg2.connect(**DB_CONFIG)


def parse_date(date_val):
    """날짜 값을 파싱 (정수형 20240101 또는 문자열 2024-01-01)"""
    if pd.isna(date_val):
        return None

    date_str = str(date_val).strip()

    # 정수형 (20240101)
    if date_str.isdigit() and len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    # 이미 올바른 형식
    if '-' in date_str:
        return date_str[:10]  # YYYY-MM-DD 부분만

    return None


def extract_brands(orgs_str: str) -> list:
    """조직 문자열에서 브랜드 추출"""
    if pd.isna(orgs_str):
        return []

    brands = set()
    orgs_lower = orgs_str.lower()

    for brand, keywords in BRAND_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in orgs_lower:
                brands.add(brand)
                break

    return list(brands)


def extract_regions(locations_str: str) -> list:
    """위치 문자열에서 권역 추출"""
    if pd.isna(locations_str):
        return []

    regions = set()
    for loc in str(locations_str).split(';'):
        parts = loc.split('#')
        if len(parts) >= 3:
            country_code = parts[2]
            if country_code in COUNTRY_TO_REGION:
                regions.add(COUNTRY_TO_REGION[country_code])

    return list(regions)


def load_smartphone_news(csv_path: str, conn):
    """스마트폰 뉴스 CSV 적재"""
    logger.info(f"Loading smartphone news: {csv_path}")

    df = pd.read_csv(csv_path)
    if df.empty:
        return 0

    inserted = 0
    skipped = 0

    with conn.cursor() as cur:
        for _, row in df.iterrows():
            try:
                # 날짜 파싱
                collection_date = parse_date(row.get('collection_date') or row.get('date'))
                published_date = parse_date(row.get('date'))

                if not collection_date:
                    skipped += 1
                    continue

                # 1. news_raw에 삽입
                cur.execute("""
                    INSERT INTO news_raw (url, source, collection_date, published_date,
                                         themes, organizations, locations, tone_raw)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url, collection_date) DO NOTHING
                    RETURNING id
                """, (
                    row.get('url'),
                    row.get('source'),
                    collection_date,
                    published_date,
                    None,  # themes not in smartphone csv
                    row.get('organizations'),
                    None,  # locations not in smartphone csv
                    str(row.get('tone')) if pd.notna(row.get('tone')) else None
                ))

                result = cur.fetchone()
                if result is None:
                    skipped += 1
                    continue

                raw_id = result[0]

                # 2. 브랜드 추출
                brands = extract_brands(row.get('organizations', ''))

                # 3. news_article에 삽입
                cur.execute("""
                    INSERT INTO news_article (raw_id, url, source, published_date,
                                             news_type, brands, tone_score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING
                """, (
                    raw_id,
                    row.get('url'),
                    row.get('source'),
                    published_date,
                    'smartphone',
                    brands if brands else None,
                    float(row.get('tone')) if pd.notna(row.get('tone')) else None
                ))

                inserted += 1

                conn.commit()

            except Exception as e:
                conn.rollback()
                logger.debug(f"Error inserting row: {e}")
                skipped += 1
                continue

    logger.info(f"Smartphone news: {inserted} inserted, {skipped} skipped")
    return inserted


def load_external_factors(csv_path: str, conn):
    """외부 요인 뉴스 CSV 적재"""
    logger.info(f"Loading external factors: {csv_path}")

    df = pd.read_csv(csv_path)
    if df.empty:
        return 0

    # factor 이름 매핑
    factor_map = {
        'geopolitics': 'geopolitics',
        'economy': 'economy',
        'supply_chain': 'supply_chain',
        'regulation': 'regulation',
        'disaster': 'disaster'
    }

    inserted = 0
    skipped = 0

    with conn.cursor() as cur:
        for _, row in df.iterrows():
            try:
                factor = factor_map.get(row.get('factor'), row.get('factor_type'))
                if factor not in factor_map.values():
                    continue

                region = row.get('region')
                # 한글 권역명을 영문으로 변환 (이전 데이터 호환)
                region_map = {
                    '북미': 'North America',
                    '유럽': 'Western Europe',
                    '서유럽': 'Western Europe',
                    '중유럽': 'Central Europe',
                    '동유럽': 'Central Europe',
                    '동아시아': 'China',
                    '중국': 'China',
                    '일본': 'Japan',
                    '한국': 'South Korea',
                    '동남아': 'Southeast Asia',
                    '인도': 'India',
                    '중남미': 'CALA',
                    '중동': 'MEA',
                    '아프리카': 'MEA',
                    '오세아니아': 'Asia Pacific Others'
                }
                region = region_map.get(region, region)

                # 유효한 권역인지 확인
                valid_regions = list(REGION_COUNTRIES.keys())
                if region not in valid_regions:
                    skipped += 1
                    continue

                # 날짜 파싱
                collection_date = parse_date(row.get('collection_date') or row.get('date'))
                published_date = parse_date(row.get('date'))

                if not collection_date:
                    skipped += 1
                    continue

                # 1. news_raw에 삽입
                cur.execute("""
                    INSERT INTO news_raw (url, source, collection_date, published_date, tone_raw)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (url, collection_date) DO NOTHING
                    RETURNING id
                """, (
                    row.get('url'),
                    row.get('source'),
                    collection_date,
                    published_date,
                    str(row.get('tone')) if pd.notna(row.get('tone')) else None
                ))

                result = cur.fetchone()
                if result is None:
                    skipped += 1
                    continue

                raw_id = result[0]

                # 2. news_article에 삽입 (region_type[] 캐스팅 필요)
                cur.execute("""
                    INSERT INTO news_article (raw_id, url, source, published_date,
                                             news_type, factor, regions, tone_score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::region_type[], %s)
                    ON CONFLICT (url) DO NOTHING
                """, (
                    raw_id,
                    row.get('url'),
                    row.get('source'),
                    published_date,
                    'external_factor',
                    factor,
                    [region],
                    float(row.get('tone')) if pd.notna(row.get('tone')) else None
                ))

                inserted += 1

                conn.commit()

            except Exception as e:
                conn.rollback()
                logger.debug(f"Error inserting row: {e}")
                skipped += 1
                continue

    logger.info(f"External factors: {inserted} inserted, {skipped} skipped")
    return inserted


def load_all_data(data_dir: str = "./historical"):
    """모든 CSV 파일 적재"""
    conn = get_connection()

    total_smartphone = 0
    total_external = 0

    # 스마트폰 뉴스 로드
    smartphone_files = glob.glob(f"{data_dir}/smartphone_*.csv")
    for f in sorted(smartphone_files):
        total_smartphone += load_smartphone_news(f, conn)

    # 외부 요인 뉴스 로드
    external_files = glob.glob(f"{data_dir}/external_*.csv")
    for f in sorted(external_files):
        total_external += load_external_factors(f, conn)

    # output 디렉토리도 확인
    smartphone_files = glob.glob("./output/smartphone_*.csv")
    for f in sorted(smartphone_files):
        total_smartphone += load_smartphone_news(f, conn)

    external_files = glob.glob("./output/external_*.csv")
    for f in sorted(external_files):
        total_external += load_external_factors(f, conn)

    conn.close()

    logger.info(f"\n=== Load Complete ===")
    logger.info(f"Total smartphone news: {total_smartphone}")
    logger.info(f"Total external factors: {total_external}")

    return total_smartphone, total_external


def check_db_stats():
    """DB 통계 확인"""
    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM news_raw")
        raw_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM news_article")
        article_count = cur.fetchone()[0]

        cur.execute("""
            SELECT news_type, COUNT(*)
            FROM news_article
            GROUP BY news_type
        """)
        type_counts = cur.fetchall()

        cur.execute("""
            SELECT factor, COUNT(*)
            FROM news_article
            WHERE factor IS NOT NULL
            GROUP BY factor
        """)
        factor_counts = cur.fetchall()

        cur.execute("""
            SELECT unnest(regions) as region, COUNT(*)
            FROM news_article
            WHERE regions IS NOT NULL
            GROUP BY region
            ORDER BY COUNT(*) DESC
        """)
        region_counts = cur.fetchall()

    conn.close()

    print(f"\n=== DB Statistics ===")
    print(f"news_raw: {raw_count}")
    print(f"news_article: {article_count}")
    print(f"\nBy type:")
    for t, c in type_counts:
        print(f"  {t}: {c}")
    print(f"\nBy factor:")
    for f, c in factor_counts:
        print(f"  {f}: {c}")
    print(f"\nBy region:")
    for r, c in region_counts:
        print(f"  {r}: {c}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        check_db_stats()
    else:
        load_all_data()
        check_db_stats()
