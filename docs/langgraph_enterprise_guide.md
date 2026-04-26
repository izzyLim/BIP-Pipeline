# LangGraph 사내 환경 구축 가이드

> **공식 문서:** https://langchain-ai.github.io/langgraph/
> **최종 수정:** 2026-04-26 | **버전:** v3.0
> **대상 독자:** 사내 AI 에이전트 시스템 구축 담당자 (Python 기본 지식 필요)

---

## 1. 개요

### 1.1 목적

LangGraph는 LLM 기반 에이전트 워크플로우를 **그래프(노드 + 엣지)** 로 모델링하는 상태 기반 오케스트레이션 프레임워크이다.
이 가이드는 Python 환경 설정부터 Docker 프로덕션 배포, MCP 도구 연동, 모니터링까지
사내 폐쇄망에서 LangGraph 기반 에이전트를 운영 수준으로 구축하는 전 과정을 다룬다.

### 1.2 왜 LangGraph인가

| 항목 | LangChain (Chain) | LangGraph (Graph) |
|------|-------------------|-------------------|
| **실행 흐름** | A -> B -> C (선형) | 분기, 루프, 병렬 가능 |
| **상태 관리** | 없음 (입출력 전달만) | 공유 State 객체 |
| **Human-in-the-Loop** | 수동 구현 | 네이티브 `interrupt()` |
| **내구성** | 없음 | Checkpointer로 크래시 복구 |
| **멀티 에이전트** | 어색한 통합 | 1등 시민 설계 |

**판단 기준:** 워크플로우에 분기(if-then)나 루프(retry/revise)가 필요하면 LangGraph. 단순 직선 파이프라인이면 LangChain으로 충분하다.

### 1.3 전제 조건

| 항목 | 요구사항 | 비고 |
|------|----------|------|
| Python | 3.11 이상 | 3.13 권장 (asyncio 성능 향상) |
| PostgreSQL | 14 이상 | Checkpointer + 데이터 저장. 16 권장 |
| Docker | 선택 (프로덕션 필수) | Docker Compose로 전체 환경 관리 |
| LLM API 키 | 최소 1개 | Anthropic, OpenAI, Google 중 택 |

### 1.4 최종 목표 아키텍처

```mermaid
graph TD
    subgraph Client["클라이언트"]
        SPRING["Spring Boot / React"]
        AF["Airflow DAG"]
    end

    subgraph LB_LAYER["로드 밸런서"]
        LB["L4 Load Balancer<br/>HAProxy / F5"]
    end

    subgraph Workers["Agent Workers - Stateless"]
        W1["Worker 1<br/>FastAPI + LangGraph"]
        W2["Worker 2<br/>FastAPI + LangGraph"]
    end

    subgraph Tools["도구 계층"]
        LOCAL["@tool 로컬 도구"]
        MCP_S["MCP Server 공유 도구"]
    end

    subgraph Data["데이터 계층"]
        PG["PostgreSQL<br/>Checkpointer + Data"]
    end

    subgraph Monitor["모니터링"]
        FUSE["LangFuse Self-hosted"]
        GRAF["Grafana 인프라 메트릭"]
    end

    Client --> LB
    LB --> W1 & W2
    W1 & W2 --> LOCAL & MCP_S
    W1 & W2 --> PG
    MCP_S --> PG
    W1 & W2 -.->|callback| FUSE
    W1 & W2 -.->|metrics| GRAF
```

핵심 설계 원칙: Worker는 완전 Stateless이다. 모든 상태는 PostgreSQL Checkpointer에 위임한다. 어떤 Worker가 요청을 받아도 동일하게 동작하므로, 장애 시 LB가 다른 Worker로 자동 라우팅한다.

---

## 2. Python 환경 구축

### 2.1 pyenv + venv 설정

```bash
# pyenv 설치 (macOS: brew install pyenv / Linux: curl https://pyenv.run | bash)
pyenv install 3.13.1 && pyenv local 3.13.1

mkdir my-langgraph-agents && cd my-langgraph-agents
python -m venv .venv && source .venv/bin/activate
```

### 2.2 패키지 설치

```bash
pip install langgraph langchain-anthropic langgraph-checkpoint-postgres \
    langchain-mcp-adapters fastapi uvicorn langfuse psycopg[binary] python-dotenv
```

### 2.3 requirements.txt

```text
langgraph>=0.4.0
langchain-anthropic>=0.3.0
langgraph-checkpoint-postgres>=2.0.0
langchain-mcp-adapters>=0.1.0
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
langfuse>=2.50.0
psycopg[binary]>=3.2.0
python-dotenv>=1.0.0
```

### 2.4 프로젝트 레이아웃

```
my-langgraph-agents/
├── .env                    # 환경변수 (git 제외)
├── .env.example            # 환경변수 템플릿
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI 엔트리포인트
│   ├── config.py           # 설정 (환경변수 로드)
│   ├── agents/
│   │   ├── state.py        # State 스키마 (TypedDict)
│   │   ├── nodes.py        # 노드 함수들
│   │   ├── graph.py        # StateGraph 구성 + 컴파일
│   │   └── prompts.py      # 시스템 프롬프트
│   ├── tools/
│   │   ├── db_tools.py     # DB 조회 도구
│   │   ├── api_tools.py    # 외부 API 도구
│   │   └── mcp_client.py   # MCP 서버 연결
│   └── middleware/
│       ├── auth.py         # 인증
│       └── audit.py        # 감사 로깅
├── mcp-server/
│   ├── server.py
│   ├── tools.py
│   └── Dockerfile
└── tests/
    └── test_agents.py
```

### 2.5 환경변수 관리

```python
# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL")
    MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/sse")
    LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://localhost:3100")
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")

settings = Settings()
```

> **보안 필수:** `.env`는 절대 git에 커밋하지 않는다. 프로덕션에서는 Docker secrets 또는 Vault를 사용한다.

---

## 3. 첫 번째 Agent 구축 (Step-by-Step 전체 코드)

### 3.1 핵심 개념 관계도

```mermaid
graph LR
    STATE["State<br/>공유 메모리"] --> NODE["Node<br/>작업 단위"]
    NODE --> EDGE["Edge<br/>흐름 연결"]
    EDGE --> COND["Conditional Edge<br/>조건 분기"]
    COND --> CHECK["Checkpointer<br/>상태 저장"]
    CHECK --> HITL["Human-in-the-Loop<br/>사람 개입"]
```

- **State** -- 그래프 전체에서 공유되는 메모리 객체. 모든 노드가 읽고 쓴다.
- **Node** -- 하나의 작업 단위(함수). State를 받아서 변환 후 반환한다.
- **Edge** -- 노드 간 직접 연결. A가 끝나면 B로 이동한다.
- **Conditional Edge** -- 조건에 따라 다른 노드로 라우팅. 루프의 핵심이다.
- **Checkpointer** -- 매 노드 실행 후 상태 자동 저장. 크래시 복구, 대화 지속.

### 3.2 State 정의

```python
# app/agents/state.py
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """에이전트 공유 상태. 모든 노드가 읽고 쓴다."""
    messages: Annotated[list, add_messages]  # 대화 이력 (자동 누적)
    iteration: int                            # 루프 카운터
```

`Annotated[list, add_messages]`는 LangGraph의 리듀서(reducer) 문법이다. 노드가 `{"messages": [new_msg]}`를 반환하면, 기존 리스트에 자동 추가된다.

### 3.3 도구 정의

```python
# app/tools/api_tools.py
from langchain_core.tools import tool
from datetime import datetime

@tool
def get_current_time() -> str:
    """현재 시각을 반환합니다."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def get_stock_price(ticker: str) -> str:
    """종목 현재가를 조회합니다. ticker 예시: 005930 (삼성전자)"""
    prices = {"005930": 72500, "000660": 185000}
    price = prices.get(ticker, None)
    if price is None:
        return f"'{ticker}' 종목을 찾을 수 없습니다."
    return f"{ticker} 현재가: {price:,}원"

@tool
def search_news(query: str) -> str:
    """최신 뉴스를 검색합니다."""
    return f"'{query}' 관련 최신 뉴스: [예시 결과]"
```

### 3.4 ReAct 에이전트 (create_react_agent)

```python
# app/agents/graph.py
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_anthropic import ChatAnthropic
from app.tools.api_tools import get_current_time, get_stock_price, search_news
from app.config import settings

async def create_agent():
    """ReAct 에이전트 인스턴스 생성"""
    # 1. Checkpointer 설정
    checkpointer = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL)
    await checkpointer.setup()  # 테이블 자동 생성 (최초 1회)

    # 2. LLM 초기화
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", max_tokens=4000)

    # 3. 도구 목록
    tools = [get_current_time, get_stock_price, search_news]

    # 4. 에이전트 컴파일
    return create_react_agent(
        llm, tools,
        checkpointer=checkpointer,
        prompt="당신은 주식 시장 데이터 분석 전문가입니다. "
               "도구를 적극 활용해 정확한 정보를 제공하세요.",
    )
```

### 3.5 커스텀 StateGraph (고급)

`create_react_agent`로 부족할 때, `StateGraph`로 노드와 엣지를 직접 구성한다.

```python
# app/agents/custom_graph.py
from langgraph.graph import StateGraph, END

workflow = StateGraph(AgentState)
workflow.add_node("router", router_node)      # 분기 판단
workflow.add_node("researcher", researcher_node)  # 리서치 실행
workflow.set_entry_point("router")
workflow.add_edge("router", "researcher")
workflow.add_conditional_edges(
    "researcher",
    lambda s: "router" if s["iteration"] < 3 and hasattr(s["messages"][-1], "tool_calls") else END,
)
graph = workflow.compile(checkpointer=checkpointer)
```

### 3.6 실행 테스트

```python
# test_run.py
import asyncio

async def main():
    agent = await create_agent()
    config = {"configurable": {"thread_id": "test-session-1"}}

    # 첫 번째 질문
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "삼성전자 현재가 알려줘"}]},
        config,
    )
    print(result["messages"][-1].content)

    # 같은 thread_id -> 대화 이력 유지
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "SK하이닉스도 알려줘"}]},
        config,
    )
    print(result["messages"][-1].content)

asyncio.run(main())
```

---

## 4. MCP 도구 연동 (langchain-mcp-adapters)

### 4.1 방법 비교

| 방법 | 장점 | 단점 | 권장 상황 |
|------|------|------|-----------|
| `@tool` 데코레이터 | 간단, 의존성 없음 | 공유 불가 | 단일 에이전트 전용 도구 |
| MCP 서버 | 여러 에이전트 공유, 독립 배포 | 네트워크 레이턴시 | 공유 도구, 마이크로서비스 |

### 4.2 MCP 서버 구축

```python
# mcp-server/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("bip-tools")

@mcp.tool()
async def get_stock_price(ticker: str) -> str:
    """종목 현재가를 조회합니다."""
    price = await fetch_price_from_api(ticker)
    return f"{ticker}: {price:,}원"

@mcp.tool()
async def get_market_index(index_name: str) -> str:
    """시장 지수를 조회합니다. (KOSPI, KOSDAQ, S&P500 등)"""
    value = await fetch_index(index_name)
    return f"{index_name}: {value}"

if __name__ == "__main__":
    mcp.run(transport="sse")
```

### 4.3 에이전트에서 MCP 서버 연결

```python
# app/tools/mcp_client.py
from langchain_mcp_adapters.client import MultiServerMCPClient
from app.config import settings

async def get_mcp_tools():
    """MCP 서버에서 도구 목록을 가져온다."""
    client = MultiServerMCPClient({
        "bip-tools": {
            "url": settings.MCP_SERVER_URL,
            "transport": "sse",
        },
    })
    return await client.get_tools()
```

### 4.4 MCP + @tool 혼합 사용

```python
local_tools = [get_current_time]          # @tool
mcp_tools = await get_mcp_tools()         # MCP 서버
all_tools = local_tools + mcp_tools
agent = create_react_agent(llm, all_tools, checkpointer=checkpointer)
```

---

## 5. FastAPI 서빙 (REST API, 스트리밍)

### 5.1 기본 REST 엔드포인트

```python
# app/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.agents.graph import create_agent

app = FastAPI(title="LangGraph Agent Server")

class AskRequest(BaseModel):
    question: str
    thread_id: str = "default"

class AskResponse(BaseModel):
    answer: str
    tools_used: list[str] = []

@app.on_event("startup")
async def startup():
    app.state.agent = await create_agent()

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    try:
        result = await app.state.agent.ainvoke(
            {"messages": [{"role": "user", "content": req.question}]},
            config,
        )
        messages = result.get("messages", [])
        answer = messages[-1].content if messages else ""
        return AskResponse(answer=answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 5.2 SSE 스트리밍 엔드포인트

```python
from fastapi.responses import StreamingResponse

@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest):
    """SSE 스트리밍 -- 실시간 채팅 UI용"""
    config = {"configurable": {"thread_id": req.thread_id}}

    async def event_generator():
        async for event in app.state.agent.astream_events(
            {"messages": [{"role": "user", "content": req.question}]},
            config, version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield f"data: {chunk.content}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 5.3 요청 흐름

```mermaid
sequenceDiagram
    participant U as 클라이언트
    participant LB as Load Balancer
    participant W as Worker (FastAPI)
    participant LG as LangGraph
    participant MCP as MCP 서버
    participant DB as PostgreSQL
    participant LF as LangFuse

    U->>LB: POST /api/ask (JWT)
    LB->>W: 라우팅
    W->>LG: agent.ainvoke(state, config)
    activate LG
    LG->>DB: Checkpoint 로드 (thread_id)
    LG->>MCP: 도구 호출
    MCP->>DB: SQL 조회
    DB-->>MCP: 결과
    MCP-->>LG: 도구 결과
    LG->>LG: LLM 호출 (응답 생성)
    LG->>DB: Checkpoint 저장
    LG-->>W: 최종 응답
    deactivate LG
    W-->>LB: JSON 응답
    LB-->>U: 응답 전달
    W--)LF: 트레이스 비동기 전송
```

---

## 6. Docker 배포 (Dockerfile, docker-compose.yml)

### 6.1 Dockerfile

```dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8100

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8100", \
     "--workers", "2"]
```

### 6.2 docker-compose.yml (개발 / PoC)

```yaml
services:
  agent-server:
    build: .
    ports:
      - "8100:8100"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - DATABASE_URL=postgresql://agent:agentpass@postgres:5432/agentdb
      - MCP_SERVER_URL=http://mcp-server:8000/sse
      - LANGFUSE_HOST=http://langfuse:3100
      - LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
      - LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
    depends_on:
      postgres:
        condition: service_healthy
      mcp-server:
        condition: service_started
    restart: unless-stopped

  mcp-server:
    build: ./mcp-server
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://agent:agentpass@postgres:5432/agentdb
    restart: unless-stopped

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agentpass
      POSTGRES_DB: agentdb
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent -d agentdb"]
      interval: 5s
      timeout: 3s
      retries: 5
    ports:
      - "5432:5432"

  langfuse:
    image: langfuse/langfuse:2
    ports:
      - "3100:3000"
    environment:
      DATABASE_URL: postgresql://langfuse:lfpass@langfuse-db:5432/langfuse
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET:-change-me}
      NEXTAUTH_URL: http://localhost:3100
      SALT: ${LANGFUSE_SALT:-change-me}
      TELEMETRY_ENABLED: "false"
    depends_on:
      langfuse-db:
        condition: service_healthy

  langfuse-db:
    image: postgres:15
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: lfpass
      POSTGRES_DB: langfuse
    volumes:
      - langfuse_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
  langfuse_data:
```

### 6.4 docker-compose.prod.yml (프로덕션 HA)

각 VM에 동일한 Compose 파일을 배포하고, 상위 L4 LB로 묶는다.

```yaml
services:
  langgraph-worker:
    image: registry.internal/langgraph-worker:${TAG:-latest}
    deploy:
      replicas: 2
    restart: always
    ports:
      - "8100-8101:8100"
    environment:
      DATABASE_URL: postgresql://agent:${DB_PASSWORD}@db.internal:5432/agentdb
      MCP_SERVER_URL: http://mcp-server:8000/sse
      LANGFUSE_HOST: http://langfuse.internal:3100
      ANTHROPIC_API_KEY_FILE: /run/secrets/anthropic_key
      WORKER_CONCURRENCY: 20
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8100/health"]
      interval: 10s
      timeout: 5s
      retries: 3
    secrets:
      - anthropic_key

  mcp-server:
    image: registry.internal/mcp-server:${TAG:-latest}
    restart: always
    ports:
      - "8000:8000"

secrets:
  anthropic_key:
    file: /etc/secrets/anthropic_key.txt
```

### 6.5 실행 명령

```bash
docker compose up -d                                        # 개발
TAG=v1.2.3 docker compose -f docker-compose.prod.yml up -d  # 프로덕션
docker compose logs -f agent-server                         # 로그
docker compose up -d --scale langgraph-worker=4             # 스케일 아웃
```

---

## 7. LangSmith / LangFuse 연동 (모니터링)

### 7.1 옵션 비교

| 도구 | 형태 | Self-host | 사내 폐쇄망 |
|------|------|-----------|-------------|
| **LangSmith** | SaaS | Enterprise만 | 불가 (데이터 외부 전송) |
| **LangFuse** | 오픈소스 | Docker 1줄 | 가능 (권장) |

> 사내 폐쇄망이면 LangSmith 사용 불가. LangFuse를 사내 VM에 Docker로 설치하면 동일한 기능을 내부에서 사용할 수 있다.

### 7.2 LangFuse 연동 (코드 3줄)

```python
from langfuse.callback import CallbackHandler

langfuse_handler = CallbackHandler(
    host="http://langfuse.internal:3100",
    public_key="pk-...",
    secret_key="sk-...",
)

result = await graph.ainvoke(
    initial_state,
    config={"callbacks": [langfuse_handler]},
)
# 자동 수집: 노드별 실행 시간, LLM 입출력, 토큰 수, 에러 트레이스
```

### 7.3 LangFuse 제공 기능

| 기능 | 설명 |
|------|------|
| **Traces** | 노드별 실행 시간, 도구 호출, LLM 입출력 워터폴 시각화 |
| **Generations** | LLM 호출별 프롬프트, 응답, 토큰 수, 비용 |
| **Sessions** | 사용자별 대화 세션 그룹핑 |
| **Dashboard** | 일별 실행 수, 토큰 사용량, 에러율, 평균 지연시간 |
| **Scores** | 품질 평가 -- 자동(LLM-as-Judge) / 수동(사용자 피드백) |
| **Prompts** | 프롬프트 버전 관리 + 배포 |

### 7.4 LangSmith (SaaS 환경용)

```bash
# 환경변수만 설정하면 자동 트레이싱 (코드 변경 없음)
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxx
LANGSMITH_PROJECT=my-agents
```

### 7.5 인프라 메트릭 (Prometheus + Grafana)

LangFuse는 에이전트 트레이싱 전용이다. CPU, 메모리, Worker 상태 등 인프라 메트릭은 `prometheus_client`로 커스텀 메트릭(`langgraph_runs_total`, `langgraph_node_duration_seconds`, `langgraph_active_runs`)을 노출하고 Grafana로 시각화한다.

---

## 8. 사내 보안 고려사항

### 8.1 보안 체크 흐름

```mermaid
graph TD
    INPUT["사용자 입력"] --> GUARD["Guardrail<br/>입력 검증<br/>PII/인젝션 차단"]
    GUARD -->|통과| AGENT["에이전트 실행"]
    GUARD -->|차단| REJECT["거부 응답"]
    AGENT --> AUDIT["감사 로그<br/>agent_audit_log"]
    AGENT --> FILTER["출력 필터<br/>민감 정보 마스킹"]
    FILTER --> OUTPUT["응답"]
```

### 8.2 보안 체크리스트

| 보안 항목 | 구현 방법 |
|-----------|-----------|
| **API 키 보호** | `.env` + Docker secrets. 절대 코드/git에 하드코딩 금지 |
| **DB 접근 제어** | 에이전트 전용 DB 계정 (읽기 전용 or 특정 테이블만) |
| **루프 제한** | Conditional Edge에 `iteration < max` 필수. 무한 루프 = API 비용 폭발 |
| **감사 로그** | 모든 LLM 호출을 DB에 기록 (에이전트명, 토큰, 도구, 결과) |
| **입력 검증** | 프롬프트 인젝션 방지. Guardrail 노드로 입력 필터링 |
| **출력 필터** | PII(개인정보), 민감 데이터가 응답에 노출되지 않도록 |
| **네트워크 격리** | MCP 서버, DB는 내부 네트워크에서만 접근 |

### 8.3 감사 로그

모든 LLM 호출을 `agent_audit_log` 테이블에 기록한다. 필수 컬럼: `agent_name`, `input_text`, `output_text`, `tools_used`, `token_input`, `token_output`, `model`, `latency_ms`, `created_at`. BIP 프로젝트의 구현 예시는 `docs/checklist_agent_architecture.md` 참조.

---

## 9. 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `checkpointer.setup()` 실패 | `autocommit=True` 누락 | `psycopg.connect(..., autocommit=True)` |
| Checkpoint 조회 에러 | `row_factory` 미설정 | `row_factory=psycopg.rows.dict_row` |
| MCP 연결 끊김 | SSE 타임아웃 | `try/finally`로 `mcp_client.close()` 보장 |
| 에이전트 무한 루프 | Conditional Edge에 종료 조건 누락 | `iteration < 3` 가드 추가 |
| 토큰 한도 초과 | 긴 대화 컨텍스트 | context compressor로 요약 또는 새 thread 시작 |
| LangFuse에 트레이스 안 뜸 | 콜백 미설정 | `config={"callbacks": [handler]}` 확인 |
| State 스키마 호환 에러 | TypedDict 변경 후 기존 체크포인트 불일치 | thread_id를 새로 생성하거나 체크포인트 정리 |
| 도구 호출 실패 (404) | MCP 서버 미실행 또는 URL 오류 | `docker ps`로 확인, `MCP_SERVER_URL` 검증 |
| `create_react_agent` import 에러 | langgraph 버전 불일치 | `pip install langgraph>=0.4.0` |
| Docker 빌드 시 psycopg 에러 | libpq 미설치 | `psycopg[binary]` 사용 또는 `apt install libpq-dev` |

### Checkpointer 데이터 정리

```sql
-- 오래된 체크포인트 정리 (30일 이전)
DELETE FROM checkpoints
WHERE (metadata->>'created_at')::timestamp < NOW() - INTERVAL '30 days';
```

### 디버깅 팁

`agent.astream_events(..., version="v2")`로 실행 중간 상태를 확인할 수 있다. `on_tool_start`, `on_tool_end`, `on_chat_model_stream` 이벤트를 로깅하면 도구 호출 흐름을 추적할 수 있다.

---

## 10. 참고 자료 + 변경 이력

### 10.1 참고 자료

| 자료 | URL |
|------|-----|
| LangGraph 공식 문서 | https://langchain-ai.github.io/langgraph/ |
| LangGraph GitHub | https://github.com/langchain-ai/langgraph |
| LangGraph 배포 옵션 | https://langchain-ai.github.io/langgraph/concepts/deployment_options/ |
| LangGraph 튜토리얼 | https://langchain-ai.github.io/langgraph/tutorials/ |
| LangGraph How-to Guides | https://langchain-ai.github.io/langgraph/how-tos/ |
| langgraph-checkpoint-postgres | https://pypi.org/project/langgraph-checkpoint-postgres/ |
| langchain-mcp-adapters | https://pypi.org/project/langchain-mcp-adapters/ |
| LangFuse 문서 | https://langfuse.com/docs |
| LangFuse + LangChain 연동 | https://langfuse.com/docs/integrations/langchain/tracing |
| LangSmith 설정 가이드 | https://docs.smith.langchain.com/ |

### 10.2 관련 BIP 문서

| 문서 | 경로 |
|------|------|
| LangGraph 기술 가이드 (핵심 개념 스터디) | `docs/langgraph_technical_guide.md` |
| 체크리스트 에이전트 아키텍처 | `docs/checklist_agent_architecture.md` |
| FastMCP 가이드 | `docs/fastmcp_guide.md` |
| BIP 에이전트 전략 | `docs/bip_agent_strategy.md` |
| 보안 거버넌스 | `docs/security_governance.md` |

### 10.3 비용 참고

| 항목 | 비용 | 비고 |
|------|------|------|
| LangGraph | 무료 (MIT) | 오픈소스 |
| Haiku 호출 | ~$0.003/질문 | 단순 판단용 최적 |
| Sonnet 호출 | ~$0.05/질문 | 복잡 분석용 |
| PostgreSQL | 셀프호스팅 무료 | Docker 볼륨 |
| LangFuse | 셀프호스팅 무료 | Docker 볼륨 |

> **BIP 실제 비용:** 6개 에이전트 운영에 월 약 $6. Haiku 중심, Sonnet은 복잡한 분석에만 사용한다.

### 10.4 변경 이력

| 버전 | 날짜 | 변경 내용 | 작성자 |
|------|------|-----------|--------|
| v1.0 | 2026-04-05 | 초기 작성. 환경 구축, 에이전트 기본, Docker 배포 | - |
| v1.5 | 2026-04-11 | MCP 연동, LangSmith 모니터링 추가 | - |
| v2.0 | 2026-04-18 | Oracle RAC Checkpointer, Multi-VM HA, LangFuse 전환, Airflow 연동 | - |
| v3.0 | 2026-04-26 | 전면 재작성. 공식 문서 기반 10장 구조, Step-by-Step 코드 보강, Mermaid 5개, 트러블슈팅 확대, 보안 섹션 강화, 변경 이력 테이블 추가 | - |
