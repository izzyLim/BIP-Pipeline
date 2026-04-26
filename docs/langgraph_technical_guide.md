# LangGraph 기술 가이드

> **공식 문서:** https://langchain-ai.github.io/langgraph/
> **GitHub:** https://github.com/langchain-ai/langgraph (29.2K+ Stars, MIT License)
> **버전 기준:** langgraph 1.1.x (2026-04)

---

## 1. 개요

### LangGraph란

LangGraph는 LLM 기반 에이전트와 멀티 에이전트 워크플로우를 **그래프(노드 + 엣지)** 로 모델링하는
상태 기반 오케스트레이션 프레임워크다. LangChain 팀이 개발했으며, LangChain 위에 구축되었지만
독립적으로도 사용할 수 있다.

핵심 추상화는 **StateGraph** -- 유한 상태 머신(FSM)의 일반화다.
각 노드는 상태(State)를 읽고 쓰며, 엣지는 다음에 실행할 노드를 결정한다.

### 왜 필요한가

| 요구사항 | 체인 방식 | LangGraph 방식 |
|---------|----------|---------------|
| 조건 분기 (if-then) | 수동 구현, 복잡 | `add_conditional_edges()` 네이티브 |
| 루프 (retry/revise) | 지원 안 됨 | 그래프 사이클로 자연스럽게 표현 |
| 병렬 실행 | 어렵다 | Fan-out/Fan-in 노드로 간단 |
| 상태 관리 | 입출력 전달만 | 공유 State 객체, Reducer로 병합 |
| 크래시 복구 | 없음 | Checkpointer로 자동 저장/복구 |
| 사람 개입 (HITL) | 수동 구현 | `interrupt()` API 네이티브 |
| 멀티 에이전트 | 통합 어려움 | Sub-graph, Supervisor 등 1등 시민 |

### 핵심 철학

1. **제어 가능성(Controllability):** 에이전트의 행동을 개발자가 세밀하게 제어할 수 있어야 한다.
   "마법 같은 자동화"보다 명시적 그래프 구조를 통한 예측 가능한 실행을 선택했다.
2. **내구성(Persistence):** 모든 실행 단계(super step)마다 상태를 자동 저장한다.
   크래시 복구, 대화 이력 관리, 타임 트래블이 내장되어 있다.
3. **사람 참여(Human-in-the-Loop):** 중요한 결정 지점에서 사람이 개입할 수 있어야 한다.
   `interrupt()` API로 실행을 일시 중지하고 승인 후 재개하는 패턴을 네이티브로 지원한다.

> **판단 기준:** 워크플로우에 분기(if-then)나 루프(retry/revise)가 필요하면 LangGraph.
> 단순 직선 파이프라인이면 LangChain이나 LCEL로 충분하다.

---

## 2. 아키텍처

### StateGraph 전체 구조

```mermaid
graph TD
    subgraph StateGraph["StateGraph (그래프 정의)"]
        direction TB
        S["State\n(TypedDict)"]
        N1["Node A\n(Python 함수)"]
        N2["Node B\n(Python 함수)"]
        N3["Node C\n(Python 함수)"]
    end
    subgraph Runtime["Runtime (실행 엔진)"]
        direction TB
        CP["Checkpointer\n(상태 저장)"]
        CH["Channels + Reducers\n(상태 전달/병합)"]
    end
    S --> N1
    N1 -->|"Edge"| N2
    N2 -->|"Conditional Edge"| N3
    N2 -->|"Conditional Edge"| N1
    N1 & N2 & N3 -.-> CP
    S --- CH
    style StateGraph fill:#0d1117,stroke:#5a7af0,color:#c9d1d9
    style Runtime fill:#0d1117,stroke:#30c880,color:#c9d1d9
    style S fill:#1a2540,stroke:#5a7af0,color:#7a9aff
    style CP fill:#201010,stroke:#f05050,color:#f08080
```

### 실행 흐름

```mermaid
sequenceDiagram
    participant U as 호출자
    participant SG as StateGraph
    participant N as 노드 (함수)
    participant R as Reducer
    participant CP as Checkpointer
    U->>SG: invoke(initial_state)
    SG->>N: 진입점 노드 실행 (state 전달)
    N->>R: 반환값을 Reducer로 병합
    R->>CP: 병합된 State 저장 (super step)
    CP-->>SG: 다음 노드 결정 (Edge 평가)
    SG->>N: 다음 노드 실행
    N->>R: 반환값 병합
    R->>CP: State 저장
    SG-->>U: 최종 State 반환
```

**Super Step:** 하나 이상의 노드가 실행되고 결과가 State에 반영되는 단위.
매 super step 종료 시 Checkpointer가 State를 저장한다.

---

## 3. 핵심 개념

### 3-1. State (상태)

그래프 전체에서 공유되는 데이터 구조. 모든 노드가 State를 읽고,
변환 결과를 반환하면 Reducer가 기존 State에 병합한다.

```python
from typing import TypedDict, List, Annotated
import operator

class AgentState(TypedDict):
    messages: Annotated[List[str], operator.add]  # 누적 (append)
    research: str                                  # 덮어쓰기
    draft: str                                     # 덮어쓰기
    iteration: int                                 # 덮어쓰기
```

**MessagesState** -- 대화형 에이전트의 표준 State:

```python
from langgraph.graph import MessagesState

# 내부적으로 아래와 동일:
# class MessagesState(TypedDict):
#     messages: Annotated[list[AnyMessage], add_messages]

class MyState(MessagesState):
    """MessagesState를 확장한 커스텀 State."""
    current_tool: str
    retry_count: int
```

`add_messages` Reducer는 동일 ID 메시지를 자동으로 덮어쓰고, 새 메시지는 뒤에 추가한다.

### 3-2. Nodes (노드)

하나의 작업 단위를 나타내는 Python 함수. State를 입력으로 받고, 변경할 필드만 포함한 부분 dict를 반환한다.

```python
def researcher(state: AgentState) -> dict:
    """자료를 조사하고 research 필드를 업데이트한다."""
    result = llm.invoke(f"조사해주세요: {state['messages'][-1]}")
    return {"research": result.content}

def writer(state: AgentState) -> dict:
    """research를 기반으로 초안을 작성한다."""
    result = llm.invoke(f"글을 작성해주세요:\n{state['research']}")
    return {"draft": result.content, "iteration": state["iteration"] + 1}
```

특수 노드: `START` (그래프 진입점), `END` (그래프 종료점).

### 3-3. Edges (조건부 라우팅)

세 가지 유형이 있다.

```python
# 1) 직접 엣지 -- researcher 완료 후 항상 writer 실행
workflow.add_edge("researcher", "writer")

# 2) 조건부 엣지 -- 상태에 따라 분기
def should_revise(state: AgentState) -> str:
    if "FAIL" in state["fact_check_result"] and state["iteration"] < 3:
        return "writer"
    return END

workflow.add_conditional_edges(
    "fact_checker", should_revise,
    {"writer": "writer", END: END},
)

# 3) 진입 엣지
workflow.add_edge(START, "researcher")
```

라우팅 함수는 State 값 기반으로 결정적(deterministic)이어야 한다.

### 3-4. Channels & Reducers

Reducer는 여러 노드가 같은 필드를 업데이트할 때 병합 전략을 결정한다.

| 데이터 타입 | Reducer | 동작 |
|------------|---------|------|
| 메시지 리스트 | `operator.add` | 기존에 추가 (append) |
| 단일 값 | 기본 (덮어쓰기) | 최신 값으로 교체 |
| 카운터 | 커스텀 함수 | 누적 합산 |

```mermaid
graph LR
    A["Node A"] -->|"return {msgs: ['a']}"| R["Reducer\noperator.add"]
    B["Node B"] -->|"return {msgs: ['b']}"| R
    R --> S["State\nmsgs: ['a','b']"]
    style R fill:#201810,stroke:#e09830,color:#f8b840
    style S fill:#1a2540,stroke:#5a7af0,color:#7a9aff
```

Fan-out으로 여러 노드가 동시에 실행되면, 각 노드의 반환값을 Reducer가 병합한다.
Reducer가 없는 필드에 여러 노드가 동시에 쓰면 충돌 에러가 발생한다.

### 3-5. Checkpointing

매 super step 종료 시 State를 자동 저장한다.

| 기능 | 설명 |
|------|------|
| 크래시 복구 | 마지막 체크포인트에서 재개 |
| 대화 지속 | `thread_id`로 이전 대화를 이어서 진행 |
| 타임 트래블 | 과거 체크포인트로 돌아가서 다른 경로 실행 |
| Human-in-the-Loop | 중단 지점의 State를 저장하고 재개 가능 |

| 유형 | 용도 | 특징 |
|------|------|------|
| `MemorySaver` | 개발/테스트 | 인메모리, 프로세스 재시작 시 소멸 |
| `SqliteSaver` | 경량 프로덕션 | 파일 기반, 단일 프로세스 |
| `PostgresSaver` | 프로덕션 | 수평 확장, 다중 인스턴스 공유 |

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

# 개발 환경
app = workflow.compile(checkpointer=MemorySaver())

# 프로덕션 환경
with PostgresSaver.from_conn_string(DB_URI) as pg_saver:
    pg_saver.setup()
    app = workflow.compile(checkpointer=pg_saver)

# thread_id로 대화 관리
config = {"configurable": {"thread_id": "user-123-session-1"}}
result = app.invoke(state, config)
```

### 3-6. Human-in-the-Loop

**패턴 1: interrupt_before / interrupt_after**

```python
app = workflow.compile(
    checkpointer=memory,
    interrupt_before=["sensitive_action"],
)
result = app.invoke(state, config)  # sensitive_action 전에 중단

# 사람이 검토 후 재개
from langgraph.types import Command
app.invoke(Command(resume="approved"), config)
```

**패턴 2: interrupt() API (LangGraph 2.0)**

```python
from langgraph.types import interrupt

def review_node(state: AgentState) -> dict:
    decision = interrupt({
        "message": "이 분석 결과를 승인하시겠습니까?",
        "data": state["analysis"],
        "actions": ["approve", "reject", "modify"],
    })
    if decision["action"] == "approve":
        return {"approved": True}
    return {"approved": False, "feedback": decision.get("reason")}
```

**패턴 3: State 수정 후 재개** -- 중단된 동안 사람이 State를 직접 수정 가능.

```python
app.update_state(config, {"draft": "사람이 수정한 초안..."})
result = app.invoke(None, config)  # 수정된 State로 재개
```

---

## 4. 그래프 구축 흐름 (전체 코드)

```python
"""리서치 -> 작성 -> 팩트체크 루프 -> 사람 승인 워크플로우."""

from typing import TypedDict, List, Annotated, Literal
import operator
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt
from langchain_anthropic import ChatAnthropic

# Step 1: LLM 초기화
llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)

# Step 2: State 정의
class ResearchState(TypedDict):
    messages: Annotated[List[str], operator.add]
    research: str
    draft: str
    fact_check_result: str
    iteration: int
    approved: bool

# Step 3: 노드 함수 정의
def researcher(state: ResearchState) -> dict:
    result = llm.invoke(f"다음 주제를 조사해주세요: {state['messages'][-1]}")
    return {"research": result.content}

def writer(state: ResearchState) -> dict:
    prompt = f"분석 리포트를 작성해주세요:\n{state['research']}"
    if state.get("fact_check_result") and "FAIL" in state["fact_check_result"]:
        prompt += f"\n\n이전 피드백:\n{state['fact_check_result']}"
    result = llm.invoke(prompt)
    return {"draft": result.content, "iteration": state.get("iteration", 0) + 1}

def fact_checker(state: ResearchState) -> dict:
    result = llm.invoke(
        f"사실 관계를 검증하세요. 문제시 FAIL, 없으면 PASS:\n\n{state['draft']}"
    )
    return {"fact_check_result": result.content}

def human_review(state: ResearchState) -> dict:
    decision = interrupt({
        "message": "최종 리포트를 승인하시겠습니까?",
        "draft": state["draft"],
        "actions": ["approve", "reject"],
    })
    return {"approved": decision == "approve"}

# Step 4: 조건 분기
def should_revise(state: ResearchState) -> Literal["writer", "human_review"]:
    if "FAIL" in state.get("fact_check_result", "") and state.get("iteration", 0) < 3:
        return "writer"
    return "human_review"

# Step 5: 그래프 구성
workflow = StateGraph(ResearchState)
workflow.add_node("researcher", researcher)
workflow.add_node("writer", writer)
workflow.add_node("fact_checker", fact_checker)
workflow.add_node("human_review", human_review)

workflow.add_edge(START, "researcher")
workflow.add_edge("researcher", "writer")
workflow.add_edge("writer", "fact_checker")
workflow.add_conditional_edges(
    "fact_checker", should_revise,
    {"writer": "writer", "human_review": "human_review"},
)
workflow.add_edge("human_review", END)

# Step 6: 컴파일 + 실행
app = workflow.compile(checkpointer=MemorySaver())
config = {"configurable": {"thread_id": "research-session-1"}}

result = app.invoke(
    {"messages": ["삼성전자 2026년 실적 전망 분석"],
     "research": "", "draft": "", "fact_check_result": "",
     "iteration": 0, "approved": False},
    config,
)

# human_review에서 중단 후, 승인하여 재개
from langgraph.types import Command
final = app.invoke(Command(resume="approve"), config)
```

### 실행 그래프 시각화

```mermaid
graph TD
    START((START)) --> R["researcher\n자료 조사"]
    R --> W["writer\n글 작성"]
    W --> FC["fact_checker\n팩트체크"]
    FC -->|"FAIL & iter < 3"| W
    FC -->|"PASS or iter >= 3"| HR["human_review\n사람 승인"]
    HR --> DONE((END))
    style R fill:#1a2540,stroke:#5a7af0,color:#7a9aff
    style W fill:#102820,stroke:#30c880,color:#50e898
    style FC fill:#201010,stroke:#f05050,color:#f08080
    style HR fill:#1a1030,stroke:#9060f0,color:#b080ff
```

---

## 5. 아키텍처 패턴

### 5-1. ReAct (Reasoning + Acting)

단일 에이전트가 도구를 자율적으로 선택하여 실행하는 패턴.
LangGraph는 `create_react_agent()` 헬퍼로 즉시 생성 가능.

```python
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool

@tool
def get_stock_price(ticker: str) -> str:
    """주식 현재가를 조회한다."""
    return f"{ticker}: 72,500원"

@tool
def get_exchange_rate(pair: str) -> str:
    """환율을 조회한다."""
    return f"{pair}: 1,385.50"

agent = create_react_agent(
    model=llm,
    tools=[get_stock_price, get_exchange_rate],
    prompt="당신은 금융 데이터 분석가입니다.",
)
result = agent.invoke({"messages": [("user", "삼성전자 주가와 환율 알려줘")]})
```

### 5-2. Supervisor 패턴

중앙 라우터가 전문 에이전트에 작업을 위임한다.

```python
def supervisor(state: AgentState) -> dict:
    response = llm.invoke(
        f"어떤 에이전트가 처리해야 할까?\n질문: {state['messages'][-1]}\n"
        f"선택지: coder, researcher, data_analyst, FINISH"
    )
    return {"next_agent": response.content.strip()}

workflow.add_conditional_edges(
    "supervisor", lambda s: s["next_agent"],
    {"coder": "coder", "researcher": "researcher",
     "data_analyst": "data_analyst", "FINISH": END},
)
workflow.add_edge("coder", "supervisor")
workflow.add_edge("researcher", "supervisor")
workflow.add_edge("data_analyst", "supervisor")
```

```mermaid
graph TD
    USER["사용자 질문"] --> SUP["Supervisor\n(라우터)"]
    SUP -->|"코딩"| CODER["Coder Agent"]
    SUP -->|"리서치"| RES["Researcher Agent"]
    SUP -->|"데이터"| DATA["Data Analyst"]
    SUP -->|"FINISH"| ANS["최종 답변"]
    CODER --> SUP
    RES --> SUP
    DATA --> SUP
    style SUP fill:#1a1030,stroke:#9060f0,color:#b080ff
    style CODER fill:#102820,stroke:#30c880,color:#50e898
    style RES fill:#1a2540,stroke:#5a7af0,color:#7a9aff
    style DATA fill:#201810,stroke:#e09830,color:#f8b840
```

### 5-3. Hierarchical (계층형) 패턴

Sub-graph로 팀 단위를 격리한다. 각 팀은 독립 State와 체크포인팅을 가진다.

```python
# 팀 A Sub-graph
team_a = StateGraph(TeamAState)
team_a.add_node("worker_a1", worker_a1_fn)
team_a.add_node("worker_a2", worker_a2_fn)
team_a.add_edge(START, "worker_a1")
team_a.add_edge("worker_a1", "worker_a2")
team_a.add_edge("worker_a2", END)
team_a_compiled = team_a.compile()

# 메인 그래프에 Sub-graph를 노드로 추가
main = StateGraph(MainState)
main.add_node("top_supervisor", top_supervisor_fn)
main.add_node("team_a", team_a_compiled)
main.add_node("team_b", team_b_compiled)
```

### 5-4. Plan-and-Execute 패턴

먼저 전체 계획을 세우고, 각 단계를 순차적으로 실행한다.

```python
class PlanExecuteState(TypedDict):
    messages: Annotated[list, operator.add]
    plan: List[str]
    current_step: int
    results: Annotated[list, operator.add]

def planner(state: PlanExecuteState) -> dict:
    response = llm.invoke(f"작업을 3-5개 단계로 분해:\n{state['messages'][-1]}")
    return {"plan": response.content.strip().split("\n"), "current_step": 0}

def executor(state: PlanExecuteState) -> dict:
    step = state["plan"][state["current_step"]]
    result = llm.invoke(f"실행: {step}")
    return {"results": [result.content], "current_step": state["current_step"] + 1}

def should_continue(state: PlanExecuteState) -> str:
    return "executor" if state["current_step"] < len(state["plan"]) else "summarizer"
```

### 5-5. Swarm 패턴

에이전트가 자율적으로 다음 에이전트에 작업을 전달하는 탈중앙 패턴.

```python
from langgraph.types import Command

def agent_a(state: AgentState) -> Command:
    result = llm.invoke(state["messages"])
    return Command(
        update={"messages": [result]},
        goto="agent_b",  # 다음 에이전트로 핸드오프
    )
```

### 패턴 선택 가이드

| 패턴 | 적합한 상황 | 복잡도 | 예측 가능성 |
|------|-----------|--------|-----------|
| **ReAct** | 단일 에이전트, 도구 호출 | 낮음 | 중간 |
| **Supervisor** | 전문 에이전트 팀, 중앙 제어 | 중간 | 높음 |
| **Hierarchical** | 대규모 조직형, 팀 간 격리 | 높음 | 높음 |
| **Plan-and-Execute** | 복잡한 단계적 작업 | 중간 | 높음 |
| **Swarm** | 자율 협업, 유연한 워크플로우 | 높음 | 낮음 |

---

## 6. 스트리밍 & UI

### 스트리밍 모드

| 모드 | API | 출력 | 용도 |
|------|-----|------|------|
| 노드 단위 | `app.stream(state)` | 노드 완료마다 스냅샷 | 진행 상황 표시 |
| 토큰 단위 | `app.astream_events()` | LLM 토큰 하나하나 | 실시간 채팅 UI |
| 커스텀 | `astream_events + 필터` | 특정 이벤트만 | 에이전트별 진행률 |

```python
# 노드 단위 스트리밍
for chunk in app.stream(initial_state, config):
    for node_name, output in chunk.items():
        print(f"[{node_name}] 완료: {list(output.keys())}")

# 토큰 단위 스트리밍 (실시간 채팅)
async for event in app.astream_events(initial_state, config, version="v2"):
    if event["event"] == "on_chat_model_stream":
        token = event["data"]["chunk"].content
        if token:
            print(token, end="", flush=True)
```

### 스트리밍 + WebSocket UI 연동

```mermaid
sequenceDiagram
    participant U as 사용자 (웹 UI)
    participant WS as WebSocket 서버
    participant LG as LangGraph App
    participant LLM as LLM API
    U->>WS: 질문 전송
    WS->>LG: app.astream_events()
    LG->>LLM: API 호출
    LLM-->>LG: 토큰 스트림
    LG-->>WS: on_chat_model_stream
    WS-->>U: 실시간 토큰 표시
    LG-->>WS: on_chain_end
    WS-->>U: 노드 완료 표시
```

### UI 도구

| 도구 | 유형 | 설명 |
|------|------|------|
| **LangGraph Studio** | IDE | 그래프 시각화, 실시간 디버깅, 노드 상태 검사 |
| **LangGraph Builder** | 웹 빌더 | [build.langchain.com](https://build.langchain.com/) |
| **Agent Chat UI** | 채팅 UI | [공식 Next.js 앱](https://github.com/langchain-ai/agent-chat-ui) |
| **LangSmith** | 모니터링 | 트레이싱, 비용 추적, 평가 데이터셋 |

| 연동 방식 | 난이도 | 특징 |
|----------|--------|------|
| Agent Chat UI (공식) | 낮음 | LangGraph 전용, 바로 연결 |
| Open WebUI | 중간 | Pipe/Function으로 연결, thread 자동 생성 |
| CopilotKit | 중간 | React 컴포넌트로 기존 앱에 임베딩 |
| 직접 구현 (React) | 높음 | WebSocket + streamEvents |

---

## 7. 프로덕션 배포

### 개발 vs 프로덕션 체크리스트

| 항목 | 개발 | 프로덕션 |
|------|------|---------|
| Checkpointer | `MemorySaver` | `PostgresSaver` 필수 |
| 타임아웃 | 없음 | 노드별 설정 (LLM 지연 대비) |
| 루프 제한 | 없음 | `recursion_limit` 설정 |
| 모니터링 | print | LangSmith / LangFuse 트레이싱 |
| 에러 처리 | 예외 발생 | 노드별 try/catch + 폴백 |
| 비용 관리 | 무제한 | 토큰 카운팅 + 일일 한도 |
| 보안 | 없음 | Guardrail 노드, PII 필터 |

### Docker 배포

```yaml
# docker-compose.yml
services:
  langgraph-app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/langgraph
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    depends_on:
      - postgres
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: langgraph
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

### FastAPI 서버 구성

```python
"""LangGraph + FastAPI 프로덕션 서버."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import json

checkpointer = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global checkpointer
    checkpointer = AsyncPostgresSaver.from_conn_string(
        "postgresql://user:pass@postgres:5432/langgraph"
    )
    await checkpointer.setup()
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/api/invoke")
async def invoke_agent(request: dict):
    graph = workflow.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": request["thread_id"]}}
    return await graph.ainvoke(request["state"], config)

@app.post("/api/stream")
async def stream_agent(request: dict):
    graph = workflow.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": request["thread_id"]}}

    async def event_generator():
        async for event in graph.astream_events(
            request["state"], config, version="v2"
        ):
            if event["event"] == "on_chat_model_stream":
                token = event["data"]["chunk"].content
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### LangGraph Platform

| 배포 옵션 | 설명 |
|----------|------|
| **Self-hosted (Lite)** | 무료, Docker Compose, 로컬/사내 서버 |
| **Self-hosted (Enterprise)** | 유료, Kubernetes, SSO/RBAC 지원 |
| **Cloud (SaaS)** | LangChain 매니지드, 인프라 불필요 |

주요 기능: Cron 스케줄링, 비동기 작업 큐, 더블 텍스트(실행 중 입력 변경 처리),
Webhook/이벤트 알림, 리소스 격리(테넌트별).

### LangSmith 모니터링

```python
import os
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_API_KEY"] = "ls_..."
os.environ["LANGSMITH_PROJECT"] = "bip-agents"
# 이후 모든 LangGraph 실행이 자동으로 LangSmith에 기록됨
```

### 프로덕션 안정성 패턴

```python
# 1) Recursion Limit -- 최대 25회 노드 실행 후 강제 종료
result = app.invoke(state, config, recursion_limit=25)

# 2) 노드별 에러 핸들링
def safe_researcher(state: ResearchState) -> dict:
    try:
        result = llm.invoke(state["messages"][-1])
        return {"research": result.content}
    except Exception as e:
        return {"research": f"[ERROR] 리서치 실패: {str(e)}"}

# 3) 타임아웃
import asyncio

async def researcher_with_timeout(state: ResearchState) -> dict:
    try:
        result = await asyncio.wait_for(
            llm.ainvoke(state["messages"][-1]), timeout=30.0,
        )
        return {"research": result.content}
    except asyncio.TimeoutError:
        return {"research": "[TIMEOUT] 리서치 시간 초과"}
```

---

## 8. 프레임워크 비교

### LangGraph vs CrewAI vs AutoGen vs Deep Agents

| 항목 | LangGraph | CrewAI | AutoGen | Deep Agents |
|------|-----------|--------|---------|-------------|
| **설계 철학** | 그래프 상태 머신 | 역할 기반 팀 | 대화 기반 협업 | 자기 개선 에이전트 |
| **상태 관리** | 네이티브 (TypedDict + Reducer) | 제한적 | 메시지 기반 | 3계층 메모리 |
| **HITL** | 네이티브 (`interrupt()`) | 제한적 | 가능 | 가능 |
| **체크포인팅** | 내장 (Postgres/SQLite) | 없음 | 없음 | SQLite |
| **스트리밍** | 토큰 레벨 | 없음 | 제한적 | 가능 |
| **멀티 에이전트** | Supervisor/Hierarchical/Swarm | 역할 지정 | GroupChat | 계층적 |
| **도구 연동** | LangChain Tools + MCP | 자체 도구 | 함수 호출 | MCP |
| **프로덕션 검증** | 높음 (Klarna, Elastic) | 중간 | 중간 | 초기 |
| **라이선스** | MIT | MIT | MIT | MIT |

### 선택 가이드

| 상황 | 추천 |
|------|------|
| 프로덕션 에이전트 시스템 | **LangGraph** -- 성숙한 생태계, 체크포인팅, 스트리밍 |
| 빠른 프로토타이핑, 역할 기반 | **CrewAI** -- 직관적 역할 할당, 적은 코드 |
| Microsoft/Azure 환경 | **AutoGen** -- Azure 통합, GroupChat |
| 자기 학습/개선 에이전트 연구 | **Deep Agents** -- 스킬 학습, 3계층 메모리 |
| 기존 LangChain 코드베이스 확장 | **LangGraph** -- 동일 생태계, 마이그레이션 용이 |

---

## 9. 참고 + 변경 이력

### 공식 자료

| 자료 | URL |
|------|-----|
| GitHub | https://github.com/langchain-ai/langgraph |
| 공식 문서 | https://langchain-ai.github.io/langgraph/ |
| 개념 문서 (High Level) | https://langchain-ai.github.io/langgraph/concepts/high_level/ |
| 에이전트 개념 | https://langchain-ai.github.io/langgraph/concepts/agentic_concepts/ |
| Quickstart | https://langchain-ai.github.io/langgraph/tutorials/get-started/1-build-basic-chatbot/ |
| LangGraph Builder | https://build.langchain.com/ |
| Agent Chat UI | https://github.com/langchain-ai/agent-chat-ui |
| LangGraph Studio | https://docs.langchain.com/langsmith/studio |
| LangGraph Platform GA | https://blog.langchain.com/langgraph-platform-ga/ |

### BIP Pipeline 내부 관련 문서

| 문서 | 경로 |
|------|------|
| 체크리스트 에이전트 아키텍처 | `docs/checklist_agent_architecture.md` |
| LangGraph 마이그레이션 기록 | `docs/langgraph_migration_journal.md` |
| LangGraph 사내 환경 구축 | `docs/langgraph_enterprise_guide.md` |
| BIP Agents 아키텍처 | `docs/bip_agents_architecture.md` |
| 보안 거버넌스 | `docs/security_governance.md` |

### 비용 구조

| 항목 | 비용 | 설명 |
|------|------|------|
| LangGraph 라이브러리 | 무료 (MIT) | 오픈소스 |
| LLM API | 모델별 상이 | 노드마다 LLM 호출 |
| 인프라 오버헤드 | +10~20% | 체크포인팅 PostgreSQL, 상태 직렬화 |
| LangGraph Platform | 유료 (Enterprise) | 셀프호스팅은 무료, 매니지드는 유료 |
| LangSmith | 무료 티어 | 프로덕션 모니터링은 유료 플랜 권장 |

### 변경 이력

| 날짜 | 버전 | 변경 내용 | 작성자 |
|------|------|----------|--------|
| 2026-04-14 | v1.0 | 최초 작성 | Claude |
| 2026-04-26 | v2.0 | 공식 문서 기반 전면 재작성. 9개 섹션 구조로 확장. State/Channels/Reducers 심화, interrupt() API 상세화, Plan-and-Execute/Swarm 패턴 추가, 프로덕션 배포(Docker/FastAPI/Platform) 확장, 프레임워크 비교(Deep Agents 추가), 전체 코드 예제 보강 | Claude |
