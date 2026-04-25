_LangGraph_ 기술 가이드 v1.1.7 · 2026.04

개요

00개요 및 위치

핵심 개념

016가지 핵심 개념 02그래프 구축 흐름 03상태 관리 심화

아키텍처 패턴

04멀티 에이전트 패턴 05Supervisor 상세 06Hierarchical 상세

실전

07스트리밍 & UI 08Human-in-the-Loop 09프로덕션 배포

에코시스템

10UI & 개발 도구 11프레임워크 비교 12비용 구조

참고

13참고 자료

LangGraph · Stateful Agent Orchestration Framework

# LangGraph  
기술 가이드

AI 에이전트 워크플로우를 그래프(노드+엣지)로 모델링하는 상태 기반 오케스트레이션 프레임워크. LangChain 위에 구축되었지만 독립적으로도 사용 가능. Klarna, Elastic, Replit 등 프로덕션 검증.

StateGraph Checkpointer Human-in-the-Loop Multi-Agent 29.2K Stars MIT License

## 왜 LangGraph인가?

항목| LangChain (Chain)| LangGraph (Graph)  
---|---|---  
**실행 흐름**|  A → B → C (선형)| 분기, 루프, 병렬 가능  
**상태 관리**|  없음 (입출력 전달만)| 공유 State 객체  
**Human-in-the-Loop**|  수동 구현| 네이티브 interrupt()  
**내구성**|  없음| 체크포인터로 크래시 복구  
**멀티 에이전트**|  어색한 통합| 1등 시민 설계  
**적합 상황**|  단순 RAG, 파이프라인| 복잡한 에이전트, 루프/분기  
  
💡

**판단 기준** 워크플로우에 분기(if-then)나 루프(retry/revise)가 필요하면 LangGraph. 단순 직선 파이프라인이면 LangChain으로 충분.

016가지 핵심 개념

LangGraph 핵심 개념 관계도

graph LR STATE["State\n공유 메모리"] --> NODE["Node\n작업 단위"] NODE --> EDGE["Edge\n흐름 연결"] EDGE --> COND["Conditional Edge\n조건 분기"] COND --> CHECK["Checkpointer\n상태 저장"] CHECK --> HITL["Human-in-the-Loop\n사람 개입"] style STATE fill:#1a2540,stroke:#5a7af0,color:#7a9aff style NODE fill:#102820,stroke:#30c880,color:#50e898 style EDGE fill:#201810,stroke:#e09830,color:#f8b840 style COND fill:#1a1030,stroke:#9060f0,color:#b080ff style CHECK fill:#201010,stroke:#f05050,color:#f08080 style HITL fill:#102028,stroke:#30c8c0,color:#50e8e0 

STATE

State — 공유 메모리

그래프 전체에서 공유되는 메모리 객체. 모든 노드가 읽고 쓴다.
    
    
    class AgentState(TypedDict):
        messages: List[str]    # 대화 이력
        research: str          # 리서치 결과
        draft: str             # 작성된 초안
        iteration: int         # 반복 횟수

NODE

Node — 작업 단위

하나의 작업 단위(함수). State를 받아서 변환 후 반환.
    
    
    def research_agent(state: AgentState):
        result = llm.invoke(state["messages"])
        return {"research": result.content}

EDGE

Edge — 흐름 연결

노드 간 직접 연결. A가 끝나면 B로 이동.
    
    
    workflow.add_edge("researcher", "writer")
    # researcher 완료 → writer 실행

CONDITIONAL EDGE

Conditional Edge — 조건 분기

조건에 따라 다른 노드로 라우팅. 루프의 핵심.
    
    
    def should_revise(state):
        if state["fact_check"] == "FAIL" \
           and state["iteration"] < 3:
            return "writer"
        return "formatter"

CHECKPOINTER

Checkpointer — 상태 저장

매 노드 실행 후 상태 자동 저장. 크래시 복구, 대화 지속.

유형| 용도| 특징  
---|---|---  
`MemorySaver`| 개발| 인메모리, 재시작 시 소멸  
`SqliteSaver`| 경량| 파일 기반, 단일 프로세스  
`PostgresSaver`| 프로덕션| 수평 확장, 다중 인스턴스  
  
HUMAN-IN-THE-LOOP

Human-in-the-Loop — 사람 개입

특정 노드 전에 실행 일시 중지. 사람이 검토/승인 후 재개.
    
    
    # 특정 노드 전 중단
    app = workflow.compile(
        interrupt_before=["fact_checker"]
    )
    
    # 노드 안에서 직접 중단
    decision = interrupt({
        "message": "검토해주세요",
        "actions": ["approve", "reject"]
    })

02그래프 구축 전체 흐름

그래프 구축 5단계

sequenceDiagram participant D as 개발자 participant SG as StateGraph participant N as 노드 등록 participant E as 엣지 연결 participant C as 컴파일 participant R as 실행 D->>SG: StateGraph(AgentState) 생성 D->>N: add_node("name", function) D->>E: set_entry_point + add_edge D->>C: workflow.compile(checkpointer) C-->>R: 실행 가능한 app 반환 R->>R: app.invoke() 또는 app.stream() 

### 완전한 코드 예시: 리서치 → 작성 → 팩트체크 루프

PYTHONStateGraph 전체 구성
    
    
    from langgraph.graph import StateGraph, END
    from typing import TypedDict, List
    
    # 1. State 정의
    class AgentState(TypedDict):
        messages: List[str]
        research: str
        draft: str
        fact_check_result: str
        iteration: int
    
    # 2. 노드 함수
    def researcher(state: AgentState):
        result = llm.invoke(f"조사: {state['messages'][-1]}")
        return {"research": result.content}
    
    def writer(state: AgentState):
        result = llm.invoke(f"작성: {state['research']}")
        return {"draft": result.content,
                "iteration": state["iteration"] + 1}
    
    def fact_checker(state: AgentState):
        result = llm.invoke(f"팩트체크: {state['draft']}")
        return {"fact_check_result": result.content}
    
    # 3. 조건 분기
    def should_revise(state: AgentState):
        if "FAIL" in state["fact_check_result"] \
           and state["iteration"] < 3:
            return "writer"    # 다시 작성
        return END             # 완료
    
    # 4. 그래프 구성
    workflow = StateGraph(AgentState)
    workflow.add_node("researcher", researcher)
    workflow.add_node("writer", writer)
    workflow.add_node("fact_checker", fact_checker)
    
    workflow.set_entry_point("researcher")
    workflow.add_edge("researcher", "writer")
    workflow.add_edge("writer", "fact_checker")
    workflow.add_conditional_edges(
        "fact_checker", should_revise)
    
    # 5. 컴파일 + 실행
    app = workflow.compile()
    result = app.invoke({
        "messages": ["삼성전자 분석해줘"],
        "research": "", "draft": "",
        "fact_check_result": "",
        "iteration": 0,
    })

위 코드의 실행 그래프

graph TD START((시작)) --> R["researcher\n자료 조사"] R --> W["writer\n글 작성"] W --> FC["fact_checker\n팩트체크"] FC -->|"FAIL & iter < 3"| W FC -->|"PASS or iter >= 3"| DONE((종료)) style R fill:#1a2540,stroke:#5a7af0,color:#7a9aff style W fill:#102820,stroke:#30c880,color:#50e898 style FC fill:#201010,stroke:#f05050,color:#f08080 

03상태 관리 심화

## Channel Reducer: 상태 병합 전략

데이터 타입| Reducer| 동작| 예시  
---|---|---|---  
메시지 리스트| `operator.add`| 기존에 추가 (append)| ["A"] + ["B"] = ["A","B"]  
단일 값| 기본 (덮어쓰기)| 최신 값으로 교체| "old" → "new"  
카운터| 커스텀 함수| 누적| lambda old, new: old + new  
  
PYTHONAnnotated Reducer 사용법
    
    
    from typing import Annotated
    import operator
    
    class AgentState(TypedDict):
        messages: Annotated[list, operator.add]  # 누적
        iteration: int                           # 덮어쓰기
        current_agent: str                       # 덮어쓰기

💡

**State 설계 베스트 프랙티스**

  * 플랫 dict 피하기 — 에이전트별 네임스페이스 분리
  * TypedDict 필수 — 타입 체크로 런타임 에러 방지
  * 스키마 변경 주의 — 체크포인트 쌓인 후 스키마 변경 시 호환성 깨짐
  * 최소 필드 — 거대한 State는 직렬화 비용 증가



State 흐름 + 체크포인팅

graph LR INIT["초기 State"] --> N1["Node 1\nstate 변환"] N1 -->|"Reducer 적용"| S1["State 업데이트"] S1 --> N2["Node 2\nstate 변환"] N2 -->|"Reducer 적용"| S2["State 업데이트"] S1 -.->|저장| CP1["Checkpoint 1"] S2 -.->|저장| CP2["Checkpoint 2"] style CP1 fill:#201010,stroke:#f05050,color:#f08080 style CP2 fill:#201010,stroke:#f05050,color:#f08080 

04멀티 에이전트 아키텍처 패턴

SUPERVISOR

Supervisor 패턴

중앙 라우터가 전문 에이전트에 작업 위임. 가장 보편적. BIP 체크리스트 에이전트가 이 패턴.

HIERARCHICAL

Hierarchical 패턴

다계층 관리자 → 팀장 → 작업자 구조. Sub-graph로 팀 단위 격리. 대규모 조직형.

SWARM

Swarm 패턴

에이전트가 자율적으로 다음 에이전트에 작업 전달. 탈중앙 협업. 유연하지만 예측 어려움.

REACT

ReAct 패턴

단일 에이전트가 도구를 자율 선택. create_react_agent()로 즉시 구성. BIP preopen 에이전트.

05Supervisor 패턴 상세

Supervisor 패턴 흐름

graph TD USER["사용자 질문"] --> SUP["Supervisor\n(라우터)"] SUP -->|"코딩"| CODER["Coder Agent"] SUP -->|"리서치"| RES["Researcher Agent"] SUP -->|"데이터"| DATA["Data Analyst"] CODER --> SUP RES --> SUP DATA --> SUP SUP -->|"최종"| ANSWER["최종 답변"] style SUP fill:#1a1030,stroke:#9060f0,color:#b080ff style CODER fill:#102820,stroke:#30c880,color:#50e898 style RES fill:#1a2540,stroke:#5a7af0,color:#7a9aff style DATA fill:#201810,stroke:#e09830,color:#f8b840 

PYTHONSupervisor 구현
    
    
    def supervisor(state: AgentState):
        response = llm.invoke(
            f"이 질문을 어떤 에이전트가 처리해야 할까?\n"
            f"질문: {state['messages'][-1]}\n"
            f"선택지: coder, researcher, data_analyst\n"
            f"에이전트 이름만 답해."
        )
        return {"next_agent": response.content.strip()}
    
    def route_to_agent(state):
        return state["next_agent"]
    
    workflow.add_conditional_edges(
        "supervisor", route_to_agent,
        {"coder": "coder",
         "researcher": "researcher",
         "data_analyst": "data_analyst"}
    )
    # 각 에이전트 완료 → supervisor로 복귀
    workflow.add_edge("coder", "supervisor")
    workflow.add_edge("researcher", "supervisor")

06Hierarchical 패턴 + Sub-graph

계층형 에이전트 구조

graph TD TOP["Top Supervisor"] --> TEAM_A["Team A Leader\n(Sub-graph)"] TOP --> TEAM_B["Team B Leader\n(Sub-graph)"] TEAM_A --> A1["Worker A1"] TEAM_A --> A2["Worker A2"] TEAM_B --> B1["Worker B1"] TEAM_B --> B2["Worker B2"] A1 & A2 --> TEAM_A B1 & B2 --> TEAM_B TEAM_A & TEAM_B --> TOP style TOP fill:#1a1030,stroke:#9060f0,color:#b080ff style TEAM_A fill:#1a2540,stroke:#5a7af0,color:#7a9aff style TEAM_B fill:#102820,stroke:#30c880,color:#50e898 

PYTHONSub-graph 구성
    
    
    # 팀 A의 하위 그래프 (독립 State + 체크포인팅)
    team_a = StateGraph(TeamAState)
    team_a.add_node("worker_a1", worker_a1_fn)
    team_a.add_node("worker_a2", worker_a2_fn)
    team_a_compiled = team_a.compile()
    
    # 메인 그래프에 하위 그래프를 노드로 추가
    main_workflow.add_node("team_a", team_a_compiled)

07스트리밍 & 실시간 UI

모드| 코드| 출력| 용도  
---|---|---|---  
**노드 단위**| `app.stream(state)`| 노드 완료마다 스냅샷| 진행 상황 표시  
**토큰 단위**| `app.astream_events()`| LLM 토큰 하나하나| 실시간 채팅 UI  
**커스텀**| `astream_events + 필터`| 특정 이벤트만| 에이전트별 진행률  
  
토큰 스트리밍 + WebSocket UI 흐름

sequenceDiagram participant U as 사용자 (웹 UI) participant WS as WebSocket participant LG as LangGraph App participant LLM as LLM API U->>WS: 질문 전송 WS->>LG: app.astream_events() LG->>LLM: API 호출 LLM-->>LG: 토큰 스트림 LG-->>WS: on_llm_stream WS-->>U: 실시간 토큰 표시 LG-->>WS: on_chain_end WS-->>U: 노드 완료 표시 

PYTHON토큰 스트리밍 예시
    
    
    # 노드 단위 스트리밍
    for chunk in app.stream(initial_state):
        for node_name, output in chunk.items():
            print(f"[{node_name}] 완료")
    
    # 토큰 단위 스트리밍 (실시간 채팅)
    async for event in app.astream_events(
        initial_state, version="v2"
    ):
        if event["event"] == "on_llm_stream":
            token = event["data"]["chunk"].content
            print(token, end="", flush=True)

08Human-in-the-Loop 심화

Human-in-the-Loop 흐름

sequenceDiagram participant A as Agent participant CP as Checkpointer participant H as Human (UI) A->>A: Node 1 실행 A->>CP: State 저장 A->>A: Node 2 실행 (interrupt_before) A-->>H: "검토해주세요" (일시 중지) Note over H: 사람이 검토/수정/승인 H->>A: 승인 (resume) A->>A: Node 2 실행 재개 A->>CP: State 저장 

패턴interrupt() API (LangGraph 2.0)

예외 기반이 아닌 **명시적 중단점 + 구조화된 페이로드**. 승인 게이트, 콘텐츠 검수, 컴플라이언스 워크플로우에 핵심.
    
    
    def review_node(state):
        decision = interrupt({
            "message": "이 분석 결과를 승인하시겠습니까?",
            "data": state["analysis"],
            "actions": ["approve", "reject", "modify"]
        })
        if decision == "approve":
            return {"approved": True}
        return {"approved": False, "feedback": decision}

09프로덕션 배포

프로덕션 배포 아키텍처

graph TD subgraph Dev["개발"] CODE["코드"] --> TEST["테스트"] TEST --> TRACE["LangSmith\n트레이싱"] end subgraph Deploy["배포"] DOCKER["Docker"] --> PG["PostgreSQL\n체크포인터"] DOCKER --> MONITOR["LangSmith\n모니터링"] end subgraph Scale["스케일링"] LB["로드 밸런서"] --> APP1["인스턴스 1"] LB --> APP2["인스턴스 2"] APP1 & APP2 --> PG_S["PostgreSQL\n(공유)"] end Dev --> Deploy --> Scale style Dev fill:#102820,stroke:#30c880 style Deploy fill:#1a2540,stroke:#5a7af0 style Scale fill:#1a1030,stroke:#9060f0 

항목| 개발| 프로덕션  
---|---|---  
**체크포인터**|  MemorySaver| PostgresSaver 필수  
**타임아웃**|  없음| 노드별 설정 (LLM 지연 대비)  
**루프 제한**|  없음| Circuit Breaker (최대 반복)  
**모니터링**|  print| LangSmith 트레이싱 + 알림  
**에러 처리**|  예외 발생| 노드별 try/catch + 폴백  
**비용**|  무제한| 토큰 카운팅 + 일일 한도  
**보안**|  없음| Guardrail 노드 (PII 필터)  
  
2.0LangGraph 2.0 신기능 (2026)

  * **Guardrail 노드** — 콘텐츠 필터링, 레이트 리밋, 감사 로깅이 1등 시민
  * **MCP 통합** — Model Context Protocol로 외부 도구 표준화 연동
  * **A2A 프로토콜** — Agent-to-Agent 크로스 프레임워크 통신
  * **interrupt() API** — 명시적 중단점 + 구조화된 페이로드



10UI & 개발 도구

## 공식 도구

도구| 유형| 설명  
---|---|---  
**LangGraph Studio**|  IDE| 그래프 시각화, 드래그&드롭, 실시간 디버깅, 노드 상태 검사. 데스크톱 + 웹 (Docker 불필요)  
**LangGraph Builder**|  웹 빌더| [build.langchain.com](<https://build.langchain.com/>) — 브라우저에서 비주얼 그래프 구성  
**Agent Chat UI**|  채팅 UI| [공식 Next.js 채팅 앱](<https://github.com/langchain-ai/agent-chat-ui>) — 아무 LangGraph 서버에 채팅 인터페이스 연결  
**LangSmith**|  모니터링| 트레이싱, 비용 추적, A/B 테스트, 평가 데이터셋  
  
## 채팅 UI 연동

방식| 난이도| 특징  
---|---|---  
**Agent Chat UI** (공식)| 쉬움| LangGraph 전용, 바로 연결. Next.js 기반  
**Open WebUI**|  중간| Pipe/Function으로 LangGraph 서버 연결. 채팅마다 전용 thread 자동 생성. 실시간 스트리밍  
**LobeChat / LibreChat**|  중간| OpenAI 호환 API 래퍼 필요  
**CopilotKit**|  중간| React 컴포넌트로 기존 앱에 채팅 임베딩  
**직접 구현 (React)**|  높음| WebSocket + streamEvents. 완전 커스터마이징  
  
Open WebUI + LangGraph 연동 구조

graph LR USER["사용자"] --> OWUI["Open WebUI"] OWUI -->|Pipe/Function| LGS["LangGraph Server"] LGS --> AGENT["에이전트 그래프"] AGENT --> TOOLS["MCP 도구"] AGENT --> LLM["LLM API"] LGS -->|"thread_id 자동 생성"| PG["PostgreSQL\n체크포인터"] LGS -->|SSE 스트리밍| OWUI style OWUI fill:#1a2540,stroke:#5a7af0,color:#7a9aff style LGS fill:#102820,stroke:#30c880,color:#50e898 style PG fill:#201010,stroke:#f05050,color:#f08080 

ℹ

**Open WebUI 연동 핵심** Open WebUI의 Pipe 기능으로 LangGraph 서버를 직접 연결. 새 채팅마다 전용 thread가 생성되고, 대화 이력은 LangGraph 체크포인터가 관리. OpenAI 호환 래퍼 없이도 연동 가능.

### 커뮤니티 도구

도구| 설명  
---|---  
[LangGraph-GUI](<https://github.com/LangGraph-GUI/LangGraph-GUI>)| 오픈소스 비주얼 노드-엣지 에디터 (로컬 LLM + 온라인 API)  
[Hermes Workspace](<https://github.com/outsourc-e/hermes-workspace>)| 네이티브 웹 워크스페이스 (채팅+터미널+메모리+스킬)  
  
11프레임워크 비교

항목| LangGraph| CrewAI| AutoGen| Hermes  
---|---|---|---|---  
**설계**|  그래프 상태 머신| 역할 기반 팀| 대화 기반 협업| 자기 개선 에이전트  
**상태 관리**|  네이티브| 제한적| 메시지 기반| 3계층 메모리  
**HITL**|  네이티브| 제한적| 가능| 가능  
**체크포인팅**|  내장| 없음| 없음| SQLite  
**스트리밍**|  토큰 레벨| 없음| 제한적| 가능  
**학습/스킬**|  없음| 없음| 없음| 내장  
**프로덕션**|  높음 (Klarna, Elastic)| 중간| 중간| 초기  
**웹 UI**|  Agent Chat UI + Studio| 없음| 없음| OpenAI 호환  
  
12비용 구조

항목| 비용| 설명  
---|---|---  
**LangGraph 라이브러리**|  무료 (MIT)| 오픈소스  
**LLM API**|  모델별 상이| 노드마다 LLM 호출 → 체인보다 비용 높을 수 있음  
**인프라 오버헤드**|  +10~20%| 체크포인팅 PostgreSQL, 상태 직렬화  
**LangGraph Platform**|  유료 (Enterprise)| 셀프호스팅은 무료, 매니지드는 유료  
**LangSmith**|  무료 티어| 프로덕션 모니터링은 유료 플랜 권장  
  
13참고 자료

[GitHub — langchain-ai/langgraph](<https://github.com/langchain-ai/langgraph>) (29.2K stars, MIT)

[공식 문서](<https://docs.langchain.com/oss/python/langgraph/overview>)

[Quickstart 가이드](<https://docs.langchain.com/oss/python/langgraph/quickstart>)

[LangGraph Builder (비주얼 빌더)](<https://build.langchain.com/>)

[Agent Chat UI (공식 채팅 앱)](<https://github.com/langchain-ai/agent-chat-ui>)

[LangGraph Studio (IDE)](<https://docs.langchain.com/langsmith/studio>)

[LangGraph Platform GA 발표](<https://blog.langchain.com/langgraph-platform-ga/>)

[LangGraph in 2026: Multi-Agent Systems (DEV)](<https://dev.to/ottoaria/langgraph-in-2026-build-multi-agent-ai-systems-that-actually-work-3h5>)

[LangGraph Deep Dive (Mager)](<https://www.mager.co/blog/2026-03-12-langgraph-deep-dive/>)

[LangGraph + Open WebUI 연동 (Medium)](<https://medium.com/@davit_martirosyan/integrating-langgraph-agents-into-open-webui-3533cc3a47e1>)

[LangGraph + CopilotKit UI (CopilotKit)](<https://www.copilotkit.ai/blog/easily-build-a-ui-for-your-ai-agent-in-minutes-langgraph-copilotkit>)

langgraph.guide · v1.1.7 기준 · 2026.04.14

MIT License · LangChain
