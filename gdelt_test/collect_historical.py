"""
GDELT 히스토리컬 데이터 수집 (2020년~)
대용량 배치 처리용 - 백그라운드 실행 권장
"""

import pandas as pd
from datetime import datetime, timedelta
from gdelt_parser import GDELTCollector
import os
import logging
import time
import json
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('collection.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 스마트폰 브랜드 (정확한 매칭)
SMARTPHONE_ORGS = [
    "Samsung Electronics", "Samsung Mobile",
    "Xiaomi", "Huawei", "OPPO", "Vivo", "OnePlus",
    "Apple Inc", "iPhone",  # Apple은 너무 광범위하므로 Apple Inc로 제한
]

# 외부 요인
EXTERNAL_FACTORS = {
    "geopolitics": ["MILITARY", "CONFLICT", "WAR", "SANCTION", "TRADE_DISPUTE", "TARIFF"],
    "economy": ["ECONOMIC", "INFLATION", "RECESSION", "INTEREST_RATE", "CURRENCY", "GDP"],
    "supply_chain": ["SUPPLY_CHAIN", "SEMICONDUCTOR", "CHIP", "SHORTAGE", "LOGISTICS"],
    "regulation": ["REGULATION", "BAN", "RESTRICTION", "ANTITRUST"],
}

# 권역 매핑 (Counterpoint Research 기준)
REGIONS = [
    "North America", "Western Europe", "Central Europe",
    "China", "India", "Japan", "South Korea", "Southeast Asia",
    "MEA", "CALA", "Asia Pacific Others"
]


def collect_month(year: int, month: int, output_dir: str, samples_per_day: int = 2):
    """
    한 달치 데이터 수집 (더 효율적인 샘플링)

    Args:
        year: 연도
        month: 월
        output_dir: 출력 디렉토리
        samples_per_day: 하루당 샘플 수 (기본 4 = 6시간 간격)
    """
    collector = GDELTCollector()

    # 해당 월의 날짜 범위
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1) - timedelta(days=1)

    month_str = f"{year}{month:02d}"
    logger.info(f"=== Collecting {month_str} ===")

    all_smartphone = []
    all_external = []

    current = start_date
    day_count = 0

    while current <= end_date:
        date_str = current.strftime("%Y%m%d")

        try:
            files = collector.get_file_list(date_str)
            if not files:
                current += timedelta(days=1)
                continue

            # 샘플링: 하루에 samples_per_day개만
            sample_interval = max(1, len(files) // samples_per_day)
            sampled = files[::sample_interval][:samples_per_day]

            for file_url in sampled:
                try:
                    df = collector.download_and_parse(file_url)

                    # 스마트폰 뉴스
                    smartphone = extract_smartphone(df, collector, date_str)
                    if smartphone is not None:
                        all_smartphone.append(smartphone)

                    # 외부 요인 (권역별)
                    for region in REGIONS:
                        external = extract_external(df, collector, region, date_str)
                        if external is not None:
                            all_external.append(external)

                    time.sleep(0.05)  # rate limiting 줄임

                except requests.exceptions.Timeout:
                    logger.warning(f"Timeout: {file_url}")
                    continue
                except Exception as e:
                    logger.warning(f"Error processing {file_url}: {e}")
                    continue

            day_count += 1
            if day_count % 5 == 0:
                logger.info(f"  Progress: {day_count} days processed")

        except Exception as e:
            logger.warning(f"Error on {date_str}: {e}")

        current += timedelta(days=1)

    # 저장
    os.makedirs(output_dir, exist_ok=True)

    if all_smartphone:
        smartphone_df = pd.concat(all_smartphone, ignore_index=True)
        smartphone_df = smartphone_df.drop_duplicates(subset=['url'])
        smartphone_file = f"{output_dir}/smartphone_{month_str}.csv"
        smartphone_df.to_csv(smartphone_file, index=False)
        logger.info(f"Saved {len(smartphone_df)} smartphone articles to {smartphone_file}")

    if all_external:
        external_df = pd.concat(all_external, ignore_index=True)
        external_df = external_df.drop_duplicates(subset=['url', 'region'])
        external_file = f"{output_dir}/external_{month_str}.csv"
        external_df.to_csv(external_file, index=False)
        logger.info(f"Saved {len(external_df)} external articles to {external_file}")

    return {
        "month": month_str,
        "days": day_count,
        "smartphone": len(all_smartphone) if all_smartphone else 0,
        "external": len(all_external) if all_external else 0
    }


def extract_smartphone(df: pd.DataFrame, collector: GDELTCollector, date_str: str):
    """스마트폰 관련 뉴스 추출"""
    org_pattern = '|'.join(SMARTPHONE_ORGS)
    mask = df['V2Organizations'].str.contains(org_pattern, case=False, na=False)

    filtered = df[mask]
    if filtered.empty:
        return None

    return pd.DataFrame({
        'date': date_str,
        'source': filtered['SourceCommonName'],
        'url': filtered['DocumentIdentifier'],
        'organizations': filtered['V2Organizations'],
        'tone': filtered['V2Tone'].apply(lambda x: collector.parse_tone(x)['tone']),
    })


def extract_external(df: pd.DataFrame, collector: GDELTCollector, region: str, date_str: str):
    """권역별 외부 요인 뉴스 추출"""
    region_df = collector.filter_by_region(df, region)
    if region_df.empty:
        return None

    results = []
    for factor, keywords in EXTERNAL_FACTORS.items():
        pattern = '|'.join(keywords)
        mask = region_df['Themes'].str.contains(pattern, case=False, na=False)
        factor_df = region_df[mask]

        if not factor_df.empty:
            results.append(pd.DataFrame({
                'date': date_str,
                'region': region,
                'factor': factor,
                'source': factor_df['SourceCommonName'],
                'url': factor_df['DocumentIdentifier'],
                'tone': factor_df['V2Tone'].apply(lambda x: collector.parse_tone(x)['tone']),
            }))

    if not results:
        return None
    return pd.concat(results, ignore_index=True)


def collect_year_range(start_year: int, end_year: int, output_dir: str = "./historical"):
    """연도 범위 수집"""
    all_stats = []

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # 미래 월은 스킵
            if year == datetime.now().year and month > datetime.now().month:
                break

            stats = collect_month(year, month, output_dir)
            all_stats.append(stats)

            # 진행상황 저장
            with open(f"{output_dir}/progress.json", "w") as f:
                json.dump(all_stats, f, indent=2)

    logger.info(f"\n=== Collection Complete ===")
    logger.info(f"Total months: {len(all_stats)}")

    return all_stats


def estimate_collection_time(start_year: int = 2020, end_year: int = 2026):
    """수집 예상 시간 계산"""
    months = 0
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if year == datetime.now().year and month > datetime.now().month:
                break
            months += 1

    # 한 달 = ~30일 × 4파일 = 120 파일
    # 파일당 ~0.8초 (다운로드 + 처리)
    files_per_month = 30 * 4
    seconds_per_file = 0.8
    total_seconds = months * files_per_month * seconds_per_file

    hours = total_seconds / 3600

    print(f"=== 수집 예상치 ===")
    print(f"기간: {start_year}-01 ~ {end_year}-{datetime.now().month:02d}")
    print(f"총 월수: {months}개월")
    print(f"예상 파일 수: {months * files_per_month:,}개")
    print(f"예상 소요 시간: {hours:.1f}시간 ({hours/24:.1f}일)")
    print(f"예상 데이터 크기: ~{months * 50}MB (압축 후)")

    return hours


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        estimate_collection_time()
        print("\n사용법:")
        print("  python collect_historical.py estimate          # 예상 시간")
        print("  python collect_historical.py 2024 1            # 2024년 1월만")
        print("  python collect_historical.py 2020 2026         # 2020~2026 전체")
    elif sys.argv[1] == "estimate":
        estimate_collection_time()
    elif len(sys.argv) == 3 and len(sys.argv[2]) <= 2:
        # 특정 월
        year = int(sys.argv[1])
        month = int(sys.argv[2])
        stats = collect_month(year, month, "./historical")
        print(f"\nStats: {stats}")
    else:
        # 연도 범위
        start_year = int(sys.argv[1])
        end_year = int(sys.argv[2]) if len(sys.argv) > 2 else start_year
        collect_year_range(start_year, end_year)
