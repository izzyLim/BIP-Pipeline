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



def insert_to_postgres(df: pd.DataFrame, table_name: str, conn):
    """
    열린 psycopg2 connection(conn)에 df를 INSERT.
    ON CONFLICT (ticker, timestamp) DO NOTHING
    반환: 실제 시도한 row 수 (유효 row 기준)
    """
    if df.empty:
        print(f"[INFO] No data to insert into {table_name}")
        return 0

    required_cols = {"ticker","timestamp","timestamp_ny","timestamp_kst","open","high","low","close","volume"}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"[WARN] Missing columns for {table_name}: {missing}")
        return 0

    values = [
        (
            r.ticker, r.timestamp, r.timestamp_ny, r.timestamp_kst,
            r.open, r.high, r.low, r.close, r.volume
        )
        for r in df.itertuples()
        if pd.notna(r.timestamp) and pd.notna(r.close)
    ]
    if not values:
        print(f"[INFO] No valid rows to insert into {table_name}")
        return 0

    sql = f"""
        INSERT INTO {table_name} (
            ticker, timestamp, timestamp_ny, timestamp_kst,
            open, high, low, close, volume
        ) VALUES %s
        ON CONFLICT (ticker, timestamp) DO NOTHING;
    """.strip()

    try:
        with conn.cursor() as cur:
            execute_values(cur, sql, values, page_size=1000)
        conn.commit()
        print(f"[INFO] Inserted {len(values)} rows into {table_name} (duplicates ignored)")
        return len(values)
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to insert into {table_name}: {e}")
        return 0


def get_active_tickers(conn_info):
    query = "SELECT ticker FROM stock_info WHERE is_active = TRUE;"
    try:
        with psycopg2.connect(**conn_info) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"[ERROR] Failed to fetch tickers: {e}")
        return []
    

def get_new_active_tickers(conn, table_name: str) -> pd.DataFrame:
    """
    대상 가격 테이블에 아직 한 번도 기록이 없는 신규 종목 티커 목록을 반환.
    conn: 열린 psycopg2 connection
    table_name: {"stock_price_1m","stock_price_1d","stock_price_1wk","stock_price_1mo"}
    """
    allowed = {"stock_price_1m", "stock_price_1d", "stock_price_1wk", "stock_price_1mo"}
    if table_name not in allowed:
        raise ValueError(f"Invalid table_name: {table_name}")

    query = f"""
        SELECT DISTINCT p.ticker
        FROM stock_info p
        LEFT JOIN {table_name} s ON p.ticker = s.ticker
        WHERE s.ticker IS NULL
    """

    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame(columns=["ticker"])
    return pd.DataFrame(rows, columns=["ticker"])



def get_pg_conn(info: dict):
    """
    PostgreSQL 연결을 생성합니다.
    info: dict with keys host, port, user, password, dbname or database
    """
    if not isinstance(info, dict):
        raise ValueError("PG_CONN_INFO must be a dict")

    host = info.get("host")
    port = info.get("port")
    user = info.get("user")
    password = (info.get("password") or "").strip()
    dbname = info.get("dbname") or info.get("database")

    missing = [k for k, v in (("host", host), ("user", user), ("dbname", dbname)) if not v]
    if missing:
        raise ValueError(f"Missing required PG_CONN_INFO keys: {', '.join(missing)}")

    try:
        return psycopg2.connect(host=host, port=port, user=user, password=password, dbname=dbname)
    except Exception as e:
        # 민감정보(비밀번호)는 로그에 남기지 않음
        raise RuntimeError(f"Failed to connect to Postgres at {host}:{port} as {user} - {e}") from e


def upsert_news(conn, items: list) -> int:
    """
    items: list of dicts with keys:
      title, url, body, summary (optional), published_at (datetime or None), source
    conn: 열린 psycopg2 connection
    반환: 처리한 rows 수

    Fallback upsert that does UPDATE first and bulk INSERT for new URLs.
    Use this if the news.url column has no UNIQUE constraint.
    """
    if not items:
        return 0

    processed = 0
    try:
        with conn.cursor() as cur:
            inserts = []
            for it in items:
                url = it.get("url")
                title = it.get("title")
                body = it.get("body")
                summary = it.get("summary")
                published_at = it.get("published_at")
                source = it.get("source")

                cur.execute(
                    """
                    UPDATE news
                    SET title = %s,
                        body = %s,
                        summary = COALESCE(%s, summary),
                        published_at = %s,
                        source = %s,
                        updated_at = NOW()
                    WHERE url = %s
                    """,
                    (title, body, summary, published_at, source, url)
                )

                if cur.rowcount == 0:
                    inserts.append((title, url, body, summary, published_at, source))
                processed += 1

            if inserts:
                insert_sql = """
                INSERT INTO news (title, url, body, summary, published_at, source, created_at, updated_at)
                VALUES %s
                """
                execute_values(cur, insert_sql, inserts, page_size=100)
        conn.commit()
        return processed
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] upsert_news failed: {e}")
        return 0