"""
뉴스 데이터 일별 집계
news_article → news_daily_summary
"""

import psycopg2
from psycopg2.extras import execute_values
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "user",
    "password": "pw1234",
    "dbname": "stockdb"
}


def get_connection():
    try:
        config = DB_CONFIG.copy()
        config["host"] = "bip-postgres"
        return psycopg2.connect(**config)
    except:
        return psycopg2.connect(**DB_CONFIG)


def aggregate_daily_summary():
    """일별 요약 집계 실행"""
    conn = get_connection()
    cur = conn.cursor()

    logger.info("Starting daily aggregation...")

    # 집계 쿼리 - 날짜 & 권역별로 통계 계산
    aggregate_query = """
    INSERT INTO news_daily_summary (
        summary_date, region,
        smartphone_count, smartphone_avg_tone,
        geopolitics_count, geopolitics_avg_tone,
        economy_count, economy_avg_tone,
        supply_chain_count, supply_chain_avg_tone,
        regulation_count, regulation_avg_tone,
        disaster_count, disaster_avg_tone
    )
    SELECT
        published_date as summary_date,
        unnest(regions) as region,

        -- 스마트폰 뉴스
        COUNT(*) FILTER (WHERE news_type = 'smartphone') as smartphone_count,
        AVG(tone_score) FILTER (WHERE news_type = 'smartphone') as smartphone_avg_tone,

        -- 외부 요인별
        COUNT(*) FILTER (WHERE factor = 'geopolitics') as geopolitics_count,
        AVG(tone_score) FILTER (WHERE factor = 'geopolitics') as geopolitics_avg_tone,

        COUNT(*) FILTER (WHERE factor = 'economy') as economy_count,
        AVG(tone_score) FILTER (WHERE factor = 'economy') as economy_avg_tone,

        COUNT(*) FILTER (WHERE factor = 'supply_chain') as supply_chain_count,
        AVG(tone_score) FILTER (WHERE factor = 'supply_chain') as supply_chain_avg_tone,

        COUNT(*) FILTER (WHERE factor = 'regulation') as regulation_count,
        AVG(tone_score) FILTER (WHERE factor = 'regulation') as regulation_avg_tone,

        COUNT(*) FILTER (WHERE factor = 'disaster') as disaster_count,
        AVG(tone_score) FILTER (WHERE factor = 'disaster') as disaster_avg_tone

    FROM news_article
    WHERE published_date IS NOT NULL
      AND regions IS NOT NULL
    GROUP BY published_date, unnest(regions)
    ON CONFLICT (summary_date, region)
    DO UPDATE SET
        smartphone_count = EXCLUDED.smartphone_count,
        smartphone_avg_tone = EXCLUDED.smartphone_avg_tone,
        geopolitics_count = EXCLUDED.geopolitics_count,
        geopolitics_avg_tone = EXCLUDED.geopolitics_avg_tone,
        economy_count = EXCLUDED.economy_count,
        economy_avg_tone = EXCLUDED.economy_avg_tone,
        supply_chain_count = EXCLUDED.supply_chain_count,
        supply_chain_avg_tone = EXCLUDED.supply_chain_avg_tone,
        regulation_count = EXCLUDED.regulation_count,
        regulation_avg_tone = EXCLUDED.regulation_avg_tone,
        disaster_count = EXCLUDED.disaster_count,
        disaster_avg_tone = EXCLUDED.disaster_avg_tone
    """

    try:
        cur.execute(aggregate_query)
        rows_affected = cur.rowcount
        conn.commit()
        logger.info(f"Aggregated {rows_affected} daily summaries")
    except Exception as e:
        conn.rollback()
        logger.error(f"Aggregation failed: {e}")
        raise

    # 결과 확인
    cur.execute("SELECT COUNT(*) FROM news_daily_summary")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT MIN(summary_date), MAX(summary_date)
        FROM news_daily_summary
    """)
    date_range = cur.fetchone()

    cur.execute("""
        SELECT region, COUNT(*),
               SUM(smartphone_count) as smartphone,
               SUM(geopolitics_count) as geopolitics,
               SUM(economy_count) as economy
        FROM news_daily_summary
        GROUP BY region
        ORDER BY COUNT(*) DESC
    """)
    by_region = cur.fetchall()

    conn.close()

    print(f"\n=== 집계 완료 ===")
    print(f"총 레코드: {total}")
    print(f"기간: {date_range[0]} ~ {date_range[1]}")
    print(f"\n권역별 통계:")
    print(f"{'권역':<25} {'일수':>6} {'스마트폰':>10} {'지정학':>10} {'경제':>10}")
    print("-" * 65)
    for region, days, smartphone, geopolitics, economy in by_region:
        print(f"{region:<25} {days:>6} {smartphone or 0:>10} {geopolitics or 0:>10} {economy or 0:>10}")

    return total


def get_daily_trend(region: str, factor: str, start_date: str, end_date: str):
    """일별 트렌드 조회"""
    conn = get_connection()
    cur = conn.cursor()

    factor_count = f"{factor}_count"
    factor_tone = f"{factor}_avg_tone"

    cur.execute(f"""
        SELECT summary_date, {factor_count}, {factor_tone}
        FROM news_daily_summary
        WHERE region = %s
          AND summary_date >= %s
          AND summary_date <= %s
        ORDER BY summary_date
    """, [region, start_date, end_date])

    results = cur.fetchall()
    conn.close()

    return results


def get_weekly_summary(region: str, start_date: str, end_date: str):
    """주간 집계"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            DATE_TRUNC('week', summary_date) as week,
            SUM(smartphone_count) as smartphone,
            AVG(smartphone_avg_tone) as smartphone_tone,
            SUM(geopolitics_count) as geopolitics,
            AVG(geopolitics_avg_tone) as geopolitics_tone,
            SUM(economy_count) as economy,
            AVG(economy_avg_tone) as economy_tone
        FROM news_daily_summary
        WHERE region = %s
          AND summary_date >= %s
          AND summary_date <= %s
        GROUP BY DATE_TRUNC('week', summary_date)
        ORDER BY week
    """, [region, start_date, end_date])

    results = cur.fetchall()
    conn.close()

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "trend":
        # 트렌드 조회: python aggregate_daily.py trend "North America" economy 2020-01-01 2020-03-31
        region = sys.argv[2]
        factor = sys.argv[3]
        start = sys.argv[4]
        end = sys.argv[5]

        results = get_daily_trend(region, factor, start, end)
        print(f"\n{region} - {factor} 일별 트렌드 ({start} ~ {end})")
        print(f"{'날짜':<12} {'기사수':>8} {'평균톤':>10}")
        print("-" * 32)
        for date, count, tone in results[:20]:
            print(f"{date} {count:>8} {tone:>10.2f}" if tone else f"{date} {count:>8} {'N/A':>10}")
    else:
        # 집계 실행
        aggregate_daily_summary()
