"""
Airflow DAG 설정
shared.config에서 공통 설정을 가져옵니다.
"""

import os
import sys

# shared 모듈 경로 추가 (Airflow 환경에서 필요)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

try:
    from shared.config import config
    PG_CONN_INFO = config.PG_CONN_INFO
except ImportError:
    # fallback: shared 모듈을 못 찾을 경우 환경변수 직접 사용
    PG_CONN_INFO = {
        "host": os.getenv("PG_HOST", "bip-postgres"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "user": os.getenv("PG_USER", "user"),
        "password": os.getenv("PG_PASSWORD", "pw1234"),
        "dbname": os.getenv("PG_DB", "stockdb"),
    }
