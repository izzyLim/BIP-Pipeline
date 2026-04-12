# BIP-Pipeline — Agent Instructions

**모든 에이전트(Claude Code, Wren AI, LangGraph, 자동화 스크립트)는 작업 시작 전 아래 문서를 반드시 읽고 준수합니다.**

## 🔒 보안 거버넌스 (최우선)

- **`docs/security_governance.md`** — 보안 불변 조건, 민감 자산 목록, 에이전트별 요구사항, 사고 대응
- 신규 기능 추가 전 체크리스트(섹션 5) 확인 필수
- 예외가 필요하면 승인 이력(섹션 6)에 기록 후 진행

**핵심 규칙:**
1. 원본 데이터(raw value)를 LLM 프롬프트에 절대 주입 금지
2. NL2SQL 실행은 `nl2sql_exec` 계정만 사용 (민감 테이블 DB 레벨 차단)
3. `.env`, `.env.example`에 실제 비밀값 기재 금지 (플레이스홀더만)
4. 감사 경로 이중화:
   - **모든 AI 에이전트**(리포트/체크리스트/LangGraph/NL2SQL/임베딩) → `agent_audit_log`
   - **NL2SQL 상세**(생성 SQL, 검증 결과) → `nl2sql_audit_log`
5. OM 프로파일러는 `includeColumnSample: false` + 민감 테이블 excludes 유지
6. 커밋 전 `git diff`로 비밀 노출 검토

**민감 테이블** (LLM/NL2SQL 접근 금지):
- Raw: `portfolio`, `users`, `user_watchlist`, `holding`, `transaction`, `cash_transaction`
- Derived: `portfolio_snapshot` (총자산/손익 — 파생이지만 사용자 재무 상태 노출)
- 운영: `monitor_alerts`

## 📊 메타데이터 거버넌스 (필수)

- **`docs/metadata_governance.md`** — 신규/변경 시 OM 메타데이터/리니지/용어 갱신 절차
- 테이블·컬럼·DAG·외부 소스의 모든 변경은 해당 플레이북(섹션 3)을 따른 후 머지
- PR 머지 전 변경 관리 체크리스트(섹션 6) 실행

**핵심 규칙:**
1. 메타데이터 원천은 OpenMetadata. DB COMMENT/Wren AI는 파생본
2. 테이블/컬럼 생성 시 설명·태그·용어 매핑을 **같이** 작성 (빈 상태 배포 금지)
3. 스키마 변경 시 OM/lineage/SQL Pairs/문서를 같이 갱신
4. 외부 소스 추가 시 `om_register_data_sources.py`로 apiEndpoint + SourceType 등록
5. 신규 DAG는 `register_table_lineage_async()` 호출 없이 머지 금지

## 📚 프로젝트 컨텍스트

- `docs/data_architecture_review.md` — 전체 아키텍처, 이슈 트래커, 결정 로그, 용어집
- `docs/nl2sql_design.md` — NL2SQL 설계, 아키텍처, 계획, 현황 (통합 문서)
- `docs/nl2sql_concepts.md` — NL2SQL·시맨틱 레이어·온톨로지 개념/용어 레퍼런스
- `docs/wrenai_technical_guide.md` — Wren AI 구성, 동기화 흐름, Palantir/Databricks 비교
- `docs/wrenai_test_report.md` — NL2SQL 품질 테스트 리포트 (평가 프레임워크 포함)

## 🛠 주요 인프라

| 컴포넌트 | 용도 | 접근 방법 |
|----------|------|---------|
| PostgreSQL | 메인 DB (`stockdb`) | `bip-postgres` 컨테이너, port 5432 |
| Airflow | 오케스트레이션 | 43개 DAG, `10_sync_metadata_daily` 등 |
| OpenMetadata | 메타데이터 카탈로그 | `http://localhost:8585`, 39 테이블 + 77 용어집 + Lineage |
| Wren AI | NL2SQL 엔진 | `http://localhost:3000`, 5 모델 + 41 SQL Pairs |

## 📝 커밋 원칙

- `.env`, 비밀값, 토큰, 패스워드는 절대 커밋 금지
- 커밋 메시지는 변경 "이유(why)" 중심
- 민감 스키마 변경 시 `docs/security_governance.md`도 함께 업데이트

## 🔐 DB 접근 가이드

- **읽기 전용 조회**: `nl2sql_exec` 계정 사용 (민감 테이블 자동 차단)
- **DAG/ETL 쓰기**: 기존 `user` 계정 (Airflow 내부에서만)
- **관리 작업**: psql 직접 접근 (운영자만)
