"""
스마트폰 관련 글로벌 뉴스 수집 스크립트
GDELT GKG 데이터에서 스마트폰 제조사/제품 관련 뉴스 추출
"""

import pandas as pd
from datetime import datetime, timedelta
from gdelt_parser import GDELTCollector
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 스마트폰 관련 검색어 (정확한 매칭)
SMARTPHONE_SEARCH = {
    # 조직명 (정확히 매칭되어야 함)
    "organizations_strict": [
        "Samsung Electronics",
        "Xiaomi",
        "Huawei",
        "OPPO",
        "Vivo",
        "OnePlus",
    ],
    # 테마 (정확히 매칭)
    "themes_strict": [
        "SMARTPHONE",
        "MOBILE_PHONE",
    ],
    # URL 패턴 (기사 URL에 포함되면 관련 가능성 높음)
    "url_patterns": [
        "smartphone", "galaxy", "iphone", "pixel", "xiaomi", "huawei",
        "mobile-phone", "handset", "android-phone"
    ]
}

# 외부 요인 (수요에 영향을 주는 요소)
EXTERNAL_FACTORS = {
    "geopolitics": ["MILITARY", "CONFLICT", "WAR", "SANCTION", "TRADE_DISPUTE", "TARIFF"],
    "economy": ["ECONOMIC", "INFLATION", "RECESSION", "INTEREST_RATE", "CURRENCY", "GDP"],
    "supply_chain": ["SUPPLY_CHAIN", "SEMICONDUCTOR", "CHIP", "SHORTAGE", "LOGISTICS", "MANUFACTURING"],
    "regulation": ["REGULATION", "LEGISLATION", "BAN", "RESTRICTION", "PRIVACY", "ANTITRUST"],
    "disaster": ["PANDEMIC", "NATURAL_DISASTER", "EARTHQUAKE", "FLOOD", "HURRICANE"],
}


def collect_daily_news(date_str: str, output_dir: str = "./output") -> dict:
    """
    특정 날짜의 뉴스 수집

    Args:
        date_str: YYYY-MM-DD 형식
        output_dir: 출력 디렉토리

    Returns:
        수집 통계 dict
    """
    collector = GDELTCollector()
    date_formatted = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y%m%d")

    # 파일 목록 조회
    files = collector.get_file_list(date_formatted)
    if not files:
        logger.warning(f"No files found for {date_str}")
        return {"date": date_str, "files": 0, "articles": 0}

    # 샘플링: 매 2시간마다 (12개 파일/일)
    sampled_files = files[::8]  # 96개 중 12개 선택
    logger.info(f"{date_str}: Processing {len(sampled_files)} files (sampled from {len(files)})")

    all_smartphone = []
    all_external = []

    for idx, file_url in enumerate(sampled_files, 1):
        try:
            df = collector.download_and_parse(file_url)

            # 스마트폰 관련 뉴스 추출
            smartphone_df = extract_smartphone_news(df, collector)
            if not smartphone_df.empty:
                smartphone_df['collection_date'] = date_str
                all_smartphone.append(smartphone_df)

            # 외부 요인 뉴스 추출 (권역별)
            for region in ["North America", "Western Europe", "Central Europe",
                          "China", "India", "Japan", "South Korea", "Southeast Asia",
                          "MEA", "CALA", "Asia Pacific Others"]:
                external_df = extract_external_factors(df, collector, region)
                if not external_df.empty:
                    external_df['collection_date'] = date_str
                    external_df['region'] = region
                    all_external.append(external_df)

            if idx % 3 == 0:
                logger.info(f"  Progress: {idx}/{len(sampled_files)} files processed")

        except Exception as e:
            logger.warning(f"Error processing {file_url}: {e}")
            continue

    # 결과 저장
    os.makedirs(output_dir, exist_ok=True)

    stats = {"date": date_str, "files": len(sampled_files)}

    if all_smartphone:
        smartphone_result = pd.concat(all_smartphone, ignore_index=True)
        smartphone_result = smartphone_result.drop_duplicates(subset=['url'])
        smartphone_file = f"{output_dir}/smartphone_news_{date_formatted}.csv"
        smartphone_result.to_csv(smartphone_file, index=False)
        stats['smartphone_articles'] = len(smartphone_result)
        logger.info(f"Saved {len(smartphone_result)} smartphone articles to {smartphone_file}")

    if all_external:
        external_result = pd.concat(all_external, ignore_index=True)
        external_result = external_result.drop_duplicates(subset=['url', 'region'])
        external_file = f"{output_dir}/external_factors_{date_formatted}.csv"
        external_result.to_csv(external_file, index=False)
        stats['external_articles'] = len(external_result)
        logger.info(f"Saved {len(external_result)} external factor articles to {external_file}")

    return stats


def extract_smartphone_news(df: pd.DataFrame, collector: GDELTCollector) -> pd.DataFrame:
    """스마트폰 관련 뉴스 추출 (정확한 필터링)"""
    # 1. Organizations에서 정확한 브랜드명 검색
    org_pattern = '|'.join(SMARTPHONE_SEARCH['organizations_strict'])
    mask_org = df['V2Organizations'].str.contains(org_pattern, case=False, na=False)

    # 2. Themes에서 정확한 테마 검색
    theme_pattern = '|'.join(SMARTPHONE_SEARCH['themes_strict'])
    mask_theme = df['Themes'].str.contains(theme_pattern, case=False, na=False)

    # 3. URL에서 스마트폰 관련 키워드 검색
    url_pattern = '|'.join(SMARTPHONE_SEARCH['url_patterns'])
    mask_url = df['DocumentIdentifier'].str.contains(url_pattern, case=False, na=False)

    # 조직명 + (테마 OR URL) 조합으로 더 정확한 필터링
    # 또는 테마가 SMARTPHONE/MOBILE_PHONE이면서 URL도 관련 키워드 포함
    filtered = df[mask_org | (mask_theme & mask_url) | (mask_org & mask_theme)].copy()

    if filtered.empty:
        return pd.DataFrame()

    # 정제
    result = pd.DataFrame({
        'date': pd.to_datetime(filtered['DATE'].str[:8], format='%Y%m%d', errors='coerce'),
        'source': filtered['SourceCommonName'],
        'url': filtered['DocumentIdentifier'],
        'themes': filtered['Themes'],
        'organizations': filtered['V2Organizations'],
        'tone': filtered['V2Tone'].apply(lambda x: collector.parse_tone(x)['tone']),
        'locations': filtered['V2Locations'],
    })

    return result


def extract_external_factors(df: pd.DataFrame, collector: GDELTCollector, region: str) -> pd.DataFrame:
    """권역별 외부 요인 뉴스 추출"""
    # 권역 필터
    region_df = collector.filter_by_region(df, region)
    if region_df.empty:
        return pd.DataFrame()

    results = []
    for factor_name, keywords in EXTERNAL_FACTORS.items():
        pattern = '|'.join(keywords)
        mask = region_df['Themes'].str.contains(pattern, case=False, na=False)
        factor_df = region_df[mask].copy()

        if not factor_df.empty:
            factor_result = pd.DataFrame({
                'date': pd.to_datetime(factor_df['DATE'].str[:8], format='%Y%m%d', errors='coerce'),
                'source': factor_df['SourceCommonName'],
                'url': factor_df['DocumentIdentifier'],
                'factor_type': factor_name,
                'themes': factor_df['Themes'],
                'tone': factor_df['V2Tone'].apply(lambda x: collector.parse_tone(x)['tone']),
            })
            results.append(factor_result)

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)


def collect_date_range(start_date: str, end_date: str, output_dir: str = "./output"):
    """날짜 범위의 뉴스 수집"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    current = start
    all_stats = []

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        stats = collect_daily_news(date_str, output_dir)
        all_stats.append(stats)
        current += timedelta(days=1)

    # 통계 요약
    total_smartphone = sum(s.get('smartphone_articles', 0) for s in all_stats)
    total_external = sum(s.get('external_articles', 0) for s in all_stats)

    logger.info(f"\n=== Collection Complete ===")
    logger.info(f"Date range: {start_date} ~ {end_date}")
    logger.info(f"Total smartphone articles: {total_smartphone}")
    logger.info(f"Total external factor articles: {total_external}")

    return all_stats


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        # 기본: 어제 데이터 수집
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"Collecting news for {yesterday}...")
        stats = collect_daily_news(yesterday)
        print(f"\nStats: {stats}")
    elif len(sys.argv) == 2:
        # 특정 날짜
        stats = collect_daily_news(sys.argv[1])
        print(f"\nStats: {stats}")
    else:
        # 날짜 범위
        collect_date_range(sys.argv[1], sys.argv[2])
