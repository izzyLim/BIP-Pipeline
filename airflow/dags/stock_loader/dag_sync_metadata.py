"""
[10_sync_metadata_daily]
OpenMetadata → DB COMMENT + Wren AI 메타데이터 동기화

- OM에 등록된 테이블/컬럼 설명을 PostgreSQL COMMENT로 반영
- OM 설명을 Wren AI 모델에 동기화 + Deploy (Qdrant 임베딩 재생성)
- 매일 1회 실행 (OM에서 설명 수정 시 다음 날 자동 반영)
"""

import logging
import os
import subprocess
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

logger = logging.getLogger(__name__)

default_args = {
    "owner": "bip",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def sync_om_to_db(**context):
    """OM 설명 → PostgreSQL COMMENT 동기화"""
    import psycopg2
    import requests

    om_host = os.getenv("OM_HOST", "http://openmetadata-server:8585")
    om_token = os.getenv("OM_BOT_TOKEN", "")
    if not om_token:
        try:
            om_token = Variable.get("OM_BOT_TOKEN", default_var="")
        except Exception:
            pass

    if not om_token:
        raise ValueError("OM_BOT_TOKEN이 설정되지 않았습니다.")

    headers = {"Authorization": f"Bearer {om_token}"}

    # OM에서 테이블/컬럼 설명 가져오기
    tables = []
    after = None
    while True:
        url = (
            f"{om_host}/api/v1/tables?"
            f"database=bip-postgres.stockdb"
            f"&fields=columns&limit=50"
        )
        if after:
            url += f"&after={after}"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            break
        data = resp.json()
        for t in data.get("data", []):
            if t.get("databaseSchema", {}).get("name") == "public":
                tables.append(t)
        after = data.get("paging", {}).get("after")
        if not after:
            break

    logger.info(f"OM에서 {len(tables)}개 테이블 조회")

    # DB COMMENT 반영
    conn = psycopg2.connect(
        host=os.getenv("PG_HOST", "bip-postgres"),
        port=os.getenv("PG_PORT", "5432"),
        user=os.getenv("PG_USER", "user"),
        password=os.getenv("PG_PASSWORD", "pw1234"),
        dbname=os.getenv("PG_DB", "stockdb"),
    )
    cur = conn.cursor()

    table_count = 0
    col_count = 0

    for table in tables:
        name = table["name"]
        desc = table.get("description", "")
        if desc:
            try:
                cur.execute(
                    f"COMMENT ON TABLE public.{name} IS %s;", (desc,)
                )
                table_count += 1
            except Exception as e:
                logger.warning(f"TABLE {name} COMMENT 실패: {e}")
                conn.rollback()
                continue

        for col in table.get("columns", []):
            col_desc = col.get("description", "")
            if col_desc:
                try:
                    cur.execute(
                        f"COMMENT ON COLUMN public.{name}.{col['name']} IS %s;",
                        (col_desc,),
                    )
                    col_count += 1
                except Exception as e:
                    logger.warning(f"COLUMN {name}.{col['name']} COMMENT 실패: {e}")
                    conn.rollback()

    conn.commit()
    cur.close()
    conn.close()

    logger.info(f"DB COMMENT 반영 완료: TABLE {table_count}개, COLUMN {col_count}개")
    return f"DB: {table_count} tables, {col_count} columns"


def sync_om_to_wrenai(**context):
    """OM 설명 → Wren AI 모델 동기화 + Deploy"""
    import requests

    om_host = os.getenv("OM_HOST", "http://openmetadata-server:8585")
    om_token = os.getenv("OM_BOT_TOKEN", "")
    wren_ui = os.getenv("WREN_UI", "http://wren-ui:3000")

    if not om_token:
        try:
            om_token = Variable.get("OM_BOT_TOKEN", default_var="")
        except Exception:
            pass

    if not om_token:
        raise ValueError("OM_BOT_TOKEN이 설정되지 않았습니다.")

    om_headers = {"Authorization": f"Bearer {om_token}"}

    # 1) Wren AI 모델 목록
    resp = requests.post(
        f"{wren_ui}/api/graphql",
        json={"query": "{ listModels { id displayName sourceTableName } }"},
        timeout=10,
    )
    wren_models = {}
    for m in resp.json().get("data", {}).get("listModels", []):
        table = m["sourceTableName"].split(".")[-1]
        wren_models[table] = m["id"]

    if not wren_models:
        logger.info("Wren AI에 등록된 모델이 없습니다. 스킵.")
        return "No models"

    # 2) Wren AI 컬럼 ID 매핑 (SQLite 직접 조회)
    result = subprocess.run(
        ["docker", "exec", "wren-ui", "sh", "-c",
         "sqlite3 /app/data/db.sqlite3 "
         "\"SELECT model_id, display_name, id FROM model_column;\""],
        capture_output=True, text=True, timeout=30,
    )
    col_ids = {}
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) == 3:
            col_ids[(int(parts[0]), parts[1])] = int(parts[2])

    # 3) OM에서 설명 가져오기
    om_data = {}
    after = None
    while True:
        url = (
            f"{om_host}/api/v1/tables?"
            f"database=bip-postgres.stockdb&fields=columns&limit=50"
        )
        if after:
            url += f"&after={after}"
        resp = requests.get(url, headers=om_headers, timeout=15)
        if resp.status_code != 200:
            break
        data = resp.json()
        for t in data.get("data", []):
            if t.get("databaseSchema", {}).get("name") == "public":
                cols = {
                    c["name"]: c["description"]
                    for c in t.get("columns", [])
                    if c.get("description")
                }
                om_data[t["name"]] = {
                    "description": t.get("description", ""),
                    "columns": cols,
                }
        after = data.get("paging", {}).get("after")
        if not after:
            break

    # 4) Wren AI 모델 업데이트
    model_count = 0
    col_count = 0

    for table_name, model_id in wren_models.items():
        om_info = om_data.get(table_name)
        if not om_info:
            continue

        desc = om_info.get("description", "").replace("\\", "\\\\").replace('"', '\\"')
        col_updates = []
        for cname, cdesc in om_info.get("columns", {}).items():
            cid = col_ids.get((model_id, cname))
            if cid is not None:
                cdesc_esc = cdesc.replace("\\", "\\\\").replace('"', '\\"')
                col_updates.append(f'{{id: {cid}, description: "{cdesc_esc}"}}')
                col_count += 1

        cols_str = ", ".join(col_updates)
        query = (
            f'mutation {{ updateModelMetadata('
            f'where: {{id: {model_id}}}, '
            f'data: {{description: "{desc}", columns: [{cols_str}]}}'
            f') }}'
        )

        resp = requests.post(
            f"{wren_ui}/api/graphql",
            json={"query": query},
            timeout=30,
        )
        if resp.json().get("data", {}).get("updateModelMetadata"):
            model_count += 1

    # 5) Deploy (Qdrant 임베딩 재생성)
    if model_count > 0:
        resp = requests.post(
            f"{wren_ui}/api/graphql",
            json={"query": "mutation { deploy { status } }"},
            timeout=30,
        )
        status = resp.json().get("data", {}).get("deploy", {}).get("status", "UNKNOWN")
        logger.info(f"Wren AI Deploy: {status}")

    logger.info(f"Wren AI 동기화 완료: 모델 {model_count}개, 컬럼 {col_count}개")
    return f"Wren: {model_count} models, {col_count} columns"


with DAG(
    dag_id="10_sync_metadata_daily",
    default_args=default_args,
    description="OM → DB COMMENT + Wren AI 메타데이터 동기화 (매일 1회)",
    schedule_interval="0 0 * * *",  # 매일 09:00 KST (UTC 00:00)
    start_date=datetime(2026, 4, 1),
    catchup=False,
    tags=["metadata", "openmetadata", "wrenai"],
) as dag:

    sync_db = PythonOperator(
        task_id="sync_om_to_db",
        python_callable=sync_om_to_db,
    )

    sync_wren = PythonOperator(
        task_id="sync_om_to_wrenai",
        python_callable=sync_om_to_wrenai,
    )

    sync_db >> sync_wren
