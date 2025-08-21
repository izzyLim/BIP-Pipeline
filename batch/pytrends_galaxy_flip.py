from pytrends.request import TrendReq
import pandas as pd
import time

# 안정적인 User-Agent 추가
pytrends = TrendReq(hl='en-US', tz=540, 
                    requests_args={'headers': {'User-Agent': 'Mozilla/5.0'}})

flip_keyword_groups = [
    ["galaxy z flip", "galaxy z flip 3", "galaxy z flip 4", "galaxy z flip 5", "galaxy z flip 6"],
    ["galaxy z flip 4", "galaxy z flip 5", "galaxy z flip 6", "galaxy z flip 7", "galaxy z flip"]
]

df_all = pd.DataFrame()

for i, group in enumerate(flip_keyword_groups):
    print(f"[{i+1}/{len(flip_keyword_groups)}] 조회 중: {group}")
    try:
        pytrends.build_payload(group, timeframe='today 5-y', geo='')
        df = pytrends.interest_over_time().drop(columns=["isPartial"])
        df_all = pd.concat([df_all, df], axis=1)
        time.sleep(15)  # ⏱ 요청 간 딜레이를 충분히!
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        time.sleep(60)  # 실패했을 경우 더 오래 기다려줌

# 중복 제거
df_all = df_all.loc[:, ~df_all.columns.duplicated()]
df_all.to_csv("galaxy_z_flip_global_trends.csv", encoding="utf-8-sig")
print("✅ 저장 완료!")
