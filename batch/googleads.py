#customer_id = "3884889244 "

# hybrid_monthly_counts.py

from pytrends.request import TrendReq
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
import pandas as pd

def get_monthly_interest(keyword: str, years: int = 4):
    pytrends = TrendReq(hl='ko', tz=540)
    # today 4-y: 최근 4년치, resolution='M'은 월별
    pytrends.build_payload([keyword], timeframe=f'')
    df = pytrends.interest_over_time().reset_index()
    df = df[df['isPartial']==False]  # 마지막 미완전 달 제거
    # 월별 평균 인덱스
    df['year_month'] = df['date'].dt.strftime('%Y%m')
    monthly = df.groupby('year_month')[keyword].mean()
    return monthly

def get_avg_monthly_searches(keyword: str, customer_id: str):
    client  = GoogleAdsClient.load_from_storage("google-ads.yaml")
    service = client.get_service("KeywordPlanIdeaService")
    request = {
        "customer_id": customer_id,
        "keyword_plan_network": client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH,
        "language": "languageConstants/1001",
        "keywords": [{"text": keyword}],
    }
    try:
        response = service.generate_keyword_historical_metrics(request=request)
    except GoogleAdsException as ex:
        raise RuntimeError(f"Google Ads API 오류: {ex}")
    # 월별 리스트 중 평균값(12개월 평균)을 직접 계산
    vols = []
    for result in response.results:
        vols.extend([v.monthly_searches for v in result.monthly_search_volumes])
    return sum(vols) / len(vols)

def main():
    keyword     = "galaxy fold 7"
    customer_id = "3884889244"  # 하이픈 없이

    # 1) Pytrends로 상대 관심도 월별 시리즈
    monthly_idx = get_monthly_interest(keyword, years=4)

    # 2) Google Ads API로 최근 12개월 평균 검색량
    avg_searches = get_avg_monthly_searches(keyword, customer_id)
    print(f"avg_monthly_searches (12m mean): {avg_searches:.1f}")

    # 3) 비율 보정: 월별 추정 검색량 = (index / sum(index)) * avg_searches * 12
    #    *12 해서 “월평균”이 아닌 “월총합” 규모로 보정
    total_idx = monthly_idx.sum()
    est = (monthly_idx / total_idx) * avg_searches * 12
    est = est.round().astype(int)

    # 4) DataFrame + CSV 저장
    df_out = pd.DataFrame({
        "year_month": est.index,
        "estimated_searches": est.values
    })
    df_out.to_csv("hybrid_monthly_counts.csv", index=False, encoding="utf-8-sig")
    print("✅ hybrid_monthly_counts.csv 저장 완료")

if __name__ == "__main__":
    main()
