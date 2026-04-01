# Wren AI 기술 가이드 — 아키텍처, 동작 원리, BIP-Pipeline 적용

> **작성일:** 2026-04-02
> **기반 프로젝트:** BIP-Pipeline (주식 투자 데이터 파이프라인)
> **Wren AI 버전:** Engine 0.22.0 / AI Service 0.29.0 / UI 0.32.2
> **목적:** Wren AI의 기술적 내부 동작 원리, 설치 과정, BIP-Pipeline 적용 상세, 대안 솔루션 비교

---

## 목차

1. [Wren AI 개요](#1-wren-ai-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [구성 요소별 기술 상세](#3-구성-요소별-기술-상세)
4. [MDL (Modeling Definition Language)](#4-mdl-modeling-definition-language)
5. [SQL 생성 파이프라인](#5-sql-생성-파이프라인)
6. [Qdrant RAG 시스템](#6-qdrant-rag-시스템)
7. [LLM 통합 (LiteLLM)](#7-llm-통합-litellm)
8. [설치 및 구성 가이드](#8-설치-및-구성-가이드)
9. [BIP-Pipeline 적용 상세](#9-bip-pipeline-적용-상세)
10. [메타데이터 동기화 (OM ↔ Wren AI)](#10-메타데이터-동기화-om--wren-ai)
11. [운영 이슈 및 해결](#11-운영-이슈-및-해결)
12. [대안 솔루션 비교](#12-대안-솔루션-비교)
13. [향후 발전 방향](#13-향후-발전-방향)
14. [엔터프라이즈 솔루션 비교 — Palantir Foundry & Databricks](#14-엔터프라이즈-솔루션-비교--palantir-foundry--databricks)

---

## 1. Wren AI 개요

### 1-1. Wren AI란?

Wren AI는 오픈소스 **Text-to-SQL 엔진**으로, 자연어 질문을 SQL 쿼리로 변환하여 실행합니다.
핵심 차별점은 **시맨틱 레이어(MDL)**를 통해 비즈니스 로직을 명시적으로 정의하여 LLM의 hallucination을 줄이는 것입니다.

```
사용자: "PER이 10 이하인 종목 보여줘"
         ↓
Wren AI: MDL에서 PER 정의 확인 → 적절한 테이블/컬럼 선택 → SQL 생성 → 실행
         ↓
결과:    종목명, PER, ROE 등 테이블 반환
```

### 1-2. 핵심 설계 철학

| 원칙 | 설명 |
|------|------|
| **Semantic-First** | LLM에 raw 스키마가 아닌 비즈니스 의미가 부여된 MDL을 제공 |
| **Data Never Leaves** | LLM에 실제 데이터를 보내지 않음. 메타데이터(스키마/설명)만 전달 |
| **Single Source of Truth** | MDL에 비즈니스 로직을 한 곳에 정의 → 일관된 쿼리 생성 |
| **Modular Pipeline** | 의도 분류, 스키마 검색, SQL 생성, 교정을 독립 모듈로 구성 |

### 1-3. 1질문 = 1SQL 제약

Wren AI는 구조적으로 **하나의 질문에 하나의 SQL만 생성**합니다.
복합 질문(여러 테이블 조회 → 결과 종합)은 처리할 수 없으며,
이를 위해서는 LangGraph 같은 에이전트 프레임워크에서 Wren AI API를 도구로 활용하는 구조가 필요합니다.

---

## 2. 시스템 아키텍처

### 2-1. 전체 구조

```mermaid
graph TB
    subgraph Client["클라이언트"]
        UI[Wren UI<br/>Next.js :3000]
        API_EXT[외부 API 호출<br/>POST /v1/asks]
    end

    subgraph Core["코어 서비스"]
        AI[Wren AI Service<br/>Python/FastAPI :5555]
        EN[Wren Engine<br/>Java + Rust/DataFusion :8080]
        IB[Ibis Server<br/>Python :8000]
    end

    subgraph Storage["저장소"]
        QD[Qdrant<br/>벡터 DB :6333]
        SQ[SQLite<br/>UI 메타데이터]
    end

    subgraph External["외부"]
        LLM[LLM Provider<br/>OpenAI / Anthropic / Ollama]
        DB[(PostgreSQL<br/>사용자 데이터)]
    end

    UI -->|GraphQL| AI
    API_EXT -->|REST| AI
    AI -->|임베딩 검색| QD
    AI -->|LLM 호출| LLM
    AI -->|SQL 검증| EN
    EN -->|MDL 기반 SQL 재작성| IB
    IB -->|실제 쿼리 실행| DB
    UI -->|모델 관리| SQ

    style Client fill:#e3f2fd
    style Core fill:#f3e5f5
    style Storage fill:#e8f5e9
    style External fill:#fff3e0
```

### 2-2. 요청 처리 흐름

```mermaid
sequenceDiagram
    participant U as 사용자/API
    participant UI as Wren UI
    participant AI as AI Service
    participant QD as Qdrant
    participant LLM as LLM (GPT)
    participant EN as Wren Engine
    participant IB as Ibis Server
    participant DB as PostgreSQL

    U->>UI: 자연어 질문 입력
    UI->>AI: POST /v1/asks {"query": "..."}

    Note over AI: 1. Intent Classification
    AI->>LLM: 의도 분류 요청
    LLM-->>AI: TEXT_TO_SQL / DATA_ASSISTANCE

    Note over AI: 2. Schema & Context Retrieval
    AI->>QD: 스키마 임베딩 검색
    QD-->>AI: 관련 테이블/컬럼 반환
    AI->>QD: SQL Pairs 유사 검색
    QD-->>AI: 유사 질문-SQL 패턴
    AI->>QD: Instructions 검색
    QD-->>AI: 적용할 규칙

    Note over AI: 3. SQL Generation
    AI->>LLM: 컨텍스트 + 질문 → SQL 생성
    LLM-->>AI: 생성된 SQL

    Note over AI: 4. SQL Validation & Correction
    AI->>EN: SQL 검증 요청
    EN-->>AI: 검증 결과 (pass/fail)

    alt SQL 검증 실패
        AI->>LLM: 에러 메시지 + 재생성 요청
        LLM-->>AI: 수정된 SQL
    end

    Note over AI: 5. SQL Execution
    AI->>EN: 검증된 SQL 실행
    EN->>IB: MDL 기반 SQL 재작성
    IB->>DB: 실제 PostgreSQL 쿼리
    DB-->>IB: 결과 데이터
    IB-->>EN: 결과
    EN-->>AI: 결과

    AI-->>UI: SQL + 결과 + 자연어 응답
    UI-->>U: 테이블/차트 표시
```

---

## 3. 구성 요소별 기술 상세

### 3-1. Wren Engine (SQL 실행 엔진)

| 항목 | 내용 |
|------|------|
| **언어** | Java (SQL 파서) + Rust (DataFusion 쿼리 엔진) |
| **기반** | Trino SQL 파서 fork + Apache DataFusion |
| **포트** | 8080 (REST), 7432 (SQL wire protocol) |
| **역할** | MDL 기반 SQL 재작성, 검증, 실행 계획 |

**핵심 동작 원리:**

```mermaid
flowchart LR
    SQL["입력 SQL<br/>(AI Service가 생성)"]
    PARSE["SQL Parser<br/>(Trino fork, Antlr4)"]
    LP["LogicalPlan<br/>(DataFusion IR)"]
    REWRITE["MDL Rewriter<br/>(모델→서브쿼리 변환)"]
    VALIDATE["Validator<br/>(테이블/컬럼/타입 검증)"]
    OUTPUT["출력 SQL<br/>(DB 방언으로 변환)"]

    SQL --> PARSE --> LP --> REWRITE --> VALIDATE --> OUTPUT

    style LP fill:#e1bee7
```

**MDL → SQL 변환 예시:**

```sql
-- 입력 (AI Service가 생성한 SQL)
SELECT stock_name, close FROM public_analytics_stock_daily
WHERE stock_name ILIKE '%하이닉스%'

-- Engine 내부: MDL 모델을 서브쿼리로 확장
SELECT stock_name, close FROM (
    SELECT * FROM public.analytics_stock_daily  -- 실제 테이블로 매핑
) AS public_analytics_stock_daily
WHERE stock_name ILIKE '%하이닉스%'
```

**SQL Rewriter 구현:**
- Antlr4 Visitor 패턴으로 AST 순회
- 모델 참조 → 서브쿼리 치환
- Calculated Field → expression 인라인 삽입
- Relationship → JOIN 조건 자동 생성

**LogicalPlan (DataFusion):**
- Apache DataFusion의 중간 표현(IR)을 사용
- `UserDefinedLogicalNode`로 MDL 전용 노드 추가
- `AnalyzerRule`로 모델별 변환 규칙 적용
- 표준 SQL → DB별 방언(PostgreSQL, BigQuery, Snowflake 등) 변환

### 3-2. Wren AI Service (NL2SQL 엔진)

| 항목 | 내용 |
|------|------|
| **언어** | Python 3.12 |
| **프레임워크** | FastAPI + uvloop |
| **비동기 처리** | Hamilton (DAG 기반 비동기 실행) |
| **컴포넌트** | Haystack (파이프라인 구성) |
| **포트** | 5555 |

**주요 API 엔드포인트:**

| 엔드포인트 | 메서드 | 용도 |
|-----------|--------|------|
| `/v1/asks` | POST | 자연어 질문 제출 |
| `/v1/asks/{id}/result` | GET | 질문 결과 조회 (polling) |
| `/v1/semantics-descriptions` | POST | 테이블/컬럼 설명 자동 생성 |
| `/v1/question-recommendations/{id}` | GET | 추천 질문 조회 |

**파이프라인 구성 (config.yaml):**

```yaml
type: pipeline
pipes:
  # 인덱싱 파이프라인 (Deploy 시 실행)
  - name: db_schema_indexing          # 스키마 임베딩 → Qdrant
  - name: table_description_indexing   # 테이블 설명 임베딩
  - name: sql_pairs_indexing           # SQL Pairs 임베딩
  - name: instructions_indexing        # Instructions 임베딩
  - name: project_meta_indexing        # 프로젝트 메타데이터

  # 검색 파이프라인 (질문 시 실행)
  - name: db_schema_retrieval          # 관련 테이블/컬럼 검색
  - name: historical_question_retrieval # 과거 질문 패턴 검색
  - name: sql_pairs_retrieval          # 유사 SQL Pairs 검색
  - name: instructions_retrieval       # 적용할 Instructions 검색

  # 생성 파이프라인
  - name: intent_classification        # 의도 분류
  - name: sql_generation               # SQL 생성
  - name: sql_generation_reasoning     # SQL 생성 추론 (Chain-of-Thought)
  - name: sql_correction               # SQL 교정 (최대 3회 재시도)
  - name: sql_answer                   # 결과 자연어 변환
  - name: chart_generation             # 차트 생성
```

### 3-3. Wren UI (웹 인터페이스)

| 항목 | 내용 |
|------|------|
| **프레임워크** | Next.js (React) |
| **API** | Apollo GraphQL |
| **데이터 저장** | SQLite (모델, 관계, SQL Pairs, Instructions) |
| **포트** | 3000 |

**GraphQL 주요 API:**

```graphql
# 모델 관리
{ listModels { id displayName description } }
{ model(where: {id: 1}) { fields { displayName type properties } } }
mutation { updateModelMetadata(where: {id: 1}, data: {description: "...", columns: [...]}) }

# SQL Pairs
mutation { createSqlPair(data: {question: "...", sql: "..."}) { id } }
{ sqlPairs { id question sql } }

# Instructions
mutation { createInstruction(data: {instruction: "...", isDefault: false, questions: []}) { id } }

# Deploy (MDL 재생성 + Qdrant 재인덱싱)
mutation { deploy { status } }
```

### 3-4. Ibis Server (데이터 소스 커넥터)

| 항목 | 내용 |
|------|------|
| **기반** | Ibis (Python 데이터 분석 프레임워크) |
| **역할** | 12+ 데이터 소스 통합 커넥터 |
| **포트** | 8000 |

**지원 데이터 소스:**
PostgreSQL, MySQL, BigQuery, Snowflake, DuckDB, ClickHouse, Trino, MSSQL, Oracle, Databricks, SQLite, MariaDB

### 3-5. Qdrant (벡터 DB)

| 항목 | 내용 |
|------|------|
| **버전** | v1.11.0 |
| **임베딩 모델** | text-embedding-3-large (3072 dimensions) |
| **포트** | 6333 (REST), 6334 (gRPC) |
| **역할** | 스키마/SQL Pairs/Instructions 임베딩 저장 및 유사도 검색 |

### 3-6. Bootstrap (초기화 서비스)

```bash
# init.sh 동작:
1. config.properties 생성 (Engine 설정)
2. mdl/ 디렉토리 생성
3. sample.json 생성 (빈 MDL 초기 파일)
```

시작 후 즉시 종료되는 init container 패턴.

---

## 4. MDL (Modeling Definition Language)

### 4-1. MDL이란?

MDL은 Wren AI의 **시맨틱 레이어 정의 언어**입니다.
물리적 DB 스키마와 사용자 사이에 비즈니스 의미를 부여하는 추상화 계층을 정의합니다.

```mermaid
graph LR
    DB["물리적 DB<br/>stock_info, stock_price_1d, ..."]
    MDL["MDL 시맨틱 레이어<br/>모델 + 관계 + 계산 필드 + 메트릭"]
    USER["사용자 / LLM<br/>비즈니스 용어로 질문"]

    DB -->|추상화| MDL -->|비즈니스 의미| USER

    style MDL fill:#fff3e0,stroke:#e65100
```

### 4-2. MDL 구조 (JSON)

```json
{
  "catalog": "stockdb",
  "schema": "public",
  "dataSource": "POSTGRES",
  "models": [
    {
      "name": "public_analytics_stock_daily",
      "properties": {
        "schema": "public",
        "catalog": "stockdb",
        "table": "analytics_stock_daily",
        "description": "Gold layer: 시세+지표+컨센서스 와이드 테이블"
      },
      "columns": [
        {
          "name": "stock_name",
          "type": "VARCHAR",
          "isCalculated": false,
          "properties": {
            "description": "한글 종목명. 검색 시 ILIKE 패턴 사용 권장.",
            "displayName": "stock_name"
          }
        },
        {
          "name": "price_change_pct",
          "type": "DECIMAL",
          "isCalculated": true,
          "expression": "(close - open) / open * 100",
          "properties": {
            "description": "당일 등락률 (%)"
          }
        }
      ]
    }
  ],
  "relationships": [
    {
      "name": "stock_daily_to_info",
      "models": ["public_analytics_stock_daily", "public_stock_info"],
      "joinType": "MANY_TO_ONE",
      "condition": "public_analytics_stock_daily.ticker = public_stock_info.ticker"
    }
  ],
  "metrics": [],
  "macros": []
}
```

### 4-3. MDL 주요 구성 요소

| 요소 | 역할 | 예시 |
|------|------|------|
| **Models** | 물리적 테이블의 논리적 표현 | `public_analytics_stock_daily` |
| **Columns** | 컬럼 + 설명 + 타입 | `stock_name: "한글 종목명"` |
| **Calculated Fields** | 런타임 계산 필드 (isCalculated=true) | `등락률 = (close - open) / open * 100` |
| **Relationships** | 모델 간 JOIN 경로 | `stock_daily.ticker = stock_info.ticker` |
| **Metrics** | 사전 정의된 집계 KPI | `평균 PER = AVG(per_actual)` |
| **Macros** | JinJava 템플릿 재사용 | 공통 필터, 계산식 |

### 4-4. MDL이 NL2SQL 정확도를 높이는 원리

```
Without MDL:  LLM이 raw 스키마만 보고 추측
  "PER 알려줘" → market_value / net_income? (단위 불일치!)

With MDL:     LLM이 MDL 설명을 참고
  "PER 알려줘" → per_actual 컬럼 사용 (이미 계산됨)
```

---

## 5. SQL 생성 파이프라인

### 5-1. 전체 파이프라인 흐름

```mermaid
flowchart TB
    Q[사용자 질문]

    subgraph Stage1["Stage 1: 의도 분류"]
        IC[Intent Classification<br/>LLM 호출]
        IC_R{TEXT_TO_SQL?}
    end

    subgraph Stage2["Stage 2: 컨텍스트 수집"]
        SR[Schema Retrieval<br/>Qdrant 벡터 검색]
        SP[SQL Pairs Retrieval<br/>유사 패턴 검색]
        IR[Instructions Retrieval<br/>규칙 검색]
        SF[SQL Functions Retrieval<br/>DB 함수 목록]
    end

    subgraph Stage3["Stage 3: SQL 생성"]
        SG[SQL Generation<br/>LLM + Chain-of-Thought]
    end

    subgraph Stage4["Stage 4: 검증/교정"]
        VD[Validation<br/>Wren Engine 검증]
        VD_R{통과?}
        SC[SQL Correction<br/>LLM 재생성<br/>최대 3회]
    end

    subgraph Stage5["Stage 5: 실행"]
        EX[SQL Execution<br/>Engine → Ibis → DB]
        AN[Answer Generation<br/>결과 자연어 변환]
    end

    Q --> IC --> IC_R
    IC_R -->|Yes| SR & SP & IR & SF
    IC_R -->|No| DA[Data Assistance<br/>일반 대화 응답]
    SR & SP & IR & SF --> SG
    SG --> VD --> VD_R
    VD_R -->|Yes| EX --> AN
    VD_R -->|No| SC --> VD

    style Stage1 fill:#e3f2fd
    style Stage2 fill:#e8f5e9
    style Stage3 fill:#fff3e0
    style Stage4 fill:#fce4ec
    style Stage5 fill:#f3e5f5
```

### 5-2. 각 Stage 상세

**Stage 1 — 의도 분류 (Intent Classification):**
- LLM에 질문을 보내 유형 판별
- `TEXT_TO_SQL`: SQL 생성 파이프라인으로
- `MISLEADING_QUERY`: 데이터와 무관한 질문 거부
- `DATA_ASSISTANCE`: 일반 도움 응답

**Stage 2 — 컨텍스트 수집 (Retrieval):**
- 질문을 임베딩 → Qdrant에서 유사도 검색
- 스키마 검색: 관련 테이블/컬럼 + 설명 (top-10 tables, top-100 columns)
- SQL Pairs: 유사 질문의 검증된 SQL 패턴 (similarity > 0.7)
- Instructions: 적용할 도메인 규칙
- Column Pruning: 불필요한 컬럼 제거 (선택적)

**Stage 3 — SQL 생성:**
- 수집된 컨텍스트를 LLM 프롬프트에 주입
- Chain-of-Thought reasoning 지원 (sql_generation_reasoning)
- MDL 모델의 reference name을 사용하여 SQL 작성

**Stage 4 — 검증/교정:**
- Wren Engine이 SQL을 LogicalPlan으로 파싱
- 테이블/컬럼 존재 여부, 타입 호환성 검증
- 실패 시 에러 메시지를 LLM에 전달하여 재생성 (최대 3회)

**Stage 5 — 실행/응답:**
- Engine → Ibis → PostgreSQL 실행
- 결과를 LLM이 자연어로 요약

### 5-3. SQL 교정 메커니즘

```
시도 1: SELECT stock_name, close FROM public.analytics_stock_daily
         → Engine Error: "table not found"

시도 2: SELECT stock_name, close FROM public_analytics_stock_daily
         → Engine: OK ✅
```

`max_sql_correction_retries: 3` (config.yaml에서 설정)

---

## 6. Qdrant RAG 시스템

### 6-1. 임베딩 대상

Deploy 시 다음 데이터가 임베딩되어 Qdrant에 저장됩니다:

| Collection | 내용 | 용도 |
|-----------|------|------|
| `db_schema` | 테이블명, 컬럼명, 타입, 설명, 관계 | 관련 스키마 검색 |
| `table_descriptions` | 테이블/컬럼 description | 의미적 유사도 매칭 |
| `sql_pairs` | question + SQL 쌍 | 유사 패턴 재활용 |
| `instructions` | 도메인 규칙 | 적용할 규칙 검색 |
| `historical_questions` | 과거 질문 이력 | 이전 질문 참고 |

### 6-2. 검색 파라미터

```yaml
settings:
  table_retrieval_size: 10              # 검색할 테이블 수
  table_column_retrieval_size: 100      # 검색할 컬럼 수
  sql_pairs_similarity_threshold: 0.7   # SQL Pairs 유사도 임계값
  sql_pairs_retrieval_max_size: 10      # 최대 반환 SQL Pairs 수
  instructions_similarity_threshold: 0.7
  instructions_top_k: 10
  historical_question_retrieval_similarity_threshold: 0.9
```

### 6-3. 임베딩 모델

```yaml
type: embedder
provider: litellm_embedder
models:
  - model: text-embedding-3-large
    alias: default
    timeout: 120
```

- **차원:** 3072
- **제공자:** OpenAI (LiteLLM 경유)
- `recreate_index: true` 설정 시 Deploy마다 전체 재인덱싱

---

## 7. LLM 통합 (LiteLLM)

### 7-1. LiteLLM이란?

LiteLLM은 100+ LLM 제공자를 통일된 API로 추상화하는 라이브러리입니다.
Wren AI는 이를 통해 OpenAI, Anthropic, Ollama 등을 동일한 인터페이스로 호출합니다.

### 7-2. 지원 제공자

| 제공자 | 모델 예시 | 비고 |
|--------|---------|------|
| **OpenAI** | gpt-4o, gpt-4o-mini | 기본값 |
| **Anthropic** | claude-sonnet-4-20250514 | API 키 필요 |
| **Google** | gemini-2.0-flash | - |
| **Ollama** | llama3.1:8b, codestral | 로컬, 무료 |
| **Azure OpenAI** | gpt-4o (Azure 배포) | 엔터프라이즈 |
| **AWS Bedrock** | Claude, Llama | - |

### 7-3. 설정 방법 (config.yaml)

```yaml
# OpenAI (기본)
type: llm
provider: litellm_llm
models:
  - alias: default
    model: gpt-4o-mini
    context_window_size: 128000
    kwargs:
      max_tokens: 4096
      temperature: 0

# Anthropic Claude로 변경
type: llm
provider: litellm_llm
models:
  - alias: default
    model: anthropic/claude-sonnet-4-20250514
    context_window_size: 200000
    kwargs:
      max_tokens: 4096
      temperature: 0

# Ollama 로컬 모델
type: llm
provider: litellm_llm
models:
  - alias: default
    model: ollama_chat/llama3.1:70b
    api_base: http://host.docker.internal:11434
    context_window_size: 128000
```

### 7-4. Rate Limit 주의

| 모델 | TPM 제한 (무료 티어) | 권장 |
|------|-------------------|------|
| gpt-4o | 30,000 TPM | Deploy 시 rate limit 걸림. 유료 티어 필요 |
| gpt-4o-mini | 200,000 TPM | 무료 티어로도 충분 |
| claude-sonnet | 40,000 TPM | - |

BIP-Pipeline에서는 **gpt-4o-mini**를 사용 중 (rate limit 회피 + 단순 쿼리에 충분한 성능).

---

## 8. 설치 및 구성 가이드

### 8-1. 사전 요구사항

```bash
# Docker 네트워크 (이미 존재해야 함)
docker network create stock-network

# .env 파일에 OpenAI 키 설정
echo "OPENAI_API_KEY=sk-..." >> .env
```

### 8-2. Docker Compose 구조

```yaml
# docker-compose.wrenai.yml 핵심 구조
services:
  wren-bootstrap:    # 초기화 (config.properties 생성 → 종료)
    image: ghcr.io/canner/wren-bootstrap:0.1.5

  wren-engine:       # SQL 엔진 (MDL 기반)
    image: ghcr.io/canner/wren-engine:0.22.0
    depends_on: [wren-bootstrap]

  ibis-server:       # DB 커넥터
    image: ghcr.io/canner/wren-engine-ibis:0.22.0

  qdrant:            # 벡터 DB
    image: qdrant/qdrant:v1.11.0

  wren-ai-service:   # NL2SQL 엔진
    image: ghcr.io/canner/wren-ai-service:0.29.0
    environment:
      QDRANT_HOST: wren-qdrant          # 필수!
      SHOULD_FORCE_DEPLOY: 1
      CONFIG_PATH: /app/config.yaml
    depends_on: [qdrant, wren-engine]

  wren-ui:           # 웹 UI
    image: ghcr.io/canner/wren-ui:0.32.2
    ports: ["3000:3000"]
    depends_on: [wren-ai-service, wren-engine]
```

### 8-3. 설치 트러블슈팅

| 문제 | 원인 | 해결 |
|------|------|------|
| Engine `config.properties not found` | Bootstrap이 volume에 파일 미생성 | `docker run --rm -v wren-data:/app/data -e DATA_PATH=/app/data ghcr.io/canner/wren-bootstrap:0.1.5 /bin/sh /app/init.sh` |
| AI Service `qdrant did not start` | `QDRANT_HOST` 환경변수 미설정 | docker-compose에 `QDRANT_HOST: wren-qdrant` 추가 |
| `Incorrect API key` | `.env`에서 키가 한 줄에 붙음 | 줄바꿈 확인 |
| `Rate limit reached for gpt-4o` | 무료 티어 TPM 30,000 초과 | config.yaml에서 `gpt-4o-mini`로 변경 |
| `table not found` (SQL Pairs 등록 시) | `public.` prefix 사용 | Wren 내부는 `public_` (언더스코어) 사용 |
| Apple Silicon 이미지 pull 실패 | platform 미지정 | `platform: linux/arm64` 명시 |

### 8-4. 초기 설정 절차

```
1. http://localhost:3000 접속
2. PostgreSQL 선택 → 연결 정보 입력 (Host: bip-postgres)
3. 테이블 선택 (Gold 테이블 우선)
4. 관계(Relationship) 정의 (ticker 기반)
5. Deploy → 스키마 인덱싱
6. 자연어 질문 테스트
```

---

## 9. BIP-Pipeline 적용 상세

### 9-1. 등록된 모델

| 모델 (reference name) | 소스 테이블 | 컬럼 수 | 용도 |
|-----------------------|-----------|---------|------|
| `public_stock_info` | stock_info | 23 | 종목 마스터 |
| `public_stock_price_1d` | stock_price_1d | 19 | 일봉 시세 |
| `public_analytics_stock_daily` | analytics_stock_daily | 46 | Gold: 시세+지표+컨센서스 |
| `public_analytics_macro_daily` | analytics_macro_daily | 49 | Gold: 매크로 피벗 |
| `public_analytics_valuation` | analytics_valuation | 32 | Gold: 밸류에이션 |

### 9-2. 테이블 관계

```mermaid
erDiagram
    public_stock_info ||--o{ public_stock_price_1d : "ticker"
    public_stock_info ||--o{ public_analytics_stock_daily : "ticker"
    public_stock_info ||--o{ public_analytics_valuation : "ticker"
    public_stock_price_1d ||--o{ public_analytics_valuation : "ticker"

    public_stock_info {
        varchar ticker PK
        varchar stock_name
        varchar market_type
        decimal market_value
    }
    public_analytics_stock_daily {
        varchar ticker FK
        date trade_date
        decimal close
        decimal rsi14
        decimal change_pct
        boolean golden_cross
    }
    public_analytics_valuation {
        varchar ticker FK
        int fiscal_year
        decimal per_actual
        decimal roe_actual
        decimal revenue_growth
    }
    public_analytics_macro_daily {
        date indicator_date PK
        decimal vix
        decimal usd_krw
        decimal kospi
        decimal kr_base_rate
    }
```

### 9-3. SQL Pairs (29개)

7개 카테고리:

| 카테고리 | 예시 질문 | SQL 패턴 핵심 |
|---------|---------|-------------|
| **종목 검색** | "하이닉스 주가" | `stock_name ILIKE '%하이닉스%'` |
| **기간별 조회** | "삼성전자 최근 한달 주가" | `trade_date >= CURRENT_DATE - INTERVAL '1 month'` |
| **기술지표** | "RSI 과매도 종목" | `rsi14 < 30 AND rsi14 IS NOT NULL` |
| **밸류에이션** | "PER 낮은 종목 10개" | `per_actual > 0 ORDER BY per_actual LIMIT 10` |
| **매크로** | "오늘 환율" | `ORDER BY indicator_date DESC LIMIT 1` |
| **수급** | "외국인 순매수 상위" | `foreign_buy_volume > 0 ORDER BY ... DESC` |
| **복합** | "저PER 고ROE" | `per_actual < 10 AND roe_actual > 15` |

### 9-4. Instructions

```
- 종목 검색 시 ticker 하드코딩 금지. stock_name ILIKE '%검색어%' 사용
- 결과에 반드시 stock_name 포함
- "현재 주가" = ORDER BY trade_date DESC LIMIT 1
- 주가 흐름 질문 시 GROUP BY 없이 일별 데이터 반환
```

---

## 10. 메타데이터 동기화 (OM ↔ Wren AI)

### 10-1. 동기화 구조

```mermaid
flowchart TB
    subgraph Source["메타데이터 원천"]
        OM["OpenMetadata<br/>UI/API에서 편집"]
    end

    subgraph DAG["10_sync_metadata_daily<br/>(Airflow DAG, 매일 09:00 KST)"]
        T1["Task 1: sync_om_to_db<br/>OM API → COMMENT ON TABLE/COLUMN"]
        T2["Task 2: sync_om_to_wrenai<br/>OM API → GraphQL updateModelMetadata → deploy"]
    end

    subgraph Target["동기화 대상"]
        DB["PostgreSQL COMMENT<br/>(신규 테이블 추가 시 Wren AI 자동 반영)"]
        WR["Wren AI Model Description<br/>(5 models, 53 columns)"]
        QD["Qdrant Embedding<br/>(Deploy 시 재인덱싱)"]
    end

    OM --> T1 --> DB
    T1 --> T2
    T2 --> WR --> QD

    style Source fill:#ffe0b2,stroke:#e65100
    style DAG fill:#e8eaf6
    style Target fill:#c8e6c9
```

### 10-2. 동기화 스크립트 상세

**`scripts/om_sync_wrenai.py` 동작 과정:**

```
1. OM API에서 39개 테이블의 description + 453개 컬럼 description 조회
2. Wren AI SQLite에서 model_id, model_column.id 매핑 조회 (docker exec)
3. GraphQL updateModelMetadata 호출 (모델별 description + columns description)
4. GraphQL deploy 호출 → MDL 재생성 + Qdrant 임베딩 재인덱싱
```

**`scripts/om_sync_comments.py` 동작 과정:**

```
1. OM API에서 테이블/컬럼 description 조회
2. psycopg2로 PostgreSQL 연결
3. COMMENT ON TABLE / COMMENT ON COLUMN SQL 실행
4. commit
```

### 10-3. Wren AI가 OM에서 활용할 수 없는 것

| OM 자산 | Wren AI 반영 | 이유 |
|--------|------------|------|
| 테이블/컬럼 설명 | ✅ 동기화 가능 | GraphQL API 존재 |
| 용어집 (Glossary 77개) | ❌ 불가 | Wren AI에 glossary 기능 없음 |
| 태그 (Domain, DataLayer) | ❌ 불가 | Wren AI에 태그 시스템 없음 |
| Lineage | ❌ 불가 | Wren AI에 lineage 개념 없음 |
| 컬럼-용어 매핑 | ❌ 불가 | - |

→ 이 자산들은 향후 **LangGraph 에이전트**에서 OM API를 직접 호출하여 LLM 컨텍스트에 주입하는 방식으로 활용 예정.

---

## 11. 운영 이슈 및 해결

### 11-1. 발견된 문제와 해결

| # | 문제 | 원인 | 해결 | 상태 |
|---|------|------|------|------|
| 1 | LLM이 ticker 추측 (035720.KQ = 카카오를 하이닉스로) | LLM 학습 데이터 기반 hallucination | Instructions: "ticker 하드코딩 금지" | ✅ |
| 2 | ETF/보통주 혼합 결과 | ILIKE로 ETF명도 매칭 | Instructions: "여러 매칭 시 모두 표시 + stock_name 포함" | ✅ |
| 3 | GROUP BY 에러 | Wren Engine 엄격한 SQL 검증 | Instructions: "주가 흐름은 GROUP BY 없이" | ✅ |
| 4 | "understanding" 무한 로딩 | OpenAI rate limit (gpt-4o) | gpt-4o-mini로 변경 | ✅ |
| 5 | Deploy 후 설명 미반영 | Wren AI가 DB COMMENT 자동 안 읽음 | GraphQL API로 직접 주입 (om_sync_wrenai.py) | ✅ |
| 6 | SQL Pairs `public.` 에러 | Wren 내부 reference name은 `public_` | 언더스코어로 변경 | ✅ |
| 7 | 1질문 = 1SQL 한계 | Wren AI 구조적 제약 | 향후 LangGraph 통합 | 🔲 |
| 8 | 답변 품질 (데이터만 반환) | Wren AI는 SQL 변환기 | 향후 LangGraph + LLM 분석 | 🔲 |

### 11-2. 성능/리소스

| 서비스 | CPU | Memory | 비고 |
|--------|-----|--------|------|
| wren-engine | 1 core | ~4GB | JVM 기반 |
| wren-ai-service | 1 core | ~2GB | Python |
| qdrant | 0.5 core | ~512MB | 경량 |
| wren-ui | 0.5 core | ~512MB | Next.js |
| ibis-server | 0.5 core | ~512MB | Python |

총 약 **3.5 CPU, 8GB RAM** 사용.

---

## 12. 대안 솔루션 비교

### 12-1. NL2SQL 도구 비교

```mermaid
quadrantChart
    title NL2SQL 도구 포지셔닝
    x-axis "단순 (라이브러리)" --> "완전 (플랫폼)"
    y-axis "개발자 중심" --> "비즈니스 사용자 중심"
    quadrant-1 "엔터프라이즈 BI"
    quadrant-2 "셀프서비스 분석"
    quadrant-3 "개발자 도구"
    quadrant-4 "커스텀 에이전트"
    "Wren AI": [0.7, 0.7]
    "Vanna AI": [0.3, 0.4]
    "Defog AI": [0.5, 0.5]
    "Chat2DB": [0.6, 0.8]
    "DataHerald": [0.8, 0.6]
    "LangChain SQL": [0.2, 0.2]
    "LangGraph": [0.3, 0.3]
```

### 12-2. 상세 비교표

| 항목 | Wren AI | Vanna AI | Defog AI | LangChain SQL Agent | Chat2DB |
|------|---------|---------|---------|-------------------|---------|
| **유형** | 플랫폼 (UI+엔진) | Python 라이브러리 | SaaS/Self-hosted | 프레임워크 | 데스크톱 앱 |
| **시맨틱 레이어** | ✅ MDL | ❌ | ❌ | ❌ | ❌ |
| **멀티 쿼리** | ❌ 1개만 | ❌ 1개만 | ❌ 1개만 | ✅ Agent Loop | ❌ |
| **자체 UI** | ✅ 웹 | ❌ (Jupyter) | ✅ 웹 | ❌ | ✅ 데스크톱 |
| **RAG** | ✅ Qdrant | ✅ ChromaDB | ✅ 자체 | ❌ (직접 구현) | ❌ |
| **SQL Pairs** | ✅ | ✅ (핵심 기능) | ✅ | ❌ | ❌ |
| **DB 지원** | 12+ | 모든 DB | 주요 6개 | 모든 DB | 20+ |
| **LLM** | 100+ (LiteLLM) | OpenAI/Ollama | 자체 모델 | 모든 LLM | OpenAI |
| **오픈소스** | ✅ AGPL | ✅ MIT | ✅ AGPL | ✅ MIT | ✅ Apache |
| **한국어** | 미검증 (작동 확인) | 미검증 | 미검증 | LLM 의존 | 지원 |
| **설치 난이도** | 중 (Docker 5개) | 하 (pip install) | 중 | 하 (pip) | 하 (다운로드) |

### 12-3. Wren AI vs Vanna AI 심층 비교

가장 자주 비교되는 두 도구:

| 기준 | Wren AI | Vanna AI |
|------|---------|---------|
| **접근 방식** | 시맨틱 레이어 + RAG | 순수 RAG (few-shot) |
| **비즈니스 로직** | MDL에 명시적 정의 | SQL 예시에서 암묵적 학습 |
| **정확도 원천** | MDL 메타데이터 + SQL Pairs | SQL Pairs + DDL + 문서 |
| **통합 방식** | REST API / UI | Python 함수 호출 |
| **적합한 경우** | 팀이 사용, 거버넌스 필요 | 개인 개발자, API 임베드 |
| **BIP 평가** | 현재 사용 중 | FastAPI 임베드 시 고려 |

### 12-4. 에이전트 프레임워크 비교

멀티 쿼리 / 복합 분석이 필요한 경우:

| 항목 | LangGraph | CrewAI | AutoGen |
|------|----------|--------|---------|
| **구조** | 상태 그래프 | 역할 기반 에이전트 | 대화 기반 에이전트 |
| **멀티 쿼리** | ✅ (노드별 실행) | ✅ (에이전트별 실행) | ✅ (턴별 실행) |
| **커스텀 도구** | ✅ (Tool 정의) | ✅ (Tool 정의) | ✅ (함수 등록) |
| **상태 관리** | ✅ (Checkpointer) | 제한적 | 제한적 |
| **BIP 평가** | **채택 예정** | - | - |

### 12-5. 아키텍처 대안 비교

```mermaid
graph TB
    subgraph A["현재: Wren AI 단독"]
        A1[사용자] --> A2[Wren AI] --> A3[1개 SQL] --> A4[결과 테이블]
    end

    subgraph B["향후: LangGraph + Wren AI"]
        B1[사용자] --> B2[LangGraph Agent]
        B2 --> B3[Wren AI API<br/>SQL 생성]
        B2 --> B4[OM API<br/>메타데이터]
        B2 --> B5[직접 SQL<br/>엔티티 해석]
        B3 & B4 & B5 --> B6[LLM 종합 분석] --> B7[자연어 응답]
    end

    subgraph C["대안: Vanna AI + FastAPI"]
        C1[사용자] --> C2[FastAPI]
        C2 --> C3[Vanna AI<br/>Python 라이브러리]
        C3 --> C4[1개 SQL] --> C5[JSON 응답]
    end

    style A fill:#e3f2fd
    style B fill:#e8f5e9
    style C fill:#fff3e0
```

| 구성 | 장점 | 단점 | 적합한 경우 |
|------|------|------|-----------|
| **A. Wren AI 단독** | 즉시 사용 가능, UI 제공 | 1SQL, 답변 단순 | 간단한 데이터 조회 |
| **B. LangGraph + Wren AI** | 멀티 쿼리, OM 활용, 풍부한 답변 | 개발 필요 | 복합 분석, 에이전트 |
| **C. Vanna + FastAPI** | 경량, API 임베드 쉬움 | UI 없음, 시맨틱 레이어 없음 | API 서비스 임베드 |

---

## 13. 향후 발전 방향

### 13-1. 단기 (Wren AI 개선)

```
🔲 Calculated Fields 추가 (등락률, 이격도, PER밴드 등 20개)
🔲 SQL Pairs 확대 (50개 → 100개, 실 사용 패턴 기반)
🔲 Instructions 고도화 (섹터별 규칙, 시장 구분 규칙)
```

### 13-2. 중기 (LangGraph 통합)

```mermaid
flowchart TB
    U[사용자 질문]

    subgraph Agent["LangGraph 에이전트"]
        A1[엔티티 해석<br/>DB ILIKE 조회]
        A2[의도 분류<br/>주가? 재무? 비교?]
        A3[쿼리 계획<br/>필요한 SQL 수 결정]
        A4[SQL 실행 × N<br/>Wren AI API]
        A5[메타데이터 보강<br/>OM API 용어집/태그]
        A6[결과 종합<br/>LLM 분석 + 자연어 응답]
    end

    subgraph Tools["도구"]
        W[Wren AI<br/>POST /v1/asks]
        O[OM API<br/>용어집/메타데이터]
        D[PostgreSQL<br/>직접 쿼리]
    end

    U --> A1 --> A2 --> A3 --> A4 --> A5 --> A6 --> U
    A1 -.-> D
    A4 -.-> W
    A5 -.-> O

    style Agent fill:#e8eaf6
    style Tools fill:#e0f2f1
```

### 13-3. 장기 (Knowledge Graph)

```
🔲 Neo4j Knowledge Graph 도입
🔲 투자 도메인 온톨로지 (isA, partOf, calculatedFrom)
🔲 OM Glossary → Knowledge Graph 자동 변환
🔲 LangGraph에서 KG 검색 → LLM 컨텍스트 주입
```

---

## 14. 엔터프라이즈 솔루션 비교 — Palantir Foundry & Databricks

BIP-Pipeline이 지향하는 아키텍처(데이터 수집 → 분석 레이어 → 시맨틱 레이어 → NL2SQL → 에이전트)는
Palantir Foundry와 Databricks Lakehouse가 엔터프라이즈 규모로 구현한 것과 개념적으로 동일합니다.

### 14-1. 전체 비교 개요

```mermaid
graph TB
    subgraph BIP["BIP-Pipeline (오픈소스 DIY)"]
        B1[Airflow<br/>오케스트레이션]
        B2[PostgreSQL<br/>저장소]
        B3[OpenMetadata<br/>카탈로그 + Lineage]
        B4[Wren AI<br/>NL2SQL]
        B5[LangGraph<br/>에이전트]
    end

    subgraph PAL["Palantir Foundry"]
        P1[Pipeline Builder<br/>오케스트레이션]
        P2[Foundry Storage<br/>저장소]
        P3[Ontology<br/>시맨틱 레이어 + 거버넌스]
        P4[AIP<br/>LLM + NL2SQL]
        P5[AIP Agent Studio<br/>에이전트]
    end

    subgraph DBR["Databricks Lakehouse"]
        D1[Workflows<br/>오케스트레이션]
        D2[Delta Lake<br/>저장소]
        D3[Unity Catalog<br/>카탈로그 + Lineage]
        D4[Genie<br/>NL2SQL]
        D5[Mosaic AI<br/>에이전트]
    end

    style BIP fill:#e8f5e9
    style PAL fill:#e3f2fd
    style DBR fill:#fff3e0
```

| 기능 영역 | BIP-Pipeline | Palantir Foundry | Databricks Lakehouse |
|----------|-------------|-----------------|---------------------|
| **오케스트레이션** | Airflow | Pipeline Builder + Transforms | Databricks Workflows |
| **저장소** | PostgreSQL | Foundry Storage (Parquet) | Delta Lake (Parquet + ACID) |
| **메타데이터 카탈로그** | OpenMetadata | Ontology | Unity Catalog |
| **Lineage** | OM Lineage (API → DAG → Table) | Ontology 자동 추적 | Unity Catalog 자동 추적 |
| **시맨틱 레이어** | Wren AI MDL | Ontology (Object Types) | Metric Views |
| **NL2SQL** | Wren AI + SQL Pairs | AIP (LLM + Ontology) | Genie (LLM + Unity Catalog) |
| **에이전트** | LangGraph (예정) | AIP Agent Studio | Mosaic AI Agent Framework |
| **용어집** | OM Glossary (77개) | Ontology Properties | Unity Catalog Tags |
| **거버넌스/태그** | OM Tags (DataLayer, Domain, SourceType) | Ontology + Dynamic Security | Unity Catalog + ABAC |
| **비용** | 무료 (오픈소스) | 수억원/년 (엔터프라이즈) | DBU 종량제 ($500~$5,000+/월) |

---

### 14-2. Palantir Foundry 상세

#### 개요

Palantir Foundry는 **엔터프라이즈 데이터 통합 + 의사결정 플랫폼**입니다.
핵심은 **Ontology(온톨로지)**로, 데이터를 테이블이 아닌 **비즈니스 객체(Object)**로 모델링합니다.

#### 전체 아키텍처

```mermaid
graph TB
    subgraph Integration["데이터 통합"]
        CONN[200+ 커넥터<br/>DB, S3, SAP, IoT]
        PB[Pipeline Builder<br/>노코드 파이프라인]
        CR[Code Repositories<br/>Python/SQL 변환]
    end

    subgraph Core["Foundry Core"]
        STORE[Storage Layer<br/>Parquet + 메타데이터]
        ONT[Ontology<br/>Object Types + Links + Actions]
        SEC[Dynamic Security<br/>Row/Object 레벨 접근 제어]
    end

    subgraph AI["AIP (AI Platform)"]
        LOGIC[AIP Logic<br/>노코드 LLM 함수]
        AGENT[Agent Studio<br/>프로덕션 에이전트]
        EVAL[AIP Evals<br/>모델 평가]
    end

    subgraph Apps["애플리케이션"]
        CONT[Contour<br/>분석 대시보드]
        WORK[Workshop<br/>노코드 앱 빌더]
        QUIV[Quiver<br/>데이터 탐색]
    end

    CONN --> PB & CR --> STORE
    STORE --> ONT --> SEC
    ONT --> LOGIC & AGENT
    ONT --> CONT & WORK & QUIV

    style Integration fill:#e3f2fd
    style Core fill:#e8eaf6
    style AI fill:#fce4ec
    style Apps fill:#e8f5e9
```

#### Ontology (온톨로지) — Foundry의 핵심

Palantir의 Ontology는 **전통적인 데이터 카탈로그(OpenMetadata)를 넘어서는 개념**입니다.
데이터를 "테이블의 행"이 아닌 **현실 세계 객체**로 표현합니다.

| 구성 요소 | 역할 | BIP 대응 |
|----------|------|---------|
| **Object Types** | 현실 세계 엔티티 정의 (종목, 거래, 투자자) | `stock_info` 테이블 ≈ "종목" Object Type |
| **Properties** | 객체의 속성 (종목코드, 시총, PER) | 컬럼 + OM 설명 |
| **Link Types** | 객체 간 관계 (종목 → 재무제표) | FK + Wren AI Relationship |
| **Action Types** | 객체 변경 행위 (매수, 포트폴리오 리밸런싱) | 없음 (Foundry 고유 기능) |
| **Functions** | 비즈니스 로직 (PER 계산, 밸류에이션 스코어) | Wren AI Calculated Fields |

**Ontology가 BIP의 OM + Wren AI + LangGraph를 합친 것과 같은 이유:**

```mermaid
graph LR
    subgraph BIP["BIP-Pipeline"]
        OM_BIP[OpenMetadata<br/>카탈로그 + 용어집]
        WR_BIP[Wren AI<br/>시맨틱 모델]
        LG_BIP[LangGraph<br/>에이전트]
    end

    subgraph Palantir["Palantir"]
        ONT_P[Ontology<br/>= OM + Wren AI + LangGraph<br/>하나로 통합]
    end

    OM_BIP -.->|메타데이터/용어| ONT_P
    WR_BIP -.->|시맨틱 모델| ONT_P
    LG_BIP -.->|워크플로우/Actions| ONT_P

    style BIP fill:#e8f5e9
    style Palantir fill:#e3f2fd
```

#### AIP (Artificial Intelligence Platform)

AIP는 LLM을 Ontology에 연결하여 **hallucination을 줄이는 구조**:

```
일반 LLM: "삼성전자 PER 알려줘" → LLM이 기억에서 추측 → 틀릴 수 있음
AIP:      "삼성전자 PER 알려줘" → Ontology에서 삼성전자 Object 조회 → 정확한 데이터 반환
```

| AIP 구성 요소 | 역할 | BIP 대응 |
|-------------|------|---------|
| **AIP Logic** | 노코드 LLM 함수 빌더 | Wren AI Instructions |
| **Agent Studio** | 프로덕션 에이전트 빌더 | LangGraph + Tools |
| **AIP Evals** | 모델 성능 평가 | 없음 (향후 필요) |

#### Foundry 가격 및 고객

| 항목 | 내용 |
|------|------|
| **가격** | 컴퓨트(초당) + 스토리지(GB/월) + Ontology(GB/월) — 일반적으로 수억원/년 |
| **고객** | 미국 국방부, CIA, NHS, Airbus, BP, 모건스탠리 |
| **시장 점유율** | 1.51% (엔터프라이즈 시장) |
| **Gotham** | 국방/정보기관 특화 버전 (지리공간 + 네트워크 분석) |

---

### 14-3. Databricks Lakehouse 상세

#### 개요

Databricks는 **레이크하우스 아키텍처** 기반 통합 데이터 + AI 플랫폼입니다.
데이터 웨어하우스의 거버넌스 + 데이터 레이크의 유연성을 결합합니다.

#### 전체 아키텍처

```mermaid
graph TB
    subgraph Control["Control Plane (Databricks 관리)"]
        UI_D[Workspace UI]
        JOB[Job Scheduler]
        UC[Unity Catalog<br/>거버넌스 + Lineage]
    end

    subgraph Data["Data Plane (고객 클라우드)"]
        DL[Delta Lake<br/>ACID + Time Travel]
        PHO[Photon Engine<br/>C++ 쿼리 엔진]
        SPK[Apache Spark<br/>분산 처리]
    end

    subgraph AI_ML["AI/ML"]
        GEN[Genie<br/>NL2SQL]
        MOS[Mosaic AI<br/>에이전트 + RAG]
        MLF[MLflow<br/>ML 라이프사이클]
        VS[Vector Search<br/>임베딩 인덱스]
    end

    subgraph Analytics["분석"]
        SQL_D[Databricks SQL<br/>서버리스 SQL]
        DASH[AI/BI Dashboards<br/>자연어 대시보드]
        NB[Notebooks<br/>Python/SQL/R/Scala]
    end

    UI_D --> JOB
    JOB --> SPK & PHO
    SPK & PHO --> DL
    UC --> DL & GEN & MOS
    DL --> SQL_D --> DASH
    DL --> GEN
    DL --> MOS & MLF

    style Control fill:#fff3e0
    style Data fill:#e8f5e9
    style AI_ML fill:#e3f2fd
    style Analytics fill:#fce4ec
```

#### Delta Lake — 저장소 핵심

Delta Lake은 Parquet 파일 위에 **ACID 트랜잭션**을 제공하는 오픈소스 스토리지 레이어:

| 기능 | 설명 | BIP 대응 |
|------|------|---------|
| **ACID 트랜잭션** | 원자성·일관성·격리·지속성 보장 | PostgreSQL ACID (기본 지원) |
| **Schema Enforcement** | 호환 안 되는 스키마 쓰기 거부 | 없음 (수동 검증) |
| **Schema Evolution** | 컬럼 추가/타입 변경 유연 | ALTER TABLE 수동 |
| **Time Travel** | 과거 버전 쿼리 (버전 번호/타임스탬프) | 없음 |
| **Delta Sharing** | 외부와 안전한 데이터 공유 | 없음 |

#### Unity Catalog — 거버넌스 & Lineage

```mermaid
graph TB
    UC[Unity Catalog]

    subgraph Namespace["3-Level Namespace"]
        CAT[Catalog<br/>stockdb]
        SCH[Schema<br/>public]
        OBJ[Objects<br/>tables, views, models, functions]
    end

    subgraph Features["핵심 기능"]
        LIN[자동 Lineage<br/>테이블 + 컬럼 레벨]
        ACC[접근 제어<br/>ANSI SQL GRANT/REVOKE]
        TAG[메타데이터 태깅<br/>분류 + 검색]
        AUD[감사 로그<br/>누가 언제 무엇을]
    end

    UC --> CAT --> SCH --> OBJ
    UC --> LIN & ACC & TAG & AUD

    style UC fill:#fff3e0,stroke:#e65100
    style Namespace fill:#e8f5e9
    style Features fill:#e3f2fd
```

| Unity Catalog 기능 | BIP 대응 |
|-------------------|---------|
| 3-Level Namespace | PostgreSQL: stockdb.public.table |
| 자동 Lineage | OM Lineage (수동 등록 + register_table_lineage) |
| 접근 제어 (GRANT/REVOKE) | PostgreSQL ROLE (미설정) |
| 메타데이터 태깅 | OM Tags (DataLayer, Domain, SourceType) |
| 감사 로그 | 없음 |

#### Genie — NL2SQL

Databricks의 NL2SQL 솔루션. Wren AI와 직접 비교:

| 항목 | Databricks Genie | Wren AI |
|------|-----------------|---------|
| **아키텍처** | Compound AI (멀티 LLM 조합) | 단일 LLM + RAG |
| **메타데이터 활용** | Unity Catalog 자동 연동 | MDL 수동 정의 + OM 동기화 |
| **Thinking Steps** | 해석 과정 투명하게 표시 | 없음 |
| **컬럼 샘플값** | 자동으로 샘플 데이터 참조 | 없음 |
| **Metric Views** | 시맨틱 메트릭 정의 지원 | MDL Calculated Fields |
| **비용** | DBU 종량제 (고가) | 무료 (OSS) + LLM API 비용 |
| **데이터 소스** | Databricks 전용 | 12+ DB 지원 |
| **멀티 쿼리** | ❌ 1개 | ❌ 1개 |

#### Mosaic AI — 에이전트 프레임워크

| 기능 | 설명 | BIP 대응 |
|------|------|---------|
| **Agent Framework** | 프로덕션 에이전트 빌드 | LangGraph |
| **RAG** | 문서 + 테이블 기반 검색 증강 | Qdrant (Wren AI) |
| **Vector Search** | 네이티브 임베딩 인덱스 | Qdrant |
| **Model Serving** | REST API 모델 배포 | 없음 (LLM API 직접 호출) |
| **Guardrails** | AI 출력 안전 장치 | 없음 |
| **MLflow 통합** | 실험 추적 + 모델 레지스트리 | 없음 |

#### Medallion Architecture

Databricks가 공식 권장하는 데이터 레이어 구조 — BIP-Pipeline이 이미 동일 패턴 적용:

```mermaid
graph LR
    subgraph Bronze["Bronze (Raw)"]
        B1[stock_price_1d]
        B2[financial_statements]
        B3[macro_indicators]
        B4[news]
    end

    subgraph Silver["Silver (Derived)"]
        S1[stock_indicators]
        S2[market_daily_summary]
    end

    subgraph Gold["Gold (Serving)"]
        G1[analytics_stock_daily]
        G2[analytics_macro_daily]
        G3[analytics_valuation]
    end

    Bronze --> Silver --> Gold

    style Bronze fill:#cd7f32,color:white
    style Silver fill:#c0c0c0
    style Gold fill:#ffd700
```

| Medallion 레이어 | Databricks | BIP-Pipeline |
|-----------------|-----------|-------------|
| **Bronze** | Raw 수집 (Delta Lake) | Raw 테이블 (stock_info, stock_price_1d, ...) |
| **Silver** | 정제/정규화 | Derived 테이블 (stock_indicators, market_daily_summary) |
| **Gold** | 비즈니스 집계 | analytics_* 테이블 (pre-joined 와이드) |

#### Databricks 가격

| 워크로드 | DBU 단가 (Premium) | 월 예상 비용 |
|---------|-------------------|-----------|
| All-Purpose | $0.55/DBU-hr | $500~$2,000 |
| Jobs | $0.30/DBU-hr | $300~$1,000 |
| Serverless SQL | $0.70/DBU-hr | $500~$3,000 |
| **총 예상** | | **$500~$5,000+/월** |

---

### 14-4. BIP-Pipeline과의 대응 관계 상세

#### 기능별 매핑

```mermaid
graph TB
    subgraph BIP["BIP-Pipeline 구성 요소"]
        direction TB
        AF[Airflow<br/>DAG 오케스트레이션]
        PG[PostgreSQL<br/>데이터 저장]
        OM[OpenMetadata<br/>카탈로그 + Lineage + 용어집]
        WR[Wren AI<br/>MDL + NL2SQL]
        LG[LangGraph<br/>에이전트 오케스트레이션]
        KA[Kafka/Spark<br/>스트리밍 (미사용)]
    end

    subgraph PAL["Palantir 대응"]
        direction TB
        P_PB[Pipeline Builder<br/>+ Code Repos]
        P_ST[Foundry Storage]
        P_ON[Ontology<br/>(카탈로그+시맨틱+액션 통합)]
        P_AI[AIP<br/>(LLM+NL2SQL+에이전트 통합)]
        P_AG[Agent Studio]
        P_MC[Machinery<br/>프로세스 마이닝]
    end

    subgraph DBR["Databricks 대응"]
        direction TB
        D_WF[Workflows]
        D_DL[Delta Lake]
        D_UC[Unity Catalog<br/>+ Metric Views]
        D_GE[Genie<br/>NL2SQL]
        D_MA[Mosaic AI<br/>Agent Framework]
        D_SS[Structured Streaming]
    end

    AF -.-> P_PB -.-> D_WF
    PG -.-> P_ST -.-> D_DL
    OM -.-> P_ON -.-> D_UC
    WR -.-> P_AI -.-> D_GE
    LG -.-> P_AG -.-> D_MA
    KA -.-> P_MC -.-> D_SS

    style BIP fill:#e8f5e9
    style PAL fill:#e3f2fd
    style DBR fill:#fff3e0
```

#### 핵심 차이점

| 관점 | BIP-Pipeline | Palantir | Databricks |
|------|-------------|---------|-----------|
| **비용** | 무료 (서버 비용만) | 수억원/년 | $6,000~$60,000/년 |
| **설치/운영** | 직접 설치/관리 | 완전 관리형 | 관리형 (클라우드) |
| **유연성** | 완전 커스텀 가능 | 제한적 커스텀 | 중간 |
| **스케일** | 단일 서버 | 엔터프라이즈 (수천 사용자) | 엔터프라이즈 |
| **NL2SQL 접근** | Wren AI (시맨틱) + LangGraph (에이전트) 분리 | AIP (통합) | Genie (통합) |
| **온톨로지** | OM Glossary + Tags (제한적) | Ontology (완전한 비즈니스 모델) | Unity Catalog (카탈로그 수준) |
| **에이전트** | LangGraph (직접 구현) | Agent Studio (노코드) | Mosaic AI (SDK) |

#### BIP가 이미 구현한 것 vs 엔터프라이즈 솔루션 대비 미구현

```
✅ BIP 구현 완료 (엔터프라이즈와 동등)
   - Medallion Architecture (Bronze/Silver/Gold)
   - 메타데이터 카탈로그 (OM = Unity Catalog 수준)
   - 데이터 Lineage (API → DAG → Table → Consumer)
   - 시맨틱 레이어 (Wren AI MDL)
   - NL2SQL 기본 (Wren AI + SQL Pairs)
   - 용어집/태그 거버넌스
   - 파이프라인 오케스트레이션 (Airflow)

⚠️ 부분 구현 (기능은 있으나 엔터프라이즈 대비 제한적)
   - Lineage: 수동 등록 (Databricks는 자동)
   - 메타데이터 동기화: DAG로 배치 (Palantir는 실시간)
   - NL2SQL: 1질문=1SQL (Genie/AIP도 동일한 한계)

🔲 미구현 (향후 과제)
   - LLM 에이전트 통합 (LangGraph + Wren AI API)
   - 비즈니스 객체 모델 (Palantir Ontology 수준)
   - Action Types (데이터 변경 워크플로우)
   - ML 모델 라이프사이클 (MLflow)
   - 접근 제어 / 감사 로그
   - 실시간 스트리밍 처리
```

---

### 14-5. 아키텍처 선택 가이드

| 상황 | 추천 |
|------|------|
| **개인/소규모 팀, 비용 최소화** | BIP-Pipeline 방식 (오픈소스 조합) |
| **빠른 PoC, 클라우드 네이티브** | Databricks (종량제, 빠른 설정) |
| **대규모 조직, 운영 의사결정 통합** | Palantir Foundry (온톨로지 + 워크플로우) |
| **데이터 엔지니어링 + ML 중심** | Databricks (Spark + MLflow + Delta Lake) |
| **국방/정부/규제 산업** | Palantir (보안 인증, Gotham) |

### 14-6. BIP-Pipeline 발전 로드맵 — 엔터프라이즈 기능 점진적 도입

```mermaid
timeline
    title BIP-Pipeline 발전 로드맵
    section 현재 (완료)
        Medallion Architecture : Gold Layer 3개 테이블
        메타데이터 카탈로그 : OpenMetadata + 용어집 + Tags
        Lineage : API → DAG → Table → Consumer
        NL2SQL : Wren AI + SQL Pairs 29개
    section 단기
        LangGraph 에이전트 : Wren AI API + OM API 통합
        Calculated Fields : MDL 비즈니스 지표 20개
        SQL Pairs 확대 : 100개 패턴
    section 중기
        FastAPI NL2SQL : Vanna AI 또는 Wren AI API 임베드
        Knowledge Graph : Neo4j 투자 도메인 온톨로지
        ML Pipeline : MLflow 실험 추적
    section 장기
        실시간 분석 : Kafka/Flink 활용
        Action Types : 자동 리밸런싱 워크플로우
        엔터프라이즈 거버넌스 : RBAC + 감사 로그
```

---

*이 문서는 BIP-Pipeline 프로젝트의 Wren AI 설치/운영 경험을 바탕으로 작성되었습니다.*
*Wren AI OSS v0.29.1, Palantir Foundry (2025), Databricks Lakehouse (2025) 기준이며, 버전 업데이트에 따라 내용이 변경될 수 있습니다.*
