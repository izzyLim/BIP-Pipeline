"""
OpenMetadata → PostgreSQL COMMENT 동기화 스크립트
============================================================
OM에 등록된 테이블/컬럼 설명을 PostgreSQL의 COMMENT ON TABLE/COLUMN으로 반영합니다.
이렇게 하면 Wren AI 등 DB에 직접 연결하는 도구에서도 설명이 자동으로 표시됩니다.

데이터 흐름:
    OM (UI/API에서 편집, 원천) → 이 스크립트 → DB COMMENT → Wren AI 자동 반영

사용법:
    OM_HOST=http://localhost:8585 python scripts/om_sync_comments.py
    python scripts/om_sync_comments.py --dry-run

Airflow DAG로 주기적 실행 권장 (예: 매일 1회)
"""

import argparse
import os
import sys

import psycopg2
import requests

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
OM_HOST = os.getenv("OM_HOST", "http://localhost:8585")
OM_BOT_TOKEN = os.getenv("OM_BOT_TOKEN", "")

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER", "user")
PG_PASSWORD = os.getenv("PG_PASSWORD", "pw1234")
PG_DB = os.getenv("PG_DB", "stockdb")

OM_DB_SERVICE = "bip-postgres"
OM_DB_NAME = "stockdb"
OM_DB_SCHEMA = "public"


def get_om_headers():
    if not OM_BOT_TOKEN:
        print("OM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    return {"Authorization": f"Bearer {OM_BOT_TOKEN}"}


def fetch_om_tables(headers: dict) -> list[dict]:
    """OM에서 모든 테이블 + 컬럼 설명을 가져옵니다."""
    tables = []
    after = None

    while True:
        url = (
            f"{OM_HOST}/api/v1/tables?"
            f"database={OM_DB_SERVICE}.{OM_DB_NAME}"
            f"&fields=columns"
            f"&limit=50"
        )
        if after:
            url += f"&after={after}"

        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"OM API 오류: {resp.status_code} {resp.text[:200]}")
            break

        data = resp.json()
        for table in data.get("data", []):
            schema = table.get("databaseSchema", {}).get("name", "")
            if schema != OM_DB_SCHEMA:
                continue
            tables.append(table)

        paging = data.get("paging", {})
        after = paging.get("after")
        if not after:
            break

    return tables


def sync_comments(tables: list[dict], dry_run: bool = False):
    """OM 설명을 PostgreSQL COMMENT로 반영합니다."""
    if dry_run:
        conn = None
        cur = None
    else:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT,
            user=PG_USER, password=PG_PASSWORD,
            dbname=PG_DB,
        )
        cur = conn.cursor()

    stats = {"table_comments": 0, "column_comments": 0, "skipped": 0}

    for table in tables:
        table_name = table["name"]
        table_desc = table.get("description", "")

        # 테이블 COMMENT
        if table_desc:
            escaped = table_desc.replace("'", "''")
            sql = f"COMMENT ON TABLE public.{table_name} IS '{escaped}';"
            if dry_run:
                print(f"  [DRY-RUN] TABLE {table_name}: {table_desc[:60]}...")
            else:
                try:
                    cur.execute(sql)
                    stats["table_comments"] += 1
                except Exception as e:
                    print(f"  SKIP TABLE {table_name}: {e}")
                    conn.rollback()
                    stats["skipped"] += 1
                    continue

        # 컬럼 COMMENT
        for col in table.get("columns", []):
            col_name = col["name"]
            col_desc = col.get("description", "")
            if not col_desc:
                continue

            escaped = col_desc.replace("'", "''")
            sql = f"COMMENT ON COLUMN public.{table_name}.{col_name} IS '{escaped}';"
            if dry_run:
                print(f"  [DRY-RUN] COLUMN {table_name}.{col_name}: {col_desc[:50]}...")
            else:
                try:
                    cur.execute(sql)
                    stats["column_comments"] += 1
                except Exception as e:
                    print(f"  SKIP COLUMN {table_name}.{col_name}: {e}")
                    conn.rollback()
                    stats["skipped"] += 1

    if not dry_run and conn:
        conn.commit()
        cur.close()
        conn.close()

    return stats


def main(dry_run: bool = False):
    print(f"\n{'=' * 60}")
    print(f"OpenMetadata → PostgreSQL COMMENT 동기화")
    print(f"OM: {OM_HOST}")
    print(f"DB: {PG_HOST}:{PG_PORT}/{PG_DB}")
    print(f"DRY-RUN: {dry_run}")
    print(f"{'=' * 60}\n")

    headers = get_om_headers()
    tables = fetch_om_tables(headers)
    print(f"OM에서 {len(tables)}개 테이블 조회 완료\n")

    stats = sync_comments(tables, dry_run=dry_run)

    print(f"\n{'=' * 60}")
    print(f"완료: TABLE {stats['table_comments']}개, "
          f"COLUMN {stats['column_comments']}개 COMMENT 반영")
    if stats["skipped"]:
        print(f"건너뜀: {stats['skipped']}개 (테이블/컬럼이 DB에 없거나 오류)")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OM → DB COMMENT 동기화")
    parser.add_argument("--dry-run", action="store_true", help="실제 DB 변경 없이 미리보기")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
