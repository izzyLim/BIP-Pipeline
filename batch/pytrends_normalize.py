import pandas as pd

# 1. 수집한 데이터 불러오기
df = pd.read_csv("iphone_trends_7_to_16.csv", index_col=0, parse_dates=True)

# 2. iphone 14 시계열을 기반으로 보정 비율 계산
# 기준: iphone 14 값이 가장 높은 그룹의 평균
anchor_mean = df["iphone 14"].mean()

# 3. 그룹별 보정 비율 계산 (optional: 기준 anchor와 비율이 다르면 보정)
# 예를 들어 iphone 14가 그룹마다 다르게 나왔다면 아래처럼 보정
# (만약 중복이 없다면 이건 생략 가능)

# 4. 다른 모델들도 iphone 14 기준으로 상대적 스케일로 맞추기
for col in df.columns:
    if col not in ["iphone 14", "iphone"]:  # anchor 제외
        ratio = df[col].max() / df["iphone 14"].max()
        df[col + "_scaled"] = df[col] / ratio

print(df)