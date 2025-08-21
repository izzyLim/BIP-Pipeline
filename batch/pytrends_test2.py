from pytrends.request import TrendReq
import pandas as pd
import time

# pytrends 초기화 (한국 기준)
pytrends = TrendReq(hl='en-US', tz=540)

# 그룹 정의 (anchor: iphone 14, iphone)
keyword_groups = [
    ["iphone 7", "iphone 8", "iphone 9", "iphone 14", "iphone"],
    ["iphone 10", "iphone 11", "iphone 12", "iphone 14", "iphone"],
    ["iphone 13", "iphone 15", "iphone 16", "iphone 14", "iphone"]
]

df_all = pd.DataFrame()

for i, group in enumerate(keyword_groups):
    print(f"[{i+1}/{len(keyword_groups)}] 조회 중: {group}")
    pytrends.build_payload(group, timeframe='today 5-y', geo='KR')  # 최근 5년, 한국 기준
    df = pytrends.interest_over_time()
    
    if 'isPartial' in df.columns:
        df = df.drop(columns=['isPartial'])
    
    df_all = pd.concat([df_all, df], axis=1)
    time.sleep(2)

# 중복 컬럼 제거
df_all = df_all.loc[:, ~df_all.columns.duplicated()]

# 저장
df_all.to_csv("iphone_trends_7_to_16.csv", encoding="utf-8-sig")

print("✅ 저장 완료! 컬럼 목록:")
print(df_all.columns)
