"""
공통 설정 모듈
환경변수 기반으로 설정을 관리합니다.

사용법:
    from shared.config import config
    print(config.PG_HOST)
    print(config.DATABASE_URL)
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """환경변수 기반 설정"""

    # PostgreSQL 설정
    PG_HOST: str = os.getenv("PG_HOST", "bip-postgres")
    PG_PORT: int = int(os.getenv("PG_PORT", "5432"))
    PG_USER: str = os.getenv("PG_USER", "user")
    PG_PASSWORD: str = os.getenv("PG_PASSWORD", "pw1234")
    PG_DB: str = os.getenv("PG_DB", "stockdb")

    # 환경 설정
    ENV: str = os.getenv("ENV", "docker")  # local, docker, production

    @property
    def DATABASE_URL(self) -> str:
        """SQLAlchemy용 DB URL"""
        return f"postgresql://{self.PG_USER}:{self.PG_PASSWORD}@{self.PG_HOST}:{self.PG_PORT}/{self.PG_DB}"

    @property
    def PG_CONN_INFO(self) -> dict:
        """psycopg2용 연결 정보"""
        return {
            "host": self.PG_HOST,
            "port": self.PG_PORT,
            "user": self.PG_USER,
            "password": self.PG_PASSWORD,
            "dbname": self.PG_DB,
        }

    @property
    def is_local(self) -> bool:
        """로컬 환경 여부"""
        return self.ENV == "local"


# 싱글톤 인스턴스
config = Config()
