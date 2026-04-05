# 체크리스트 모니터링 에이전트 아키텍처

> **작성일:** 2026-04-05
> **대상:** BIP-Agents LangGraph 체크리스트 모니터링 에이전트 (`bip-agents-api`)
> **관련 거버넌스:** `docs/security_governance.md`, `docs/metadata_governance.md`

---

## 1. 개요

장중 체크리스트 모니터링 에이전트는 매일 아침 모닝리포트가 생성한 체크리스트를
하루 동안 추적하고, 시간대별로 텔레그램에 분석 메시지를 발송하는 시스템입니다.

**핵심 원칙:**
- **신호 판정은 deterministic 룰 엔진**이 담당 (재현성/감사 용이성)
- **LLM(Haiku)은 설명/요약만** 담당 (비용 절감, 일관성)
- **도구 호출은 코드 레벨에서 강제** (LLM 판단에 의존하지 않음)
- **절대 시장 맥락 반영** (체크리스트 임계값 + 90일 분포)

---

## 2. 4단계 LangGraph 파이프라인

```
checklist_text (DB 로드)
    ↓
┌─────────────────────────────────┐
│ [1] Parser (deterministic)      │
│  - 항목 단위 분해               │
│  - 유형 분류 (level/news/...)   │
│  - 임계값/방향 추출             │
│  - required_tools 매핑          │
│  - time_phase 필터링            │
└─────────────────────────────────┘
    ↓ parsed_items
┌─────────────────────────────────┐
│ [2] Collector (MCP 도구 호출)   │
│  - 체크리스트 항목별 실시간     │
│  - must_call_context 강제       │
│  - ALWAYS_COLLECT_STOCKS 10개   │
└─────────────────────────────────┘
    ↓ gathered_data + always_stocks
┌─────────────────────────────────┐
│ [3] Signal (룰 엔진)            │
│  - family별 규칙 적용           │
│  - 🟢/🟡/🔴 판정                │
│  - LLM 호출 없음                │
└─────────────────────────────────┘
    ↓ signals
┌─────────────────────────────────┐
│ [4] Explainer (Haiku)           │
│  - 이미 결정된 신호를 텍스트화  │
│  - time_phase별 프롬프트 분기   │
│  - 텔레그램 메시지 포맷         │
└─────────────────────────────────┘
    ↓ analysis_result
API 응답 → Airflow → 텔레그램
```

---

## 3. 단계별 상세

### 3-1. Parser (`checklist_parser.py`)

**입력:** `checklist_text` (모닝리포트 HTML에서 추출된 원문)

**처리:**
- 섹션 헤더 감지: "장 시작 전" / "장 중" / "주의 가격 레벨"
- 각 항목을 `ChecklistItem` dict로 변환
- `_classify_item()`으로 유형/키/임계값/방향 추출

**출력 필드:**
```python
{
    "index": 0,
    "original": "원/달러 1,520원 돌파 여부",
    "section": "pre_market",
    "item_type": "level",
    "indicator_key": "fx_krw",
    "threshold": 1520.0,
    "direction": "above",
    "required_tools": ["realtime_fx_rate", "get_indicator_context"],
    "must_call_context": True,
}
```

**시간대 필터링:**
```python
def filter_items_by_phase(items, time_phase):
    if time_phase == "pre_market":
        return [i for i in items if i["section"] == "pre_market"]
    elif time_phase == "intraday":
        return [i for i in items if i["section"] in ("intraday", "price_level")]
    elif time_phase == "close":
        return items  # 전체 (복기용)
```

### 3-2. Collector (`checklist_collector.py`)

**MCP 도구 호출 정책:**
- 파서가 지정한 `required_tools` 순서대로 호출
- `must_call_context=True`이면 `get_indicator_context` 강제 호출
- MCP 응답이 `[{"type":"text","text":"..."}]` 형태여도 `_unwrap()`으로 dict 정규화

**ALWAYS_COLLECT_STOCKS (체크리스트 외 항상 수집):**
```python
ALWAYS_COLLECT_STOCKS = [
    ("005930", "삼성전자"),        # 반도체 1
    ("000660", "SK하이닉스"),      # 반도체 2
    ("373220", "LG에너지솔루션"),  # 2차전지 1
    ("207940", "삼성바이오로직스"), # 바이오 1
    ("005380", "현대차"),          # 자동차 1
    ("000270", "기아"),            # 자동차 2
    ("005490", "POSCO홀딩스"),     # 소재
    ("035420", "NAVER"),           # IT 1
    ("035720", "카카오"),          # IT 2
    ("006400", "삼성SDI"),         # 2차전지 2
]
```

**CONTEXT_MAPPING (indicator_key → 지표):**
| indicator_key | indicator_type | region |
|--------------|---------------|--------|
| fx_krw | exchange_rate | South Korea |
| kospi/kosdaq | stock_index_kospi/kosdaq | South Korea |
| sp500/nasdaq/nikkei | stock_index_sp500/nasdaq/nikkei | North America/Japan |
| btc/eth | crypto_btc/eth | — |
| oil/gold | commodity_oil/gold | North America |
| vix | vix | North America |

### 3-3. Signal (`checklist_signal.py` + `checklist_rules.py`)

**룰 엔진 구조:**
- `rule_fx(value, threshold, direction, context)` — 환율 (higher_is_risk)
- `rule_index(...)` — 지수 (higher_is_positive, drawdown 기반)
- `rule_stock(...)` — 개별 종목
- `rule_commodity(...)` — 원자재 (Z-score 기반)
- `rule_crypto(...)` — 크립토 (변동성 큰 자산)
- `rule_general(...)` — 뉴스/기타
- `judge()` — indicator_key로 dispatch

**판정 로직 예시 (rule_fx, higher_is_risk):**
```python
if context.percentile >= 90:
    return RED, "역대 고점권 경계 구간"
elif context.percentile >= 75:
    return YELLOW, "상위 25% 구간 (주의)"
elif met:
    return GREEN, "조건 충족"
else:
    return YELLOW, "미도달"
```

**판정 로직 예시 (rule_index, higher_is_positive):**
```python
if drawdown_from_90d_high <= -10:
    return RED, "조정 국면"
elif drawdown_from_90d_high <= -5:
    return YELLOW, "약세 관찰"
elif percentile >= 90:
    return YELLOW, "과열 주의"
```

### 3-4. Explainer (`checklist_explainer.py`)

**LLM 역할:**
- 이미 결정된 신호등(🟢/🟡/🔴)은 **변경 금지**
- 수치는 제공된 데이터에서만 사용
- 텔레그램 마크다운 포맷 변환

**time_phase별 프롬프트 분기:**
- `pre_market` / `intraday`: 항목별 출력 (신호등 + 판정 근거)
- `close`: 체크리스트 전체 복기 + 내일 관찰 포인트

**출력 형식:**
```
✅ *원문 항목*
🔴 판단 근거 (수치 포함)

———————————————
📊 *주요 종목*: 삼성전자, SK하이닉스, ...
📊 *수급*: 외국인/기관/개인
💡 *종합*: 한줄 시장 전망
```

---

## 4. MCP 도구 목록

### 4-1. 실시간 시세 (한투 API)
| 도구 | 설명 | 한투 엔드포인트 |
|------|------|---------------|
| `realtime_stock_price` | 종목 현재가 | FHKST01010100 |
| `realtime_index` | KOSPI/KOSDAQ 지수 | FHPUP02100000 |
| `realtime_investor` | 투자자 매매동향 (시장 전체는 네이버 fallback) | FHKST01010900 |
| `realtime_program_trade` | 프로그램 매매 | FHPPG04650100 |
| `preopen_stock_price` | **예상 체결가 (08:30~09:00)** | FHKST01010100 (antc_cntg_prc) |
| `preopen_index` | **지수 예상 시가** | FHPUP02100000 (bstp_nmix_oprc) |

### 4-2. 외부 데이터
| 도구 | 설명 | 소스 |
|------|------|------|
| `realtime_fx_rate` | USD/KRW 환율 + 전일 대비 | ExchangeRate API + DB |
| `night_futures_ewy` | 한국 ETF 야간선물 | yfinance (EWY) |
| `global_index` | 닛케이/S&P/나스닥/DAX/항셍 | yfinance |
| `crypto_price` | BTC/ETH 실시간 | Upbit API |
| `news_search_naver` | 뉴스 검색 | 네이버 뉴스 API |

### 4-3. 맥락 도구 (Phase 1 추가)
| 도구 | 설명 | 데이터 |
|------|------|------|
| `get_indicator_context` | 90일 분포/percentile/drawdown/trend | macro_indicators 테이블 |
| `sector_performance` | 업종별 등락률 | macro_indicators (KRX 섹터) |

### 4-4. DB 조회
| 도구 | 설명 |
|------|------|
| `db_investor_flow` | 투자자별 순매수 5일 |
| `db_investor_trading` | 종목별 수급 TOP5 |
| `db_semiconductor_prices` | 반도체 현물가 |
| `db_market_indices` | 주요 지수 |

---

## 5. get_indicator_context 상세

**입력:**
- `indicator_type`: exchange_rate, stock_index_kospi, crypto_btc 등
- `region`: exchange_rate는 필수 (South Korea=USD/KRW)
- `current_value`: 실시간 도구 결과 전달 (시점 mismatch 방지)
- `lookback_days`: 기본 90

**출력 핵심 필드:**
```python
{
    "family": "fx",
    "direction": "higher_is_risk",
    "percentile": 95.7,              # 상위 4.3%
    "zscore": 1.7,                    # 평균 대비 1.7σ
    "range_position": 0.936,          # 90일 범위 93.6% 위치 (clamp 0~1)
    "out_of_90d_range": False,
    "drawdown_from_90d_high": -0.37,  # 90일 고점 대비
    "trend_label": "상승",
    "volatility_20d_pct": 0.75,
    "interpretation": "역대 고점권 (경계 구간)",
    "reliability": "normal",          # 표본 20 미만이면 "low"
}
```

**Indicator Family 매핑:**
| indicator_type | family | direction |
|---------------|--------|-----------|
| exchange_rate | fx | higher_is_risk |
| stock_index_* | index | higher_is_positive |
| commodity_oil/gold | commodity | neutral |
| crypto_btc/eth | crypto | neutral |
| vix | sentiment | higher_is_risk |

**캐시:**
- 프로세스 메모리 TTL 3분
- 키: `(indicator_type, region, lookback_days, value_bucket)`
- value_bucket = `round(current_value / 10)` (10단위 반올림)
- max size 500, 초과 시 오래된 엔트리 제거

---

## 6. 호출 흐름 (Airflow ↔ BIP-Agents)

```
Airflow DAG
    ↓
POST http://bip-agents-api:8100/api/checklist/analyze
{
  "checklist_text": "...",
  "time_phase": "intraday",
  "analysis_date": "2026-04-06"
}
    ↓
BIP-Agents FastAPI
    ↓
run_checklist_monitor()
    ↓
LangGraph 4단계 파이프라인
    ↓
Response:
{
  "analysis_result": "...",
  "token_usage": {...},
  "audit": {
    "run_id": "checklist_intraday_abc123",
    "agent_name": "market_monitor_checklist",
    "llm_provider": "anthropic",
    "llm_model": "claude-haiku-4-5-20251001",
    "prompt_class": "analyze_checklist_intraday",
    "prompt_tokens": 1244,
    "completion_tokens": 290,
    "tools_used": [...],
    "data_sources": [...],
    "referenced_tables": ["macro_indicators", "monitor_checklist"],
    "execution_ms": 8650,
    "status": "success"
  }
}
    ↓
Airflow: record_agent_audit(**audit) → agent_audit_log INSERT
    ↓
텔레그램 발송
```

---

## 7. 감사 로그 (Security Governance 3-3, 3-4)

모든 LLM 호출은 `agent_audit_log`에 기록됩니다.

**필수 필드:**
- `agent_name`, `agent_type`, `run_id`
- `llm_provider`, `llm_model`, `prompt_class`
- `prompt_tokens`, `completion_tokens`, `execution_ms`
- `tools_used`, `data_sources`, `referenced_tables`
- `status`, `error_message`

**민감 자산 접근 없음:**
- `monitor_checklist`: 공용 체크리스트 원문 (민감 아님)
- `macro_indicators`: 공개 시장 지표
- 사용자별 재무 정보 접근 없음

---

## 8. 발송 스케줄

| 시각 (KST) | DAG | 목적 | LLM |
|-----------|-----|------|-----|
| 08:10 | `morning_report` | 모닝리포트 생성 + 이메일 + 텔레그램 체크리스트 원문 | Opus 4.6 |
| 08:25 | `market_monitor_checklist_parse` | HTML에서 체크리스트 추출 → DB 저장 + 장전 분석 발송 | Haiku (장전) |
| 08:40 | `market_monitor_preopen` | 예상 체결가 + 갭 방향 분석 | Haiku |
| 09:00 | `market_monitor_intraday` | 장 초반 정기 현황 | Haiku |
| 09:10~15:50 | `market_monitor_intraday` | 10분 간격 이상치 감지 | 없음 (규칙 기반) |
| 10:00 / 12:00 / 14:30 | `market_monitor_intraday` | 정기 현황 | Haiku |
| 15:35 | `market_monitor_close` | 장 마감 복기 + 내일 관찰 포인트 | Haiku |

---

## 9. 비용

**모니터링 에이전트 (Haiku 기반):**
- 일일 8회 호출 (장전 1 + preopen 1 + 정기 4 + 마감 1 + 모닝리포트 텔레그램 0)
- 평균 1,500 input + 400 output = **$0.003/호출**
- **일일 약 $0.025 (월 ~$0.55, 연 ~$6.3)**

**모닝리포트 (Opus, 기존):**
- 일일 1회, $0.49
- 월 $10.78, 연 $123.52

**합계: 약 $129/년**

---

## 10. 관련 파일

### BIP-Pipeline
- `airflow/dags/dag_market_monitor.py` — DAG 정의 (4개)
- `airflow/dags/reports/market_monitor.py` — 체크리스트 상태 표시/발송
- `airflow/dags/stock_loader/dag_indicator_context_snapshot.py` — 스냅샷 계산
- `airflow/dags/utils/audited_llm.py` — 감사 로그 래퍼
- `postgres/monitor_tables.sql` — monitor_checklist, monitor_alerts
- `postgres/analytics_tables.sql` — indicator_context_snapshot, macro_indicators 인덱스

### BIP-Agents
- `langgraph/api.py` — FastAPI 서버 (감사 메타 응답)
- `langgraph/checklist_main.py` — 진입점
- `langgraph/checklist_graph.py` — 4단계 그래프 빌드
- `langgraph/checklist_state.py` — 상태 스키마
- `langgraph/checklist_parser.py` — 파서 + 플래너
- `langgraph/checklist_collector.py` — MCP 도구 호출
- `langgraph/checklist_signal.py` — 신호 생성
- `langgraph/checklist_rules.py` — 룰 엔진
- `langgraph/checklist_explainer.py` — Haiku 설명
- `langgraph/preopen_analyzer.py` — 08:40 분석기
- `mcp-servers/bip-stock-mcp/server.py` — MCP 도구 등록
- `mcp-servers/bip-stock-mcp/realtime.py` — 한투/Upbit/yfinance
- `mcp-servers/bip-stock-mcp/context.py` — get_indicator_context
- `mcp-servers/bip-stock-mcp/db.py` — PG 풀

---

## 11. Phase 이력

| Phase | 일자 | 주요 변경 |
|-------|------|----------|
| **Phase 1** | 2026-04-05 | `get_indicator_context` MCP 도구, 복합 인덱스, 에이전트 프롬프트 강화 |
| **Phase 2** | 2026-04-05 | LangGraph 4단계 분리 (parser/collector/signal/explainer), 룰 엔진, 코드 레벨 도구 강제 |
| **Phase 3** | 2026-04-05 | `indicator_context_snapshot` 테이블, 룰 엔진 모듈 분리, `checklist_rules.py` |
| **Phase 4** | 2026-04-05 | `market_monitor_preopen` DAG, 예상 체결가 MCP 도구, 감사 로그 통합, 주요 종목 10개 확장 |

---

## 12. 결정 로그

**2026-04-05 — 신호 판정을 LLM에서 룰 엔진으로 이관**
- 이유: Codex 검토 결과 단일 ReAct 노드가 임계값 판단을 부정확하게 함 (예: 원/달러 1,510원 = 역대 고점권인데 "1,520 미돌파"만 보고 🟢 판정)
- 해결: deterministic 파서/룰 엔진 분리, LLM은 설명만 담당
- 결과: 재현성 확보, 토큰 사용량 1/4 감소

**2026-04-05 — `get_indicator_context` 도구 추가**
- 이유: 절대 시장 맥락 부재 (임계값 미돌파가 곧 긍정이 아님)
- 해결: 90일 분포 기반 percentile/zscore/drawdown 계산
- 결과: 환율/지수의 절대 수준 판단 가능

**2026-04-05 — 주요 종목 항상 수집 10개로 확장**
- 이유: 삼성전자/SK하이닉스만으로는 시장 전체 파악 부족
- 해결: KOSPI 시총/업종 대표 10개 `ALWAYS_COLLECT_STOCKS` 추가
- 결과: 체크리스트에 없어도 반도체/2차전지/바이오/자동차/IT/소재 전 업종 커버

**2026-04-05 — 08:40 preopen DAG 추가**
- 이유: 08:25 체크리스트 파싱과 09:00 장 시작 사이에 35분 공백
- 해결: 한투 API 예상 체결가(08:30~09:00)를 활용한 갭 방향 분석
- 결과: 장 시작 직전 시장 분위기 파악 가능

---

*이 문서는 BIP-Agents 체크리스트 모니터링 에이전트의 구조와 운영 기준을 설명합니다.*
*보안/메타데이터 거버넌스(`docs/security_governance.md`, `docs/metadata_governance.md`)를 함께 참조하세요.*
