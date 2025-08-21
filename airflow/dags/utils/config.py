import os

PG_CONN_INFO = {
    "host": os.getenv("PG_HOST", "bip-postgres"),
    "port": int(os.getenv("PG_PORT", "5432")),
    "user": os.getenv("PG_USER", "user"),
    "password": os.getenv("PG_PASSWORD", "pw1234"),
    "dbname": os.getenv("PG_DB", "stockdb"),
}
