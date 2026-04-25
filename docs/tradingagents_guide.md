# TradingAgents  
기술 가이드

실제 트레이딩 펌의 구조를 모방한 멀티 에이전트 LLM 금융 트레이딩 프레임워크. 애널리스트, 리서처, 트레이더, 리스크 매니저 에이전트들이 협력하여 시장을 분석하고 트레이딩 결정을 내려요.

LangGraph 기반 멀티 LLM 지원 오픈소스 Apache 2.0 arXiv 2412.20138 Python 3.13+

⚠

**연구 목적 전용** TradingAgents는 연구 목적으로 설계된 프레임워크입니다. 선택된 LLM 모델, 모델 온도, 거래 기간, 데이터 품질 등 다양한 요인에 의해 트레이딩 성능이 달라질 수 있어요. 금융·투자·트레이딩 자문을 의도하지 않습니다.

48K+

GitHub Stars

7

전문 에이전트 역할

6+

지원 LLM 제공자

11+

LLM 호출 / 예측

01업데이트 이력

2026-03

**v0.2.3 릴리스** — 다국어 지원, GPT-5.4 패밀리 모델, 통합 모델 카탈로그, 백테스팅 날짜 정확도 개선, 프록시 지원

2026-03

**v0.2.2 릴리스** — GPT-5.4/Gemini 3.1/Claude 4.6 모델 지원, 5단계 평가 척도, OpenAI Responses API, Anthropic effort control, 크로스 플랫폼 안정성

2026-02

**v0.2.0 릴리스** — 멀티 프로바이더 LLM 지원 (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x) 및 시스템 아키텍처 개선

2026-01

**Trading-R1** 기술 보고서 공개 (arXiv:2509.11420), Terminal 곧 출시 예정

2024-12

**TradingAgents 최초 공개** — arXiv 논문 2412.20138 발표, 오픈소스 전면 공개

02전체 아키텍처

## 외부 데이터 소스 → 에이전트 → 결정

데이터 흐름 전체 개요

flowchart LR subgraph Sources["📡 외부 데이터 소스"] AV["Alpha Vantage\n재무 데이터"] FH["Finnhub\n뉴스·센티먼트"] SM["소셜 미디어\nReddit / Twitter"] CH["차트 데이터\n가격·거래량"] end subgraph Agents["🤖 에이전트 팀"] FA["Fundamentals\nAnalyst"] SA["Sentiment\nAnalyst"] NA["News\nAnalyst"] TA["Technical\nAnalyst"] end subgraph Decision["📋 의사결정 레이어"] RES["Researcher Team\n(Bull vs Bear)"] TR["Trader Agent"] RM["Risk Mgmt"] FM["Fund Manager"] end AV --> FA FH --> NA FH --> SA SM --> SA CH --> TA FA & SA & NA & TA --> RES RES --> TR --> RM --> FM FM -->|승인| OUT["✅ 매수 / 매도 / 보유"] FM -->|거부| BACK["🔄 재검토"] 

## 실제 트레이딩 펌을 모방한 5단계 파이프라인

5단계 트레이딩 결정 파이프라인

flowchart TD subgraph I["I. 애널리스트 팀 — 병렬 실행 ⚡"] direction LR FA["📈 Fundamentals Analyst\n재무제표 · 내재가치"] SA["💬 Sentiment Analyst\n소셜미디어 · 감성분석"] NA["📰 News Analyst\n뉴스 · 거시경제"] TA["📊 Technical Analyst\nMACD · RSI · 차트패턴"] end subgraph II["II. 리서처 팀 — 토론 💬"] direction LR BR["🐂 Bull Researcher\n상승 논거 · 강세론"] BeR["🐻 Bear Researcher\n하락 리스크 · 약세론"] BR <\-->|"⟺ 구조화된 토론 DEBATE"| BeR end subgraph III["III. 트레이더"] TR["💼 Trader Agent\n애널리스트 + 리서처 종합\n매수 / 매도 / 보유 결정"] end subgraph IV["IV. 리스크 관리"] RM["🛡️ Risk Management Team\n변동성 · 유동성 · 포트폴리오 리스크"] end subgraph V["V. 최종 결정"] FM["👔 Fund Manager\n포트폴리오 매니저"] end I -->|"분석 리포트 취합"| II II -->|"균형 잡힌 시장 평가"| III III -->|"결정 제안서"| IV IV -->|"리스크 평가 완료"| V V -->|"승인"| OUT["✅ 주문 실행"] V -->|"거부"| BACK["🔄 재검토 요청"] 

설계 철학왜 멀티 에이전트인가

단일 LLM 시스템은 펀더멘털, 센티먼트, 기술적 분석, 리스크를 동시에 잘 처리하기 어려워요. TradingAgents는 역할을 분리해서 각 에이전트가 자신의 전문 영역에 집중하도록 설계했어요.

특히 Bull/Bear 리서처 간의 **구조화된 토론** 이 핵심 차별점이에요. 단순한 데이터 수집을 넘어 반대 의견을 체계적으로 검토하는 과정이 더 균형 잡힌 결정을 만들어요.

03애널리스트 팀 — 4개 에이전트 병렬 실행

4명의 애널리스트가 **동시에** 시장 정보를 수집해요. 각자 전문 도구와 제약이 있어요.

FUNDAMENTALS ANALYST

펀더멘털 애널리스트

기업 재무제표와 성과 지표를 평가. 내재 가치와 잠재적 리스크 신호를 파악. 수익성, 부채 비율, 현금흐름 중심 분석.

재무제표 주가수익비율 Alpha Vantage

SENTIMENT ANALYST

센티먼트 애널리스트

소셜 미디어와 대중 정서를 감성 점수 알고리즘으로 분석. 단기 시장 분위기 측정. Reddit, Twitter 데이터 활용.

감성분석 소셜 데이터 Finnhub

NEWS ANALYST

뉴스 애널리스트

글로벌 뉴스와 거시경제 지표 모니터링. 이벤트가 시장 상황에 미치는 영향을 해석. 실시간 뉴스 피드 분석.

글로벌 뉴스 거시경제 Alpha Vantage

TECHNICAL ANALYST

기술적 애널리스트

기술 지표(MACD, RSI 등)로 트레이딩 패턴 감지 및 가격 움직임 예측. 차트 패턴, 지지/저항선 분석.

MACD RSI 볼린저밴드 이동평균

04리서처 팀 — Bull vs Bear 토론

BULL RESEARCHER

강세론 리서처

애널리스트 팀의 인사이트를 바탕으로 상승 가능성을 평가. 매수 포지션을 지지하는 논거를 구성하고 방어.

BEAR RESEARCHER

약세론 리서처

동일한 데이터에서 하락 리스크를 발굴. Bull 리서처의 논리를 비판적으로 검토하고 반박 논거 제시.

핵심구조화된 토론 프로토콜

두 리서처는 단순히 정보를 수집하는 게 아니라 **서로 논쟁** 해요. 이 토론 과정이 과도한 낙관론이나 비관론을 걸러내고 균형 잡힌 시장 평가를 만들어요.

토론 라운드 수는 `max_debate_rounds`로 조정 가능해요. 라운드가 많을수록 더 깊은 분석이 가능하지만 LLM 호출 비용이 늘어요.

05트레이더 에이전트

TRADER AGENT

트레이더 에이전트

애널리스트 리포트와 리서처 토론 결과를 종합. 거래 타이밍과 규모를 결정하고 구체적인 매매 신호를 생성. 과거 데이터와 현재 인사이트를 통합하여 매수/매도/보유를 결정.

특징리포트 기반 의사결정

트레이더는 자유로운 자연어 대화보다 **구조화된 애널리스트 리포트** 를 우선 참조해요. 이렇게 하면 핵심 정보가 유실되지 않고 장시간 상호작용에서도 컨텍스트가 유지돼요.

06리스크 관리팀 & 펀드 매니저

RISK MANAGEMENT TEAM

리스크 관리팀

시장 변동성, 유동성, 기타 리스크 요소를 평가하여 포트폴리오 리스크를 지속적으로 모니터링. 트레이딩 전략 조정 후 평가 리포트를 펀드 매니저에게 제출.

변동성 분석 VaR 최대 낙폭

FUND MANAGER (PORTFOLIO MANAGER)

펀드 매니저

리스크 팀의 리포트를 기반으로 거래 제안을 최종 승인 또는 거부. 승인 시 시뮬레이션 거래소에 주문 전달 및 실행.

07에이전트 통신 프로토콜

## 구조화된 출력 + 자연어 토론의 혼합

에이전트 간 통신 흐름

flowchart TD subgraph Analysts["📊 애널리스트 팀 — 병렬 실행"] FA[Fundamentals Analyst] SA[Sentiment Analyst] NA[News Analyst] TA[Technical Analyst] end subgraph Reports["📄 구조화된 분석 리포트"] R1[재무 분석 리포트] R2[감성 분석 리포트] R3[뉴스 분석 리포트] R4[기술 분석 리포트] end subgraph Research["🔬 리서처 팀 — 자연어 토론"] BR["🐂 Bull Researcher"] BeR["🐻 Bear Researcher"] BR <\-->|논쟁 DEBATE| BeR end subgraph Decision["📋 결정 레이어"] TR[Trader Agent] RM[Risk Management Team] FM[Fund Manager] end FA -->|구조화된 리포트| R1 SA -->|구조화된 리포트| R2 NA -->|구조화된 리포트| R3 TA -->|구조화된 리포트| R4 R1 --> Research R2 --> Research R3 --> Research R4 --> Research Research -->|균형 잡힌 평가| TR TR -->|결정 신호 + 근거| RM RM -->|리스크 평가 리포트| FM FM -->|승인 / 거부| 주문실행[🏦 주문 실행] 

상황| 통신 방식| 이유  
---|---|---  
애널리스트 → 트레이더| 구조화된 분석 리포트| 정보 손실 없이 핵심 데이터 전달  
트레이더 → 리스크팀| 결정 신호 + 상세 근거 리포트| 판단 근거의 투명성 확보  
Bull ↔ Bear 리서처| 자연어 토론 (논쟁 형식)| 깊은 추론과 균형 잡힌 시각 형성  
리스크팀 내부| 자연어 토론| 복합적인 리스크 요소 종합 판단  
글로벌 상태 쿼리| 직접 참조| 필요 시 모든 에이전트가 글로벌 상태 직접 접근  
  
💡

**설계 원칙** 이전 프레임워크들이 비구조화 대화에 의존했던 것과 달리, TradingAgents는 구조화된 리포트를 기본 통신 수단으로 사용해요. 자연어 대화는 토론이 필요한 특정 인터랙션(리서처, 리스크팀)에만 제한적으로 활용해요.

08설치

## 3가지 설치 방법

방법 1로컬 설치 (권장)
    
    
    # 1. 클론
    git clone https://github.com/TauricResearch/TradingAgents.git
    cd TradingAgents
    
    # 2. 가상환경 생성 (Python 3.13 필요)
    conda create -n tradingagents python=3.13
    conda activate tradingagents
    
    # 3. 패키지 설치
    pip install .

방법 2Docker 실행
    
    
    # 기본 실행
    cp .env.example .env   # API 키 입력
    docker compose run --rm tradingagents
    
    # Ollama (로컬 모델) 사용 시
    docker compose --profile ollama run --rm tradingagents-ollama

09API 키 설정

환경변수LLM 제공자별 API 키
    
    
    # LLM 제공자 (하나 이상 설정)
    export OPENAI_API_KEY=...          # OpenAI (GPT-5.x)
    export GOOGLE_API_KEY=...          # Google (Gemini 3.x)
    export ANTHROPIC_API_KEY=...       # Anthropic (Claude 4.x)
    export XAI_API_KEY=...             # xAI (Grok 4.x)
    export OPENROUTER_API_KEY=...      # OpenRouter (멀티 모델)
    
    # 금융 데이터 제공자 (하나 필요)
    export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage (무료 티어 가능)
    
    # 또는 .env 파일로 관리
    cp .env.example .env
    # .env 파일에 키 입력

제공자| 환경변수| 지원 모델 (v0.2.3)| 비용 팁  
---|---|---|---  
**OpenAI**| `OPENAI_API_KEY`| GPT-5.4, GPT-5.4-mini| 테스트는 gpt-5.4-mini 권장  
**Anthropic**| `ANTHROPIC_API_KEY`| Claude 4.6, Claude 4.6 Haiku| Haiku로 비용 절감  
**Google**| `GOOGLE_API_KEY`| Gemini 3.1, Gemini 3.1 Flash| Flash로 빠른 실행  
**xAI**| `XAI_API_KEY`| Grok 4.x|   
**Ollama**|  불필요| 로컬 모델| API 비용 없음  
  
10CLI 사용법

BASHCLI 실행
    
    
    # 설치된 커맨드 사용
    tradingagents
    
    # 또는 소스에서 직접 실행
    python -m cli.main

CLI 기능인터랙티브 화면에서 선택 가능한 항목

  * **Tickers** — 분석할 종목 코드 (예: NVDA, AAPL, TSLA)
  * **Analysis Date** — 분석 기준 날짜 (백테스팅용)
  * **LLM Provider** — OpenAI, Google, Anthropic, xAI, OpenRouter, Ollama
  * **Research Depth** — 분석 깊이 (깊을수록 LLM 호출 증가)



실행 중 에이전트 진행 상황을 실시간으로 추적하는 인터페이스가 표시돼요.

11Python 패키지 사용

PYTHON기본 사용법
    
    
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
    
    # 기본 설정으로 초기화
    ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())
    
    # 종목 + 날짜로 분석 실행 (forward propagate)
    _, decision = ta.propagate("NVDA", "2026-01-15")
    print(decision)

PYTHON커스텀 설정
    
    
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
    
    config = DEFAULT_CONFIG.copy()
    
    # LLM 설정
    config["llm_provider"]   = "anthropic"       # openai | google | anthropic | xai | openrouter | ollama
    config["deep_think_llm"] = "claude-sonnet-4-6" # 복잡한 추론용 (고비용)
    config["quick_think_llm"]= "claude-haiku-4-5"  # 빠른 작업용 (저비용)
    
    # 에이전트 동작 설정
    config["max_debate_rounds"] = 2   # Bull/Bear 토론 라운드 수
    config["online_tools"]     = True  # 실시간 데이터 수집 여부
    
    ta = TradingAgentsGraph(debug=True, config=config)
    _, decision = ta.propagate("AAPL", "2026-01-15")
    print(decision)

12주요 설정 옵션

설정 키| 기본값| 설명  
---|---|---  
`llm_provider`| `"openai"`| LLM 제공자 선택  
`deep_think_llm`| `"gpt-5.4"`| 복잡한 추론 담당 모델 (리서처, 리스크팀)  
`quick_think_llm`| `"gpt-5.4-mini"`| 빠른 작업 담당 모델 (애널리스트)  
`max_debate_rounds`| `1`| Bull/Bear 토론 라운드 수 (많을수록 깊은 분석, 비용 증가)  
`online_tools`| `True`| 실시간 데이터 수집 활성화 여부  
`backend_url`| 로컬| Ollama 등 로컬 모델 서버 URL  
  
⚡

**비용 주의** 예측 1회당 11+ LLM 호출, 20+ 도구 호출이 발생해요. 테스트 시에는 `quick_think_llm`에 저렴한 모델(Haiku, gpt-5.4-mini)을 사용하고, `max_debate_rounds`를 1로 설정하는 걸 권장해요.

13성능 벤치마크

## 기준 모델 대비 주요 지표 개선 (arXiv 논문 기준)

↑

누적 수익률

Cumulative Returns

↑

샤프 비율

Sharpe Ratio

↓

최대 낙폭

Maximum Drawdown

ℹ

**샤프 비율 해석** 논문 실험에서 샤프 비율이 예상 경험적 범위(SR > 2 = 우수, > 3 = 탁월)를 초과한 구간이 있었어요. 연구팀은 결정 시퀀스를 검토해서 계산 정확성을 확인했고, 해당 기간에 TradingAgents의 풀백이 거의 없었던 것이 원인이라고 설명해요. 결과는 있는 그대로 보고됩니다.

중요성능 가변 요인

  * 선택한 LLM 백본 모델의 품질
  * 모델 temperature 설정
  * 거래 기간 및 시장 환경
  * 데이터 품질 (금융 데이터 API)
  * 기타 비결정론적 요인



14LangGraph 기반 설계

## 유연성과 모듈성을 위한 LangGraph 선택

LangGraph 노드 구성 및 LLM 역할 분리

flowchart LR subgraph Quick["⚡ quick_think_llm\n(빠른 작업 · 저비용)"] FA[Fundamentals Analyst] SA[Sentiment Analyst] NA[News Analyst] TA[Technical Analyst] end subgraph Deep["🧠 deep_think_llm\n(복잡한 추론 · 고비용)"] BR[Bull Researcher] BeR[Bear Researcher] RM[Risk Management] end subgraph Any["🔄 선택 가능"] TR[Trader Agent] FM[Fund Manager] end Quick --> Deep Deep --> Any 

지원 LLM 제공자 및 모델 교체 구조

flowchart LR TG[TradingAgentsGraph] --> LLM{LLM Provider} LLM -->|openai| GPT["GPT-5.4 / GPT-5.4-mini"] LLM -->|anthropic| Claude["Claude 4.6 / Haiku"] LLM -->|google| Gemini["Gemini 3.1 / Flash"] LLM -->|xai| Grok["Grok 4.x"] LLM -->|openrouter| OR["멀티 모델 라우팅"] LLM -->|ollama| Local["로컬 모델\n(API 비용 없음)"] 

설계왜 LangGraph인가

TradingAgents는 LangGraph로 구축되어 각 에이전트 역할이 독립적인 노드로 구성돼요. 이 덕분에 특정 에이전트만 교체하거나, 새 역할을 추가하거나, 모델을 바꾸는 작업이 다른 부분에 영향을 주지 않아요.

GPU 없이 API 크레딧만으로 배포 가능. 어떤 로컬 또는 API 접근 가능한 모델로도 교체 가능해서 향후 더 나은 추론 모델이나 금융 특화 모델로 쉽게 업그레이드할 수 있어요.

에이전트 역할| LLM 유형| 이유  
---|---|---  
Bull/Bear 리서처| deep_think_llm| 복잡한 논쟁과 추론 필요  
리스크 관리팀| deep_think_llm| 다차원 리스크 평가  
펀더멘털 애널리스트| quick_think_llm| 데이터 처리 중심  
센티먼트 애널리스트| quick_think_llm| 패턴 인식 중심  
뉴스 애널리스트| quick_think_llm| 텍스트 요약 중심  
기술적 애널리스트| quick_think_llm| 지표 계산 중심  
  
💡

**비용 최적화 전략** 역할별로 다른 모델을 쓰는 게 핵심이에요. 복잡한 추론이 필요한 리서처와 리스크팀에는 비싼 모델, 데이터 처리 중심의 애널리스트에는 저렴한 모델을 배정하면 품질을 유지하면서 비용을 크게 줄일 수 있어요.

15한계 및 주의사항

예측 1회당 LLM 호출 흐름 (11+ calls · 20+ tool calls)

flowchart TD Start([종목 + 날짜 입력]) --> Parallel subgraph Parallel["병렬 실행 — 4 LLM calls"] direction LR A[Fundamentals\nAnalyst] B[Sentiment\nAnalyst] C[News\nAnalyst] D[Technical\nAnalyst] end Parallel --> Debate subgraph Debate["토론 — max_debate_rounds × 2 calls"] direction LR BR["🐂 Bull\nResearcher"] <\-->|논쟁| BeR["🐻 Bear\nResearcher"] end Debate --> TR["Trader Agent\n— 1 call"] TR --> RM["Risk Management\n— 1~2 calls"] RM --> FM["Fund Manager\n— 1 call"] FM --> End(["✅ 최종 결정 반환"]) 

필독실제 투자에 사용하면 안 되는 이유

  * **연구 목적 전용** — 프로덕션 트레이딩 시스템이 아니에요
  * **LLM 비결정성** — 동일 입력에도 매번 다른 결정이 나올 수 있어요
  * **데이터 의존성** — 무료 API 데이터 품질에 크게 의존해요
  * **과거 데이터 편향** — 백테스팅 결과가 미래 성과를 보장하지 않아요
  * **높은 API 비용** — 실시간 운영 시 예측 1회당 상당한 LLM 비용 발생



### 현재 알려진 한계

한계| 상세| 개선 방향  
---|---|---  
LLM 추론 비용| 예측당 11+ LLM 호출, 20+ 도구 호출| 캐싱, 배치 처리 최적화 (예정)  
블랙박스 의사결정| 현재 딥러닝 방식의 복잡한 아키텍처 해석 어려움| 투명성 개선 연구 중  
시장 미시구조 미반영| 주문 실행 비용, 슬리피지 등 미고려| 시뮬레이션 정교화  
  
16기술 스택

## 전체 기술 구성

기술 스택 전체 구성도

flowchart TB subgraph Ext["📡 외부 연동 레이어"] direction LR subgraph DataSrc["금융 데이터"] AV["Alpha Vantage\n재무·뉴스·지표"] FH["Finnhub\n뉴스·감성·실시간"] end subgraph LLMSrc["LLM 제공자"] OAI["OpenAI\nGPT-5.4 / mini"] ANT["Anthropic\nClaude 4.6 / Haiku"] GGL["Google\nGemini 3.1 / Flash"] XAI["xAI\nGrok 4.x"] OLM["Ollama\n로컬 모델"] end end subgraph Core["⚙️ 핵심 프레임워크"] direction TB LC["LangChain\n추상화 레이어"] LG["LangGraph\n에이전트 그래프 실행"] LC --> LG end subgraph App["🤖 TradingAgents 애플리케이션"] direction TB TG["TradingAgentsGraph\n.propagate(ticker, date)"] subgraph AgentNodes["에이전트 노드 (LangGraph)"] direction LR AN["Analyst\nNodes × 4"] RN["Researcher\nNodes × 2"] TN["Trader\nNode"] RMN["Risk Mgmt\nNode"] FMN["Fund Manager\nNode"] end TG --> AgentNodes end subgraph Interface["🖥️ 인터페이스"] direction LR CLI["CLI\npython -m cli.main"] PKG["Python Package\nTradingAgentsGraph()"] DOC["Docker\ncompose run"] end DataSrc --> Core LLMSrc --> Core Core --> App App --> Interface 

### 컴포넌트별 상세

레이어| 컴포넌트| 버전| 역할  
---|---|---|---  
**런타임** | Python | 3.13+ | 전체 실행 환경  
**프레임워크** | LangChain | 최신 | LLM 추상화, 체인 구성, 도구 통합  
LangGraph | 최신 | 에이전트 그래프 실행, 상태 관리, 노드 라우팅  
**LLM 제공자** | OpenAI | GPT-5.4 / mini | 기본 권장 모델 (실험 기준)  
Anthropic | Claude 4.6 / Haiku | v0.2.2부터 공식 지원  
Google | Gemini 3.1 / Flash | v0.2.2부터 공식 지원  
xAI | Grok 4.x | v0.2.0부터 지원  
Ollama | 로컬 모델 자유 선택 | API 비용 없음 · 완전 로컬  
**금융 데이터** | Alpha Vantage | 무료 티어 가능 | 재무제표, 주가, 거시경제 지표  
Finnhub | 무료 티어 가능 | 실시간 뉴스, 감성 데이터  
**배포** | pip install | — | Python 패키지로 직접 설치  
Docker | compose v2 | 컨테이너 실행, Ollama 프로파일 포함  
Conda | — | 가상환경 관리 권장  
**인터페이스** | CLI | python -m cli.main | 인터랙티브 종목·날짜·LLM 선택  
Python API | TradingAgentsGraph | .propagate(ticker, date) 한 줄로 실행  
  
LLM 역할 분리 — 비용 최적화 구조

flowchart LR subgraph DT["🧠 deep_think_llm\n복잡한 추론 · 고비용"] BR["Bull Researcher"] BeR["Bear Researcher"] RM["Risk Management"] end subgraph QT["⚡ quick_think_llm\n빠른 처리 · 저비용"] FA["Fundamentals Analyst"] SA["Sentiment Analyst"] NA["News Analyst"] TA["Technical Analyst"] end subgraph TR["🔄 설정 가능"] T["Trader Agent"] FM["Fund Manager"] end QT -->|"분석 리포트"| DT DT -->|"시장 평가"| TR style DT fill:#181428,stroke:#8858e8 style QT fill:#14181c,stroke:#e8a020 style TR fill:#101828,stroke:#4878e8 

💡

**GPU 불필요** TradingAgents는 모든 LLM을 API로 호출하기 때문에 GPU 없이 API 크레딧만으로 실행할 수 있어요. 단, 로컬 모델(Ollama)을 쓸 때는 충분한 RAM이 필요해요 (7B 모델 기준 8GB+).

17인용 및 링크

## 논문 인용

BIBTEXarXiv 2412.20138
    
    
    @misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework},
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138},
    }

### 주요 링크

[GitHub 레포](<https://github.com/TauricResearch/TradingAgents>) [arXiv 논문](<https://arxiv.org/abs/2412.20138>) [공식 문서](<https://tauricresearch.github.io/TradingAgents/>) [Trading-R1 리포트](<https://arxiv.org/abs/2509.11420>)

ℹ

**Tauric Research** TradingAgents 외에 Trading-R1(RL 기반 트레이딩 모델)도 연구 중이에요. Terminal 제품도 곧 출시 예정. 오픈소스 금융 AI 리서치 커뮤니티에 관심 있다면 GitHub Discussions에 참여할 수 있어요.

tradingagents.guide · v0.2.3 기준 · 2026.04.12

연구 목적 전용 · Apache License 2.0 · TauricResearch
