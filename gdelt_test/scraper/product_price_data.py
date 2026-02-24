"""
제품 가격 데이터 생성 및 적재
월별 가격 변동 시뮬레이션
"""

import psycopg2
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import random
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 세그먼트별 기본 가격 범위 (USD)
SEGMENT_PRICE_RANGE = {
    "flagship": (799, 1499),
    "mid-range": (299, 599),
    "entry": (99, 249),
}

# 브랜드별 프리미엄 계수
BRAND_PREMIUM = {
    "Apple": 1.15,
    "Samsung": 1.0,
    "Google": 0.95,
    "Sony": 1.1,
    "OnePlus": 0.85,
    "Xiaomi": 0.75,
    "OPPO": 0.8,
    "Vivo": 0.8,
    "Realme": 0.7,
    "Huawei": 0.9,
    "Honor": 0.8,
    "Motorola": 0.85,
    "Nothing": 0.85,
    "ASUS": 1.05,
    "Nubia": 0.9,
    "ZTE": 0.75,
    "Tecno": 0.6,
    "Infinix": 0.6,
    "Itel": 0.5,
}

# 권역별 가격 조정 계수
REGION_ADJUSTMENT = {
    "North America": 1.0,
    "Western Europe": 1.1,  # VAT 포함
    "Central Europe": 0.95,
    "China": 0.85,
    "India": 0.8,
    "Japan": 1.05,
    "South Korea": 0.95,
    "Southeast Asia": 0.9,
    "MEA": 0.95,
    "CALA": 1.0,
    "Asia Pacific Others": 1.0,
}

# 권역별 통화
REGION_CURRENCY = {
    "North America": "USD",
    "Western Europe": "EUR",
    "Central Europe": "EUR",
    "China": "CNY",
    "India": "INR",
    "Japan": "JPY",
    "South Korea": "KRW",
    "Southeast Asia": "USD",
    "MEA": "USD",
    "CALA": "USD",
    "Asia Pacific Others": "AUD",
}


def get_connection():
    return psycopg2.connect(
        host='localhost', port=5432, user='user', password='pw1234', dbname='stockdb'
    )


def calculate_price_depreciation(months_since_launch: int, segment: str) -> float:
    """
    출시 후 경과 월수에 따른 가격 하락률 계산

    - Flagship: 월 1.5% 하락, 최대 40% 하락
    - Mid-range: 월 2% 하락, 최대 50% 하락
    - Entry: 월 1% 하락, 최대 30% 하락
    """
    if segment == "flagship":
        monthly_rate = 0.015
        max_depreciation = 0.4
    elif segment == "mid-range":
        monthly_rate = 0.02
        max_depreciation = 0.5
    else:  # entry
        monthly_rate = 0.01
        max_depreciation = 0.3

    depreciation = min(months_since_launch * monthly_rate, max_depreciation)
    return 1 - depreciation


def generate_price_data():
    """가격 데이터 생성"""
    conn = get_connection()
    cur = conn.cursor()

    # 모든 제품 조회
    cur.execute("""
        SELECT id, brand, product_name, segment, release_date, regions
        FROM product_release
        WHERE release_date IS NOT NULL
        ORDER BY release_date
    """)
    products = cur.fetchall()

    conn.close()

    logger.info(f"Processing {len(products)} products")

    price_records = []

    for product in products:
        product_id, brand, product_name, segment, release_date, regions = product

        # regions 파싱 (PostgreSQL 배열 문자열 형식: {"North America","Western Europe"})
        if not regions:
            regions = ["North America"]
        elif isinstance(regions, str):
            # PostgreSQL 배열 문자열 파싱
            regions = regions.strip('{}').replace('"', '').split(',')
            regions = [r.strip() for r in regions if r.strip()]

        if not regions:
            regions = ["North America"]

        # 기본 가격 계산
        price_min, price_max = SEGMENT_PRICE_RANGE.get(segment, (299, 599))
        base_price = random.uniform(price_min, price_max)

        # 브랜드 프리미엄 적용
        brand_mult = BRAND_PREMIUM.get(brand, 0.9)
        base_price *= brand_mult

        # 특정 제품 가격 조정 (Ultra, Pro Max 등)
        name_lower = product_name.lower()
        if "ultra" in name_lower or "pro max" in name_lower:
            base_price *= 1.3
        elif "pro" in name_lower or "plus" in name_lower:
            base_price *= 1.15
        elif "mini" in name_lower or "lite" in name_lower or "se" in name_lower:
            base_price *= 0.8

        # 출시일부터 현재까지 월별 가격 생성
        current_date = release_date
        end_date = datetime(2024, 12, 31).date()

        month_count = 0
        while current_date <= end_date:
            # 월 첫째 날로 정규화
            price_date = current_date.replace(day=1)

            # 감가상각 계산
            depreciation = calculate_price_depreciation(month_count, segment)

            # 권역별 가격 생성
            for region in regions:
                region_mult = REGION_ADJUSTMENT.get(region, 1.0)

                # 최종 가격 계산
                final_price = base_price * depreciation * region_mult

                # 약간의 변동성 추가 (±3%)
                final_price *= random.uniform(0.97, 1.03)
                final_price = round(final_price, 2)

                # 현지 통화 가격 (간단한 환율 적용)
                currency = REGION_CURRENCY.get(region, "USD")
                if currency == "EUR":
                    price_local = final_price * 0.92
                elif currency == "CNY":
                    price_local = final_price * 7.2
                elif currency == "INR":
                    price_local = final_price * 83
                elif currency == "JPY":
                    price_local = final_price * 150
                elif currency == "KRW":
                    price_local = final_price * 1300
                elif currency == "AUD":
                    price_local = final_price * 1.5
                else:
                    price_local = final_price

                price_records.append({
                    "product_id": product_id,
                    "brand": brand,
                    "product_name": product_name,
                    "price_date": price_date,
                    "region": region,
                    "price_usd": final_price,
                    "price_local": round(price_local, 2),
                    "currency": currency,
                    "price_type": "retail"
                })

            # 다음 달로 이동
            current_date += relativedelta(months=1)
            month_count += 1

    logger.info(f"Generated {len(price_records)} price records")
    return price_records


def save_to_db(price_records):
    """DB에 저장"""
    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    errors = 0
    batch = []

    for record in price_records:
        batch.append((
            record["product_id"],
            record["brand"],
            record["product_name"],
            record["price_date"],
            record["region"],
            record["price_usd"],
            record["price_local"],
            record["currency"],
            record["price_type"]
        ))

        if len(batch) >= 500:
            try:
                cur.executemany("""
                    INSERT INTO product_price
                        (product_id, brand, product_name, price_date, region,
                         price_usd, price_local, currency, price_type)
                    VALUES (%s, %s, %s, %s, %s::region_type, %s, %s, %s, %s)
                    ON CONFLICT (product_name, price_date, region) DO NOTHING
                """, batch)
                conn.commit()
                inserted += len(batch)
                logger.info(f"  Inserted {inserted} records...")
            except Exception as e:
                logger.warning(f"Batch error: {e}")
                conn.rollback()
                errors += len(batch)
            batch = []

    # 남은 배치 처리
    if batch:
        try:
            cur.executemany("""
                INSERT INTO product_price
                    (product_id, brand, product_name, price_date, region,
                     price_usd, price_local, currency, price_type)
                VALUES (%s, %s, %s, %s, %s::region_type, %s, %s, %s, %s)
                ON CONFLICT (product_name, price_date, region) DO NOTHING
            """, batch)
            conn.commit()
            inserted += len(batch)
        except Exception as e:
            logger.warning(f"Final batch error: {e}")
            conn.rollback()
            errors += len(batch)

    conn.close()

    logger.info(f"Total inserted: {inserted}, errors: {errors}")
    return inserted


def check_stats():
    """통계 확인"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM product_price")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT brand, COUNT(DISTINCT product_name), COUNT(*)
        FROM product_price
        GROUP BY brand
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """)
    by_brand = cur.fetchall()

    cur.execute("""
        SELECT region, COUNT(*), AVG(price_usd)
        FROM product_price
        GROUP BY region
        ORDER BY COUNT(*) DESC
    """)
    by_region = cur.fetchall()

    cur.execute("""
        SELECT
            EXTRACT(YEAR FROM price_date) as year,
            COUNT(*),
            AVG(price_usd)
        FROM product_price
        GROUP BY year
        ORDER BY year
    """)
    by_year = cur.fetchall()

    cur.execute("""
        SELECT product_name, MIN(price_usd), MAX(price_usd),
               MAX(price_usd) - MIN(price_usd) as price_drop
        FROM product_price
        WHERE region = 'North America'
        GROUP BY product_name
        ORDER BY price_drop DESC
        LIMIT 5
    """)
    top_drops = cur.fetchall()

    conn.close()

    print(f"\n=== Product Price Stats ===")
    print(f"Total records: {total:,}")

    print(f"\nTop Brands:")
    for brand, products, records in by_brand:
        print(f"  {brand}: {products} products, {records:,} price records")

    print(f"\nBy Region:")
    for region, count, avg_price in by_region:
        print(f"  {region}: {count:,} records, avg ${avg_price:.0f}")

    print(f"\nBy Year:")
    for year, count, avg_price in by_year:
        print(f"  {int(year)}: {count:,} records, avg ${avg_price:.0f}")

    print(f"\nTop Price Drops (North America):")
    for name, min_p, max_p, drop in top_drops:
        print(f"  {name}: ${max_p:.0f} → ${min_p:.0f} (-${drop:.0f})")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        check_stats()
    else:
        price_records = generate_price_data()
        save_to_db(price_records)
        check_stats()
