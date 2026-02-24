"""
수요예측 설명 에이전트용 Tools
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import psycopg2
from psycopg2.extras import RealDictCursor

# DB 연결 설정
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "user",
    "password": "pw1234",
    "dbname": "stockdb"
}


def get_connection():
    """DB 연결"""
    try:
        config = DB_CONFIG.copy()
        config["host"] = "bip-postgres"
        return psycopg2.connect(**config)
    except:
        return psycopg2.connect(**DB_CONFIG)


# =============================================================================
# Tool Definitions (for LLM)
# =============================================================================

TOOL_DEFINITIONS = [
    {
        "name": "search_news",
        "description": "Search news articles by keywords, region, factor type, and date range. Returns specific articles with URLs, sources, and tone scores. Use this to find concrete evidence and cite specific news sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords to search for (e.g., ['Samsung', 'Galaxy', 'chip shortage'])"
                },
                "region": {
                    "type": "string",
                    "enum": ["North America", "Western Europe", "Central Europe", "China", "India", "Japan", "South Korea", "Southeast Asia", "MEA", "CALA", "Asia Pacific Others"],
                    "description": "Region to filter by"
                },
                "factor": {
                    "type": "string",
                    "enum": ["geopolitics", "economy", "supply_chain", "regulation", "disaster"],
                    "description": "External factor type to filter by"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 10)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_news_summary",
        "description": "Get aggregated news statistics for a region over a time period. Returns total article counts, average sentiment tone (-10 to +10), and tone trends (improving/stable/worsening). Use this first to understand the overall news landscape before diving into details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "enum": ["North America", "Western Europe", "Central Europe", "China", "India", "Japan", "South Korea", "Southeast Asia", "MEA", "CALA", "Asia Pacific Others"],
                    "description": "Region to analyze"
                },
                "factor": {
                    "type": "string",
                    "enum": ["geopolitics", "economy", "supply_chain", "regulation", "disaster"],
                    "description": "External factor type (optional - omit to get all factors)"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                }
            },
            "required": ["region", "start_date", "end_date"]
        }
    },
    {
        "name": "get_daily_trend",
        "description": "Get daily time-series data for news coverage and sentiment. Returns daily article counts and average tone scores. Use this to identify specific dates with unusual activity or sentiment shifts that may explain demand anomalies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "enum": ["North America", "Western Europe", "Central Europe", "China", "India", "Japan", "South Korea", "Southeast Asia", "MEA", "CALA", "Asia Pacific Others"],
                    "description": "Region"
                },
                "factor": {
                    "type": "string",
                    "enum": ["geopolitics", "economy", "supply_chain", "regulation", "disaster", "smartphone"],
                    "description": "Factor type to analyze (use 'smartphone' for direct smartphone news)"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                }
            },
            "required": ["region", "factor", "start_date", "end_date"]
        }
    },
    {
        "name": "get_product_releases",
        "description": "Get smartphone product launch information. Returns brand, product name, segment, announce/release dates. Use this to understand how new product launches may drive or shift demand between segments or brands.",
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": {
                    "type": "string",
                    "description": "Brand name (e.g., 'Samsung', 'Apple', 'Xiaomi')"
                },
                "segment": {
                    "type": "string",
                    "enum": ["entry", "mid-range", "flagship"],
                    "description": "Product segment"
                },
                "region": {
                    "type": "string",
                    "enum": ["North America", "Western Europe", "Central Europe", "China", "India", "Japan", "South Korea", "Southeast Asia", "MEA", "CALA", "Asia Pacific Others"],
                    "description": "Release region"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_product_prices",
        "description": "Get smartphone price trends over time. Returns price history, depreciation rates, and price changes. Use this to analyze how pricing strategies, discounts, or price drops may affect demand.",
        "input_schema": {
            "type": "object",
            "properties": {
                "brand": {
                    "type": "string",
                    "description": "Brand name (e.g., 'Samsung', 'Apple', 'Xiaomi')"
                },
                "product_name": {
                    "type": "string",
                    "description": "Product name (e.g., 'iPhone 14 Pro', 'Galaxy S23 Ultra')"
                },
                "segment": {
                    "type": "string",
                    "enum": ["entry", "mid-range", "flagship"],
                    "description": "Product segment"
                },
                "region": {
                    "type": "string",
                    "enum": ["North America", "Western Europe", "Central Europe", "China", "India", "Japan", "South Korea", "Southeast Asia", "MEA", "CALA", "Asia Pacific Others"],
                    "description": "Region for pricing"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_macro_indicators",
        "description": "Get macroeconomic indicators: exchange_rate (vs USD), interest_rate, pmi (purchasing managers index), cpi (consumer price index), gdp_growth. Use this to understand how economic conditions affect consumer purchasing power and demand.",
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "enum": ["North America", "Western Europe", "Central Europe", "China", "India", "Japan", "South Korea", "Southeast Asia", "MEA", "CALA", "Asia Pacific Others"],
                    "description": "Region"
                },
                "indicator_type": {
                    "type": "string",
                    "enum": ["exchange_rate", "interest_rate", "pmi", "cpi", "gdp_growth"],
                    "description": "Type of indicator"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                }
            },
            "required": ["region", "indicator_type", "start_date", "end_date"]
        }
    }
]


# =============================================================================
# Tool Implementations
# =============================================================================

def search_news(
    keywords: List[str] = None,
    region: str = None,
    factor: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 10
) -> List[Dict]:
    """뉴스 검색"""
    conn = get_connection()

    query = """
        SELECT
            url,
            source,
            published_date,
            news_type,
            factor,
            regions,
            brands,
            tone_score
        FROM news_article
        WHERE 1=1
    """
    params = []

    if region:
        query += " AND %s = ANY(regions)"
        params.append(region)

    if factor:
        query += " AND factor = %s"
        params.append(factor)

    if start_date:
        query += " AND published_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND published_date <= %s"
        params.append(end_date)

    # 키워드 검색은 URL 기반 (향후 벡터 검색으로 개선)
    if keywords:
        keyword_conditions = []
        for kw in keywords:
            keyword_conditions.append("url ILIKE %s")
            params.append(f"%{kw}%")
        query += f" AND ({' OR '.join(keyword_conditions)})"

    query += " ORDER BY published_date DESC LIMIT %s"
    params.append(limit)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        results = cur.fetchall()

    conn.close()

    return [dict(r) for r in results]


def get_news_summary(
    region: str,
    start_date: str,
    end_date: str,
    factor: str = None
) -> Dict:
    """뉴스 요약 통계"""
    conn = get_connection()

    # 기본 통계
    query = """
        SELECT
            COUNT(*) as total_articles,
            AVG(tone_score) as avg_tone,
            MIN(tone_score) as min_tone,
            MAX(tone_score) as max_tone
        FROM news_article
        WHERE %s = ANY(regions)
          AND published_date >= %s
          AND published_date <= %s
    """
    params = [region, start_date, end_date]

    if factor:
        query += " AND factor = %s"
        params.append(factor)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        stats = dict(cur.fetchone())

        # 일별 톤 추이 (트렌드 계산용)
        trend_query = """
            SELECT
                DATE_TRUNC('week', published_date) as week,
                AVG(tone_score) as avg_tone
            FROM news_article
            WHERE %s = ANY(regions)
              AND published_date >= %s
              AND published_date <= %s
        """
        trend_params = [region, start_date, end_date]

        if factor:
            trend_query += " AND factor = %s"
            trend_params.append(factor)

        trend_query += " GROUP BY week ORDER BY week"

        cur.execute(trend_query, trend_params)
        weekly_tones = cur.fetchall()

    conn.close()

    # 트렌드 계산
    if len(weekly_tones) >= 2:
        first_half = [r['avg_tone'] for r in weekly_tones[:len(weekly_tones)//2] if r['avg_tone']]
        second_half = [r['avg_tone'] for r in weekly_tones[len(weekly_tones)//2:] if r['avg_tone']]

        if first_half and second_half:
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)

            if avg_second > avg_first + 0.5:
                trend = "improving"
            elif avg_second < avg_first - 0.5:
                trend = "worsening"
            else:
                trend = "stable"
        else:
            trend = "unknown"
    else:
        trend = "insufficient_data"

    return {
        "region": region,
        "factor": factor,
        "period": f"{start_date} ~ {end_date}",
        "total_articles": stats['total_articles'],
        "avg_tone": round(stats['avg_tone'], 2) if stats['avg_tone'] else None,
        "tone_range": {
            "min": round(stats['min_tone'], 2) if stats['min_tone'] else None,
            "max": round(stats['max_tone'], 2) if stats['max_tone'] else None
        },
        "tone_trend": trend
    }


def get_product_releases(
    brand: str = None,
    segment: str = None,
    region: str = None,
    start_date: str = None,
    end_date: str = None
) -> List[Dict]:
    """제품 출시 정보"""
    conn = get_connection()

    query = """
        SELECT
            brand,
            product_name,
            segment,
            announce_date,
            release_date,
            regions
        FROM product_release
        WHERE 1=1
    """
    params = []

    if brand:
        query += " AND brand ILIKE %s"
        params.append(f"%{brand}%")

    if segment:
        query += " AND segment = %s"
        params.append(segment)

    if region:
        query += " AND %s = ANY(regions)"
        params.append(region)

    if start_date:
        query += " AND release_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND release_date <= %s"
        params.append(end_date)

    query += " ORDER BY release_date DESC"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        results = cur.fetchall()

    conn.close()

    return [dict(r) for r in results]


def get_macro_indicators(
    region: str,
    indicator_type: str,
    start_date: str,
    end_date: str
) -> Dict:
    """거시경제 지표"""
    conn = get_connection()

    query = """
        SELECT
            indicator_date,
            value,
            change_pct
        FROM macro_indicators
        WHERE region = %s
          AND indicator_type = %s
          AND indicator_date >= %s
          AND indicator_date <= %s
        ORDER BY indicator_date
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, [region, indicator_type, start_date, end_date])
        results = cur.fetchall()

    conn.close()

    if not results:
        return {
            "region": region,
            "indicator": indicator_type,
            "data": [],
            "message": "No data available"
        }

    values = [dict(r) for r in results]

    # 트렌드 계산
    if len(values) >= 2:
        first_val = values[0]['value']
        last_val = values[-1]['value']
        if first_val and last_val:
            change = (last_val - first_val) / first_val * 100
            if change > 2:
                trend = "increasing"
            elif change < -2:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "unknown"
    else:
        trend = "insufficient_data"

    return {
        "region": region,
        "indicator": indicator_type,
        "period": f"{start_date} ~ {end_date}",
        "values": values,
        "trend": trend
    }


def get_product_prices(
    brand: str = None,
    product_name: str = None,
    segment: str = None,
    region: str = None,
    start_date: str = None,
    end_date: str = None
) -> Dict:
    """제품 가격 정보 조회"""
    conn = get_connection()

    query = """
        SELECT
            pp.brand,
            pp.product_name,
            pp.price_date,
            pp.region,
            pp.price_usd,
            pp.price_type,
            pr.segment,
            pr.release_date
        FROM product_price pp
        JOIN product_release pr ON pp.product_id = pr.id
        WHERE 1=1
    """
    params = []

    if brand:
        query += " AND pp.brand ILIKE %s"
        params.append(f"%{brand}%")

    if product_name:
        query += " AND pp.product_name ILIKE %s"
        params.append(f"%{product_name}%")

    if segment:
        query += " AND pr.segment = %s"
        params.append(segment)

    if region:
        query += " AND pp.region = %s"
        params.append(region)

    if start_date:
        query += " AND pp.price_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND pp.price_date <= %s"
        params.append(end_date)

    query += " ORDER BY pp.product_name, pp.price_date"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        results = cur.fetchall()

    conn.close()

    if not results:
        return {
            "products": [],
            "message": "No price data found",
            "filters": {
                "brand": brand,
                "product_name": product_name,
                "segment": segment,
                "region": region
            }
        }

    # 제품별 가격 데이터 그룹화
    products = {}
    for row in results:
        key = row['product_name']
        if key not in products:
            products[key] = {
                "brand": row['brand'],
                "product_name": row['product_name'],
                "segment": row['segment'],
                "release_date": str(row['release_date']) if row['release_date'] else None,
                "region": row['region'],
                "prices": []
            }
        products[key]["prices"].append({
            "date": str(row['price_date']),
            "price_usd": float(row['price_usd'])
        })

    # 가격 변동 통계 계산
    product_summaries = []
    for prod in products.values():
        prices = prod["prices"]
        if len(prices) >= 2:
            first_price = prices[0]["price_usd"]
            last_price = prices[-1]["price_usd"]
            depreciation_pct = round((1 - last_price / first_price) * 100, 1)
            monthly_rate = round(depreciation_pct / len(prices), 2)
        else:
            depreciation_pct = 0
            monthly_rate = 0

        product_summaries.append({
            "brand": prod["brand"],
            "product_name": prod["product_name"],
            "segment": prod["segment"],
            "release_date": prod["release_date"],
            "region": prod["region"],
            "first_price": prices[0]["price_usd"] if prices else None,
            "latest_price": prices[-1]["price_usd"] if prices else None,
            "depreciation_pct": depreciation_pct,
            "monthly_depreciation_rate": monthly_rate,
            "price_history": prices[-12:]  # 최근 12개월만
        })

    return {
        "total_products": len(product_summaries),
        "filters": {
            "brand": brand,
            "product_name": product_name,
            "segment": segment,
            "region": region,
            "period": f"{start_date or 'all'} ~ {end_date or 'all'}"
        },
        "products": product_summaries[:20],  # 최대 20개 제품
        "note": "Prices based on research-estimated depreciation (SellCell/BankMyCell data)"
    }


def get_daily_trend(
    region: str,
    factor: str,
    start_date: str,
    end_date: str
) -> Dict:
    """일별 트렌드 조회 (news_daily_summary 테이블)"""
    conn = get_connection()

    factor_count = f"{factor}_count"
    factor_tone = f"{factor}_avg_tone"

    query = f"""
        SELECT summary_date, {factor_count} as count, {factor_tone} as avg_tone
        FROM news_daily_summary
        WHERE region = %s
          AND summary_date >= %s
          AND summary_date <= %s
        ORDER BY summary_date
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, [region, start_date, end_date])
        results = cur.fetchall()

    conn.close()

    if not results:
        return {
            "region": region,
            "factor": factor,
            "data": [],
            "message": "No data available"
        }

    daily_data = [dict(r) for r in results]

    # 통계 계산
    total_count = sum(d['count'] or 0 for d in daily_data)
    tones = [d['avg_tone'] for d in daily_data if d['avg_tone'] is not None]
    avg_tone = sum(tones) / len(tones) if tones else None

    # 트렌드 계산 (전반부 vs 후반부)
    if len(tones) >= 4:
        first_half = tones[:len(tones)//2]
        second_half = tones[len(tones)//2:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)

        if avg_second > avg_first + 0.3:
            trend = "improving"
        elif avg_second < avg_first - 0.3:
            trend = "worsening"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"

    return {
        "region": region,
        "factor": factor,
        "period": f"{start_date} ~ {end_date}",
        "total_articles": total_count,
        "avg_tone": round(avg_tone, 2) if avg_tone else None,
        "trend": trend,
        "daily_data": daily_data[:30]  # 최대 30일만 반환
    }


# =============================================================================
# Tool Executor
# =============================================================================

TOOL_FUNCTIONS = {
    "search_news": search_news,
    "get_news_summary": get_news_summary,
    "get_daily_trend": get_daily_trend,
    "get_product_releases": get_product_releases,
    "get_product_prices": get_product_prices,
    "get_macro_indicators": get_macro_indicators,
}


def execute_tool(tool_name: str, parameters: Dict) -> Any:
    """Tool 실행"""
    if tool_name not in TOOL_FUNCTIONS:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return TOOL_FUNCTIONS[tool_name](**parameters)
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    # 테스트
    print("=== Testing search_news ===")
    results = search_news(region="North America", limit=3)
    print(f"Found {len(results)} articles")

    print("\n=== Testing get_news_summary ===")
    summary = get_news_summary(
        region="China",
        factor="geopolitics",
        start_date="2020-01-01",
        end_date="2020-06-30"
    )
    print(summary)

    print("\n=== Testing get_daily_trend ===")
    trend = get_daily_trend(
        region="North America",
        factor="economy",
        start_date="2020-01-01",
        end_date="2020-03-31"
    )
    print(f"Total articles: {trend['total_articles']}, Trend: {trend['trend']}")

    print("\n=== Testing get_product_releases ===")
    releases = get_product_releases(
        brand="Samsung",
        segment="flagship",
        start_date="2023-01-01",
        end_date="2024-12-31"
    )
    print(f"Found {len(releases)} products")

    print("\n=== Testing get_product_prices ===")
    prices = get_product_prices(
        brand="Apple",
        region="North America",
        start_date="2022-01-01",
        end_date="2024-12-31"
    )
    print(f"Found {prices['total_products']} products")
    for p in prices['products'][:3]:
        print(f"  {p['product_name']}: ${p['first_price']} → ${p['latest_price']} (-{p['depreciation_pct']}%)")

    print("\n=== Testing get_macro_indicators ===")
    macro = get_macro_indicators(
        region="North America",
        indicator_type="interest_rate",
        start_date="2023-01-01",
        end_date="2023-12-31"
    )
    print(f"Trend: {macro.get('trend', 'N/A')}, Values: {len(macro.get('values', []))} records")
