# LangGraph 멀티 에이전트 전환 기록
> BIP Morning Pulse 리포트 파이프라인 — LangGraph 도입 시행착오 및 실험 결과

---

## 1. 배경 및 목적

### 기존 아키텍처 (llm_analyzer_v2)

기존 모닝 리포트는 단일 LLM 호출 방식이었다.

```
데이터 수집 (macro_collector.py)
    → 프롬프트에 데이터 전부 주입
    → Claude Opus 4.5 단일 호출 (max_tokens=16000)
    → 결과 파싱 → HTML 렌더링 → 메일 발송
```

**한계:**
- 입력 데이터가 많을수록 컨텍스트 오염 (중요 정보가 묻힘)
- 분석 영역별 전문성 부재 (글로벌/한국/반도체를 한 LLM이 모두 처리)
- 실시간 데이터 조회 불가 (모든 데이터를 사전 수집해서 주입)
- 프롬프트 길이 증가에 따른 품질 저하

### LangGraph 도입 목적

- **병렬 분석**: 글로벌/한국/반도체/수급 에이전트를 동시에 실행
- **MCP 연동**: 에이전트가 필요한 데이터를 온디맨드로 직접 조회
- **전문화**: 각 에이전트가 특정 도메인에 집중
- **품질 관리**: Quality Checker로 리포트 품질 자동 검증

---

## 2. 최종 아키텍처

```
parallel_analysis (병렬 실행)
├── global_agent  (Sonnet) — 글로벌 시장, 매크로
├── korea_agent   (Sonnet + MCP ReAct) — 한국 시장, 수급
├── semi_agent    (Sonnet + MCP ReAct) — 반도체 섹터
└── flow_agent    (Haiku) — 수급 분석 보조

aggregator (Opus) — 통합 리포트 작성

quality_checker (Haiku) — 품질 검증
    ↓ FAIL → aggregator 재실행 (최대 2회)
    ↓ PASS

finalize → 결과 반환

report_builder_langgraph.py — HTML 렌더링, 메일 발송
    + Haiku (시장전망/대응시나리오 별도 생성)
```

### MCP 서버 (bip-stock-mcp)

FastMCP SSE 서버로 다음 도구를 제공:

| 도구 | 설명 |
|------|------|
| `db_market_indices` | KOSPI/KOSDAQ/S&P500 등 주요 지수 |
| `db_investor_flow` | 외국인/기관/개인 일별 순매수 집계 |
| `db_investor_trading` | 종목별 수급 TOP5 |
| `db_semiconductor_prices` | DRAM/NAND 현물가 |
| `news_search_naver` | 네이버 뉴스 검색 |
| `news_search_web` | 웹 검색 (SerpAPI) |
| `dart_disclosure_list` | DART 공시 목록 |
| `dart_financial_statement` | DART 재무제표 |
| `dart_corp_search` | 기업 고유번호 검색 |
| `krx_stock_trade_info` | KRX 종목 일별 시세 |
| `krx_market_index` | KRX 지수 |

---

## 3. 단계별 시행착오

### 3-1. 토큰 잘림 문제 (Aggregator Token Truncation)

**증상:** 리포트에서 체크리스트, 시장전망, 대응시나리오 섹션이 누락됨

**원인 분석:**
- Aggregator `max_tokens=6000` 으로 출력이 중간에 잘림
- 여러 에이전트 결과를 통합하면 자연스럽게 출력이 길어짐

**시도한 해결책:**
```
max_tokens: 6000 → 10000 → 16000 → 32000 (모델 최대값)
```

**최종 결론:** API는 `max_tokens`를 반드시 지정해야 하므로 모델 최대값으로 설정.

| 모델 | 최대 출력 토큰 |
|------|-------------|
| claude-opus-4-6 | 32,000 |
| claude-sonnet-4-6 | 64,000 |
| claude-haiku-4-5 | 8,192 |

Korea/Semi ReAct 에이전트도 4096 → 16000으로 상향 (툴 호출 루프 후 최종 리포트 작성 시 잘림 방지).

---

### 3-2. MCP 도구 미호출 문제

**증상:** Korea/Semi 에이전트가 MCP 도구를 전혀 호출하지 않음. 분석 내용은 나오지만 실데이터가 아닌 LLM 내부 지식 기반으로 작성됨.

**원인 분석:**
초기 설계는 데이터를 주입한 후 MCP 도구를 추가로 활용하는 방식이었다.

```python
# 초기 방식 (문제)
prompt = f"{KOREA_PROMPT}\n\n데이터:\n{json.dumps(korea_data)}"
# 이미 데이터가 있으니 LLM이 도구 호출을 생략함
```

**핵심 원인:** LLM은 이미 충분한 데이터가 있다고 판단하면 도구를 호출하지 않는다. ReAct 패턴에서 도구 호출은 LLM의 자율적 판단에 의존하기 때문.

**해결 과정:**

1차 시도: 프롬프트에 "도구를 반드시 호출하세요" 가이드 추가 → 일부 호출하지만 불안정
2차 시도: 데이터 주입 완전 제거 → LLM이 데이터 없이 도구를 **반드시** 호출해야 하는 상황 만들기

```python
# 최종 방식 (해결)
# 데이터 주입 없이 날짜만 전달
report_date = state.get("report_date", "")
prompt = f"{KOREA_PROMPT}\n\n분석 기준일: {report_date}"
```

프롬프트도 "아래 데이터를 분석하세요" → "아래 순서대로 도구를 호출하여 수집하세요"로 변경:

```
분석 순서:
1. `db_market_indices` 호출 — KOSPI/KOSDAQ 등락 확인
2. `db_investor_flow` 호출 — 외국인/기관/개인 순매수 집계 확인
3. `db_investor_trading` 호출 — 종목별 수급 상세 확인
4. `news_search_naver`로 시장 배경 뉴스 검색
5. 뉴스에서 특이 이슈 포착 시 추가 조사
```

**결과 확인:** LLM이 자율적으로 생성한 검색 키워드로 뉴스 검색:
- `"미국 이란 전쟁 반도체 헬륨 공급"` (지정학 이슈 감지 후 자율 검색)
- `"구글 터보퀀트 메모리 반도체 영향"` (뉴스에서 포착한 이슈 심층 조사)

이는 하드코딩된 키워드가 아닌 LLM이 맥락을 파악해 생성한 것.

**교훈:**
> ReAct 에이전트에서 도구를 안정적으로 호출시키려면 **데이터를 아예 제거**해서 LLM이 도구를 호출할 수밖에 없는 환경을 만드는 것이 가장 효과적이다.

---

### 3-3. Korea Agent 토큰 폭발 문제

**증상:** Korea 에이전트 입력 토큰이 135,000으로 폭발 → 비용 급등

**원인 분석:**
데이터를 부분적으로만 제거한 중간 상태에서 ReAct 루프가 무한히 실행됨.

```
[1] 사고: 데이터가 있으니 확인해보자
[2] 도구 호출: db_market_indices
[3] 사고: 더 확인해보자
[4] 도구 호출: db_investor_flow
[5] 사고: 데이터가 있는데 왜 아직 분석 안 했지?
... (루프 반복)
```

각 툴 호출 결과가 컨텍스트에 누적되면서 입력 토큰이 계속 증가.

**해결:**
- 데이터 주입을 **완전히** 제거 (부분 제거는 오히려 더 나쁨)
- 프롬프트에 명시적 순서 지정으로 루프 방지

---

### 3-4. Quality Checker 오작동으로 인한 비용 낭비

**증상:** 품질 검증이 계속 FAIL → Aggregator 재실행 → 비용 2배

**원인 분석:**
Quality Checker가 검증하는 필수 5개 섹션 목록이 실제 Aggregator 출력과 불일치.

```python
# Quality Checker가 기대한 섹션
(📌오늘의핵심 / 🌐글로벌 / 🇰🇷한국 / ✅체크리스트 / ⚡시나리오)
#                                                           ↑
#                          이 섹션을 Aggregator에서 이미 제거했음
```

`⚡시나리오(대응시나리오)` 섹션을 Aggregator에서 제거하고 Haiku가 별도 생성하도록 변경했는데, Quality Checker는 여전히 이 섹션을 요구하고 있었음.

**해결:**
```python
# 수정 후 — 실제 존재하는 섹션으로 교체
(📌오늘의핵심 / 🌍글로벌 / 🇰🇷한국 / 🇺🇸미국 / ✅체크리스트)
```

**비용 영향:**
- Aggregator (Opus) 재실행 1회 = 약 $1.71 낭비
- 전체 비용의 약 72%가 Aggregator × 2 실행에서 발생

---

### 3-5. 신호등(🟢🟡🔴) 항상 긍정 표시 문제

**증상:** 시장이 하락해도 신호등이 🟢 또는 🟡로만 표시됨

**원인 분석:**
LLM이 신호등 판단 기준 없이 자체적으로 판단하여 일관성 없는 결과 생성.

**해결 과정:**

1단계: 명시적 판단 기준 추가
```
- 🟢 긍정/강세/호재: 수치가 개선되고 뉴스/정세도 우호적
- 🟡 중립/혼조/불확실: 수치와 맥락이 엇갈리거나 방향이 불분명
- 🔴 부정/약세/악재: 수치 악화 OR 주요 리스크 현재화
```

2단계: `calculate_reference_signals()` 도입 (llm_analyzer_v2에서 차용)

실제 수치 데이터 기반으로 사전 계산된 참고 신호를 LLM에게 힌트로 제공:

```python
# 예시 출력
참고 신호 (수치 기반):
- KOSPI 등락: -1.2% → 🔴
- VIX: 28.5 (>25) → 🔴
- USD/KRW: +0.8% → 🔴
- DRAM DDR5: +0.3% → 🟢
```

```python
# 프롬프트에 주입
아래는 실제 수치 데이터 기반으로 사전 계산된 참고 신호입니다.
최종 신호는 뉴스, 지정학적 맥락, 시장 흐름을 종합해 당신이 직접 판단하세요.
수치 참고값과 다르게 판단했다면 그 이유를 보고서 본문에 반영하세요.

{reference_signals}
```

**설계 철학:**
- 수치만으로 판단 불가능한 경우 존재 (지정학, 정책 기대감 등)
- LLM이 뉴스/맥락까지 종합해서 최종 판단하되, 수치 참고값을 앵커로 제공
- 참고값과 다른 판단을 내릴 경우 보고서에 이유 명시 요구

---

### 3-6. 시장 신호 표시 방식 변경

**초기 LangGraph 방식 (잘못된 설계):**
```
### 🚦 시장 신호       ← 별도 섹션으로 최상단에 배치
- 글로벌: 🟢
- 한국(전일): 🟡
...
```

**문제점:**
- 원본 llm_analyzer_v2와 섹션 구조가 다름
- 리포트 내용 흐름 상 상단에 신호등 섹션이 뜨는 것이 어색
- HTML에서는 별도 파싱해서 표시하는데 LLM 출력에서는 최상단에 있어 이중 구조

**원본 방식 (올바른 설계):**
```
### 🌍 글로벌 정세 & 매크로 환경 [🟡]
### 🇰🇷 [과거] 어제 한국 시장 마감 결과 [🔴]
### 🇺🇸 [최신] 오늘 새벽 미국 시장 마감 결과 [🟢]
### 📈 [전망] 오늘 한국 시장 예상 [🟡]
### 🔬 반도체 섹터 심층 분석 [🟢]
```

- 각 섹션 헤더 끝에 `[🟡]` 형식으로 삽입
- `report_builder_langgraph.py`의 `extract_signals()`가 헤더에서 파싱 후 제거
- HTML 템플릿의 `📡 섹션별 시장 신호` 대시보드로 렌더링

```python
# extract_signals() 로직
signal_map = {
    r'글로벌.*정세|글로벌.*매크로': '글로벌',
    r'한국.*과거|과거.*한국|어제 한국': '한국(전일)',
    r'미국.*최신|최신.*미국|새벽.*미국|미국.*마감': '미국',
    r'한국.*전망|전망.*한국|오늘 한국': '한국(전망)',
    r'반도체.*섹터|반도체.*심층': '반도체',
}
# 헤더에서 [🟡] 파싱 → 제거 → 본문에는 신호등 없이 표시
```

---

### 3-7. 섹션 순서 불일치

**초기 LangGraph Aggregator 섹션 순서:**
```
🚦 시장 신호 (별도 섹션)
📌 오늘의 핵심
🔥 특별 이벤트 ← 글로벌보다 앞에 있었음
🌍 글로벌
🇰🇷 한국
🇺🇸 미국
📈 전망
🔬 반도체
💰 수급 동향 ← 불필요한 섹션
💡 투자 아이디어
📅 이번 주 이벤트
✅ 체크리스트
```

**원본 llm_analyzer_v2 섹션 순서:**
```
📌 오늘의 핵심
🌍 글로벌
🔥 특별 이벤트 (조건부)
🇰🇷 한국
🇺🇸 미국
📈 전망
🔬 반도체
💡 투자 아이디어
📅 이번 주 이벤트
✅ 체크리스트
```

**변경 사항:**
1. `🚦 시장 신호` 별도 섹션 제거 → 헤더 `[🟡]` 방식으로 통합
2. `🔥 특별 이벤트` → `🌍 글로벌` 뒤로 이동
3. `💰 수급 동향` 제거

---

### 3-8. 수급 동향 섹션 중복 문제

**문제:**
수급 관련 내용이 세 곳에 중복:

| 위치 | 방식 | 신뢰성 |
|------|------|--------|
| HTML 투자자 동향 테이블 | DB 직접 쿼리 | ✅ 항상 있음 (결정론적) |
| korea_agent 분석 | MCP 툴 호출 (LLM 결정) | ⚠️ 매번 다를 수 있음 |
| aggregator `💰 수급 동향` | korea/flow 결과 재요약 | ⚠️ 위에 의존 |

**핵심 인사이트:**
> ReAct 에이전트의 도구 호출은 비결정적(non-deterministic)이다. LLM이 "이미 충분한 정보가 있다"고 판단하면 특정 도구를 건너뛸 수 있다. 따라서 수급 데이터처럼 **항상 표시되어야 하는 정보**는 DB 직접 쿼리 기반의 HTML 데이터 테이블로 보장하고, LLM은 해석/분석 역할만 담당해야 한다.

**결론:** `💰 수급 동향` 섹션 제거. HTML 데이터 테이블이 결정론적으로 보장.

---

### 3-9. 시장전망/대응시나리오 분리 (원본 설계 복원)

**초기 LangGraph 설계:** Aggregator가 시장전망 + 대응시나리오까지 모두 생성

**문제:** Aggregator 토큰이 이미 많은데 전망/시나리오까지 추가하면 품질 저하 및 잘림 위험

**원본 파이프라인 설계 복원:**
```python
# 1. Aggregator (Opus): 상세 분석 리포트
ai_analysis = run_langgraph_analysis(macro_data, news_context)

# 2. Haiku: 분석 내용을 읽고 시장전망/대응시나리오 요약 생성
insight_text = generate_insight_summary(ai_analysis)
# → "📊 오늘의 시장 전망" + "대응 시나리오" 파싱
```

**역할 분리:**
- Opus Aggregator: 팩트 기반 상세 분석
- Haiku: 요약 및 투자자 관점 전망 (빠르고 저렴)

---

## 4. 비용 분석

### 실측 비용 (특정 실행 기준)

| 에이전트 | 입력 토큰 | 출력 토큰 | 모델 | 비용 추정 |
|---------|---------|---------|------|---------|
| global | ~2,000 | ~1,000 | Sonnet | ~$0.02 |
| korea | **71,015** | ~3,000 | Sonnet | ~$0.26 |
| semi | **73,364** | ~2,500 | Sonnet | ~$0.24 |
| flow | ~1,000 | ~500 | Haiku | ~$0.001 |
| aggregator (1회) | ~30,000 | ~8,000 | Opus | ~$0.85 |
| aggregator (2회) | ~30,000 | ~8,000 | Opus | ~$0.85 |
| quality | ~10,000 | ~200 | Haiku | ~$0.008 |
| **합계** | | | | **~$2.39** |

### 비용 구조 분석

```
Opus Aggregator × 2 실행 = $1.70 (총비용의 71%)
Korea ReAct = $0.26 (입력 토큰 폭발 원인: MCP 결과 누적)
Semi ReAct = $0.24
```

### 비용 절감 방향

1. **Quality Checker FAIL 방지** → Aggregator 재실행 제거 → 약 $0.85 절약
   - 필수 섹션 목록을 실제 출력과 정확히 일치시킴
   - 현실적 체크 항목으로 교체

2. **Korea/Semi 입력 토큰 절감**
   - ReAct 루프 최적화 (불필요한 재사고 방지)
   - 툴 결과 요약 전달

3. **모델 조정 고려**
   - Aggregator를 Opus → Sonnet으로 낮추면 약 $0.60 절약
   - 단, 분석 품질 저하 위험 있음

---

## 5. HTML 렌더링 파이프라인

### 추출 흐름

```python
ai_analysis (aggregator 원본 마크다운)
  ↓
extract_key_summary()      # ### 📌 오늘의 핵심 → 상단 강조 박스
  ↓
extract_signals()          # ### 🌍 ... [🟡] → 신호등 대시보드
  ↓
extract_checklist()        # ### ✅ 체크리스트 → 별도 강조 박스
  ↓
convert_markdown_*()       # 나머지 → ai_analysis_html (AI 분석 상세 블록)
```

```python
insight_text (Haiku 원본)
  ↓
outlook_pattern  →  insight_outlook_html  (🔭 오늘의 시장 전망)
scenario_pattern →  insight_scenario_html (🎯 대응 시나리오)
```

### 메일 HTML 최종 섹션 순서

```
1. 📌 오늘의 핵심     (key_summary — LLM 파싱)
2. 🔭 오늘의 시장 전망 (insight_outlook — Haiku)
3. ✅ 체크리스트       (checklist — LLM 파싱)
4. 🎯 대응 시나리오    (insight_scenario — Haiku)
5. 📈 주요 지수        (데이터 테이블)
6. 🌍 매크로 지표      (데이터 테이블)
7. 💰 투자자 동향      (데이터 테이블)
8. 📊 거래량/거래대금  (데이터 테이블)
9. 📡 섹션별 시장 신호 (signals 대시보드)
──── AI 상세 분석 구분선 ────
10. 💡 AI 분석 상세   (ai_analysis_html — 전체 LLM 분석)
11. 📊 수급 상세      (데이터 테이블)
12. 🔧 반도체 현물가  (데이터 테이블)
13. KOSPI/KOSDAQ/S&P500/NASDAQ 히트맵
```

---

## 6. 주요 설계 원칙 (학습 결과)

### 6-1. 데이터 주입 vs 도구 호출

```
❌ 데이터 주입 후 도구 호출 안내
   → LLM이 이미 데이터 있다고 판단, 도구 무시

✅ 데이터 완전 제거 + "도구 호출 순서" 명시
   → LLM이 도구를 반드시 호출해야 하는 환경
```

### 6-2. 결정론적 vs 비결정론적

```
결정론적 (항상 보장)     비결정론적 (LLM 판단)
─────────────────────   ──────────────────────
HTML 데이터 테이블        ReAct 도구 호출 순서
DB 직접 쿼리 결과         LLM 검색 키워드
Reference Signals 계산    특정 도구 호출 여부
```

**원칙:** 항상 보여야 하는 데이터는 결정론적으로 처리. LLM에게 맡기면 매번 다를 수 있음.

### 6-3. 비용 최적화

```
Haiku  : 요약, 검증, 짧은 생성 작업
Sonnet : 도구 호출 + 전문 분석
Opus   : 최종 통합, 복잡한 추론

Quality Checker가 PASS/FAIL을 제대로 하지 못하면
비싼 Opus Aggregator가 재실행됨 → 최대 비용 요인
```

### 6-4. 섹션 구조 일관성

```
원본 llm_analyzer_v2 섹션 순서 = LangGraph aggregator 섹션 순서
                                = HTML 렌더링 파싱 기준

세 가지가 일치해야 파싱 로직이 안정적으로 작동.
```

---

## 7. 현재 상태 및 미해결 과제

### 완료

- [x] ReAct 기반 자율 도구 호출 (korea, semi)
- [x] MCP DB 도구 추가 (investor_flow, investor_trading, semiconductor_prices, market_indices)
- [x] Reference Signals 기반 신호등 판단
- [x] Quality Checker 필수 섹션 목록 실제 출력과 일치
- [x] 섹션 순서 원본과 통일
- [x] 시장신호 표시 방식 원본 방식으로 통일 (헤더 `[🟡]`)
- [x] max_tokens 모델 최대값으로 상향
- [x] `💰 수급 동향` 중복 제거

### 미해결

- [ ] **KOSDAQ 수급 데이터 누락**: `stock_price_1d`의 `foreign_buy_volume`이 KOSDAQ 종목에 대해 NULL인 것으로 추정. `dag_kr_investor_trend.py`의 Naver 스크래핑이 KOSDAQ에 효과적으로 작동하는지 확인 필요.
  ```sql
  SELECT market_type, COUNT(*), COUNT(foreign_buy_volume)
  FROM stock_price_1d p JOIN stock_info si ON p.ticker = si.ticker
  WHERE p.timestamp::date = CURRENT_DATE - 1
  GROUP BY market_type;
  ```

- [ ] **비용 최적화**: 현재 리포트 1회 발송 약 $2.39. Aggregator 재실행 방지로 ~$0.85 절감 기대.

- [ ] **Korea/Semi 입력 토큰 최적화**: ReAct 루프에서 MCP 결과가 컨텍스트에 누적되어 입력 토큰 증가 (각 ~70K). 툴 결과 요약 또는 토큰 윈도우 제한 고려.

---

## 8. 파일 구조

```
BIP-Agents/
├── langgraph/
│   ├── agents.py          # 에이전트 정의 (PROMPTS, nodes)
│   ├── main.py            # 그래프 실행 진입점
│   ├── state.py           # ReportState 정의
│   └── graph.py           # LangGraph 그래프 구성
├── mcp-servers/bip-stock-mcp/
│   ├── server.py          # FastMCP 서버 (도구 등록)
│   ├── db.py              # asyncpg DB 조회
│   ├── dart.py            # DART API
│   ├── krx.py             # KRX/네이버 금융
│   └── news.py            # 뉴스 검색
└── docker-compose.yml     # bip-stock-mcp + langgraph 서비스

BIP-Pipeline/
└── airflow/dags/reports/
    ├── report_builder_langgraph.py  # LangGraph 버전 리포트 빌더
    ├── langgraph_runner.py          # LangGraph 호출 인터페이스
    └── llm_analyzer_v2.py           # 원본 분석기 (Reference Signals 공유)
```
