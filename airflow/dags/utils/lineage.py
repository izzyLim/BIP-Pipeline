"""
OpenMetadata Lineage 자동 등록 유틸리티

DAG 실행 중 DB 쓰기 함수가 호출될 때 자동으로 pipeline → table lineage를 OM에 등록합니다.
실패해도 DAG 실행에 영향을 주지 않습니다 (silent fail).

환경변수:
    OM_HOST      : OpenMetadata 서버 주소 (기본값: http://openmetadata-server:8585)
    OM_BOT_TOKEN : ingestion-bot JWT 토큰
"""

import logging
import os
import threading
from functools import lru_cache
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OM_HOST = os.getenv("OM_HOST", "http://openmetadata-server:8585")
OM_SERVICE_PIPELINE = os.getenv("OM_SERVICE_PIPELINE", "bip-airflow")
OM_SERVICE_DB = os.getenv("OM_SERVICE_DB", "bip-postgres")
OM_DB_NAME = os.getenv("OM_DB_NAME", "stockdb")
OM_DB_SCHEMA = os.getenv("OM_DB_SCHEMA", "public")

_token_lock = threading.Lock()
_cached_token: Optional[str] = None


def _get_token() -> Optional[str]:
    """환경변수에서 OM 토큰을 읽습니다."""
    return os.getenv("OM_BOT_TOKEN")


def _get_headers() -> Optional[dict]:
    token = _get_token()
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


@lru_cache(maxsize=128)
def _get_entity_id(fqn: str, entity_type: str) -> Optional[str]:
    """FQN으로 OM 엔티티 ID를 조회합니다. 결과를 캐싱합니다."""
    headers = _get_headers()
    if not headers:
        return None

    endpoint_map = {
        "table": "tables",
        "pipeline": "pipelines",
    }
    endpoint = endpoint_map.get(entity_type)
    if not endpoint:
        return None

    try:
        resp = requests.get(
            f"{OM_HOST}/api/v1/{endpoint}/name/{fqn}",
            headers=headers,
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json().get("id")
    except Exception as e:
        logger.debug(f"OM entity lookup failed for {fqn}: {e}")
    return None


def _get_dag_context() -> tuple[Optional[str], Optional[str]]:
    """현재 실행 중인 Airflow task의 dag_id, task_id를 반환합니다."""
    try:
        from airflow.operators.python import get_current_context
        ctx = get_current_context()
        dag_id = ctx["dag"].dag_id
        task_id = ctx["task_instance"].task_id
        return dag_id, task_id
    except Exception:
        return None, None


def _put_lineage(from_id: str, from_type: str, to_id: str, to_type: str, headers: dict) -> bool:
    """OM lineage API 단일 edge 등록."""
    try:
        resp = requests.put(
            f"{OM_HOST}/api/v1/lineage",
            headers=headers,
            json={"edge": {
                "fromEntity": {"id": from_id, "type": from_type},
                "toEntity": {"id": to_id, "type": to_type},
            }},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f"[Lineage] OM 연결 오류: {e}")
        return False


def register_table_lineage(
    target_table: Optional[str],
    dag_id: Optional[str] = None,
    source_tables: Optional[list] = None,
) -> bool:
    """
    lineage를 OpenMetadata에 등록합니다.

    쓰기 DAG (target_table 있음):
        source_table → pipeline → target_table

    읽기 전용 DAG (target_table=None):
        source_table → pipeline  (pipeline이 종착점, 예: 이메일 발송 리포트)

    Args:
        target_table:  쓰기 대상 테이블명. None이면 읽기 전용 DAG로 처리.
        dag_id:        DAG ID. None이면 Airflow 컨텍스트에서 자동 감지.
        source_tables: 읽기 소스 테이블 목록 (예: ["stock_price_1d", "stock_info"])

    Returns:
        성공 여부 (실패해도 예외를 발생시키지 않음)
    """
    headers = _get_headers()
    if not headers:
        logger.debug("OM_BOT_TOKEN not set, skipping lineage registration")
        return False

    if dag_id is None:
        dag_id, _ = _get_dag_context()
    if dag_id is None:
        logger.debug("Could not determine dag_id, skipping lineage registration")
        return False

    pipeline_fqn = f"{OM_SERVICE_PIPELINE}.{dag_id}"
    pipeline_id = _get_entity_id(pipeline_fqn, "pipeline")
    if not pipeline_id:
        logger.debug(f"Pipeline not found in OM: {pipeline_fqn}")
        return False

    ok = True

    # pipeline → target_table (쓰기 DAG만)
    if target_table is not None:
        target_fqn = f"{OM_SERVICE_DB}.{OM_DB_NAME}.{OM_DB_SCHEMA}.{target_table}"
        target_id = _get_entity_id(target_fqn, "table")
        if not target_id:
            logger.debug(f"Table not found in OM: {target_fqn}")
            ok = False
        else:
            ok = _put_lineage(pipeline_id, "pipeline", target_id, "table", headers)
            if ok:
                logger.info(f"[Lineage] {dag_id} → {target_table} 등록 완료")

    # source_table → pipeline
    for src in (source_tables or []):
        src_fqn = f"{OM_SERVICE_DB}.{OM_DB_NAME}.{OM_DB_SCHEMA}.{src}"
        src_id = _get_entity_id(src_fqn, "table")
        if not src_id:
            logger.debug(f"Source table not found in OM: {src_fqn}")
            continue
        if _put_lineage(src_id, "table", pipeline_id, "pipeline", headers):
            logger.info(f"[Lineage] {src} → {dag_id} 등록 완료")

    return ok


def register_table_lineage_async(
    target_table: str,
    dag_id: Optional[str] = None,
    source_tables: Optional[list] = None,
):
    """비동기로 lineage를 등록합니다. DAG 실행 성능에 영향을 주지 않습니다."""
    if dag_id is None:
        dag_id, _ = _get_dag_context()

    t = threading.Thread(
        target=register_table_lineage,
        args=(target_table, dag_id, source_tables),
        daemon=True,
    )
    t.start()
