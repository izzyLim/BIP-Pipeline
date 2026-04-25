# LangGraph  
사내 환경 구축

Python 환경 설정부터 체크포인터(PostgreSQL/Oracle RAC), MCP 서버, FastAPI 에이전트 서버, Multi-VM Docker HA 배포, Airflow 연동, LangFuse 모니터링까지 — 사내 폐쇄망에 LangGraph 기반 에이전트 시스템을 처음부터 구축하는 전 과정.

Python 3.11+ PostgreSQL / Oracle RAC Docker + Multi-VM HA FastAPI MCP LangFuse (Self-hosted)

## 최종 목표 아키텍처

사내 프로덕션 환경 전체 구성도 (Multi-VM + Oracle RAC + LangFuse)

graph TD subgraph Client["클라이언트"] SPRING["Spring Boot\n기존 웹 시스템"] TG["텔레그램"] AF["Airflow DAG"] end subgraph LB_LAYER["로드 밸런서"] LB["L4 Load Balancer\nF5 / HAProxy\n(VIP)"] end subgraph VM1["VM-1 (Docker)"] W1A["Worker 1a"] W1B["Worker 1b"] end subgraph VM2["VM-2 (Docker)"] W2A["Worker 2a"] W2B["Worker 2b"] end subgraph VM3["VM-3 (Docker)"] W3A["Worker 3a"] W3B["Worker 3b"] end subgraph Worker_Detail["Worker 내부 구조"] FAST["FastAPI\nHTTP/WebSocket"] LG["LangGraph\n에이전트 그래프"] TOOLS["로컬 도구\n@tool"] MCP_C["MCP Client"] end subgraph MCP_S["MCP 서버 (Docker)"] MCP_T["MCP 도구\n외부 API 래핑"] end subgraph DB_LAYER["데이터 계층"] SCAN["SCAN Listener\n단일 진입점"] subgraph RAC["Oracle Exadata RAC"] NODE1["RAC Node 1\nActive"] NODE2["RAC Node 2\nActive"] end ASM["ASM\n공유 스토리지"] end subgraph Monitor["모니터링"] FUSE["LangFuse\nSelf-hosted\n트레이싱 UI"] GRAF["Grafana\n인프라 메트릭"] AUDIT["감사 로그\nagent_audit_log"] end Client --> LB LB --> VM1 LB --> VM2 LB --> VM3 FAST --> LG LG --> TOOLS LG --> MCP_C MCP_C --> MCP_T W1A & W1B & W2A & W2B & W3A & W3B --> SCAN MCP_T --> SCAN SCAN --> NODE1 SCAN --> NODE2 NODE1 --> ASM NODE2 --> ASM LG -.->|callback| FUSE LG -.-> AUDIT VM1 & VM2 & VM3 -.->|metrics| GRAF style LB_LAYER fill:#0d0f18,stroke:#f05050,color:#f08080 style VM1 fill:#0d0f18,stroke:#30c880 style VM2 fill:#0d0f18,stroke:#30c880 style VM3 fill:#0d0f18,stroke:#30c880 style Worker_Detail fill:#0d0f18,stroke:#5a7af0 style MCP_S fill:#0d0f18,stroke:#5a7af0 style DB_LAYER fill:#0d0f18,stroke:#e09830 style RAC fill:#101520,stroke:#e09830 style Monitor fill:#0d0f18,stroke:#9060f0 

요청 흐름 시퀀스

sequenceDiagram participant U as Spring Boot (사용자) participant LB as Load Balancer participant W as Worker (FastAPI) participant LG as LangGraph participant MCP as MCP 서버 participant ORA as Oracle RAC (SCAN) participant LF as LangFuse U->>LB: POST /api/ask (JWT 포함) LB->>W: 라우팅 (health check 통과 Worker) W->>LG: graph.ainvoke(state, config) activate LG LG->>ORA: Checkpoint 로드 (thread_id) LG->>LG: router 노드 (분기 판단) LG->>MCP: 도구 호출 (get_stock_price 등) MCP->>ORA: SQL 조회 ORA-->>MCP: 결과 MCP-->>LG: 도구 결과 LG->>ORA: LLM 호출 (사내 API) LG->>ORA: Checkpoint 저장 LG-->>W: 최종 응답 deactivate LG W-->>LB: JSON 응답 LB-->>U: 응답 전달 W--)LF: 트레이스 비동기 전송 

ℹ

**핵심 설계 원칙** Worker는 완전 Stateless — 모든 상태는 Oracle RAC에 위임. 어떤 Worker가 요청을 받아도 동일하게 동작하므로, 장애 시 LB가 다른 Worker로 자동 라우팅.

01사전 준비

항목| 요구사항| 비고  
---|---|---  
**Python**|  3.11 이상| 3.13 권장. asyncio 성능 향상  
**PostgreSQL**|  14 이상| 체크포인터 + 데이터 저장. 16 권장  
**Docker**|  선택 (프로덕션 필수)| Docker Compose로 전체 환경 관리  
**LLM API 키**|  최소 1개| Anthropic, OpenAI, Google 중 택  
**Git**|  필수| 버전 관리  
  
SHELLPython 가상환경 생성
    
    
    # Python 3.11+ 확인
    python3 --version
    
    # 프로젝트 디렉토리 생성
    mkdir my-langgraph-agents && cd my-langgraph-agents
    
    # 가상환경 생성 + 활성화
    python3 -m venv .venv
    source .venv/bin/activate  # Linux/Mac
    # .venv\Scripts\activate   # Windows

02패키지 설치

SHELL필수 패키지
    
    
    # LangGraph 코어
    pip install langgraph
    
    # LLM 프로바이더 (사용할 것만)
    pip install langchain-anthropic    # Claude
    pip install langchain-openai       # OpenAI
    pip install langchain-google-genai # Gemini
    
    # 체크포인터 (프로덕션)
    pip install langgraph-checkpoint-postgres
    
    # MCP 도구 연동
    pip install langchain-mcp-adapters
    
    # 웹 서버
    pip install fastapi uvicorn
    
    # 모니터링
    pip install langsmith

FILErequirements.txt
    
    
    langgraph>=1.1.0
    langchain-anthropic>=0.3.0
    langgraph-checkpoint-postgres>=2.0.0
    langchain-mcp-adapters>=0.1.0
    fastapi>=0.115.0
    uvicorn[standard]>=0.32.0
    langsmith>=0.2.0
    psycopg[binary]>=3.2.0
    python-dotenv>=1.0.0

03프로젝트 구조

구조권장 프로젝트 레이아웃
    
    
    my-langgraph-agents/
    ├── .env                    # 환경변수 (git 제외)
    ├── .env.example            # 환경변수 템플릿
    ├── requirements.txt
    ├── docker-compose.yml
    ├── Dockerfile
    │
    ├── app/                    # 메인 애플리케이션
    │   ├── __init__.py
    │   ├── main.py             # FastAPI 엔트리포인트
    │   ├── config.py           # 설정 (환경변수 로드)
    │   │
    │   ├── agents/             # 에이전트 정의
    │   │   ├── __init__.py
    │   │   ├── state.py        # State 스키마 (TypedDict)
    │   │   ├── nodes.py        # 노드 함수들
    │   │   ├── graph.py        # StateGraph 구성 + 컴파일
    │   │   └── prompts.py      # 시스템 프롬프트
    │   │
    │   ├── tools/              # 도구 정의
    │   │   ├── __init__.py
    │   │   ├── db_tools.py     # DB 조회 도구
    │   │   ├── api_tools.py    # 외부 API 도구
    │   │   └── mcp_client.py   # MCP 서버 연결
    │   │
    │   └── middleware/          # 미들웨어
    │       ├── auth.py         # 인증
    │       └── audit.py        # 감사 로깅
    │
    ├── mcp-server/             # MCP 도구 서버 (별도 컨테이너)
    │   ├── server.py
    │   ├── tools.py
    │   └── Dockerfile
    │
    └── tests/
        ├── test_agents.py
        └── test_tools.py

💡

**핵심 분리 원칙** State 정의(state.py), 노드 로직(nodes.py), 그래프 구성(graph.py)을 분리하면 테스트와 유지보수가 쉬워요. 프롬프트도 별도 파일로.

04환경변수 & 시크릿 관리

FILE.env.example (git에 커밋)
    
    
    # LLM 프로바이더
    ANTHROPIC_API_KEY=sk-ant-...
    OPENAI_API_KEY=sk-...
    
    # PostgreSQL
    DATABASE_URL=postgresql://user:password@localhost:5432/agentdb
    
    # MCP 서버
    MCP_SERVER_URL=http://localhost:8000/sse
    
    # LangSmith 모니터링
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=lsv2_...
    LANGSMITH_PROJECT=my-agents
    
    # 앱 설정
    APP_ENV=development
    LOG_LEVEL=INFO

PYTHONapp/config.py
    
    
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    class Settings:
        ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        DATABASE_URL = os.getenv("DATABASE_URL")
        MCP_SERVER_URL = os.getenv("MCP_SERVER_URL",
                                    "http://localhost:8000/sse")
        LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false")
        APP_ENV = os.getenv("APP_ENV", "development")
    
    settings = Settings()

⚠️

**보안 필수** `.env`는 절대 git에 커밋하지 마세요. `.gitignore`에 추가. 프로덕션에서는 Vault, AWS Secrets Manager, 또는 Docker secrets 사용.

05LLM 프로바이더 연결

프로바이더| 패키지| 모델 예시| 특징  
---|---|---|---  
**Anthropic**| `langchain-anthropic`| claude-sonnet-4-6, claude-haiku-4-5| 도구 사용 우수, MCP 네이티브  
**OpenAI**| `langchain-openai`| gpt-5.4, gpt-5.4-mini| 범용성, 풍부한 생태계  
**Google**| `langchain-google-genai`| gemini-3.1-flash| 빠른 속도, 비용 효율  
**Ollama (로컬)**| `langchain-ollama`| llama3, mistral| API 비용 없음, GPU 필요  
  
PYTHONLLM 초기화 패턴
    
    
    from langchain_anthropic import ChatAnthropic
    from langchain_openai import ChatOpenAI
    
    # Anthropic (BIP에서 사용)
    llm_haiku = ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
    )
    llm_sonnet = ChatAnthropic(
        model="claude-sonnet-4-6-20260414",
        max_tokens=8000,
    )
    
    # OpenAI
    llm_gpt = ChatOpenAI(
        model="gpt-5.4-mini",
        temperature=0,
    )
    
    # 역할별 분리 (비용 최적화)
    # 단순 판단 → Haiku ($0.003/질문)
    # 복잡 분석 → Sonnet ($0.05/질문)

💡

**BIP 비용 전략** 단순 판단(체크리스트, 뉴스 요약)은 Haiku, 복잡한 분석(모닝리포트)만 Sonnet. 월 $6으로 6개 에이전트 운영 중.

06체크포인터 설정 (PostgreSQL / Oracle RAC)

### 옵션 비교

방안| 장점| 단점| 권장 환경  
---|---|---|---  
**A. PostgreSQL (공식)**|  공식 지원, setup() 자동 생성| 별도 DB 인프라 필요| 신규 구축, PoC  
**B. Oracle RAC (커스텀)**|  기존 Exadata RAC 활용, 추가 인프라 없음| BaseCheckpointSaver 구현 필요 (4~5개 메서드)| 사내 Oracle 있는 경우  
**C. SQLite**|  설치 불필요| 단일 프로세스, HA 불가| 로컬 개발 전용  
  
### A. PostgreSQL 체크포인터 (공식)

체크포인터 DB 스키마 (자동 생성)

erDiagram checkpoints { text thread_id PK text checkpoint_ns text checkpoint_id PK jsonb checkpoint jsonb metadata } checkpoint_blobs { text thread_id FK text channel text version bytea blob } checkpoint_writes { text thread_id FK text task_id int idx text channel bytea blob } checkpoint_migrations { int v PK } checkpoints ||--o{ checkpoint_blobs : "stores large data" checkpoints ||--o{ checkpoint_writes : "intermediate writes" 

SQLDB 생성 (수동 시)
    
    
    -- 전용 데이터베이스 생성 (기존 DB 사용도 가능)
    CREATE DATABASE agentdb;
    
    -- 전용 사용자 (선택)
    CREATE USER agent_user WITH PASSWORD 'secure_password';
    GRANT ALL PRIVILEGES ON DATABASE agentdb TO agent_user;

PYTHON체크포인터 초기화 + 테이블 자동 생성
    
    
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    import psycopg
    
    # 동기 버전
    conn = psycopg.connect(
        "postgresql://user:pass@localhost:5432/agentdb",
        autocommit=True,         # 필수! setup()이 커밋하려면
        row_factory=psycopg.rows.dict_row  # 필수!
    )
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()  # 테이블 자동 생성
    
    # 비동기 버전 (FastAPI에서 사용)
    checkpointer = AsyncPostgresSaver.from_conn_string(
        "postgresql://user:pass@localhost:5432/agentdb"
    )
    await checkpointer.setup()
    
    # 에이전트에 적용
    app = workflow.compile(checkpointer=checkpointer)
    
    # thread_id로 대화 관리
    config = {"configurable": {"thread_id": "user-123-session-1"}}
    result = await app.ainvoke(input_state, config)

⚠️

**필수 설정** `autocommit=True`와 `row_factory=dict_row`가 없으면 setup()이 실패하거나 조회 에러 발생. 가장 흔한 실수.

### B. Oracle RAC 체크포인터 (커스텀)

기존 Oracle 19c Exadata RAC가 있는 사내 환경에서는 별도 PostgreSQL을 추가할 필요 없이 Custom Checkpointer로 기존 인프라를 활용.

Oracle RAC Checkpointer 구조

graph LR subgraph Workers["Stateless Workers"] W1["Worker 1"] W2["Worker 2"] W3["Worker 3"] end subgraph Oracle["Oracle Exadata RAC"] SCAN["SCAN Listener\n단일 DNS 진입점"] N1["RAC Node 1\nActive"] N2["RAC Node 2\nActive"] ASM["ASM\n공유 스토리지"] end W1 -->|"oracledb\n(FAN event)"| SCAN W2 --> SCAN W3 --> SCAN SCAN --> N1 SCAN --> N2 N1 --> ASM N2 --> ASM style Workers fill:#0d0f18,stroke:#30c880 style Oracle fill:#0d0f18,stroke:#e09830 

SQLOracle 테이블 생성
    
    
    -- Checkpoints (상태 저장)
    CREATE TABLE langgraph_checkpoints (
        thread_id             VARCHAR2(128) NOT NULL,
        checkpoint_ns         VARCHAR2(128) DEFAULT '' NOT NULL,
        checkpoint_id         VARCHAR2(128) NOT NULL,
        parent_checkpoint_id  VARCHAR2(128),
        checkpoint_data       BLOB          NOT NULL,   -- JSON 직렬화
        metadata              CLOB,
        updated_at            TIMESTAMP DEFAULT SYSTIMESTAMP,
        CONSTRAINT pk_lg_checkpoint
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    ) TABLESPACE langgraph_data;
    
    -- Channel Writes (중간 상태)
    CREATE TABLE langgraph_writes (
        thread_id       VARCHAR2(128) NOT NULL,
        checkpoint_ns   VARCHAR2(128) DEFAULT '' NOT NULL,
        checkpoint_id   VARCHAR2(128) NOT NULL,
        task_id         VARCHAR2(128) NOT NULL,
        idx             NUMBER(10)    NOT NULL,
        channel         VARCHAR2(256) NOT NULL,
        type            VARCHAR2(256),
        blob_data       BLOB,
        CONSTRAINT pk_lg_writes
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    ) TABLESPACE langgraph_data;
    
    -- 오래된 체크포인트 정리 (30일)
    -- DBMS_SCHEDULER 또는 interval partition 활용

PYTHONOracleCheckpointSaver 구현
    
    
    from langgraph.checkpoint.base import BaseCheckpointSaver
    import oracledb
    import json
    
    class OracleCheckpointSaver(BaseCheckpointSaver):
        """Oracle 19c RAC용 Checkpointer"""
    
        def __init__(self, dsn: str, user: str, password: str):
            super().__init__()
            self.pool = oracledb.create_pool(
                dsn=dsn,           # SCAN DNS
                user=user,
                password=password,
                min=5, max=20,
                increment=2,
                events=True,       # FAN 이벤트 수신 (RAC failover 감지)
            )
    
        def put(self, config, checkpoint, metadata, new_versions):
            """체크포인트 저장 (MERGE = upsert)"""
            thread_id = config["configurable"]["thread_id"]
            checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
            checkpoint_id = checkpoint["id"]
            parent_id = config["configurable"].get("checkpoint_id")
    
            with self.pool.acquire() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        MERGE INTO langgraph_checkpoints t
                        USING (SELECT :tid AS thread_id,
                                      :ns  AS checkpoint_ns,
                                      :cid AS checkpoint_id FROM dual) s
                        ON (t.thread_id = s.thread_id
                            AND t.checkpoint_ns = s.checkpoint_ns
                            AND t.checkpoint_id = s.checkpoint_id)
                        WHEN MATCHED THEN UPDATE SET
                            checkpoint_data = :data,
                            metadata = :meta,
                            updated_at = SYSTIMESTAMP
                        WHEN NOT MATCHED THEN INSERT
                            (thread_id, checkpoint_ns, checkpoint_id,
                             parent_checkpoint_id, checkpoint_data,
                             metadata, updated_at)
                        VALUES (:tid, :ns, :cid, :pid, :data,
                                :meta, SYSTIMESTAMP)
                    """, {
                        "tid": thread_id, "ns": checkpoint_ns,
                        "cid": checkpoint_id, "pid": parent_id,
                        "data": json.dumps(checkpoint).encode(),
                        "meta": json.dumps(metadata),
                    })
                conn.commit()
    
        def get_tuple(self, config):
            """thread_id + checkpoint_ns 기준 최신 checkpoint 조회"""
            # ... SELECT + ORDER BY updated_at DESC FETCH FIRST 1 ROW
    
        def list(self, config, *, filter=None, before=None, limit=10):
            """checkpoint 이력 조회"""
            # ... SELECT + pagination
    
    # 사용
    checkpointer = OracleCheckpointSaver(
        dsn="(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)"
            "(HOST=scan.internal)(PORT=1521))"
            "(CONNECT_DATA=(SERVICE_NAME=CHATBOT)))",
        user="langgraph_svc",
        password=os.environ["ORACLE_PASSWORD"],
    )
    graph = workflow.compile(checkpointer=checkpointer)

💡

**RAC가 제공하는 HA**

  * **SCAN Listener** — Worker는 단일 DNS로 연결, 노드 장애 시 자동 라우팅
  * **FAN 이벤트** — `events=True`로 노드 다운 즉시 감지, 커넥션 풀 자동 정리
  * **Active-Active** — 두 노드 모두 읽기/쓰기 가능, 별도 failover 대기 없음
  * **TAF** — SELECT 중 노드 장애 시 다른 노드에서 자동 재실행



### 운영 공통

운영체크포인트 데이터 관리

  * **데이터 증가** — 매 노드 실행마다 State 저장. 장기 운영 시 주기적 정리 필요
  * **정리** : PostgreSQL `DELETE ... WHERE created_at < NOW() - INTERVAL '30 days'` / Oracle `DBMS_SCHEDULER` 또는 interval partition
  * **스키마 변경** — State TypedDict에 필드 추가 후 기존 체크포인트와 호환 안 될 수 있음. 마이그레이션 계획 필수
  * **커넥션 풀** — PostgreSQL: pgBouncer 20+ / Oracle: oracledb pool `min=5, max=20`



07MCP 서버 구축 & 연동

MCP 서버 ↔ LangGraph 연동 구조

graph LR LG["LangGraph Agent"] -->|"langchain-mcp-adapters"| CLIENT["MCP Client\n(MultiServerMCPClient)"] CLIENT -->|SSE| MCP1["MCP Server 1\n도구 A, B, C"] CLIENT -->|SSE| MCP2["MCP Server 2\n도구 D, E"] MCP1 --> API1["외부 API"] MCP1 --> DB1["데이터베이스"] MCP2 --> API2["다른 서비스"] style LG fill:#1a2540,stroke:#5a7af0,color:#7a9aff style CLIENT fill:#201810,stroke:#e09830,color:#f8b840 style MCP1 fill:#102820,stroke:#30c880,color:#50e898 style MCP2 fill:#102820,stroke:#30c880,color:#50e898 

### 방법 A: @tool 데코레이터 (간단, MCP 불필요)

PYTHON로컬 도구 정의
    
    
    from langchain_core.tools import tool
    
    @tool
    def search_database(query: str) -> str:
        """데이터베이스에서 검색합니다."""
        # 실제 DB 쿼리
        result = db.execute(query)
        return str(result)
    
    @tool
    def get_stock_price(ticker: str) -> str:
        """종목 현재가를 조회합니다."""
        price = api.get_price(ticker)
        return f"{ticker}: {price}원"
    
    # 에이전트에 도구 등록
    agent = create_react_agent(llm, tools=[search_database, get_stock_price])

### 방법 B: MCP 서버 (확장성, 여러 에이전트가 공유)

PYTHONMCP 서버 구축 (mcp-server/server.py)
    
    
    from mcp.server.fastmcp import FastMCP
    
    mcp = FastMCP("my-tools")
    
    @mcp.tool()
    async def search_database(query: str) -> str:
        """데이터베이스에서 검색합니다."""
        result = await db.execute(query)
        return str(result)
    
    @mcp.tool()
    async def get_stock_price(ticker: str) -> str:
        """종목 현재가를 조회합니다."""
        price = await api.get_price(ticker)
        return f"{ticker}: {price}원"
    
    if __name__ == "__main__":
        mcp.run(transport="sse")  # SSE로 노출

PYTHON에이전트에서 MCP 서버 연결
    
    
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langgraph.prebuilt import create_react_agent
    
    # MCP 서버 연결 (여러 서버 동시 연결 가능)
    mcp_client = MultiServerMCPClient({
        "my-tools": {
            "url": "http://localhost:8000/sse",
            "transport": "sse"
        },
        "another-server": {
            "url": "http://localhost:8001/sse",
            "transport": "sse"
        }
    })
    tools = await mcp_client.get_tools()
    
    # 에이전트에 MCP 도구 등록
    agent = create_react_agent(llm, tools)
    result = await agent.ainvoke({"messages": [...]})

ℹ

**MCP vs @tool 판단 기준** 도구를 한 에이전트만 쓰면 @tool로 충분. 여러 에이전트/서비스가 같은 도구를 공유하거나, 도구를 독립 배포/스케일링해야 하면 MCP 서버로 분리. 상세는 → [FastMCP 가이드](<fastmcp_guide.html>) 참조.

08FastAPI 에이전트 서버

PYTHONapp/main.py — 최소 서버
    
    
    from fastapi import FastAPI
    from pydantic import BaseModel
    from app.agents.graph import create_agent
    from app.config import settings
    
    app = FastAPI(title="LangGraph Agent Server")
    
    class AskRequest(BaseModel):
        question: str
        thread_id: str = "default"
    
    class AskResponse(BaseModel):
        answer: str
        tools_used: list[str] = []
    
    @app.post("/api/ask", response_model=AskResponse)
    async def ask(req: AskRequest):
        agent = await create_agent()
        config = {"configurable": {"thread_id": req.thread_id}}
    
        result = await agent.ainvoke(
            {"messages": [{"role": "user",
                           "content": req.question}]},
            config
        )
    
        # 마지막 AI 메시지 추출
        messages = result.get("messages", [])
        answer = messages[-1].content if messages else ""
    
        return AskResponse(answer=answer)
    
    # 실행: uvicorn app.main:app --host 0.0.0.0 --port 8100

PYTHONapp/agents/graph.py — 에이전트 그래프
    
    
    from langgraph.prebuilt import create_react_agent
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langchain_anthropic import ChatAnthropic
    from app.tools.mcp_client import get_mcp_tools
    from app.config import settings
    
    async def create_agent():
        """에이전트 인스턴스 생성"""
        # 체크포인터
        checkpointer = AsyncPostgresSaver.from_conn_string(
            settings.DATABASE_URL
        )
    
        # LLM
        llm = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
        )
    
        # 도구 (MCP 또는 로컬)
        tools = await get_mcp_tools()
    
        # 에이전트 컴파일
        return create_react_agent(
            llm, tools,
            checkpointer=checkpointer,
            prompt="당신은 데이터 분석 전문가입니다."
        )

### 스트리밍 엔드포인트 (실시간 채팅 UI용)

PYTHONSSE 스트리밍
    
    
    from fastapi.responses import StreamingResponse
    
    @app.post("/api/ask/stream")
    async def ask_stream(req: AskRequest):
        agent = await create_agent()
        config = {"configurable": {"thread_id": req.thread_id}}
    
        async def event_generator():
            async for event in agent.astream_events(
                {"messages": [{"role": "user",
                               "content": req.question}]},
                config, version="v2"
            ):
                if event["event"] == "on_llm_stream":
                    token = event["data"]["chunk"].content
                    yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"
    
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream"
        )

09Docker 컨테이너화 & Multi-VM HA 배포

### 기본: 단일 서버 Docker Compose

DOCKERDockerfile
    
    
    FROM python:3.13-slim
    
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    COPY app/ ./app/
    
    EXPOSE 8100
    CMD ["uvicorn", "app.main:app", \
         "--host", "0.0.0.0", "--port", "8100"]

DOCKERdocker-compose.yml (개발/PoC)
    
    
    services:
      agent-server:
        build: .
        ports: ["8100:8100"]
        environment:
          - LLM_API_URL=https://llm-gateway.internal/v1
          - DATABASE_URL=postgresql://user:pass@postgres:5432/agentdb
          - MCP_SERVER_URL=http://mcp-server:8000/sse
          - LANGFUSE_HOST=http://langfuse:3000
        depends_on: [postgres, mcp-server]
    
      mcp-server:
        build: ./mcp-server
        ports: ["8000:8000"]
        environment:
          - DATABASE_URL=postgresql://user:pass@postgres:5432/agentdb
    
      postgres:
        image: postgres:16
        environment:
          POSTGRES_USER: user
          POSTGRES_PASSWORD: pass
          POSTGRES_DB: agentdb
        volumes: [pgdata:/var/lib/postgresql/data]
    
    volumes:
      pgdata:

### 프로덕션: Multi-VM HA 배포 (K8s 없이)

사내 K8s 클러스터를 활용하기 어려운 경우, VM 2~3대 + Docker Compose + 사내 L4 LB로 프로덕션 HA를 구성할 수 있습니다. 핵심은 **Worker가 완전 Stateless** 이므로 어디서든 동일하게 동작한다는 점.

Multi-VM HA 배포 토폴로지

graph TD subgraph LB["Load Balancer (F5 / HAProxy)"] VIP["VIP: 10.x.x.100\nHealth Check: GET /health"] end subgraph VM1["VM-1 (10.x.x.1)"] DC1["docker-compose"] W1A["Worker 1a :8000"] W1B["Worker 1b :8001"] MCP1["MCP Server :9000"] end subgraph VM2["VM-2 (10.x.x.2)"] DC2["docker-compose"] W2A["Worker 2a :8000"] W2B["Worker 2b :8001"] MCP2["MCP Server :9000"] end subgraph VM3["VM-3 (10.x.x.3)"] DC3["docker-compose"] W3A["Worker 3a :8000"] W3B["Worker 3b :8001"] MCP3["MCP Server :9000"] end subgraph Monitoring["모니터링 VM"] LF["LangFuse :3100"] GF["Grafana :3000"] end VIP --> DC1 VIP --> DC2 VIP --> DC3 DC1 --> W1A DC1 --> W1B DC2 --> W2A DC2 --> W2B DC3 --> W3A DC3 --> W3B W1A & W2A & W3A -.-> LF style LB fill:#0d0f18,stroke:#f05050,color:#f08080 style VM1 fill:#0d0f18,stroke:#30c880 style VM2 fill:#0d0f18,stroke:#30c880 style VM3 fill:#0d0f18,stroke:#30c880 style Monitoring fill:#0d0f18,stroke:#9060f0 

| 최소 (HA 최소 충족)| 권장  
---|---|---  
**VM 수**|  2대| 3대  
**Worker / VM**|  1~2개| 2~4개 (CPU 코어 수 따라)  
**총 Worker**|  2~4개| 6~12개  
**LB**|  사내 F5 활용| 별도 HAProxy VM 2대 (Active-Standby)  
**DB**|  기존 Oracle RAC 또는 PostgreSQL  
**VM 스펙**|  4 core / 8GB| 8 core / 16GB  
  
DOCKERdocker-compose.yml (각 VM에 동일 배포)
    
    
    services:
      langgraph-worker:
        image: registry.internal/langgraph-worker:latest
        deploy:
          replicas: 2                          # VM당 2개 Worker
        restart: always
        ports:
          - "8000-8001:8000"
        environment:
          ORACLE_DSN: "(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=scan.internal)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=CHATBOT)))"
          ORACLE_USER: langgraph_svc
          ORACLE_PASSWORD_FILE: /run/secrets/oracle_pw
          LLM_API_URL: https://llm-gateway.internal/v1
          LANGFUSE_HOST: http://langfuse.internal:3100
          LANGFUSE_PUBLIC_KEY: pk-xxx
          LANGFUSE_SECRET_KEY_FILE: /run/secrets/langfuse_sk
          WORKER_CONCURRENCY: 20
        healthcheck:
          test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
          interval: 10s
          timeout: 5s
          retries: 3
        secrets:
          - oracle_pw
          - langfuse_sk
    
      mcp-server:
        image: registry.internal/mcp-server:latest
        restart: always
        ports: ["9000:9000"]
    
    secrets:
      oracle_pw:
        file: /etc/secrets/oracle_pw.txt
      langfuse_sk:
        file: /etc/secrets/langfuse_sk.txt

HAPROXYhaproxy.cfg (상위 LB 설정)
    
    
    frontend langgraph_front
        bind *:443 ssl crt /etc/ssl/langgraph.pem
        default_backend langgraph_workers
    
    backend langgraph_workers
        balance roundrobin
        option httpchk GET /health
        http-check expect status 200
    
        server vm1 10.x.x.1:80 check inter 5s fall 3 rise 2
        server vm2 10.x.x.2:80 check inter 5s fall 3 rise 2
        server vm3 10.x.x.3:80 check inter 5s fall 3 rise 2

SHELL순차 무중단 배포 스크립트
    
    
    #!/bin/bash
    # deploy.sh — VM 순차 무중단 배포 (K8s rolling update 대체)
    SERVERS="vm1 vm2 vm3"
    IMAGE="registry.internal/langgraph-worker:${TAG}"
    
    for server in $SERVERS; do
        echo "=== $server 배포 시작 ==="
        # 1. LB에서 제외 (drain)
        ssh lb "echo 'set server langgraph_workers/$server state drain' \
            | socat stdio /var/run/haproxy.sock"
        # 2. 기존 요청 완료 대기
        sleep 30
        # 3. 새 이미지 pull + 재시작
        ssh $server "cd /opt/langgraph && \
            docker compose pull && docker compose up -d --force-recreate"
        # 4. Health check 통과 대기
        for i in $(seq 1 30); do
            ssh $server "curl -sf http://localhost:80/health" && break
            sleep 2
        done
        # 5. LB 복귀
        ssh lb "echo 'set server langgraph_workers/$server state ready' \
            | socat stdio /var/run/haproxy.sock"
        echo "=== $server 완료 ==="
    done

### 장애 대응 매트릭스

장애| 영향| 자동 대응  
---|---|---  
**Worker 1대 죽음**|  해당 요청 실패| Docker restart: always + LB가 다른 VM으로 라우팅. Checkpointer 덕분에 중간 상태 복구 가능  
**VM 1대 다운**|  해당 VM의 Worker 전체 중단| LB health check 실패 → 자동 제외. 나머지 VM이 처리  
**Oracle Node 다운**|  순간 커넥션 끊김| FAN 이벤트로 자동 감지 → SCAN이 살아있는 노드로 라우팅 (Active-Active)  
**LLM API 타임아웃**|  그래프 노드 실패| Retry with exponential backoff + circuit breaker  
  
SHELLwatchdog.sh (Worker 자동 복구 — crontab 1분)
    
    
    #!/bin/bash
    HEALTHY=$(docker compose ps --format json | jq -r 'select(.Health=="healthy")' | wc -l)
    EXPECTED=2
    if [ "$HEALTHY" -lt "$EXPECTED" ]; then
        docker compose up -d --force-recreate langgraph-worker
        curl -X POST "https://hooks.internal/alert" \
             -d "text=$(hostname) Worker 재시작 ($HEALTHY/$EXPECTED)"
    fi

10Airflow 스케줄링 연동

Airflow → 에이전트 서버 연동 패턴

sequenceDiagram participant AF as Airflow DAG participant API as Agent Server (FastAPI) participant LG as LangGraph Agent participant TG as 텔레그램 AF->>API: POST /api/analyze (스케줄 실행) API->>LG: agent.ainvoke() LG->>LG: 도구 호출 + 분석 LG-->>API: 결과 반환 API-->>AF: JSON 응답 AF->>TG: 텔레그램 발송 

PYTHONAirflow DAG에서 에이전트 호출
    
    
    from airflow import DAG
    from airflow.operators.python import PythonOperator
    import requests
    
    def call_agent(**context):
        """에이전트 서버에 HTTP 호출"""
        resp = requests.post(
            "http://agent-server:8100/api/analyze",
            json={"checklist_text": "...",
                  "time_phase": "intraday"},
            timeout=180,
        )
        result = resp.json()
        print(f"분석 완료: {result['answer'][:100]}")
    
        # 텔레그램 발송
        send_telegram(result["answer"])
    
    with DAG("agent_schedule", schedule="*/10 9-15 * * 1-5"):
        task = PythonOperator(
            task_id="run_agent",
            python_callable=call_agent
        )

ℹ

**BIP 패턴** Airflow는 스케줄링만 담당하고, 에이전트 로직은 BIP-Agents 서버에 위임. HTTP로 느슨하게 결합하면 에이전트 업데이트가 DAG 변경 없이 가능.

11모니터링 — LangFuse (Self-hosted) / LangSmith

### 옵션 비교

도구| 형태| Self-host| 특징| 사내 폐쇄망  
---|---|---|---|---  
**LangSmith**|  SaaS| Enterprise만| 업계 표준, 자동 트레이싱| X (데이터 외부 전송)  
**LangFuse**|  오픈소스| Docker 1줄| LangSmith 대체 1순위| O (권장)  
**Arize Phoenix**|  오픈소스| 단일 컨테이너| 경량, 빠름| O  
  
ℹ

**사내 폐쇄망이면 LangSmith 사용 불가** — 모든 트레이스가 외부 SaaS로 전송됩니다. LangFuse를 사내 VM에 Docker로 띄우면 동일한 기능을 폐쇄망 내부에서 사용할 수 있습니다.

### LangFuse (권장 — Self-hosted)

LangFuse 모니터링 아키텍처

graph LR subgraph Workers["LangGraph Workers"] W1["Worker 1"] W2["Worker 2"] W3["Worker 3"] end subgraph LF_Stack["LangFuse (사내 VM)"] LF_APP["LangFuse Server\n:3100"] LF_DB["PostgreSQL\n(LangFuse 전용)"] end subgraph Features["제공 기능"] TRACE["Traces\n노드별 워터폴"] GEN["Generations\nLLM 입출력/토큰"] SESS["Sessions\n사용자별 세션"] DASH["Dashboard\n요약 차트"] SCORE["Scores\n품질 평가"] PROMPT["Prompts\n버전 관리"] end W1 -->|"CallbackHandler\n(비동기)"| LF_APP W2 --> LF_APP W3 --> LF_APP LF_APP --> LF_DB LF_APP --> Features style Workers fill:#0d0f18,stroke:#30c880 style LF_Stack fill:#0d0f18,stroke:#9060f0 style Features fill:#0d0f18,stroke:#5a7af0 

DOCKERLangFuse 설치 (사내 VM)
    
    
    # docker-compose.langfuse.yml
    services:
      langfuse:
        image: langfuse/langfuse:2
        ports: ["3100:3000"]
        environment:
          DATABASE_URL: postgresql://langfuse:pw@langfuse-db:5432/langfuse
          NEXTAUTH_SECRET: your-secret-key
          NEXTAUTH_URL: http://langfuse.internal:3100
          SALT: your-salt
          TELEMETRY_ENABLED: "false"         # 폐쇄망: 텔레메트리 비활성화
        depends_on: [langfuse-db]
    
      langfuse-db:
        image: postgres:15
        environment:
          POSTGRES_USER: langfuse
          POSTGRES_PASSWORD: pw
          POSTGRES_DB: langfuse
        volumes: [langfuse_data:/var/lib/postgresql/data]
    
    volumes:
      langfuse_data:
    
    # 실행
    # docker compose -f docker-compose.langfuse.yml up -d
    # → http://langfuse.internal:3100 접속

PYTHONLangGraph 연동 (코드 3줄)
    
    
    from langfuse.callback import CallbackHandler
    
    # LangFuse 콜백 생성
    langfuse_handler = CallbackHandler(
        host="http://langfuse.internal:3100",    # 사내 주소
        public_key="pk-...",
        secret_key="sk-...",
    )
    
    # 그래프 실행 시 config에 추가 — 끝
    result = await graph.ainvoke(
        initial_state,
        config={"callbacks": [langfuse_handler]}
    )
    # 자동 수집: 노드별 실행 시간, LLM 입출력, 토큰 수, 에러 트레이스

### LangFuse Trace 상세 화면 예시

UITrace 워터폴 (노드별 실행 타임라인)
    
    
    Trace: "올해 매출 상위 10개 부서"              2.8s  ✅
    ├── router              0.08s  ✅  → nl2sql
    ├── nl2sql_generate     1.20s  ✅  GPT-4o  tokens: 450→120
    │   └── LLM Call        1.18s      prompt: "Convert to SQL..."
    ├── sql_validate        0.15s  ✅  passed
    ├── sql_execute         0.35s  ✅  10 rows
    └── summarize           0.90s  ✅  GPT-4o  tokens: 200→350
        └── LLM Call        0.88s      prompt: "Summarize these..."
    
    Total: 2.8s | Tokens: 650 in / 470 out | Cost: $0.023

### LangFuse 제공 기능

기능| 설명  
---|---  
**Traces**|  노드별 실행 시간, 도구 호출, LLM 입출력 워터폴 시각화  
**Generations**|  LLM 호출별 프롬프트, 응답, 토큰 수, 비용  
**Sessions**|  사용자별 대화 세션 그룹핑  
**Dashboard**|  일별 실행 수, 토큰 사용량, 에러율, 평균 지연시간  
**Scores**|  품질 평가 — 자동(LLM-as-Judge) / 수동(사용자 피드백)  
**Prompts**|  프롬프트 버전 관리 + 배포  
**Users**|  사용자별 사용량, 비용, 에러율 추적  
  
### 인프라 메트릭: Grafana (기존 활용)

LangFuse는 에이전트 실행 트레이싱 전용. CPU, 메모리, Worker 상태 등 인프라 메트릭은 기존 Grafana + Prometheus를 활용.

PYTHONPrometheus 메트릭 노출 (Worker)
    
    
    from prometheus_client import Counter, Histogram, Gauge
    
    graph_runs_total = Counter(
        "langgraph_runs_total", "Total graph executions",
        ["graph_id", "status"]
    )
    node_duration = Histogram(
        "langgraph_node_duration_seconds", "Node execution time",
        ["node_name"]
    )
    active_runs = Gauge(
        "langgraph_active_runs", "Currently running graphs"
    )
    llm_tokens_total = Counter(
        "langgraph_llm_tokens_total", "LLM tokens consumed",
        ["direction"]   # input / output
    )

### (참고) LangSmith — SaaS 환경용

설정외부 인터넷 사용 가능한 경우
    
    
    # 환경변수만 설정하면 자동 트레이싱 (코드 변경 없음)
    LANGSMITH_TRACING=true
    LANGSMITH_ENDPOINT=https://api.smith.langchain.com
    LANGSMITH_API_KEY=lsv2_pt_xxxxxxxx
    LANGSMITH_PROJECT=my-agents

⚠️

**사내 폐쇄망에서는 사용 불가** 모든 트레이스 데이터가 외부 LangSmith 서버로 전송됩니다. 사내 데이터 유출 가능성이 있으므로 폐쇄망에서는 LangFuse (Self-hosted)를 권장합니다.

12보안 & 거버넌스

보안 체크 흐름

graph TD INPUT["사용자 입력"] --> GUARD["Guardrail\n입력 검증\nPII/인젝션 차단"] GUARD -->|통과| AGENT["에이전트 실행"] GUARD -->|차단| REJECT["거부 응답"] AGENT --> AUDIT["감사 로그\nagent_audit_log"] AGENT --> FILTER["출력 필터\n민감 정보 마스킹"] FILTER --> OUTPUT["응답"] style GUARD fill:#201010,stroke:#f05050,color:#f08080 style AUDIT fill:#201810,stroke:#e09830,color:#f8b840 

보안 항목| 구현 방법  
---|---  
**API 키 보호**| .env + Docker secrets. 절대 코드/git에 하드코딩 금지  
**DB 접근 제어**|  에이전트 전용 DB 계정 (읽기 전용 or 특정 테이블만)  
**루프 제한**|  Conditional Edge에 `iteration < max` 필수. 무한 루프 = API 비용 폭발  
**감사 로그**|  모든 LLM 호출을 DB에 기록 (에이전트명, 토큰, 도구, 결과)  
**입력 검증**|  프롬프트 인젝션 방지. Guardrail 노드로 입력 필터링  
**출력 필터**|  PII(개인정보), 민감 데이터가 응답에 노출되지 않도록  
  
13트러블슈팅

증상| 원인| 해결  
---|---|---  
**checkpointer.setup() 실패**|  autocommit=True 누락| `psycopg.connect(..., autocommit=True)`  
**체크포인트 조회 에러**|  row_factory 미설정| `row_factory=psycopg.rows.dict_row`  
**MCP 연결 끊김**|  SSE 타임아웃| try/finally로 `mcp_client.close()` 보장  
**에이전트 무한 루프**|  Conditional Edge에 종료 조건 누락| `iteration < 3` 가드 추가  
**토큰 한도 초과**|  긴 대화 컨텍스트| context_compressor로 요약 또는 새 thread 시작  
**LangSmith에 트레이스 안 뜸**|  환경변수 미설정| `LANGSMITH_TRACING=true` 확인  
**State 스키마 호환 에러**|  TypedDict 변경 후 기존 체크포인트| thread_id를 새로 생성하거나 체크포인트 정리  
**도구 호출 실패 (404)**|  MCP 서버 미실행 또는 URL 오류| docker ps로 확인, MCP_SERVER_URL 검증  
  
14비용 가이드

항목| 비용| 비고  
---|---|---  
**LangGraph**|  무료 (MIT)| 오픈소스  
**Haiku 호출**|  ~$0.003/질문| 단순 판단용 최적  
**Sonnet 호출**|  ~$0.05/질문| 복잡 분석용  
**PostgreSQL**|  셀프호스팅 무료| Docker 볼륨  
**LangSmith**|  무료 티어 있음| 프로덕션은 유료 권장  
**인프라 오버헤드**|  +10~20%| 체크포인팅 DB I/O  
  
💡

**BIP 실제 비용** 6개 에이전트(모닝리포트/체크리스트/preopen/스크리너/뉴스/인사이트) 운영에 월 ~$6. Haiku 중심 + Sonnet은 분석에만.

15BIP 적용 사례 요약

에이전트| 패턴| LLM| 도구| 스케줄  
---|---|---|---|---  
**체크리스트 모니터링**|  ReAct| Haiku| MCP 44개| 10분마다  
**종목 추천**|  멀티 노드 (Bull/Bear 토론)| Haiku| MCP| 일 1회  
**Preopen 분석**|  단일 LLM + MCP 병렬| Haiku| MCP| 08:40  
**모닝리포트**|  단일 LLM| Sonnet| 뉴스 API| 08:10  
**뉴스 다이제스트**|  단일 LLM| Haiku| 뉴스 API| 4시간마다  
  
### BIP에서 얻은 교훈

성공

잘 작동한 것

  * ReAct + MCP: 코드 변경 없이 새 항목 대응
  * Haiku 중심: 월 $6으로 6개 에이전트
  * Airflow↔FastAPI: 느슨한 결합



교훈

다음에 주의할 것

  * 프롬프트가 결과의 80%. 구조보다 중요
  * 테스트 환경 반드시 분리 (채널 오염)
  * 감사 로그는 처음부터. 나중에 추가 어려움



16참고 자료

[LangGraph 기술 가이드](<langgraph_technical_guide.html>) — 핵심 개념, 아키텍처 패턴, 코드 예시 (스터디용)

[BIP 에이전트 전략](<bip_agent_strategy.html>) — 차세대 아키텍처 검토

[GitHub — langgraph](<https://github.com/langchain-ai/langgraph>) (29.2K stars, MIT)

[LangGraph 공식 문서](<https://docs.langchain.com/oss/python/langgraph/overview>)

[Quickstart 가이드](<https://docs.langchain.com/oss/python/langgraph/quickstart>)

[langgraph-checkpoint-postgres (PyPI)](<https://pypi.org/project/langgraph-checkpoint-postgres/>)

[LangFuse 공식 문서 (Self-hosted 가이드 포함)](<https://langfuse.com/docs>)

[LangFuse + LangChain/LangGraph 연동 가이드](<https://langfuse.com/docs/integrations/langchain/tracing>)

[LangSmith 설정 가이드 (SaaS 환경용)](<https://docs.langchain.com/langsmith/platform-setup>)

[FastAPI + MCP + LangGraph 템플릿 (GitHub)](<https://github.com/NicholasGoh/fastapi-mcp-langgraph-template>)

[FastAPI + LangGraph + MCP 튜토리얼 (Medium)](<https://medium.com/@termtrix/building-a-simple-ai-agent-using-fastapi-langgraph-mcp-03fc7ffbea59>)

langgraph-setup.guide · Step-by-Step v2.0 · 2026.04.18

MIT License · LangChain
