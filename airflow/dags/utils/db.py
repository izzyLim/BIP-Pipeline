import psycopg2
from psycopg2.extras import execute_values
import pandas as pd


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
        print(f"[INFO] Inserted {len(values)} rows into {table_name}")
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
