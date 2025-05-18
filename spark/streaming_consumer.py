import json
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col
from pyspark.sql.types import StructType, StringType, DoubleType, LongType, TimestampType

from shared.db_handler import save_stock_prices

# Kafka 메시지의 JSON 스키마 정의
schema = StructType() \
    .add("ticker", StringType()) \
    .add("timestamp", TimestampType()) \
    .add("open", DoubleType()) \
    .add("high", DoubleType()) \
    .add("low", DoubleType()) \
    .add("close", DoubleType()) \
    .add("volume", LongType())

# Spark 세션 생성
spark = SparkSession.builder.appName("KafkaStockConsumer").getOrCreate()
spark.sparkContext.setLogLevel("WARN")

# Kafka에서 메시지 스트리밍 읽기
df = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", "kafka:9092") \
    .option("subscribe", "stock_prices") \
    .option("startingOffsets", "latest") \
    .load()

# Kafka 메시지를 JSON으로 파싱
df_parsed = df.selectExpr("CAST(value AS STRING) as json_str") \
    .select(from_json(col("json_str"), schema).alias("data")) \
    .select("data.*")

# 각 마이크로배치마다 DB 저장 함수 호출
def save_to_db(batch_df, batch_id):
    records = batch_df.toJSON().map(lambda row: json.loads(row)).collect()
    print(f"[DEBUG] Batch ID {batch_id}: {len(records)} record(s) received.")
    if records:
        print(f"[DEBUG] First record sample: {records[0]}")
        save_stock_prices(records)
    else:
        print("[DEBUG] No records to save.")

# 스트리밍 시작
query = df_parsed.writeStream \
    .foreachBatch(save_to_db) \
    .outputMode("append") \
    .start()

query.awaitTermination()
