# NL2SQL 프로젝트 설계 및 계획

## 개요

자연어 질문을 SQL로 변환하여 주식 데이터를 동적으로 조회하는 시스템 구축

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
├── metadata_agent.py        # 메인 에이전트
├── schema_scanner.py        # DB 스키마 스캔
├── description_generator.py # LLM으로 설명 생성
├── openmetadata_client.py   # OpenMetadata API 클라이언트
└── dag_metadata_sync.py     # Airflow DAG (주기적 동기화)
```

**schema_scanner.py 핵심 로직:**
```python
def scan_database_schema(engine) -> Dict[str, Any]:
    """
    DB 스키마 전체 스캔

    Returns:
        {
            "tables": [
                {
                    "name": "stock_price_1d",
                    "columns": [
                        {
                            "name": "ticker",
                            "type": "VARCHAR(20)",
                            "nullable": False,
                            "sample_values": ["005930.KS", "000660.KS", ...],
                            "distinct_count": 2500,
                            "null_ratio": 0.0
                        },
                        ...
                    ],
                    "row_count": 1000000,
                    "indexes": [...],
                    "foreign_keys": [...]
                },
                ...
            ]
        }
    """
    pass

def analyze_column_patterns(column_data: Dict) -> Dict:
    """
    컬럼 데이터 패턴 분석
    - 날짜 패턴, 코드 패턴, 숫자 범위 등
    """
    pass
```

**description_generator.py 핵심 로직:**
```python
DESCRIPTION_PROMPT = """
다음 데이터베이스 컬럼 정보를 분석하여 설명을 생성하세요.

테이블: {table_name}
컬럼: {column_name}
데이터 타입: {data_type}
샘플 값: {sample_values}
Null 비율: {null_ratio}
고유값 수: {distinct_count}

다음 형식으로 응답하세요:
1. 컬럼 설명 (한국어, 1-2문장)
2. 비즈니스 용어 (이 컬럼을 부르는 다른 이름들)
3. 데이터 패턴 설명
"""

def generate_column_description(column_info: Dict) -> Dict:
    """
    LLM으로 컬럼 설명 자동 생성

    Returns:
        {
            "description": "일별 주가 데이터의 종가",
            "business_terms": ["종가", "마감가", "closing price"],
            "pattern": "양수 실수, 원 단위"
        }
    """
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
│      ▼                                                  │
│  [실행기]                                               │
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
├── context_collector.py     # 메타데이터 + Graph 조회
├── sql_generator.py         # SQL 생성 (LLM)
├── query_validator.py       # 쿼리 검증
├── query_executor.py        # 쿼리 실행
└── few_shot_examples.py     # Few-shot 예시
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

```python
VALIDATION_RULES = {
    # 허용
    "allowed_statements": ["SELECT"],

    # 차단
    "blocked_keywords": [
        "DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
        "GRANT", "REVOKE", "CREATE", "EXEC", "EXECUTE"
    ],

    # 위험 패턴
    "dangerous_patterns": [
        r";\s*--",           # SQL 주석 인젝션
        r"UNION\s+SELECT",   # UNION 인젝션
        r"INTO\s+OUTFILE",   # 파일 쓰기
    ],

    # 제한
    "max_rows": 1000,        # 최대 반환 행 수
    "timeout_seconds": 30,   # 쿼리 타임아웃
}
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

## 다음 단계 (Phase 5 이후)

- **Graph RAG 도입**: 뉴스/리포트에서 지식 추출
- **자연어 응답 생성**: SQL 결과를 자연어로 설명
- **대화형 인터페이스**: 슬랙/웹 챗봇 연동
- **쿼리 캐싱**: 자주 묻는 질문 캐시
