_Enterprise_ LLM Chatbot 권한 제어 설계안 Java + Python Hybrid · 2026.04

개요

00요구사항 & 과제 01핵심 설계 원칙 02전체 아키텍처

권한 제어

03JWT 전파 흐름 04레이어별 역할 05요청 처리 흐름

도구별 권한

06MCP Tools 07NL2SQL 08RAG

구현 상세

09Spring 쪽 구현 10Python 쪽 구현 11프로젝트 구조

운영 & 보안

12감사 & 모니터링 13정보 누출 방지 14실패 모드 대응

실행 계획

15단계별 로드맵 16런칭 체크리스트

Enterprise Chatbot · Permission-Aware Architecture

# 엔터프라이즈 LLM 챗봇  
권한 제어 설계안

기존 Java Spring 시스템의 권한 정책을 100% 재사용하면서 NL2SQL + RAG + MCP Tools + LangGraph 에이전트를 통합한 하이브리드 아키텍처. Python 사이드카가 에이전트 오케스트레이션을 담당하고, 권한 판단은 기존 Spring에만 존재합니다.

Java Spring (기존) Python Sidecar JWT Propagation LangGraph Agent Zero Trust Principles

## 해결할 문제

REQUIREMENT

복잡한 질의 처리 역량

  * 자연어 → SQL (NL2SQL)
  * 문서 검색 (RAG)
  * 다양한 도구 호출 (MCP)
  * 멀티 스텝 추론 (LangGraph)



CONSTRAINT

권한 제약

  * 사용자별 접근 가능 데이터 상이
  * 기존 시스템 권한 정책 재사용
  * 권한 없는 데이터는 응답에 절대 포함 불가
  * 정보 누출·hallucination 방지



STACK

기존 시스템

  * Java Spring Boot + Spring Security
  * Oracle DB (애플리케이션 필터링)
  * Elasticsearch
  * 사내 SSO + JWT 인증



LLM

사내 LLM API

  * 사내 LLM Gateway 경유
  * 서비스 계정 인증 (사용자와 별도)
  * OpenAI 호환 또는 커스텀 스펙
  * 쿼터/감사 정책 적용



01핵심 설계 원칙 (불변 조건)

P-01

**권한 판단은 기존 Spring에만 존재한다** Python 사이드카는 권한을 해석·결정하지 않는다. JWT를 들고 Spring API에 물어본다.

P-02

**Python은 DB에 직접 접근하지 않는다** 모든 데이터 조회는 기존 Spring REST API 또는 전용 NL2SQL 실행 API를 경유한다.

P-03

**사용자 JWT는 전체 레이어에 동일하게 전파된다** Spring UI → Python LLM → MCP → Spring REST API까지 같은 토큰이 Authorization 헤더로 흐른다.

P-04

**LLM API 자격증명과 사용자 JWT는 완전히 분리된다** 사내 LLM API 호출은 서비스 계정, 사용자 권한 제어는 JWT. 섞이지 않는다.

P-05

**Default Deny** 권한 검증 실패·에러·타임아웃 시 데이터 반환 금지. 일반화된 메시지만 반환.

P-06

**권한 없는 데이터는 LLM 컨텍스트에 애초에 들어가지 않는다** 후처리 마스킹이 아닌, 도구 응답 단계에서 차단. LLM이 보면 이미 늦다.

P-07

**모든 데이터 접근은 감사 기록된다** 누가, 언제, 무엇을 조회했는지 추적 가능. Spring의 기존 감사 로그와 통합.

P-08

**에러 메시지도 권한에 따라 차등** "X 테이블 접근 금지" 같은 메타 정보 노출 금지. "요청하신 정보 제공 불가"로 일반화.

02전체 아키텍처

하이브리드 아키텍처 전체 구성

graph TD USER["사용자 (브라우저)"] SSO["기존 SSO / IdP"] subgraph Spring["기존 Java Spring 시스템"] UI["/chat 페이지\nThymeleaf or 기존 프론트"] PROXY["/api/chat 프록시\nChatController"] BIZ_API["기존 REST API\nCustomer/Order/...\n@PreAuthorize"] NL2SQL_API["/api/nl2sql/execute\nSQL 검증 + 권한 필터 + 실행"] RAG_API["/api/rag/verify\n문서 권한 검증"] SPRING_SEC["Spring Security\nJWT 검증 + 권한"] end subgraph Python["Python LLM 사이드카 (신규)"] GW["FastAPI Gateway\nJWT 검증"] AGENT["LangGraph Agent\nState: user_token"] MCP["MCP 도구들\n기존 API 래퍼"] end LLM_API["사내 LLM API\n서비스 계정 인증"] subgraph Data["데이터 레이어"] ORA["Oracle DB"] ES["Elasticsearch"] VEC["Vector DB\n권한 메타데이터"] end USER -->|로그인| SSO SSO -->|JWT| USER USER -->|JWT| UI UI -->|JWT| PROXY PROXY -->|JWT| GW GW --> AGENT AGENT --> MCP AGENT -->|서비스 계정| LLM_API MCP -->|JWT| BIZ_API MCP -->|JWT| NL2SQL_API MCP -->|JWT| RAG_API BIZ_API --> SPRING_SEC NL2SQL_API --> SPRING_SEC RAG_API --> SPRING_SEC BIZ_API --> ORA BIZ_API --> ES NL2SQL_API --> ORA RAG_API --> VEC style Spring fill:#0d0f18,stroke:#5a7af0 style Python fill:#0d0f18,stroke:#30c880 style Data fill:#0d0f18,stroke:#e09830 

🔐

**아키텍처 핵심** Python 사이드카는 "에이전트 오케스트레이션"만 담당. 모든 데이터 접근은 반드시 Spring API를 경유하며, Spring Security가 기존과 동일하게 권한을 집행합니다. Python 코드가 손상되어도 Spring에서 막힙니다. 

## 왜 하이브리드인가?

접근법| 장점| 단점| 선택  
---|---|---|---  
순수 Spring (Spring AI) | 단일 JVM, 배포 단순, 권한 자연스러움 | LangGraph 고급 기능 제한, MCP 생태계 Java 지원 약함 | 부적합 (요구사항 복잡)  
순수 Python | LangGraph/MCP 완전 활용 | 기존 Spring 권한·API 재사용 어려움 | 부적합 (권한 재구현 부담)  
**Spring + Python 사이드카 (채택)** | 기존 권한 100% 재사용, LangGraph/MCP 고급 기능 활용, 느슨한 결합 | 두 언어 스택, JWT 전파 설계 필요 | 최적  
  
03JWT 전파 흐름

JWT가 전체 레이어에 전파되는 시퀀스

sequenceDiagram participant U as 사용자 participant SSO as SSO/IdP participant UI as Spring UI participant PX as Spring /api/chat participant PY as Python Gateway participant AG as LangGraph Agent participant TL as MCP Tool participant API as Spring REST API participant DB as Oracle/ES U->>SSO: 로그인 SSO-->>U: JWT 발급 U->>UI: /chat (JWT in Cookie/Header) UI->>PX: 질문 전송 (JWT) Note over PX: JWT 추출 후 Authorization Bearer로 설정 PX->>PY: POST /api/ask\nAuthorization: Bearer {JWT} Note over PY: JWT 검증 (Spring과 동일 공개키) PY->>AG: 에이전트 실행\nstate.user_token = JWT AG->>TL: 도구 호출 (state에서 JWT 전달) TL->>API: GET /api/customers\nAuthorization: Bearer {JWT} Note over API: Spring Security가 JWT 검증\n@PreAuthorize 권한 체크 API->>DB: 사용자 권한 필터 적용 조회 DB-->>API: 필터링된 데이터 API-->>TL: 권한 범위 내 응답 TL-->>AG: 결과 (이미 권한 필터링됨) AG-->>PY: LLM이 해석한 답변 PY-->>PX: 최종 응답 PX-->>UI: JSON UI-->>U: 채팅 답변 표시 

🔑

**JWT 전파의 핵심** 동일한 JWT가 레이어를 타고 최종 Spring API까지 도달합니다. Spring Security가 JWT를 검증하고 기존 권한 로직이 작동하므로, 사용자가 챗봇을 쓰든 기존 UI를 쓰든 **동일한 데이터 범위** 가 보장됩니다. 

04레이어별 역할 & 책임

레이어| 역할| 권한 관련 책임| 기술  
---|---|---|---  
**Spring UI** | 채팅 페이지 렌더링 | 기존 인증 세션 재사용 | Thymeleaf / 기존 프론트  
**Spring 프록시** | LLM 서비스로 요청 중계 | JWT 추출 → Bearer 헤더로 전달 | Spring Controller  
**Python Gateway** | API 진입점 | JWT 검증 (Spring과 동일 공개키) | FastAPI + python-jose  
**LangGraph Agent** | 에이전트 오케스트레이션 | State에 user_token 보관 & 전파 | LangGraph + LangChain  
**MCP Tools** | 기존 API 래핑 | JWT를 Spring API로 릴레이 | FastMCP + httpx  
**Spring REST API** | 실제 데이터 조회 | **권한 집행 (핵심)** | Spring Security + @PreAuthorize  
**Oracle / ES** | 데이터 저장 | 기존 방식 (VPD or 앱 필터) | Oracle 19c / ES  
  
권한 책임 분리 (Separation of Concerns)

graph LR subgraph NoAuth["권한 판단 없음"] PY_G["Python Gateway\nJWT 검증만"] AG["LangGraph Agent\n오케스트레이션"] MCP["MCP Tools\n릴레이"] end subgraph Auth["권한 판단 담당"] SPRING["Spring REST API\n@PreAuthorize\nService 필터"] end PY_G --> AG --> MCP -->|JWT| SPRING SPRING -->|필터링된 데이터| MCP style NoAuth fill:#0d0f18,stroke:#e09830 style Auth fill:#0d0f18,stroke:#30c8c0 

05요청 처리 흐름 (End-to-End)

사용자 질의부터 응답까지 — 권한 포함 처리

flowchart TD START(["사용자 질문\n우리 부서 최근 주문 현황 알려줘"]) --> AUTH{JWT 검증} AUTH -->|실패| DENY1["401 재로그인"] AUTH -->|성공| PLAN[에이전트 플래닝\nLLM이 도구 선택] PLAN --> BRANCH{어떤 도구?} BRANCH -->|MCP 기본| T1[get_orders 도구] BRANCH -->|NL2SQL| T2[run_sql 도구] BRANCH -->|RAG| T3[search_docs 도구] T1 -->|JWT| S1[Spring /api/orders] T2 -->|JWT + SQL| S2[Spring /api/nl2sql/execute] T3 -->|JWT + query| S3[Spring /api/rag/search] S1 --> AZ{Spring 권한 체크\n@PreAuthorize} S2 --> AZ S3 --> AZ AZ -->|거부| DENY2["403 → 일반화 메시지"] AZ -->|허용| FILTER[Service 레이어\n사용자별 필터링] FILTER --> DATA[Oracle / ES / Vector] DATA -->|필터링된 데이터| RESULT[도구 결과] RESULT --> AGENT[에이전트 종합] AGENT --> GUARD{Guardrail 검증} GUARD -->|통과| RESPONSE[자연어 응답] GUARD -->|실패| DENY3["기본값 응답"] RESPONSE --> END([사용자에게 답변]) DENY2 --> AGENT DENY3 --> END style AUTH fill:#201010,stroke:#f05050,color:#f08080 style AZ fill:#201010,stroke:#f05050,color:#f08080 style GUARD fill:#201010,stroke:#f05050,color:#f08080 style FILTER fill:#102820,stroke:#30c880,color:#50e898 style AGENT fill:#1a2540,stroke:#5a7af0,color:#7a9aff 

06MCP Tools — 기존 API 래퍼

MCP 도구 권한 처리 흐름

sequenceDiagram participant AG as LangGraph Agent participant MCP as MCP Tool participant API as Spring API participant SS as Spring Security participant SVC as Service Layer AG->>MCP: search_customer(name, ctx.user_token) MCP->>API: GET /api/customers?name=...\nAuthorization: Bearer {JWT} API->>SS: JWT 검증 SS->>SS: @PreAuthorize 권한 체크 alt 권한 있음 SS->>SVC: customerService.search(name, user) SVC->>SVC: 부서/역할 필터 적용 SVC-->>API: 필터링된 고객 목록 API-->>MCP: 200 OK + 데이터 MCP-->>AG: {customers: [...]} else 권한 없음 SS-->>API: 403 Forbidden API-->>MCP: 403 MCP-->>AG: {accessible: false,\n message: "접근 권한 없음"} end 

PYTHONMCP Tool 구현 패턴
    
    
    from fastmcp import FastMCP, Context
    import httpx
    
    mcp = FastMCP("enterprise-tools")
    SPRING_API = "https://internal.company.com/api"
    
    @mcp.tool
    async def search_customer(name: str, ctx: Context) -> dict:
        """고객 정보 검색 (사용자 권한 기반)"""
        user_token = ctx.state.get("user_token")
        if not user_token:
            return {"error": "인증 토큰 없음"}
    
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{SPRING_API}/customers/search",
                    params={"name": name},
                    headers={"Authorization": f"Bearer {user_token}"},
                )
    
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            elif resp.status_code == 403:
                return {"accessible": False,
                        "message": "요청하신 정보를 제공할 수 없습니다"}
            elif resp.status_code == 401:
                return {"error": "인증 만료. 재로그인 필요"}
            else:
                return {"error": f"조회 실패 (code: {resp.status_code})"}
        except Exception as e:
            # 에러 메시지에 내부 정보 노출 금지
            return {"error": "일시적 오류"}

⚠️

**반드시 지킬 것**

  * MCP 도구는 **절대 DB에 직접 접근하지 않는다**
  * 모든 외부 호출은 기존 Spring API 경유
  * 에러 메시지에 URL, 테이블명, 컬럼명 노출 금지
  * 사용자 JWT 이외의 credential 사용 금지



07NL2SQL — 가장 까다로운 권한 처리

⚠️

**NL2SQL은 가장 위험한 도구** LLM이 자유롭게 SQL을 생성하므로 권한 필터가 누락될 수 있습니다. 따라서 **Python이 SQL 실행을 직접 하지 않고** , Spring 전용 엔드포인트에 위임해야 합니다. 

NL2SQL 권한 안전 처리 흐름

sequenceDiagram participant AG as LangGraph Agent participant PY as Python NL2SQL Tool participant LLM as 사내 LLM API participant SP as Spring /api/nl2sql/execute participant VAL as Spring SqlValidator participant RW as Spring SqlRewriter participant AUD as Spring AuditLog participant DB as Oracle AG->>PY: run_sql(question, ctx.user_token) PY->>LLM: NL → SQL 변환 요청\n(프롬프트에 스키마 + 예제) LLM-->>PY: 생성된 SQL PY->>SP: POST /api/nl2sql/execute\n{question, sql}\nAuthorization: Bearer {JWT} SP->>VAL: SQL 문법·허용 테이블 검증 alt 검증 실패 VAL-->>SP: InvalidSql SP-->>PY: 400 + "쿼리 제한 초과" else 검증 통과 VAL-->>SP: OK SP->>RW: 사용자 권한 기반 WHERE 주입 RW-->>SP: 재작성된 SQL SP->>AUD: 감사 로그 기록 (원본+재작성+사용자) SP->>DB: 전용 NL2SQL role로 실행 DB-->>SP: 결과 (사용자 범위 내) SP-->>PY: 데이터 end PY-->>AG: 결과 (LLM이 해석) 

### Spring 쪽 NL2SQL 엔드포인트

JAVANL2SQLController.java
    
    
    @RestController
    @RequestMapping("/api/nl2sql")
    public class NL2SQLController {
    
        @Autowired private SqlValidatorService validator;
        @Autowired private SqlRewriterService rewriter;
        @Autowired private NL2SQLAuditService auditService;
        @Autowired private JdbcTemplate nl2sqlJdbc;  // 전용 role 계정
    
        @PostMapping("/execute")
        @PreAuthorize("hasAnyRole('ANALYST', 'MANAGER')")
        public ResponseEntity<?> execute(
            @RequestBody NL2SQLRequest req,
            @AuthenticationPrincipal UserDetails user
        ) {
            // 1. SQL 검증 (sqlglot 파서 또는 직접 파서)
            ValidationResult vr = validator.validate(req.getSql());
            if (!vr.isValid()) {
                auditService.logBlocked(user, req, vr.getReason());
                return ResponseEntity.status(400)
                    .body(Map.of("error", "쿼리 제한을 초과했습니다"));
            }
    
            // 2. 사용자 권한 기반 WHERE 주입
            String rewrittenSql = rewriter.addUserFilter(req.getSql(), user);
    
            // 3. 감사 로그
            String auditId = auditService.logStart(user, req, rewrittenSql);
    
            try {
                // 4. 전용 DB 계정으로 실행 (민감 테이블 GRANT 없음)
                List<Map<String,Object>> rows = nl2sqlJdbc.queryForList(rewrittenSql);
    
                // 5. 결과 마스킹 (필요 시)
                rows = rewriter.maskSensitiveColumns(rows, user);
    
                auditService.logSuccess(auditId, rows.size());
                return ResponseEntity.ok(Map.of("rows", rows, "count", rows.size()));
            } catch (DataAccessException e) {
                auditService.logError(auditId, e.getMessage());
                return ResponseEntity.status(500)
                    .body(Map.of("error", "쿼리 실행 실패"));
            }
        }
    }

### Spring 쪽 권한 기반 WHERE 주입

JAVASqlRewriterService.java
    
    
    @Service
    public class SqlRewriterService {
    
        /**
         * 사용자 권한에 따라 SQL에 WHERE 조건 자동 주입
         * - 부서 기반: WHERE dept_id IN (사용자 접근 가능 부서)
         * - 소유 기반: WHERE owner_id = 사용자 ID
         */
        public String addUserFilter(String sql, UserDetails user) {
            // 1. sqlglot (또는 JSQLParser) AST 파싱
            Statement stmt = parseSelect(sql);
    
            // 2. 참조 테이블에 따라 필터 결정
            List<String> tables = extractTables(stmt);
            Map<String, String> filters = new HashMap<>();
            for (String table : tables) {
                if (tableHasDeptColumn(table)) {
                    List<Integer> allowedDepts = getAllowedDepts(user);
                    filters.put(table, "dept_id IN (" + join(allowedDepts) + ")");
                }
                if (tableHasOwnerColumn(table)) {
                    filters.put(table, "owner_id = " + user.getId());
                }
            }
    
            // 3. AST에 WHERE 조건 AND 연결로 추가
            return injectWhere(stmt, filters).toString();
        }
    
        /**
         * 민감 컬럼 마스킹 (역할별)
         */
        public List<Map<String,Object>> maskSensitiveColumns(
                List<Map<String,Object>> rows, UserDetails user) {
            if (user.hasRole("ADMIN")) return rows;  // 관리자는 원본
    
            return rows.stream().map(row -> {
                Map<String,Object> masked = new HashMap<>(row);
                if (masked.containsKey("ssn")) masked.put("ssn", "******-*******");
                if (masked.containsKey("phone")) masked.put("phone", maskPhone(...));
                return masked;
            }).toList();
        }
    }

### Python 쪽 NL2SQL 도구

PYTHONnl2sql_tool.py
    
    
    @mcp.tool
    async def run_sql(question: str, ctx: Context) -> dict:
        """자연어 질문을 SQL로 변환 후 실행"""
        user_token = ctx.state.get("user_token")
    
        # 1. LLM이 SQL 생성
        schema_context = await get_schema_for_user(user_token)
        sql = await llm.generate_sql(question, schema_context)
    
        # 2. Spring NL2SQL 엔드포인트에 위임 (검증+권한+실행+감사 전부 Spring 책임)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{SPRING_API}/api/nl2sql/execute",
                json={"question": question, "sql": sql},
                headers={"Authorization": f"Bearer {user_token}"},
            )
    
        if resp.status_code == 200:
            data = resp.json()
            return {"success": True, "rows": data["rows"][:100],  # 과다 반환 방지
                    "total_count": data["count"]}
        elif resp.status_code == 400:
            return {"error": "쿼리를 처리할 수 없습니다. 질문을 다시 해주세요"}
        elif resp.status_code == 403:
            return {"error": "접근 권한이 없습니다"}
        else:
            return {"error": "일시적 오류"}

🔐

**왜 Python이 직접 실행하면 안 되나** Python이 Oracle에 직접 연결하면 ① LLM이 생성한 SQL이 권한 필터 없이 실행될 위험, ② Spring Security와 별도의 권한 경로가 생겨 감사 추적 분산, ③ 사내 보안 감사 시 이중 관리 부담. Spring에 위임하면 기존 감사 인프라를 그대로 활용할 수 있습니다. 

08RAG — 권한 메타데이터 기반 필터링

RAG 인덱싱 시 권한 메타데이터 부착

flowchart LR DOC[원본 문서\n사내 시스템] -->|수집| CHUNK[청킹 + 임베딩] CHUNK --> META[권한 메타데이터 부착\nacl.roles, acl.depts, sensitivity] META --> VEC[(Vector DB\nQdrant/ES)] DOC -.->|권한 변경 이벤트| SYNC[ACL 동기화 DAG] SYNC --> VEC style META fill:#201010,stroke:#f05050,color:#f08080 style VEC fill:#102820,stroke:#30c880,color:#50e898 

RAG 검색 시 권한 필터링 (이중 검증)

sequenceDiagram participant AG as LangGraph Agent participant RT as RAG Tool participant PERM as Spring /api/me/permissions participant VEC as Vector DB participant VER as Spring /api/rag/verify AG->>RT: search_documents(query, user_token) RT->>PERM: GET /api/me/permissions\nAuthorization: Bearer {JWT} PERM-->>RT: {roles: [...], depts: [...], max_level: "internal"} RT->>VEC: Vector Search\nfilter: acl.roles IN user.roles\n sensitivity <= max_level VEC-->>RT: Top-K 청크 (권한 필터 적용) loop 각 청크 RT->>VER: POST /api/rag/verify\n{doc_id}\nAuthorization: Bearer {JWT} VER-->>RT: {accessible: true/false} end RT-->>AG: 권한 검증 통과한 청크만 반환 

PYTHONRAG Tool 구현
    
    
    @mcp.tool
    async def search_documents(query: str, ctx: Context) -> list:
        """문서 검색 — 권한 기반"""
        user_token = ctx.state.get("user_token")
    
        # 1. Spring에서 사용자 권한 조회
        perms = await fetch_user_permissions(user_token)
        if not perms:
            return []
    
        # 2. Vector DB 검색 with 권한 필터
        query_emb = await embed(query)
        results = qdrant.search(
            collection_name="docs",
            query_vector=query_emb,
            query_filter={
                "must": [
                    {"key": "acl.roles", "match": {"any": perms["roles"]}},
                    {"key": "acl.depts", "match": {"any": perms["depts"]}},
                    {"key": "acl.sensitivity_level",
                     "range": {"lte": perms["max_level"]}}
                ]
            },
            limit=20
        )
    
        # 3. 이중 검증 (Spring 실시간 확인)
        verified = []
        for r in results:
            if await verify_access(r.payload["doc_id"], user_token):
                verified.append({
                    "content": r.payload["content"],
                    "source": r.payload["source"],
                    "score": r.score
                })
        return verified[:5]

필터 레벨 1

벡터 검색 단계

권한 메타데이터(`acl`)를 Qdrant/ES 쿼리 필터에 주입. 권한 없는 청크는 **Top-K 결과에 애초에 포함되지 않음**.

필터 레벨 2

이중 검증

검색된 각 청크에 대해 Spring에 `GET /api/rag/verify` 호출. 권한 변경이 Vector DB에 미반영된 경우 대비.

동기화

ACL 동기화 DAG

원본 문서 권한 변경 시 Vector DB의 `acl` 메타데이터 업데이트. Airflow 주기적 sync.

Fallback

Spring 프록시 패턴

복잡한 경우 Spring이 RAG 검색 자체를 대행. Python은 `/api/rag/search` 호출만.

09Spring 쪽 구현

## 채팅 UI + 프록시 컨트롤러

JAVAChatController.java
    
    
    @RestController
    @RequestMapping("/api/chat")
    public class ChatController {
    
        @Value("${llm.sidecar.url}")
        private String llmSidecarUrl;
    
        @Autowired
        private RestTemplate restTemplate;
    
        @GetMapping("/page")
        @PreAuthorize("isAuthenticated()")
        public String chatPage() {
            return "chat";  // Thymeleaf chat.html
        }
    
        @PostMapping("/ask")
        @PreAuthorize("isAuthenticated()")
        public ResponseEntity<?> ask(
            @RequestBody ChatRequest req,
            HttpServletRequest request,
            @AuthenticationPrincipal UserDetails user
        ) {
            // 현재 사용자의 JWT 추출
            String jwt = extractJwt(request);
    
            // Python LLM 서비스 호출
            HttpHeaders headers = new HttpHeaders();
            headers.setBearerAuth(jwt);
            headers.setContentType(MediaType.APPLICATION_JSON);
    
            try {
                ResponseEntity<Map> response = restTemplate.exchange(
                    llmSidecarUrl + "/api/ask",
                    HttpMethod.POST,
                    new HttpEntity<>(req, headers),
                    Map.class
                );
                return ResponseEntity.ok(response.getBody());
            } catch (HttpClientErrorException e) {
                // Python 쪽 에러를 그대로 전파
                return ResponseEntity.status(e.getStatusCode())
                    .body(e.getResponseBodyAsString());
            }
        }
    
        private String extractJwt(HttpServletRequest request) {
            String auth = request.getHeader("Authorization");
            if (auth != null && auth.startsWith("Bearer ")) {
                return auth.substring(7);
            }
            // 쿠키에서 꺼내기 (세션 기반 시)
            return (String) request.getAttribute("jwt");
        }
    }

### 채팅 페이지 (Thymeleaf 또는 기존 프론트)

HTMLtemplates/chat.html
    
    
    <!DOCTYPE html>
    <html xmlns:th="http://www.thymeleaf.org">
    <head>
      <title>사내 AI 챗봇</title>
      <meta name="_csrf" th:content="${_csrf.token}"/>
    </head>
    <body>
      <div id="chat">
        <div id="messages">
```
        <textarea id="input" rows="3"></textarea>
        <button onclick="send()">전송</button>
```
    
      <script>
        async function send() {
          const q = document.getElementById('input').value;
          const csrf = document.querySelector('meta[name="_csrf"]').content;
    
          const resp = await fetch('/api/chat/ask', {
            method: 'POST',
            credentials: 'include',  // 기존 세션 쿠키 포함
            headers: {
              'Content-Type': 'application/json',
              'X-CSRF-TOKEN': csrf
            },
            body: JSON.stringify({question: q})
          });
    
          const data = await resp.json();
          appendMessage('assistant', data.answer);
        }
      </script>
    </body>
    </html>

10Python 쪽 구현

PYTHONapp/main.py
    
    
    from fastapi import FastAPI, Depends, HTTPException
    from app.auth import verify_jwt
    from app.agents.graph import create_agent
    
    app = FastAPI(title="Enterprise LLM Sidecar")
    
    @app.post("/api/ask")
    async def ask(req: AskRequest, user = Depends(verify_jwt)):
        """에이전트에게 질문 전달"""
        agent = await create_agent()
    
        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": req.question}],
            "user_id": user["sub"],
            "user_token": user["raw_token"],  # 그대로 전파
        }, config={"configurable": {"thread_id": f"{user['sub']}-{req.session_id}"}})
    
        return {
            "answer": extract_answer(result),
            "sources": result.get("sources", []),
        }

PYTHONapp/auth.py — JWT 검증
    
    
    import jwt
    from fastapi import Depends, HTTPException, Header
    from app.config import settings
    
    async def verify_jwt(authorization: str = Header(...)) -> dict:
        """Spring과 동일 공개키로 JWT 검증"""
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing Bearer token")
    
        token = authorization[7:]
        try:
            payload = jwt.decode(
                token,
                settings.JWT_PUBLIC_KEY,  # Spring과 공유
                algorithms=["RS256"],
                audience=settings.JWT_AUDIENCE,
            )
            payload["raw_token"] = token  # 하위로 전파용
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid token")

PYTHONapp/agents/graph.py — LangGraph Agent
    
    
    from langgraph.prebuilt import create_react_agent
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.tools.mcp_client import get_mcp_tools
    from app.config import settings
    
    async def create_agent():
        # 사내 LLM API (OpenAI 호환 가정)
        llm = ChatOpenAI(
            model=settings.INTERNAL_LLM_MODEL,
            base_url=settings.INTERNAL_LLM_BASE_URL,
            api_key=settings.INTERNAL_LLM_API_KEY,  # 서비스 계정
        )
    
        tools = await get_mcp_tools()  # MCP 도구 로드
    
        checkpointer = AsyncPostgresSaver.from_conn_string(
            settings.DATABASE_URL
        )
    
        return create_react_agent(
            llm, tools,
            checkpointer=checkpointer,
            prompt=SYSTEM_PROMPT,
        )

11프로젝트 구조

저장소 구조

graph LR subgraph Existing["기존 Spring (확장)"] SC["controllers/"] SS["services/"] ST["templates/"] end subgraph New["신규 Python 사이드카"] PA["app/"] PM["mcp-server/"] end SC --> ChatCtrl[ChatController] SC --> NLCtrl[NL2SQLController] SC --> RagCtrl[RagController] SS --> SqlVal[SqlValidator] SS --> SqlRew[SqlRewriter] SS --> Audit[AuditService] ST --> ChatPage[chat.html] PA --> Main[main.py] PA --> Auth[auth.py] PA --> Graph[agents/graph.py] PA --> Tools[tools/] PM --> McpSrv[server.py] PM --> McpTools[tools.py] style Existing fill:#0d0f18,stroke:#5a7af0 style New fill:#0d0f18,stroke:#30c880 

구조디렉토리 트리
    
    
    company-chatbot/
    ├── spring-app/                    # 기존 Spring Boot (확장)
    │   ├── src/main/java/com/company/
    │   │   ├── controllers/
    │   │   │   ├── ChatController.java        # /chat UI + 프록시
    │   │   │   ├── NL2SQLController.java      # NL2SQL 실행 전용
    │   │   │   └── RagController.java         # RAG 권한 검증
    │   │   ├── services/
    │   │   │   ├── SqlValidatorService.java
    │   │   │   ├── SqlRewriterService.java    # WHERE 주입, 마스킹
    │   │   │   └── NL2SQLAuditService.java
    │   │   └── security/
    │   │       └── JwtConfig.java             # 기존 + Bearer 지원
    │   └── src/main/resources/templates/
    │       └── chat.html                       # 채팅 UI
    │
    └── llm-sidecar/                    # 신규 Python 서비스
        ├── app/
        │   ├── main.py                         # FastAPI
        │   ├── auth.py                         # JWT 검증
        │   ├── config.py                       # 환경변수
        │   ├── agents/
        │   │   ├── graph.py                    # LangGraph 에이전트
        │   │   ├── state.py                    # State with user_token
        │   │   └── prompts.py
        │   ├── tools/
        │   │   ├── mcp_client.py               # MCP 서버 연결
        │   │   ├── nl2sql_tool.py              # NL2SQL
        │   │   └── rag_tool.py                 # RAG
        │   └── middleware/
        │       ├── audit.py
        │       └── rate_limit.py
        ├── mcp-server/
        │   ├── server.py                       # FastMCP
        │   ├── tools.py                        # Spring API 래퍼
        │   └── Dockerfile
        ├── Dockerfile
        ├── docker-compose.yml
        └── requirements.txt

12감사 & 모니터링

감사 로그 흐름

graph TD REQ[사용자 질의] --> GW[Python Gateway] GW -->|요청 로그| PY_AUDIT[(llm_request_log\nPython)] GW --> AG[Agent 실행] AG --> TOOL[MCP Tool 호출] TOOL -->|JWT로 API 호출| SPRING[Spring API] SPRING -->|기존 감사| SPRING_AUDIT[(기존 access_log\nSpring)] SPRING -->|NL2SQL 시| NL_AUDIT[(nl2sql_audit_log\nSpring)] AG -->|최종 응답 로그| PY_AUDIT style PY_AUDIT fill:#201810,stroke:#e09830,color:#f8b840 style SPRING_AUDIT fill:#102040,stroke:#5a7af0,color:#7a9aff style NL_AUDIT fill:#102040,stroke:#5a7af0,color:#7a9aff 

### 감사 로그 테이블 스키마

SQLllm_request_log (Python 쪽)
    
    
    CREATE TABLE llm_request_log (
        request_id      UUID PRIMARY KEY,
        user_id         VARCHAR(100) NOT NULL,
        session_id      VARCHAR(100),
        received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
        question        TEXT,
        tools_called    JSONB,                -- [{name, args, status}]
        api_calls       JSONB,                -- Spring API 호출 내역
        permission_denied_count INT DEFAULT 0,
    
        response        TEXT,
        llm_model       VARCHAR(50),
        input_tokens    INT,
        output_tokens   INT,
        total_ms        INT,
    
        status          VARCHAR(20),          -- success, partial, denied, error
        error_message   TEXT
    );
    
    CREATE INDEX idx_llm_request_user ON llm_request_log(user_id, received_at DESC);
    CREATE INDEX idx_llm_request_status ON llm_request_log(status)
        WHERE status != 'success';

감사 항목| 책임| 저장 위치  
---|---|---  
사용자 질의 & 응답| Python| llm_request_log  
도구 호출 내역| Python| llm_request_log.tools_called  
Spring API 호출| Spring| 기존 access_log (재사용)  
NL2SQL 생성 & 실행| Spring| nl2sql_audit_log  
권한 거부 이벤트| 양쪽| 각자 + 알림  
LLM API 사용량| 사내 LLM 게이트웨이| LLM 플랫폼  
  
### 모니터링 지표

보안 지표

이상 탐지

  * 사용자당 권한 거부 횟수 (비정상 탐색)
  * 동일 사용자 동시 세션 수
  * 응답에서 금지 패턴 검출
  * NL2SQL 검증 실패율



품질 지표

응답 품질

  * 평균 응답 시간
  * 도구별 호출 빈도·성공률
  * LLM 토큰 사용량
  * 사용자 피드백 (👍/👎)



13정보 누출 방지

시나리오| 나쁜 예| 좋은 예  
---|---|---  
**에러 메시지** | "users 테이블에 SELECT 권한 없음" | "요청하신 정보를 제공할 수 없습니다"  
**권한 거부 차등** | "영업1팀 데이터만 볼 수 있습니다" | "접근 가능한 범위를 벗어났습니다"  
**민감 필드 프롬프트** | "홍길동 고객 주민번호 860101-..." | "고객 A의 정보 (주민번호 마스킹)"  
**내부 경로 노출** | "https://internal-api/db/secret..." | URL 표시 없음  
**LLM 추정** | "정확한 매출은 모르지만 아마도 10억..." | "해당 정보는 확인할 수 없습니다"  
  
### 캐시 정책

⚠️

**절대 교차 사용자 캐시 금지** 같은 질문이라도 사용자별로 권한 범위가 다르므로 응답이 다를 수 있습니다. 캐시 키는 반드시 `(user_id, question)`로 구성하거나, 아예 캐시하지 않는 것이 안전합니다. 

### LLM Guardrail

PYTHON출력 후처리 예시
    
    
    FORBIDDEN_PATTERNS = [
        r"\d{6}[-]\d{7}",          # 주민번호
        r"\d{3}[-]\d{3,4}[-]\d{4}", # 전화번호
        r"\d{10,16}",              # 카드번호/계좌번호 유사
        r"password|secret|api_key",
    ]
    
    def output_guardrail(text: str) -> str:
        """최종 응답에서 금지 패턴 마스킹"""
        for pattern in FORBIDDEN_PATTERNS:
            text = re.sub(pattern, "[마스킹]", text, flags=re.IGNORECASE)
        return text

14실패 모드 & 대응

실패 시나리오| 발생 지점| 대응  
---|---|---  
JWT 만료 | Python Gateway | 401 반환 → UI에서 재로그인 유도  
Spring API 403 | MCP Tool | 일반화 메시지 반환, LLM이 "권한 없음" 답변  
Spring API 장애 | MCP Tool | Circuit Breaker + "일시적 장애" 응답  
LLM API 타임아웃 | Python Gateway | Retry 1회, 실패 시 "나중에 다시" 메시지  
LLM Hallucination | Agent | Guardrail 후처리 + 도구 결과 우선 정책  
NL2SQL Injection 시도 | Spring Validator | 차단 + 감사 기록 + 관리자 알림  
무한 루프 | LangGraph | Conditional Edge에 max_iterations 가드  
토큰 탈취 | 전 레이어 | 짧은 JWT 만료 + refresh + 비정상 활동 탐지  
Vector DB 장애 | RAG Tool | RAG 도구만 비활성화, 다른 도구는 정상 작동  
  
권한 거부 이벤트 처리 흐름

graph TD CALL[MCP Tool이 Spring API 호출] --> RESP{응답 상태} RESP -->|200 OK| OK[정상 결과] RESP -->|403 Forbidden| DENIED[권한 거부] DENIED --> AUDIT[감사 로그 기록] AUDIT --> GENERIC[일반화 메시지 생성\n요청하신 정보를 제공할 수 없습니다] GENERIC --> AG[Agent에 전달] AG --> LLM_EXPLAIN[LLM이 자연스럽게 설명] LLM_EXPLAIN --> USER[사용자에게 답변] AUDIT -->|비정상 패턴| ALERT[보안 알림] style DENIED fill:#201010,stroke:#f05050,color:#f08080 style GENERIC fill:#201810,stroke:#e09830,color:#f8b840 style ALERT fill:#201010,stroke:#f05050,color:#f08080 

15단계별 로드맵

구현 로드맵 (10주)

gantt title Enterprise Chatbot 구현 로드맵 dateFormat YYYY-MM-DD axisFormat %m/%d section Phase 0 사전 LLM API 스펙 조사 :p0a, 2026-04-20, 3d 기존 권한 정책 파악 :p0b, after p0a, 3d 보안팀 사전 협의 :p0c, after p0b, 3d section Phase 1 기본 Spring 프록시 컨트롤러 :p1a, after p0c, 5d Python Gateway + JWT :p1b, after p1a, 5d MCP 도구 5개 래핑 :p1c, after p1b, 7d 채팅 UI 추가 :p1d, after p1c, 3d 테스트 권한 A vs B :p1e, after p1d, 3d section Phase 2 NL2SQL Spring SqlValidator :p2a, after p1e, 5d Spring SqlRewriter :p2b, after p2a, 5d Python NL2SQL Tool :p2c, after p2b, 3d 감사 로그 통합 :p2d, after p2c, 3d section Phase 3 RAG Vector DB 구축 :p3a, after p2d, 5d 권한 메타데이터 인덱싱 :p3b, after p3a, 5d Python RAG Tool + 검증 :p3c, after p3b, 5d section Phase 4 운영 모니터링 대시보드 :p4a, after p3c, 5d 침투 테스트 :p4b, after p4a, 7d 파일럿 사용자 확대 :p4c, after p4b, 7d 

PHASE 0

사전 준비 (2주)

  * 사내 LLM API 스펙 확인 (OpenAI 호환? 커스텀?)
  * 기존 Spring 권한 메커니즘 분석
  * Oracle VPD 도입 여부 검토
  * 보안팀 사전 협의 + 데이터 분류



PHASE 1

기본 챗봇 (3주)

  * Spring 채팅 페이지 + 프록시
  * Python FastAPI Gateway + JWT 검증
  * MCP Server + 주요 API 5~10개 래핑
  * 기본 LangGraph ReAct 에이전트
  * 권한 A/B 사용자 통합 테스트



PHASE 2

NL2SQL (2주)

  * Spring NL2SQLController 추가
  * SqlValidator (sqlglot/JSQLParser)
  * SqlRewriter (WHERE 주입, 마스킹)
  * 전용 DB role 생성
  * 감사 로그 통합



PHASE 3

RAG (2주)

  * Vector DB (Qdrant or ES) 구축
  * 문서 권한 메타데이터 설계
  * ACL 동기화 DAG
  * Python RAG Tool + 이중 검증



PHASE 4

운영 (3주+)

  * 모니터링 대시보드 (Grafana)
  * 보안팀 침투 테스트
  * 파일럿 → 부서별 확대
  * 레트로 & 개선



16런칭 전 체크리스트

필수보안 검증

  * [ ] 권한이 다른 테스트 사용자 2명 이상으로 동일 질문 → 다른 결과 확인
  * [ ] 권한 없는 리소스 명시적 요청 시 일반화 메시지만 반환
  * [ ] 모든 데이터 접근이 Spring REST API 경유 확인 (Python → DB 직접 접근 금지)
  * [ ] LLM 프롬프트/응답에 민감 데이터(PII, 재무) 없는지 검사
  * [ ] NL2SQL이 전용 API만 사용하는지 확인
  * [ ] RAG 검색에 ACL 필터가 항상 적용되는지 확인
  * [ ] Guardrail이 금지 패턴을 차단하는지 테스트
  * [ ] 보안팀 침투 테스트 통과
  * [ ] JWT 만료 시 재로그인 플로우 동작
  * [ ] 토큰 탈취 시 짧은 만료 + refresh 동작 확인



운영감사 & 모니터링

  * [ ] 모든 LLM 요청이 llm_request_log에 기록
  * [ ] Spring 기존 감사 로그가 Python 사이드카 요청도 포함
  * [ ] NL2SQL 감사 로그 스키마 완비
  * [ ] 권한 거부 알림 설정 (Slack/이메일)
  * [ ] 사용량 쿼터 & rate limit 설정
  * [ ] 비용 모니터링 (LLM API 사용량)



품질기능 검증

  * [ ] 기본 QA (API 기반 질의)
  * [ ] NL2SQL 정확도 (벤치마크 쿼리 통과)
  * [ ] RAG 검색 품질 (관련성)
  * [ ] 멀티 스텝 에이전트 동작
  * [ ] 스트리밍 응답 (UX)
  * [ ] 오류 발생 시 우아한 fallback



## 관련 문서

[LangGraph 기술 가이드](<langgraph_technical_guide.html>) — 핵심 개념, 아키텍처 패턴

[LangGraph 사내 환경 구축 가이드](<langgraph_enterprise_guide.html>) — Python 환경, FastAPI, Docker

[FastMCP 가이드](<fastmcp_guide.html>) — MCP 서버 구축, 전송 모드, 연동

[BIP 에이전트 전략](<bip_agent_strategy.html>) — 차세대 Planner Agent 아키텍처

[Hermes Agent 조사](<hermes_agent_research.html>) — 자기 개선형 에이전트

[에이전트 하네스 설계 (GAN)](<agent_harness_gan_design.html>) — 생성/평가 분리

[NL2SQL 데이터 레이어 레퍼런스](<nl2sql_data_layer_reference.html>) — 개념, 도구, 보안

enterprise-chatbot-permission.guide · Hybrid Java + Python · 2026.04.16

Zero Trust · Permission Propagation · Audit Everything
