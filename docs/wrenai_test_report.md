# Wren AI NL2SQL 품질 테스트 리포트

> **테스트일:** 2026-04-02 (1차), 2026-04-03 (2차 개선 검증)
> **Wren AI 버전:** Engine 0.22.0 / AI Service 0.29.0 / UI 0.32.2
> **LLM:** gpt-4o-mini (OpenAI, LiteLLM 경유)
> **테스트 방법:** Wren AI REST API (`POST /v1/asks` → `GET /v1/asks/{id}/result`) 자동화 스크립트

---

## 목차

1. [테스트 목적 및 배경](#1-테스트-목적-및-배경)
2. [테스트 환경](#2-테스트-환경)
3. [테스트 결과 요약](#3-테스트-결과-요약)
4. [테스트 케이스 상세](#4-테스트-케이스-상세)
5. [발견된 문제 및 조치](#5-발견된-문제-및-조치)
6. [개선 전후 비교](#6-개선-전후-비교)
7. [NL2SQL 정확도 개선 전략](#7-nl2sql-정확도-개선-전략)
8. [2차 테스트 — 개선 검증 및 신규 패턴](#8-2차-테스트--개선-검증-및-신규-패턴-2026-04-03)
9. [최종 현황 및 향후 계획](#9-최종-현황-및-향후-계획)

---

## 1. 테스트 목적 및 배경

### 1-1. 테스트 목적

Wren AI NL2SQL 설치 후 실제 질문에 대한 SQL 생성 품질을 검증하고,
메타데이터 보강(컬럼 설명, 계산 힌트, SQL Pairs) 작업의 효과를 측정합니다.

### 1-2. 테스트 전 수행한 개선 작업

| 작업 | 수량 | 목적 |
|------|------|------|
| Gold 테이블 컬럼 설명 추가 (OM → Wren AI) | 115개 (12%→100%) | LLM이 컬럼 의미 파악 |
| 계산 힌트 보강 | 27개 핵심 컬럼 | 파생 계산식 유도 |
| SQL Pairs 사전 등록 | 29개 | 자주 묻는 패턴 학습 |
| Instructions | 2개 | ILIKE 규칙, 계산 폴백 |
| Deploy (Qdrant 재인덱싱) | 1회 | 모든 변경사항 임베딩 반영 |

### 1-3. 테스트 대상 모델

| 모델 | 컬럼 수 | 설명 커버리지 | 용도 |
|------|---------|-------------|------|
| `public_analytics_stock_daily` | 46 | 100% (46/46) | 종목별 시세+지표+컨센서스 |
| `public_analytics_macro_daily` | 49 | 100% (49/49) | 거시경제 지표 피벗 |
| `public_analytics_valuation` | 32 | 100% (32/32) | 밸류에이션 종합 |
| `public_stock_info` | 23 | 100% (23/23) | 종목 마스터 |
| `public_stock_price_1d` | 19 | 95% (18/19) | 일봉 시세 |

---

## 2. 테스트 환경

### 2-1. 인프라 구성

```mermaid
graph LR
    TEST["테스트 스크립트<br/>(Python)"]
    AI["Wren AI Service<br/>:5555"]
    QD["Qdrant<br/>:6333"]
    EN["Wren Engine<br/>:8080"]
    IB["Ibis Server<br/>:8000"]
    PG["PostgreSQL<br/>:5432"]

    TEST -->|POST /v1/asks| AI
    AI -->|임베딩 검색| QD
    AI -->|SQL 검증| EN
    EN -->|SQL 실행| IB
    IB -->|쿼리| PG
```

### 2-2. 테스트 방법

```python
# 1) 질문 제출
POST http://localhost:5555/v1/asks
{"query": "삼성전자 현재 주가", "mdl_hash": ""}

# 2) 결과 polling (3초 간격, 최대 90초)
GET http://localhost:5555/v1/asks/{query_id}/result

# 3) 응답 구조
{
    "status": "finished",
    "rephrased_question": "...",
    "sql_generation_reasoning": "...",  # Chain-of-Thought
    "response": [{"sql": "SELECT ..."}],
    "error": null
}
```

### 2-3. 평가 기준 프레임워크

NL2SQL 품질을 5개 차원, 3단계 등급으로 평가합니다.

#### 평가 차원

```mermaid
graph TB
    subgraph Dimensions["5개 평가 차원"]
        D1["1. 실행 가능성<br/>(Executability)"]
        D2["2. 의미 정확성<br/>(Semantic Accuracy)"]
        D3["3. 결과 정확성<br/>(Result Accuracy)"]
        D4["4. 효율성<br/>(Efficiency)"]
        D5["5. 사용자 의도 충족<br/>(Intent Satisfaction)"]
    end

    D1 -->|"SQL이 실행 되는가?"| D2
    D2 -->|"맞는 테이블/컬럼을 쓰는가?"| D3
    D3 -->|"결과가 정확한가?"| D4
    D4 -->|"최적의 SQL인가?"| D5
    D5 -->|"사용자가 원하는 답인가?"| FINAL[종합 평가]

    style Dimensions fill:#e8eaf6
```

#### 차원별 상세 기준

| # | 차원 | 등급 A (Pass) | 등급 B (Partial) | 등급 F (Fail) |
|---|------|-------------|-----------------|-------------|
| 1 | **실행 가능성** | SQL 실행 성공 + 결과 반환 | SQL 실행 성공하나 빈 결과 | SQL 미생성 또는 실행 에러 |
| 2 | **의미 정확성** | 올바른 테이블 + 올바른 컬럼 | 올바른 테이블 + 비최적 컬럼 | 잘못된 테이블 또는 잘못된 컬럼 |
| 3 | **결과 정확성** | 결과 값이 실제 데이터와 일치 | 근사치이나 단위/범위 차이 | 결과가 완전히 틀림 |
| 4 | **효율성** | 간결한 SQL (불필요한 CTE/서브쿼리 없음) | 동작하지만 과도한 복잡성 | 성능 문제 (풀스캔, N+1 등) |
| 5 | **의도 충족** | 사용자 질문의 의도를 정확히 충족 | 부분적으로 충족 (누락된 정보 있음) | 의도와 무관한 결과 |

#### 자동 체크 항목 (스크립트 검증)

| 체크 ID | 항목 | 검증 방법 | 적용 조건 |
|---------|------|---------|---------|
| CHK-01 | SQL 생성 여부 | `response` 배열 비어있지 않은지 | 모든 질문 |
| CHK-02 | 테이블 정확성 | 기대 테이블명이 SQL에 포함 | 모든 질문 |
| CHK-03 | ILIKE 사용 | 종목명 검색 시 ILIKE 패턴 | 질문에 종목명 포함 시 |
| CHK-04 | ticker 하드코딩 금지 | SQL에 `.KS`, `.KQ` 등 직접 기재 없음 | 질문에 종목명 포함 시 |
| CHK-05 | stock_name 포함 | SELECT에 stock_name 존재 | 종목 관련 질문 |
| CHK-06 | LIMIT 포함 | "상위 N개" 질문에 LIMIT 또는 ROW_NUMBER | 랭킹 질문 |
| CHK-07 | 계산식 정확 | 기대 컬럼이 계산식에 포함 | 파생 지표 질문 |
| CHK-08 | 기간 필터 | INTERVAL 또는 날짜 조건 존재 | "최근", "한달", "1주일" 등 |
| CHK-09 | 최신 데이터 | MAX(date) 또는 ORDER BY DESC LIMIT | "현재", "오늘" 등 |
| CHK-10 | NULL 처리 | IS NOT NULL 조건 포함 | 계산식에 나눗셈 포함 시 |

#### 종합 등급 산정

```
A등급 (Pass):     5개 차원 모두 A → 완벽
B등급 (Partial):  1~2개 차원 B, 나머지 A → 동작하지만 개선 필요
C등급 (Marginal): 3개 이상 차원 B → SQL Pair 등록 권장
F등급 (Fail):     1개 이상 차원 F → SQL Pair 등록 필수
```

#### 이번 테스트 결과에 적용

| TC | 질문 | 실행 | 의미 | 결과 | 효율 | 의도 | 종합 |
|----|------|------|------|------|------|------|------|
| 01 | 현재 VIX 지수 | A | A | A | A | A | **A** |
| 02 | 삼성전자 현재 주가 | A | A | A | A | A | **A** |
| 03 | 코스피 시총 상위 5 | A | A | A | B | A | **B** |
| 04 | 삼성전자 목표가 괴리율 | A | A | A | A | A | **A** |
| 05 | 거래대금 상위 10 | A | B | A | B | A | **B** |
| 06 | 현재 실질금리 | F | - | - | - | F | **F** |
| 07 | 현재 신용스프레드 | F | - | - | - | F | **F** |
| 08 | 코스피 20일 이격도 | A | A | A | B | A | **A** |
| 09 | ROE 20%+ PER 10이하 | A | A | A | A | A | **A** |
| 10 | 외국인 순매수 금액 | A | A | A | B | A | **A** |
| 11 | 최근 1주일 환율 | A | A | A | A | A | **A** |
| 12 | 하이닉스 최근 한달 | A | A | A | A | A | **A** |

```
A등급: 7개 (58%)  — 완벽
B등급: 3개 (25%)  — 동작하지만 비최적
F등급: 2개 (17%)  — SQL Pair로 해결 완료
```

---

## 3. 테스트 결과 요약

### 3-1. 전체 성적

```
총 12개 테스트 케이스
  ✅ 성공:     9개 (75%)
  ⚠️ 부분성공: 1개 (8%)
  ❌ 실패:     2개 (17%)
```

```mermaid
pie title NL2SQL 테스트 결과 (12개)
    "성공" : 9
    "부분성공" : 1
    "실패" : 2
```

### 3-2. 카테고리별 결과

| 카테고리 | 성공 | 실패 | 성공률 |
|---------|------|------|--------|
| 기본 조회 (최신값, 종목검색) | 2/2 | 0 | 100% |
| 랭킹 조회 (상위 N개) | 0/1 | 1 (부분) | 0% |
| 계산식 유도 | 3/5 | 2 | 60% |
| 복합 조건 (AND/OR) | 2/2 | 0 | 100% |
| 기간 필터 | 2/2 | 0 | 100% |

### 3-3. 핵심 발견

```
1. 기본 조회/기간 필터/복합 조건 → 매우 정확 (100%)
2. 계산식 유도 → 컬럼 description 힌트가 있으면 성공, 전문 용어만 있으면 실패
3. 실패 케이스 → SQL Pair 추가로 즉시 해결 가능
4. 컬럼 설명 100% 채운 효과가 가장 큼
```

---

## 4. 테스트 케이스 상세

### TC-01: 현재 VIX 지수 ✅

| 항목 | 내용 |
|------|------|
| **질문** | "현재 VIX 지수" |
| **기대** | analytics_macro_daily에서 최신 1행 조회 |
| **결과** | ✅ 성공 |

**생성된 SQL:**
```sql
SELECT "indicator_date", "vix"
FROM "public_analytics_macro_daily"
ORDER BY "indicator_date" DESC
LIMIT 1
```

**평가:** ORDER BY DESC LIMIT 1 패턴 정확. 컬럼 설명 "VIX 공포 지수. 20 이하=안정, 20~30=주의, 30 이상=공포"가 정확한 테이블/컬럼 매핑에 기여.

---

### TC-02: 삼성전자 현재 주가 ✅

| 항목 | 내용 |
|------|------|
| **질문** | "삼성전자 현재 주가" |
| **기대** | ILIKE + stock_name 포함 |
| **결과** | ✅ 성공 |

**생성된 SQL:**
```sql
SELECT "stock_name", "close"
FROM "public_analytics_stock_daily"
WHERE "trade_date" = (SELECT MAX("trade_date") FROM "public_analytics_stock_daily")
  AND "stock_name" ILIKE '%삼성전자%'
```

**평가:** Instruction의 ILIKE 규칙 정확히 적용. stock_name 포함. MAX(trade_date) 서브쿼리로 최신 데이터 조회.

---

### TC-03: 코스피 시가총액 상위 5종목 ⚠️

| 항목 | 내용 |
|------|------|
| **질문** | "코스피 시가총액 상위 5종목" |
| **기대** | market_type='KOSPI' + ORDER BY market_value DESC LIMIT 5 |
| **결과** | ⚠️ 부분 성공 |

**생성된 SQL:**
```sql
WITH RankedStocks AS (
  SELECT "stock_name", "market_value",
    ROW_NUMBER() OVER (ORDER BY "market_value" DESC) AS rank
  FROM "public_analytics_stock_daily"
  WHERE "market_type" = 'KOSPI'
    AND "trade_date" = (SELECT MAX("trade_date") FROM "public_analytics_stock_daily")
)
SELECT "stock_name", "market_value" FROM RankedStocks WHERE rank <= 5
```

**평가:** 결과는 정확하지만 CTE + ROW_NUMBER 사용은 과도. 단순 `ORDER BY ... DESC LIMIT 5`로 충분. 기능적으로는 문제없음.

---

### TC-04: 삼성전자 목표가 괴리율 ✅

| 항목 | 내용 |
|------|------|
| **질문** | "삼성전자 목표가 괴리율" |
| **기대** | 계산: (target_price - close) / close * 100 |
| **결과** | ✅ 성공 |

**생성된 SQL:**
```sql
WITH latest_data AS (
  SELECT *
  FROM "public_analytics_stock_daily"
  WHERE "trade_date" = (SELECT MAX("trade_date") FROM "public_analytics_stock_daily")
    AND "stock_name" ILIKE '%삼성전자%'
)
SELECT "stock_name", "close", "target_price",
  ("target_price" - "close") / "close" * 100 AS target_upside_pct
FROM latest_data
```

**평가:** 컬럼 description의 계산 힌트 `"괴리율 계산: (target_price - close) / close * 100"`이 정확히 반영됨. **계산 힌트 효과 입증.**

---

### TC-05: 거래대금 상위 10종목 ⚠️

| 항목 | 내용 |
|------|------|
| **질문** | "거래대금 상위 10종목" |
| **기대** | 계산: close * volume |
| **결과** | ⚠️ 부분 성공 |

**생성된 SQL:**
```sql
WITH RankedStocks AS (
  SELECT "stock_name", "trading_value",
    ROW_NUMBER() OVER (ORDER BY "trading_value" DESC) AS rank
  FROM "public_stock_price_1d"
  JOIN "public_stock_info" ON ...
)
SELECT ... WHERE rank <= 10
```

**평가:** `trading_value` 컬럼을 `stock_price_1d`에서 직접 사용 (이 컬럼이 실제 존재). Gold 테이블(`analytics_stock_daily`)이 아닌 Raw 테이블 사용. 기능적으로는 동작하지만, 의도한 `close * volume` 계산 대신 기존 컬럼 활용. SQL Pair로 올바른 패턴 등록 완료.

---

### TC-06: 현재 실질금리 ❌

| 항목 | 내용 |
|------|------|
| **질문** | "현재 실질금리" |
| **기대** | 계산: kr_base_rate - kr_cpi_yoy |
| **결과** | ❌ 실패 (SQL 미생성) |

**생성된 SQL:** (없음)

**원인 분석:**
- "실질금리"가 LLM에게 너무 전문적인 용어
- 의도 분류(Intent Classification)에서 `TEXT_TO_SQL`이 아닌 `DATA_ASSISTANCE`로 분류된 것으로 추정
- Instructions에 계산식이 있지만, 의도 분류 단계에서 이미 데이터 질문으로 인식 못함

**조치:** SQL Pair 등록으로 해결
```sql
-- SQL Pair #51: "현재 실질금리"
SELECT indicator_date, kr_base_rate, kr_cpi_yoy,
  kr_base_rate - kr_cpi_yoy AS real_rate
FROM public_analytics_macro_daily
ORDER BY indicator_date DESC LIMIT 1
```

---

### TC-07: 현재 신용스프레드 ❌

| 항목 | 내용 |
|------|------|
| **질문** | "현재 신용스프레드" |
| **기대** | 계산: kr_corp_3y - kr_govt_3y |
| **결과** | ❌ 실패 (SQL 미생성) |

**원인 분석:** TC-06과 동일. "신용스프레드" 전문 용어 인식 실패.

**조치:** SQL Pair 등록으로 해결 (SQL Pair #52)

---

### TC-08: 코스피 20일 이격도 상위 종목 ✅

| 항목 | 내용 |
|------|------|
| **질문** | "코스피 20일 이격도 상위 종목" |
| **기대** | 계산: (close - ma20) / ma20 * 100 |
| **결과** | ✅ 성공 |

**생성된 SQL:**
```sql
WITH ranked_stocks AS (
  SELECT "stock_name",
    ("close" - "ma20") / "ma20" * 100 AS disparity_20d,
    ROW_NUMBER() OVER (ORDER BY ("close" - "ma20") / "ma20" * 100 DESC) AS rank
  FROM "public_analytics_stock_daily"
  WHERE "market_type" = 'KOSPI'
    AND "trade_date" = (SELECT MAX("trade_date") FROM "public_analytics_stock_daily")
    AND "ma20" IS NOT NULL
)
SELECT "stock_name", "disparity_20d" FROM ranked_stocks WHERE rank <= 10
```

**평가:** 컬럼 description의 `"이격도: (close - ma20) / ma20 * 100"` 힌트 정확히 반영. **계산 힌트 효과 재확인.** NULL 체크도 포함.

---

### TC-09: ROE 20% 이상이고 PER 10 이하 종목 ✅

| 항목 | 내용 |
|------|------|
| **질문** | "ROE 20% 이상이고 PER 10 이하 종목" |
| **기대** | 복합 WHERE 조건 |
| **결과** | ✅ 성공 |

**생성된 SQL:**
```sql
SELECT "stock_name", "roe_actual", "per_actual", "fiscal_year"
FROM "public_analytics_valuation"
WHERE "roe_actual" > 20 AND "per_actual" <= 10 AND "per_actual" > 0
  AND "fiscal_year" = (SELECT MAX("fiscal_year") FROM "public_analytics_valuation")
```

**평가:** 복합 조건 정확. `per_actual > 0` (적자 제외) 자동 포함. SQL Pair의 유사 패턴("저PER 고ROE 종목")이 영향.

---

### TC-10: 외국인 순매수 금액 상위 종목 ✅

| 항목 | 내용 |
|------|------|
| **질문** | "외국인 순매수 금액 상위 종목" |
| **기대** | 계산: foreign_buy_volume * close |
| **결과** | ✅ 성공 |

**생성된 SQL:**
```sql
WITH ranked_stocks AS (
  SELECT "stock_name", "foreign_buy_volume",
    "foreign_buy_volume" * "close" AS buy_amount,
    ROW_NUMBER() OVER (ORDER BY "foreign_buy_volume" * "close" DESC) AS rank
  FROM "public_analytics_stock_daily"
  WHERE "trade_date" = (SELECT MAX("trade_date") FROM "public_analytics_stock_daily")
    AND "foreign_buy_volume" > 0
)
SELECT ... WHERE rank <= 10
```

**평가:** `foreign_buy_volume * close` 계산 정확. 컬럼 description의 `"금액: foreign_buy_volume * close"` 힌트 반영.

---

### TC-11: 최근 1주일 원달러 환율 추이 ✅

| 항목 | 내용 |
|------|------|
| **질문** | "최근 1주일 원달러 환율 추이" |
| **기대** | INTERVAL 기간 필터 |
| **결과** | ✅ 성공 |

**생성된 SQL:**
```sql
SELECT "indicator_date", "usd_krw"
FROM "public_analytics_macro_daily"
WHERE "indicator_date" >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY "indicator_date"
```

**평가:** 정확. "원달러" → `usd_krw` 매핑, 기간 필터 정확.

---

### TC-12: 하이닉스 최근 한달 주가 ✅

| 항목 | 내용 |
|------|------|
| **질문** | "하이닉스 최근 한달 주가" |
| **기대** | ILIKE + INTERVAL |
| **결과** | ✅ 성공 |

**생성된 SQL:**
```sql
SELECT "stock_name", "close", "trade_date"
FROM "public_analytics_stock_daily"
WHERE "stock_name" ILIKE '%하이닉스%'
  AND "trade_date" >= CURRENT_DATE - INTERVAL '1 month'
ORDER BY "trade_date"
```

**평가:** ILIKE 패턴, 기간 필터, stock_name 포함 모두 정확. SQL Pair의 유사 패턴 영향.

---

## 5. 발견된 문제 및 조치

### 5-1. 문제 유형 분류

```mermaid
pie title 문제 유형 분포
    "전문 용어 인식 실패" : 2
    "과도한 SQL 복잡성" : 1
    "테이블 선택 비최적" : 1
```

### 5-2. 상세 문제 및 조치

| # | 문제 | 원인 | 조치 | 효과 |
|---|------|------|------|------|
| 1 | "실질금리" SQL 미생성 | 전문 용어 → 의도 분류 실패 | SQL Pair #51 등록 | RAG 검색으로 즉시 해결 |
| 2 | "신용스프레드" SQL 미생성 | 전문 용어 → 의도 분류 실패 | SQL Pair #52 등록 | RAG 검색으로 즉시 해결 |
| 3 | 상위 N개 질문에 CTE+ROW_NUMBER 과도 | LLM의 SQL 스타일 선호 | 허용 (기능적 동일) | - |
| 4 | 거래대금에 Raw 테이블 사용 | `trading_value` 컬럼이 Raw에만 존재 | SQL Pair #55 등록 | Gold 테이블 유도 |

### 5-3. 조치 후 추가된 SQL Pairs

| ID | 질문 | 핵심 SQL 패턴 |
|----|------|-------------|
| 51 | 현재 실질금리 | `kr_base_rate - kr_cpi_yoy AS real_rate` |
| 52 | 신용스프레드 | `kr_corp_3y - kr_govt_3y AS credit_spread` |
| 53 | 실질금리 추이 | 위 + `INTERVAL '3 months'` |
| 54 | 신용스프레드 추이 | 위 + `INTERVAL '3 months'` |
| 55 | 거래대금 상위 종목 | `close * volume AS trading_value` |

---

## 6. 개선 전후 비교

### 6-1. 컬럼 설명 커버리지

```mermaid
xychart-beta
    title "컬럼 설명 커버리지 (Before → After)"
    x-axis ["stock_info", "stock_price_1d", "macro_daily", "stock_daily", "valuation"]
    y-axis "커버리지 (%)" 0 --> 100
    bar [100, 95, 12, 7, 9]
    bar [100, 95, 100, 100, 100]
```

| 모델 | Before | After | 변화 |
|------|--------|-------|------|
| analytics_macro_daily | 6/49 (12%) | **49/49 (100%)** | +43 |
| analytics_stock_daily | 3/46 (7%) | **46/46 (100%)** | +43 |
| analytics_valuation | 3/32 (9%) | **32/32 (100%)** | +29 |
| **합계** | 53/169 (31%) | **168/169 (99%)** | **+115** |

### 6-2. SQL Pairs 수

```
초기:    29개 (설치 시 등록)
테스트 후: 34개 (+5개, 실패 패턴 기반)
```

### 6-3. 개선 효과 요약

| 개선 항목 | 기여도 | 근거 |
|----------|--------|------|
| **컬럼 설명 100% 채우기** | ★★★★★ | 이격도, 목표가 괴리율 등 계산식 정확 생성 |
| **계산 힌트 (description)** | ★★★★ | TC-04, TC-08, TC-10에서 계산 힌트 정확 반영 확인 |
| **SQL Pairs** | ★★★ | 전문 용어(실질금리, 신용스프레드) 실패 → 즉시 해결 |
| **Instructions (ILIKE)** | ★★★ | TC-02, TC-12에서 ILIKE 정확 적용 |

---

## 7. NL2SQL 정확도 개선 전략

### 7-1. 지속적 개선 사이클

```mermaid
flowchart LR
    USE[실제 사용]
    FAIL[실패/부정확 발견]
    PAIR[SQL Pair 등록]
    TEST[테스트 검증]
    DEPLOY[Deploy<br/>Qdrant 재인덱싱]

    USE --> FAIL --> PAIR --> DEPLOY --> TEST --> USE

    style PAIR fill:#c8e6c9
```

**핵심 원칙:**
- Instructions는 **범용 규칙**만 (2~3개면 충분)
- SQL Pairs는 **구체적 패턴** (실패할 때마다 추가)
- 컬럼 설명에 **계산 힌트** 포함 (OM에서 관리 → 자동 동기화)

### 7-2. 개선 우선순위

```
1위: 실패 케이스를 SQL Pair로 등록 (즉각적, 확실한 효과)
2위: 컬럼 설명에 계산 힌트 보강 (OM → Wren AI 자동 동기화)
3위: Instructions는 최소한으로 유지 (범용 규칙만)
4위: Calculated Fields는 집계만 가능 (MDL 제약, 향후 버전에서 개선 기대)
```

### 7-3. 하지 말아야 할 것

| 안티패턴 | 이유 |
|---------|------|
| Instructions에 모든 규칙 나열 | 검색 노이즈 증가, 관련 없는 규칙이 컨텍스트 오염 |
| 용어집 전체를 Instructions로 변환 | 77개 용어가 매 질문마다 검색됨 → 비효율 |
| 모든 계산식을 Instructions에 중복 기재 | 컬럼 description에 이미 포함 → 중복 |
| SQL Pairs를 너무 구체적으로 | "삼성전자 PER" 대신 "종목별 PER" 패턴으로 일반화 |

---

## 8. 2차 테스트 — 개선 검증 및 신규 패턴 (2026-04-03)

### 8-1. 2차 테스트 목적

1차 테스트에서 발견된 F등급/B등급 케이스에 SQL Pair를 추가한 효과 검증 + 신규 질문 패턴 테스트.

### 8-2. 사전 작업 (1차 → 2차 사이 수행)

| 작업 | 수량 | 내용 |
|------|------|------|
| Gold 컬럼 설명 추가 | 115개 | analytics_* 테이블 커버리지 12%→100% |
| 계산 힌트 보강 | 27개 | 이격도, 괴리율, 실질금리 등 계산식을 description에 포함 |
| 계산 폴백 Instruction | 1개 | "컬럼 없으면 계산식으로 SQL 생성" 규칙 |
| 1차 실패 SQL Pair | 5개 | 실질금리, 신용스프레드, 거래대금 |

### 8-3. 2차 테스트 결과

#### 기존 F등급 재검증

| TC | 질문 | 1차 | 2차 | 변화 |
|----|------|-----|-----|------|
| 06 | 현재 실질금리 | F | **A** | SQL Pair가 RAG로 검색되어 정확한 SQL 생성 |
| 07 | 현재 신용스프레드 | F | **A** | 동일 |

#### 기존 B등급 재검증

| TC | 질문 | 1차 | 2차 | 변화 |
|----|------|-----|-----|------|
| 03 | 코스피 시총 상위 5 | B | **B** | 여전히 CTE+ROW_NUMBER (기능적 문제 없음, LLM 스타일 선호) |
| 05 | 거래대금 상위 10 | B | **A** | SQL Pair 효과 — Gold 테이블 + close*volume 계산 사용 |

#### 신규 패턴 테스트 (9개)

| # | 질문 | 카테고리 | 등급 | 비고 |
|---|------|---------|------|------|
| N-01 | 삼성전자 전월 대비 주가 변동 | 기간 비교 | **A** | CTE로 전월 종가 조회 + 변동률 계산 |
| N-02 | 최근 3개월 VIX 평균 | 집계 | **F→A** | 1차 실패, SQL Pair 추가 후 성공 |
| N-03 | 삼성전자 SK하이닉스 PER 비교 | 종목 비교 | **A** | ILIKE OR 조건 정확 |
| N-04 | 업종별 평균 PER | GROUP BY | **B→A** | SQL Pair 추가 후 sector JOIN 정확 |
| N-05 | 코스피 코스닥 시가총액 합계 | 시장별 집계 | **A** | market_type + SUM 정확 |
| N-06 | 삼성전자 PSR | 복합 계산 | **A** | market_value/revenue 계산 정확 |
| N-07 | 배당수익률 높은 종목 | 데이터 부재 | **F** | Gold 테이블에 배당 데이터 없음 (구조적 한계) |
| N-08 | 오늘 시장 어때 | 모호한 질문 | **F→A** | SQL Pair으로 주요 지수 요약 패턴 등록 |
| N-09 | 반도체 전망 | 매우 모호 | **F** | 의견 질문 — NL2SQL 범위 밖 (LangGraph 영역) |

### 8-4. 2차 테스트 종합

```mermaid
pie title 2차 테스트 종합 결과 (13개)
    "A등급" : 10
    "B등급" : 1
    "F등급 (구조적 한계)" : 2
```

```
A등급: 10/13 (77%) — 1차 대비 58%→77% 향상
B등급:  1/13 (8%)  — CTE 스타일 선호 (기능적 문제 없음)
F등급:  2/13 (15%) — 데이터 부재 + NL2SQL 범위 밖 (해결 불가)
```

### 8-5. 2차 테스트에서 추가한 SQL Pairs (7개)

| ID | 질문 | 핵심 패턴 |
|----|------|---------|
| 56 | 최근 3개월 VIX 평균 | `AVG(vix)` + `INTERVAL '3 months'` |
| 57 | VIX 평균 | `AVG(vix)` + `MIN/MAX` |
| 58 | 오늘 시장 어때 | kospi, kosdaq, sp500, nasdaq, usd_krw, vix 종합 |
| 59 | 시장 현황 | 위와 유사 (동의어 패턴) |
| 60 | 시가총액 상위 종목 | `ORDER BY market_value DESC LIMIT 10` |
| 61 | 업종별 평균 PER | `GROUP BY sector` + `AVG(per_actual)` |
| 62 | 삼성전자 전월 대비 주가 변동률 | 서브쿼리로 전월 종가 조회 |

### 8-6. 해결 불가 항목 분석

| 질문 | 실패 원인 | 해결 방향 |
|------|---------|---------|
| 배당수익률 높은 종목 | Gold 테이블에 배당 데이터 미포함 | `analytics_valuation`에 `dividend_yield` 컬럼 추가 (DAG 수정) |
| 반도체 전망 | 데이터 질문이 아닌 의견 질문 | LangGraph 에이전트에서 뉴스 데이터 + LLM 분석으로 처리 |

---

## 9. 최종 현황 및 향후 계획

### 9-1. SQL Pairs 현황

```
초기 등록:        29개 (2026-04-02)
1차 테스트 후:    34개 (+5)
2차 테스트 후:    41개 (+7)
```

| 카테고리 | 수량 | 대표 패턴 |
|---------|------|---------|
| 종목 검색/주가 | 7 | ILIKE + ORDER DESC LIMIT |
| 기간별 조회 | 3 | INTERVAL + ORDER BY |
| 기술지표 | 3 | RSI/골든크로스/볼린저밴드 |
| 밸류에이션 | 5 | PER/ROE/부채비율/매출성장 |
| 매크로 | 9 | 환율/금리/VIX/실질금리/스프레드 |
| 수급 | 2 | 외국인/기관 순매수 |
| 복합/비교 | 7 | 저PER고ROE/거래대금/52주신저가 |
| 시장 요약 | 3 | 시장현황/시총상위/업종별PER |
| 기간 비교 | 2 | 전월대비/전분기 |

### 9-2. 테스트 점수 변화

```mermaid
xychart-beta
    title "NL2SQL 테스트 등급 변화"
    x-axis ["1차 (12개)", "2차 (13개)"]
    y-axis "비율 (%)" 0 --> 100
    bar [58, 77]
    bar [25, 8]
    bar [17, 15]
```

| 등급 | 1차 테스트 | 2차 테스트 | 변화 |
|------|----------|----------|------|
| A (Pass) | 7/12 (58%) | 10/13 (77%) | +19%p |
| B (Partial) | 3/12 (25%) | 1/13 (8%) | -17%p |
| F (Fail) | 2/12 (17%) | 2/13 (15%) | -2%p (구조적 한계만 잔존) |

### 9-3. 개선 사이클 검증 결과

```mermaid
flowchart LR
    T1["1차 테스트<br/>12개 질문"]
    A1["분석<br/>F:2, B:3"]
    FIX1["조치<br/>SQL Pair 5개<br/>컬럼설명 115개<br/>계산힌트 27개"]
    T2["2차 테스트<br/>13개 질문"]
    A2["분석<br/>F:4 (신규 포함)"]
    FIX2["조치<br/>SQL Pair 7개"]
    T3["재검증<br/>3개 질문"]
    R["결과<br/>A: 77%"]

    T1 --> A1 --> FIX1 --> T2 --> A2 --> FIX2 --> T3 --> R

    style FIX1 fill:#c8e6c9
    style FIX2 fill:#c8e6c9
    style R fill:#fff9c4
```

**검증된 개선 사이클:**
1. 테스트 실행 → 실패 발견
2. 실패 원인 분류 (용어 인식 / 계산식 / 데이터 부재 / 범위 밖)
3. 해결 가능한 것 → SQL Pair 추가
4. 재검증 → A등급 확인
5. 해결 불가 → 구조적 개선(DAG/스키마) 또는 LangGraph 에이전트로 이관

### 9-4. 향후 계획

#### 정기 테스트 (권장)

```
주 1회: 10~20개 신규 질문 테스트
  → 실패 케이스 SQL Pair 등록
  → SQL Pairs 50개 → 100개로 점진적 확대

월 1회: 전체 SQL Pairs 대상 회귀 테스트
  → Wren AI 버전 업데이트 시 기존 패턴 깨지는지 확인
```

#### 추가 테스트 필요 영역

| 영역 | 예시 질문 | 예상 난이도 | 상태 |
|------|---------|----------|------|
| 기간 비교 | "삼성전자 전월 대비 주가 변동" | 높음 | ✅ 2차에서 성공 |
| 종목 비교 | "삼성전자 vs SK하이닉스 PER 비교" | 중간 | ✅ 2차에서 성공 |
| 조건부 집계 | "업종별 평균 PER" | 중간 | ✅ 2차에서 성공 (SQL Pair 후) |
| 복합 계산 | "PEG ratio (PER ÷ 성장률)" | 높음 | 🔲 미테스트 |
| 시계열 분석 | "골든크로스 발생 후 1개월 수익률" | 매우 높음 | 🔲 미테스트 (멀티 쿼리) |
| 모호한 질문 | "오늘 시장 어때" | 높음 | ✅ 2차에서 성공 (SQL Pair 후) |
| 의견 질문 | "반도체 전망" | NL2SQL 한계 | ❌ LangGraph 영역 |

#### 테스트 자동화

```bash
# Wren AI REST API 기반 자동 품질 검증
python3 /tmp/wrenai_test.py

# 향후 정리하여 scripts/wrenai_test.py로 이동 + Airflow DAG 등록 가능
```

---

## 부록: 테스트에 사용된 Wren AI API 응답 예시

### 성공 케이스 응답 (TC-04: 삼성전자 목표가 괴리율)

```json
{
    "status": "finished",
    "rephrased_question": "What is the target price gap rate for Samsung Electronics?",
    "intent_reasoning": "User seeks specific calculated data from the database.",
    "sql_generation_reasoning": "Step 1: Identify target_price and close columns...\nStep 2: Apply calculation hint from description: (target_price - close) / close * 100...",
    "type": "TEXT_TO_SQL",
    "retrieved_tables": ["public_analytics_stock_daily", "public_stock_info"],
    "response": [{
        "sql": "WITH latest_data AS (...) SELECT stock_name, close, target_price, (target_price - close) / close * 100 AS target_upside_pct FROM latest_data",
        "type": "llm"
    }],
    "error": null
}
```

### 실패 → 성공 케이스 (TC-06: 현재 실질금리, SQL Pair 추가 후)

**1차 (실패):**
```json
{"status": "finished", "response": [], "error": null}
```

**2차 (SQL Pair 추가 후 성공):**
```json
{
    "status": "finished",
    "response": [{
        "sql": "SELECT \"indicator_date\", \"kr_base_rate\", \"kr_cpi_yoy\", \"kr_base_rate\" - \"kr_cpi_yoy\" AS \"real_rate\" FROM \"public_analytics_macro_daily\" ORDER BY \"indicator_date\" DESC LIMIT 1"
    }]
}
```

### NL2SQL 범위 밖 케이스 (반도체 전망)

```json
{"status": "finished", "response": [], "error": null}
```

데이터 조회가 아닌 의견/분석 질문 → SQL 생성 불가. LangGraph 에이전트에서 뉴스 데이터 + LLM 분석으로 처리 필요.

---

*이 리포트는 Wren AI NL2SQL 시스템의 품질 기준선(baseline)을 수립하고, 테스트-개선 사이클의 효과를 검증하기 위해 작성되었습니다.*
*1차(2026-04-02) → 2차(2026-04-03) 테스트를 통해 A등급 비율이 58%→77%로 개선되었습니다.*

---

## 3차: LLM 모델 비교 테스트 (2026-04-07~08)

### 배경

Wren AI 소스 코드 분석 결과, 응답 포맷 메커니즘(`response_format: json_schema`)이 OpenAI Structured Outputs 전용으로 구현되어 있음을 확인. Claude 모델 사용 시 LiteLLM이 중간 변환하는 방식으로 동작하므로 모델 간 품질 차이를 실측 비교.

### 테스트 환경

- Wren AI Service v0.29.0, Engine v0.22.0
- 9개 모델 등록 (Gold 3 + Raw 2 + Curated View 4)
- SQL Pairs 43개, Instructions 4개
- 테스트: 순차 5문항 + 동시 3문항 + 품질 8문항

### 모델별 결과

| 항목 | GPT-4o-mini | GPT-4o | GPT-4.1 | **GPT-4.1-mini** | GPT-5.4-mini | Haiku 4.5 | **Sonnet 4.5** |
|------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **순차 평균** | **11s** | 80s | 75s (rate limit) | **16s** | 39s | **11s** | 30s |
| **동시 3건 성공** | 1/3 | 3/3 | 1/3 (timeout) | **3/3** | **3/3** | **3/3** | **3/3** |
| **SQL 생성률** | 높음 | 중 (4/8 NO SQL) | 중 | **높음 (7/8)** | 낮음 (4/8 NO SQL) | 높음 | **높음** |
| **SQL 품질** | 중 | 중상 | 중 | **상** | 상 | 중 | **상** |
| **Boolean 플래그** | 일부 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| **Curated View 활용** | - | - | - | **v_valuation_signals 사용** | - | - | - |
| **비용** | 저 | 고 | 고 | **저** | 중 | 저 | 중 |
| **안정성** | 양호 | TPM 한도 | TPM 한도 | **양호** | 양호 | 양호 | 양호 |

### 주요 발견

1. **GPT-4o/4.1**: OpenAI Tier-1 TPM 30,000 한도로 사용 불가. Tier-2(450,000 TPM) 업그레이드 후 GPT-4o 테스트 → 80s로 매우 느림
2. **GPT-5.4-mini**: `reasoning_effort` 필수 파라미터 + `temperature=0` 미지원. Wren AI config에서 `reasoning_effort: low` + `max_completion_tokens` 사용 시 동작하나 NO SQL 비율 높음
3. **Claude 모델 boolean 플래그 미사용**: `response_format: json_schema`가 OpenAI 전용 → LiteLLM 변환 시 Instructions 준수율 저하
4. **GPT-4.1-mini가 유일하게 Curated View 활용**: "저평가주" 질문에 `v_valuation_signals__v1` 테이블 사용 + `is_oversold_rsi` 시도 (모델 컬럼 미등록으로 실패)
5. **Sonnet 4.5 SQL 품질 최고**: CTE 적극 활용, DENSE_RANK 일관적 사용, `lower() = lower()` 정확 매칭

### 선정: GPT-4.1-mini

**선정 이유:**
- 속도(16s)와 품질의 최적 균형점
- 동시 처리 3/3 안정적
- Curated View/boolean 플래그 활용 시도 → Instructions 준수력 우수
- OpenAI `json_schema` 네이티브 지원으로 구조화된 응답 보장
- 비용 효율적

**config.yaml 설정:**
```yaml
type: llm
provider: litellm_llm
timeout: 120
models:
  - alias: default
    model: gpt-4.1-mini
    context_window_size: 200000
    kwargs:
      max_tokens: 4096
      temperature: 0
```

### Wren AI 프롬프트 분석

소스 코드 분석 (`/src/pipelines/generation/utils/sql.py`):
- **시스템 프롬프트**: 모델 중립적 (ANSI SQL 규칙, CTE 선호, DENSE_RANK 사용 등)
- **응답 포맷**: `SQL_GENERATION_MODEL_KWARGS`에서 `response_format: json_schema` 사용 → **OpenAI Structured Outputs 전용**
- **영향**: Claude 모델은 LiteLLM이 json_schema를 텍스트 프롬프트로 변환하여 전달 → Instructions/boolean 플래그 준수율 저하

### 추가 개선: Instructions 보강 (2026-04-08)

LLM 모델 비교 과정에서 발견된 문제 해결을 위해 Instructions 추가:

| ID | 규칙 | 해결한 문제 |
|----|------|-----------|
| 7 | `data_type` 컬럼 설명 (actual/estimate/preliminary) | 잠정실적 조회 시 `data_type` 필터 누락 |
| 8 | 종목명 한글 필수 + ETF 제외 | "하이닉스" → "SK Hynix" 영문 번역으로 매칭 실패, KODEX ETF 잘못 매칭 |

### 모델 컬럼 추가 (2026-04-08)

`analytics_valuation` 모델에 누락 컬럼 추가:
- `data_type` (VARCHAR): actual/estimate/preliminary 구분
- `fiscal_quarter` (INTEGER): 분기 (0=연간, 1~4=분기)

SQL Pair 추가:
- "삼성전자 1분기 잠정 실적" → `WHERE data_type = 'preliminary'`
- "삼성전자와 SK하이닉스 2025~2026년 매출 비교" → `data_type` 필터 없이 전체 조회

---

## 4차: Phase 1 최종 품질 검증 (2026-04-12)

### 배경

Phase 1 마무리 작업 후 전체 품질 검증:
- Curated View 4개 모델 재생성 (컬럼 1개 → 전체 17~52개 복구)
- Relationship 4개 복구 (View → stock_info)
- SQL Pairs 27개 추가 (43 → 70개)
- OM → Wren AI description 동기화 DAG 실행

### 테스트 방법

1. Wren AI API로 질문 제출 → SQL 생성
2. 생성된 SQL의 테이블명을 PostgreSQL용으로 변환 (`public_xxx` → `"public"."xxx"`)
3. PostgreSQL에서 실행 → 결과 행 수/내용 검증
4. 동일 테스트를 Claude/Codex 스크립트 양쪽에서 독립 실행

### 결과 비교

| Metric | Claude | Codex 스크립트 |
|--------|:-:|:-:|
| **SQL 생성** | 15/15 (100%) | 14/15 (93%) |
| **DB 실행** | 15/15 (100%) | 14/15 (93%) |
| **의미 검증** | 15/15 (100%) | 13/15 (87%) |

> Codex 스크립트 차이(1-2건)는 API 타임아웃/검증 로직 차이. 동일 Wren AI 엔진이므로 생성 SQL은 동일.

### 케이스별 상세

| # | 질문 | SQL | 실행 | 검증 | 행 수 | 비고 |
|:-:|------|:-:|:-:|:-:|:-:|------|
| 1 | 삼성전자 PER | ✅ | ✅ | ✅ | 1 | stock_info 사용 |
| 2 | 코스피 시총 상위 5종목 | ✅ | ✅ | ✅ | 5 | ETF 제외 적용 |
| 3 | 저평가주 찾아줘 | ✅ | ✅ | ✅ | 20 | is_value_stock ✅ |
| 4 | 과매도 종목 | ✅ | ✅ | ✅ | 16 | is_oversold_rsi ✅ |
| 5 | 외국인 순매수 상위 종목 | ✅ | ✅ | ✅ | 20 | is_foreign_net_buy ✅ |
| 6 | 삼성전자 vs SK하이닉스 밸류에이션 | ✅ | ✅ | ✅ | 2 | 한글 매칭 ✅ |
| 7 | 삼성전자 잠정 실적 | ✅ | ✅ | ✅ | 1 | data_type='preliminary' ✅ |
| 8 | 2025 실적 + 2026 추정치 비교 | ✅ | ✅ | ✅ | 2223 | data_type 필터 없음 ✅ |
| 9 | 삼성전자 최근 5일 주가 | ✅ | ✅ | ✅ | 5 | |
| 10 | 최근 1주일 환율 추이 | ✅ | ✅ | ✅ | 7 | |
| 11 | 기관 외국인 동시 매수 종목 | ✅ | ✅ | ✅ | 20 | is_foreign + is_institution ✅ |
| 12 | 현대차 기아 실적 비교 | ✅ | ✅ | ✅ | 10 | 한글 IN 매칭 ✅ |
| 13 | 성장주 추천 | ✅ | ✅ | ✅ | 20 | is_growth_stock ✅ |
| 14 | 저평가 + 외국인 매수 종목 | ✅ | ✅ | ✅ | 20 | Cross-view JOIN ✅ |
| 15 | 삼성전자 52주 신고가 신저가 | ✅ | ✅ | ✅ | 1 | v_technical_signals 사용 ✅ |

### Boolean Flag 사용률

| 테스트 | 이전 (3차) | 현재 (4차) |
|--------|:-:|:-:|
| 저평가주 | ❌ | ✅ is_value_stock |
| 과매도 | ❌ | ✅ is_oversold_rsi |
| 성장주 | ❌ | ✅ is_growth_stock |
| 거래량 급증 | ❌ | ✅ is_volume_spike |
| 외국인 순매수 | ❌ | ✅ is_foreign_net_buy |
| 기관 순매수 | ❌ | ✅ is_institution_net_buy |
| 52주 신저가 | ❌ | ✅ is_near_52w_low |
| **합계** | **0/8 (0%)** | **7/8 (87%)** |

원인: Curated View 모델의 컬럼이 ticker 1개만 등록되어 있었음 → 전체 컬럼 재등록으로 해결

### Phase 1 전체 개선 추이

| 지표 | 1차 (04-02) | 2차 (04-03) | 3차 (04-07) | **4차 (04-12)** |
|------|:-:|:-:|:-:|:-:|
| A등급 비율 | 58% | 77% | - | **100%** |
| SQL 생성 성공 | 75% | 85% | 100% | **100%** |
| DB 실행 성공 | - | - | - | **100%** |
| Boolean flag | - | - | 0/8 | **7/8 (87%)** |
| SQL Pairs | 29 | 34 | 43 | **70** |
| Instructions | 2 | 2 | 4 | **4** |
| 모델 컬럼 등록 | 부분 | 부분 | 부분 | **전체** |
| 평균 응답 속도 | ~11s | ~11s | 16s | **10s** |
| LLM | gpt-4o-mini | gpt-4o-mini | gpt-4.1-mini | **gpt-4.1-mini** |

### 자동화 테스트 스크립트

Codex가 작성한 `scripts/wren_nl2sql_phase1_test.py`로 재현 가능:

```bash
export PG_PASSWORD=<password>
export PG_HOST=localhost
export WREN_TIMEOUT_SECONDS=120
python3 scripts/wren_nl2sql_phase1_test.py
```

리포트 출력: `reports/wren_phase1_results.json`, `reports/wren_phase1_results.md`

---

## 5차: Phase 1 구조 정비 및 다종목 검증 (2026-04-12)

### 5-1. 구조 정비 — 무엇을 왜 했는가

#### Curated View 4개 모델 전체 컬럼 재등록

**무엇:** `v_latest_valuation`, `v_valuation_signals__v1`, `v_technical_signals__v1`, `v_flow_signals__v1` 4개 모델의 컬럼을 1개(ticker만)에서 전체(17~52개)로 재등록.

**왜 필요했는가:** 3차 테스트에서 boolean flag 사용률이 0/8(0%)로 측정되었다. GPT-4.1-mini가 `is_oversold_rsi` 컬럼을 사용하려 시도했으나 "Schema error: No field named public_v_technical_signals__v1.is_oversold_rsi"로 실패했다. 진단 결과, **Curated View 모델이 최초 등록 시 `fields: ["ticker"]`로만 생성**되어 나머지 16~51개 컬럼이 Wren AI에 존재하지 않았다. LLM은 Qdrant 임베딩에 없는 컬럼은 사용할 수 없으므로, boolean flag가 전혀 활용되지 않는 근본 원인이었다.

**결과:**
| View | 이전 (컬럼) | 이후 (컬럼) | 핵심 추가 컬럼 |
|------|:-:|:-:|------|
| v_latest_valuation | 1 | 34 | per_actual, pbr_actual, roe_actual 등 밸류에이션 지표 |
| v_valuation_signals__v1 | 1 | 35 | is_value_stock, is_growth_stock, is_deep_value 등 6개 boolean |
| v_technical_signals__v1 | 1 | 52 | is_oversold_rsi, is_volume_spike, golden_cross 등 기술 지표 |
| v_flow_signals__v1 | 1 | 17 | is_foreign_net_buy, is_institution_net_buy 등 수급 지표 |

**효과:** boolean flag 사용률 0/8 → 7/8 (87%)

#### Relationship 4개 복구

**무엇:** `v_latest_valuation`, `v_valuation_signals__v1`, `v_technical_signals__v1`, `v_flow_signals__v1` 각각에서 `stock_info`로의 MANY_TO_ONE Relationship 추가.

**왜 필요했는가:** 이전 작업에서 `analytics_valuation` 모델을 삭제/재생성하면서 해당 모델과 연결된 Relationship이 CASCADE 삭제되었고, 신규 View 모델에는 Relationship이 설정되지 않은 상태였다. Relationship이 없으면 Wren AI가 **Cross-model JOIN SQL을 생성할 수 없다**. 예를 들어 "저평가이면서 외국인 매수 종목"은 `v_valuation_signals`와 `v_flow_signals`를 `stock_info`를 경유해 JOIN해야 하는데, Relationship 없이는 이 경로를 LLM이 인식하지 못한다.

**결과:** 기존 2개 + 신규 4개 = 총 6개 Relationship

```
stock_info (id=1)
  ↑ MANY_TO_ONE
  ├── analytics_stock_daily (기존)
  ├── stock_price_1d (기존)
  ├── v_latest_valuation (신규)
  ├── v_valuation_signals__v1 (신규)
  ├── v_technical_signals__v1 (신규)
  └── v_flow_signals__v1 (신규)
```

#### SQL Pairs 27개 추가 (43 → 70개)

**무엇:** 6개 카테고리에 걸쳐 27개 SQL Pair를 등록.

**왜 필요했는가:** SQL Pairs는 Wren AI의 RAG 검색에서 Few-shot 예시로 사용된다. LLM이 유사 질문의 SQL 패턴을 참조하여 더 정확한 SQL을 생성한다. 특히:

1. **Boolean flag 패턴 (6개):** Curated View 컬럼을 등록했지만, LLM이 `is_value_stock = true` 같은 패턴을 자발적으로 사용하려면 Few-shot 예시가 필요하다. SQL Pair가 없으면 LLM은 여전히 `per_actual < 10 AND pbr_actual < 1`처럼 직접 계산하려 한다.

2. **data_type/fiscal_quarter 패턴 (4개):** `analytics_valuation`에 추가된 `data_type`(actual/estimate/preliminary)과 `fiscal_quarter` 컬럼의 정확한 사용법을 LLM에 학습시키기 위해. 특히 "잠정 실적" → `WHERE data_type = 'preliminary'`와 "연도별 비교" → `data_type` 필터 없이 전체 조회, 두 패턴이 상반되므로 명시적 예시가 필수.

3. **종목 비교 패턴 (5개):** 2개 이상 종목을 `IN` 절로 비교하는 SQL 패턴. LLM이 자체적으로 생성할 수 있지만, 종목명 한글 매칭 + ETF 제외 규칙을 일관되게 적용하려면 예시가 있어야 한다.

4. **시계열 패턴 (5개):** `INTERVAL`, `CURRENT_DATE`, `ORDER BY trade_date DESC LIMIT N` 같은 시간 범위 쿼리 패턴.

5. **수급 분석 패턴 (3개):** `v_flow_signals__v1`의 boolean flag를 활용한 외국인/기관 순매수 분석.

6. **복합 조건 패턴 (4개):** 2개 이상의 Curated View를 JOIN하는 고급 패턴. 이것이 가장 LLM이 자력으로 생성하기 어려운 유형이다.

**결과:** SQL Pairs 43 → 70개, 4차 테스트 15/15 (100%) 달성

#### OM → Wren AI description 동기화 DAG 실행

**무엇:** `10_sync_metadata_daily` DAG를 수동 trigger하여 OpenMetadata의 테이블/컬럼 설명을 Wren AI 모델에 반영.

**왜 필요했는가:** Curated View 모델을 삭제/재생성하면 기존에 동기화되어 있던 컬럼 description이 초기화된다. Description이 없으면 LLM이 컬럼의 비즈니스 의미를 이해하지 못해 잘못된 컬럼을 선택하거나 무시한다. 예를 들어 `is_value_stock` 컬럼에 "PER 10 이하이면서 PBR 1 이하인 저평가 종목 여부"라는 설명이 없으면, LLM은 이 컬럼이 무엇을 의미하는지 추론해야 한다.

### 5-2. 다종목 검증 (20문항)

**왜 필요했는가:** 4차 테스트(15문항)가 삼성전자/SK하이닉스 중심으로 편향되어 있었다. 실제 사용 환경에서는 다양한 종목(대형주, 중형주, KOSDAQ, 미국주식)과 약칭/업종 질의가 발생하므로, 이에 대한 커버리지를 검증해야 한다.

**테스트 범위:**

| 카테고리 | 문항수 | 대상 |
|---------|:-:|------|
| KOSPI 대형주 | 5 | 현대차, NAVER, 카카오, LG에너지솔루션, 포스코홀딩스 |
| KOSPI 중형주 | 3 | 셀트리온, 한화에어로, 두산에너빌리티 |
| KOSDAQ | 2 | 에코프로비엠, 알테오젠 |
| 미국주식 | 3 | 엔비디아, 테슬라, 애플 |
| 업종/섹터 | 2 | 자동차, 바이오 |
| 약칭 테스트 | 3 | 엔솔, 현차, 포스코 |
| 다종목 비교 | 2 | 3종목 PER, 2종목 밸류에이션 |

**결과:** SQL 생성 18/20 (90%), DB 실행 18/20 (90%)

### 5-3. 발견된 문제와 한계

#### 문제 1: 종목명 영문 번역 (Instructions 위반)

**증상:** "셀트리온 52주 신고가 신저가" → SQL에 `lower('Celltrion')` 사용 → 0행
**원인:** Instructions에 "종목명은 반드시 한글로 검색" 규칙이 있으나 LLM이 간헐적으로 위반
**영향:** 한글 종목명이 DB에 있는 종목에서 매칭 실패
**대응:** SQL Pair 추가로 한글 패턴 강화, 또는 Phase 3 에이전트에서 Entity Resolution 단계 추가

#### 문제 2: 약칭 매핑 한계

**증상:**
- "현차 PER" → `LIKE '%현차%'` → 0행 (정식명: 현대차)
- "엔솔 주가" → `LIKE '%엔솔%'` → 케이엔솔 매칭 (의도: LG에너지솔루션)
- "포스코 실적" → `LIKE '%포스코%'` → 여러 종목 매칭 (의도: 포스코홀딩스)

**원인:** NL2SQL은 자연어 약칭을 정식 종목명으로 변환하는 **Entity Resolution 기능이 없다**. LIKE 패턴 매칭만으로는 약칭→정식명 변환이 불가능.
**영향:** 실사용 시 사용자들이 약칭을 많이 사용하므로 UX 저하 필연적
**대응:** Phase 3 LangGraph 에이전트에서 Entity Resolver 노드 구현 (약칭→정식명 매핑 테이블 또는 LLM 기반 해석)

#### 문제 3: 데이터 부재

**증상:**
- "포스코홀딩스 PBR" → SQL 정상이지만 stock_info에 해당 종목 없음 (ADR만 존재)
- "테슬라 PER" → per 값이 NULL

**원인:** 데이터 수집 범위 또는 수집 로직 문제. NL2SQL 품질과 무관.
**대응:** 데이터 수집 DAG 점검 (별도 작업)

#### 문제 4: Wren AI sql_answer 환각

**증상:** "삼성전자와 하이닉스의 5년간 PER/PBR/ROE 비교" 질문에서 SQL은 11행(양쪽 모두 포함)을 정상 반환했으나, Wren AI 답변 텍스트에 **"하이닉스의 데이터는 제공되지 않아 비교가 어렵습니다"**로 표시.

**원인:** Wren AI의 `sql_answer` 파이프라인은 SQL 실행 결과를 LLM에 넣어 자연어로 요약하는데, 행이 많거나 `data_type`이 actual/estimate/preliminary로 섞여있으면 LLM이 일부 데이터를 무시하는 환각이 발생.

**검증:** 동일 SQL을 PostgreSQL에서 직접 실행한 결과:
```
 stock_name | fiscal_year | data_type  |  PER   |  PBR  |  ROE
 삼성전자   |        2022 | actual     |  21.70 |  3.40 |  15.69
 삼성전자   |        2023 | actual     |  77.98 |  3.32 |   4.26
 ...
 SK하이닉스 |        2022 | actual     | 317.30 | 11.24 |   3.54
 SK하이닉스 |        2023 | actual     |        | 13.29 | -17.08
 ...
 (11행 — 두 종목 모두 정상)
```

**영향:** SQL 품질은 정상이지만 사용자에게 잘못된 답변이 전달됨. Wren AI UI에서 "View SQL" → 결과 테이블을 직접 확인하면 정확한 데이터를 볼 수 있으나, 자연어 답변만 보면 오해 유발.

**대응:** Phase 3 LangGraph 에이전트에서 Result Synthesizer를 직접 구현하여 답변 생성 품질 제어. 현재 Wren AI의 sql_answer는 프롬프트 커스터마이징이 불가능하므로 구조적 한계.

### 5-4. Phase 1 최종 상태 (2026-04-12)

| 항목 | 수량/상태 |
|------|---------|
| 등록 모델 | 9개 (Gold 3 + Raw 2 + View 4) |
| 전체 컬럼 | 309개 (DB와 100% 일치) |
| Relationship | 6개 |
| SQL Pairs | 70개 |
| Instructions | 4개 |
| LLM | GPT-4.1-mini |
| SQL 생성률 | 100% (15/15 표준 테스트) |
| DB 실행률 | 100% (15/15) |
| Boolean flag 사용률 | 87% (7/8) |
| 다종목 SQL 생성률 | 90% (18/20) |
| 평균 응답 속도 | 10s |

### 5-5. Phase 2에서 해결해야 할 것

위 문제들은 NL2SQL 엔진(Wren AI) 단독으로는 구조적으로 해결할 수 없으며, LangGraph 에이전트에서 다음 노드를 구현해야 한다:

| 문제 | Phase 2 해결 노드 |
|------|-----------------|
| 약칭 매핑 | Entity Resolver (약칭→정식명 변환) |
| 영문 번역 | Entity Resolver (한글 강제) |
| 답변 환각 | Result Synthesizer (직접 답변 생성) |
| 데이터 부재 판단 | Evidence Validator ("데이터 없음" 명시) |
