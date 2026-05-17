#!/bin/bash
# dbt 학습조직 세미나 데모 시연 스크립트
#
# 사용: bash scripts/dbt_demo.sh
# 사전 조건: bip-postgres 컨테이너 실행 중
#
# 4단계 순서로 dbt의 핵심 기능을 보여줌:
#   1. dbt run     — 의존성 자동 추적 + 실행
#   2. dbt test    — 데이터 품질 자동 검증
#   3. dbt docs    — Lineage + 카탈로그 자동 생성
#   4. docs serve  — 브라우저에서 시각화 확인

set -e

DBT_COMPOSE="dbt/docker-compose.yml"
DBT_CONTAINER="bip-dbt"

# ---------- 컬러 출력 ----------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}▶ $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    sleep 1
}

# ---------- 컨테이너 기동 확인 ----------
if ! docker ps --format '{{.Names}}' | grep -q "^${DBT_CONTAINER}$"; then
    step "dbt 컨테이너 기동"
    docker compose -f "${DBT_COMPOSE}" up -d
    sleep 3
fi

# ---------- 연결 확인 ----------
step "[Step 0] DB 연결 확인 (dbt debug)"
docker exec ${DBT_CONTAINER} dbt debug 2>&1 | tail -5

# ---------- Step 1 ----------
step "[Step 1] 의존성 자동 추적 — dbt가 6개 모델 실행 순서를 결정"
docker exec ${DBT_CONTAINER} dbt run 2>&1 | grep -E "START sql|OK created|Done"
echo ""
echo -e "${GREEN}▶ 핵심: 사람이 실행 순서 관리할 필요 없음. {{ ref() }} 가 의존성 자동 추적${NC}"

# ---------- Step 2 ----------
step "[Step 2] 데이터 품질 자동 검증 — dbt test"
docker exec ${DBT_CONTAINER} dbt test 2>&1 | tail -5
echo ""
echo -e "${GREEN}▶ 핵심: not_null, unique, relationships, accepted_values 내장. 별도 도구 불필요${NC}"

# ---------- Step 3 ----------
step "[Step 3] 문서 + Lineage 자동 생성 — dbt docs generate"
docker exec ${DBT_CONTAINER} dbt docs generate 2>&1 | tail -3
echo ""
echo -e "${GREEN}▶ 핵심: schema.yml의 description이 그대로 카탈로그 사이트로${NC}"

# ---------- Step 4 ----------
step "[Step 4] 브라우저에서 확인 — http://localhost:8081"
echo -e "${YELLOW}    Lineage 그래프 + 컬럼 카탈로그 + 테스트 결과 모두 시각화${NC}"
echo ""
echo "    docs serve 실행 중... (Ctrl+C 로 종료)"
echo ""
docker exec ${DBT_CONTAINER} dbt docs serve --port 8080 --host 0.0.0.0
