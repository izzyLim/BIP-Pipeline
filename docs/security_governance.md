# BIP-Pipeline 보안 거버넌스

> **작성일:** 2026-04-05
> **대상:** 프로젝트에서 동작하는 모든 에이전트 (Claude Code, Wren AI, LangGraph, 자동화 스크립트)
> **목적:** 민감 데이터 보호, 공격 표면 최소화, 사고 대응 원칙 수립
> **업데이트 원칙:** 신규 에이전트/도구 추가 시, 배포 전에 본 문서를 반드시 검토·갱신

---

## 1. 보안 불변 조건 (Inviolable Rules)

다음 조건은 **모든 에이전트와 자동화 흐름이 반드시 준수**해야 하며, 예외가 필요하면 명시적 승인과 문서화를 거쳐야 합니다.

### 1-1. 원본 데이터는 LLM에 전달하지 않는다

- 스키마 스캐너, 메타데이터 자동화, RAG 인덱서 등 **어떤 경로로도 raw 값을 LLM 프롬프트에 주입 금지**
- 대신 타입 요약(`type_summary`), 포맷 힌트, 길이/값 범위, distinct_count, null_ratio 등 **구조적 요약**만 전달
- 민감 테이블/컬럼은 **LLM 파이프라인 자체에서 제외** (denylist 필수)

### 1-2. NL2SQL 실행은 최소 권한 DB role로만 수행

- 전용 역할 `nl2sql_reader` + 사용자 `nl2sql_exec` 사용
- 일반 애플리케이션 계정(`user`)이나 DB admin 계정 재사용 금지
- 민감 테이블은 `GRANT` 자체가 없어야 한다 (DB 레벨 방어)

### 1-3. 방어는 4-layer, 한 층이 뚫려도 다음 층에서 차단

| Layer | 방어 수단 | 구현 위치 |
|-------|---------|---------|
| 1. 문법/키워드 | SELECT-only, DDL/DML 금지, 위험 패턴 차단 | `query_validator.py` |
| 2. Allowlist | 허용 테이블/컬럼만 참조 가능 (sqlglot AST) | `validator_config.py::NL2SQL_ALLOWLIST` |
| 3. DB role | 민감 테이블에 GRANT 없음 | `postgres/nl2sql_role.sql` |
| 4. Curated view | base 테이블 직접 접근 금지 (향후) | `v_nl2sql_*` 뷰 |

### 1-4. 모든 AI 에이전트 실행은 감사 로그에 기록

**두 개의 감사 경로를 함께 운영합니다:**

| 감사 테이블 | 범위 | 기록 주체 |
|------------|------|---------|
| `agent_audit_log` | 모든 AI 에이전트 호출 (리포트, 체크리스트, LangGraph, NL2SQL, 임베딩 등) | 공통 |
| `nl2sql_audit_log` | NL2SQL의 SQL 생성/검증/실행 세부 기록 | NL2SQL 전용 상세 로그 |

**`agent_audit_log` 필수 기록 항목:**
- agent_name, agent_type, run_id
- llm_provider, llm_model, prompt_class
- input_summary (raw 비밀값 제외) + input_hash
- tools_used, data_sources, referenced_tables
- status, error_message, output_summary, policy_violations
- sensitive_data_flag (민감 테이블 접근 시도 탐지 플래그)

**`nl2sql_audit_log` 필수 기록 항목 (NL2SQL 추가 상세):**
- 질문, 생성 SQL, 검증 결과, 참조 테이블, 차단 사유, 실행 결과

**적용 범위 확장 원칙:**
- Anthropic/OpenAI 직접 호출 경로(리포트/체크리스트/LangGraph)도 `agent_audit_log`에 기록
- 신규 에이전트 배포 시 감사 hook 통합 없이 머지 금지
- 감사 실패가 에이전트 실행을 막지는 않도록 하되, 기록 실패는 ERROR 레벨 로그로 남김
- `nl2sql_reader`는 두 감사 테이블 모두 INSERT만 가능, SELECT 불가

### 1-6. OpenMetadata 프로파일링 정책 (raw 데이터 격리)

OM은 메타데이터 원천이지만, 프로파일러가 raw 샘플을 수집하면 LLM 금지 규칙이 우회될 수 있습니다.
**프로파일러 설정은 다음을 반드시 만족해야 합니다:**

- `includeColumnSample: false`, `generateSampleData: false`, `sampleDataCount: 0`
- 민감 테이블은 `tableFilterPattern.excludes`에 명시 (섹션 2-1 "민감 자산 목록"과 동기화)
- 민감 컬럼 패턴은 `columnFilterPattern.excludes`에 정규식으로 차단
- 통계값(min/max/avg/distinct_count/null_ratio)은 허용 — raw 값이 아님
- 신규 테이블 추가 시 프로파일러 config 리뷰가 신규 테이블 플레이북의 **block step**

설정 파일: `openmetadata/connectors/bip_profiler.yaml`

### 1-7. 비밀 정보는 코드/문서/git 히스토리에 남기지 않는다

- API 키, DB 비밀번호, JWT 토큰, Fernet 키, 개인정보는 **절대 커밋 금지**
- 실수로 커밋된 경우 **즉시 회전(rotate)** + 히스토리 정리
- `.env`만 사용, `.env.example`은 플레이스홀더만 포함
- 관리 방법: 환경변수, Airflow Variable, 외부 vault

---

## 2. 민감 자산 목록 (Sensitive Inventory)

본 프로젝트에서 **LLM/NL2SQL 접근이 차단된 자산** 목록. 신규 민감 자산 추가 시 즉시 업데이트.

### 2-1. 테이블 (차단)

**Raw 사용자/인증 데이터:**

| 테이블 | 민감 사유 |
|--------|---------|
| `portfolio` | KIS 인증키(`kis_app_key`, `kis_app_secret`), 계좌번호, 계좌 패스워드 |
| `users` | 사용자 계정, 이메일 |
| `user_watchlist` | 사용자 관심 종목 |
| `holding` | 보유 현황 (포지션/금액) |
| `transaction` | 거래 내역 |
| `cash_transaction` | 입출금 내역 |

**파생 재무/사용자 데이터 (Derived Sensitive):**

다른 raw 테이블에서 계산되었더라도 **사용자별 재무 상태**를 드러내면 민감 데이터로 취급.

| 테이블 | 민감 사유 |
|--------|---------|
| `portfolio_snapshot` | 포트폴리오별 총자산(`total_value_krw`), 현금(`cash_value_krw`), 일별 손익(`daily_pnl`), 누적 손익(`total_pnl`) — 사용자별 재무 상태 노출 |

**운영 이력:**

| 테이블 | 민감 사유 |
|--------|---------|
| `monitor_alerts` | 운영 알림 발송 이력 (내부 모니터링 패턴 노출) |

**에이전트가 이 표의 테이블이 필요하면 직접 접근 대신 다음 중 하나:**
1. Owner-scoped 뷰 (`WHERE portfolio_id = :current_user_portfolio`) 생성
2. 집계/마스킹 뷰 (`v_portfolio_aggregate_masked` 등) 생성
3. 운영자 승인 + 감사 로그 기록 후 예외 부여

**신규 테이블 추가 시 판단 기준:**
- 컬럼에 다음 중 하나라도 포함되면 민감: 사용자 ID, 계좌/자산/잔액, 인증키/토큰, 개인식별정보
- raw가 아닌 파생/집계라도 사용자별 재무/개인 상태가 드러나면 민감
- 애매하면 기본값을 "민감"으로 설정하고 allowlist에서 시작

### 2-2. 컬럼 패턴 (차단)

정규식으로 자동 매칭되는 컬럼명 패턴:

```
.*_secret$        .*_key$        .*_token$
.*_password$      ^email$        ^phone$
^ssn$             ^account_number$
```

### 2-3. 외부 비밀 (코드 외부 관리)

| 항목 | 관리 방법 | 위치 |
|------|---------|------|
| PostgreSQL `user` 비밀번호 | 환경변수 `PG_PASSWORD` | `.env` (git 제외) |
| `nl2sql_exec` 비밀번호 | 환경변수 `NL2SQL_PG_PASSWORD` | `.env` (git 제외) |
| OpenMetadata JWT | 환경변수 `OM_BOT_TOKEN` | `.env`, Airflow Variable |
| OM Fernet 키 | 컨테이너 내부만 | DB 복호화 시 일회성 사용 |
| DART API 키 | `DART_API_KEY` | `.env` |
| OpenAI API 키 | `OPENAI_API_KEY` | `.env` |
| Anthropic API 키 | `ANTHROPIC_API_KEY` | Airflow Variable |
| KIS API 키 | DB `portfolio` 테이블 (암호화 권장) | RAM/vault 권장 |
| Telegram Bot Token | Airflow Variable | `TELEGRAM_BOT_TOKEN` |
| Naver API Client Secret | Airflow Variable | `naver_client_secret` |
| SMTP 패스워드 | Airflow Variable | `smtp_password` |

---

## 3. 에이전트별 보안 요구사항

### 3-1. Claude Code (현재 작업 에이전트)

- **파일 쓰기**: `.env`, `.env.example`에 실제 비밀값 기재 금지. 플레이스홀더만 허용.
- **커밋**: 커밋 전 `git diff`로 노출 검토. `.env` 관련 파일은 staged 목록에서 제거.
- **로그 출력**: 쿼리 결과에 민감 컬럼이 포함되면 출력 전 마스킹/생략.
- **SQL 실행**: DB 직접 조회 시 `user` 대신 `nl2sql_exec` 우선 사용 (읽기 전용 작업인 경우).

### 3-2. Wren AI (NL2SQL 엔진)

- **DB 커넥션**: `nl2sql_exec`만 사용 (`user` 재사용 금지) ✅ 적용 완료 (2026-04-05)
- **모델 등록**: 민감 테이블(`portfolio`, `users`, `portfolio_snapshot` 등) 등록 금지
- **MDL description**: 민감 컬럼 설명 작성 시에도 실제 값 예시 금지
- **SQL Pairs**: 예시 SQL에 민감 테이블 참조 금지
- **Instructions**: 민감 패턴 유도하는 규칙 금지
- **감사**: Wren AI 질의는 `nl2sql_audit_log` + `agent_audit_log` 양쪽에 기록 (NL2SQL 상세 + 공통 감사)

### 3-3. 리포트/모니터링 에이전트 (morning_report, market_monitor_checklist, news_retriever, llm_analyzer)

- **LLM 호출**: Anthropic/OpenAI 직접 호출 시 `agent_audit_log`에 반드시 기록
  - agent_name, agent_type, llm_provider, llm_model, prompt_class 필수
  - input_summary는 raw 민감값 제외 (해시는 원본으로 계산)
- **데이터 소스**: 민감 테이블 직접 조회 금지. 필요한 경우 운영자 승인 + policy_violations 기록
- **프롬프트 구성**: DB 행을 LLM 프롬프트에 넣을 때 민감 컬럼 제거 또는 마스킹
- **API 키**: 코드에 하드코딩 금지. Airflow Variable 또는 환경변수 사용
- **알림 전송**: Telegram/Email 본문에 민감 필드(계좌/인증키) 노출 금지

### 3-4. LangGraph 에이전트 (BIP-Agents)

- **도구(tool) 목록**: DB 도구는 `nl2sql_exec` 커넥션만 허용
- **컨텍스트 주입**: OM API 호출 시 민감 테이블 메타데이터 필터링
- **메모리**: 세션 간 영구 저장 시 민감 정보 마스킹 필수
- **응답 생성**: LLM 최종 응답에 raw 비밀값 포함 금지 (사후 검증)
- **감사**: BIP-Agents FastAPI 응답에 `audit` 메타데이터 포함, Airflow 쪽에서 `record_agent_audit()` 호출

- **✅ 2026-04-05 구현 완료**:
  - `bip-agents-api` FastAPI 서버가 `/api/checklist/analyze`, `/api/preopen/analyze` 응답에 `AuditMeta` 포함
  - 포함 필드: `run_id`, `agent_name`, `agent_type`, `llm_provider`, `llm_model`, `prompt_class`,
    `prompt_tokens`, `completion_tokens`, `tools_used`, `data_sources`, `referenced_tables`,
    `execution_ms`, `status`, `error_message`
  - Airflow `dag_market_monitor.py`가 응답에서 audit을 추출하여 `agent_audit_log`에 INSERT
  - `market_monitor_checklist`, `market_monitor_preopen` 모두 감사 경로 연결됨
- **현재 한계**: 체크리스트 파이프라인은 4단계(parser/collector/signal/explainer)가 단일 LLM 호출(explainer Haiku)만
  발생시켜 노드별 세분화 감사가 불필요. 추후 Sonnet/Opus 멀티 콜로 확장하면 노드별 감사 분리 검토 필요.
- **관련 문서**: `docs/checklist_agent_architecture.md` 섹션 7 (감사 로그)

### 3-5. 자동화 스크립트 (`scripts/*`)

- **메타데이터 동기화** (`om_sync_*.py`): 민감 테이블의 description 동기화 시에도 sample value 노출 금지
- **Airflow DAG**: `10_sync_metadata_daily` 등 메타 작업은 `nl2sql_exec`가 아닌 admin 계정 사용 허용 (쓰기 필요)
- **로그**: DAG 로그에 패스워드/토큰 출력 금지. `***`로 마스킹.
- **OM 등록 스크립트** (`om_register_data_sources.py`, `om_tag_tables.py`): 민감 자산 목록(섹션 2-1)과 동기화 유지

---

## 4. 사고 대응 (Incident Response)

### 4-1. 비밀 노출 감지 시

1. **즉시 회전(rotate)**
   - 노출된 비밀번호/키 무효화
   - 새 값 생성 후 `.env`, Airflow Variable, vault에 반영
2. **히스토리 정리**
   - `git filter-repo` 또는 `BFG Repo-Cleaner`로 과거 커밋에서 제거
   - 원격 저장소 force push (팀원 합의 필요)
3. **영향도 조사**
   - 감사 로그, DB 로그에서 이상 접근 확인
   - `pg_stat_activity`, OpenMetadata 감사 로그 확인
4. **재발 방지**
   - pre-commit hook 추가 (예: `detect-secrets`, `gitleaks`)
   - `.gitignore` 보강

### 4-2. NL2SQL 오용 감지 시

1. `nl2sql_audit_log`에서 차단 이력 확인
2. 패턴이 반복되면 allowlist/denylist 업데이트
3. 해당 사용자/에이전트 권한 재검토
4. 필요 시 `nl2sql_exec` 비밀번호 회전

### 4-3. 의심스러운 SQL 패턴

- `SELECT * FROM portfolio ...` — allowlist 위반
- `UNION SELECT ... FROM users` — 인젝션 시도
- `pg_read_file(...)` — 파일 시스템 접근 시도
- `COPY ... TO ...` — 데이터 유출 시도

위 패턴은 **Layer 1 validator**에서 차단되어야 하며, 감사 로그에 `blocked_pattern`으로 기록됩니다.

---

## 5. 보안 체크리스트

신규 기능/에이전트 배포 전 반드시 확인:

```
□ 민감 테이블(2-1 목록, portfolio_snapshot 포함)에 접근하지 않는가?
□ 민감 컬럼 패턴(2-2 목록)을 필터링하는가?
□ LLM 프롬프트에 raw value가 들어가지 않는가?
□ DB 커넥션이 nl2sql_exec 또는 적절한 최소 권한 role인가?
□ 감사 로그 기록 경로가 설정되어 있는가?
  - NL2SQL → nl2sql_audit_log + agent_audit_log
  - 리포트/모니터링/LangGraph → agent_audit_log
□ OM 프로파일러 config가 민감 테이블 excludes에 포함했는가?
□ OM 프로파일러 includeColumnSample: false 확인했는가?
□ 신규 테이블을 Wren/에이전트에 노출하면 NL2SQL_ALLOWLIST + nl2sql_role.sql GRANT도 갱신했는가?
□ .env/.env.example에 실제 비밀값이 없는가?
□ git diff에서 비밀값이 노출되지 않는가?
□ 로그/알림 본문에 민감 정보가 마스킹되는가?
□ 사고 시 회전 절차가 문서화되어 있는가?
```

---

## 6. 승인 이력 & 예외

본 문서의 원칙에 대한 예외는 **문서화된 승인** 후에만 허용됩니다.

| 날짜 | 항목 | 승인자 | 근거 | 만료 |
|------|------|-------|------|------|
| — | — | — | — | — |

### 6-1. 열린 보안 이슈 (Follow-up TODO)

| 날짜 | 항목 | 심각도 | 조치 필요 |
|------|------|-------|----------|
| 2026-04-05 | `PG_PASSWORD=pw1234`가 `.env`에서 그대로 사용 중 — git 히스토리에 이미 노출된 값 | High | **비밀번호 회전 필요**: PostgreSQL `user`, `nl2sql_exec` 양쪽 모두. 회전 후 `.env`, Airflow Variable, Docker 컨테이너 재시작 |
| 2026-04-05 | DART API 키가 `collect_kospi_financials.py`, `test_dart_collect.py`에 하드코딩되어 있었음 (이번 PR에서 제거) | High | **DART API 키 회전 필요**: https://opendart.fss.or.kr 에서 재발급 |
| 2026-04-05 | `gdelt_test/` 하위 스크립트 다수에 `pw1234` 하드코딩 남음 | Medium | 고립된 테스트 디렉토리. 삭제 또는 별도 PR에서 일괄 정리 |
| ~~2026-04-05~~ | ~~BIP-Agents 레포 내부 LangGraph 노드별 감사 hook 미구현~~ | ~~Medium~~ | **✅ 해결 (2026-04-05 저녁)**: FastAPI 응답 `AuditMeta` → Airflow에서 `record_agent_audit()` 호출. `market_monitor_checklist`, `market_monitor_preopen` 감사 경로 연결됨 |
| 2026-04-05 | `.env.example`에 플레이스홀더가 아닌 실제값 (`pw1234`, Fernet 키) 히스토리 잔존 | Medium | `git filter-repo` 또는 BFG로 히스토리 정리 + 원격 force push (팀 합의 필요) |

---

## 7. 참고 자료

- `docs/metadata_governance.md` — 메타데이터/리니지/용어 관리 거버넌스 (이 문서와 함께 읽을 것)
- `docs/nl2sql_design.md` — NL2SQL 설계, 아키텍처, 보안 요구사항
- `postgres/nl2sql_role.sql` — 최소 권한 DB role 정의
- `postgres/nl2sql_audit.sql` — NL2SQL SQL 생성/실행 감사 로그
- `postgres/agent_audit.sql` — 모든 AI 에이전트 LLM 호출 감사 로그 (통합)
- `openmetadata/connectors/bip_profiler.yaml` — OM 프로파일러 정책 (민감 테이블 제외)
- `docs/data_architecture_review.md` — 전체 아키텍처 및 거버넌스 결정 로그
- `docs/wrenai_technical_guide.md` — Wren AI 구성 및 동기화 흐름

---

*이 문서는 BIP-Pipeline에서 동작하는 모든 에이전트·자동화가 반드시 참조해야 하는 보안 기준선입니다.*
*원칙에 변경이 필요한 경우, PR을 통해 리뷰 후 본 문서를 먼저 갱신한 다음 구현을 진행하세요.*
