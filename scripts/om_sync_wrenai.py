"""
OpenMetadata → Wren AI 메타데이터 동기화 스크립트
============================================================
OM에 등록된 테이블/컬럼 설명을 Wren AI 모델에 반영합니다.
Wren AI GraphQL API의 updateModelMetadata를 사용합니다.

데이터 흐름:
    OM (원천) → 이 스크립트 → Wren AI (모델 description)
                           → DB COMMENT (om_sync_comments.py)

사용법:
    OM_HOST=http://localhost:8585 python scripts/om_sync_wrenai.py
    python scripts/om_sync_wrenai.py --dry-run
"""

import argparse
import os
import sys

import requests

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
OM_HOST = os.getenv("OM_HOST", "http://localhost:8585")
OM_BOT_TOKEN = os.getenv("OM_BOT_TOKEN", "")
WREN_UI = os.getenv("WREN_UI", "http://localhost:3000")

OM_DB_SERVICE = "bip-postgres"
OM_DB_NAME = "stockdb"
OM_DB_SCHEMA = "public"


def get_om_headers():
    if not OM_BOT_TOKEN:
        print("OM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    return {"Authorization": f"Bearer {OM_BOT_TOKEN}"}


# ─────────────────────────────────────────────
# Wren AI: 현재 모델/컬럼 ID 매핑
# ─────────────────────────────────────────────

def get_wren_models() -> dict:
    """Wren AI에 등록된 모델 목록을 가져옵니다. {table_name: model_id}"""
    resp = requests.post(
        f"{WREN_UI}/api/graphql",
        json={"query": "{ listModels { id displayName sourceTableName } }"},
        timeout=10,
    )
    data = resp.json().get("data", {}).get("listModels", [])
    result = {}
    for m in data:
        # sourceTableName: "public.stock_info" → "stock_info"
        table = m["sourceTableName"].split(".")[-1] if "." in m["sourceTableName"] else m["sourceTableName"]
        result[table] = m["id"]
    return result


def get_wren_columns(model_id: int) -> dict:
    """Wren AI 모델의 컬럼 목록을 가져옵니다. {col_name: col_id}"""
    resp = requests.post(
        f"{WREN_UI}/api/graphql",
        json={"query": f'{{ model(where: {{id: {model_id}}}) {{ fields {{ displayName referenceName }} }} }}'},
        timeout=10,
    )
    fields = resp.json().get("data", {}).get("model", {}).get("fields", [])
    # displayName과 referenceName은 같으므로 referenceName 사용
    # 하지만 GraphQL에서 field ID를 직접 안 줌 → SQLite에서 가져와야 함
    return {f["referenceName"]: f["displayName"] for f in fields}


def get_wren_column_ids() -> dict:
    """Wren AI SQLite에서 직접 (model_id, col_name) → col_id 매핑을 가져옵니다."""
    import subprocess
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", "wren-data:/data", "alpine", "sh", "-c",
         "apk add --no-cache sqlite >/dev/null 2>&1 && "
         "sqlite3 /data/db.sqlite3 "
         "\"SELECT mc.model_id, mc.display_name, mc.id FROM model_column mc;\""],
        capture_output=True, text=True, timeout=30,
    )
    mapping = {}  # (model_id, col_name) → col_id
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) == 3:
            model_id, col_name, col_id = int(parts[0]), parts[1], int(parts[2])
            mapping[(model_id, col_name)] = col_id
    return mapping


# ─────────────────────────────────────────────
# OM: 테이블/컬럼 설명 가져오기
# ─────────────────────────────────────────────

def fetch_om_descriptions(headers: dict) -> dict:
    """OM에서 테이블/컬럼 설명을 가져옵니다.
    Returns: {table_name: {"description": "...", "columns": {col_name: "desc"}}}
    """
    result = {}
    after = None

    while True:
        url = (
            f"{OM_HOST}/api/v1/tables?"
            f"database={OM_DB_SERVICE}.{OM_DB_NAME}"
            f"&fields=columns&limit=50"
        )
        if after:
            url += f"&after={after}"

        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            break

        data = resp.json()
        for table in data.get("data", []):
            schema = table.get("databaseSchema", {}).get("name", "")
            if schema != OM_DB_SCHEMA:
                continue

            table_name = table["name"]
            cols = {}
            for c in table.get("columns", []):
                desc = c.get("description", "")
                if desc:
                    cols[c["name"]] = desc

            result[table_name] = {
                "description": table.get("description", ""),
                "columns": cols,
            }

        paging = data.get("paging", {})
        after = paging.get("after")
        if not after:
            break

    return result


# ─────────────────────────────────────────────
# Wren AI: updateModelMetadata 호출
# ─────────────────────────────────────────────

def update_wren_model(model_id: int, description: str, columns: list[dict], dry_run: bool) -> bool:
    """Wren AI 모델 + 컬럼 설명을 업데이트합니다."""
    if dry_run:
        return True

    # Escape quotes for GraphQL
    desc_escaped = description.replace("\\", "\\\\").replace('"', '\\"')

    # Build columns array
    col_parts = []
    for c in columns:
        cdesc = c["description"].replace("\\", "\\\\").replace('"', '\\"')
        col_parts.append(f'{{id: {c["id"]}, description: "{cdesc}"}}')
    cols_str = ", ".join(col_parts)

    query = (
        f'mutation {{ updateModelMetadata('
        f'where: {{id: {model_id}}}, '
        f'data: {{description: "{desc_escaped}", columns: [{cols_str}]}}'
        f') }}'
    )

    try:
        resp = requests.post(
            f"{WREN_UI}/api/graphql",
            json={"query": query},
            timeout=30,
        )
        result = resp.json()
        return result.get("data", {}).get("updateModelMetadata") is True
    except Exception as e:
        print(f"    GraphQL 오류: {e}")
        return False


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def main(dry_run: bool = False):
    print(f"\n{'=' * 60}")
    print(f"OpenMetadata → Wren AI 메타데이터 동기화")
    print(f"OM: {OM_HOST}")
    print(f"Wren UI: {WREN_UI}")
    print(f"DRY-RUN: {dry_run}")
    print(f"{'=' * 60}\n")

    # 1) Wren AI 모델/컬럼 ID 매핑
    wren_models = get_wren_models()
    wren_col_ids = get_wren_column_ids()
    print(f"Wren AI 모델: {len(wren_models)}개")
    for tbl, mid in wren_models.items():
        print(f"  {tbl} (model_id={mid})")

    # 2) OM 설명 가져오기
    om_headers = get_om_headers()
    om_data = fetch_om_descriptions(om_headers)
    print(f"\nOM 테이블: {len(om_data)}개 (설명 있는 것만)\n")

    # 3) 매칭 & 동기화
    stats = {"models": 0, "columns": 0}

    for table_name, model_id in wren_models.items():
        om_info = om_data.get(table_name)
        if not om_info:
            print(f"  {table_name}: OM에 없음, 스킵")
            continue

        table_desc = om_info.get("description", "")
        om_cols = om_info.get("columns", {})

        # 매칭되는 컬럼 설명 수집
        col_updates = []
        for col_name, col_desc in om_cols.items():
            col_id = wren_col_ids.get((model_id, col_name))
            if col_id is not None:
                col_updates.append({"id": col_id, "description": col_desc})

        if dry_run:
            print(f"  [DRY-RUN] {table_name}: desc={table_desc[:50]}..., {len(col_updates)}개 컬럼")
        else:
            ok = update_wren_model(model_id, table_desc, col_updates, dry_run)
            if ok:
                print(f"  {table_name}: {len(col_updates)}개 컬럼 설명 반영")
                stats["models"] += 1
                stats["columns"] += len(col_updates)
            else:
                print(f"  {table_name}: 업데이트 실패")

    # 4) Deploy (Qdrant 임베딩 재생성)
    if not dry_run and stats["models"] > 0:
        print("\nDeploy 실행 (Qdrant 임베딩 재생성)...")
        resp = requests.post(
            f"{WREN_UI}/api/graphql",
            json={"query": "mutation { deploy { status } }"},
            timeout=30,
        )
        status = resp.json().get("data", {}).get("deploy", {}).get("status", "UNKNOWN")
        print(f"  Deploy: {status}")

    print(f"\n{'=' * 60}")
    print(f"완료: 모델 {stats['models']}개, 컬럼 {stats['columns']}개 설명 반영 + Deploy")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OM → Wren AI 메타데이터 동기화")
    parser.add_argument("--dry-run", action="store_true", help="실제 변경 없이 미리보기")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
