# FastMCP  
가이드

MCP(Model Context Protocol)는 AI 에이전트가 외부 도구와 데이터에 접근하는 표준 프로토콜. FastMCP는 이를 Python 데코레이터 한 줄로 구현할 수 있게 해주는 프레임워크. 도구 정의 → 스키마 자동 생성 → 서버 실행까지 5분.

24.5K Stars Apache 2.0 v3.2 Anthropic 표준 Python Prefect

## MCP란? — 에이전트의 USB 포트

MCP 프로토콜 구조

graph LR subgraph Hosts["MCP 호스트 (AI 에이전트)"] H1["Claude Desktop"] H2["LangGraph Agent"] H3["자체 앱"] end subgraph Protocol["MCP 프로토콜"] P["표준화된 인터페이스\nTools / Resources / Prompts"] end subgraph Servers["MCP 서버"] S1["DB 도구"] S2["API 래핑"] S3["파일 시스템"] S4["웹 검색"] end Hosts --> Protocol Protocol --> Servers style Protocol fill:#201810,stroke:#e09830,color:#f8b840 

MCP

Model Context Protocol

Anthropic이 2024년 공개한 AI 도구 연결 표준. "AI 에이전트의 USB-C"라고 불림.

어떤 AI 에이전트든 MCP 서버에 연결하면 도구를 사용 가능. 프로바이더 독립적.

FASTMCP

FastMCP

MCP 서버를 Python 데코레이터로 빠르게 구축하는 프레임워크. Prefect가 관리.

FastMCP 1.0은 공식 MCP Python SDK에 편입됨. v3.0에서 독립적으로 진화.

01설치

SHELL설치
    
    
    # uv 사용 (권장)
    uv pip install fastmcp
    
    # pip 사용
    pip install fastmcp
    
    # LangGraph 연동용
    pip install langchain-mcp-adapters

02Tools — 도구 정의

개념Tool = LLM이 호출하는 함수

Python 함수에 `@mcp.tool` 데코레이터를 붙이면, 타입 힌트와 docstring에서 **스키마가 자동 생성** 됩니다. JSON Schema, 검증, 에러 처리 전부 자동.

PYTHON도구 정의 기본
    
    
    from fastmcp import FastMCP
    
    mcp = FastMCP("my-server")
    
    @mcp.tool
    def get_stock_price(ticker: str) -> dict:
        """종목 현재가를 조회합니다.
    
        Args:
            ticker: 종목 코드 (예: 005930)
        """
        price = fetch_from_api(ticker)
        return {"ticker": ticker, "price": price}
    
    @mcp.tool
    async def search_news(query: str, count: int = 5) -> list:
        """뉴스를 검색합니다.
    
        Args:
            query: 검색어
            count: 결과 수 (기본 5)
        """
        results = await news_api.search(query, count)
        return results

💡

**docstring이 곧 설명** LLM은 이 docstring을 읽고 도구를 선택합니다. 잘 쓰면 LLM이 도구를 정확하게 호출하고, 못 쓰면 엉뚱한 도구를 선택합니다.

03Resources — 리소스 노출

PYTHON리소스 정의
    
    
    # 정적 리소스
    @mcp.resource("config://app-settings")
    def get_settings() -> str:
        """앱 설정을 반환합니다."""
        return json.dumps({"version": "1.0", "env": "production"})
    
    # 동적 리소스 (URI 템플릿)
    @mcp.resource("db://table/{table_name}")
    def get_table_schema(table_name: str) -> str:
        """테이블 스키마를 반환합니다."""
        schema = db.get_schema(table_name)
        return json.dumps(schema)

ℹ

**Tool vs Resource** Tool은 "행동"(API 호출, DB 쿼리), Resource는 "데이터"(설정, 스키마, 문서). Tool은 LLM이 호출하고, Resource는 컨텍스트로 주입됩니다.

04Prompts — 프롬프트 템플릿

PYTHON프롬프트 템플릿 정의
    
    
    @mcp.prompt
    def analyze_stock(ticker: str) -> str:
        """종목 분석 프롬프트"""
        return f"""다음 종목을 분석해주세요:
        - 종목코드: {ticker}
        - get_stock_price 도구로 현재가 확인
        - search_news 도구로 관련 뉴스 검색
        - 종합 판단 제시"""

05전송 모드 비교

3가지 전송 모드 비교

graph TD subgraph STDIO["stdio"] S_C["클라이언트"] -->|stdin/stdout| S_S["서버\n(서브프로세스)"] end subgraph SSE["SSE (Server-Sent Events)"] E_C["클라이언트"] -->|"HTTP POST /messages"| E_S["서버"] E_S -->|"SSE /sse"| E_C end subgraph HTTP["Streamable HTTP (최신)"] H_C["클라이언트"] -->|"POST /mcp"| H_S["서버"] H_S -->|"JSON or SSE"| H_C end style STDIO fill:#0d0f18,stroke:#30c880 style SSE fill:#0d0f18,stroke:#e09830 style HTTP fill:#0d0f18,stroke:#5a7af0 

항목| stdio| SSE| Streamable HTTP  
---|---|---|---  
**통신 방식**|  stdin/stdout 파이프| HTTP POST + SSE 스트림 (2 엔드포인트)| 단일 HTTP 엔드포인트 (/mcp)  
**적합 환경**|  로컬 데스크톱 앱| 원격 서버 (레거시)| 원격 서버 (최신 표준)  
**성능**|  최고 (네트워크 없음)| 좋음| 좋음  
**수평 확장**|  불가| 제한적 (long-lived 연결)| 가능 (stateless)  
**호환성**|  Claude Desktop 등| BIP 현재 사용 중| 2026 최신 표준  
**상태**|  유지| Deprecated (→ Streamable HTTP)| 권장  
  
💡

**판단 기준** 서버와 클라이언트가 같은 머신이면 **stdio**. 다른 머신(Docker, 클라우드)이면 **Streamable HTTP** (또는 레거시 환경에서 SSE). BIP는 Docker 구성이라 SSE 사용 중.

06SSE 서버 구성

PYTHONSSE 모드 서버 실행
    
    
    from fastmcp import FastMCP
    
    mcp = FastMCP(
        name="my-tools",
        host="0.0.0.0",  # 외부 접근 허용
        port=8000,
    )
    
    @mcp.tool
    def my_tool(query: str) -> str:
        """도구 설명"""
        return f"결과: {query}"
    
    if __name__ == "__main__":
        mcp.run(transport="sse")
    
    # 실행: python server.py
    # → http://0.0.0.0:8000/sse 에서 SSE 엔드포인트 노출

PYTHONStreamable HTTP 모드 (최신)
    
    
    # Streamable HTTP는 단일 엔드포인트
    if __name__ == "__main__":
        mcp.run(transport="streamable-http")
    
    # → http://0.0.0.0:8000/mcp 에서 단일 엔드포인트 노출
    # 클라이언트가 JSON 또는 SSE를 선택적으로 수신

CLICLI로 실행
    
    
    # stdio 모드 (기본)
    fastmcp run server.py
    
    # SSE 모드
    fastmcp run server.py --transport sse
    
    # Streamable HTTP
    fastmcp run server.py --transport streamable-http
    
    # 포트 지정
    fastmcp run server.py --transport sse --port 9000

07LangGraph 연동

LangGraph ↔ MCP 연동 아키텍처

graph LR LG["LangGraph Agent\ncreate_react_agent"] -->|langchain-mcp-adapters| CLIENT["MultiServerMCPClient"] CLIENT -->|SSE| MCP1["MCP Server 1\nDB 도구"] CLIENT -->|SSE| MCP2["MCP Server 2\nAPI 도구"] CLIENT -->|stdio| MCP3["MCP Server 3\n로컬 도구"] style LG fill:#1a2540,stroke:#5a7af0,color:#7a9aff style CLIENT fill:#201810,stroke:#e09830,color:#f8b840 style MCP1 fill:#102820,stroke:#30c880,color:#50e898 style MCP2 fill:#102820,stroke:#30c880,color:#50e898 style MCP3 fill:#102820,stroke:#30c880,color:#50e898 

PYTHONMultiServerMCPClient로 연결
    
    
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langgraph.prebuilt import create_react_agent
    from langchain_anthropic import ChatAnthropic
    
    # 여러 MCP 서버 동시 연결 (전송 모드 혼합 가능)
    mcp_client = MultiServerMCPClient({
        "stock-tools": {
            "url": "http://mcp-server:8000/sse",
            "transport": "sse",
        },
        "local-tools": {
            "command": "python",
            "args": ["local_mcp.py"],
            "transport": "stdio",
        },
    })
    
    # MCP 도구를 LangChain 도구로 변환
    tools = await mcp_client.get_tools()
    print(f"로드된 도구: {len(tools)}개")
    
    # LangGraph 에이전트에 도구 등록
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001")
    agent = create_react_agent(llm, tools)
    
    # 실행
    result = await agent.ainvoke({
        "messages": [{"role": "user",
                      "content": "삼성전자 현재가 알려줘"}]
    })
    
    # 정리 (SSE 연결 해제)
    await mcp_client.close()

⚠️

**MultiServerMCPClient는 stateless** 각 도구 호출마다 새 세션을 생성합니다. SSE 연결은 반드시 `mcp_client.close()`로 정리하세요. BIP에서는 try/finally로 보장.

팁전송 모드 혼합

`MultiServerMCPClient`는 서버마다 다른 전송 모드를 지정할 수 있습니다. 원격 서버는 SSE, 로컬 도구는 stdio로 혼합하면 에이전트가 **모든 도구를 동일하게** 사용합니다.

08FastMCP 클라이언트 (서버 없이 테스트)

PYTHONFastMCP Client로 직접 호출
    
    
    from fastmcp import Client
    
    # URL로 원격 서버 연결
    async with Client("http://localhost:8000/sse") as client:
        # 도구 목록 조회
        tools = await client.list_tools()
        print(f"사용 가능한 도구: {[t.name for t in tools]}")
    
        # 도구 호출
        result = await client.call_tool(
            "get_stock_price",
            {"ticker": "005930"}
        )
        print(result)
    
        # 리소스 조회
        resource = await client.read_resource("config://app-settings")
        print(resource)

09Docker 배포

DOCKERFILEMCP 서버 Dockerfile
    
    
    FROM python:3.13-slim
    
    WORKDIR /app
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    
    COPY *.py .
    
    EXPOSE 8000
    CMD ["python", "server.py"]

DOCKERdocker-compose.yml (에이전트 서버와 함께)
    
    
    services:
      mcp-server:
        build: ./mcp-server
        ports: ["8000:8000"]
        environment:
          - DATABASE_URL=postgresql://user:pass@postgres:5432/db
          - KIS_APP_KEY=${KIS_APP_KEY}      # 외부 API 키
          - MCP_TRANSPORT=sse
          - MCP_HOST=0.0.0.0
          - MCP_PORT=8000
    
      agent-server:
        build: ./agent
        ports: ["8100:8100"]
        environment:
          - MCP_SERVER_URL=http://mcp-server:8000/sse
          - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
        depends_on: [mcp-server]

10디버깅 & MCP Inspector

CLIMCP Inspector 실행
    
    
    # Inspector 실행 (웹 UI 자동 열림)
    fastmcp dev server.py
    
    # → http://127.0.0.1:6274 에서 웹 인터페이스
    # - Connect 클릭
    # - Tools 탭: 등록된 도구 목록 + 테스트
    # - Resources 탭: 리소스 조회 테스트
    # - Prompts 탭: 프롬프트 테스트

💡

**Inspector는 개발 필수 도구** 도구를 만들 때마다 Inspector에서 먼저 테스트하세요. 스키마가 의도대로 생성되었는지, 응답 형식이 맞는지 시각적으로 확인 가능.

11MCP 서버 설계 패턴

패턴 A

단일 서버 — 모든 도구를 하나에

소규모 프로젝트, 도구 10~20개. 배포 단순. BIP 초기에 이 패턴.

패턴 B

도메인별 분리 — 서버 여러 개

DB 도구 서버 + API 도구 서버 + 검색 서버. 독립 스케일링 가능.

패턴 C

모듈 분리 + 단일 서버

파일은 분리(db.py, api.py)하지만 하나의 FastMCP에 등록. BIP 현재 패턴.

패턴 D

Gateway 패턴

MCP 서버가 FastAPI 뒤에 위치. 인증/로깅을 API Gateway에서 처리.

ℹ

**BIP의 선택: 패턴 C** 7개 파일(server.py, realtime.py, db.py, dart.py, krx.py, news.py, context.py)로 모듈 분리하되, 하나의 FastMCP 인스턴스에 44개 도구 등록. 배포는 Docker 컨테이너 1개.

12BIP MCP 서버 실전 사례

## bip-stock-mcp — 44개 도구의 실제 구성

BIP MCP 서버 내부 구조

graph TD MCP["FastMCP\nbip-stock-mcp"] --> SV["server.py\n도구 등록 (44개)"] SV --> RT["realtime.py\n한투 API\n시세/수급/예상체결"] SV --> DB_M["db.py\nPostgreSQL\n투자자동향/반도체/지표"] SV --> DART["dart.py\nDART API\n공시/재무제표"] SV --> KRX["krx.py\nKRX\n거래정보/지수"] SV --> NEWS["news.py\n네이버/웹\n뉴스 검색"] SV --> CTX["context.py\nget_indicator_context\n90일 통계"] style MCP fill:#201810,stroke:#e09830,color:#f8b840 style RT fill:#102820,stroke:#30c880,color:#50e898 style DB_M fill:#1a2540,stroke:#5a7af0,color:#7a9aff 

PYTHONBIP server.py 실제 구조
    
    
    from fastmcp import FastMCP
    
    # 모듈에서 함수 import
    from realtime import (
        get_realtime_stock_price, get_realtime_index,
        get_realtime_investor, get_preopen_price, ...
    )
    from db import fetch_investor_flow, fetch_semiconductor_prices
    from dart import get_disclosure_list, get_financial_statement
    from news import search_naver_news, search_web
    from context import get_indicator_context
    
    mcp = FastMCP(
        name="bip-stock-mcp",
        host="0.0.0.0",
        port=8000,
    )
    
    # 실시간 시세 (한투 API)
    @mcp.tool
    async def realtime_stock_price(code: str) -> dict:
        """종목 현재가 조회 (한투 API, 6자리 코드)."""
        return await get_realtime_stock_price(code)
    
    @mcp.tool
    async def realtime_index(index_name: str = "KOSPI") -> dict:
        """KOSPI/KOSDAQ 지수 조회."""
        return await get_realtime_index(index_name)
    
    # ... 44개 도구 등록
    
    if __name__ == "__main__":
        mcp.run(transport="sse")

### 도구 카테고리별 분포

카테고리| 파일| 도구 수| 데이터 소스  
---|---|---|---  
**실시간 시세**|  realtime.py| 11| 한투 API (KIS)  
**DB 조회**|  db.py| 8| PostgreSQL  
**공시/재무**|  dart.py| 5| DART API  
**거래 정보**|  krx.py| 4| KRX  
**뉴스 검색**|  news.py| 3| 네이버/웹  
**지표 맥락**|  context.py| 1| DB (90일 통계)  
**글로벌**|  realtime.py| 6| yfinance, Upbit  
**장전 분석**|  realtime.py| 3| 한투 API  
**섹터**|  realtime.py| 3| KRX/DB  
**합계**| **44개**|   
  
💡

**BIP 운영 팁**

  * 외부 API 토큰은 **파일 캐시** 로 컨테이너 재시작 대비 (한투 KIS 토큰 22시간 유효)
  * 각 도구는 **자체 에러 핸들링** — API 실패 시 `{"error": "..."}` 반환, 서버 전체 크래시 방지
  * 도구 이름은 **LLM이 이해하기 쉽게** — `realtime_stock_price`, `night_futures_ewy`
  * 비동기 함수(`async def`) 필수 — I/O 바운드 작업이 대부분이라 동시 호출 성능



13참고 자료

[GitHub — FastMCP](<https://github.com/jlowin/fastmcp>) (24.5K stars, Apache 2.0)

[FastMCP 공식 문서](<https://gofastmcp.com>)

[MCP 공식 사이트 (Anthropic)](<https://modelcontextprotocol.io>)

[langchain-mcp-adapters (LangChain ↔ MCP)](<https://github.com/langchain-ai/langchain-mcp-adapters>)

[MCP 전송 프로토콜 비교 (MCPcat)](<https://mcpcat.io/guides/comparing-stdio-sse-streamablehttp/>)

[FastMCP + LangGraph 원격 서버 구축 (Medium)](<https://medium.com/@anoopninangeorge/building-a-remote-mcp-server-a-mcp-client-with-fastmcp-langchain-langgraph-17cf0e8d043b>)

[FastMCP 튜토리얼 (Firecrawl)](<https://www.firecrawl.dev/blog/fastmcp-tutorial-building-mcp-servers-python>)

[LangGraph 기술 가이드](<langgraph_technical_guide.html>)

[LangGraph 사내 환경 구축 가이드](<langgraph_enterprise_guide.html>)

fastmcp.guide · v3.2 기준 · 2026.04.14

Apache 2.0 · Prefect / Anthropic MCP
