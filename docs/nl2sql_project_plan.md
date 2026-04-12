# NL2SQL 프로젝트 설계 및 계획

> **변경 이력:**
> - 2026-04-05: 보안 관점 보강 (Codex adversarial review 대응)
>   - Phase 1: 스키마 스캐너가 raw sample_values를 LLM에 전달하지 않도록 변경 (SENSITIVE_DENYLIST + type_summary)
>   - Phase 3: 쿼리 검증에 4-layer 방어 구조 추가 (allowlist + DB role + curated view + 감사 로그)
>   - 자세한 내용: 섹션 "🔒 보안 원칙" 및 3.4 하위 섹션 참조

## 개요

자연어 질문을 SQL로 변환하여 주식 데이터를 동적으로 조회하는 시스템 구축

## 🔒 보안 원칙 (선제 요구사항)

NL2SQL 시스템 구현 시 **반드시 만족해야 하는 보안 불변 조건**:

1. **LLM은 raw 데이터 값을 절대 보지 않는다.**
   - 스키마 스캐너가 수집하는 sample_values는 LLM 입력 경로에 올리지 않는다.
   - 대신 type_summary (포맷/길이/범위/distinct_count 등 구조적 요약)만 전달한다.
   - 민감 테이블(`portfolio`, `users` 등)은 LLM 파이프라인 자체에서 제외한다.

2. **NL2SQL 실행은 read-only 전용 DB 역할(`nl2sql_reader`)로만 수행한다.**
   - 애플리케이션 DB의 비밀 테이블에는 `GRANT` 자체가 없어야 한다.
   - Airflow 일반 커넥션(`bip_postgres`)을 NL2SQL 실행에 재사용 금지.

3. **4-layer 방어** — 한 레이어가 뚫려도 다음 레이어에서 차단되어야 한다.
   - Layer 1: 문법/키워드 차단 (SELECT-only, DDL/DML 금지)
   - Layer 2: Allowlist 검증 (허용 테이블/컬럼만 참조 가능, sqlglot AST 파싱)
   - Layer 3: DB role 격리 (민감 테이블에 GRANT 없음)
   - Layer 4: Curated 뷰 전용 (base 테이블 직접 접근 금지, 향후 작업)

4. **감사 로그 필수.** 모든 NL2SQL 실행은 `nl2sql_audit_log`에 기록 (질문/SQL/검증 결과/차단 사유).

5. **공격 표면 최소화.**
   - `pg_read_file`, `pg_ls_dir`, `pg_stat_activity`, `COPY`, `INTO OUTFILE` 등 파일/함수/통계 뷰 차단.
   - UNION, 주석 인젝션 등 위험 패턴 차단.

### 목표 아키텍처

```
[자연어 질문]
      │
      ▼
┌─────────────────────────────────────────────────┐
│              NL2SQL 에이전트                      │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │ OpenMetadata │    │      Graph DB        │   │
│  │  (스키마)     │    │  (비즈니스 맥락)      │   │
│  └──────┬───────┘    └──────────┬───────────┘   │
│         │                       │               │
│         └───────────┬───────────┘               │
│                     ▼                           │
│            [SQL 쿼리 생성 LLM]                   │
│                     │                           │
│                     ▼                           │
│            [쿼리 검증 & 실행]                    │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
               [쿼리 결과 반환]
```

---

## Phase 1: 메타데이터 정비 (1주)

### 1.1 OpenMetadata 설치 및 설정

**Docker Compose 추가:**
```yaml
# docker-compose.yml에 추가
openmetadata:
  image: openmetadata/server:latest
  container_name: openmetadata
  ports:
    - "8585:8585"
  environment:
    - OPENMETADATA_CLUSTER_NAME=bip-cluster
  depends_on:
    - bip-postgres
  networks:
    - stock-network

openmetadata-ingestion:
  image: openmetadata/ingestion:latest
  container_name: openmetadata-ingestion
  depends_on:
    - openmetadata
  networks:
    - stock-network
```

**PostgreSQL 연결 설정:**
- Host: bip-postgres
- Port: 5432
- Database: stockdb
- Schema: public

### 1.2 메타데이터 에이전트 구현

자동으로 DB 스키마를 분석하고 메타데이터를 생성/등록하는 에이전트

**에이전트 구조:**
```
┌─────────────────────────────────────────────────────┐
│            메타데이터 정비 에이전트                    │
│                                                     │
│  [스키마 스캐너]                                     │
│      │ - 테이블/컬럼 목록 추출                        │
│      │ - 데이터 타입, 제약조건 수집                   │
│      │ - 샘플 데이터 조회                            │
│      ▼                                              │
│  [설명 생성 LLM]                                     │
│      │ - 컬럼명에서 의미 추론                         │
│      │ - 샘플 데이터로 패턴 분석                      │
│      │ - 비즈니스 용어 매핑 제안                      │
│      ▼                                              │
│  [OpenMetadata 등록기]                              │
│      │ - API로 메타데이터 등록                        │
│      │ - 기존 메타데이터와 병합                       │
│      ▼                                              │
│  [검증 & 리뷰]                                       │
│        - 사람이 검토/수정할 수 있는 리포트 생성        │
└─────────────────────────────────────────────────────┘
```

**구현 파일:**
```
airflow/dags/metadata/
├── __init__.py
├── metadata_agent.py         # 메인 에이전트
├── schema_scanner.py         # DB 스키마 스캔 (type_summary만 수집)
├── sensitive_config.py       # 🔒 SENSITIVE_DENYLIST, is_sensitive()
├── description_generator.py  # LLM으로 설명 생성 (민감 컬럼 우회)
├── openmetadata_client.py    # OpenMetadata API 클라이언트
└── dag_metadata_sync.py      # Airflow DAG (주기적 동기화)
```

**🔒 보안 원칙 (2026-04-05 추가):**
> **LLM은 원본 데이터(raw value)를 절대 보지 않는다.**
> - 민감 테이블/컬럼(`SENSITIVE_DENYLIST`)은 LLM 파이프라인에서 전면 차단
> - 일반 컬럼도 raw sample_values 대신 타입 요약(type summary) / 마스킹 예시만 전달
> - 민감 스키마 프로파일링은 LLM을 거치지 않는 로컬 전용 경로로 수행

**민감정보 denylist (필수):**
```python
# airflow/dags/metadata/sensitive_config.py
SENSITIVE_DENYLIST = {
    # 테이블 전체 차단
    "tables": {
        "portfolio",              # KIS 인증키, 계좌번호 포함
        "users",                  # 사용자 계정
        "user_watchlist",
        "holding",                # 보유 현황
        "transaction",            # 거래 내역
        "cash_transaction",
    },
    # 특정 컬럼 차단 (테이블별)
    "columns": {
        "portfolio": {"kis_app_key", "kis_app_secret", "account_number", "account_password"},
        # 향후 다른 민감 컬럼 추가
    },
    # 패턴 기반 차단 (컬럼명 정규식)
    "column_patterns": [
        r".*_secret$", r".*_key$", r".*_token$", r".*_password$",
        r"^email$", r"^phone$", r"^ssn$", r"^account_number$",
    ],
}

def is_sensitive(table: str, column: str = None) -> bool:
    """민감 테이블/컬럼 여부 판정"""
    if table in SENSITIVE_DENYLIST["tables"]:
        return True
    if column and column in SENSITIVE_DENYLIST["columns"].get(table, set()):
        return True
    if column:
        import re
        for pat in SENSITIVE_DENYLIST["column_patterns"]:
            if re.match(pat, column, re.IGNORECASE):
                return True
    return False
```

**schema_scanner.py 핵심 로직 (보안 강화):**
```python
def scan_database_schema(engine) -> Dict[str, Any]:
    """
    DB 스키마 전체 스캔 — 민감정보 필터 적용

    민감 테이블: 메타데이터만 수집, sample_values 수집 금지
    일반 테이블: 타입 요약(type summary)만 수집, raw value 수집 금지

    Returns:
        {
            "tables": [
                {
                    "name": "stock_price_1d",
                    "sensitive": False,
                    "columns": [
                        {
                            "name": "ticker",
                            "type": "VARCHAR(20)",
                            "nullable": False,
                            # ⚠️ sample_values 대신 type_summary 사용
                            "type_summary": {
                                "format": "KR_TICKER",   # 005930.KS 형식
                                "length_range": [7, 8],
                                "distinct_count": 2500,
                                "null_ratio": 0.0,
                            },
                        },
                        ...
                    ],
                    "row_count": 1000000,
                },
                # 민감 테이블은 메타데이터만
                {
                    "name": "portfolio",
                    "sensitive": True,
                    "columns": [{"name": "kis_app_key", "type": "VARCHAR(100)"}],
                    "type_summary": None,  # 프로파일링 안 함
                },
            ]
        }
    """
    pass

def collect_type_summary(engine, table: str, column: str) -> Dict:
    """
    raw value 대신 구조적 요약만 추출.

    허용:
    - 길이 범위 (min/max length)
    - 숫자 범위 (min/max for numeric, 단 민감 컬럼은 제외)
    - 포맷 식별 (날짜, 티커, UUID 등 정규식 매칭)
    - distinct_count, null_ratio

    금지:
    - 실제 문자열/숫자 값 수집
    - LIMIT 10 형태 샘플 쿼리
    """
    if is_sensitive(table, column):
        return {"skipped": "sensitive"}
    # ... pattern detection, ranges
    pass
```

**description_generator.py 핵심 로직 (보안 강화):**
```python
# ⚠️ sample_values 필드 제거, type_summary만 사용
DESCRIPTION_PROMPT = """
다음 데이터베이스 컬럼의 구조 정보를 분석하여 설명을 생성하세요.
(실제 데이터 값은 전달되지 않으며, 타입 요약만 제공됩니다.)

테이블: {table_name}
컬럼: {column_name}
데이터 타입: {data_type}
포맷 힌트: {format_hint}           # 예: "KR_TICKER (005930.KS 형식)"
값 범위: {value_range}             # 예: "길이 7-8자" 또는 "숫자 범위 0~1e15"
Null 비율: {null_ratio}
고유값 수: {distinct_count}

다음 형식으로 응답하세요:
1. 컬럼 설명 (한국어, 1-2문장)
2. 비즈니스 용어 (이 컬럼을 부르는 다른 이름들)
3. 데이터 패턴 설명
"""

def generate_column_description(column_info: Dict) -> Dict:
    """
    LLM으로 컬럼 설명 자동 생성 — raw value 전달 금지.

    민감 테이블/컬럼은 LLM 호출 없이 수동 작성 또는 rule-based 생성.
    """
    if column_info.get("sensitive"):
        # LLM 파이프라인 우회 — 수동 작성 or rule-based
        return generate_sensitive_description_locally(column_info)
    # type_summary만 사용, sample_values 주입 금지
    pass

def generate_sensitive_description_locally(column_info: Dict) -> Dict:
    """민감 컬럼은 로컬에서만 설명 생성 (LLM 호출 없음)"""
    pass
```

### 1.3 현재 테이블 구조 (정비 대상)

| 테이블 | 설명 | 주요 컬럼 |
|--------|------|----------|
| `stock_info` | 종목 기본정보 | ticker, stock_name, market_type, industry_name, market_value |
| `stock_price_1d` | 일봉 시세 | ticker, timestamp, open, high, low, close, volume |
| `financial_statements` | 재무제표 | ticker, fiscal_year, account_name, amount |
| `investor_flow` | 투자자 동향 | date, foreign_amount, institution_amount, individual_amount |
| `macro_indicators` | 매크로 지표 | indicator_type, indicator_date, value |
| `semiconductor_prices` | 반도체 가격 | product_type, price_date, price |
| `consensus_estimates` | 컨센서스 | ticker, estimate_date, eps, target_price |
| `company_dart_info` | DART 기업정보 | ticker, corp_code, corp_name |

### 1.4 일정

| 일자 | 작업 |
|------|------|
| Day 1 | OpenMetadata Docker 설정, PostgreSQL 연결 |
| Day 2 | schema_scanner.py 구현 |
| Day 3 | description_generator.py 구현 (LLM 연동) |
| Day 4 | openmetadata_client.py 구현 (API 연동) |
| Day 5 | metadata_agent.py 통합, 테스트 |
| Day 6-7 | 전체 테이블 메타데이터 정비, 리뷰 |

---

## Phase 2: Graph DB 구축 (1주)

### 2.1 Neo4j 설치

**Docker Compose 추가:**
```yaml
neo4j:
  image: neo4j:5.15-community
  container_name: neo4j
  ports:
    - "7474:7474"  # HTTP
    - "7687:7687"  # Bolt
  environment:
    - NEO4J_AUTH=neo4j/bip-password
    - NEO4J_PLUGINS=["apoc"]
  volumes:
    - neo4j_data:/data
  networks:
    - stock-network
```

### 2.2 Knowledge Graph 스키마 설계

**노드 타입:**
```cypher
// 비즈니스 개념
(:Concept {name, description, type})
  - type: "sector", "theme", "indicator", "event"

// 테이블/컬럼 (OpenMetadata 연동)
(:Table {name, description})
(:Column {name, description, data_type})

// 종목
(:Stock {ticker, name, market})

// 비즈니스 용어
(:Term {name, synonyms[]})
```

**관계 타입:**
```cypher
// 개념 관계
(:Concept)-[:RELATED_TO]->(:Concept)
(:Concept)-[:IS_A]->(:Concept)         // 상위 개념
(:Concept)-[:HAS_MEMBER]->(:Stock)     // 섹터 → 종목

// 스키마 관계
(:Table)-[:HAS_COLUMN]->(:Column)
(:Column)-[:MAPS_TO]->(:Term)          // 컬럼 ↔ 비즈니스용어

// 종목 관계
(:Stock)-[:BELONGS_TO]->(:Concept)     // 종목 → 섹터/테마
(:Stock)-[:COMPETITOR]->(:Stock)       // 경쟁사
(:Stock)-[:SUPPLIER]->(:Stock)         // 공급망
```

**예시 데이터:**
```cypher
// 섹터/테마 구조
CREATE (semi:Concept {name: "반도체", type: "sector"})
CREATE (hbm:Concept {name: "HBM", type: "theme"})
CREATE (ai:Concept {name: "AI", type: "theme"})

CREATE (hbm)-[:IS_A]->(semi)
CREATE (hbm)-[:RELATED_TO]->(ai)

// 종목 연결
CREATE (sk:Stock {ticker: "000660.KS", name: "SK하이닉스", market: "KOSPI"})
CREATE (samsung:Stock {ticker: "005930.KS", name: "삼성전자", market: "KOSPI"})

CREATE (sk)-[:BELONGS_TO]->(semi)
CREATE (sk)-[:BELONGS_TO]->(hbm)
CREATE (samsung)-[:BELONGS_TO]->(semi)
CREATE (samsung)-[:COMPETITOR]->(sk)

// 비즈니스 용어 매핑
CREATE (t:Term {name: "시가총액", synonyms: ["시총", "market cap", "market_value"]})
CREATE (c:Column {name: "market_value", table: "stock_info"})
CREATE (c)-[:MAPS_TO]->(t)
```

### 2.3 Graph 구축 에이전트

**역할:**
1. 종목-섹터-테마 관계 자동 구축 (stock_info 기반)
2. 비즈니스 용어 사전 구축
3. 뉴스에서 새로운 관계 추출 (선택)

**구현 파일:**
```
airflow/dags/knowledge_graph/
├── __init__.py
├── graph_builder_agent.py   # 메인 에이전트
├── neo4j_client.py          # Neo4j 연결
├── stock_relation_builder.py # 종목 관계 구축
├── term_mapper.py           # 비즈니스 용어 매핑
└── dag_graph_sync.py        # Airflow DAG
```

### 2.4 일정

| 일자 | 작업 |
|------|------|
| Day 1 | Neo4j Docker 설정, 기본 스키마 생성 |
| Day 2 | neo4j_client.py 구현 |
| Day 3 | stock_relation_builder.py - 종목/섹터 관계 |
| Day 4 | term_mapper.py - 비즈니스 용어 매핑 |
| Day 5 | graph_builder_agent.py 통합 |
| Day 6-7 | 데이터 구축, 검증 |

---

## Phase 3: NL2SQL 엔진 구현 (1-2주)

### 3.1 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    NL2SQL 에이전트                       │
│                                                         │
│  [질문 분석기]                                           │
│      │ - 질문에서 엔티티 추출 (종목명, 지표명, 기간 등)    │
│      │ - 의도 파악 (조회, 비교, 집계 등)                  │
│      ▼                                                  │
│  [컨텍스트 수집기]                                       │
│      │ - OpenMetadata에서 관련 테이블/컬럼 조회           │
│      │ - Graph DB에서 관련 개념/종목 조회                 │
│      ▼                                                  │
│  [SQL 생성기]                                           │
│      │ - LLM으로 SQL 쿼리 생성                           │
│      │ - Few-shot 예시 포함                              │
│      ▼                                                  │
│  [쿼리 검증기]                                           │
│      │ - SQL 문법 검증                                   │
│      │ - SELECT만 허용 (DML 차단)                        │
│      │ - 위험 패턴 탐지                                  │
│      │ - 🔒 allowlist 검증 (테이블/컬럼)                  │
│      │ - 🔒 민감 스키마 차단 (portfolio/users 등)         │
│      ▼                                                  │
│  [실행기]                                               │
│        - 🔒 read-only DB role로만 실행                   │
│        - 🔒 curated 뷰 전용 접속                         │
│        - 쿼리 실행 및 결과 반환                          │
│        - 타임아웃 설정                                   │
└─────────────────────────────────────────────────────────┘
```

### 3.2 구현 파일

```
airflow/dags/nl2sql/
├── __init__.py
├── nl2sql_agent.py          # 메인 에이전트 (LangGraph)
├── question_analyzer.py     # 질문 분석
├── context_collector.py     # 메타데이터 + Graph 조회 (🔒 민감 스키마 제외)
├── sql_generator.py         # SQL 생성 (LLM)
├── query_validator.py       # 쿼리 검증 (🔒 4-layer defense)
├── validator_config.py      # 🔒 NL2SQL_ALLOWLIST, NL2SQL_DENYLIST
├── query_executor.py        # 쿼리 실행 (🔒 nl2sql_reader 전용 커넥션)
├── audit_logger.py          # 🔒 nl2sql_audit_log 기록
└── few_shot_examples.py     # Few-shot 예시
```

**관련 DB 리소스:**
```
postgres/
├── nl2sql_role.sql          # 🔒 nl2sql_reader role + GRANT 정의
└── nl2sql_audit.sql         # 🔒 nl2sql_audit_log 테이블 DDL
```

### 3.3 Few-shot 예시

```python
FEW_SHOT_EXAMPLES = [
    {
        "question": "삼성전자 최근 5일 주가 보여줘",
        "sql": """
            SELECT timestamp::date as date, close, change_pct
            FROM stock_price_1d
            WHERE ticker = '005930.KS'
            ORDER BY timestamp DESC
            LIMIT 5
        """
    },
    {
        "question": "반도체 섹터 시총 상위 10개 종목",
        "sql": """
            SELECT stock_name, market_value,
                   ROUND((market_value / 1e12)::numeric, 2) as 시총_조
            FROM stock_info
            WHERE industry_name LIKE '%반도체%'
              AND market_type = 'KOSPI'
            ORDER BY market_value DESC
            LIMIT 10
        """
    },
    {
        "question": "이번 주 외국인 순매수 상위 종목",
        "sql": """
            SELECT s.stock_name, SUM(i.foreign_amount) as 외국인순매수
            FROM investor_flow i
            JOIN stock_info s ON i.ticker = s.ticker
            WHERE i.date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY s.stock_name
            ORDER BY 외국인순매수 DESC
            LIMIT 10
        """
    },
]
```

### 3.4 쿼리 검증 규칙

**🔒 방어 계층 (Defense in Depth, 2026-04-05 보강):**

NL2SQL 실행은 **4단계 방어**를 모두 통과해야 합니다:

```
Layer 1: 문법/키워드 차단   → SQL 파서 기반 SELECT-only 강제
Layer 2: Allowlist 검증     → 허용된 테이블/컬럼만 사용 가능
Layer 3: DB role 격리       → read-only 역할 + 민감 스키마 GRANT 없음
Layer 4: Curated 뷰 전용    → base 테이블 직접 접근 금지
```

```python
# airflow/dags/nl2sql/validator_config.py

VALIDATION_RULES = {
    # Layer 1: 문법/키워드
    "allowed_statements": ["SELECT"],
    "blocked_keywords": [
        "DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
        "GRANT", "REVOKE", "CREATE", "EXEC", "EXECUTE",
        "COPY", "CALL", "MERGE",
    ],
    "dangerous_patterns": [
        r";\s*--",            # SQL 주석 인젝션
        r"UNION\s+SELECT",    # UNION 인젝션
        r"INTO\s+OUTFILE",    # 파일 쓰기
        r"pg_read_file",      # PostgreSQL 파일 함수
        r"pg_ls_dir",
        r"pg_stat_activity",  # 다른 세션 조회
    ],

    # 제한
    "max_rows": 1000,
    "timeout_seconds": 30,
}

# Layer 2: Allowlist — NL2SQL이 접근 가능한 엔티티만 명시
NL2SQL_ALLOWLIST = {
    # Gold layer (pre-joined 와이드 테이블) — 주 대상
    "public.analytics_stock_daily",
    "public.analytics_macro_daily",
    "public.analytics_valuation",

    # Raw (읽기 전용 허용)
    "public.stock_info",
    "public.stock_price_1d",
    "public.stock_indicators",
    "public.financial_statements",
    "public.consensus_estimates",
    "public.macro_indicators",
    "public.news",

    # 향후 추가될 curated 뷰
    # "public.v_nl2sql_stock_summary",
    # "public.v_nl2sql_sector_rollup",
}

# Layer 2-b: 명시적 차단 (allowlist로 처리해도 한 번 더 확인)
NL2SQL_DENYLIST = {
    "public.portfolio",          # KIS 인증키, 계좌번호
    "public.users",
    "public.user_watchlist",
    "public.holding",
    "public.transaction",
    "public.cash_transaction",
    "public.monitor_alerts",     # 운영 알림 이력
}


def validate_sql_entities(sql: str) -> tuple[bool, str]:
    """
    SQL에서 참조하는 모든 테이블/컬럼을 파싱하여 allowlist 검증.
    sqlglot 또는 sqlparse로 AST 파싱.

    Returns:
        (is_safe, reason)
    """
    import sqlglot
    parsed = sqlglot.parse_one(sql, dialect="postgres")

    # 모든 테이블 참조 추출
    referenced_tables = set()
    for table in parsed.find_all(sqlglot.exp.Table):
        full_name = f"{table.db or 'public'}.{table.name}"
        referenced_tables.add(full_name)

    # Allowlist 검증
    not_allowed = referenced_tables - NL2SQL_ALLOWLIST
    if not_allowed:
        return False, f"Allowlist 외 테이블 참조: {not_allowed}"

    # Denylist 재확인 (방어 2중화)
    blocked = referenced_tables & NL2SQL_DENYLIST
    if blocked:
        return False, f"민감 테이블 참조 차단: {blocked}"

    return True, "ok"
```

### 3.4.1 DB Role 격리 (Layer 3)

NL2SQL 전용 PostgreSQL role을 생성하여, 애플리케이션 DB의 비밀 테이블에 **GRANT 자체가 없도록** 구성합니다.

```sql
-- postgres/nl2sql_role.sql (신규)

-- NL2SQL 전용 읽기 전용 역할
CREATE ROLE nl2sql_reader NOLOGIN;

-- Gold/Raw 허용 테이블에만 SELECT 권한
GRANT USAGE ON SCHEMA public TO nl2sql_reader;

GRANT SELECT ON
    public.analytics_stock_daily,
    public.analytics_macro_daily,
    public.analytics_valuation,
    public.stock_info,
    public.stock_price_1d,
    public.stock_indicators,
    public.financial_statements,
    public.consensus_estimates,
    public.macro_indicators,
    public.news
TO nl2sql_reader;

-- 민감 테이블은 GRANT 없음 (portfolio, users, holding 등)
-- → SQL이 allowlist를 우회해도 DB 레벨에서 차단됨

-- 실제 로그인 유저 생성 (Airflow에서 이 계정으로만 NL2SQL 실행)
CREATE USER nl2sql_exec WITH PASSWORD '<STRONG_PASSWORD>' IN ROLE nl2sql_reader;

-- 통계 뷰 차단
REVOKE ALL ON pg_catalog.pg_stat_activity FROM nl2sql_reader;

-- 함수 실행 권한 제한
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM nl2sql_reader;
```

**Airflow 연결 구성:**
```python
# NL2SQL 실행기는 일반 Airflow DB 커넥션이 아닌 nl2sql_exec 전용 커넥션 사용
NL2SQL_PG_CONN_ID = "bip_postgres_nl2sql"   # nl2sql_exec 계정
# 기본 bip_postgres 커넥션은 재사용 금지
```

### 3.4.2 Curated 뷰 (Layer 4, 향후 작업)

base 테이블 직접 접근 대신 뷰를 거치도록 설계. 뷰는 민감 컬럼을 미리 제거/마스킹:

```sql
-- 향후 추가할 뷰 예시
CREATE VIEW v_nl2sql_stock_summary AS
SELECT ticker, stock_name, market_type, industry_name,
       market_value, close, trade_date
FROM public.analytics_stock_daily
WHERE trade_date >= CURRENT_DATE - INTERVAL '2 years';
-- 민감 컬럼, 과거 deep history, 내부 flag 제외
```

### 3.4.3 감사 로그

모든 NL2SQL 실행은 감사 테이블에 기록:

```sql
CREATE TABLE nl2sql_audit_log (
    id BIGSERIAL PRIMARY KEY,
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    user_id VARCHAR(100),
    original_question TEXT NOT NULL,
    generated_sql TEXT NOT NULL,
    validation_result VARCHAR(50),        -- "pass", "blocked_allowlist", ...
    blocked_reason TEXT,
    row_count INT,
    execution_ms INT
);
```

### 3.5 LangGraph 워크플로우

```python
from langgraph.graph import StateGraph, END

class NL2SQLState(TypedDict):
    question: str
    entities: List[str]
    intent: str
    context: Dict
    sql: str
    validation_result: Dict
    result: Any
    error: str

def create_nl2sql_graph():
    workflow = StateGraph(NL2SQLState)

    # 노드 추가
    workflow.add_node("analyze_question", analyze_question)
    workflow.add_node("collect_context", collect_context)
    workflow.add_node("generate_sql", generate_sql)
    workflow.add_node("validate_sql", validate_sql)
    workflow.add_node("execute_sql", execute_sql)
    workflow.add_node("handle_error", handle_error)

    # 엣지 연결
    workflow.add_edge("analyze_question", "collect_context")
    workflow.add_edge("collect_context", "generate_sql")
    workflow.add_edge("generate_sql", "validate_sql")

    # 조건부 엣지
    workflow.add_conditional_edges(
        "validate_sql",
        lambda state: "execute" if state["validation_result"]["valid"] else "regenerate",
        {
            "execute": "execute_sql",
            "regenerate": "generate_sql"  # 최대 3회 재시도
        }
    )

    workflow.add_edge("execute_sql", END)

    workflow.set_entry_point("analyze_question")

    return workflow.compile()
```

### 3.6 일정

| 일자 | 작업 |
|------|------|
| Day 1-2 | question_analyzer.py, context_collector.py |
| Day 3-4 | sql_generator.py, few_shot_examples.py |
| Day 5 | query_validator.py, query_executor.py |
| Day 6-7 | LangGraph 워크플로우 통합 |
| Day 8-10 | 테스트, 디버깅, Few-shot 개선 |

---

## Phase 4: 통합 및 모닝 리포트 연동 (1주)

### 4.1 모닝 리포트에 NL2SQL 적용

**인사이트 에이전트가 동적 질문:**
```
[인사이트 에이전트]
  "오늘 반도체 섹터 외국인 수급이 특이한데,
   최근 1주일 추이를 확인해보자"
      │
      ▼
[NL2SQL 에이전트]
  → SQL 생성 및 실행
      │
      ▼
[결과를 인사이트 분석에 활용]
```

### 4.2 MCP Tool 구현

```python
# mcp_tools/nl2sql_tool.py
class NL2SQLTool:
    """
    MCP Tool로 NL2SQL 노출
    다른 에이전트에서 호출 가능
    """

    name = "query_stock_data"
    description = "자연어로 주식 데이터 조회. 예: '삼성전자 최근 주가', '반도체 섹터 시총 순위'"

    def execute(self, question: str) -> Dict:
        agent = NL2SQLAgent()
        return agent.run(question)
```

---

## 전체 일정 요약

| Phase | 기간 | 주요 산출물 |
|-------|------|------------|
| Phase 1 | Week 1 | OpenMetadata 구축, 메타데이터 에이전트 |
| Phase 2 | Week 2 | Neo4j Knowledge Graph, Graph 구축 에이전트 |
| Phase 3 | Week 3-4 | NL2SQL 엔진 (LangGraph) |
| Phase 4 | Week 5 | 모닝 리포트 연동, MCP Tool |

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| 메타데이터 | OpenMetadata |
| Knowledge Graph | Neo4j |
| 워크플로우 | LangGraph |
| LLM | GPT-5.4 / Claude Sonnet |
| 오케스트레이션 | Airflow |
| DB | PostgreSQL |

---

## 리스크 및 대응

| 리스크 | 대응 방안 |
|--------|----------|
| SQL 생성 정확도 낮음 | Few-shot 예시 확충, 재시도 로직 |
| 복잡한 조인 실패 | 자주 쓰는 조인은 View로 미리 생성 |
| 쿼리 성능 문제 | 인덱스 최적화, 타임아웃 설정 |
| 보안 (SQL 인젝션) | 검증 레이어 강화, SELECT만 허용 |

---

## 아키텍처 포지셔닝 (2026-04-08 확정)

### 컴포넌트 역할 정의

| 컴포넌트 | 역할 | 분류 |
|---------|------|------|
| **Gold Tables + Curated Views** | 비즈니스 로직 SSOT (PER 계산, boolean 플래그, 단위 변환) | canonical semantic layer |
| **Wren AI MDL** | LLM이 스키마를 이해하도록 돕는 주석 (description, relationship) | NL2SQL semantic shell |
| **Wren AI** | 스키마 RAG + LLM + SQL 검증 + 관리 UI | semantic-aware Text-to-SQL engine |
| **LangGraph** (Phase 3) | 멀티스텝 쿼리, 비정형 데이터, 온톨로지 통합 | orchestration layer |

> Wren AI는 "시맨틱 레이어"가 아니라 "NL2SQL 엔진"이다.
> 진짜 시맨틱 레이어는 PostgreSQL Gold Tables + Curated Views에 위치한다.

### NL2SQL 엔진 선택: Wren AI

Wren AI, Vanna AI, Defog AI, DataHerald, LangChain SQL Agent 비교 후 선택.
- **선택 근거:** 관리 UI, SQL 자동 보정(3회), Intent Classification, Qdrant RAG 내장
- **한계:** 1질문=1SQL, 비정형 불가, 프롬프트 커스터마이징 불가, OpenAI 편향
- **대응:** `NL2SQLEngine` 추상화 + Phase 3 LangGraph로 한계 보완
- 상세: `docs/wrenai_technical_guide.md` 12-10, 12-11절 참조

---

## Phase 1 진행 현황 (2026-04-12 최종)

### Phase 1 완료 — 최종 상태

| 항목 | 상태 | 수량/결과 |
|------|:----:|---------|
| Gold 테이블 | ✅ | 3종 (analytics_stock_daily, analytics_macro_daily, analytics_valuation) |
| Curated View | ✅ | 4종 (v_latest_valuation, v_valuation_signals, v_technical_signals, v_flow_signals) |
| Wren AI 모델 | ✅ | 9개, **전체 309개 컬럼** (DB와 100% 일치) |
| Relationship | ✅ | 6개 (View → stock_info 4개 복구 포함) |
| SQL Pairs | ✅ | **70개** (43 → +27개 6카테고리) |
| Instructions | ✅ | 4개 (계산식/종목검색/data_type/한글필수) |
| LLM 모델 | ✅ | GPT-4.1-mini (7개 모델 비교 후 선정) |
| 보안 4-layer | ✅ | 구문 → allowlist → DB role → curated view |
| 감사 로그 | ✅ | nl2sql_audit_log + agent_audit_log |
| OM 메타데이터 | ✅ | 39 테이블, 77 용어, 전체 lineage |
| OM → Wren AI 동기화 | ✅ | 10_sync_metadata_daily DAG 실행 완료 |
| 품질 테스트 자동화 | ✅ | scripts/wren_nl2sql_phase1_test.py (Codex 작성) |

### 품질 지표

| 지표 | 1차 (04-02) | 2차 (04-03) | 3차 (04-07) | **4차 (04-12)** |
|------|:-:|:-:|:-:|:-:|
| SQL 생성률 | 75% | 85% | 100% | **100%** |
| DB 실행률 | - | - | - | **100%** |
| Boolean flag | - | - | 0% | **87%** |
| 평균 속도 | 11s | 11s | 16s | **10s** |
| SQL Pairs | 29 | 34 | 43 | **70** |

### Phase 2에서 해결할 구조적 한계

Phase 1에서 발견되었으나 NL2SQL 엔진 단독으로 해결 불가능한 문제:

| 문제 | 원인 | Phase 2 해결 방안 |
|------|------|-----------------|
| 약칭 매핑 실패 (현차→현대차) | Entity Resolution 기능 없음 | LangGraph Entity Resolver 노드 |
| 종목명 영문 번역 (셀트리온→Celltrion) | Instructions 간헐적 미준수 | Entity Resolver + 한글 강제 |
| sql_answer 환각 (데이터 있는데 "없다"고 답변) | Wren AI 답변 생성 커스터마이징 불가 | LangGraph Result Synthesizer |
| 1질문=1SQL 제약 | Wren AI 구조적 한계 | LangGraph 멀티스텝 쿼리 |

상세: `docs/wrenai_test_report.md` 5차 테스트 섹션 참조

---

## 다음 단계 (Phase 5 이후)

- **Graph RAG 도입**: 뉴스/리포트에서 지식 추출
- **자연어 응답 생성**: SQL 결과를 자연어로 설명
- **대화형 인터페이스**: 슬랙/웹 챗봇 연동
- **쿼리 캐싱**: 자주 묻는 질문 캐시
