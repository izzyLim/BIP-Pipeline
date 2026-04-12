# BIP-Pipeline

주식 투자 관리 시스템 — KOSPI/KOSDAQ/미국 주식 데이터 파이프라인 + 분석 + NL2SQL.

## 📋 개요

- **데이터 파이프라인**: Airflow가 9개 외부 소스(Yahoo Finance, DART, KRX, ECOS, GDELT, KIS, Naver News 등)에서 데이터 수집 → Raw/Derived/Gold 3단 Medallion Architecture로 저장
- **메타데이터 카탈로그**: OpenMetadata가 39개 테이블, 77개 용어집, 외부 API → DAG → Table → Consumer 전체 리니지 관리
- **NL2SQL**: Wren AI + 5개 모델 + 41개 SQL Pairs + 4-layer 보안 방어
- **에이전트**: 모닝 브리핑, 실시간 모니터링, LangGraph 파이프라인

## 🚀 시작하기

### 1. 사전 요구사항

- Docker & Docker Compose
- Python 3.10+
- `.env` 파일 생성 (아래 참조)

### 2. 환경변수 설정

`.env.example`을 참고하여 `.env` 파일 작성 (⚠️ **비밀값은 절대 커밋 금지**):

```bash
cp .env.example .env
# .env 파일을 열어 실제 값 입력:
# - PG_PASSWORD, NL2SQL_PG_PASSWORD
# - OPENAI_API_KEY, ANTHROPIC_API_KEY
# - DART_API_KEY, OM_BOT_TOKEN, 등
```

### 3. 인프라 기동

```bash
# Docker network 생성 (최초 1회)
docker network create stock-network

# PostgreSQL
docker-compose --env-file .env -f docker-compose.postgres.yml up -d

# NL2SQL 전용 role 생성 (비밀번호는 psql 변수로 주입)
docker exec -i bip-postgres psql -U user -d stockdb \
  -v nl2sql_password=$NL2SQL_PG_PASSWORD \
  -f /postgres/nl2sql_role.sql
docker exec -i bip-postgres psql -U user -d stockdb < postgres/nl2sql_audit.sql
docker exec -i bip-postgres psql -U user -d stockdb < postgres/agent_audit.sql

# OpenMetadata
docker-compose --env-file .env -f docker-compose.openmetadata.yml up -d

# Airflow
cd airflow && docker-compose --env-file ../.env up -d && cd ..

# Wren AI (NL2SQL)
docker-compose --env-file .env -f docker-compose.wrenai.yml up -d
```

### 4. 접속

| 서비스 | URL |
|--------|-----|
| Airflow | http://localhost:8080 |
| OpenMetadata | http://localhost:8585 |
| Wren AI UI | http://localhost:3000 |
| PostgreSQL | `localhost:5432/stockdb` |

---

## 🔒 보안 거버넌스 (필독)

이 프로젝트에서 **코드를 작성하거나 에이전트를 추가하기 전에 반드시 아래 문서를 읽고 준수**해야 합니다.

### 핵심 불변 조건

1. **원본 데이터(raw value)를 LLM 프롬프트에 절대 주입 금지**
   - 스키마 스캐너는 `type_summary`(포맷/길이/distinct_count)만 전달
   - 민감 테이블은 LLM 파이프라인 자체에서 제외

2. **NL2SQL 실행은 `nl2sql_exec` 전용 계정만 사용**
   - 민감 테이블(`portfolio`, `users`, `portfolio_snapshot` 등)은 DB 레벨에서 `permission denied`
   - 일반 `user` 계정을 NL2SQL 경로에 재사용 금지

3. **모든 AI 에이전트 실행은 감사 로그에 기록**
   - `agent_audit_log`: 모든 LLM 호출 (리포트/모니터링/LangGraph/NL2SQL/임베딩)
   - `nl2sql_audit_log`: NL2SQL SQL 생성/검증/실행 세부
   - 감사 실패 시 **fail-closed** (결과 반환 금지)

4. **비밀값은 코드/문서/git 히스토리에 남기지 않음**
   - `.env`만 사용, `.env.example`은 플레이스홀더만
   - 커밋 전 `git diff`로 비밀 노출 검토

5. **OpenMetadata 프로파일러는 raw sample 수집 금지**
   - `includeColumnSample: false`, 민감 테이블 `tableFilterPattern.excludes`

### 민감 자산 목록 (LLM/NL2SQL 접근 금지)

| 분류 | 테이블 |
|------|--------|
| Raw 사용자/인증 | `portfolio`, `users`, `user_watchlist`, `holding`, `transaction`, `cash_transaction` |
| Derived 민감 | `portfolio_snapshot` (총자산/손익) |
| 운영 | `monitor_alerts`, `agent_audit_log`, `nl2sql_audit_log` |

### 4-Layer 방어 구조

```
Layer 1: 문법/키워드 차단    → query_validator (SELECT-only, DDL 금지)
Layer 2: Allowlist 검증      → sqlglot AST로 참조 테이블 파싱
Layer 3: DB role 격리        → nl2sql_exec 계정만 사용, 민감 테이블 GRANT 없음
Layer 4: Curated 뷰 전용     → base 테이블 직접 접근 금지 (향후)
```

신규 기능/에이전트 배포 전 반드시 `docs/security_governance.md` 섹션 5 체크리스트 수행.

---

## 📊 메타데이터 거버넌스 (필독)

테이블/컬럼/DAG/외부 소스를 **신규 생성하거나 변경**할 때는 메타데이터도 같이 갱신해야 합니다.
**메타데이터 원천은 OpenMetadata**이고, DB COMMENT와 Wren AI 모델 설명은 OM에서 파생되어 `10_sync_metadata_daily` DAG로 자동 동기화됩니다.

### 핵심 규칙

1. 신규 테이블 생성 시 테이블 설명, 주요 컬럼 설명(단위/계산식 포함), DataLayer 태그, Domain 태그를 **같이** 작성 (빈 상태 배포 금지)
2. 스키마 변경 시 OM/lineage/SQL Pairs/문서를 같이 갱신
3. 신규 DAG 배포 시 `register_table_lineage_async()` 호출 없이 머지 금지
4. 외부 소스 추가 시 `scripts/om_register_data_sources.py`에 apiService + apiEndpoint + SourceType 태그 등록
5. Gold 테이블(`analytics_*`) 변경 시 파생 민감성 재검토 + NL2SQL allowlist/role 확인

상세 플레이북: `docs/metadata_governance.md` 섹션 3 (상황별 필수 작업 7개)

---

## 📚 필수 문서

**신규 팀원 온보딩 / PR 작성 전 반드시 읽어야 하는 문서:**

| 문서 | 목적 |
|------|------|
| **`docs/security_governance.md`** | 보안 불변 조건, 민감 자산 목록, 에이전트별 요구사항, 사고 대응 |
| **`docs/metadata_governance.md`** | 메타데이터/리니지/용어 관리 절차, SLO, 체크리스트 |
| **`docs/data_architecture_review.md`** | 전체 아키텍처, 이슈 트래커, 결정 로그 |
| **`docs/nl2sql_design.md`** | NL2SQL 설계, 아키텍처, 계획, 현황 (통합) |
| **`docs/nl2sql_concepts.md`** | NL2SQL 개념/용어 레퍼런스 |
| **`docs/wrenai_technical_guide.md`** | Wren AI 구성, 동기화 흐름, 대안 비교 |
| **`docs/wrenai_test_report.md`** | NL2SQL 품질 테스트 프레임워크 및 결과 |

**프로젝트 루트의 `CLAUDE.md`**는 Claude Code 세션이 자동으로 로드하는 에이전트 지시 파일로, 위 문서를 참조합니다.

---

## 🗂 디렉토리 구조

```
BIP-Pipeline/
├── CLAUDE.md                       # Claude Code 에이전트 지시 (자동 로드)
├── docs/                           # 거버넌스/아키텍처 문서
│   ├── security_governance.md
│   ├── metadata_governance.md
│   ├── data_architecture_review.md
│   ├── nl2sql_design.md
│   ├── nl2sql_concepts.md
│   ├── wrenai_technical_guide.md
│   └── wrenai_test_report.md
├── airflow/
│   ├── dags/
│   │   ├── stock_loader/           # 43개 DAG (수집/변환/Gold)
│   │   ├── reports/                # 모닝 브리핑, 시장 모니터링
│   │   ├── nl2sql/                 # NL2SQL 검증기 + 실행기 + 보안 테스트
│   │   └── utils/
│   │       ├── audited_llm.py      # 🔒 감사 포함 LLM 호출 wrapper
│   │       └── lineage.py          # OM lineage 등록
│   └── docker-compose.yaml
├── postgres/
│   ├── init.sql / patch.sql        # 스키마
│   ├── nl2sql_role.sql             # 🔒 NL2SQL 전용 DB role (idempotent)
│   ├── nl2sql_audit.sql            # NL2SQL 감사 로그
│   └── agent_audit.sql             # 전체 AI 에이전트 감사 로그
├── openmetadata/
│   └── connectors/                 # OM Ingestion 설정 (env 주입)
├── wrenai/
│   └── config.yaml                 # Wren AI MDL + LLM 설정
├── scripts/                        # OM 자동화 스크립트
│   ├── om_sync_comments.py         # OM → DB COMMENT
│   ├── om_sync_wrenai.py           # OM → Wren AI
│   ├── om_register_data_sources.py # 외부 API 등록
│   └── ...
└── shared/
    └── config.py                   # 🔒 공통 설정 (비밀 필수 검증)
```

---

## 🧪 보안 통합 테스트 실행

NL2SQL 4-layer 방어가 실제로 동작하는지 검증:

```bash
PG_HOST=localhost PG_PORT=5432 \
  PG_USER=user PG_PASSWORD=<password> PG_DB=stockdb \
  NL2SQL_PG_USER=nl2sql_exec NL2SQL_PG_PASSWORD=<nl2sql_password> \
  python3 airflow/dags/nl2sql/test_nl2sql_security.py
```

**39개 테스트 항목:**
- Layer 1: 키워드/위험 패턴 차단 (6)
- Layer 2: portfolio/portfolio_snapshot/allowlist 검증 (8)
- Layer 3: DB role 실제 permission denied 확인 (3)
- 정상 쿼리 happy path (3)
- 감사 persistence (5)
- Least-privilege (admin 비번 없이 동작) (4)
- Fail-closed on audit failure (4)
- Identity 검증 (config override + Airflow conn bypass) (6)

---

## 🤖 AI 에이전트 사용 원칙

### Claude Code

- `CLAUDE.md`가 자동 로드되며, 보안·메타데이터 거버넌스 규칙이 최상단에 명시됨
- 세션 시작 시 `docs/security_governance.md`와 `docs/metadata_governance.md`를 참조

### Wren AI (NL2SQL)

- DB 커넥션은 `nl2sql_exec` 전용 계정만 사용
- 민감 테이블 모델 등록 금지
- 모든 질의는 `nl2sql_audit_log` + `agent_audit_log` 양쪽 기록

### 리포트/모니터링/LangGraph 에이전트

- Anthropic/OpenAI 직접 호출 금지 → `utils.audited_llm` wrapper 사용 필수
- 감사 기록 없이 머지 금지

### 신규 자동화 스크립트

- `utils.audited_llm` 또는 `record_agent_audit()` 호출 포함
- 민감 테이블 조회 시 운영자 승인 + `policy_violations` 기록

---

## 📝 기여 가이드

### PR 전 체크리스트

```
□ docs/security_governance.md 섹션 5 보안 체크리스트 수행
□ docs/metadata_governance.md 섹션 6 변경 관리 체크리스트 수행
□ git diff로 .env/비밀값 노출 검토
□ 신규 LLM 호출은 audited_llm wrapper 경유
□ 신규 DAG는 register_table_lineage_async() 호출
□ NL2SQL 관련 변경이면 test_nl2sql_security.py 재실행 (39/39 PASS 유지)
```

### 비밀 노출 감지 시

즉시 회전 + 히스토리 정리. `docs/security_governance.md` 섹션 4-1 참조.

---

## 🛠 주요 스크립트

| 스크립트 | 역할 |
|---------|------|
| `scripts/om_enrich_metadata.py` | OM 테이블/컬럼 설명 일괄 등록 |
| `scripts/om_build_glossary.py` | OM 용어집 구축 (77개) |
| `scripts/om_tag_tables.py` | DataLayer/Domain 태그 등록 |
| `scripts/om_register_data_sources.py` | 외부 API → OM apiEndpoint 등록 |
| `scripts/om_sync_comments.py` | OM → PostgreSQL COMMENT 동기화 |
| `scripts/om_sync_wrenai.py` | OM → Wren AI 모델 설명 동기화 |
| `scripts/backfill_indicators.py` | 기술지표 백필 |

---

## 📄 라이선스

Private project — 무단 복제/배포 금지.
