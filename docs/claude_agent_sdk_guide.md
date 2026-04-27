# Claude Agent SDK  
멀티 세션 오케스트레이션

여러 Claude Code 세션을 역할별로 나눠 동시에 운영할 때, 오케스트레이터 패턴으로 세션 간 충돌을 방지하고 진행 상황을 한눈에 조율합니다.

Claude Agent SDK AWS Bedrock 지원 Python / TypeScript 서브에이전트 사내 환경 친화적

01

## 멀티 에이전트 오케스트레이션이란?

하나의 프로젝트를 여러 Claude Code 세션에 역할을 나눠 동시에 진행할 때 생기는 문제들이 있습니다.

⚠️ 파일 충돌

같은 파일을 서로 다른 세션이 동시에 수정해 충돌 발생

🔗 의존성 누락

A 세션이 끝나야 B 세션이 시작해야 하는 순서를 놓침

👁️ 가시성 부족

전체 진행 상황을 한눈에 파악할 수 없음

🚧 블로킹 미감지

어떤 세션이 블로킹 이슈를 갖고 있는지 파악 불가

오케스트레이터 패턴은 전담 '조율 세션'이 다른 모든 세션의 상태를 파악하고, 우선순위를 결정하며, 충돌을 사전에 감지합니다.

🎯 오케스트레이터 세션

진행상황 수집 · 영향도 분석 · 다음 지시 결정

↓   ↓   ↓

세션 A

백엔드 / API

세션 B

프론트엔드 / UI

세션 C

DB / 스키마

02

## Claude Agent SDK 개요

Claude Agent SDK는 Claude Code CLI 내부 엔진을 Python / TypeScript 코드로 프로그래밍할 수 있게 Anthropic이 공식 제공하는 라이브러리입니다. 원래 'Claude Code SDK'였으나 2025년 9월 이름이 변경되었습니다.

ℹ️

**핵심 차이점** 일반 Anthropic API는 Claude에게 프롬프트를 보내고 툴 실행을 개발자가 직접 구현해야 합니다. Agent SDK는 Claude가 파일 읽기 · 명령어 실행 · 웹 검색 · 코드 수정까지 자율적으로 처리합니다. 

### 핵심 기능

🤖 자율 실행

파일 읽기, 명령어 실행, 웹 검색, 코드 수정을 Claude가 스스로 판단해서 처리

🔀 서브에이전트

오케스트레이터 Claude가 다른 Claude 세션을 프로그래밍적으로 생성하고 결과 수집

☁️ 멀티 클라우드

Bedrock / Vertex AI / Azure 환경변수 하나로 전환 가능

🔌 MCP 지원

Model Context Protocol로 Slack, GitHub, DB 등 외부 서비스 연동

03

## OpenClaw vs Claude Agent SDK

OpenClaw은 강력한 멀티에이전트 프레임워크이지만, 사내 환경 특성과 팀 규모를 고려하면 Claude Agent SDK가 더 현실적입니다.

항목 | OpenClaw | Claude Agent SDK  
---|---|---  
설치 / 승인| 서드파티 오픈소스 — 사내 승인 필요| Anthropic 공식 — 별도 승인 불필요  
외부망 의존| Discord / Slack / Telegram 연동 전제| 없음  
Bedrock 지원| 추가 설정 필요| 환경변수 하나로 전환  
학습 곡선| 높음 (Lobster, 스킬 마켓플레이스 등)| 낮음 (Python 기본 지식으로 충분)  
멀티에이전트| 네이티브 강력 지원| 서브에이전트 지원  
스킬 에코시스템| 5,400+ 스킬| CLAUDE.md 커스텀  
권장 상황| 대규모 팀, 외부 채널 연동 필요 시| 소규모 팀, 사내 환경, 빠른 시작  
  
💡

**결론** 개인 MacBook ↔ 사내 Bedrock 환경을 오가는 현재 상황에서는 Claude Agent SDK가 압도적으로 유리합니다. 팀이 커지고 외부 채널 연동이 필요해지면 그때 OpenClaw를 검토하세요. 

04

## 전체 아키텍처 설계

즉시 적용 가능한 파일 공유 방식과 자동화를 위한 SDK 스크립트 방식, 두 레이어로 구성합니다.

### 프로젝트 디렉토리 구조

DIRECTORY
    
    
    프로젝트 루트/
    ├── CLAUDE.md                    ← 전체 역할 분배 정의
    ├── .claude/
    │   ├── session-orchestrator.md  ← 오케스트레이터 역할 정의
    │   ├── session-backend.md       ← 백엔드 세션 역할 정의
    │   ├── session-frontend.md      ← 프론트엔드 세션 역할 정의
    │   └── session-db.md            ← DB 세션 역할 정의
    ├── .orchestrator/
    │   ├── status-backend.md        ← 백엔드 세션이 자동 업데이트
    │   ├── status-frontend.md       ← 프론트엔드 세션이 자동 업데이트
    │   └── status-db.md             ← DB 세션이 자동 업데이트
    └── orchestrator.py              ← SDK 기반 자동화 스크립트

### 데이터 흐름

각 세션 작업 → status 파일 업데이트 → 오케스트레이터 읽기 → 충돌 / 의존성 분석 → 다음 지시 결정

05

## 방법 1 — CLI + 공유 파일 방식

SDK 설치 없이 지금 당장 적용할 수 있습니다. 각 세션이 작업 상태를 마크다운 파일로 남기고, 오케스트레이터 세션이 그 파일을 읽어 전체 상황을 파악합니다.

1

각 세션 CLAUDE.md에 상태 업데이트 규칙 추가
    
    
    ## 작업 완료 시 필수 규칙
    작업 단위가 끝날 때마다 .orchestrator/status-backend.md를 업데이트할 것.
    
    ### 업데이트 형식
    ## 최종 업데이트: {날짜 시간}
    
    ### 완료된 작업
    - [x] 작업 내용
    
    ### 현재 진행 중
    - 작업 내용 (예상 완료: ~시간)
    
    ### 블로킹 이슈
    - 다른 세션 결과를 기다려야 하는 항목
    
    ### 다음 예정 작업
    - 작업 내용

2

오케스트레이터 세션에서 아래 프롬프트 사용
    
    
    .orchestrator/ 폴더의 모든 status 파일을 읽고:
    
    1. 전체 진행상황 요약 (세션별 완료율)
    2. 충돌 가능성 감지 (같은 파일을 여러 세션이 수정 중인지)
    3. 의존성 블로킹 이슈 (A가 끝나야 B가 시작 가능한 것)
    4. 다음 우선순위 작업 목록
    5. 각 세션에 전달할 다음 지시사항
    
    를 정리해줘.

⚠️

**한계** 상태 업데이트가 각 세션의 수동 실행에 의존하며 병렬 자동 실행은 불가능합니다. 패턴이 안정화되면 방법 2로 전환하세요. 

06

## 방법 2 — Claude Agent SDK 스크립트

반복 패턴이 안정화되면 SDK로 자동화합니다. 서브에이전트를 병렬로 실행하고 결과를 자동으로 수집합니다.

### 설치

BASH
    
    
    pip install claude-agent-sdk

### orchestrator.py — 기본 구조

PYTHON
    
    
    import asyncio
    from claude_agent_sdk import query, ClaudeAgentOptions
    
    # 서브에이전트 실행 함수
    async def run_subagent(role: str, task: str, cwd: str):
        results = []
        async for message in query(
            prompt=task,
            options=ClaudeAgentOptions(
                cwd=cwd,
                allowed_tools=["Bash", "Read", "Write"],
                system_prompt=f"당신은 {role} 담당입니다."
            )
        ):
            if hasattr(message, "result"):
                results.append(message.result)
        return results
    
    # 오케스트레이터 메인
    async def orchestrate():
        # 서브에이전트 병렬 실행
        backend_task  = run_subagent("백엔드", "현재 TODO 처리해줘", "./backend")
        frontend_task = run_subagent("프론트엔드", "현재 TODO 처리해줘", "./frontend")
    
        backend_result, frontend_result = await asyncio.gather(
            backend_task, frontend_task
        )
    
        # 오케스트레이터가 결과 종합 및 보고
        async for message in query(
            prompt=f"""
            백엔드 결과: {backend_result}
            프론트엔드 결과: {frontend_result}
    
            위 결과를 바탕으로:
            1. 전체 진행상황 요약
            2. 충돌 / 의존성 이슈
            3. 다음 우선순위 작업
            를 정리해줘.
            """
        ):
            if hasattr(message, "result"):
                print(message.result)
    
    asyncio.run(orchestrate())

### 실행
    
    
    python orchestrator.py

07

## Bedrock 환경 연결

사내 AWS Bedrock 환경에서 사용할 때는 환경변수 설정만으로 전환됩니다. 코드 변경은 전혀 필요하지 않습니다.

BASH — .env.bedrock
    
    
    # Bedrock 사용 선언
    export CLAUDE_CODE_USE_BEDROCK=1
    
    # AWS 리전 (서울)
    export AWS_REGION=ap-northeast-2
    
    # AWS 자격증명 — 프로파일 방식 (권장)
    export AWS_PROFILE=your-company-profile
    
    # 이후 동일하게 실행
    python orchestrator.py

### 환경별 전환 — .env 파일로 관리

BASH — .env.local (개인 MacBook)
    
    
    ANTHROPIC_API_KEY=sk-ant-...

BASH — .env.bedrock (사내)
    
    
    CLAUDE_CODE_USE_BEDROCK=1
    AWS_REGION=ap-northeast-2
    AWS_PROFILE=company-profile

💡

개인 MacBook에서 패턴을 완성한 뒤, .env.bedrock으로 전환해 사내 환경에 그대로 적용하세요. 코드 수정 없이 동일하게 동작합니다.

08

## CLAUDE.md 설계 가이드

CLAUDE.md는 각 세션이 시작될 때 자동으로 읽히는 컨텍스트 파일입니다. 역할 분리와 공통 규칙을 여기에 정의합니다.

### 프로젝트 루트 CLAUDE.md — 공통 규칙

MARKDOWN
    
    
    # 프로젝트: BIP-Pipeline
    
    ## 역할 분배
    - 세션 A (백엔드): FastAPI 엔드포인트, 비즈니스 로직
    - 세션 B (프론트엔드): React 컴포넌트, UI/UX
    - 세션 C (DB): Oracle 스키마, 마이그레이션
    - 오케스트레이터: 진행 상황 조율, 충돌 감지
    
    ## 공통 규칙
    1. 작업 단위 완료 시 .orchestrator/status-{역할}.md 업데이트 필수
    2. 다른 세션 담당 파일 수정 전 오케스트레이터에 보고
    3. 블로킹 이슈 발생 시 즉시 status 파일에 기록

### 오케스트레이터 세션 역할 정의

MARKDOWN — .claude/session-orchestrator.md
    
    
    # 오케스트레이터 역할
    
    당신은 아래 세션들의 진행상황을 모니터링하고 조율하는 역할입니다.
    
    ## 주요 임무
    1. .orchestrator/ 폴더의 모든 status 파일 주기적으로 확인
    2. 같은 파일을 여러 세션이 수정 중인지 충돌 감지
    3. 의존성 순서 관리 (A 완료 후 B 시작 필요한 것)
    4. 전체 진행률 계산 및 보고
    5. 각 세션에 다음 작업 지시
    
    ## 보고 형식
    - 진행률: 세션별 완료 작업 / 전체 작업
    - 충돌 위험: 파일명과 관련 세션
    - 블로킹: 현재 대기 중인 세션과 이유
    - 다음 지시: 세션별 구체적 액션

09

## 운영 체크리스트

### 초기 셋업

  * 프로젝트 루트에 CLAUDE.md 작성 완료
  * .claude/ 폴더에 세션별 역할 파일 작성
  * .orchestrator/ 폴더 생성
  * 각 세션 CLAUDE.md에 상태 업데이트 규칙 추가
  * Bedrock 환경변수 설정 확인 (사내 환경)

### 일상 운영

  * 오케스트레이터 세션을 별도 터미널 창에서 상시 운영
  * 각 작업 단위 완료 시 status 파일 업데이트
  * 30분~1시간마다 오케스트레이터에 전체 상황 확인 요청
  * 충돌 감지 시 즉시 관련 세션에 중단 지시

### SDK 자동화 전환 시점

  * 동일 패턴의 오케스트레이션이 3회 이상 반복될 때
  * 세션 수가 5개 이상으로 늘어날 때
  * 병렬 실행이 필수적으로 필요해질 때
  * Bedrock 환경에서 안정적으로 동작 확인 후

🎯

**핵심 권고사항** 처음부터 SDK로 자동화하려 하지 말고, 방법 1(파일 공유)로 워크플로우 패턴을 먼저 안정화하세요. 반복적으로 하게 되는 패턴이 생기면 그때 Python 스크립트로 옮기는 것이 훨씬 효율적입니다. Bedrock 전환은 환경변수 하나로 되므로 개인 환경에서 완성한 패턴을 사내에 그대로 적용하면 됩니다. 
