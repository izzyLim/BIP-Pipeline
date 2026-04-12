# BIP-Pipeline 메타데이터 거버넌스

> **작성일:** 2026-04-05
> **대상:** 프로젝트의 모든 에이전트 (Claude Code, Wren AI, LangGraph, 데이터 엔지니어, 자동화 스크립트)
> **목적:** NL2SQL 기반을 유지하기 위한 메타데이터/리니지/용어 관리 표준
> **시행 원칙:** 신규 자산 생성 또는 변경 시 본 문서의 절차를 **반드시 수행한 후에 PR/배포**

---

## 1. 왜 메타데이터 거버넌스가 필요한가

NL2SQL 시스템의 정확도는 **메타데이터 품질에 1:1로 연동**됩니다. 테이블/컬럼 설명이 비어있거나 오래된 상태에서는 LLM이 추측으로 SQL을 만들어 잘못된 답을 냅니다. 스키마 변경이 메타데이터에 반영되지 않으면 리니지가 깨지고, 용어집과 코드가 어긋나면 사용자 질문이 엉뚱한 컬럼에 매핑됩니다.

실제로 2026-04-02 품질 테스트에서 **Gold 컬럼 설명 커버리지 31% → 99%로 올렸더니 A등급이 58% → 77%로 상승**한 사례가 있습니다. 이는 메타데이터 관리가 옵션이 아닌 필수 인프라라는 뜻입니다.

**메타데이터 원천(Source of Truth)은 OpenMetadata입니다.** DB COMMENT와 Wren AI 모델 설명은 OM에서 파생된 사본이며, `10_sync_metadata_daily` DAG로 자동 동기화됩니다.

```
OpenMetadata (편집/원천)
    ├→ scripts/om_sync_comments.py → DB COMMENT (PostgreSQL)
    └→ scripts/om_sync_wrenai.py   → Wren AI model description + Deploy (Qdrant)
```

> **⚠️ 보안 원천성 주의**
> OM이 메타데이터 원천이라는 것은 **설명/태그/용어 편집의 원천**을 의미합니다.
> **raw 데이터 값은 OM에 저장되면 안 됩니다.** OM 프로파일러는 `includeColumnSample: false`로
> 설정되어 있으며, 민감 테이블은 `tableFilterPattern.excludes`에 명시 제외되어 있습니다.
> (`openmetadata/connectors/bip_profiler.yaml` 및 `docs/security_governance.md` 섹션 1-6 참조)

---

## 2. 거버넌스 불변 조건

다음 조건은 모든 에이전트/작업자가 반드시 준수해야 합니다.

### 2-1. 신규 자산 생성 시 메타데이터는 "같이" 만든다

- 테이블/컬럼을 새로 만들 때 **빈 상태로 배포 금지**
- 최소 요구사항: 테이블 설명, 주요 컬럼 설명(특히 단위/포맷/비즈니스 의미), DataLayer 태그, Domain 태그
- 지표가 파생 계산인 경우 **계산식 힌트**를 description에 포함

### 2-2. 스키마 변경은 메타데이터와 리니지를 같이 갱신한다

- 컬럼 추가/삭제/타입 변경 → OM에서 해당 테이블의 설명·태그·용어 매핑 확인
- DAG 변경 → `utils/lineage.py`의 `register_table_lineage_async()` 호출 갱신
- 외부 API 추가 → `scripts/om_register_data_sources.py`에 apiEndpoint 추가 + SourceType 태그

### 2-3. 메타데이터 원천은 OpenMetadata다

- DB COMMENT, Wren AI MDL, 문서는 파생본
- 편집은 **OM API/UI에서만** 수행. 다른 곳에 직접 쓰지 말 것
- 동기화는 `10_sync_metadata_daily` DAG에 위임

### 2-4. 리니지는 누락 없이 끝까지 연결한다

- 외부 소스(apiEndpoint) → DAG(pipeline) → 테이블(table) → 소비자(consumer pipeline)
- 읽기 전용 DAG도 `target_table=None`으로 등록 (`morning_report` 패턴)
- 새 DAG 배포 시 lineage 등록 없이 머지 금지

### 2-5. 용어집(Glossary)은 컬럼과 연결되어야 한다

- 비즈니스 용어(PER, ROE, 골든크로스 등)는 OM Glossary에 정의
- 관련 컬럼에 `om_link_columns.py` 또는 OM UI로 `glossary term` 매핑
- 신규 지표/컬럼 추가 시, 이미 존재하는 용어를 우선 재사용 (중복 생성 금지)

### 2-6. Gold 테이블은 NL2SQL 소비자 관점에서 관리한다

- 컬럼 설명에 "무엇인지" + "단위" + "계산식/참조 컬럼" 포함
- raw 테이블과 네이밍이 다르면 매핑 관계 설명에 기재
- 민감 컬럼은 Gold에 포함시키지 말 것 (보안 거버넌스 참조)

### 2-7. 변경 이력은 결정 로그에 남긴다

- 스키마/메타데이터의 의미가 바뀌는 변경은 `docs/data_architecture_review.md` 결정 로그에 기록
- 단순 오타 수정이나 description 보강은 제외

---

## 3. 상황별 필수 작업 (Playbook)

### 3-1. 신규 테이블 추가 시

```
1. DDL 작성 → postgres/ 하위에 SQL 파일
2. 수집 DAG 작성 → airflow/dags/stock_loader/
3. register_table_lineage_async()로 lineage 등록 (DAG 완료 시점)

4. 🔒 민감성 판정 (security_governance.md 섹션 2-1 기준)
   - 사용자 ID / 계좌 / 자산 / 인증키 / 개인정보 포함 → 민감
   - 파생이라도 사용자별 재무/개인 상태 드러냄 → 민감
   - 애매하면 기본값 "민감"

5. 🔒 OM 프로파일러 config 검토 (block step)
   - 민감 테이블이면 openmetadata/connectors/bip_profiler.yaml의
     tableFilterPattern.excludes에 반드시 추가
   - 민감 컬럼이 있으면 columnFilterPattern.excludes에 추가
   - 이 단계 완료 전 OM ingestion 금지

6. OM Ingestion 실행 → 테이블 자동 수집
   docker exec openmetadata-ingestion metadata ingest -c /connectors/bip_postgres.yaml
7. OM에서 테이블/컬럼 설명 작성
   - 최소: 테이블 설명, 모든 주요 컬럼 설명, 단위 명시
   - 권장: 계산 힌트, 참조 컬럼 관계
8. 태그 부여
   - DataLayer: raw / derived / gold / application
   - Domain: market / financial / macro / news / portfolio / product / user
9. 용어집 매핑 (해당되는 경우)
10. 10_sync_metadata_daily DAG 수동 실행 → DB COMMENT + Wren AI 반영

11. 🔒 NL2SQL 보안 핸드오프 (테이블이 Wren/에이전트에 노출되는 경우에만)
    a. postgres/nl2sql_role.sql에 GRANT SELECT 추가
       GRANT SELECT ON public.<new_table> TO nl2sql_reader;
    b. airflow/dags/nl2sql/validator_config.py의 NL2SQL_ALLOWLIST에 추가
       (향후 NL2SQL 모듈 구현 시)
    c. 민감 테이블이면 대신 NL2SQL_DENYLIST + security_governance.md 섹션 2-1에 추가
    d. 필요한 경우 curated 뷰 (v_nl2sql_*) 생성 후 뷰만 노출
    e. psql -U nl2sql_exec로 SELECT 테스트 → 권한 동작 검증

12. Wren AI UI에서 모델로 추가할지 결정
    - Gold/Raw 비민감 테이블이면 추가
    - 민감 테이블이면 금지 (위 5, 11 단계에서 이미 차단됨)

13. PR 메시지에 메타데이터 + 보안 핸드오프 체크리스트 결과 포함
```

### 3-2. 기존 테이블에 컬럼 추가 시

```
1. 마이그레이션 SQL 작성
2. 수집 로직 업데이트
3. OM에서 해당 컬럼 설명 추가 (단위, 의미, 계산식 포함)
4. 기존 태그와 일관되게 유지
5. 용어집 매핑 (신규 지표인 경우)
6. 10_sync_metadata_daily DAG 수동 실행 (또는 다음날 자동 실행)
7. Wren AI SQL Pair에 영향 있는지 확인 (새 컬럼을 쓰는 예시 질문이 있는지)
```

### 3-3. 컬럼 삭제/타입 변경 시

```
1. 영향 분석:
   - OM lineage에서 downstream consumer 확인
   - Wren AI SQL Pairs에서 해당 컬럼 사용 여부 grep
   - 문서에서 컬럼 언급 검색
2. OM에서 컬럼 메타데이터 정리
3. 영향 받는 SQL Pairs 업데이트 또는 삭제
4. 결정 로그에 변경 사유/날짜 기록
5. 마이그레이션 실행
6. 동기화 DAG 실행
```

### 3-4. 신규 외부 데이터 소스 추가 시

```
1. `scripts/om_register_data_sources.py`에 apiService + apiEndpoint 정의 추가
2. SourceType 태그 지정 (rest-api / scraping / library)
3. 연결된 DAG 목록(pipelines) 매핑
4. 스크립트 실행 → OM에 등록 + lineage edge 생성
5. 문서 업데이트:
   - docs/data_architecture_review.md 섹션 4-3, 12
   - docs/wrenai_technical_guide.md (해당되는 경우)
```

### 3-5. 신규 DAG 배포 시

```
1. 수집/변환 로직 구현
2. lineage 등록 패턴 적용:
   - 쓰기 DAG: register_table_lineage_async("target_table", source_tables=[...])
   - 읽기 전용 DAG: register_table_lineage_async(target_table=None, source_tables=[...])
3. Airflow ingestion 실행 (OM에 새 pipeline 등록)
4. 외부 소스와 연결 필요 시 om_register_data_sources.py 업데이트
5. 민감 테이블 접근하는 경우 security_governance 체크리스트 실행
```

### 3-6. Gold 테이블(analytics_*) 변경 시

```
1. 원본 Raw 컬럼에서 파생되는지 확인
2. 계산식이 변경되면 컬럼 description에 반영 (단위 재확인)
3. 🔒 파생 민감성 재검토
   - 새 컬럼이 사용자별 재무/개인 상태를 드러내는가?
   - 그렇다면 security_governance.md 섹션 2-1 "파생 민감 데이터"에 추가
   - portfolio_snapshot과 같이 derived sensitive로 분류
4. 🔒 OM 프로파일러 excludes 재확인 (민감 컬럼 추가된 경우)
5. 영향 범위가 넓으면 결정 로그 기록
6. 테스트 쿼리 실행:
   - scripts/wrenai_test.py 또는 /tmp/wrenai_test.py
   - A등급 % 회귀 여부 확인
7. 실패가 생기면 SQL Pair 추가로 해결
8. 🔒 NL2SQL allowlist/role 재확인 (신규 컬럼이 민감이면 curated 뷰로 이동)
```

### 3-7. 용어집 신규 등록 시

```
1. 이미 등록된 용어 77개를 먼저 확인 (중복 방지)
   curl OM API /glossaryTerms
2. om_build_glossary.py에 엔트리 추가 (동의어 포함)
3. om_link_columns.py에 컬럼 매핑 추가
4. 재실행 → OM에 반영
5. 신규 용어가 Wren AI에서 어떻게 쓰일지 고려 (SQL Pair로 연결될 수 있는지)
```

---

## 4. 에이전트별 의무 사항

### 4-1. Claude Code

- **테이블/컬럼 생성 코드 작성 시** 반드시 동일 PR에서 OM 메타데이터 반영 여부를 확인
- **스키마 변경을 제안할 때** 영향 범위(lineage, SQL Pairs, 문서)를 먼저 조사 후 제시
- **결정 로그**와 **플레이북 실행 기록**은 작업 완료 시점에 같이 업데이트
- 빈 설명으로 커밋 금지, 기본 스텁이라도 작성

### 4-2. Wren AI

- 모델 등록 시 OM에서 설명을 가져오지 못하면 **빈 상태로 배포 금지**
- Deploy 전 `10_sync_metadata_daily` 동기화 완료 여부 확인
- SQL Pairs는 현재 스키마(Gold 컬럼 목록)와 일치하는지 검증
- MDL Relationship은 실제 FK와 일치하는지 확인

### 4-3. LangGraph 에이전트 (향후)

- OM API에서 실시간으로 설명/용어집을 가져와 컨텍스트 주입
- Wren AI API 호출 결과와 OM 메타데이터가 어긋나면 Wren AI 재배포 필요성 알림
- 새로운 용어가 반복 등장하면 Glossary 추가 제안

### 4-4. 자동화 스크립트 (`scripts/`)

- OM API 읽기/쓰기는 기존 스크립트(`om_*.py`) 패턴을 재사용
- 신규 동기화 스크립트 작성 시 **멱등성** 유지 (재실행해도 안전)
- 실패 시 원인 로그를 남기고, 롤백이 필요한 케이스는 명시

---

## 5. 메타데이터 품질 SLO

다음 지표는 정기 점검합니다. 미달 시 해당 영역 보강 작업이 우선순위가 됩니다.

| 지표 | 목표 | 측정 방법 | 현재 (2026-04-05) |
|------|------|---------|-----------------|
| 테이블 설명 커버리지 | 100% | `SELECT ... FROM pg_class JOIN ... WHERE description IS NOT NULL` | 100% (35/35) |
| Gold 컬럼 설명 커버리지 | 100% | Wren AI SQLite `model_column.properties` | 99%+ |
| Raw 주요 컬럼 설명 커버리지 | 95%+ | OM 컬럼 description | 99%+ (453/453) |
| DAG ↔ Table lineage 연결률 | 95%+ | `pipelines with downstream / total pipelines` | 86% (테스트 DAG 제외) |
| 외부 소스 apiEndpoint 등록률 | 100% | `om_register_data_sources.py`에 정의된 소스 수 대비 OM 등록 수 | 100% (9/9) |
| SourceType 태그 적용률 | 100% | apiEndpoint 중 SourceType 태그 있는 수 | 100% (14/14) |
| 용어집 컬럼 매핑률 | 70%+ | 주요 컬럼 대비 Glossary term 매핑 수 | 미측정 |
| NL2SQL 테스트 A등급 비율 | 80%+ | `docs/wrenai_test_report.md` | 77% |
| OM → DB COMMENT 동기화 | 일 1회 이상 | DAG `10_sync_metadata_daily` 성공률 | 매일 09:00 KST |
| OM → Wren AI 동기화 | 일 1회 이상 | DAG `10_sync_metadata_daily` 성공률 | 매일 09:00 KST |

---

## 6. 변경 관리 체크리스트

메타데이터나 스키마에 영향이 있는 작업은 PR 머지 전 아래 항목을 확인:

```
□ 영향 범위 조사: OM에서 해당 테이블/컬럼의 downstream 확인
□ Lineage 업데이트: DAG 변경 시 register_table_lineage_async() 호출 갱신
□ 설명 작성/갱신: 테이블 description, 컬럼 description (단위/계산식 포함)
□ 태그 확인: DataLayer, Domain, SourceType 유지
□ 용어집: 신규 지표면 Glossary 추가 또는 기존 용어 재사용
□ 동기화: 10_sync_metadata_daily 수동 실행 또는 확인
□ Wren AI 영향: 모델/Relationship/SQL Pair에 영향 있으면 반영 + Deploy
□ 테스트: NL2SQL 관련 변경이면 scripts/wrenai_test.py로 회귀 검증
□ 문서: data_architecture_review.md, 해당 가이드 문서, 결정 로그 업데이트

보안 핸드오프 (security_governance.md와 연계):
□ 민감성 판정: 신규/변경 자산이 사용자별 재무·개인 상태를 드러내는가?
□ OM 프로파일러: 민감 테이블이면 bip_profiler.yaml excludes에 추가 완료
□ NL2SQL allowlist: 노출 대상이면 NL2SQL_ALLOWLIST에 추가 완료
□ DB role GRANT: postgres/nl2sql_role.sql 업데이트 (SELECT 부여 또는 명시 제외)
□ Curated 뷰: 민감 컬럼 있으면 뷰로 격리, base 테이블 직접 노출 금지
□ 감사 hook: 에이전트가 LLM 호출 추가 시 agent_audit_log 기록 경로 연결
□ 전체 security_governance.md 체크리스트 (섹션 5) 실행
```

---

## 7. 관련 도구 & 파일

| 역할 | 파일/도구 |
|------|---------|
| 테이블/컬럼 설명 일괄 등록 | `scripts/om_enrich_metadata.py` |
| 용어집 구축 | `scripts/om_build_glossary.py` |
| 컬럼 ↔ 용어 매핑 | `scripts/om_link_columns.py` |
| 태그 일괄 등록 | `scripts/om_tag_tables.py` |
| 외부 API 등록 | `scripts/om_register_data_sources.py` |
| OM → DB COMMENT 동기화 | `scripts/om_sync_comments.py` |
| OM → Wren AI 동기화 | `scripts/om_sync_wrenai.py` |
| 동기화 자동화 DAG | `airflow/dags/stock_loader/dag_sync_metadata.py` |
| DAG lineage 등록 | `airflow/dags/utils/lineage.py` |
| Wren AI 품질 테스트 | 스크립트 템플릿: `docs/wrenai_test_report.md` 부록 |

---

## 8. 참고 문서

- `docs/data_architecture_review.md` — 전체 아키텍처, 이슈 트래커, 결정 로그
- `docs/security_governance.md` — 보안 불변 조건 (민감 자산 제외 규칙)
- `docs/nl2sql_design.md` — NL2SQL 설계, 아키텍처, 계획, 현황
- `docs/wrenai_technical_guide.md` — Wren AI 구성, 동기화 흐름
- `docs/wrenai_test_report.md` — 품질 테스트 프레임워크

---

## 9. 승인 이력 & 예외

본 문서의 원칙에 대한 예외는 문서화된 승인 후에만 허용됩니다.

| 날짜 | 항목 | 승인자 | 근거 | 만료 |
|------|------|-------|------|------|
| — | — | — | — | — |

---

*이 문서는 BIP-Pipeline의 메타데이터/리니지/용어를 NL2SQL 기반으로 유지하기 위한 거버넌스 기준선입니다.*
*보안 거버넌스(`docs/security_governance.md`)와 함께 읽어야 하며, 두 문서 간 충돌이 있으면 보안 거버넌스가 우선합니다.*
