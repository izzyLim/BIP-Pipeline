# NL2SQL · 시맨틱 레이어 · 온톨로지: 개념과 구현 가이드

> **작성일:** 2026-03-28
> **목적:** NL2SQL 시스템 설계 학습 자료 — 단순 Text-to-SQL부터 온톨로지 기반 시맨틱 레이어까지
> **기반 프로젝트:** BIP-Pipeline (주식 투자 데이터 파이프라인)

---

## 목차

1. [왜 NL2SQL인가 — 배경과 필요성](#1-왜-nl2sql인가)
2. [Text-to-SQL의 현실 — 정확도와 한계](#2-text-to-sql의-현실)
3. [데이터 레이어 아키텍처 — Medallion Architecture](#3-medallion-architecture)
4. [시맨틱 레이어란 무엇인가](#4-시맨틱-레이어)
5. [온톨로지란 무엇인가](#5-온톨로지)
6. [메타데이터 카탈로그의 역할 — OpenMetadata](#6-메타데이터-카탈로그)
7. [NL2SQL 도구 생태계](#7-nl2sql-도구-생태계)
8. [목표 아키텍처 — 전체 그림](#8-목표-아키텍처)
9. [구현 로드맵](#9-구현-로드맵)
10. [핵심 개념 정리](#10-핵심-개념-정리)

---

## 1. 왜 NL2SQL인가

### 1-1. 기존 데이터 접근의 문제

데이터 분석에는 항상 "SQL을 쓸 수 있는 사람"이 필요했습니다.

```
비즈니스 담당자: "삼성전자 PER이 경쟁사 대비 저평가인가요?"
데이터 엔지니어: (쿼리 작성 → 실행 → 결과 전달)
```

이 과정에서 병목과 정보 비대칭이 생깁니다.

### 1-2. NL2SQL이 해결하려는 것

**NL2SQL(Natural Language to SQL)**은 자연어 질문을 SQL 쿼리로 변환해, 비기술 사용자도 데이터를 직접 조회할 수 있게 합니다.

```
사용자: "삼성전자 최근 3개월 RSI 추이 보여줘"
시스템: SELECT trade_date, rsi14
        FROM stock_indicators
        WHERE ticker = '005930.KS'
          AND trade_date >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY trade_date
```

### 1-3. LLM 등장 이후의 변화

2023년 이전에는 NL2SQL이 학술 연구 수준이었습니다. GPT-4·Claude 같은 대형 언어 모델(LLM)이 등장하면서 실용적 수준의 NL2SQL이 가능해졌습니다.

---

## 2. Text-to-SQL의 현실

### 2-1. 정확도의 착시

| 환경 | 정확도 |
|------|--------|
| 학술 벤치마크 (Spider, WikiSQL) | 85~93% |
| 실제 기업 환경 | **20~50%** |
| 도메인 특화 데이터 (금융, 의료 등) | 더 낮음 |

학술 벤치마크는 단순하고 정리된 스키마를 사용합니다. 실제 환경은 다릅니다.

### 2-2. 왜 실제 환경에서 틀리는가

**문제 1: 단위 혼동**
```sql
-- 사용자: "시총 1조 이상 종목"
-- LLM이 생성한 잘못된 쿼리:
WHERE market_value >= 1000000000000  -- 원 단위로 잘못 해석

-- 정확한 쿼리 (market_value는 억원 단위):
WHERE market_value >= 10000
```

**문제 2: 용어 모호성**
```sql
-- 사용자: "투자의견 좋은 종목"
-- LLM이 생성한 잘못된 쿼리:
WHERE rating = 5  -- 또는 WHERE rating = 1 (높은 게 좋은지 모름)

-- 실제: rating은 1(Sell)~5(Strong Buy), 높을수록 긍정
WHERE rating >= 4
```

**문제 3: 올바른 실행, 틀린 결과**
```sql
-- 사용자: "삼성전자 PER"
-- SQL 문법은 맞지만 계산이 틀린 쿼리:
SELECT market_value / net_income AS per  -- 단위 불일치로 잘못된 값

-- 정확한 쿼리:
SELECT (market_value * 100000000) / net_income AS per
```

### 2-3. 핵심 교훈

> **"SQL이 실행된다"고 "결과가 맞다"는 의미가 아니다.**

단순 Text-to-SQL은 **스키마 구조**만 알고 있습니다. 비즈니스 의미·단위·계산 규칙을 모릅니다. 이것이 시맨틱 레이어가 필요한 이유입니다.

---

## 3. Medallion Architecture

### 3-1. 개념

데이터 레이크하우스에서 널리 사용되는 **3계층 데이터 아키텍처**입니다.

```
Bronze  →  Silver  →  Gold
(원본)     (정제)     (서빙)
```

| 레이어 | 역할 | 특징 |
|--------|------|------|
| **Bronze** | 원본 데이터 그대로 저장 | 수집한 raw 데이터. 변환 없음. |
| **Silver** | 정제·정규화된 데이터 | 중복 제거, 단위 통일, 파생 컬럼 계산 |
| **Gold** | 분석 목적에 최적화 | 여러 테이블을 미리 JOIN. 비즈니스 질문에 즉답 가능 |

### 3-2. BIP-Pipeline에 적용

```
Bronze (원본)
  stock_price_1d      — Yahoo Finance/Naver 수집 원본
  macro_indicators    — VIX·환율·금리 수집 원본
  news                — 뉴스 기사 원본

Silver (파생·정규화)
  stock_indicators    — 기술적 지표 계산 (RSI, MACD, BB 등)
  financial_statements — DART 재무제표 정규화
  consensus_estimates — 애널리스트 추정치 정제

Gold (분석용, 현재 미구현)
  gold_stock_daily    — 시세 + 지표 + 컨센서스 + 재무 통합 뷰
  gold_macro_daily    — 매크로 지표 통합 뷰
```

### 3-3. Gold 레이어의 NL2SQL 이점

Gold 레이어 없이 "삼성전자 RSI와 PER 알려줘":
```sql
-- LLM이 4개 테이블 JOIN을 정확히 알아야 함
SELECT si.stock_name, ind.rsi14, ce.est_per
FROM stock_info si
JOIN stock_indicators ind ON si.ticker = ind.ticker
JOIN consensus_estimates ce ON si.ticker = ce.ticker
WHERE si.ticker = '005930.KS'
  AND ind.trade_date = CURRENT_DATE
  AND ce.estimate_year = 2025
```

Gold 레이어 있으면:
```sql
SELECT stock_name, rsi14, est_per
FROM gold_stock_daily
WHERE ticker = '005930.KS' AND trade_date = CURRENT_DATE
```

---

## 4. 시맨틱 레이어

### 4-1. 개념

**시맨틱 레이어(Semantic Layer)**는 물리적 DB 스키마와 비즈니스 사용자 사이의 **추상화 계층**입니다.

```
비즈니스 사용자          시맨틱 레이어              물리적 DB
─────────────────────────────────────────────────────────────
"시가총액"          →    market_value × 1억    →    stock_info.market_value (억원)
"PER"              →    시가총액 / 당기순이익   →    복수 테이블 계산
"대형주"           →    시총 1조 이상          →    market_value >= 10000
"골든크로스 종목"  →    golden_cross = TRUE    →    stock_indicators.golden_cross
```

### 4-2. 시맨틱 레이어가 정의하는 것

| 구성요소 | 설명 | 예시 |
|----------|------|------|
| **메트릭(Metric)** | 계산 로직이 있는 비즈니스 지표 | PER = 시총 / 순이익 |
| **디멘션(Dimension)** | 분류·필터 기준 | 시장(KOSPI/NASDAQ), 섹터, 대형주 여부 |
| **관계(Relationship)** | 테이블 간 JOIN 조건 | stock_info.ticker = stock_indicators.ticker |
| **필터(Filter)** | 자주 쓰는 조건 | 활성 종목 = is_active = TRUE |
| **단위(Unit)** | 값의 단위 정의 | market_value: 억원, revenue: 원(KRW) |

### 4-3. 시맨틱 레이어 예시 (YAML 형식, Wren AI 스타일)

```yaml
models:
  - name: stock_overview
    description: "종목 기본 정보 + 시세 + 기술적 지표 통합 뷰"

    relationships:
      - name: stock_to_indicators
        from: stock_info
        to: stock_indicators
        join_type: LEFT
        condition: "stock_info.ticker = stock_indicators.ticker"

    calculated_fields:
      - name: market_cap_krw
        label: "시가총액 (원)"
        expression: "market_value * 100000000"
        description: "market_value(억원) × 1억 = 원 단위 환산"

      - name: per_actual
        label: "실제 PER"
        expression: "market_cap_krw / net_income"
        description: "시가총액(원) / 당기순이익(원). 재무제표 최신 연간 기준"

    dimensions:
      - name: is_large_cap
        label: "대형주 여부"
        expression: "market_value >= 10000"
        description: "시가총액 1조원 이상"

      - name: is_golden_cross
        label: "골든크로스 종목"
        expression: "golden_cross = TRUE"

metrics:
  - name: avg_per_by_sector
    label: "섹터별 평균 PER"
    expression: "AVG(per_actual)"
    dimensions: ["sector"]
```

### 4-4. 시맨틱 레이어의 NL2SQL 개선 효과

```
질문: "반도체 섹터에서 PER 저평가된 대형주는?"

시맨틱 레이어 없이:
  LLM이 알아야 할 것들 —
    - PER 계산식 (시총 단위 변환 포함)
    - "반도체 섹터" = sector 컬럼의 어떤 값?
    - "대형주" = market_value 몇 이상?
    - "저평가" = 절대값? 상대값?

시맨틱 레이어 있으면:
  SELECT * FROM stock_overview
  WHERE sector = '반도체'
    AND is_large_cap = TRUE
    AND per_actual < (SELECT AVG(per_actual) * 0.8
                      FROM stock_overview WHERE sector = '반도체')
```

---

## 5. 온톨로지

### 5-1. 시맨틱 레이어와의 차이

| | 시맨틱 레이어 | 온톨로지 |
|---|--------------|---------|
| **초점** | 계산·집계·JOIN 규칙 | 개념 간 관계·분류 체계 |
| **질문** | "PER을 어떻게 계산하나?" | "삼성전자는 어떤 개념에 속하나?" |
| **표현** | YAML, SQL, 수식 | RDF/OWL, 지식 그래프, 트리 구조 |
| **예시** | PER = 시총/순이익 | 삼성전자 → isA → 반도체주 → isA → 대형주 |

### 5-2. 온톨로지란

**온톨로지(Ontology)**는 특정 도메인의 **개념과 관계를 형식화한 지식 체계**입니다. 철학의 "존재론"에서 유래했으며, 컴퓨터 과학에서는 기계가 이해할 수 있는 지식 표현 방법을 의미합니다.

### 5-3. 투자 도메인 온톨로지 예시

```
[주식] ─── isA ──→ [금융상품]
  │
  ├── [한국주식] ─── listedOn ──→ [KOSPI]
  │     │                          [KOSDAQ]
  │     └── [삼성전자] ─── belongsTo ──→ [반도체 섹터]
  │                    ─── isA ──────→ [대형주]
  │                    ─── isA ──────→ [수출주]
  │
  └── [미국주식] ─── listedOn ──→ [NASDAQ]
                                   [NYSE]

[투자지표]
  ├── [밸류에이션 지표]
  │     ├── [PER] ─── calculatedFrom ──→ [시가총액], [당기순이익]
  │     ├── [PBR] ─── calculatedFrom ──→ [시가총액], [자본총계]
  │     └── [EV/EBITDA]
  │
  └── [기술적 지표]
        ├── [추세 지표] ── includes ──→ [이동평균], [MACD]
        └── [모멘텀 지표] ─ includes ──→ [RSI], [스토캐스틱]

[투자 스타일]
  ├── [가치투자] ─── focuses_on ──→ [밸류에이션 지표]
  │                ─── targets ───→ [저PER주], [저PBR주]
  └── [성장투자] ─── focuses_on ──→ [매출성장률], [영업이익률]
```

### 5-4. 온톨로지가 NL2SQL에 가져오는 것

**1단계 (현재):** 단순 키워드 매핑
```
"삼성전자" → ticker = '005930.KS'
```

**2단계 (시맨틱 레이어):** 계산 규칙 적용
```
"저PER" → per_actual < 업종 평균 * 0.8
```

**3단계 (온톨로지):** 개념 추론
```
"가치주 중 반도체 관련주" →
  가치주 = PER < 15 AND PBR < 1.5
  반도체 관련주 = 직접 반도체 섹터 OR 반도체 장비 OR 반도체 소재
  → 온톨로지에서 "반도체 관련" 개념의 하위 분류 전체 포함
```

---

## 6. 메타데이터 카탈로그

### 6-1. OpenMetadata의 역할

**OpenMetadata**는 데이터 자산을 중앙에서 관리하는 오픈소스 메타데이터 카탈로그입니다.

```
OpenMetadata가 관리하는 것:
  ├── 테이블 설명 (어떤 데이터를 저장하는가)
  ├── 컬럼 설명 (각 컬럼의 의미·단위)
  ├── Lineage (데이터 흐름 — 어디서 와서 어디로 가는가)
  ├── FK 관계 (테이블 간 연결 구조)
  ├── 프로파일러 통계 (데이터 분포, NULL 비율)
  ├── 태그 & 분류 (PII, 재무, 운영 등)
  └── Glossary (비즈니스 용어 정의)
```

### 6-2. NL2SQL과 메타데이터 카탈로그의 연계

```python
# NL2SQL 시스템이 OM API에서 컨텍스트를 가져오는 예시
def get_schema_context(tables: list) -> str:
    """OM API에서 테이블·컬럼 설명을 가져와 LLM 프롬프트 컨텍스트 생성"""
    context = []
    for table in tables:
        fqn = f"bip-postgres.stockdb.public.{table}"
        table_data = om_client.get_table(fqn)

        context.append(f"테이블: {table}")
        context.append(f"설명: {table_data['description']}")
        context.append("컬럼:")
        for col in table_data['columns']:
            context.append(f"  - {col['name']}: {col['description']}")

    return "\n".join(context)

# LLM 프롬프트에 컨텍스트 주입
prompt = f"""
다음 DB 스키마를 기반으로 SQL을 작성하세요.

{get_schema_context(['stock_info', 'stock_indicators', 'consensus_estimates'])}

질문: {user_question}
"""
```

### 6-3. Glossary — 온톨로지의 시작점

OM의 **Glossary 기능**은 비즈니스 용어와 DB 컬럼을 연결합니다.

```
Glossary Term: "대형주"
  정의: 시가총액 1조원(market_value ≥ 10,000 억원) 이상인 상장 종목
  연결 컬럼: stock_info.market_value
  관련 용어: 중형주, 소형주, KOSPI200

Glossary Term: "컨센서스 매수"
  정의: 애널리스트 투자의견 점수(rating)가 4.0 이상인 종목
  연결 컬럼: consensus_estimates.rating
  주의: rating은 1(Sell)~5(Strong Buy). 높을수록 긍정적.
```

이것이 체계화되면 **온톨로지의 기초**가 됩니다.

---

## 7. NL2SQL 도구 생태계

### 7-1. 도구 유형 분류

```
┌─────────────────────────────────────────────────────────┐
│                     NL2SQL 도구 유형                      │
├─────────────────┬───────────────────────────────────────┤
│  라이브러리     │  Vanna.ai, LangChain, LlamaIndex       │
│  (코드 통합용)  │  직접 import해서 사용                  │
├─────────────────┼───────────────────────────────────────┤
│  완성형 앱      │  Wren AI, Chat2DB, DB-GPT              │
│  (설치형 UI)    │  Docker로 설치, 브라우저로 사용        │
├─────────────────┼───────────────────────────────────────┤
│  클라우드 서비스│  Snowflake Cortex, BigQuery Gemini     │
│  (관리형)       │  클라우드 종속, 별도 설치 불필요       │
└─────────────────┴───────────────────────────────────────┘
```

### 7-2. 주요 도구 상세 비교

#### Vanna.ai
- **방식:** RAG(Retrieval-Augmented Generation) 기반
- **동작 원리:**
  ```
  지식 베이스 구축 → DDL + 컬럼 설명 + 과거 쿼리 예시 저장
       ↓
  질문 입력 → 관련 스키마/예시 검색 → LLM에 컨텍스트 주입 → SQL 생성
  ```
- **장점:** 커스터마이징 자유, 도메인 특화 쿼리 예시 학습 가능
- **단점:** UI 없음, 별도 서버 구축 필요
- **라이선스:** MIT
- **적합한 경우:** 개발자가 직접 통합하는 백엔드 서비스

#### Wren AI
- **방식:** 시맨틱 엔진 + NL2SQL
- **동작 원리:**
  ```
  YAML 시맨틱 모델 정의 → 비즈니스 메트릭·관계·계산식 등록
       ↓
  질문 → 시맨틱 레이어 참조 → 정확한 SQL 생성 → 결과 + 차트
  ```
- **장점:** 시맨틱 레이어 내장, MCP 지원, Docker 설치, 차트 생성
- **단점:** 시맨틱 모델 초기 구축 작업 필요
- **라이선스:** Apache 2.0
- **적합한 경우:** 팀 전체가 쓰는 데이터 포털, 시맨틱 레이어 중심 설계

#### Chat2DB
- **방식:** IDE 스타일 SQL 도구 + AI 보조
- **특징:** 24개 DB 지원, SQL 자동완성, 자연어 쿼리, 시각화
- **라이선스:** Apache 2.0
- **적합한 경우:** 개발자/분석가 개인 생산성 도구

#### DB-GPT
- **방식:** 완전 로컬 LLM 지원 (Ollama 연동)
- **특징:** 외부 API 없이 사내 폐쇄망 운영, 데이터 외부 유출 없음
- **라이선스:** MIT
- **적합한 경우:** 보안이 중요한 금융/의료 기관 사내망

#### LangChain / LlamaIndex
- **방식:** LLM 오케스트레이션 프레임워크
- **특징:** NL2SQL은 기능 중 하나. 에이전트·파이프라인 전체 구축에 사용
- **라이선스:** MIT
- **적합한 경우:** NL2SQL + 에이전트 + 자동화를 통합 개발

### 7-3. 선택 기준 정리

```
단순히 빨리 써보고 싶다          →  Chat2DB (설치 5분)
백엔드 서비스에 통합             →  Vanna.ai
시맨틱 레이어까지 구축           →  Wren AI
완전 사내망 (API 키 불가)        →  DB-GPT
에이전트·자동화까지 포함         →  LangChain + Vanna.ai
장기적 아키텍처 (온톨로지 포함)  →  Wren AI + OM Glossary
```

---

## 8. 목표 아키텍처

### 8-1. 전체 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                          사용자 인터페이스                        │
│              Chat UI (React)  /  모닝 브리핑 이메일              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                        Agent Layer                               │
│          Claude API Tool Use — 알림·리포팅·자동화 에이전트       │
│    tools: [DB 조회, Airflow 트리거, 이메일 발송, 알림 전송]      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                      NL2SQL Layer                                │
│                        Wren AI                                   │
│              시맨틱 레이어 + 온톨로지 + SQL 생성                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    Semantic Layer (Wren Engine)                  │
│   메트릭 정의    │  관계(JOIN) 정의  │  비즈니스 용어 매핑       │
│   PER, PBR...   │  stock_info→...   │  대형주, 가치주, 성장주    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   Metadata Catalog (OpenMetadata)                │
│   테이블/컬럼 설명  │  Lineage  │  Glossary  │  FK 관계         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                     Data Layer (PostgreSQL)                      │
│  Bronze: stock_price_1d/1m, macro_indicators, news, financial_statements  │
│  Silver: stock_indicators, market_daily_summary, consensus_estimates     │
│  Gold:   analytics_macro_daily, analytics_stock_daily, analytics_valuation │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   Pipeline (Airflow 22개 DAG)                    │
│     수집 → 정제 → 지표 계산 → Lineage 자동 등록 → OM 반영       │
└─────────────────────────────────────────────────────────────────┘
```

### 8-2. 질문 처리 흐름 예시

```
사용자: "반도체 대형주 중 골든크로스 발생하고 PER이 업종 평균보다 낮은 종목은?"

Step 1. Agent가 의도 파악
        → NL2SQL 쿼리 유형으로 분류

Step 2. Wren AI 시맨틱 레이어 참조
        → "반도체 대형주" = sector='IT' AND industry_name LIKE '%반도체%'
                            AND market_value >= 10000
        → "골든크로스" = golden_cross = TRUE (stock_indicators)
        → "PER 업종 평균보다 낮음" = per_actual < sector_avg_per

Step 3. 온톨로지 참조 (확장 단계)
        → "반도체 관련주" 개념 = 직접 반도체 + 장비 + 소재 + 후공정 포함

Step 4. SQL 생성 및 실행
        SELECT stock_name, per_actual, rsi14, golden_cross
        FROM gold_stock_daily
        WHERE is_semiconductor_related = TRUE
          AND is_large_cap = TRUE
          AND golden_cross = TRUE
          AND per_actual < sector_avg_per
        ORDER BY per_actual ASC

Step 5. 결과 + 해석 반환
        → "총 5개 종목 발견. 삼성전자(PER 12.3, 업종 평균 대비 -23%)..."
```

### 8-3. 레이어별 구현 기술 스택

| 레이어 | 기술 | 상태 |
|--------|------|------|
| **데이터 파이프라인** | Airflow + PostgreSQL | ✅ 운영 중 |
| **메타데이터 카탈로그** | OpenMetadata v1.12.3 | ✅ 구축 완료 |
| **테이블/컬럼 설명** | OM API 일괄 등록 | ✅ 완료 (35개 테이블) |
| **Lineage** | utils/lineage.py 자동 등록 | ✅ 완료 (22개 DAG) |
| **FK 관계** | 물리적 FK 12개 + OM 논리적 FK | ✅ 완료 (1wk/1mo 삭제로 14→12개) |
| **Glossary (온톨로지 기초)** | OM Glossary | ✅ 완료 — 77개 용어 등록 |
| **컬럼-용어 매핑** | om_link_columns.py, om_enrich_metadata.py | ✅ 완료 |
| **Tags 분류 (Layer/Domain)** | OM Tags | ✅ 완료 — 37개 테이블 DataLayer/Domain 태그 적용 |
| **Gold Layer 테이블** | PostgreSQL + Airflow DAG | ✅ 완료 — analytics_macro_daily, analytics_stock_daily, analytics_valuation |
| **시맨틱 레이어** | Wren AI | 🔲 미시작 |
| **NL2SQL** | Wren AI + LLM | 🔲 미시작 |
| **에이전트 (모닝리포트)** | bip-agents (LangGraph + FastMCP) | 🟡 진행 중 (별도 repo) |
| **Chat UI** | React (기존 BIP-React 확장) | 🔲 미시작 |

---

## 9. 구현 로드맵

### Phase 1: 메타데이터 완성 ✅ 완료 (2026-03-28)
```
✅ OpenMetadata 설치 및 구성
✅ 35개 테이블 수집 (ingestion)
✅ 테이블/컬럼 설명 등록 (35개 테이블, om_enrich_metadata.py)
✅ Lineage 자동 등록 (22개 DAG 전체 — register_table_lineage_async)
✅ 물리적 FK 추가 (12개, stock_price_1wk/1mo DROP으로 14→12)
✅ OM Glossary 구축 완료 (77개 용어 — om_build_glossary.py)
✅ 컬럼-용어 매핑 완료 (om_link_columns.py, om_enrich_metadata.py)
✅ 불필요 테이블 정리 — stock_price_1wk/1mo DROP (1d resample 대체)
✅ Tags 분류 체계 (raw/derived/gold, domain 분류) — 37개 테이블 완료 (2026-03-29)
```

### Phase 2: Gold Layer + 시맨틱 레이어 구축
```
✅ analytics_macro_daily — macro_indicators EAV pivot, 437행 적재 완료 (DAG: 09_analytics_macro_daily)
✅ analytics_stock_daily — 시세 + 기술지표 + 컨센서스 와이드 테이블 (DAG: 09_analytics_stock_daily)
✅ analytics_valuation   — PER/PBR/ROE pre-computed, 7,609행 적재 완료 (DAG: 09_analytics_valuation)
✅ Tags 분류 체계 등록 (OM — 37개 테이블 DataLayer/Domain 태그 완료)
🔲 Wren AI 설치 (Docker Compose)
🔲 핵심 메트릭 정의 (PER, PBR, ROE, 배당수익률 등 20개)
🔲 비즈니스 디멘션 정의 (대형주, 가치주, 성장주, 섹터 분류)
🔲 테이블 관계 정의 (JOIN 경로 시맨틱 모델로 전환)
🔲 NL2SQL 테스트 쿼리 30개 작성 및 정확도 검증
```

### Phase 3: 온톨로지 고도화
```
🔲 투자 도메인 개념 체계 설계 (주식 분류 트리)
🔲 OM Glossary와 Wren AI 시맨틱 모델 연동
🔲 개념 간 관계 정의 (isA, partOf, calculatedFrom 등)
🔲 Knowledge Graph 구축 (선택적: Neo4j)
```

### Phase 4: NL2SQL + 에이전트 통합
```
🔲 Wren AI API를 FastAPI에 연동
🔲 Claude API Tool Use로 에이전트 구현
    - DB 조회 tool
    - Airflow DAG 트리거 tool
    - 이메일/알림 발송 tool
🔲 Chat UI 구현 (기존 BIP-React 확장)
🔲 모닝 브리핑 에이전트 고도화
```

---

## 10. 핵심 개념 정리

### 용어 사전

| 용어 | 정의 |
|------|------|
| **NL2SQL** | 자연어(Natural Language)를 SQL 쿼리로 변환하는 기술 |
| **Text-to-SQL** | NL2SQL과 동의어. LLM 기반 구현이 주류 |
| **RAG** | Retrieval-Augmented Generation. 검색된 문서를 LLM 프롬프트에 주입해 답변 정확도 향상 |
| **시맨틱 레이어** | DB와 사용자 사이의 비즈니스 의미 추상화 계층. 메트릭·디멘션·관계 정의 |
| **온톨로지** | 특정 도메인의 개념과 관계를 형식화한 지식 체계 |
| **Medallion Architecture** | Bronze→Silver→Gold 3단계 데이터 레이어 아키텍처 |
| **EAV 패턴** | Entity-Attribute-Value. `macro_indicators`처럼 (날짜, 유형, 값) 구조로 유연하게 지표 확장 |
| **Lineage** | 데이터 흐름 추적. 어떤 테이블이 어디서 왔고 어디에 쓰이는지 |
| **메타데이터 카탈로그** | 데이터 자산의 스키마·설명·lineage·태그를 중앙 관리하는 시스템 |
| **MCP** | Model Context Protocol. AI 에이전트가 외부 데이터/도구에 접근하는 표준 프로토콜 |
| **Tool Use** | LLM이 외부 함수(도구)를 호출할 수 있는 기능. Claude/GPT-4 모두 지원 |

### NL2SQL 정확도 향상 핵심 요소

```
1. 스키마 문서화        → 컬럼 설명, 단위, 값 범위 (OM에 완료)
2. 비즈니스 용어 정의   → Glossary, 시맨틱 레이어
3. 쿼리 예시 학습       → Vanna.ai 방식 (few-shot)
4. 검증 레이어          → 생성된 SQL의 문법·의미 검증
5. 피드백 루프          → 틀린 쿼리를 수정하여 재학습
```

### 실제 구현 시 주의사항

> **"SQL이 실행된다"고 "결과가 맞다"는 의미가 아니다.**

- 단위 변환 오류는 SQL이 성공해도 잘못된 결과를 반환
- 비즈니스 용어 모호성은 컬럼 설명만으로 해결 안 됨 → 시맨틱 레이어 필요
- 학술 벤치마크 정확도를 실제 도메인 데이터에 그대로 기대하면 안 됨
- 복잡한 분석 쿼리일수록 Gold 레이어 또는 시맨틱 레이어가 없으면 LLM이 틀릴 가능성 높음

---

*이 문서는 BIP-Pipeline 프로젝트의 실제 구현 경험을 바탕으로 작성되었습니다.*
*NL2SQL·시맨틱 레이어·온톨로지는 독립적인 개념이지만, 실용적인 시스템에서는 함께 설계해야 최대 효과를 냅니다.*
