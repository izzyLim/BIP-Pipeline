# 스마트폰 수요예측 설명 에이전트 아키텍처

## 1. 개요

### 1.1 목적
스마트폰 수요 예측 결과에서 이상치나 급격한 변화가 발생했을 때, 그 원인을 뉴스 데이터, 경제 지표, 제품 출시 정보 등을 기반으로 분석하고 설명하는 AI 에이전트 시스템.

### 1.2 핵심 기능
- 특정 시점/권역의 수요 변화 원인 분석
- 뉴스 감성(tone) 트렌드 분석
- 경제 지표와 수요의 상관관계 설명
- 제품 출시/가격 변동이 수요에 미치는 영향 분석

---

## 2. 전체 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (React)                                │
│                         http://localhost:5174/forecast                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ForecastChat.jsx                                                    │    │
│  │  - 채팅 UI                                                           │    │
│  │  - 도구 사용 내역 표시 (이름, 파라미터, 결과 요약)                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ HTTP (REST API)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Backend (FastAPI)                                    │
│                         http://localhost:8000                                │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  app/api/forecast.py                                                 │    │
│  │  - /api/forecast/chat : 에이전트 대화 엔드포인트                       │    │
│  │  - /api/forecast/tools : 도구 목록 조회                               │    │
│  │  - 개별 도구 직접 호출 엔드포인트들                                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ Tool Use (Function Calling)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Claude API (Anthropic)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Model: claude-sonnet-4-20250514                                     │    │
│  │  - System Prompt (분석 전략 가이드)                                   │    │
│  │  - Tool Definitions (6개 도구)                                       │    │
│  │  - Agentic Loop (tool_use → tool_result 반복)                        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ Tool Execution
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Agent Tools (Python)                                 │
│                         gdelt_test/agent/tools.py                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  - search_news          : 뉴스 기사 검색                              │    │
│  │  - get_news_summary     : 뉴스 통계 요약                              │    │
│  │  - get_daily_trend      : 일별 트렌드                                 │    │
│  │  - get_product_releases : 제품 출시 정보                              │    │
│  │  - get_product_prices   : 제품 가격 추이                              │    │
│  │  - get_macro_indicators : 거시경제 지표                               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ SQL Queries
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PostgreSQL Database                                  │
│                         localhost:5432 / stockdb                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Tables:                                                             │    │
│  │  - news_article (1.4M+) : GDELT 뉴스 데이터                          │    │
│  │  - news_daily_summary   : 일별 집계 데이터                            │    │
│  │  - product_release (208): 제품 출시 정보                              │    │
│  │  - product_price (22K)  : 제품 가격 이력                              │    │
│  │  - macro_indicators (27K): 거시경제 지표                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 데이터 소스 및 수집

### 3.1 GDELT (Global Database of Events, Language, and Tone)

#### 데이터 소스
- **URL**: `http://data.gdeltproject.org/gdeltv2/masterfilelist.txt`
- **형식**: 15분 단위 업데이트되는 GKG (Global Knowledge Graph) 파일
- **기간**: 2020-01-01 ~ 현재 (약 5년치)

#### 수집 프로세스
```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  GDELT GKG   │────▶│   Download   │────▶│    Parse     │────▶│  PostgreSQL  │
│  (ZIP/CSV)   │     │   & Extract  │     │  & Classify  │     │   Insert     │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │   Classification      │
                                    │   - news_type         │
                                    │   - factor            │
                                    │   - regions           │
                                    │   - brands            │
                                    └───────────────────────┘
```

#### 수집 스크립트
| 스크립트 | 용도 |
|---------|------|
| `collector/historical_collector.py` | 과거 데이터 일괄 수집 |
| `collector/daily_collector.py` | 일일 증분 수집 |
| `collector/gkg_parser.py` | GKG 파일 파싱 |
| `collector/classifier.py` | 뉴스 분류 (유형/요인/권역) |

### 3.2 뉴스 분류 체계

#### 뉴스 유형 (news_type)
| 유형 | 설명 | 키워드 예시 |
|------|------|------------|
| `smartphone` | 스마트폰 직접 관련 | smartphone, iPhone, Galaxy, Xiaomi |
| `external` | 외부 영향 요인 | tariff, inflation, chip shortage |

#### 외부 요인 (factor)
| 요인 | 설명 | 키워드 예시 |
|------|------|------------|
| `geopolitics` | 지정학 | war, sanction, trade war, tariff |
| `economy` | 경제 | inflation, interest rate, recession |
| `supply_chain` | 공급망 | chip shortage, semiconductor, logistics |
| `regulation` | 규제 | antitrust, ban, privacy law |
| `disaster` | 재난 | pandemic, earthquake, flood |

#### 권역 (regions) - Counterpoint Research 기준
| 권역 | 국가/지역 |
|------|----------|
| North America | 미국, 캐나다 |
| Western Europe | 영국, 독일, 프랑스, 이탈리아, 스페인 등 |
| Central Europe | 폴란드, 체코, 헝가리 등 |
| China | 중국 |
| India | 인도 |
| Japan | 일본 |
| South Korea | 한국 |
| Southeast Asia | 베트남, 태국, 인도네시아, 필리핀, 말레이시아 |
| MEA | 중동 & 아프리카 |
| CALA | 카리브해 & 라틴아메리카 |
| Asia Pacific Others | 호주, 뉴질랜드, 대만, 홍콩 등 |

### 3.3 제품 출시 데이터 (Product Release)

#### 데이터 소스
- **출처**: 공식 보도자료, Wikipedia, GSMArena
- **수집 방식**: 수동 큐레이션 (주요 브랜드 flagship/mid-range 제품)
- **기간**: 2020-01 ~ 2024-12

#### 포함 브랜드
| 브랜드 | 제품 라인 | 세그먼트 |
|--------|----------|----------|
| Samsung | Galaxy S, Note, Z Fold/Flip, A 시리즈 | flagship, mid-range |
| Apple | iPhone Pro/Plus/기본, SE | flagship, mid-range |
| Xiaomi | Mi, Redmi, POCO | flagship, mid-range, entry |
| OPPO | Find X, Reno | flagship, mid-range |
| vivo | X, V 시리즈 | flagship, mid-range |
| OnePlus | 숫자 시리즈, Nord | flagship, mid-range |
| Google | Pixel | flagship, mid-range |
| Huawei | Mate, P 시리즈 | flagship |
| Realme | GT, Number 시리즈 | mid-range |

#### 데이터 필드
```python
{
    "brand": "Samsung",
    "product_name": "Galaxy S24 Ultra",
    "segment": "flagship",           # entry | mid-range | flagship
    "announce_date": "2024-01-17",
    "release_date": "2024-01-31",
    "regions": ["North America", "Western Europe", "South Korea"]
}
```

#### 수집 스크립트
| 스크립트 | 용도 |
|---------|------|
| `scraper/product_data.py` | 제품 출시 데이터 로드 |
| `scraper/gsmarena_scraper.py` | GSMArena 스펙 스크래핑 (참고용) |

### 3.4 제품 가격 데이터 (Product Price)

#### 데이터 소스
- **MSRP (출시가)**: 공식 발표가, Wikipedia, GSMArena
- **감가상각률**: SellCell, BankMyCell 리서치 보고서 (2021-2026)

#### 감가상각 모델
```
월별 가격 = MSRP × (1 - 월별감가율)^경과월수
```

| 세그먼트 | 연간 감가율 | 월별 감가율 | 비고 |
|----------|------------|------------|------|
| flagship | 35-45% | ~3.5% | 1년차 급락, 이후 완만 |
| mid-range | 30-40% | ~3.0% | |
| entry | 25-35% | ~2.5% | 상대적으로 안정 |

#### 브랜드별 감가 특성
| 브랜드 | 감가율 | 특성 |
|--------|--------|------|
| Apple | 낮음 (25-35%) | 리셀 가치 높음 |
| Samsung | 중간 (35-45%) | 신모델 출시 시 급락 |
| Xiaomi | 높음 (40-50%) | 가격 경쟁력 중심 |
| OnePlus | 중간 (35-40%) | |
| Google | 높음 (40-50%) | Pixel 특성 |

#### 데이터 필드
```python
{
    "product_id": 1,
    "brand": "Apple",
    "product_name": "iPhone 15 Pro",
    "price_date": "2024-06-01",
    "region": "North America",
    "price_usd": 899.00,
    "price_type": "market"           # msrp | market | resale
}
```

#### 수집 스크립트
| 스크립트 | 용도 |
|---------|------|
| `scraper/product_price_data.py` | MSRP 데이터 |
| `scraper/product_price_real.py` | 감가상각 기반 가격 생성 |

### 3.5 거시경제 지표 (Macro Indicators)

#### 데이터 소스
| 지표 | 소스 | API/라이브러리 |
|------|------|---------------|
| 환율 (Exchange Rate) | Yahoo Finance | `yfinance` |
| 금리 (Interest Rate) | Yahoo Finance, FRED | `yfinance`, `fredapi` |
| PMI | Trading Economics | 수동 수집 |
| CPI | World Bank, FRED | `fredapi` |
| GDP 성장률 | World Bank, IMF | 수동 수집 |

#### 권역별 지표 매핑
| 권역 | 환율 심볼 | 금리 심볼 |
|------|----------|----------|
| North America | DX-Y.NYB (USD Index) | ^TNX (10Y Treasury) |
| Western Europe | EURUSD=X | - |
| China | USDCNY=X | - |
| Japan | USDJPY=X | - |
| South Korea | USDKRW=X | - |
| India | USDINR=X | - |
| Southeast Asia | USDTHB=X (태국 바트 대표) | - |
| MEA | USDZAR=X (남아공 랜드 대표) | - |
| CALA | USDBRL=X (브라질 헤알 대표) | - |

#### 데이터 필드
```python
{
    "region": "North America",
    "indicator_type": "interest_rate",  # exchange_rate | interest_rate | pmi | cpi | gdp_growth
    "indicator_date": "2024-01-15",
    "value": 4.25,
    "change_pct": 0.05
}
```

#### 수집 스크립트
| 스크립트 | 용도 |
|---------|------|
| `collect_macro.py` | 거시경제 지표 수집 (yfinance 기반) |

### 3.6 데이터 현황 (2026-02-24 기준)

| 테이블 | 레코드 수 | 기간 | 데이터 소스 |
|--------|----------|------|------------|
| news_article | 1,443,084 | 2020-01 ~ 2026-02 | GDELT GKG |
| ├─ smartphone | 20,183 | | |
| └─ external | 1,422,901 | | |
| product_release | 208 | 2020 ~ 2024 | 공식 보도자료, Wikipedia |
| product_price | 22,085 | 2020 ~ 2025 | MSRP + 감가상각 모델 |
| macro_indicators | 26,738 | 2020 ~ 2025 | Yahoo Finance, FRED |

### 3.7 데이터 수집 아키텍처 요약

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           데이터 수집 파이프라인                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   GDELT     │    │   Yahoo     │    │  공식 발표  │    │  리서치     │  │
│  │   GKG API   │    │   Finance   │    │  보도자료   │    │  보고서     │  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│         │                  │                  │                  │         │
│         ▼                  ▼                  ▼                  ▼         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ 뉴스 파싱   │    │ 지표 수집   │    │ 제품 출시   │    │ 가격 모델   │  │
│  │ & 분류      │    │ (yfinance)  │    │ 큐레이션    │    │ (감가상각)  │  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│         │                  │                  │                  │         │
│         └──────────────────┼──────────────────┼──────────────────┘         │
│                            ▼                  ▼                            │
│                    ┌─────────────────────────────────┐                     │
│                    │         PostgreSQL              │                     │
│                    │  news_article | macro_indicators│                     │
│                    │  product_release | product_price│                     │
│                    └─────────────────────────────────┘                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 데이터베이스 스키마

### 4.1 news_article
```sql
CREATE TABLE news_article (
    id SERIAL PRIMARY KEY,
    gkg_id VARCHAR(100) UNIQUE,
    url TEXT NOT NULL,
    source VARCHAR(255),
    published_date DATE,
    news_type VARCHAR(20),        -- 'smartphone' | 'external'
    factor VARCHAR(30),           -- 'geopolitics' | 'economy' | ...
    regions TEXT[],               -- ARRAY['China', 'India']
    brands TEXT[],                -- ARRAY['Samsung', 'Apple']
    tone_score FLOAT,             -- -10 ~ +10
    themes TEXT[],
    locations TEXT[],
    persons TEXT[],
    organizations TEXT[],
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_news_published ON news_article(published_date);
CREATE INDEX idx_news_regions ON news_article USING GIN(regions);
CREATE INDEX idx_news_type_factor ON news_article(news_type, factor);
```

### 4.2 news_daily_summary
```sql
CREATE TABLE news_daily_summary (
    id SERIAL PRIMARY KEY,
    summary_date DATE,
    region VARCHAR(50),
    smartphone_count INT,
    smartphone_avg_tone FLOAT,
    geopolitics_count INT,
    geopolitics_avg_tone FLOAT,
    economy_count INT,
    economy_avg_tone FLOAT,
    supply_chain_count INT,
    supply_chain_avg_tone FLOAT,
    regulation_count INT,
    regulation_avg_tone FLOAT,
    disaster_count INT,
    disaster_avg_tone FLOAT,
    UNIQUE(summary_date, region)
);
```

### 4.3 product_release
```sql
CREATE TABLE product_release (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(50),
    product_name VARCHAR(200),
    segment VARCHAR(20),          -- 'entry' | 'mid-range' | 'flagship'
    announce_date DATE,
    release_date DATE,
    regions TEXT[],
    specs JSONB
);
```

### 4.4 product_price
```sql
CREATE TABLE product_price (
    id SERIAL PRIMARY KEY,
    product_id INT REFERENCES product_release(id),
    brand VARCHAR(50),
    product_name VARCHAR(200),
    price_date DATE,
    region VARCHAR(50),
    price_usd DECIMAL(10,2),
    price_type VARCHAR(20)        -- 'msrp' | 'market' | 'resale'
);
```

### 4.5 macro_indicators
```sql
CREATE TABLE macro_indicators (
    id SERIAL PRIMARY KEY,
    region VARCHAR(50),
    indicator_type VARCHAR(30),   -- 'exchange_rate' | 'interest_rate' | 'pmi' | 'cpi' | 'gdp_growth'
    indicator_date DATE,
    value DECIMAL(15,4),
    change_pct DECIMAL(8,4)
);
```

---

## 5. 에이전트 아키텍처

### 5.1 에이전트 구성요소

```
┌─────────────────────────────────────────────────────────────────┐
│                      Forecast Agent                              │
│                                                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │ System Prompt  │  │ Tool Definitions│  │ Conversation   │     │
│  │ (분석 전략)     │  │ (6개 도구)      │  │ History        │     │
│  └────────────────┘  └────────────────┘  └────────────────┘     │
│           │                  │                   │               │
│           └──────────────────┼───────────────────┘               │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Claude API                             │   │
│  │              claude-sonnet-4-20250514                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   Tool Executor                           │   │
│  │              execute_tool(name, params)                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 시스템 프롬프트 구조

```
1. Role Definition
   - 스마트폰 수요 분석 전문 에이전트

2. Analysis Strategy (4단계)
   ├── Step 1: 컨텍스트 파악 (get_news_summary, get_daily_trend)
   ├── Step 2: 근본 원인 조사 (get_macro_indicators, search_news)
   ├── Step 3: 제품 요인 분석 (get_product_releases, get_product_prices)
   └── Step 4: 종합 분석

3. Tool Usage Guide
   - 각 도구의 용도와 해석 방법

4. Taxonomy
   - 권역, 세그먼트, 외부 요인 정의

5. Response Format
   - 요약 → 주요 원인 → 근거 → 추가 고려사항
```

### 5.3 도구 정의

| 도구명 | 용도 | 주요 파라미터 |
|--------|------|--------------|
| `search_news` | 뉴스 기사 검색 (증거 수집) | keywords, region, factor, date range |
| `get_news_summary` | 뉴스 통계 개요 | region, factor, date range |
| `get_daily_trend` | 일별 시계열 분석 | region, factor, date range |
| `get_product_releases` | 신제품 출시 정보 | brand, segment, region, date range |
| `get_product_prices` | 가격 변동 분석 | brand, product_name, segment, region |
| `get_macro_indicators` | 경제 지표 조회 | region, indicator_type, date range |

---

## 6. 에이전트 실행 흐름

### 6.1 요청-응답 흐름

```
User                Frontend              Backend              Claude API           Tools/DB
 │                     │                     │                     │                   │
 │  질문 입력           │                     │                     │                   │
 │────────────────────▶│                     │                     │                   │
 │                     │  POST /chat         │                     │                   │
 │                     │────────────────────▶│                     │                   │
 │                     │                     │  messages.create    │                   │
 │                     │                     │────────────────────▶│                   │
 │                     │                     │                     │                   │
 │                     │                     │  tool_use (분석 시작) │                   │
 │                     │                     │◀────────────────────│                   │
 │                     │                     │                     │                   │
 │                     │                     │  execute_tool       │                   │
 │                     │                     │────────────────────────────────────────▶│
 │                     │                     │                     │                   │
 │                     │                     │  query results      │                   │
 │                     │                     │◀────────────────────────────────────────│
 │                     │                     │                     │                   │
 │                     │                     │  tool_result        │                   │
 │                     │                     │────────────────────▶│                   │
 │                     │                     │                     │                   │
 │                     │                     │     ... (반복) ...   │                   │
 │                     │                     │                     │                   │
 │                     │                     │  end_turn (최종 응답) │                   │
 │                     │                     │◀────────────────────│                   │
 │                     │                     │                     │                   │
 │                     │  ChatResponse       │                     │                   │
 │                     │◀────────────────────│                     │                   │
 │                     │                     │                     │                   │
 │  응답 + 도구 내역    │                     │                     │                   │
 │◀────────────────────│                     │                     │                   │
```

### 6.2 Agentic Loop (도구 반복 호출)

```python
# Backend: forecast.py

while response.stop_reason == "tool_use":
    # 1. 에이전트의 도구 호출 요청 추출
    tool_calls = [block for block in response.content if block.type == "tool_use"]

    # 2. 각 도구 실행
    for tool_call in tool_calls:
        result = execute_tool(tool_call.name, tool_call.input)
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": json.dumps(result)
        })

    # 3. 도구 결과와 함께 다음 API 호출
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=[...conversation_history, {"role": "user", "content": tool_results}]
    )

# 4. stop_reason == "end_turn" 이면 최종 응답 반환
```

### 6.3 예시: 분석 흐름

**질문**: "2020년 Q1 중국 시장 상황 분석해줘"

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 컨텍스트 파악                                            │
├─────────────────────────────────────────────────────────────────┤
│ Tool: get_news_summary                                          │
│ Params: region="China", start_date="2020-01-01", end="2020-03-31"│
│ Result: 424 articles, avg_tone=-1.23, trend=worsening           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 일별 트렌드 확인                                         │
├─────────────────────────────────────────────────────────────────┤
│ Tool: get_daily_trend                                           │
│ Params: region="China", factor="economy", ...                   │
│ Result: 1월 21일부터 급격한 톤 하락 감지                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 구체적 증거 수집                                         │
├─────────────────────────────────────────────────────────────────┤
│ Tool: search_news                                               │
│ Params: region="China", keywords=["pandemic", "lockdown"]       │
│ Result: COVID-19 관련 기사들 (출처: Reuters, Bloomberg...)       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: 제품 출시 상황 확인                                      │
├─────────────────────────────────────────────────────────────────┤
│ Tool: get_product_releases                                      │
│ Params: region="China", start_date="2020-01-01", ...            │
│ Result: Xiaomi Mi 10, OPPO Find X2 등 5개 플래그십 출시          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 최종 응답 생성                                                   │
├─────────────────────────────────────────────────────────────────┤
│ ## 2020년 Q1 중국 스마트폰 시장 상황 분석                         │
│                                                                 │
│ ### 요약                                                        │
│ 코로나19 팬데믹 초기 충격으로 부정적 뉴스 톤(-1.23)...            │
│                                                                 │
│ ### 주요 원인                                                   │
│ 1. 팬데믹 영향 (1월 21일부터 경제 뉴스 악화)                      │
│ 2. 오프라인 매장 폐쇄                                            │
│ ...                                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. API 엔드포인트

### 7.1 채팅 API

```
POST /api/forecast/chat
```

**Request:**
```json
{
  "message": "2020년 Q1 중국 시장 상황 분석해줘",
  "conversation_id": "conv_20240101120000"  // optional
}
```

**Response:**
```json
{
  "response": "## 2020년 Q1 중국 스마트폰 시장...",
  "conversation_id": "conv_20240101120000",
  "tools_used": ["get_news_summary", "search_news", "get_product_releases"],
  "tool_details": [
    {
      "name": "get_news_summary",
      "parameters": {"region": "China", "start_date": "2020-01-01", ...},
      "result_summary": "424건, 톤 -1.23, worsening"
    },
    ...
  ]
}
```

### 7.2 기타 API

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/forecast/health` | GET | 헬스체크 |
| `/api/forecast/tools` | GET | 도구 목록 |
| `/api/forecast/news/search` | POST | 뉴스 검색 |
| `/api/forecast/news/summary` | POST | 뉴스 요약 |
| `/api/forecast/trend` | GET | 일별 트렌드 |
| `/api/forecast/products/releases` | POST | 제품 출시 |
| `/api/forecast/products/prices` | POST | 제품 가격 |
| `/api/forecast/macro` | GET | 거시경제 지표 |
| `/api/forecast/conversation/{id}` | DELETE | 대화 삭제 |

---

## 8. 프로젝트 구조

```
BIP-Pipeline/gdelt_test/
├── agent/
│   └── tools.py              # 에이전트 도구 정의 및 구현
├── collector/
│   ├── historical_collector.py   # 과거 데이터 수집
│   ├── daily_collector.py        # 일일 수집
│   ├── gkg_parser.py             # GKG 파싱
│   └── classifier.py             # 뉴스 분류
├── db/
│   └── schema.sql            # DB 스키마
├── docs/
│   └── ARCHITECTURE.md       # 본 문서
├── historical/
│   └── progress.json         # 수집 진행 상황
└── scripts/
    └── aggregate_daily.py    # 일별 집계

BIP-React-FastAPI/
├── backend/
│   └── app/
│       └── api/
│           └── forecast.py   # Forecast API 라우터
└── frontend/
    └── src/
        ├── components/
        │   └── ForecastChat.jsx  # 채팅 UI
        └── pages/
            └── ForecastPage.jsx  # 페이지 컴포넌트
```

---

## 9. 설정 및 환경변수

### 9.1 필수 환경변수

```bash
# .env (gdelt_test/)
ANTHROPIC_API_KEY=sk-ant-...

# Database
DB_HOST=localhost
DB_PORT=5432
DB_USER=user
DB_PASSWORD=pw1234
DB_NAME=stockdb
```

### 9.2 실행 방법

```bash
# Backend 실행
cd BIP-React-FastAPI/backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend 실행
cd BIP-React-FastAPI/frontend
npm run dev

# 접속
http://localhost:5174/forecast
```

---

## 10. 향후 개선 방향

### 10.1 데이터 품질
- [ ] 뉴스 본문 수집 및 임베딩 (현재 URL만 저장)
- [ ] 벡터 검색 (Semantic Search) 도입
- [ ] 권역 분류 정확도 개선

### 10.2 에이전트 기능
- [ ] 실제 수요 예측 모델 연동 (SHAP 값)
- [ ] 시각화 도구 추가 (차트 생성)
- [ ] 스트리밍 응답 지원

### 10.3 시스템
- [ ] Redis 캐싱 (반복 쿼리 최적화)
- [ ] 비동기 뉴스 수집 파이프라인
- [ ] Docker Compose 통합 배포

---

## 11. 참고 자료

- [GDELT Project](https://www.gdeltproject.org/)
- [Counterpoint Research](https://www.counterpointresearch.com/)
- [Anthropic Tool Use](https://docs.anthropic.com/claude/docs/tool-use)
- [FastAPI](https://fastapi.tiangolo.com/)
