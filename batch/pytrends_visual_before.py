import pandas as pd
import matplotlib.pyplot as plt

# CSV 불러오기
df = pd.read_csv("iphone_trends_7_to_16.csv", index_col=0, parse_dates=True)

# iPhone 7~16 전체 모델 추출
all_models = [col for col in df.columns if col.startswith("iphone ") and col != "iphone"]

# 시각화
plt.figure(figsize=(16, 8))
for model in all_models:
    plt.plot(df.index, df[model], label=model)

plt.title("📉 iPhone 7 ~ 16 모델별 Google Trends (정규화 전)")
plt.xlabel("Date")
plt.ylabel("Relative Interest (0~100)")
plt.legend(loc="upper right", ncol=2)
plt.grid(True)
plt.tight_layout()
plt.show()
