import json
import time
import requests
import pandas as pd
from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError
from datetime import datetime
import pytz

from utils import get_market_status  # 유틸에서 불러옴


TOPIC = "stock_prices"
KAFKA_BROKER = "kafka:9092"  # Kafka 컨테이너 이름 기준



def ensure_topic_exists(topic_name):
    admin_client = KafkaAdminClient(bootstrap_servers="kafka:9092", client_id='producer-init')
    topic = NewTopic(name=topic_name, num_partitions=1, replication_factor=1)

    try:
        admin_client.create_topics([topic])
        print(f"[INFO] Kafka topic '{topic_name}' created.")
    except TopicAlreadyExistsError:
        print(f"[INFO] Kafka topic '{topic_name}' already exists.")
    finally:
        admin_client.close()

def fetch_latest_price(ticker: str) -> pd.DataFrame:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "range": "1d",
        "interval": "1m",
    }
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        print(f"[ERROR] API 요청 실패: {response.status_code}")
        return None

    try:
        result = response.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        indicators = result["indicators"]["quote"][0]

        df = pd.DataFrame(indicators)
        df["timestamp"] = pd.to_datetime(timestamps, unit="s", utc=True)
        df["ticker"] = ticker
        df["timestamp_kst"] = df["timestamp"].dt.tz_convert("Asia/Seoul")

        df = df[["ticker", "timestamp", "timestamp_kst", "open", "high", "low", "close", "volume"]]
        return df

    except Exception as e:
        print(f"[ERROR] 데이터 파싱 실패: {e}")
        return None

def run_producer():
    ticker = "AAPL"
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )

    while True:
        status = get_market_status()
        print(f"[INFO] 현재 시장 상태: {status}")

        if status == "장중":
            print("[INFO] 장중이므로 데이터 전송 중...", flush=True)
            df = fetch_latest_price(ticker)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    if pd.isna(row["close"]) or pd.isna(row["timestamp"]):
                        continue

                    record = {
                        "ticker": row["ticker"],
                        "timestamp": row["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": int(row["volume"]),
                    }

                    producer.send(TOPIC, value=record)
                    print("[PRODUCER] Sent:", record)
            else:
                print("[PRODUCER] 데이터 없음")
        else:
            print(f"[PRODUCER] 현재 시장 상태: {status} → 데이터 전송 생략", flush=True)

        time.sleep(10)


if __name__ == "__main__":
    ensure_topic_exists(TOPIC)
    run_producer()
