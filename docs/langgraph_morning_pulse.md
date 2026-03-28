# Morning Pulse LangGraph 고도화 설계

## 1. 현황 및 문제점

### 현재 구조
```
DB 적재 데이터 로드
    ↓
단일 LLM 호출 (analyze_market_v2) — 모든 섹션을 한 번에 분석
    ↓
Haiku 요약 (generate_insight_summary)
    ↓
HTML 렌더링 → 이메일 발송
```

### 한계점
| 문제 | 내용 |
|------|------|
| 단일 컨텍스트 과부하 | 모든 데이터를 하나의 프롬프트에 넣어 분석 품질 저하 |
| 고정 데이터만 사용 | DB에 적재된 데이터 외 실시간 맥락 반영 불가 |
| 품질 검증 없음 | 할루시네이션, 수치 오류 자동 감지 안됨 |
| 섹션별 깊이 불균일 | 중요도와 관계없이 동일한 분석 깊이 |

---

## 2. LangGraph 도입 목표

- **병렬 멀티 에이전트**: 섹션별 전담 에이전트가 동시에 분석
- **ReAct 자율 검색**: DB에 없는 정보는 에이전트가 직접 검색 tool 호출
- **비용 최적화**: 섹션 복잡도에 따라 모델 차별화 (Haiku / Sonnet)
- **품질 검증 루프**: Critic 에이전트가 수치 오류·할루시네이션 감지 후 재분석

---

## 3. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                     LangGraph Graph                      │
│                                                         │
│  [data_loader] ──→ [supervisor]                         │
│                         │                               │
│              ┌──────────┼──────────┬──────────┐         │
│              ↓          ↓          ↓          ↓         │
│       [global_agent] [korea_agent] [semi_agent] [flow_agent] │
│       Sonnet+검색  Sonnet+검색  Haiku+DB   Haiku+DB    │
│              │          │          │          │         │
│              └──────────┴──────────┴──────────┘         │
│                         ↓                               │
│                  [aggregator]  ← Sonnet                 │
│                         ↓                               │
│                 [quality_checker] ← Haiku               │
│                    ↓         ↓                          │
│                 (OK)      (재분석 필요)                  │
│                  ↓              ↓                       │
│           [report_builder]  [supervisor] (최대 2회)     │
│                  ↓                                      │
│              이메일 발송                                 │
└─────────────────────────────────────────────────────────┘
```

---

## 4. 에이전트 상세 설계

### 4-1. Supervisor 에이전트
- **역할**: 전체 흐름 조율, 각 에이전트에 태스크 분배
- **모델**: Claude Haiku (단순 라우팅)
- **입력**: DB 적재 데이터 전체, 날짜/시장 상황
- **출력**: 각 에이전트별 작업 지시 (어떤 추가 검색이 필요한지 포함)

```python
# 예시 출력
{
  "global_agent": {"needs_search": True, "query": "FOMC 최신 발언"},
  "korea_agent":  {"needs_search": True, "query": "외국인 매도 원인"},
  "semi_agent":   {"needs_search": False},
  "flow_agent":   {"needs_search": False},
}
```

---

### 4-2. 글로벌 매크로 에이전트 (global_agent)
- **모델**: Claude Sonnet / GPT-4o
- **담당**: 미국 시장, 글로벌 정세, 매크로 환경
- **DB 데이터**: S&P500, NASDAQ, VIX, 금리, 환율, 원자재
- **Tools**:
  - `search_news(query)`: 실시간 뉴스 검색 (Naver/Serp API)
  - `search_web(query)`: 해외 매크로 이슈 검색
- **출력**: 글로벌 섹션 분석 텍스트 + 신호등

---

### 4-3. 한국 시장 에이전트 (korea_agent)
- **모델**: Claude Sonnet / GPT-4o
- **담당**: KOSPI/KOSDAQ, 섹터, 한국 시장 전망
- **DB 데이터**: 한국 지수, 섹터별 수익률, 야간선물
- **Tools**:
  - `search_news(query)`: 국내 시장 뉴스 검색
  - `query_db(sql)`: 특정 종목 상세 조회
- **출력**: 한국 전일/전망 섹션 + 신호등

---

### 4-4. 반도체 에이전트 (semi_agent)
- **모델**: Claude Haiku (DB 데이터만으로 충분)
- **담당**: DRAM/NAND 현물가, 반도체 섹터 분석
- **DB 데이터**: `macro_indicators` (dram_*, nand_*), 반도체 종목 수급
- **Tools**: 없음 (DB 데이터로 충분)
- **출력**: 반도체 섹션 분석 텍스트 + 신호등

---

### 4-5. 수급 에이전트 (flow_agent)
- **모델**: Claude Haiku
- **담당**: 외국인/기관/개인 투자자 동향, ETF 수급
- **DB 데이터**: `investor_flow`, `investor_trading`
- **Tools**: 없음
- **출력**: 수급 섹션 분석 텍스트

---

### 4-6. Aggregator 에이전트
- **모델**: Claude Sonnet
- **역할**: 4개 에이전트 결과를 하나의 일관된 리포트로 통합
- **입력**: 각 에이전트 출력 텍스트
- **출력**: 통합 분석 + 오늘의 핵심 + 체크리스트 생성

---

### 4-7. Quality Checker 에이전트
- **모델**: Claude Haiku
- **역할**: 수치 오류·할루시네이션 감지, 품질 점수 평가
- **체크 항목**:
  - 제공된 수치와 분석 내 수치 일치 여부
  - 신호등 5개 모두 존재 여부
  - 필수 섹션 누락 여부
- **출력**: `{"ok": true}` 또는 `{"ok": false, "issues": [...]}`
- **재분석**: 최대 2회까지 supervisor로 피드백 전달

---

## 5. 그래프 State 설계

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph

class ReportState(TypedDict):
    # 입력
    macro_data: dict          # DB 적재 데이터
    news_context: str         # 기존 뉴스 RAG 결과

    # Supervisor 지시
    agent_tasks: dict         # 각 에이전트 작업 지시

    # 에이전트 출력
    global_analysis: str
    korea_analysis: str
    semi_analysis: str
    flow_analysis: str

    # 통합 결과
    final_analysis: str
    signals: dict             # 신호등 {"글로벌": "🟢", ...}
    key_summary: str
    checklist: str
    insight_outlook: str
    insight_scenario: str

    # 품질 검증
    quality_ok: bool
    quality_issues: list
    iteration: int            # 재분석 횟수 (최대 2)
```

---

## 6. 비용 최적화 전략

| 에이전트 | 모델 | 예상 토큰 | 비고 |
|---------|------|-----------|------|
| Supervisor | Haiku | ~1K | 라우팅만 |
| global_agent | Sonnet | ~5K in / ~3K out | 검색 포함 |
| korea_agent | Sonnet | ~5K in / ~3K out | 검색 포함 |
| semi_agent | Haiku | ~2K in / ~1K out | DB만 |
| flow_agent | Haiku | ~2K in / ~1K out | DB만 |
| aggregator | Sonnet | ~8K in / ~4K out | 통합 |
| quality_checker | Haiku | ~4K in / ~0.5K out | |

**현재 대비 토큰 증가**: 약 2~2.5배
**품질 향상**: 각 섹션 분석 깊이 대폭 향상
**비용 절감 포인트**: 수급/반도체는 Haiku로 처리 (전체의 ~40%)

---

## 7. Tools 설계

```python
# 검색 도구
@tool
def search_news(query: str) -> str:
    """Naver 뉴스 API로 최신 뉴스 검색"""
    ...

@tool
def search_web(query: str) -> str:
    """SerpAPI로 해외 이슈 검색"""
    ...

@tool
def query_db(sql: str) -> str:
    """stockdb 직접 조회 (SELECT만 허용)"""
    ...
```

---

## 8. 기존 시스템과의 관계

- **기존 DAG 파이프라인**: 그대로 유지 (데이터 적재 담당)
- **LangGraph**: 분석 단계만 교체 (`analyze_market_v2` 대체)
- **이메일/PDF 발송**: 기존 `email_sender`, `pdf_generator` 그대로 사용
- **템플릿**: `morning_report.html` 그대로 사용

```
기존: collect_all_macro_data() → analyze_market_v2() → 발송
신규: collect_all_macro_data() → langgraph_analyze()  → 발송
```

---

## 9. 구현 단계

| 단계 | 내용 | 우선순위 |
|------|------|---------|
| 1 | LangGraph State/Graph 기본 구조 세팅 | 필수 |
| 2 | 에이전트별 프롬프트 분리 (기존 프롬프트 분할) | 필수 |
| 3 | Supervisor → 병렬 에이전트 → Aggregator 연결 | 필수 |
| 4 | search_news tool 연결 (ReAct) | 높음 |
| 5 | Quality Checker + 재분석 루프 | 중간 |
| 6 | query_db tool 연결 | 낮음 |
| 7 | 비용 모니터링 대시보드 | 낮음 |

---

## 10. 예상 효과

- **분석 깊이**: 섹션별 전담 분석으로 현재 대비 질적 향상
- **실시간 대응**: 돌발 이슈를 검색 tool로 즉시 반영
- **안정성**: Quality Checker로 오류 리포트 발송 방지
- **확장성**: 새 섹션 추가 시 에이전트 하나만 추가
