# 수요예측 설명 에이전트 설계

## 1. 개요

### 목적
스마트폰 수요예측 모델의 결과를 **비전문가도 이해할 수 있도록** 자연어로 설명하는 AI 에이전트

### 핵심 질문 (Agent가 답해야 할 것들)
- "왜 이번 분기 북미 flagship 수요가 10% 하락 예측인가요?"
- "인도 시장 mid-range 수요 증가의 주요 원인은?"
- "Samsung Galaxy S25 출시가 예측에 얼마나 영향을 미쳤나요?"
- "지정학 리스크가 중국 시장에 미치는 영향은?"

---

## 2. 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    Explanation Agent                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              LLM (Claude/GPT-4)                      │    │
│  │  - 자연어 이해 및 생성                                │    │
│  │  - Tool 선택 및 실행 계획                            │    │
│  │  - 결과 종합 및 설명 생성                            │    │
│  └─────────────────────────────────────────────────────┘    │
│                            │                                 │
│              ┌─────────────┴─────────────┐                  │
│              ▼                           ▼                  │
│  ┌──────────────────┐      ┌──────────────────┐            │
│  │   Tool Router    │      │  Context Manager │            │
│  │  (도구 선택)      │      │  (대화 맥락 관리) │            │
│  └──────────────────┘      └──────────────────┘            │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │  Analysis   │ │   Search    │ │  Reference  │
    │   Tools     │ │   Tools     │ │   Tools     │
    └─────────────┘ └─────────────┘ └─────────────┘
```

---

## 3. Tools 설계

### 3.1 Analysis Tools (분석 도구)

#### `get_shap_values`
SHAP 값으로 예측에 기여한 피처 분석
```python
def get_shap_values(
    region: str,           # "North America", "China", etc.
    segment: str,          # "entry", "mid-range", "flagship"
    period: str,           # "2024-Q1"
    top_k: int = 5         # 상위 K개 피처
) -> dict:
    """
    Returns:
    {
        "prediction": 12500000,  # 예측 수요량
        "base_value": 11000000,  # 기준값
        "top_features": [
            {"feature": "news_tone_geopolitics", "shap_value": 0.15, "direction": "negative"},
            {"feature": "product_release_count", "shap_value": 0.12, "direction": "positive"},
            {"feature": "exchange_rate_change", "shap_value": 0.08, "direction": "negative"},
            ...
        ]
    }
    """
```

#### `compare_predictions`
기간/권역 간 예측 비교
```python
def compare_predictions(
    region: str,
    segment: str,
    period_a: str,          # "2024-Q1"
    period_b: str,          # "2024-Q2"
) -> dict:
    """
    Returns:
    {
        "period_a": {"prediction": 12500000, "actual": 12300000},
        "period_b": {"prediction": 13200000, "actual": None},
        "change_pct": 5.6,
        "key_differences": [
            {"feature": "new_product_launches", "change": "+2"},
            {"feature": "avg_news_tone", "change": "-0.3"},
        ]
    }
    """
```

#### `get_feature_trend`
특정 피처의 시계열 트렌드
```python
def get_feature_trend(
    feature_name: str,      # "news_tone_economy", "product_releases"
    region: str,
    start_date: str,
    end_date: str,
) -> dict:
    """
    Returns:
    {
        "feature": "news_tone_economy",
        "values": [
            {"date": "2024-01", "value": -0.5},
            {"date": "2024-02", "value": -0.8},
            ...
        ],
        "trend": "declining",
        "change_pct": -15.2
    }
    """
```

---

### 3.2 Search Tools (검색 도구)

#### `search_news`
관련 뉴스 검색 (벡터 + 키워드)
```python
def search_news(
    query: str,             # 자연어 쿼리 또는 키워드
    region: str = None,
    factor: str = None,     # "geopolitics", "economy", etc.
    start_date: str = None,
    end_date: str = None,
    limit: int = 10,
) -> list:
    """
    Returns:
    [
        {
            "url": "https://...",
            "source": "Reuters",
            "date": "2024-01-15",
            "tone": -2.5,
            "summary": "US-China trade tensions escalate...",
            "relevance_score": 0.92
        },
        ...
    ]
    """
```

#### `get_news_summary`
기간별 뉴스 요약 통계
```python
def get_news_summary(
    region: str,
    factor: str,            # "geopolitics", "economy", etc.
    start_date: str,
    end_date: str,
) -> dict:
    """
    Returns:
    {
        "total_articles": 1250,
        "avg_tone": -1.2,
        "tone_trend": "improving",  # worsening, stable, improving
        "top_themes": ["TARIFF", "SANCTION", "TRADE_DISPUTE"],
        "notable_events": [
            {"date": "2024-01-10", "description": "New tariffs announced", "tone": -4.5},
        ]
    }
    """
```

---

### 3.3 Reference Tools (참조 도구)

#### `get_product_releases`
제품 출시 정보 조회
```python
def get_product_releases(
    brand: str = None,      # "Samsung", "Apple", etc.
    segment: str = None,
    region: str = None,
    start_date: str = None,
    end_date: str = None,
) -> list:
    """
    Returns:
    [
        {
            "brand": "Samsung",
            "product": "Galaxy S24 Ultra",
            "segment": "flagship",
            "release_date": "2024-01-17",
            "regions": ["North America", "Western Europe", "South Korea"]
        },
        ...
    ]
    """
```

#### `get_macro_indicators`
거시경제 지표 조회
```python
def get_macro_indicators(
    region: str,
    indicator_type: str,    # "exchange_rate", "interest_rate", "pmi", etc.
    start_date: str,
    end_date: str,
) -> dict:
    """
    Returns:
    {
        "indicator": "exchange_rate",
        "region": "India",
        "values": [
            {"date": "2024-01", "value": 83.2, "change_pct": 0.5},
            ...
        ],
        "current_trend": "weakening"
    }
    """
```

---

## 4. 설명 생성 플로우

### 예시: "왜 북미 flagship 수요가 하락 예측인가요?"

```
1. [Intent 파악]
   - 권역: North America
   - 세그먼트: flagship
   - 질문 유형: 원인 분석

2. [Tool 실행 계획]
   a. get_shap_values(region="North America", segment="flagship", period="2024-Q1")
   b. get_news_summary(region="North America", factor="economy", ...)
   c. get_product_releases(segment="flagship", region="North America", ...)
   d. compare_predictions(period_a="2023-Q4", period_b="2024-Q1", ...)

3. [결과 수집]
   - SHAP: 경제 뉴스 톤(-0.15), 환율(-0.08), 신제품 출시(+0.05)
   - 뉴스: 평균 톤 -1.8 (악화 추세), 주요 테마: INFLATION, INTEREST_RATE
   - 제품: Galaxy S24, iPhone 15 출시 완료
   - 비교: 전분기 대비 -8%

4. [설명 생성]
   "북미 flagship 수요가 8% 하락 예측된 주요 원인:

   1. **경제 불확실성 증가** (기여도: 45%)
      - 최근 3개월간 경제 관련 뉴스 톤이 -1.8로 악화
      - 인플레이션과 금리 인상 관련 부정적 뉴스 1,250건

   2. **환율 영향** (기여도: 25%)
      - 달러 강세로 해외 소비자 구매력 감소

   3. **신제품 출시 사이클** (기여도: 20%)
      - Galaxy S24, iPhone 15 출시 후 초기 수요 안정화 단계

   관련 뉴스: [Reuters: US inflation concerns...] [Bloomberg: Fed rate...]"
```

---

## 5. 프롬프트 템플릿

### System Prompt
```
You are a smartphone demand forecasting explanation agent.

Your role is to explain WHY the demand forecast model made certain predictions,
using evidence from news data, product releases, and economic indicators.

Guidelines:
1. Always ground explanations in data (SHAP values, news articles, indicators)
2. Quantify impact when possible (%, contribution scores)
3. Cite specific news sources or events
4. Use business-friendly language (avoid technical jargon)
5. Structure explanations with clear cause-effect relationships

Available tools: {tool_descriptions}

Region taxonomy: North America, Western Europe, Central Europe, China, India,
                 Japan, South Korea, Southeast Asia, MEA, CALA, Asia Pacific Others

Segment taxonomy: entry, mid-range, flagship

Factor taxonomy: geopolitics, economy, supply_chain, regulation, disaster
```

### User Query Templates
```
- 원인 분석: "Why is {region} {segment} demand predicted to {change}?"
- 비교 분석: "Compare {region} demand between {period_a} and {period_b}"
- 영향 분석: "How does {factor} affect {region} market?"
- 제품 영향: "What impact did {product} launch have on forecasts?"
```

---

## 6. 구현 우선순위

### Phase 1: MVP (2주)
- [ ] get_shap_values (mock data로 시작)
- [ ] search_news (기존 news_article 테이블 활용)
- [ ] 기본 설명 생성 플로우

### Phase 2: 확장 (2주)
- [ ] get_news_summary (news_daily_summary 테이블)
- [ ] get_product_releases (product_release 테이블)
- [ ] compare_predictions

### Phase 3: 고도화 (2주)
- [ ] 벡터 검색 (news_embedding)
- [ ] get_macro_indicators
- [ ] get_feature_trend
- [ ] 대화 맥락 관리

---

## 7. 기술 스택

- **Agent Framework**: LangChain / Claude Tool Use
- **LLM**: Claude 3.5 Sonnet (비용 효율) 또는 GPT-4
- **Vector DB**: PostgreSQL + pgvector
- **Embedding**: OpenAI text-embedding-3-small
- **API**: FastAPI
