# Hermes Agent 조사 보고서

Nous Research의 자기 개선형 오픈소스 AI 에이전트 | 2026-04-13 조사

69.9K

GitHub Stars

40+

Built-in Tools

118

Bundled Skills

200+

지원 LLM

15+

플랫폼

MIT

라이선스

## 1\. 개요

### Hermes Agent란?

Nous Research가 개발한 **자기 개선형(Self-Improving) 오픈소스 AI 에이전트**. 2026년 2월 출시, v0.7.0 (2026-04-03 기준).

핵심 차별점: **내장 학습 루프(Built-in Learning Loop)** — 작업 완료 후 자동으로 스킬을 생성/개선하고, 세션 간 지식을 유지하며, 사용할수록 더 똑똑해짐.

IDE 종속 코파일럿이나 단순 챗봇 래퍼가 아닌, **인프라 위에서 독립적으로 실행되는 자율 에이전트**.

### Nous Research

Hermes, Nomos, Psyche 언어 모델을 개발한 AI 연구 조직. Hermes Agent는 이들의 에이전트 프레임워크 제품.

호환 제공자: Nous Portal, OpenRouter (200+모델), OpenAI, Anthropic, z.ai, Kimi/Moonshot, 커스텀 엔드포인트

## 2\. 핵심 학습 루프 (Closed Learning Loop)

1\. Receive  
메시지 수신

→

2\. Retrieve  
메모리/스킬 검색

→

3\. Reason & Act  
LLM 추론 + 도구 호출

→

4\. Document  
스킬 자동 생성/갱신

→

5\. Persist  
지식 영구 저장

### 자기 개선 효과

  * 자동 생성된 스킬을 사용한 에이전트는 연구 작업을 **40% 더 빠르게** 완료 (프롬프트 튜닝 없이)
  * 5+ 도구 호출이 필요한 복잡 작업 완료 시 자동으로 스킬 문서 생성
  * 반복 작업은 점진적으로 효율 향상 (사용자 선호 형식 학습)
  * 리플렉션 토큰 오버헤드: 일반 에이전트 대비 15~25% 추가



## 3\. 메모리 아키텍처 (3계층)

계층 | 역할 | 기술 | 지속성  
---|---|---|---  
**Session Memory** | 현재 대화 컨텍스트 | 컨텍스트 윈도우 내 유지, `context_compressor.py`로 초과 시 요약 | 세션 내  
**Persistent Memory** | 세션 간 장기 기억 (대화, 사실, 선호도) | SQLite + FTS5 전문검색, LLM 요약 기반 압축, ~10ms 검색 (10K+ 문서) | 영구  
**Procedural Memory (Skills)** | 방법론 기억 — "어떻게 했는지" 절차 저장 | Markdown 스킬 파일, agentskills.io 표준, Progressive Disclosure (3단계) | 영구  
  
### 핵심 혁신: Procedural Memory

전통적 에이전트가 **사실(facts)** 을 기억하는 반면, Hermes는 **방법(methods)** 을 기억한다. 성공한 워크플로우를 재사용 가능한 절차로 변환하여 유사 문제 발생 시 자동 로드.

캐시 인식 설계: 시스템 프롬프트 스냅샷을 세션 초기화 시 고정하여 고빈도 모델 호출이 캐시된 컨텍스트 윈도우를 효율적으로 사용.

## 4\. 스킬 시스템

### 스킬 구조
    
    
    my-skill/
      SKILL.md          # YAML frontmatter + 절차 내용
      scripts/          # 실행 스크립트
      references/       # 참조 문서
      assets/           # 이미지 등

agentskills.io 오픈 표준 준수

### Progressive Disclosure (3단계)

  * **Level 0** : 스킬 이름+설명 목록만 (토큰 최소)
  * **Level 1** : 특정 스킬 전체 내용 로드
  * **Level 2** : 스킬 내 특정 참조 파일 로드



필요할 때만 상세 로드 → 토큰 절약

### 스킬 생명주기

단계| 설명  
---|---  
자동 생성| 5+ 도구 호출 복잡 작업 완료 후 에이전트가 자동으로 `SKILL.md` 생성  
자기 개선| 사용 중 모순/확장 정보 발견 시 스킬 문서 자동 패치  
공유| agentskills.io Skills Hub를 통해 커뮤니티 공유 (보안 스캔 통과 필수)  
검색| FTS5 전문검색으로 ~10ms 내 관련 스킬 조회  
  
118개 번들 스킬 (96 기본 + 22 선택), 26+ 카테고리

## 5\. 코어 아키텍처

### 5개 주요 서브시스템

서브시스템| 핵심 파일| 역할  
---|---|---  
**AIAgent Loop** | `run_agent.py` (~9,200줄) | 중앙 오케스트레이션 — 프로바이더 선택, 프롬프트 구성, 도구 실행, 영속성  
**Prompt System** | `prompt_builder.py`, `context_compressor.py` | 성격 파일 + 메모리 + 스킬 + 컨텍스트 문서 조립, Anthropic 캐시 최적화  
**Provider Resolver** | 공유 런타임 | (provider, model) 튜플 → 자격증명 + API 모드 매핑 (18+ 프로바이더)  
**Tool System** | 자기등록 레지스트리 | 47개 도구 / 20개 도구셋, 6개 터미널 백엔드 (local, Docker, SSH, Daytona, Modal, Singularity)  
**Messaging Gateway** | 장기 실행 프로세스 | 14개 플랫폼 어댑터, 통합 세션 라우팅, 인가  
  
### 데이터 플로우

경로| 흐름  
---|---  
**CLI** | user input → `HermesCLI.process_input()` → `AIAgent.run_conversation()` → API call → tool dispatch → response → DB persist  
**Gateway** | platform event → adapter → auth → session resolve → `AIAgent.run_conversation()` → platform delivery  
**Cron** | scheduler tick → job load → fresh AIAgent → skill inject → response → state update  
  
### 설계 원칙

  * **Prompt Stability** : 대화 중 시스템 프롬프트 변경 불가
  * **Observable Execution** : 모든 도구 호출이 사용자에게 가시적
  * **Interruptible** : 작업 중단 가능
  * **Platform-Agnostic Core** : 코어와 플랫폼 분리
  * **Loose Coupling** : 레지스트리 기반 느슨한 결합
  * **Profile Isolation** : 여러 프로필 동시 실행 가능



## 6\. 실행 환경 & 플랫폼

### 터미널 백엔드 (6개)

  * **Local** — 로컬 머신 직접 실행
  * **Docker** — 컨테이너 격리
  * **SSH** — 원격 서버
  * **Daytona** — 클라우드 개발환경
  * **Modal** — 서버리스 실행
  * **Singularity** — HPC 컨테이너



### 메시징 플랫폼 (15+)

  * CLI, Telegram, Discord, Slack
  * WhatsApp, Signal, Matrix, Mattermost
  * Email, SMS, DingTalk, Feishu
  * WeCom, BlueBubbles, Home Assistant



### 설치
    
    
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

Linux, macOS, WSL2, Termux (Android) 지원. 최소 사양: 2코어, 8GB RAM, $5/월 VPS

## 7\. 다른 에이전트와 비교

항목 | Hermes Agent | Claude Code | OpenClaw  
---|---|---|---  
**철학** | 자기 개선하는 에이전트 | 코드 생성 전문가 | 다중 플랫폼 연결  
**학습 루프** | 내장 스킬 자동 생성/개선 | 부분적 메모리 파일 수동 | 없음  
**메모리** | 3계층 (세션/영구/절차적) | CLAUDE.md + auto memory | 없음  
**플랫폼** | 15+ (Telegram, Slack 등) | 터미널/IDE/웹 | 50+  
**도구** | 47개 + MCP 서버 | 파일/터미널/웹 | 플러그인 기반  
**강점** | 자율 학습, 스킬 생태계 | 코딩 품질, 프론티어 모델 | 플랫폼 커버리지  
**GitHub Stars** | ~70K | N/A (Anthropic 제품) | ~345K  
**라이선스** | MIT | 상용 | Apache 2.0  
  
## 8\. BIP 프로젝트 관점 시사점

### 참고 가능한 개념

  * **스킬 시스템** : BIP의 체크리스트 에이전트가 반복적으로 수행하는 분석 패턴을 "스킬"로 저장하면 프롬프트 토큰 절약 + 일관성 확보 가능
  * **Progressive Disclosure** : 현재 모든 체크리스트 항목을 한 번에 LLM에 전달하는데, 레벨별 로딩으로 토큰 최적화 가능
  * **Procedural Memory** : "환율 방향성 판정법", "유가 영향 분석법" 같은 반복 절차를 스킬 문서로 관리하면 방향성 오판 문제 구조적 해결
  * **Cron 스케줄링** : Hermes의 자연어 크론 스케줄링이 Airflow DAG보다 유연할 수 있음 (단, 엔터프라이즈 안정성은 Airflow가 우위)



### 현재 BIP와의 차이

  * BIP는 **파이프라인 중심** (Airflow DAG → 정해진 흐름), Hermes는 **에이전트 중심** (자율 판단)
  * BIP의 체크리스트 에이전트는 Haiku ReAct 방식 → Hermes의 학습 루프와 유사하지만 스킬 저장/재활용 메커니즘은 없음
  * BIP의 뉴스 다이제스트 파이프라인은 Hermes의 "반복 작업 학습" 개념과 유사 (패턴 인식 → 효율화)
  * Hermes의 멀티 플랫폼 게이트웨이는 BIP의 텔레그램 + 이메일 구조보다 확장성이 높음



### 도입 시 고려사항

  * 리플렉션 토큰 오버헤드 15~25% — 비용 민감한 환경에서는 부담
  * 월 API 비용 $15~$400+ — BIP 현재 ~$5/월 대비 크게 증가
  * 코딩 전문 작업은 Claude Code/Cursor가 더 적합 (Hermes 공식 인정)
  * SQLite 기반 → PostgreSQL 중심의 BIP 인프라와 통합 시 추가 작업 필요
  * 자율 에이전트의 예측 불가능성 — BIP의 거버넌스(보안, 감사 로그) 요구사항과 충돌 가능



## 9\. 웹앱 / Open WebUI 연동

### Hermes Agent — 웹 연동 (최상)

OpenAI 호환 API 서버를 노출하므로, **아무 프론트엔드와 바로 연결** 가능.

방식| 설명  
---|---  
**Open WebUI**|  공식 연동 문서 제공. OPENAI_API_BASE_URL만 설정하면 완료  
**hermes-webui**| [전용 웹 UI](<https://github.com/nesquena/hermes-webui>) — CLI과 동일한 기능을 브라우저에서  
**hermes-workspace**| [네이티브 워크스페이스](<https://github.com/outsourc-e/hermes-workspace>) — 채팅+터미널+메모리+스킬 인스펙터  
**기타**|  LobeChat, LibreChat, NextChat, ChatBox 등 OpenAI 포맷 지원 프론트엔드 모두 가능  
  
### Deep Agents — 웹 연동 (제한적)

방식| 설명  
---|---  
**deep-agents-ui**| [LangChain 공식 전용 UI](<https://github.com/langchain-ai/deep-agents-ui>)  
**Open WebUI**|  직접 연동 불가. OpenAI 호환 래퍼를 별도 구현해야 연결 가능  
  
LangChain/LangGraph 기반이라 범용 프론트엔드와 바로 붙는 구조는 아님

## 10\. BIP에 Hermes를 도입한다면?

### 현재 BIP 구조 vs Hermes 최상단 구조

### 현재 BIP
    
    
    Airflow (스케줄링/모니터링)
      → BIP-Agents (LLM + MCP)
        → checklist_agent
        → preopen_analyzer
        → stock_screener
      → 텔레그램 / 이메일

### Hermes 최상단
    
    
    Hermes Agent (오케스트레이션+학습+웹UI)
      → BIP-Agents (도구로 호출)
      → Airflow (스케줄링만)
      → 웹 / 텔레그램 / Slack

### 3가지 선택지

옵션 | 설명 | 장점 | 단점 | 리스크  
---|---|---|---|---  
A. 개념만 차용 (추천) | 현재 구조 유지하면서 Hermes의 좋은 아이디어를 BIP에 점진적으로 적용 | 안정적, 기존 투자 보존, 점진적 개선 | 웹 UI/멀티플랫폼은 직접 구현 필요 | 낮음  
B. 인터페이스 레이어 | Hermes를 사용자 대화 창구로, 실제 분석은 BIP-Agents가 처리 | 웹 UI 즉시 확보, 학습 루프 활용 | Hermes↔BIP 연동 개발 필요, 이중 인프라 | 중간  
C. 전면 교체 | BIP-Agents를 Hermes 프레임워크로 마이그레이션 | 통합된 아키텍처, 학습 루프 네이티브 | 기존 코드 폐기, 거버넌스 재구축, SQLite↔PostgreSQL | 높음  
  
### 옵션 A: 차용 가능한 Hermes 개념

  * **스킬 시스템** → 체크리스트 에이전트의 반복 분석 패턴을 스킬 문서로 저장 (환율 방향성 판정, 유가 분석 등)
  * **Procedural Memory** → "어떻게 했는지"를 기억 — 현재 auto memory는 "무엇을" 기억
  * **Progressive Disclosure** → 프롬프트에 스킬 전체를 넣지 않고 레벨별 로딩으로 토큰 절약
  * **웹 UI** → 기존 React-FastAPI에 채팅 인터페이스 추가 (Hermes 불필요)
  * **뉴스 다이제스트** → 이미 BIP에서 구현 완료 (Hermes의 "반복 작업 학습"과 유사)



### 옵션 B: Hermes를 인터페이스 레이어로 쓸 때
    
    
    사용자 ↔ Hermes (대화/웹UI/학습)
               ↕ OpenAI 호환 API
           BIP-Agents API (실제 분석)
               ↕
           Airflow + PostgreSQL + MCP

  * Hermes가 BIP-Agents의 `/api/checklist/analyze`, `/api/screener/daily` 등을 도구로 호출
  * 사용자는 "오늘 시장 어때?" 같은 자연어로 질문 → Hermes가 판단해서 적절한 BIP API 호출
  * 학습 루프로 자주 묻는 질문의 응답 패턴을 스킬로 저장



### Hermes 도입 시 잃는 것

  * **Airflow 안정성** — 스케줄링/재시도/모니터링 UI → Hermes cron은 이만큼 성숙하지 않음
  * **PostgreSQL 인프라** → Hermes는 SQLite 기반, 기존 39개 테이블과 통합 어려움
  * **감사 로그/보안** → agent_audit_log, security_governance 등 다시 구축 필요
  * **토큰 비용** → 리플렉션 오버헤드 15~25% 증가 (BIP 현재 ~$5/월 → ~$20+/월)
  * **예측 가능성** → 자율 에이전트의 행동이 규칙 기반보다 불확실



## 11\. 비용 구조

항목| 수치  
---|---  
최소 호스팅| $5/월 VPS (2코어, 8GB RAM)  
월 API 비용| $15~$400+ (모델/사용량 따라)  
리플렉션 오버헤드| 토큰 15~25% 추가  
FTS5 검색 지연| ~10ms (10K+ 문서)  
  
## 12\. 참고 자료

  * [GitHub - NousResearch/hermes-agent](<https://github.com/nousresearch/hermes-agent>) (69.9K stars, MIT)
  * [공식 문서](<https://hermes-agent.nousresearch.com/docs/>)
  * [아키텍처 상세](<https://hermes-agent.nousresearch.com/docs/developer-guide/architecture>)
  * [Complete Guide (NxCode, 2026)](<https://www.nxcode.io/resources/news/hermes-agent-complete-guide-self-improving-ai-2026>)
  * [OpenClaw 비교 분석 (MindStudio)](<https://www.mindstudio.ai/blog/what-is-hermes-agent-openclaw-alternative>)
  * [Self-Improving AI Agent (DEV Community)](<https://dev.to/arshtechpro/hermes-agent-a-self-improving-ai-agent-that-runs-anywhere-2b7d>)



마지막 업데이트: 2026-04-13 | BIP-Pipeline 내부 조사 문서 
