# 체크리스트 모니터링 에이전트 아키텍처

> **작성일:** 2026-04-05 | **최종 수정:** 2026-04-12
> **대상:** BIP-Agents 체크리스트 모니터링 에이전트 (`bip-agents-api`)
> **관련 거버넌스:** `docs/security_governance.md`, `docs/metadata_governance.md`

---

## 1. 개요

장중 체크리스트 모니터링 에이전트는 매일 아침 모닝리포트가 생성한 체크리스트를
하루 동안 추적하고, 시간대별로 텔레그램에 분석 메시지를 발송하는 시스템입니다.

**핵심 원칙 (Phase 5에서 변경):**
- **LLM(Haiku)이 체크리스트를 읽고 필요한 MCP 도구를 직접 선택/호출**
- 키워드 파싱/룰 엔진 불필요 — **새 항목에도 코드 변경 없이 동작**
- 프롬프트로 출력 형식 제어 (각 항목 2줄, 신호등 + 판정)
- percentile/zscore 맥락 분석 불필요 — **현재값 vs 체크리스트 기준 비교만**

---

## 2. Phase 이력

| Phase | 일자 | 주요 변경 |
|-------|------|----------|
| **Phase 1** | 2026-04-05 | `get_indicator_context` MCP 도구, 에이전트 프롬프트 강화 |
| **Phase 2** | 2026-04-05 | LangGraph 4단계 분리 (parser/collector/signal/explainer), 룰 엔진 |
| **Phase 3** | 2026-04-05 | `indicator_context_snapshot` 테이블, 룰 엔진 모듈 분리 |
| **Phase 4** | 2026-04-05 | preopen DAG, 예상 체결가 MCP 도구, 감사 로그, 주요 종목 10개 |
| **Phase 5** | 2026-04-06 | **4단계 파이프라인 폐기 → LLM + MCP 직접 호출로 전환** |
| **Phase 5-1** | 2026-04-06 | 체크리스트 DB 저장을 report_builder에서 직접 (HTML 파싱 제거) |
| **Phase 5-2** | 2026-04-07 | 프롬프트 간소화 (맥락 분석 제거, 현재값 비교만) |
| **Phase 5-3** | 2026-04-07 | 시간대별 user_message 분리 (장전: 한국 주식 조회 불가 명시) |
| **Phase 5-4** | 2026-04-07 | 모닝리포트 모델 Sonnet으로 변경, 체크리스트 HTML 섹션 그룹핑 |
| **Phase 6** | 2026-04-11 | 체크리스트 알림 하이브리드 포맷(체크 결과 + 인사이트), 방향성 규칙(higher_is_risk) 프롬프트 명시, 항목 병합, 09:30 첫 리포트, 도구 호출 상세 로깅 |
| **Phase 6-1** | 2026-04-11 | preopen 예상 체결가 API 교체 (FHKST01010200 output2/antc_cnpr + 시간 가드) |
| **Phase 6-2** | 2026-04-11 | `ALWAYS_COLLECT_STOCKS` 강제 조회 + `resolve_stock_code()` 자동 매칭 + 실시간 스냅샷 에이전트 전달 |
| **Phase 6-3** | 2026-04-13 | 뉴스 다이제스트 파이프라인(`news_digest` 테이블 + 4시간 수집 DAG), 모닝리포트에 48시간 다이제스트 주입, 데이터 신선도 경고(월요일/연휴), data_date 라벨링 규칙(preopen/체크리스트), preopen fallback 강화(stck_prpr 3단계) |

---

## 3. 현재 아키텍처 (Phase 5)

```
Airflow DAG
    ↓
POST /api/checklist/analyze
{checklist_text, time_phase}
    ↓
checklist_agent.py — run_checklist_agent()
    ↓
create_react_agent(Haiku, MCP 도구 44개, 시스템 프롬프트)
    ↓
LLM이 체크리스트를 읽고:
  1. 각 항목에 필요한 도구를 직접 선택
  2. 실시간 데이터 수집 (환율, 지수, 종목, 뉴스 등)
  3. 체크리스트 기준과 현재값 비교
  4. 신호등 판정 + 1줄 분석
    ↓
텔레그램 발송
```

### Phase 2→5 전환 이유

| Phase 2 (4단계 파이프라인) | Phase 5 (LLM 직접 호출) |
|---|---|
| 키워드 파서가 LLM 출력 형식에 의존 → 형식 바뀌면 파싱 실패 | LLM이 텍스트를 직접 이해 → 형식 무관 |
| 항목별 도구 매핑을 코드로 관리 → 새 항목마다 코드 수정 | LLM이 도구를 직접 선택 → 코드 변경 없음 |
| 룰 엔진이 indicator_key별 분기 → 분기 누락 시 "데이터 없음" | LLM이 적절한 도구 호출 → 유연한 대응 |
| 4단계 상태 전달 복잡 | 단일 ReAct 에이전트, 단순 |

---

## 4. 핵심 파일

### checklist_agent.py

```python
async def run_checklist_agent(checklist_text, time_phase):
    # MCP 도구 로드
    mcp_client = MultiServerMCPClient(...)
    tools = await mcp_client.get_tools()

    # Haiku ReAct 에이전트 생성
    agent = create_react_agent(llm, tools, prompt=system_prompt)

    # 실행
    result = await agent.ainvoke({"messages": [user_message]})
```

### 시간대별 동작

| time_phase | user_message 핵심 지시 | 특이사항 |
|---|---|---|
| `pre_market` | "장 시작 전 항목만 확인. 한국 주식 실시간 조회 불가" | EWY, 환율, 뉴스만 사용 |
| `intraday` | "장전 항목 제외, 나머지 전부 확인" | 주요 종목 현재가 포함 |
| `close` | "전체 항목 최종 결과 확인" | 종합 복기 + 내일 관찰 포인트 |

### 프롬프트 구조

```
체크리스트 모니터링 에이전트.

## 작업
체크리스트 항목마다 도구로 현재 데이터를 가져와서 기준과 비교. 그게 전부.

## 도구 매핑
- KOSPI/KOSDAQ → realtime_index
- 환율 → realtime_fx_rate
- 종목 → realtime_stock_price(code:6자리)
- EWY (코스피 전용) → night_futures_ewy
- WTI/유가 → get_indicator_context(indicator_type='commodity_oil')
...

## 출력 형식
각 항목 2줄:
✅ *{항목 요약}*
{신호등} {현재값 vs 기준 비교 1줄}

## 금지
- percentile, zscore 분석
- 추가 섹션/해설
```

---

## 5. 체크리스트 데이터 흐름

```
[모닝리포트 생성] (report_builder.py)
    ↓ extract_checklist() → checklist_raw
    ↓ save_checklist() → monitor_checklist 테이블
    ↓ (HTML 파싱 불필요 — 빌드 시점에 직접 저장)

[체크리스트 파싱 DAG] (08:25 KST)
    ↓ load_checklist() → DB에서 읽기
    ↓ send_checklist_status(override_hour=8) → 장전 분석

[장중 모니터링] (09:00~15:50, 10분 간격)
    ↓ Layer 1: 규칙 기반 이상치 감지 (LLM 없음)
    ↓ 정기 현황 (09:30, 10:00, 12:00, 14:30)
      → send_checklist_status() → BIP-Agents API 호출 → 텔레그램

[장마감] (15:35)
    ↓ send_checklist_status(override_hour=16) → 전체 복기
```

### 체크리스트 HTML 렌더링 (이메일)

모닝리포트 이메일에서 체크리스트는 **섹션별 그룹핑**으로 표시:

```
✅ 오늘의 체크리스트

🌅 장 시작 전
☐ 야간 WTI 선물 확인
☐ 이란 협상 뉴스 확인

📊 장 중
☐ 갭 하락 폭 확인
☐ 외국인 수급 방향

⚠️ 주의 가격 레벨
☐ KOSPI 5,200선 지지
☐ SK하이닉스 850,000원
```

프롬프트에서 "□ 장 시작 전 / □ 장 중 모니터링 / □ 주의 가격 레벨" 3개 섹션 강제.
`report_builder.py`에서 고정 섹션 헤더를 감지해 HTML 그룹핑.

---

## 6. MCP 도구 매핑

### 프롬프트에 명시된 매핑 (LLM이 참조)

| 데이터 | 도구 |
|--------|------|
| KOSPI/KOSDAQ 지수 | `realtime_index` |
| 원/달러 환율 | `realtime_fx_rate` |
| 개별 종목 가격 | `realtime_stock_price(code:6자리)` |
| 코스피 갭 예측 | `night_futures_ewy` (EWY, 코스피 전용) |
| 외국인/기관 수급 | `realtime_investor` |
| BTC/ETH | `crypto_price` |
| S&P500/NASDAQ/Nikkei | `global_index` |
| 뉴스 검색 | `news_search_naver` |
| WTI/유가 | `get_indicator_context(commodity_oil)` |
| 금 | `get_indicator_context(commodity_gold)` |

### 주요 종목 코드 (프롬프트에 포함)

삼성전자=005930, SK하이닉스=000660, LG에너지솔루션=373220, 현대차=005380,
삼성바이오=207940, NAVER=035420, 카카오=035720, 삼성SDI=006400, 기아=000270, POSCO=005490

---

## 7. 발송 스케줄

| 시각 (KST) | DAG | 목적 | LLM |
|-----------|-----|------|-----|
| 08:10 | `morning_report` | 모닝리포트 생성 + 체크리스트 DB 저장 | Sonnet |
| 08:25 | `market_monitor_checklist_parse` | DB에서 체크리스트 읽기 + 장전 분석 발송 | Haiku (에이전트) |
| 08:40 | `market_monitor_preopen` | 예상 체결가 + 갭 방향 분석 | Haiku |
| 09:30 / 10:00 / 12:00 / 14:30 | `market_monitor_intraday` | 정기 체크리스트 현황 | Haiku (에이전트) |
| 09:10~15:50 | `market_monitor_intraday` | 10분 간격 이상치 감지 | 없음 (규칙 기반) |
| 15:35 | `market_monitor_close` | 장 마감 종합점검 | Haiku (에이전트) |

**모든 알림 DAG: `retries: 0`** (중복 발송 방지)

---

## 8. 비용

**모니터링 에이전트 (Haiku 기반):**
- 일일 ~8회 호출
- 입력 ~3,000 토큰, 출력 ~800 토큰 (에이전트가 도구 호출 포함)
- **일일 약 $0.03 (월 ~$0.66)**

**모닝리포트 (Sonnet):**
- 일일 1회, ~$0.10
- 월 $2.20

**합계: 약 $35/년**

---

## 9. 감사 로그 (Security Governance 3-3, 3-4)

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

## 10. 관련 파일

### BIP-Pipeline (Airflow)
- `airflow/dags/dag_market_monitor.py` — DAG 4개 (parse/preopen/intraday/close)
- `airflow/dags/dag_morning_report.py` — 모닝리포트 DAG
- `airflow/dags/reports/market_monitor.py` — 체크리스트 저장/로드, 발송 로직
- `airflow/dags/reports/report_builder.py` — 체크리스트 추출 + DB 저장 + HTML 렌더링
- `airflow/dags/reports/llm_analyzer_v2.py` — 모닝리포트 LLM 프롬프트 (날짜 기반)
- `airflow/dags/reports/templates/morning_report.html` — 이메일 HTML 템플릿

### BIP-Agents (에이전트)
- `langgraph/checklist_agent.py` — **핵심: Haiku + MCP ReAct 에이전트**
- `langgraph/checklist_main.py` — 진입점
- `langgraph/api.py` — FastAPI 서버 (감사 메타 응답)
- `langgraph/preopen_analyzer.py` — 08:40 분석기

### BIP-Agents (MCP 서버)
- `mcp-servers/bip-stock-mcp/server.py` — MCP 도구 등록 (44개)
- `mcp-servers/bip-stock-mcp/realtime.py` — 한투/Upbit/yfinance + EWY data_date
- `mcp-servers/bip-stock-mcp/context.py` — get_indicator_context
- `mcp-servers/bip-stock-mcp/db.py` — PG 풀

### 폐기된 파일 (Phase 2~4, 참조용으로 유지)
- `langgraph/checklist_parser.py` — 키워드 기반 파서 (Phase 5에서 불필요)
- `langgraph/checklist_collector.py` — 코드 레벨 도구 호출 (Phase 5에서 불필요)
- `langgraph/checklist_signal.py` — 룰 엔진 신호 생성 (Phase 5에서 불필요)
- `langgraph/checklist_rules.py` — 판정 규칙 (Phase 5에서 불필요)
- `langgraph/checklist_explainer.py` — Haiku 설명 (Phase 5에서 불필요)
- `langgraph/checklist_graph.py` — 4단계 그래프 빌드 (Phase 5에서 불필요)

---

## 11. 결정 로그

**2026-04-05 — Phase 2: 4단계 파이프라인 도입**
- 이유: Haiku가 임계값 판단을 부정확하게 함 (환율 1,510 역대 고점인데 🟢 판정)
- 해결: deterministic 파서/룰 엔진 분리, LLM은 설명만
- 결과: 재현성 확보, 토큰 1/4 감소

**2026-04-06 — Phase 5: LLM 직접 호출로 전환**
- 이유: 키워드 파서가 LLM 출력 형식 변화에 취약 (□ → `- [ ]` 변경 시 전체 실패)
- 이유: 새 체크리스트 항목(코스피200 선물 수급)에 코드 매핑 누락 → "데이터 없음"
- 해결: 4단계 파이프라인 폐기, Haiku ReAct 에이전트가 도구를 직접 선택
- 결과: 코드 변경 없이 새 항목 대응 가능, 유지보수 대폭 감소

**2026-04-06 — 체크리스트 DB 저장 방식 변경**
- 이전: 모닝리포트 HTML에서 사후 파싱 (HTML 형식 의존, 취약)
- 이후: report_builder에서 LLM 출력 시점에 직접 DB 저장 (형식 무관)

**2026-04-07 — 맥락 분석 제거**
- 이유: 체크리스트는 "오늘 이것들 확인해라"인데 90일 percentile/zscore까지 붙이면 과도
- 해결: 프롬프트에서 맥락 분석 금지, 현재값 vs 기준 비교만
- 결과: 메시지 간결, 토큰 절감

**2026-04-07 — 모닝리포트 모델 Sonnet으로 변경**
- 이유: 3개 모델 비교(Opus/Sonnet/GPT-5.4) 결과 Sonnet이 분석 깊이/비용 대비 최고
- Airflow Variable `llm_model` = `claude-sonnet-4-6`으로 설정

**2026-04-07 — EWY/글로벌 지수에 data_date 추가**
- 이유: 미국 휴장일에 3일 전 EWY 데이터로 "갭 하락 유력" 오판
- 해결: yfinance 응답에 data_date 필드 추가, 프롬프트 날짜도 "어제" → 실제 날짜

**2026-04-07 — S&P500/NASDAQ 0값 수정**
- 이유: 미국 휴장일에 KOSPI 기준 날짜로 JOIN → 미국 데이터 없음 → 0
- 해결: 지수별 각자 최신 날짜로 독립 조회

**2026-04-11 — Phase 6: 체크리스트 알림 가독성 전면 개선**
- 이유: 기존 포맷(항목당 2줄 × 13개 = 40+줄)이 모바일에서 읽기 어려움
- 해결: 하이브리드 포맷(체크 결과 1줄씩 + 📈📉 움직임 + 👀 관찰 포인트), 15~20줄
- 환율/유가 방향성 오판 방지: 프롬프트에 `higher_is_risk` 판정 예시 명시
- 동일 indicator 항목 병합: 모닝리포트 프롬프트 + 에이전트 프롬프트 양쪽 적용
- 첫 리포트 09:00 → 09:30 (수급 첫 집계 대기)

**2026-04-11 — preopen 예상 체결가 API 교체**
- 이유: 기존 `FHKST01010100/antc_cntg_prc`가 08:40에 0 반환 (전 종목 "동시호가 미개시")
- 해결: `FHKST01010200 output2/antc_cnpr` (안정적) + `_is_preopen_window()` 시간 가드
- fallback: antc_cnpr=0이면 기존 API로 재시도

**2026-04-11 — 실시간 스냅샷 에이전트 전달**
- 이유: 에이전트가 도구를 미호출하면 체크리스트 원문의 어제 데이터를 그대로 사용
- 해결: `fetch_market_snapshot()` 결과(지수/환율/수급/종목 10개)를 텍스트로 에이전트에 주입
- "반드시 이 데이터를 기준으로 판단" 지시 포함

**2026-04-13 — 뉴스 다이제스트 파이프라인**
- 이유: 모닝리포트가 생성 시점(08:10)에만 뉴스 수집 → 월요일에 주말 이슈(협상 결렬 등) 누락
- 해결: 4시간마다 뉴스 수집+Haiku 요약(`news_digest` 테이블), 모닝리포트에서 48시간 통합 주입
- 결과: 주말 포함 상시 수집으로 월요일 리포트 뉴스 커버리지 확대

**2026-04-13 — 데이터 신선도 경고 + data_date 라벨링**
- 이유: 월요일 리포트가 금요일 데이터를 "어제"처럼 해석, preopen에서 EWY/수급이 과거 데이터임을 미표시
- 해결: (1) 한국/미국 데이터가 2일 이상 전이면 프롬프트에 신선도 경고 주입, (2) 도구 응답의 data_date가 오늘이 아니면 "(MM/DD 기준)" 라벨 필수
- preopen fallback 3단계: antc_cnpr → antc_cntg_prc → stck_prpr(현재가)

---

*이 문서는 BIP-Agents 체크리스트 모니터링 에이전트의 구조와 운영 기준을 설명합니다.*
*보안/메타데이터 거버넌스(`docs/security_governance.md`, `docs/metadata_governance.md`)를 함께 참조하세요.*
