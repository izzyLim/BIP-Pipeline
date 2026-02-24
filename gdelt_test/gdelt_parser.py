"""
GDELT GKG (Global Knowledge Graph) 파서
뉴스 데이터 수집 및 분석용
"""

import pandas as pd
import requests
import zipfile
import io
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import os

# GKG 컬럼 정의 (주요 컬럼만)
GKG_COLUMNS = [
    'GKGRECORDID',      # 0: 레코드 ID
    'DATE',             # 1: 날짜 (YYYYMMDDHHMMSS)
    'SourceCollectionIdentifier',  # 2
    'SourceCommonName', # 3: 뉴스 소스
    'DocumentIdentifier',  # 4: URL
    'Counts',           # 5
    'V2Counts',         # 6
    'Themes',           # 7: 테마/주제 (중요!)
    'V2Themes',         # 8
    'Locations',        # 9: 위치 정보
    'V2Locations',      # 10
    'Persons',          # 11: 인물
    'V2Persons',        # 12
    'Organizations',    # 13: 조직/기업
    'V2Organizations',  # 14
    'V2Tone',           # 15: 감성 점수 (중요!)
    'Dates',            # 16
    'GCAM',             # 17
    'SharingImage',     # 18
    'RelatedImages',    # 19
    'SocialImageEmbeds',# 20
    'SocialVideoEmbeds',# 21
    'Quotations',       # 22
    'AllNames',         # 23
    'Amounts',          # 24
    'TranslationInfo',  # 25
    'Extras',           # 26
]


class GDELTCollector:
    """GDELT GKG 데이터 수집기"""

    BASE_URL = "http://data.gdeltproject.org/gdeltv2"

    # 권역별 국가 코드 (Counterpoint Research 기준)
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

    # 외부 요인 테마 매핑
    EXTERNAL_FACTOR_THEMES = {
        "지정학": ["MILITARY", "CONFLICT", "WAR", "SANCTION", "TRADE_DISPUTE", "TERROR"],
        "경제": ["ECONOMIC", "INFLATION", "RECESSION", "CENTRAL_BANK", "CURRENCY", "INTEREST_RATE"],
        "공급망": ["SUPPLY_CHAIN", "SEMICONDUCTOR", "CHIP", "SHORTAGE", "LOGISTICS"],
        "규제": ["REGULATION", "LEGISLATION", "BAN", "RESTRICTION", "PRIVACY", "ANTITRUST"],
        "재난": ["PANDEMIC", "COVID", "NATURAL_DISASTER", "EARTHQUAKE", "FLOOD"],
    }

    # 스마트폰 관련 키워드 (더 정확한 매칭)
    SMARTPHONE_KEYWORDS = [
        "SAMSUNG_ELECTRONICS", "APPLE_INC", "IPHONE", "GALAXY_PHONE",
        "XIAOMI", "HUAWEI", "OPPO", "VIVO",
        "SMARTPHONE", "MOBILE_PHONE", "HANDSET"
    ]

    # 스마트폰 브랜드/제품명 (Organizations 컬럼용)
    SMARTPHONE_ORGS = [
        "Samsung Electronics", "Apple", "Xiaomi", "Huawei", "OPPO", "Vivo",
        "OnePlus", "Google", "Motorola", "Sony"
    ]

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def get_file_list(self, date: str) -> List[str]:
        """특정 날짜의 GKG 파일 목록 조회

        Args:
            date: YYYYMMDD 형식
        """
        # masterfilelist에서 해당 날짜 파일 찾기
        master_url = f"{self.BASE_URL}/masterfilelist.txt"
        response = requests.get(master_url, timeout=60)

        files = []
        for line in response.text.split('\n'):
            if f"{date}" in line and "gkg.csv.zip" in line:
                parts = line.strip().split(' ')
                if len(parts) >= 3:
                    files.append(parts[2])

        return files

    def download_and_parse(self, url: str, timeout: int = 30) -> pd.DataFrame:
        """GKG 파일 다운로드 및 파싱"""
        print(f"Downloading: {url}")
        response = requests.get(url, timeout=timeout)

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_name = z.namelist()[0]
            with z.open(csv_name) as f:
                df = pd.read_csv(
                    f,
                    sep='\t',
                    header=None,
                    names=GKG_COLUMNS[:27],
                    on_bad_lines='skip',
                    dtype=str
                )

        return df

    def parse_tone(self, tone_str: str) -> Dict:
        """V2Tone 파싱 (감성 점수)"""
        if pd.isna(tone_str):
            return {"tone": 0, "positive": 0, "negative": 0}

        parts = str(tone_str).split(',')
        if len(parts) >= 3:
            return {
                "tone": float(parts[0]) if parts[0] else 0,
                "positive": float(parts[1]) if parts[1] else 0,
                "negative": float(parts[2]) if parts[2] else 0,
            }
        return {"tone": 0, "positive": 0, "negative": 0}

    def parse_locations(self, loc_str: str) -> List[str]:
        """위치 정보에서 국가 코드 추출"""
        if pd.isna(loc_str):
            return []

        countries = set()
        for loc in str(loc_str).split(';'):
            parts = loc.split('#')
            if len(parts) >= 3:
                country_code = parts[2]
                if country_code:
                    countries.add(country_code)

        return list(countries)

    def filter_by_keywords(self, df: pd.DataFrame, keywords: List[str]) -> pd.DataFrame:
        """키워드로 필터링 (Themes 컬럼)"""
        if not keywords:
            return df

        pattern = '|'.join(keywords)
        mask = df['Themes'].str.contains(pattern, case=False, na=False)
        return df[mask]

    def filter_by_organizations(self, df: pd.DataFrame, orgs: List[str]) -> pd.DataFrame:
        """조직/기업명으로 필터링 (Organizations, V2Organizations 컬럼)"""
        if not orgs:
            return df

        pattern = '|'.join(orgs)
        mask_org = df['Organizations'].str.contains(pattern, case=False, na=False)
        mask_v2org = df['V2Organizations'].str.contains(pattern, case=False, na=False)
        return df[mask_org | mask_v2org]

    def filter_smartphone_news(self, df: pd.DataFrame) -> pd.DataFrame:
        """스마트폰 관련 뉴스 필터 (Themes + Organizations 결합)"""
        # 테마 기반 필터
        theme_filtered = self.filter_by_keywords(df, self.SMARTPHONE_KEYWORDS)

        # 조직명 기반 필터
        org_filtered = self.filter_by_organizations(df, self.SMARTPHONE_ORGS)

        # 합집합
        combined = pd.concat([theme_filtered, org_filtered]).drop_duplicates(subset=['GKGRECORDID'])
        return combined

    def filter_by_region(self, df: pd.DataFrame, region: str) -> pd.DataFrame:
        """권역으로 필터링"""
        if region not in self.REGION_COUNTRIES:
            print(f"Unknown region: {region}")
            return df

        country_codes = self.REGION_COUNTRIES[region]

        def has_country(loc_str):
            countries = self.parse_locations(loc_str)
            return any(c in country_codes for c in countries)

        mask = df['V2Locations'].apply(has_country)
        return df[mask]

    def search(
        self,
        keywords: List[str],
        region: Optional[str] = None,
        start_date: str = None,
        end_date: str = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """뉴스 검색

        Args:
            keywords: 검색 키워드 리스트
            region: 권역 (북미, 유럽, 동아시아 등)
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
            limit: 최대 결과 수
        """
        # 날짜 범위 계산
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        all_results = []
        current_dt = start_dt

        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y%m%d")
            files = self.get_file_list(date_str)

            # 하루에 파일이 많으므로 샘플링 (매 6시간 = 4개 파일)
            sampled_files = files[::24]  # 하루 중 일부만

            for file_url in sampled_files[:2]:  # 하루 최대 2개 파일
                try:
                    df = self.download_and_parse(file_url)

                    # 키워드 필터
                    df = self.filter_by_keywords(df, keywords)

                    # 권역 필터
                    if region:
                        df = self.filter_by_region(df, region)

                    if not df.empty:
                        all_results.append(df)

                except Exception as e:
                    print(f"Error processing {file_url}: {e}")
                    continue

            current_dt += timedelta(days=1)

        if not all_results:
            return pd.DataFrame()

        result_df = pd.concat(all_results, ignore_index=True)

        # 정제
        result_df = self._clean_results(result_df)

        return result_df.head(limit)

    def search_external_factors(
        self,
        region: str,
        factors: List[str],
        start_date: str,
        end_date: str,
        limit: int = 50
    ) -> pd.DataFrame:
        """외부 요인 (지정학, 경제 등) 뉴스 검색"""

        keywords = []
        for factor in factors:
            if factor in self.EXTERNAL_FACTOR_THEMES:
                keywords.extend(self.EXTERNAL_FACTOR_THEMES[factor])

        return self.search(
            keywords=keywords,
            region=region,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )

    def _clean_results(self, df: pd.DataFrame) -> pd.DataFrame:
        """결과 정제"""
        # 필요한 컬럼만 선택
        cols = ['DATE', 'SourceCommonName', 'DocumentIdentifier', 'Themes', 'V2Tone', 'V2Locations']
        df = df[[c for c in cols if c in df.columns]].copy()

        # 날짜 변환
        df['DATE'] = pd.to_datetime(df['DATE'].str[:8], format='%Y%m%d', errors='coerce')

        # 감성 점수 추출
        df['Tone'] = df['V2Tone'].apply(lambda x: self.parse_tone(x)['tone'])

        # 중복 URL 제거
        df = df.drop_duplicates(subset=['DocumentIdentifier'])

        # 컬럼 이름 정리
        df = df.rename(columns={
            'DATE': 'date',
            'SourceCommonName': 'source',
            'DocumentIdentifier': 'url',
            'Themes': 'themes',
        })

        return df[['date', 'source', 'url', 'themes', 'Tone']]


def quick_test():
    """빠른 테스트"""
    collector = GDELTCollector()

    # 최신 파일 하나만 테스트
    latest_url = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
    response = requests.get(latest_url)

    for line in response.text.strip().split('\n'):
        if 'gkg.csv.zip' in line:
            url = line.split()[-1]
            break

    print(f"\n=== 최신 GKG 파일 테스트 ===")
    df = collector.download_and_parse(url)
    print(f"전체 기사 수: {len(df)}")

    # 스마트폰 관련 필터 (개선된 버전)
    smartphone_df = collector.filter_smartphone_news(df)
    print(f"스마트폰 관련 기사 (Themes + Orgs): {len(smartphone_df)}")

    if not smartphone_df.empty:
        print("\n=== 스마트폰 관련 샘플 ===")
        for _, row in smartphone_df.head(5).iterrows():
            print(f"- Source: {row['SourceCommonName']}")
            print(f"  URL: {row['DocumentIdentifier'][:80]}...")
            orgs = str(row['Organizations'])[:80] if pd.notna(row['Organizations']) else 'N/A'
            print(f"  Orgs: {orgs}")
            tone = collector.parse_tone(row['V2Tone'])
            print(f"  Tone: {tone['tone']:.2f} (pos: {tone['positive']:.1f}, neg: {tone['negative']:.1f})")
            print()

    # 권역별 외부 요인 분석
    print("\n=== 외부 요인 분석 ===")
    for factor_name, keywords in collector.EXTERNAL_FACTOR_THEMES.items():
        factor_df = collector.filter_by_keywords(df, keywords)
        print(f"{factor_name}: {len(factor_df)}건")

    # 권역별 기사 수
    print("\n=== 권역별 기사 분포 ===")
    for region_name in ["북미", "유럽", "동아시아", "동남아"]:
        region_df = collector.filter_by_region(df, region_name)
        print(f"{region_name}: {len(region_df)}건")

    return df


if __name__ == "__main__":
    quick_test()
