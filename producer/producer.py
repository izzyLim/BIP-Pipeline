import json
import time
import logging
import sys
import requests
import pandas as pd
from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError
from datetime import datetime
import pytz

from utils import get_market_status, is_nyse_holiday, get_nyse_holidays

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)
logger = logging.getLogger("producer")

TOPIC = "stock_prices"
KAFKA_BROKER = "kafka:9092"



def ensure_topic_exists(topic_name):
    admin_client = KafkaAdminClient(bootstrap_servers="kafka:9092", client_id='producer-init')
    topic = NewTopic(name=topic_name, num_partitions=1, replication_factor=1)

    try:
        admin_client.create_topics([topic])
        logger.info(f"Kafka topic '{topic_name}' created")
    except TopicAlreadyExistsError:
        logger.info(f"Kafka topic '{topic_name}' already exists")
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
        logger.error(f"API 요청 실패: {response.status_code}")
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
        logger.error(f"데이터 파싱 실패: {e}")
        return None

def run_producer():
    ticker = "AAPL"
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )

    while True:
        status = get_market_status()

        # 공휴일인 경우 어떤 공휴일인지 표시
        if is_nyse_holiday():
            from datetime import datetime
            import pytz
            ny_tz = pytz.timezone("America/New_York")
            today = datetime.now(ny_tz).date()
            holiday_name = get_nyse_holidays().get(today, "공휴일")
            logger.info(f"현재 시장 상태: {status} (오늘은 {holiday_name})")
        else:
            logger.info(f"현재 시장 상태: {status}")

        if status == "장중":
            logger.info("장중이므로 데이터 전송 중...")
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
                    logger.debug(f"Sent: {record}")
            else:
                logger.warning("데이터 없음")
        else:
            logger.info(f"현재 시장 상태: {status} → 데이터 전송 생략")

        time.sleep(10)


if __name__ == "__main__":
    ensure_topic_exists(TOPIC)
    run_producer()
