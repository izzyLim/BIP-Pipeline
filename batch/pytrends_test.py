from pytrends.request import TrendReq
import pandas as pd

def fetch_and_save_trends(
    keyword: str,
    timeframe: str = "today 3-m",
    geo: str = "",
    csv_path: str = "samsung_slim7_trends_all.csv",
    proxy: str = "http://username:password@proxy-host:proxy-port",
):
    # 1) 프록시 설정
    proxies = {
        "http":  proxy,
        "https": proxy,
    }

    # 2) Pytrends 세션 생성 (한국어·KST 기준) + 프록시 적용
    pytrends = TrendReq(
        hl='ko',
        tz=540,
        proxies=proxies,
        requests_args={
            "timeout": 10,    # 요청 타임아웃
            "verify": False,  # SSL 검증 끄기 (필요 시)
        }
    )
    
    # 3) 데이터 요청 (전체 기간)
    pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
    df = pytrends.interest_over_time().drop(columns=['isPartial'], errors='ignore')
    
    # 4) CSV로 저장
    df.to_csv(csv_path)
    print(f"✅ CSV saved: {csv_path}")
    

if __name__ == "__main__":
    KEYWORD = "galaxy fold 7"
    fetch_and_save_trends(
        keyword=KEYWORD,
        timeframe="all",             # 전체 기간 데이터
        geo="",                      # 글로벌
        csv_path="samsung_slim7_trends_all.csv",
        proxy="http://user:pass@127.0.0.1:3128",  # 실제 프록시 정보로 교체
    )
