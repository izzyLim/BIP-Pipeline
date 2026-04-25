Deep _Agents_ 기술 가이드 v0.5 · 2026.04 최신

개요

00개요 및 위치 01LangChain · LangGraph 비교 02타 SDK 비교 03언제 쓰는가 04전체 아키텍처

핵심 API

03create_deep_agent() 04미들웨어 스택

컨텍스트 관리

05컨텍스트 타입 06Memory vs Skills 07자동 압축/요약

Backend 시스템

08Backend 종류 09CompositeBackend

SubAgent

10SubAgent 개념 11비동기 SubAgent NEW 12병렬 실행

운영

13Human-in-the-Loop 14MCP 연동 15보안 16Docker 배포 17실전 패턴 ✓체크리스트

LangChain Deep Agents · Technical Guide

# Deep Agents  
기술 가이드

LangChain이 Claude Code에서 영감을 받아 만든 에이전트 하네스. LangGraph 런타임 위에 계획·파일시스템·서브에이전트·장기메모리를 내장하여 복잡한 다단계 작업을 처리합니다.

**버전** v0.5.0a1 (비동기 서브에이전트 프리뷰) **기반** LangChain + LangGraph **라이선스** MIT **설치** pip install deepagents

01LangChain · LangGraph · Deep Agents 비교

## 세 가지는 같은 스택의 다른 레이어

핵심대체 관계가 아닌 계층 관계

세 가지 모두 LangChain이 만들었지만 역할이 완전히 달라요. 서로 대체하는 게 아니라 아래 레이어 위에 쌓이는 구조예요.

Deep Agents SDK  ← 에이전트 하네스 (batteries included)  
        ↑ 위에 구축  
LangGraph        ← 에이전트 런타임 (실행 인프라)  
        ↑ 위에 구축  
LangChain        ← 에이전트 프레임워크 (추상화 레이어) 

### 역할별 상세 비교

구분| LangChain| LangGraph| Deep Agents  
---|---|---|---  
**레이어** | 에이전트 프레임워크 | 에이전트 런타임 | 에이전트 하네스  
**역할** | 모델·툴·루프 추상화 | 그래프 기반 실행 엔진 | 계획·파일시스템·서브에이전트 내장  
**제어 수준** | 높음 (유연) | 매우 높음 (저수준) | 중간 (의견 포함)  
**시작 난이도** | 쉬움 | 중간 | 가장 쉬움  
**플래닝 도구** | 직접 구현 | 직접 구현 | write_todos 내장  
**파일시스템** | 직접 구현 | 직접 구현 | ls/read/write 내장  
**컨텍스트 요약** | 직접 구현 | 직접 구현 | 자동 (85% 도달 시)  
**서브에이전트** | 직접 구현 | 직접 그래프 설계 | task 도구 내장  
**스트리밍** | 지원 | 지원 | LangGraph 상속  
**HITL** | 기본 지원 | interrupt 완전 지원 | interrupt_on으로 선언적  
**배포** | 자유 | LangGraph Platform | LangGraph Platform  
  
### 언제 무엇을 쓰는가

상황| 선택  
---|---  
빠른 에이전트 프로토타입, 단순 툴 호출 루프| LangChain create_agent  
복잡한 상태 그래프, 정밀한 흐름 제어, 결정론적 파이프라인| LangGraph 직접 설계  
계획·파일·서브에이전트가 필요한 다단계 자율 작업| Deep Agents SDK  
온톨로지/시맨틱 레이어 위에서 자유 질의| Deep Agents SDK  
정해진 파이프라인 안에서 Deep Agents 서브루틴| LangGraph + Deep Agents 조합  
  
02Claude Agent SDK · Codex SDK 비교

## 유사한 외부 SDK와의 비교 (공식 문서 기준)

항목| LangChain Deep Agents| Claude Agent SDK| OpenAI Codex SDK  
---|---|---|---  
**주요 용도** | 범용 에이전트 (코딩 포함) | Claude 기반 코딩 에이전트 | 코딩 작업 특화  
**모델 지원** | 모델 무관 (100+ 제공자) | Claude 계열 특화 | OpenAI 모델 특화  
**장기 메모리** | Memory Store (스레드 간) | 없음 | 없음  
**파일시스템 백엔드** | 플러그인형 (State/FS/Store/Composite) | 로컬 | 로컬/클라우드  
**보안 설정** | 툴별 HITL 선언적 설정 | 권한 모드 + Hooks | OS 레벨 샌드박스 모드  
**프론트엔드 연동** | React 통합 지원 | 서버 사이드만 | 서버 사이드만  
**관찰 가능성** | LangSmith 네이티브 | 없음 | OpenAI Traces  
**배포** | LangGraph Platform | 자체 호스팅 | N/A  
**라이선스** | MIT | MIT (Claude Code는 독점) | Apache-2.0  
  
ℹ

**Bedrock 환경에서의 선택** Claude Agent SDK는 Bedrock 환경에서 잘 작동하지만 모델 고정 + 장기 메모리 없음. Deep Agents는 모델 무관이라 Bedrock의 Claude든 다른 모델이든 자유롭게 선택 가능하고 장기 메모리도 내장돼 있어요. 다만 Bedrock에서 LangSmith 연동이 제한될 수 있어 별도 확인이 필요해요.

03언제 쓰는가

## Deep Agents vs LangGraph 직접 설계

핵심Deep Agents는 LangGraph를 대체하지 않아요

Deep Agents는 LangGraph **위에** 구축된 하네스예요. 런타임은 여전히 LangGraph이고, Deep Agents는 반복적으로 구현해야 하는 패턴들(계획, 파일시스템, 서브에이전트, 요약)을 미리 내장해둔 것입니다.

상황| 권장| 이유  
---|---|---  
질문 유형이 예측 가능한 파이프라인| LangGraph 직접 설계| 흐름 제어가 명확해야 할 때  
자유 질의 + 온톨로지/시맨틱 레이어| Deep Agents| LLM이 동적으로 판단해야 할 때  
다단계 리서치·분석 작업| Deep Agents| 계획·서브에이전트 내장 활용  
단순 툴 호출 루프| LangChain create_agent| 오버엔지니어링 방지  
파이프라인 + 자유 판단 혼합| Deep Agents + 내부 LangGraph| 계획/해석은 Deep Agent, 실행은 파이프라인  
  
## 실질적 차이 — 6가지 기준

기준| LangGraph 직접 설계| Deep Agents  
---|---|---  
**실행 흐름** | 코드에 고정 (결정론적) | LLM이 동적으로 결정  
**새 에이전트 추가** | 그래프 노드·엣지 수정 필요 | subagents 목록에 추가만  
**병렬 실행** | 명시적으로 직접 구현 | LLM이 자동으로 병렬 task 호출  
**컨텍스트 관리** | State 직접 설계 | SummarizationMiddleware 자동  
**예측 가능성** | 높음 — 항상 같은 흐름 | 낮음 — LLM 판단에 따라 다름  
**디버깅** | 쉬움 — 흐름 추적 명확 | 어려움 — LLM이 왜 그렇게 했는지?  
  
⚠ 주의결정론적 파이프라인에 Deep Agents를 쓰면 위험한 이유

TradingAgents처럼 **실행 순서가 중요한 시스템** 에서 Deep Agents를 쓰면 LLM이 스스로 판단해서 단계를 건너뛸 수 있어요.

예를 들어 LLM이 "오늘은 리스크 팀 검토 생략해도 될 것 같은데?"라고 판단하거나, 토론 없이 바로 트레이더로 넘어가는 식이에요. 금융 시스템처럼 특정 단계가 반드시 실행되어야 하는 경우에는 이런 비결정성이 치명적이에요.

→ **순서가 중요한 파이프라인 = LangGraph, 자유로운 탐색/분석 = Deep Agents**

## 혼합 패턴 — Deep Agents + LangGraph 조합

패턴상위는 Deep Agents, 내부 실행은 LangGraph

두 가지를 따로 쓰는 게 아니라 **조합** 하면 각각의 장점을 모두 취할 수 있어요.

Deep Agents가 "어떤 분석이 필요한지, 어떤 순서로 접근할지" 상위 레벨을 판단하고, 실제 결정론적 실행은 LangGraph 파이프라인 서브에이전트에 위임하는 패턴이에요.

PYTHONCompiledSubAgent로 LangGraph 그래프를 서브에이전트로 등록
    
    
    from deepagents import create_deep_agent, CompiledSubAgent
    from langchain.agents import create_agent
    
    # ① LangGraph로 결정론적 파이프라인 구성
    #    (Analyst → Researcher → Trader → Risk → FundManager 고정 흐름)
    trading_pipeline = create_agent(
        model=model,
        tools=trading_tools,
        prompt="트레이딩 분석 파이프라인. 반드시 전체 단계를 순서대로 실행."
    )
    
    # ② LangGraph 그래프를 CompiledSubAgent로 래핑
    trading_subagent = CompiledSubAgent(
        name="trading-pipeline",
        description="종목 심층 분석. 펀더멘털→리서처→트레이더→리스크 전체 파이프라인 실행",
        runnable=trading_pipeline   # ← 컴파일된 LangGraph 그래프
    )
    
    # ③ Deep Agents가 상위 오케스트레이터로 동작
    orchestrator = create_deep_agent(
        model="claude-sonnet-4-6",
        subagents=[trading_subagent],
        system_prompt="""당신은 포트폴리오 분석 조율자예요.
    
        사용자의 요청을 분석해서:
        - 심층 종목 분석이 필요하면 → trading-pipeline 서브에이전트 호출
        - 여러 종목 비교가 필요하면 → 병렬로 여러 task 동시 호출
        - 시장 개요 질문이면 → 직접 답변
    
        서브에이전트의 실행 순서는 건드리지 마세요. 내부 파이프라인이 알아서 처리해요.
        """,
        backend=backend,
    )
    
    # 사용: 자유로운 자연어 요청 → 오케스트레이터가 판단 → 파이프라인 실행
    result = orchestrator.invoke({
        "messages": [{
            "role": "user",
            "content": "NVDA랑 AAPL 비교 분석해줘. 어디에 투자하는 게 나을지"
        }]
    })
    # → 오케스트레이터가 두 종목을 병렬로 trading-pipeline에 위임
    # → 각 파이프라인은 결정론적으로 전체 단계 실행
    # → 결과를 받아 비교 분석 종합

레이어| 담당| 특징  
---|---|---  
**Deep Agents (상위)** | 어떤 분석이 필요한지 판단, 병렬 호출 여부 결정, 결과 종합 | 자유로운 자연어 요청 처리  
**LangGraph (내부)** | 결정론적 파이프라인 실행, 단계 보장 | 순서·안전성 보장  
  
💡

**BIP-Pipeline에 적용한다면** NL2SQL + 수요예측 파이프라인은 LangGraph로 결정론적으로 구성하고, "아이폰 vs 갤럭시 비교 분석해줘" 같은 자유로운 분석 요청은 Deep Agents 오케스트레이터가 받아서 필요한 파이프라인들을 병렬로 호출하는 패턴이 자연스러워요.

04전체 아키텍처

## 계층 구조

사용자 요청 → Deep Agent (create_deep_agent)

↓ Middleware Stack 처리

TodoList MW Filesystem MW SubAgent MW Summarization MW PromptCaching MW

↓ Backend 라우팅

StateBackend FilesystemBackend StoreBackend CompositeBackend

↓ LangGraph 런타임 (스트리밍, 체크포인팅, HITL)

ℹ

**Claude Code에서 영감** Deep Agents는 Claude Code가 단순 코딩을 넘어 범용으로 쓰이는 이유를 분석해서 만들었어요. Claude Code의 4가지 핵심 — 상세 시스템 프롬프트, no-op 플래닝 툴, 서브에이전트, 파일시스템 — 을 일반화한 것입니다.

03create_deep_agent() API

## 함수 시그니처 및 파라미터

PYTHON기본 사용법
    
    
    from deepagents import create_deep_agent
    from langchain.chat_models import init_chat_model
    
    # 최소 구성 (기본값: Claude Sonnet 4.5)
    agent = create_deep_agent()
    
    # 커스텀 구성
    agent = create_deep_agent(
        model=init_chat_model("claude-sonnet-4-6"),
        tools=[my_tool_a, my_tool_b],
        system_prompt="당신은 데이터 분석 전문가입니다.",
        backend=my_backend,
        subagents=[researcher, coder],
        checkpointer=checkpointer,   # 대화 상태 영속화
        store=store,                 # 스레드 간 영구 메모리
        interrupt_on={"write_file": True},
        debug=True,
        name="DataAnalysisAgent",
    )
    
    # create_deep_agent는 컴파일된 LangGraph 그래프를 반환
    result = agent.invoke({
        "messages": [{"role": "user", "content": "질문"}]
    })

### 핵심 파라미터

파라미터| 타입| 기본값| 설명  
---|---|---|---  
model| str | BaseChatModel| claude-sonnet-4.5| LLM 모델. `"openai:gpt-4o"` 문자열 또는 인스턴스  
tools| Sequence[...]| None| 커스텀 도구 (내장 도구 외 추가)  
system_prompt| str| None| 에이전트 역할 정의. 내장 프롬프트 앞에 삽입  
backend| BackendProtocol| StateBackend| 파일 저장소 백엔드  
subagents| list[SubAgent]| None| 커스텀 서브에이전트 정의  
memory| list[str]| None| 항상 주입되는 AGENTS.md 경로 목록  
skills| list[str]| None| 관련성 있을 때만 로드되는 SKILL.md 경로  
checkpointer| Checkpointer| None| 대화 상태 영속화 (thread_id로 재개)  
store| BaseStore| None| 스레드 간 영구 메모리  
interrupt_on| dict[str, bool]| None| HITL 승인 필요 도구 설정  
debug| bool| False| 디버그 모드 (단계별 실행)  
  
### 자동 주입되는 내장 도구

도구| 출처 미들웨어| 기능  
---|---|---  
`write_todos`| TodoListMiddleware| 작업 목록 관리 (no-op, 컨텍스트 엔지니어링용)  
`ls`| FilesystemMiddleware| 디렉토리 조회  
`read_file`| FilesystemMiddleware| 파일 읽기 (offset/limit 페이지네이션)  
`write_file`| FilesystemMiddleware| 새 파일 생성  
`edit_file`| FilesystemMiddleware| 기존 파일 편집 (문자열 치환)  
`glob`| FilesystemMiddleware| 패턴으로 파일 검색  
`grep`| FilesystemMiddleware| 파일 내용 검색  
`execute`| FilesystemMiddleware| 셸 명령 실행 (SandboxBackend 필요)  
`task`| SubAgentMiddleware| 서브에이전트 호출  
  
04미들웨어 스택

## 자동 적용 순서 (외부 → 내부)

8HumanInTheLoopMiddlewareinterrupt_on 설정 시에만 활성화선택

7User Middleware사용자 정의 미들웨어선택

6PatchToolCallsMiddlewaredangling tool call 자동 수리자동

5AnthropicPromptCachingMiddleware시스템 프롬프트 자동 캐싱 → 비용 절감자동

4SummarizationMiddleware컨텍스트 85% 도달 시 자동 요약자동

3SubAgentMiddlewaretask 도구 + 서브에이전트 생성자동

2FilesystemMiddleware파일시스템 도구 + 대용량 결과 자동 처리자동

1TodoListMiddlewarewrite_todos 도구 (no-op, 계획 수립용)자동

💡

**FilesystemMiddleware 대용량 처리** 도구 결과가 80,000자(기본값) 초과 시 `/large_tool_results/{id}`에 자동 저장하고, 에이전트에는 처음 10줄 + 파일 참조만 전달해요. 에이전트가 `read_file`로 페이지네이션 읽기 가능.

05컨텍스트 타입

## 5가지 컨텍스트 레이어

타입| 제어 방법| 범위| 특징  
---|---|---|---  
**Input context**|  system_prompt, memory, skills| 정적 / 매 실행| 시작 시 주입  
**Runtime context**|  invoke 시 context 파라미터| 실행당| 서브에이전트에 자동 전파  
**Context compression**|  SummarizationMiddleware 자동| 자동| 한계 도달 시 자동 압축  
**Context isolation**|  SubAgent task 도구| 서브에이전트별| 메인 컨텍스트 오염 방지  
**Long-term memory**|  StoreBackend + /memories/ 경로| 스레드 간 영구| 대화 종료 후도 유지  
  
06Memory vs Skills

## 중요한 구분 — 항상 vs 필요할 때

핵심Memory는 항상, Skills는 관련성 있을 때만

**Memory** — AGENTS.md 파일. 시스템 프롬프트에 **항상** 주입돼요. 온톨로지 구조 요약, 핵심 비즈니스 규칙, 사용자 선호 같은 것을 넣으세요. 최소화가 중요해요.

**Skills** — SKILL.md 파일. 시작 시 frontmatter만 읽고, 관련 질문이 들어올 때만 전체 내용을 로드해요. NL2SQL 방법론, 수요 예측 절차 같은 도메인 지식을 넣으세요. 토큰 절약 효과가 커요.

PYTHONMemory + Skills 설정 예시
    
    
    agent = create_deep_agent(
        model="claude-sonnet-4-6",
    
        # Memory — 항상 주입, 최소한으로 유지
        memory=[
            "/project/AGENTS.md",         # 온톨로지 구조 요약
            "~/.deepagents/preferences.md" # 사용자 선호
        ],
    
        # Skills — 관련성 있을 때만 로드 (토큰 절감)
        skills=[
            "/skills/nl2sql/",      # SQL 관련 질문 시 로드
            "/skills/forecast/",    # 예측 관련 질문 시 로드
            "/skills/shap/",        # SHAP 해석 요청 시 로드
        ],
    
        system_prompt="""
        당신은 스마트폰 수요 데이터 분석 전문가입니다.
    
        ## 온톨로지 구조
        - 제품: Brand → Series → Model
        - 시장: Region → Country → Channel
        - 시간: Year → Quarter → Week
        """
    )

07자동 컨텍스트 압축 및 요약

## SummarizationMiddleware 동작

개념왜 필요한가

온톨로지 기반 자유 질의는 대화가 길어질 수밖에 없어요. Oracle 쿼리 결과, 외부 데이터, 중간 분석 결과가 쌓이다 보면 컨텍스트 창이 넘쳐요.

SummarizationMiddleware는 이를 자동으로 관리해요. 개발자가 신경 쓸 필요가 없어요.

동작 방식트리거 조건 및 커스텀 설정
    
    
    # 기본 동작
    # 컨텍스트의 85% 도달 시 자동 요약
    # 최근 10% 유지, 나머지는 요약으로 압축
    
    # 커스텀 설정 (미들웨어 직접 지정)
    from deepagents.middleware import SummarizationMiddleware
    
    agent = create_deep_agent(
        model=model,
        middleware=[
            SummarizationMiddleware(
                model=model,
                trigger=("fraction", 0.80),  # 80%에서 트리거
                keep=("fraction", 0.15),     # 최근 15% 유지
            )
        ]
    )

💡

**FilesystemMiddleware와 시너지** 대용량 쿼리 결과는 파일로 오프로드되고, SummarizationMiddleware가 오래된 대화를 압축해요. 두 메커니즘이 함께 동작해서 장시간 분석 세션도 안정적으로 유지돼요.

08Backend 시스템

## 4가지 Backend 비교

StateBackend

LangGraph 상태에 파일 저장. 대화 스레드 범위 내 임시 저장. 기본값.

임시기본값빠름

FilesystemBackend

로컬 디스크에 직접 저장. 영구 보존. virtual_mode=True로 경로 격리.

영구디스크보안설정 필요

StoreBackend

LangGraph Store에 저장. 스레드 간 공유. 장기 메모리에 적합.

영구스레드 간 공유

CompositeBackend

경로 접두사 기반으로 여러 Backend 조합. longest-prefix 매칭.

라우팅조합권장

09CompositeBackend 설계

## 경로 기반 스토리지 분리

PYTHON데이터 플랫폼용 CompositeBackend 예시
    
    
    from deepagents.backends import (
        CompositeBackend, StateBackend,
        StoreBackend, FilesystemBackend
    )
    
    backend = CompositeBackend(
        default=StateBackend,   # / 하위 기본 (임시 작업 파일)
        routes={
            "/memories/": StoreBackend,    # 온톨로지 지식 영구 저장
            "/analysis/": FilesystemBackend(
                root_dir="./analysis_workspace",
                virtual_mode=True,       # 경로 탈출 방지
                max_file_size_mb=10,
            ),
        }
    )
    
    # 라우팅 동작
    # /notes.txt           → StateBackend (임시)
    # /memories/ontology.md → StoreBackend (영구, 스레드 간 공유)
    # /analysis/report.md  → FilesystemBackend (로컬 디스크)

10SubAgent — 컨텍스트 격리

## SubAgent가 해결하는 문제

개념Context Quarantine

Oracle 쿼리, 외부 API 조회, 웹 검색 등 대용량 결과를 메인 에이전트가 직접 처리하면 컨텍스트가 폭발해요. SubAgent는 이 작업을 **독립된 컨텍스트** 에서 처리하고 최종 결과만 메인에 반환해요.

격리되는 상태: `messages`, `todos`, `structured_response`. 파일(files)과 커스텀 상태는 공유돼요.

### 두 가지 SubAgent 타입

타입| 정의 방식| 적합한 경우  
---|---|---  
**SubAgent (dict)**|  딕셔너리로 정의| 대부분의 경우  
**CompiledSubAgent**|  LangGraph 그래프 직접 전달| 복잡한 내부 워크플로우가 필요한 경우  
  
PYTHONSubAgent 정의 및 사용
    
    
    # dict 방식 SubAgent 정의
    nl2sql_agent = {
        "name": "nl2sql-agent",
        "description": "Oracle DB 자연어 쿼리 처리. SQL 생성 및 실행 필요 시 사용",
        "system_prompt": """Oracle 19c SQL 전문가.
        메타데이터 확인 → SQL 생성 → 검증 → 실행 순서 준수.
        FETCH FIRST 사용, 전체 스캔 금지.""",
        "tools": [oracle_query_tool, metadata_lookup_tool],
        "model": "claude-sonnet-4-6",  # 선택적 모델 오버라이드
        "skills": ["/skills/nl2sql/"],   # 이 에이전트만의 Skills
    }
    
    forecast_agent = {
        "name": "forecast-agent",
        "description": "수요 예측 분석. 시계열 예측 및 SHAP 해석 필요 시 사용",
        "system_prompt": "Prophet/XGBoost 기반 수요 예측 전문가...",
        "tools": [load_data_tool, run_model_tool, shap_tool],
        "model": "anthropic/claude-haiku-4-5",  # 저렴한 모델로 비용 절감
    }
    
    agent = create_deep_agent(
        model="claude-sonnet-4-6",
        subagents=[nl2sql_agent, forecast_agent],
        system_prompt="""데이터 분석 오케스트레이터.
        SQL 조회 필요 → nl2sql-agent 위임
        예측 분석 필요 → forecast-agent 위임
        병렬 실행 가능한 경우 동시에 task 호출"""
    )

11비동기 SubAgent v0.5 NEW

## 논블로킹 백그라운드 서브에이전트

NEWv0.5 프리뷰 기능 — 프로덕션 미권장

기존 동기 SubAgent는 완료될 때까지 메인 에이전트를 블록했어요. 긴 분석 작업(수십 초~수 분)에서는 병목이 됐죠.

비동기 SubAgent는 **즉시 task ID를 반환** 하고 백그라운드에서 실행돼요. 메인 에이전트는 계속 사용자와 대화하면서 나중에 결과를 확인할 수 있어요.

기능| 동기 SubAgent| 비동기 SubAgent  
---|---|---  
실행 모델| 완료까지 블록| 즉시 반환, 백그라운드 실행  
중간 업데이트| 불가| update_async_task로 가능  
취소| 불가| cancel_async_task로 가능  
상태| 무상태| 자체 스레드에 상태 유지  
배포 요건| 없음| LangSmith Deployments 필요  
  
PYTHON비동기 SubAgent 설정
    
    
    from deepagents import AsyncSubAgent, create_deep_agent
    
    async_subagents = [
        AsyncSubAgent(
            name="deep-researcher",
            description="장시간 데이터 수집 및 분석. 비동기로 실행됨",
            graph_id="researcher",  # langgraph.json에 등록된 그래프 ID
        ),
    ]
    
    # 비동기 제어 도구 (자동 주입)
    # start_async_task  — 백그라운드 작업 시작 → task ID 반환
    # check_async_task  — 상태 및 결과 확인
    # update_async_task — 실행 중인 작업에 새 지시 전송
    # cancel_async_task — 작업 취소
    # list_async_tasks  — 전체 작업 목록

12병렬 실행 패턴

## LLM이 한 번에 여러 task 호출 → 자동 병렬

동작 원리한 번의 LLM 응답에서 여러 task 호출
    
    
    # "아이폰 vs 갤럭시 비교 분석해줘" 같은 질문에서
    # LLM이 자동으로 병렬 호출 생성
    
    AIMessage(tool_calls=[
        {"name": "task", "args": {
            "description": "아이폰 16 시리즈 판매 데이터 조회",
            "subagent_type": "nl2sql-agent"
        }},
        {"name": "task", "args": {
            "description": "갤럭시 S25 시리즈 판매 데이터 조회",
            "subagent_type": "nl2sql-agent"
        }},
        {"name": "task", "args": {
            "description": "동기간 스마트폰 시장 외부 지표 수집",
            "subagent_type": "general-purpose"
        }},
    ])
    # → 세 서브에이전트 병렬 실행
    # → 각각 독립된 컨텍스트에서 처리
    # → 완료 후 메인 에이전트에 결과 통합

💡

**시스템 프롬프트에 명시하면 더 잘 활용해요** "병렬 실행 가능한 경우 동시에 여러 task를 호출하세요"를 system_prompt에 넣어주면 LLM이 더 적극적으로 병렬화해요.

13Human-in-the-Loop

## 민감한 작업 전 사람 승인

PYTHONinterrupt_on 설정
    
    
    agent = create_deep_agent(
        model=model,
        checkpointer=checkpointer,  # HITL에 checkpointer 필수
        interrupt_on={
            "execute": True,        # 셸 명령 실행 전 승인
            "write_file": True,    # 파일 쓰기 전 승인
            "task": False,          # 서브에이전트 자동 허용
        }
    )
    
    # 스트리밍으로 인터럽트 감지
    for event in agent.stream({"messages": [...]}, stream_mode="updates"):
        if "interrupt" in event:
            approved = get_user_approval(event["interrupt"])
            if not approved:
                break

14MCP 연동

## MCP 서버를 툴로 연결

개념langchain-mcp-adapters 사용

Deep Agents는 `langchain-mcp-adapters`로 MCP 서버를 툴로 연결해요. MCP 서버가 제공하는 툴들이 `tools` 파라미터에 추가돼요.

PYTHONMCP 서버 연동 예시
    
    
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from deepagents import create_deep_agent
    
    # MCP 클라이언트 설정
    async with MultiServerMCPClient({
        "oracle": {
            "command": "python",
            "args": ["mcp_servers/oracle_server.py"],
        },
        "metadata": {
            "url": "http://openmetadata-mcp:8080/sse",
            "transport": "sse",
        },
    }) as client:
        mcp_tools = await client.get_tools()
    
        agent = create_deep_agent(
            model="claude-sonnet-4-6",
            tools=mcp_tools,  # MCP 툴 주입
            subagents=[nl2sql_agent],
            backend=composite_backend,
        )
    
    # CLI에서 MCP 도구 사용 (deepagents 0.4+)
    # deepagent --mcp oracle_server.py --mcp metadata_server.py

15보안 설정

## 방어 계층 및 모범 사례

계층| 메커니즘| 효과  
---|---|---  
입력 검증| `_validate_path()`| .. 경로 탈출, Windows 절대경로 차단  
파일시스템 격리| `virtual_mode=True`| root_dir 외부 접근 불가  
심볼릭 링크| `O_NOFOLLOW`| symlink 따라가기 방지 (Linux/macOS)  
명령 인젝션| Base64 인코딩| 셸 인젝션 방지  
파일 크기| `max_file_size_mb`| 대용량 파일 grep 스킵  
실행 승인| `interrupt_on["execute"]`| 셸 명령 전 사람 확인  
  
⚠

**Windows 환경 주의** Windows에서는 `O_NOFOLLOW`가 지원되지 않아 symlink를 따라가요. Windows 환경에서는 반드시 `virtual_mode=True`를 사용하세요.

16Docker 배포

## 기본 구성 — 일반 Python 앱과 동일

핵심Deep Agents는 pip 패키지 — Docker 구성이 단순해요

Deep Agents는 `pip install deepagents`로 설치되는 일반 Python 패키지예요. 별도 런타임이나 특수 환경이 필요 없어서 Docker 구성이 일반 FastAPI/Python 앱과 거의 동일해요.

단 하나 중요한 주의점: **`/memories/`, `/workspace/` 경로는 반드시 볼륨으로 마운트**해야 해요. 안 하면 컨테이너 재시작 시 장기 메모리가 전부 날아가요.

DOCKERFILE기본 구성
    
    
    # Dockerfile
    FROM python:3.13-slim
    
    WORKDIR /app
    
    COPY requirements.txt .
    RUN pip install deepagents langchain-aws
    
    COPY . .
    
    # 볼륨 마운트 포인트 명시
    VOLUME ["/app/workspace", "/app/memories"]
    
    CMD ["python", "main.py"]

YAMLdocker-compose.yml 기본
    
    
    services:
      deep-agent:
        build: .
        env_file: .env              # API 키 / AWS 자격증명 관리
        volumes:
          - ./workspace:/app/workspace   # FilesystemBackend 로컬 마운트
          - ./memories:/app/memories     # 장기 메모리 영속화 ← 필수!
        ports:
          - "8000:8000"             # FastAPI 등 API 서버로 서빙할 경우

PYTHON컨테이너 내부 Backend 경로 설정
    
    
    from deepagents.backends import CompositeBackend, StateBackend, FilesystemBackend
    
    backend = CompositeBackend(
        default=StateBackend,
        routes={
            # 컨테이너 내부 경로 → 볼륨으로 호스트와 연결
            "/memories/": FilesystemBackend(
                root_dir="/app/memories",   # ← 볼륨 마운트 경로와 일치
                virtual_mode=True
            ),
            "/workspace/": FilesystemBackend(
                root_dir="/app/workspace",  # ← 볼륨 마운트 경로와 일치
                virtual_mode=True
            ),
        }
    )

## Bedrock 환경 (air-gapped / 사내망)

YAMLBedrock 자격증명 주입
    
    
    services:
      deep-agent:
        build: .
        environment:
          - AWS_DEFAULT_REGION=ap-northeast-2
          - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
          - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
        volumes:
          - ./workspace:/app/workspace
          - ./memories:/app/memories

PYTHONBedrock 모델 설정
    
    
    from langchain_aws import ChatBedrock
    from deepagents import create_deep_agent
    
    model = ChatBedrock(
        model_id="anthropic.claude-sonnet-4-6-...",
        region_name="ap-northeast-2"
    )
    
    agent = create_deep_agent(
        model=model,
        backend=backend,
        system_prompt="...",
    )

💡

**air-gapped 환경 완전 구성** Bedrock + Ollama 조합이면 외부 인터넷 없이 완전 내부망에서 동작하는 Deep Agents 컨테이너를 만들 수 있어요. Bedrock은 VPC 엔드포인트로, Ollama는 내부 GPU 서버에 배포해서 연결하면 돼요.

## Ollama 로컬 모델 프로파일 구성

YAMLOllama 프로파일 포함 전체 구성
    
    
    services:
      # 기본 실행 (외부 API)
      deep-agent:
        build: .
        env_file: .env
        volumes:
          - ./workspace:/app/workspace
          - ./memories:/app/memories
    
      # Ollama 로컬 모델 사용 시
      deep-agent-ollama:
        build: .
        environment:
          - LLM_PROVIDER=ollama
          - OLLAMA_BASE_URL=http://ollama:11434
        volumes:
          - ./workspace:/app/workspace
          - ./memories:/app/memories
        depends_on:
          - ollama
    
      # Ollama 서버
      ollama:
        image: ollama/ollama
        volumes:
          - ollama_data:/root/.ollama
        ports:
          - "11434:11434"
    
    volumes:
      ollama_data:

### 실행 방법

BASH프로파일별 실행
    
    
    # 기본 실행 (외부 LLM API)
    docker compose run --rm deep-agent
    
    # Ollama 로컬 모델로 실행
    docker compose --profile ollama run --rm deep-agent-ollama
    
    # LangSmith 트레이싱 추가 (환경변수만 추가)
    LANGSMITH_TRACING=true \
    LANGSMITH_API_KEY=your-key \
    docker compose run --rm deep-agent

## 구성 정리

항목| 내용| 비고  
---|---|---  
**Docker 가능 여부**|  ✅ 일반 Python 앱과 동일| 별도 런타임 불필요  
**/memories/ 볼륨**|  ⚠️ 필수| 없으면 재시작 시 장기 메모리 소실  
**/workspace/ 볼륨**|  ⚠️ 권장| 분석 작업 파일 영속화  
**Bedrock 연동**|  ✅ 환경변수 주입| AWS 자격증명 env로 전달  
**Ollama 로컬 모델**|  ✅ 별도 컨테이너| API 비용 없음, RAM 8GB+ 필요  
**LangSmith 연동**|  ✅ 환경변수만| LANGSMITH_API_KEY 추가  
**virtual_mode**|  필수 설정| 컨테이너 탈출 방지  
  
17실전 패턴

## 온톨로지 기반 데이터 플랫폼 전체 구성

PYTHONBIP-Pipeline 스타일 구성 예시
    
    
    from deepagents import create_deep_agent
    from deepagents.backends import CompositeBackend, StateBackend, StoreBackend, FilesystemBackend
    from langchain_aws import ChatBedrock
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.store.memory import InMemoryStore
    
    # 1. Bedrock 모델 설정
    main_model = ChatBedrock(model_id="anthropic.claude-sonnet-4-6...")
    sub_model  = ChatBedrock(model_id="anthropic.claude-haiku-4-5...")
    
    # 2. CompositeBackend 구성
    backend = CompositeBackend(
        default=StateBackend,
        routes={
            "/memories/": StoreBackend,        # 온톨로지 지식 영구 저장
            "/analysis/": FilesystemBackend(
                root_dir="./workspace", virtual_mode=True
            ),
        }
    )
    
    # 3. SubAgent 정의
    nl2sql_subagent = {
        "name": "nl2sql",
        "description": "자연어 → SQL 변환 및 Oracle 실행",
        "system_prompt": "Oracle 19c SQL 전문가...",
        "tools": [oracle_mcp_tool, metadata_mcp_tool],
        "model": sub_model,
        "skills": ["/skills/nl2sql/"],
    }
    
    forecast_subagent = {
        "name": "forecast",
        "description": "수요 예측 모델 실행 및 SHAP 해석",
        "system_prompt": "Prophet/XGBoost 수요 예측 전문가...",
        "tools": [data_load_tool, model_run_tool, mlflow_tool],
        "model": sub_model,
        "skills": ["/skills/forecast/", "/skills/shap/"],
    }
    
    # 4. 메인 에이전트 구성
    agent = create_deep_agent(
        model=main_model,
        subagents=[nl2sql_subagent, forecast_subagent],
        backend=backend,
        memory=["/project/AGENTS.md"],
        skills=["/skills/domain-knowledge/"],
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
        interrupt_on={"execute": True},
        system_prompt="""스마트폰 수요 데이터 분석 전문가.
    
    ## 온톨로지 구조
    - 제품: Brand → Series → Model
    - 시장: Region → Country → Channel
    
    ## 위임 전략
    - SQL 조회 필요 → nl2sql 서브에이전트
    - 예측/SHAP 필요 → forecast 서브에이전트
    - 독립적 작업은 병렬로 동시 task 호출
    - 온톨로지 개념 확인 필요 → /memories/ 파일 참조
    """,
    )
    
    # 5. 실행 (thread_id로 대화 연속성 유지)
    config = {"configurable": {"thread_id": "user_session_001"}}
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "지난 분기 아이폰 vs 갤럭시 판매 비교해줘"}]},
        config=config
    )

### 장기 메모리 구성 (대화 간 지식 유지)

PYTHON스레드 간 메모리 설정
    
    
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore
    
    # 프로덕션용 영구 저장소
    checkpointer = PostgresSaver.from_conn_string("postgresql://...")
    store = PostgresStore.from_conn_string("postgresql://...")
    
    agent = create_deep_agent(
        model=model,
        checkpointer=checkpointer,
        store=store,
        backend=CompositeBackend(
            default=StateBackend,
            routes={"/memories/": StoreBackend}
        ),
        system_prompt="""중요한 발견은 /memories/ 에 저장해줘.
        예: /memories/ontology-updates.md, /memories/model-decisions.md"""
    )

✓구현 체크리스트

기본 설정

  * `pip install deepagents` 설치
  * system_prompt에 에이전트 역할 및 온톨로지 구조 정의
  * Memory에 핵심 규칙 (최소화), Skills에 도메인 지식 분리
  * CompositeBackend로 임시/영구/로컬 스토리지 분리



SubAgent 설계

  * SubAgent별 역할을 명확히 분리 (name, description 구체적으로)
  * 각 SubAgent에 최소한의 툴만 할당
  * 비용 최적화: 오케스트레이터 Sonnet, 서브에이전트 Haiku
  * 병렬 실행 권장 내용을 system_prompt에 명시



컨텍스트 관리

  * Memory 파일 최소화 (항상 주입되므로)
  * Skills는 단일 도메인에 집중해서 작성
  * 대용량 결과는 파일로 오프로드 (자동 동작 확인)
  * SummarizationMiddleware 트리거 값 조정 (필요시)



보안 및 운영

  * FilesystemBackend에 `virtual_mode=True` 설정
  * execute 도구에 `interrupt_on` 필수 설정
  * LangSmith 트레이싱 활성화 (LANGSMITH_TRACING=true)
  * checkpointer 설정으로 대화 연속성 확보
  * Bedrock 환경: langchain-aws 사용, Agent Skills API 대신 Skills 파일 사용



Docker 배포

  * `/memories/` 볼륨 마운트 필수 — 없으면 재시작 시 장기 메모리 소실
  * `/workspace/` 볼륨 마운트 권장 — 분석 파일 영속화
  * Backend `root_dir` 경로를 볼륨 마운트 경로와 일치시키기
  * FilesystemBackend에 `virtual_mode=True` 필수 — 컨테이너 탈출 방지
  * Bedrock: AWS 자격증명을 환경변수로 주입 (하드코딩 금지)
  * air-gapped 환경: Bedrock + Ollama 조합으로 완전 내부망 구성



deepagents.guide · v0.5 기준 · 2026.04

LangChain · LangGraph · MIT License
