import psycopg2
from psycopg2.extras import execute_values
import pandas as pd



def upsert_stock_info(rows, conn_info):
    """
    주식 종목 정보를 stock_info 테이블에 upsert (insert or update) 처리
    :param rows: dict 리스트, 각 row는 하나의 종목 정보
    :param conn_info: PostgreSQL 연결 정보 (dict 형태)
    """
    if not rows:
        print("[INFO] 저장할 데이터가 없습니다.")
        return

    columns = [
        "ticker",
        "stock_name",
        "stock_name_eng",
        "market_type",
        "exchange_code",
        "currency_code",
        "listing_date",
        "par_value",
        "total_shares",
        "market_value",
        "data_source"
    ]

    values = [[row.get(col) for col in columns] for row in rows]

    insert_query = f"""
    INSERT INTO stock_info ({', '.join(columns)})
    VALUES %s
    ON CONFLICT (ticker) DO UPDATE SET
    {', '.join([f"{col} = EXCLUDED.{col}" for col in columns if col != 'ticker'])}
    ;
    """

    try:
        with psycopg2.connect(**conn_info) as conn:
            with conn.cursor() as cur:
                execute_values(cur, insert_query, values)
        print(f"[INFO] {len(rows)}건 upsert 완료")
    except Exception as e:
        print("[ERROR] upsert_stock_info 오류:", e)
        raise



def insert_to_postgres(df: pd.DataFrame, table_name: str, conn_info: dict):
    if df.empty:
        print(f"[INFO] No data to insert into {table_name}")
        return

    insert_query = f"""
        INSERT INTO {table_name} (
            ticker, timestamp, timestamp_ny, timestamp_kst,
            open, high, low, close, volume
        ) VALUES %s
        ON CONFLICT (ticker, timestamp) DO NOTHING;
    """

    values = [
        (
            row["ticker"], row["timestamp"], row["timestamp_ny"], row["timestamp_kst"],
            row["open"], row["high"], row["low"], row["close"], row["volume"]
        )
        for _, row in df.iterrows()
        if pd.notna(row["timestamp"]) and pd.notna(row["close"])
    ]

    try:
        with psycopg2.connect(**conn_info) as conn:
            with conn.cursor() as cur:
                execute_values(cur, insert_query, values)
            conn.commit()
        print(f"[INFO] Inserted {len(values)} rows into {table_name} (duplicates ignored)")
    except Exception as e:
        print(f"[ERROR] Failed to insert into {table_name}: {e}")


def get_active_tickers(conn_info: dict):
    query = "SELECT ticker FROM stock_metadata WHERE is_active = TRUE;"
    try:
        with psycopg2.connect(**conn_info) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"[ERROR] Failed to fetch tickers: {e}")
        return []