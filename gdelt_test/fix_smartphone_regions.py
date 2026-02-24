"""
스마트폰 뉴스의 regions 필드 보정
소스 도메인 기반으로 권역 추론
"""

import psycopg2
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "user",
    "password": "pw1234",
    "dbname": "stockdb"
}

# 소스 도메인 -> 권역 매핑
SOURCE_TO_REGION = {
    # India
    "indiatimes.com": ["India"],
    "hindustantimes.com": ["India"],
    "livemint.com": ["India"],
    "ndtv.com": ["India"],
    "thehindu.com": ["India"],
    "economictimes.com": ["India"],
    "business-standard.com": ["India"],
    "moneycontrol.com": ["India"],
    "financialexpress.com": ["India"],

    # China
    "chinadaily.com.cn": ["China"],
    "gizchina.com": ["China"],
    "scmp.com": ["China"],
    "globaltimes.cn": ["China"],
    "xinhuanet.com": ["China"],
    "caixin.com": ["China"],
    "yicaiglobal.com": ["China"],

    # South Korea
    "koreatimes.co.kr": ["South Korea"],
    "koreaherald.com": ["South Korea"],
    "yna.co.kr": ["South Korea"],
    "mk.co.kr": ["South Korea"],
    "chosun.com": ["South Korea"],
    "donga.com": ["South Korea"],
    "etnews.com": ["South Korea"],

    # Japan
    "japantimes.co.jp": ["Japan"],
    "nikkei.com": ["Japan"],
    "asahi.com": ["Japan"],
    "mainichi.jp": ["Japan"],

    # Southeast Asia
    "talkvietnam.com": ["Southeast Asia"],
    "channelnewsasia.com": ["Southeast Asia"],
    "straitstimes.com": ["Southeast Asia"],
    "bangkokpost.com": ["Southeast Asia"],
    "thejakartapost.com": ["Southeast Asia"],
    "philstar.com": ["Southeast Asia"],
    "inquirer.net": ["Southeast Asia"],
    "vnexpress.net": ["Southeast Asia"],
    "nst.com.my": ["Southeast Asia"],

    # MEA (Middle East & Africa)
    "menafn.com": ["MEA"],
    "gulfnews.com": ["MEA"],
    "arabianbusiness.com": ["MEA"],
    "zawya.com": ["MEA"],
    "thenationalnews.com": ["MEA"],
    "aljazeera.com": ["MEA"],
    "news24.com": ["MEA"],  # South Africa
    "iol.co.za": ["MEA"],

    # Western Europe
    "finanznachrichten.de": ["Western Europe"],
    "bbc.co.uk": ["Western Europe"],
    "theguardian.com": ["Western Europe"],
    "ft.com": ["Western Europe"],
    "telegraph.co.uk": ["Western Europe"],
    "reuters.com": ["North America", "Western Europe"],  # Global
    "lemonde.fr": ["Western Europe"],
    "spiegel.de": ["Western Europe"],
    "elpais.com": ["Western Europe"],

    # Central Europe
    "pravda.com.ua": ["Central Europe"],
    "tass.com": ["Central Europe"],
    "ria.ru": ["Central Europe"],

    # CALA (Latin America)
    "infobae.com": ["CALA"],
    "eluniversal.com.mx": ["CALA"],
    "uol.com.br": ["CALA"],
    "clarin.com": ["CALA"],
    "elcomercio.pe": ["CALA"],

    # Asia Pacific Others
    "smh.com.au": ["Asia Pacific Others"],
    "abc.net.au": ["Asia Pacific Others"],
    "nzherald.co.nz": ["Asia Pacific Others"],
    "taipeitimes.com": ["Asia Pacific Others"],
    "focustaiwan.tw": ["Asia Pacific Others"],

    # North America (US/Canada)
    "bnnbloomberg.ca": ["North America"],
    "yahoo.com": ["North America"],
    "msn.com": ["North America"],
    "forbes.com": ["North America"],
    "washingtonpost.com": ["North America"],
    "nytimes.com": ["North America"],
    "cnbc.com": ["North America"],
    "cnn.com": ["North America"],
    "wsj.com": ["North America"],
    "bloomberg.com": ["North America"],
    "techcrunch.com": ["North America"],
    "theverge.com": ["North America"],
    "engadget.com": ["North America"],
    "cnet.com": ["North America"],
    "zdnet.com": ["North America"],
    "marketwatch.com": ["North America"],
    "benzinga.com": ["North America"],
    "prnewswire.com": ["North America"],
    "globenewswire.com": ["North America"],
    "businesswire.com": ["North America"],
}

# 기본값: 글로벌 뉴스는 주요 시장으로 배정
DEFAULT_REGIONS = ["North America", "Western Europe"]


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def infer_region_from_source(source: str) -> list:
    """소스 도메인에서 권역 추론"""
    if not source:
        return DEFAULT_REGIONS

    source_lower = source.lower()

    # 정확한 매칭 시도
    if source_lower in SOURCE_TO_REGION:
        return SOURCE_TO_REGION[source_lower]

    # 부분 매칭 시도
    for domain, regions in SOURCE_TO_REGION.items():
        if domain in source_lower or source_lower in domain:
            return regions

    # TLD 기반 추론
    tld_region = {
        ".cn": ["China"],
        ".in": ["India"],
        ".kr": ["South Korea"],
        ".jp": ["Japan"],
        ".de": ["Western Europe"],
        ".uk": ["Western Europe"],
        ".fr": ["Western Europe"],
        ".au": ["Asia Pacific Others"],
        ".nz": ["Asia Pacific Others"],
        ".tw": ["Asia Pacific Others"],
        ".br": ["CALA"],
        ".mx": ["CALA"],
        ".ru": ["Central Europe"],
        ".ae": ["MEA"],
        ".sa": ["MEA"],
        ".za": ["MEA"],
        ".sg": ["Southeast Asia"],
        ".my": ["Southeast Asia"],
        ".id": ["Southeast Asia"],
        ".vn": ["Southeast Asia"],
        ".th": ["Southeast Asia"],
        ".ph": ["Southeast Asia"],
    }

    for tld, regions in tld_region.items():
        if source_lower.endswith(tld):
            return regions

    # 매칭 실패시 기본값
    return DEFAULT_REGIONS


def update_smartphone_regions():
    """스마트폰 뉴스 regions 업데이트"""
    conn = get_connection()
    cur = conn.cursor()

    # 업데이트할 뉴스 조회
    cur.execute("""
        SELECT id, source
        FROM news_article
        WHERE news_type = 'smartphone'
          AND (regions IS NULL OR cardinality(regions) = 0)
    """)

    news_to_update = cur.fetchall()
    logger.info(f"Updating {len(news_to_update)} smartphone news articles")

    # 권역별 카운트
    region_counts = defaultdict(int)
    updates = []

    for news_id, source in news_to_update:
        regions = infer_region_from_source(source)
        updates.append((regions, news_id))
        for r in regions:
            region_counts[r] += 1

    # 배치 업데이트
    batch_size = 500
    updated = 0

    for i in range(0, len(updates), batch_size):
        batch = updates[i:i+batch_size]
        cur.executemany("""
            UPDATE news_article
            SET regions = %s::region_type[]
            WHERE id = %s
        """, batch)
        conn.commit()
        updated += len(batch)
        if updated % 2000 == 0:
            logger.info(f"  Updated {updated} records...")

    conn.close()

    logger.info(f"Total updated: {updated}")
    logger.info("Region distribution:")
    for region, count in sorted(region_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {region}: {count}")

    return updated


def verify_update():
    """업데이트 결과 확인"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            CASE WHEN regions IS NULL THEN 'NULL'
                 WHEN cardinality(regions) = 0 THEN 'EMPTY'
                 ELSE 'HAS_REGIONS' END as status,
            COUNT(*)
        FROM news_article
        WHERE news_type = 'smartphone'
        GROUP BY 1
    """)

    print("\n=== 업데이트 결과 ===")
    for status, count in cur.fetchall():
        print(f"  {status}: {count:,}")

    cur.execute("""
        SELECT unnest(regions) as region, COUNT(*) as cnt
        FROM news_article
        WHERE news_type = 'smartphone'
        GROUP BY region
        ORDER BY cnt DESC
    """)

    print("\n=== 권역별 분포 ===")
    for region, count in cur.fetchall():
        print(f"  {region}: {count:,}")

    conn.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        verify_update()
    else:
        update_smartphone_regions()
        verify_update()
