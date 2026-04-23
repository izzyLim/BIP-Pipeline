# OpenMetadata 기능 및 사용 가이드

> **공식 문서:** https://docs.open-metadata.org

---

## 목차

1. [개요](#1-개요)
2. [아키텍처](#2-아키텍처)
3. [핵심 기능](#3-핵심-기능)
4. [커넥터 생태계](#4-커넥터-생태계)
5. [관리 기능](#5-관리-기능)
6. [배포 옵션](#6-배포-옵션)
7. [API](#7-api)
8. [BIP-Pipeline에서의 활용 현황](#8-bip-pipeline에서의-활용-현황)
9. [참고](#9-참고)

---

## 1. 개요

### OpenMetadata란 무엇인가

OpenMetadata는 데이터 조직을 위한 **통합 메타데이터 플랫폼**이다. 데이터 발견(Discovery), 계보(Lineage), 거버넌스(Governance), 품질(Quality), 협업(Collaboration)을 하나의 플랫폼에서 관리할 수 있도록 설계되었다.

### 핵심 가치: 중앙화된 메타데이터 SSOT

모든 데이터 자산의 메타데이터를 **단일 진실 원천(Single Source of Truth)**으로 관리한다. 테이블 설명, 컬럼 정의, 태그, 용어집, 계보 정보가 하나의 카탈로그에 통합되어 있으므로, 여러 도구와 팀 간의 메타데이터 불일치 문제를 해소한다.

- 데이터베이스, 대시보드, 파이프라인, ML 모델 등 **이기종 자산**을 통합 관리
- API 중심 설계로 **프로그래밍 방식 자동화** 가능
- 협업 기능으로 **데이터 문화 형성** 지원

### 오픈소스 (Apache 2.0)

Apache 2.0 라이선스로 배포되며, 커뮤니티 주도로 개발된다. 상용 관리형 서비스(Collate)도 제공되지만 핵심 기능은 모두 오픈소스에 포함되어 있다. GitHub에서 18,000+ 스타를 보유하며, 활발한 Slack 커뮤니티가 운영 중이다.

---

## 2. 아키텍처

### 전체 구조

OpenMetadata는 **API 중심(API-first)** 아키텍처를 채택한다. JSON Schema로 엔티티 모델을 정의하고, 이를 기반으로 REST API를 자동 생성하며, UI는 해당 API를 소비하는 클라이언트이다.

```mermaid
graph TB
    subgraph Clients["클라이언트"]
        UI[Web UI<br/>React]
        SDK[Python SDK<br/>openmetadata-ingestion]
        API_CLI[REST API<br/>직접 호출]
    end

    subgraph Server["OpenMetadata Server"]
        REST[REST API Layer<br/>Dropwizard/Java]
        SCHEMA[JSON Schema<br/>엔티티 모델 정의]
        AUTH[인증/인가<br/>JWT, SSO, RBAC]
        EVENT[이벤트 핸들러<br/>변경 감지, 알림]
    end

    subgraph Storage["저장소"]
        DB[(MySQL / PostgreSQL<br/>메타데이터 저장)]
        ES[(Elasticsearch<br/>검색 인덱스)]
    end

    subgraph Ingestion["수집 프레임워크"]
        CONN[커넥터<br/>DB, Dashboard, Pipeline, ...]
        PROF[프로파일러<br/>통계 수집]
        LINEAGE_I[계보 수집기]
        DQ[품질 테스트 러너]
    end

    subgraph External["외부 시스템"]
        PG[(PostgreSQL)]
        AF[Airflow]
        DASH[대시보드 도구]
        MSG[메시징 시스템]
    end

    UI & SDK & API_CLI --> REST
    REST --> SCHEMA
    REST --> AUTH
    REST --> EVENT
    REST --> DB
    REST --> ES

    CONN --> REST
    PROF --> REST
    LINEAGE_I --> REST
    DQ --> REST

    CONN --> PG & AF & DASH & MSG

    style Server fill:#e3f2fd
    style Storage fill:#e8f5e9
    style Ingestion fill:#fff3e0
    style External fill:#fce4ec
```

### 주요 구성 요소

| 구성 요소 | 역할 | 기술 스택 |
|-----------|------|-----------|
| **Server** | REST API 제공, 비즈니스 로직 | Java (Dropwizard) |
| **UI** | 웹 기반 사용자 인터페이스 | React, TypeScript |
| **Database** | 메타데이터 영구 저장 | MySQL 또는 PostgreSQL |
| **Elasticsearch** | 전문 검색, 필터링 | Elasticsearch 7.x / 8.x |
| **Ingestion Framework** | 메타데이터 수집 파이프라인 | Python (openmetadata-ingestion) |

### API 중심 설계 흐름

```
JSON Schema (엔티티 정의)
    ↓
REST API (자동 생성, Swagger 문서)
    ↓
Web UI (API 소비, 시각화)
    ↓
Python SDK (프로그래밍 자동화)
```

이 설계 덕분에 UI에서 할 수 있는 **모든 작업을 API/SDK로도 동일하게** 수행할 수 있다. 자동화 스크립트, CI/CD 파이프라인, 외부 도구 연동이 자연스럽게 가능하다.

---

## 3. 핵심 기능

### 3-1. 데이터 발견 (Data Discovery)

#### 무엇인가

조직 내의 모든 데이터 자산을 **검색하고 탐색**할 수 있는 기능이다. 데이터 카탈로그의 가장 기본적이고 핵심적인 가치이다.

#### 왜 필요한가

- 데이터 사일로 해소: 여러 시스템에 흩어진 데이터를 한곳에서 검색
- 중복 작업 방지: 이미 존재하는 데이터셋을 모르고 새로 만드는 것을 방지
- 데이터 이해도 향상: 스키마, 설명, 태그, 소유자 정보를 통해 데이터의 의미를 빠르게 파악

#### 사용 방법

**통합 검색**
- 키워드 검색: 테이블명, 컬럼명, 설명 텍스트를 대상으로 전문 검색
- 고급 검색: 필터(소유자, 태그, 도메인, 서비스, Tier 등)를 조합한 세밀한 검색
- Elasticsearch 기반으로 빠른 응답 제공

**자산 유형**

OpenMetadata가 관리하는 데이터 자산 유형은 다음과 같다:

| 자산 유형 | 설명 | 예시 |
|-----------|------|------|
| 테이블 (Table) | 데이터베이스 테이블/뷰 | `stock_price_1d`, `analytics_valuation` |
| 토픽 (Topic) | 메시징 토픽 | Kafka 토픽 |
| 대시보드 (Dashboard) | BI 대시보드 | Grafana, Superset 패널 |
| 파이프라인 (Pipeline) | ETL/오케스트레이션 | Airflow DAG |
| ML 모델 (ML Model) | 머신러닝 모델 | MLflow 등록 모델 |
| 컨테이너 (Container) | 오브젝트 스토리지 | S3 버킷, GCS 버킷 |
| 검색 인덱스 (Search Index) | 검색 엔진 인덱스 | Elasticsearch 인덱스 |
| API 엔드포인트 (API Endpoint) | REST API | 외부 데이터 소스 API |

**데이터 미리보기**
- 샘플 데이터 조회 (관리자 설정에 따라 활성화/비활성화 가능)
- 컬럼별 통계 (null 비율, 고유값 수, 최대/최소/평균 등)

**상세 정보**
- 스키마: 컬럼명, 타입, 설명, 태그, 용어집 매핑
- 프로파일: 행 수, 컬럼 통계, 분포 히스토그램
- 계보: 데이터의 출처와 소비처
- 쿼리 이력: 해당 테이블에 대해 실행된 쿼리 패턴
- 사용 빈도: 조회 횟수, 최근 접근 사용자

---

### 3-2. 데이터 계보 (Data Lineage)

#### 무엇인가

데이터가 **어디에서 왔고(source), 어떻게 변환되었으며(transformation), 어디로 흘러가는지(sink)**를 추적하는 기능이다.

#### 왜 필요한가

- **영향 분석(Impact Analysis)**: 소스 테이블 변경 시 어떤 하류(downstream) 자산이 영향 받는지 파악
- **근본 원인 추적(Root Cause Analysis)**: 데이터 품질 문제가 어느 단계에서 발생했는지 역추적
- **규정 준수(Compliance)**: 데이터의 전체 이동 경로를 감사 목적으로 기록
- **NL2SQL 맥락 제공**: 테이블 간의 관계를 LLM이 이해하도록 계보 정보를 활용

#### 사용 방법

```mermaid
graph LR
    subgraph "외부 소스"
        API1[Naver Finance API]
        API2[DART API]
        API3[Yahoo Finance]
    end

    subgraph "파이프라인"
        DAG1[02_price_kr DAG]
        DAG2[05_financial DAG]
        DAG3[09_analytics DAG]
    end

    subgraph "테이블"
        T1[stock_price_1d]
        T2[financial_statements]
        T3[analytics_stock_daily]
    end

    subgraph "소비자"
        C1[morning_report DAG]
        C2[Wren AI NL2SQL]
    end

    API1 --> DAG1 --> T1
    API2 --> DAG2 --> T2
    T1 & T2 --> DAG3 --> T3
    T3 --> C1
    T3 --> C2

    style T3 fill:#c8e6c9
```

**자동 계보 수집**
- 커넥터가 데이터베이스 쿼리 로그, Airflow DAG 정의 등을 분석하여 자동으로 계보를 생성
- Airflow 커넥터: DAG에서 참조하는 테이블 관계를 자동 추출
- 데이터베이스 커넥터: 뷰 정의의 SQL을 파싱하여 계보 생성

**컬럼 레벨 계보**
- 테이블 간 계보뿐 아니라 **개별 컬럼 간의 매핑**까지 추적
- 특정 컬럼이 어떤 소스 컬럼에서 파생되었는지 확인 가능
- 예: `analytics_stock_daily.close_price` ← `stock_price_1d.close`

**수동 계보 추가**
- UI에서 드래그 앤 드롭으로 계보 엣지 추가
- 자동 수집이 놓치는 복잡한 변환 로직에 유용

**Python SDK를 통한 프로그래밍 방식**
```python
from metadata.ingestion.lineage.sql_lineage import search_table_entities
from metadata.ingestion.ometa.ometa_api import OpenMetadata

# lineage 엣지 추가 예시
metadata.add_lineage(
    AddLineageRequest(
        edge=EntitiesEdge(
            fromEntity=source_ref,
            toEntity=target_ref,
            lineageDetails=LineageDetails(
                pipeline=pipeline_ref,
                description="DAG에서 자동 등록"
            )
        )
    )
)
```

**시각화**
- 그래프 뷰: 노드(엔티티)와 엣지(관계)로 구성된 인터랙티브 그래프
- 업스트림/다운스트림 탐색: 특정 자산에서 상류/하류를 단계적으로 펼쳐 확인
- 필터링: 특정 서비스, 데이터베이스, 스키마 기준으로 계보 범위 제한

---

### 3-3. 데이터 거버넌스

#### 3-3-1. 용어집 (Glossary)

##### 무엇인가

비즈니스 용어를 **표준화하여 정의하고, 데이터 자산과 연결**하는 기능이다. "PER", "ROE", "골든크로스" 같은 비즈니스 용어가 실제 어떤 테이블의 어떤 컬럼에 대응하는지를 명시적으로 관리한다.

##### 왜 필요한가

- **용어 표준화**: 같은 개념을 팀마다 다른 이름으로 부르는 혼란 방지
- **NL2SQL 정확도 향상**: 사용자가 비즈니스 용어로 질문할 때, 정확한 컬럼으로 매핑
- **신규 팀원 온보딩**: 도메인 지식을 체계적으로 문서화

##### 사용 방법

```mermaid
graph TB
    G["Glossary<br/>투자 용어집"]
    G --> T1["Term: PER<br/>(주가수익비율)"]
    G --> T2["Term: ROE<br/>(자기자본이익률)"]
    G --> T3["Term: 시가총액"]

    T1 --> C1["analytics_valuation.per"]
    T1 --> C2["consensus_estimates.per"]
    T2 --> C3["analytics_valuation.roe"]
    T3 --> C4["stock_info.market_cap"]

    T1 -.- S1["동의어: Price-to-Earnings Ratio"]
    T2 -.- S2["동의어: Return on Equity"]

    style G fill:#e1bee7
    style T1 fill:#f3e5f5
    style T2 fill:#f3e5f5
    style T3 fill:#f3e5f5
```

**계층 구조**
- Glossary (최상위): 도메인별 용어집 (예: 투자 용어집, 매크로 경제 용어집)
- Term (용어): 개별 비즈니스 용어
- Child Term (하위 용어): 용어 아래 세부 분류 가능

**용어 속성**
- 이름(Name): 영문 식별자 (`per`, `roe`)
- 표시 이름(Display Name): 한글 표시명 (`주가수익비율`)
- 설명(Description): 정의, 계산식, 단위 등 상세 설명
- 동의어(Synonyms): 같은 개념의 다른 명칭 (`PER`, `P/E Ratio`)
- 관련 용어(Related Terms): 연관 개념 링크
- 태그(Tags): 분류용 태그

**용어-자산 매핑**
- 용어를 테이블 또는 컬럼에 직접 태깅
- NL2SQL에서 사용자 질문의 비즈니스 용어를 정확한 컬럼에 매핑하는 데 핵심적으로 활용

**승인 워크플로우**
- Reviewer 지정: 용어 변경 시 리뷰어의 승인이 필요하도록 설정
- 용어의 품질과 일관성을 조직적으로 관리

**CSV 일괄 임포트/엑스포트**
- 대량의 용어를 CSV 파일로 작성한 뒤 일괄 업로드
- 기존 용어집을 CSV로 내보내 외부 도구에서 편집 후 재임포트
- 용어 이름, 설명, 동의어, 관련 용어, 소유자 등의 컬럼 지원

**스타일링**
- 용어에 색상(Color)과 아이콘(Icon)을 지정하여 시각적 구분
- UI에서 용어가 태깅된 자산을 쉽게 식별

**API 지원**
- REST API로 용어 CRUD, 용어-자산 매핑 자동화 가능
- `scripts/om_build_glossary.py` 같은 스크립트로 프로그래밍 방식 일괄 등록

---

#### 3-3-2. 분류 (Classification) & 태그 (Tags)

##### 무엇인가

데이터 자산에 **분류(Classification)와 태그(Tag)**를 부여하여 체계적으로 조직화하는 기능이다. 용어집이 비즈니스 의미를 정의한다면, 태그는 데이터의 **속성과 특성**을 분류한다.

##### 왜 필요한가

- **데이터 분류 체계**: 민감도(PII), 중요도(Tier), 레이어(Raw/Derived/Gold) 등으로 분류
- **검색 효율**: 태그 기반 필터링으로 원하는 자산을 빠르게 찾기
- **접근 제어 기반**: 태그를 RBAC 정책과 연동하여 세분화된 접근 제어
- **자동 거버넌스**: Auto Classification으로 민감 데이터 자동 식별

##### 사용 방법

**시스템 분류 (Built-in)**

| 분류 | 태그 예시 | 용도 |
|------|-----------|------|
| PII | `PII.Sensitive`, `PII.NonSensitive` | 개인정보 식별 |
| Tier | `Tier.Tier1`, `Tier.Tier2`, ... | 데이터 중요도 등급 |
| PersonalData | `PersonalData.Personal`, `PersonalData.SpecialCategory` | GDPR 대응 |

**사용자 정의 분류 생성**
- UI 또는 API를 통해 커스텀 Classification 생성
- 예: `DataLayer` (raw, derived, gold), `Domain` (market, financial, macro, news)
- 각 Classification 아래에 하위 태그를 자유롭게 정의

**자동 태깅 (Auto Classification)**
- 프로파일러 실행 시 컬럼 이름, 데이터 패턴을 분석하여 PII 등을 자동 태깅
- 이메일 패턴, 전화번호 패턴, 신용카드 번호 패턴 등 인식
- 자동 분류 결과를 리뷰 후 확정하는 워크플로우 지원

**태그를 통한 접근 제어**
- RBAC 정책에서 "PII.Sensitive 태그가 붙은 자산은 Data Steward만 접근 가능" 같은 규칙 설정
- 태그 기반 정책은 자산이 추가될 때 자동 적용

---

#### 3-3-3. 도메인 & 데이터 제품 (Domains & Data Products)

##### 무엇인가

**도메인(Domain)**은 비즈니스 영역별로 데이터를 그룹화하는 최상위 조직 단위이다. **데이터 제품(Data Product)**은 도메인 내에서 소비자에게 제공되는 의미 있는 데이터 묶음이다.

##### 왜 필요한가

- **데이터 메시(Data Mesh)** 아키텍처 지원: 도메인 소유권 기반 분산 데이터 관리
- **데이터 발견성 향상**: 도메인별로 자산을 탐색하여 관련 데이터를 빠르게 찾기
- **책임 명확화**: 각 도메인에 소유자를 지정하여 데이터 품질 책임 부여

##### 사용 방법

**도메인 기반 데이터 조직**
- 도메인 생성: `Market`, `Financial`, `Macro`, `News` 등
- 각 도메인에 관련 테이블, 파이프라인, 대시보드를 배정
- 도메인 소유자(Domain Owner)를 지정하여 거버넌스 책임 할당

**데이터 제품 정의**
- 도메인 내에서 특정 소비자(팀, 서비스)를 위한 데이터 제품 정의
- 데이터 제품에 포함되는 자산 목록, 품질 SLA, 접근 권한 설정
- 예: "투자 분석 데이터 제품" = `analytics_stock_daily` + `analytics_valuation` + `consensus_estimates`

---

### 3-4. 데이터 품질 & 관찰성

#### 무엇인가

데이터의 **정확성, 완전성, 적시성**을 검증하고, 이상 징후를 **자동 탐지**하여 알림을 보내는 기능이다.

#### 왜 필요한가

- **데이터 신뢰성 확보**: 잘못된 데이터로 의사결정을 내리는 위험 방지
- **조기 이상 감지**: 데이터 파이프라인 장애를 빠르게 발견
- **SLA 관리**: 데이터 제품의 품질 기준 충족 여부를 모니터링

#### 사용 방법

**품질 테스트 유형 (No-code 테스트)**

코드를 작성하지 않고 UI에서 테스트를 정의할 수 있다:

| 테스트 유형 | 설명 | 예시 |
|-------------|------|------|
| Column Values to Be Not Null | 특정 컬럼에 NULL이 없어야 함 | `stock_price_1d.close IS NOT NULL` |
| Column Values to Be Unique | 특정 컬럼 값의 고유성 확인 | `stock_info.ticker` |
| Column Values to Be Between | 값 범위 확인 | `stock_price_1d.volume >= 0` |
| Table Row Count to Be Between | 행 수 범위 확인 | `stock_info` 행 수가 2,000~10,000 사이 |
| Column Value Length to Be Between | 문자열 길이 확인 | `ticker` 길이 5~10자 |
| Table Custom SQL Query | 커스텀 SQL로 검증 | 사용자 정의 비즈니스 규칙 |

**프로파일러**
- 테이블 수준: 행 수, 크기, 생성/수정일
- 컬럼 수준: NULL 비율, 고유값 수, 최소/최대/평균/표준편차
- 히스토그램: 값 분포 시각화
- 시계열 추이: 프로파일 결과를 시간별로 추적하여 변화 감지

**알림 설정**
- 테스트 실패 시 Slack, Teams, Email, Webhook으로 알림 발송
- 심각도(Severity) 기반 알림 라우팅

**인시던트 관리**
- 테스트 실패를 "인시던트"로 등록하고 담당자를 지정
- 해결 과정을 문서화하고 추적
- 해결 완료 시 인시던트를 종료하여 이력 관리

**이상 탐지 (Anomaly Detection)**
- 프로파일러가 수집한 시계열 통계를 기반으로 이상치를 자동 감지
- 행 수의 급격한 변화, NULL 비율 급증 등을 자동 경고
- 별도 설정 없이 프로파일러 실행만으로 동작

---

### 3-5. 데이터 협업

#### 무엇인가

데이터 자산에 대해 팀원 간 **소통하고, 작업을 요청하며, 변경 사항을 공유**하는 기능이다.

#### 왜 필요한가

- **컨텍스트 보존**: 데이터에 대한 질문과 답변이 해당 자산에 직접 연결
- **작업 추적**: 메타데이터 보강 요청을 체계적으로 관리
- **변경 인식**: 데이터 자산의 변경 사항을 관심 있는 사용자에게 자동 통보

#### 사용 방법

**대화 스레드 (Conversations)**
- 테이블, 컬럼, 대시보드 등 모든 자산에 대화 스레드를 생성
- `@mention`으로 특정 사용자를 태그하여 질문이나 논의
- Markdown 지원, 코드 블록 삽입 가능

**작업 (Tasks)**
- 설명 요청(Request Description): 빈 설명이 있는 자산에 설명 작성을 요청
- 태그 요청(Request Tag): 태그 추가를 요청
- 담당자 할당, 기한 설정, 상태(Open/Closed) 관리
- 작업 목록을 대시보드에서 한눈에 확인

**공지사항 (Announcements)**
- 특정 자산에 시간 제한 공지 등록 (예: "이 테이블은 4/15~4/20 마이그레이션 예정")
- 해당 자산을 조회하는 사용자에게 공지가 표시됨
- 시작일/종료일 지정으로 자동 노출/숨김

**활동 피드 (Activity Feeds)**
- 사용자가 팔로우한 자산의 모든 변경 사항을 타임라인으로 표시
- 스키마 변경, 태그 추가, 설명 수정, 소유자 변경 등 기록
- 개인화된 피드로 관심 영역의 변화만 추적

**팔로우 & 소유자 지정**
- 자산 팔로우: 변경 알림을 수신
- 소유자(Owner) 지정: 데이터 품질과 메타데이터의 책임자 명시
- 팀(Team) 단위로도 소유권 설정 가능

---

### 3-6. 데이터 인사이트

#### 무엇인가

조직의 **메타데이터 건강 상태와 데이터 활용도**를 대시보드로 시각화하는 기능이다.

#### 왜 필요한가

- **거버넌스 진행 상황 추적**: 설명 커버리지, 태그 적용률 등의 KPI 모니터링
- **데이터 문화 측정**: 팀별/사용자별 기여도와 활용 패턴 파악
- **개선 우선순위 도출**: 메타데이터가 가장 부족한 영역 식별

#### 사용 방법

**KPI 정의**
- 설명 커버리지: 설명이 있는 테이블/컬럼 비율 목표 설정 (예: 95%)
- 소유자 지정률: 소유자가 배정된 자산 비율
- 태그 적용률: 태그가 하나 이상 있는 자산 비율
- 기간별 목표 설정 및 달성률 추적

**데이터 자산 통계**
- 총 자산 수, 유형별 분포
- 시간별 자산 증가 추이
- 테이블별 크기, 행 수 변화

**활용도 분석**
- 가장 많이 조회된 테이블/대시보드
- 활발하게 사용되는 자산 vs 미사용 자산 식별
- 사용자별 활동 통계

---

## 4. 커넥터 생태계

OpenMetadata는 다양한 데이터 소스와 도구에 대한 커넥터를 제공한다. 커넥터는 **메타데이터 수집(Ingestion)**, **프로파일링(Profiling)**, **계보 추출(Lineage)**, **품질 테스트(Quality)** 워크플로우를 지원한다.

### 4-1. 데이터베이스

| 커넥터 | 메타데이터 | 프로파일러 | 계보 | 품질 테스트 |
|--------|:----------:|:----------:|:----:|:-----------:|
| PostgreSQL | O | O | O | O |
| MySQL | O | O | O | O |
| Snowflake | O | O | O | O |
| BigQuery | O | O | O | O |
| Redshift | O | O | O | O |
| Oracle | O | O | O | O |
| MSSQL | O | O | O | O |
| ClickHouse | O | O | O | O |
| Databricks | O | O | O | O |
| Trino / Presto | O | O | O | O |
| DynamoDB | O | - | - | - |
| MongoDB | O | - | - | - |

### 4-2. 대시보드

| 커넥터 | 메타데이터 | 계보 |
|--------|:----------:|:----:|
| Tableau | O | O |
| Power BI | O | O |
| Looker | O | O |
| Superset | O | O |
| Metabase | O | O |
| Grafana | O | - |
| Redash | O | - |
| Mode | O | O |

### 4-3. 파이프라인

| 커넥터 | 메타데이터 | 계보 |
|--------|:----------:|:----:|
| Airflow | O | O |
| dbt | O | O |
| Dagster | O | O |
| Databricks Pipeline | O | O |
| Fivetran | O | O |
| Airbyte | O | - |
| NiFi | O | - |
| Glue | O | O |

### 4-4. 메시징

| 커넥터 | 메타데이터 | 스키마 |
|--------|:----------:|:------:|
| Kafka | O | O |
| Redpanda | O | O |
| Kinesis | O | - |

### 4-5. ML 모델

| 커넥터 | 메타데이터 |
|--------|:----------:|
| MLflow | O |
| SageMaker | O |

### 4-6. 스토리지

| 커넥터 | 메타데이터 |
|--------|:----------:|
| S3 | O |
| GCS | O |
| ADLS | O |

### 4-7. 메타데이터 마이그레이션

기존 메타데이터 카탈로그에서 OpenMetadata로 마이그레이션하는 커넥터:

| 커넥터 | 설명 |
|--------|------|
| Alation | Alation에서 테이블/컬럼 설명, 태그, 용어집 마이그레이션 |
| Atlas | Apache Atlas에서 메타데이터 마이그레이션 |
| Amundsen | Amundsen에서 메타데이터 마이그레이션 |

---

## 5. 관리 기능

### 5-1. 팀 & 사용자

#### 무엇인가

조직 구조를 반영한 **계층적 팀 구조**와 사용자 관리 기능이다.

#### 왜 필요한가

- **소유권 관리**: 데이터 자산의 책임 소재를 조직 구조에 맞게 설정
- **접근 제어**: 팀/사용자 단위의 권한 관리
- **협업**: 팀 단위의 알림, 작업 할당

#### 사용 방법

**계층적 팀 구조**
- Organization (최상위) → Business Unit → Division → Department → Group
- 각 수준에서 소유자 설정과 정책 적용 가능
- 상위 팀의 정책이 하위 팀에 상속

**사용자 관리**
- 사용자 초대: 이메일 초대 또는 SSO 연동으로 자동 프로비저닝
- 프로필: 이름, 이메일, 팀 소속, 역할
- 관리자(Admin)가 팀 배정, 역할 변경 가능

**소유권 (Ownership)**
- 모든 데이터 자산에 소유자(사용자 또는 팀) 지정
- 소유자는 해당 자산의 메타데이터 품질, 태그, 설명에 대한 1차 책임
- 소유자 미지정 자산을 대시보드에서 식별하여 할당 독려

---

### 5-2. 역할 & 정책 (RBAC)

#### 무엇인가

**역할 기반 접근 제어(Role-Based Access Control)**로, 사용자의 역할에 따라 데이터 자산과 기능에 대한 접근 권한을 세밀하게 제어한다.

#### 왜 필요한가

- **최소 권한 원칙**: 각 사용자에게 업무에 필요한 최소한의 권한만 부여
- **민감 데이터 보호**: PII, 재무 데이터 등에 대한 접근을 역할별로 제한
- **감사 추적**: 누가 어떤 권한으로 접근했는지 기록

#### 사용 방법

**기본 역할**

| 역할 | 권한 | 대상 사용자 |
|------|------|-------------|
| Admin | 모든 자산과 설정에 대한 전체 권한 | 시스템 관리자 |
| Data Steward | 메타데이터 편집, 용어집/태그 관리, 품질 테스트 설정 | 데이터 거버넌스 담당자 |
| Data Consumer | 읽기 전용, 대화/작업 참여 | 일반 분석가, 개발자 |

**커스텀 역할 생성**
- 기본 역할 외에 조직에 맞는 커스텀 역할 정의 가능
- 예: `NL2SQL Operator` — Gold 레이어 테이블만 조회 가능

**정책 (Policy) 기반 세분화된 접근 제어**

```mermaid
graph TB
    R[역할 Role] --> P[정책 Policy]
    P --> RULE1[규칙 1: 테이블 편집 허용]
    P --> RULE2[규칙 2: PII 태그 자산 조회 차단]
    P --> RULE3[규칙 3: Gold 레이어만 접근 허용]

    RULE1 --> |조건| COND1[소유한 자산만]
    RULE2 --> |조건| COND2[PII.Sensitive 태그]
    RULE3 --> |조건| COND3[DataLayer.gold 태그]

    style R fill:#bbdefb
    style P fill:#c8e6c9
```

- 정책은 **규칙(Rule)**의 집합
- 각 규칙: 리소스(table, topic, ...) + 동작(view, edit, delete, ...) + 조건(태그, 소유자, ...) + 효과(allow/deny)
- 정책을 역할에 연결하여 적용

**리소스 레벨 권한 설정**
- 개별 테이블, 파이프라인, 대시보드 단위로 세밀한 권한 설정
- 태그 기반 조건으로 동적 권한 부여 (예: `Tier.Tier1` 자산은 Admin만 수정 가능)

---

### 5-3. 봇 & API

#### 무엇인가

**서비스 계정(Bot)**을 통해 자동화 스크립트, 외부 도구가 OpenMetadata API에 접근하도록 하는 기능이다.

#### 왜 필요한가

- **자동화**: CI/CD 파이프라인, DAG에서 메타데이터를 프로그래밍 방식으로 관리
- **외부 연동**: Wren AI, dbt, 커스텀 도구 등과 메타데이터 동기화
- **보안**: 사용자 계정이 아닌 전용 서비스 계정으로 API 접근

#### 사용 방법

**서비스 계정 (Bot)**
- `ingestion-bot`: 기본 제공되는 수집용 봇 (메타데이터 수집 워크플로우에 사용)
- 커스텀 봇 생성 가능: 특정 용도에 맞는 최소 권한 봇
- 각 봇에 역할/정책 할당으로 접근 범위 제한

**JWT 인증**
- 봇 계정에 JWT 토큰을 발급하여 API 인증
- 토큰은 `.env` 파일 또는 시크릿 관리 시스템에서 주입
- 토큰 만료/갱신 관리

**REST API (전체 CRUD)**
- 모든 엔티티에 대한 CRUD 엔드포인트 제공
- Swagger UI로 API 문서 확인: `http://<host>:8585/swagger.html`

**Python SDK**
```python
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.generated.schema.entity.services.connections.metadata.openMetadataConnection import (
    OpenMetadataConnection,
)

server_config = OpenMetadataConnection(
    hostPort="http://localhost:8585/api",
    authProvider="openmetadata",
    securityConfig={"jwtToken": "<bot-jwt-token>"},
)
metadata = OpenMetadata(server_config)

# 테이블 조회
table = metadata.get_by_name(entity=Table, fqn="bip-postgres.stockdb.public.stock_info")

# 설명 업데이트
metadata.patch_description(entity=Table, source=table, description="종목 마스터 테이블")
```

---

### 5-4. 알림 설정

#### 무엇인가

데이터 자산의 **변경 이벤트를 감지하여 외부 채널로 알림**을 보내는 기능이다.

#### 왜 필요한가

- **변경 인식**: 스키마 변경, 소유자 변경, 품질 테스트 실패 등을 즉시 인지
- **사고 대응 시간 단축**: 데이터 품질 이슈 발생 시 빠른 알림으로 MTTR 감소
- **거버넌스 자동화**: 특정 이벤트 발생 시 자동으로 관련자에게 통지

#### 사용 방법

**연동 채널**

| 채널 | 설정 방법 |
|------|-----------|
| Slack | Webhook URL 등록, 채널 지정 |
| MS Teams | Webhook URL 등록 |
| Email | SMTP 설정 |
| Webhook | 커스텀 HTTP 엔드포인트 |
| Google Chat | Webhook URL 등록 |

**이벤트 기반 알림**

감지 가능한 이벤트 유형:
- 스키마 변경 (컬럼 추가/삭제/타입 변경)
- 소유자 변경
- 태그/용어 변경
- 품질 테스트 실패
- 파이프라인 상태 변경
- 대화/작업 멘션

필터 설정:
- 특정 서비스, 테이블, 파이프라인에 대해서만 알림
- 이벤트 유형별 필터링
- 소유자/팀 기반 알림 라우팅

---

## 6. 배포 옵션

### Docker Compose (개발/PoC)

**용도**: 로컬 개발, 기능 평가, PoC

```bash
# 최신 버전 실행
python -m pip install openmetadata-ingestion[docker]
metadata docker --start
```

구성 요소:
- openmetadata-server: API 서버 (8585 포트)
- openmetadata-ingestion: 수집 프레임워크
- mysql / postgresql: 메타데이터 저장소
- elasticsearch: 검색 엔진

장점: 빠른 시작, 단일 명령으로 전체 스택 실행
단점: 고가용성/확장성 미지원, 프로덕션 비권장

### Kubernetes (프로덕션)

**용도**: 프로덕션 환경, 고가용성 필요 시

- Helm Chart 제공: `open-metadata/openmetadata`
- 외부 데이터베이스(RDS, Cloud SQL) 연결 지원
- Elasticsearch/OpenSearch 클러스터 연결
- 수평 확장, 롤링 업데이트 지원
- Airflow 연동 옵션: 내장 Airflow 또는 외부 Airflow 사용

### Collate (관리형 SaaS)

**용도**: 운영 부담 최소화, 엔터프라이즈 기능 필요 시

- OpenMetadata 팀이 운영하는 관리형 서비스
- 자동 업그레이드, 백업, 모니터링 포함
- 추가 엔터프라이즈 기능: SSO, 세분화된 RBAC, 감사 로그 강화

---

## 7. API

### REST API 엔드포인트 개요

OpenMetadata는 모든 엔티티에 대해 일관된 REST API를 제공한다.

| 엔드포인트 | 설명 |
|------------|------|
| `GET /api/v1/tables` | 테이블 목록 조회 |
| `GET /api/v1/tables/name/{fqn}` | FQN으로 테이블 조회 |
| `PATCH /api/v1/tables/{id}` | 테이블 메타데이터 수정 (JSON Patch) |
| `PUT /api/v1/tags` | 태그 생성/수정 |
| `GET /api/v1/glossaries` | 용어집 목록 조회 |
| `PUT /api/v1/glossaryTerms` | 용어 생성/수정 |
| `PUT /api/v1/lineage` | 계보 엣지 추가 |
| `GET /api/v1/lineage/{entity}/{fqn}` | 계보 조회 |
| `GET /api/v1/services/databaseServices` | 데이터베이스 서비스 목록 |
| `GET /api/v1/search/query` | 통합 검색 |
| `GET /api/v1/feed` | 활동 피드 조회 |
| `PUT /api/v1/dataQuality/testCases` | 품질 테스트 케이스 생성 |

### 인증 방식

| 방식 | 설명 | 용도 |
|------|------|------|
| JWT | 봇 계정에 JWT 토큰 발급 | 자동화 스크립트, 수집 워크플로우 |
| SSO | Google, Azure AD, Okta, Auth0 등 | 사용자 로그인 |
| Basic Auth | 사용자명/비밀번호 | 개발 환경 (비권장) |

### Python SDK 사용법

`openmetadata-ingestion` 패키지는 REST API의 Python 래퍼를 제공한다.

**설치**
```bash
pip install openmetadata-ingestion
```

**기본 사용법**
```python
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.generated.schema.entity.data.table import Table
from metadata.generated.schema.type.tagLabel import TagLabel

# 연결 설정
metadata = OpenMetadata(server_config)

# 테이블 조회
table = metadata.get_by_name(entity=Table, fqn="bip-postgres.stockdb.public.stock_info")

# 테이블 목록
tables = metadata.list_entities(entity=Table, limit=100)

# 태그 추가
metadata.patch_tag(entity=Table, source=table, tag_label=TagLabel(
    tagFQN="DataLayer.gold",
    source="Classification",
))

# 계보 추가
from metadata.generated.schema.api.lineage.addLineage import AddLineageRequest
metadata.add_lineage(AddLineageRequest(edge=...))
```

**수집 워크플로우 프로그래밍 실행**
```python
from metadata.workflow.metadata import MetadataWorkflow

config = {
    "source": {"type": "postgres", "serviceName": "bip-postgres", ...},
    "sink": {"type": "metadata-rest", "config": {}},
    "workflowConfig": {"openMetadataServerConfig": {...}},
}
workflow = MetadataWorkflow.create(config)
workflow.execute()
workflow.print_status()
```

---

## 8. BIP-Pipeline에서의 활용 현황

BIP-Pipeline 프로젝트에서 OpenMetadata는 **메타데이터의 단일 진실 원천(SSOT)**으로 운용되고 있다. 메타데이터 편집은 OM에서만 수행하며, DB COMMENT와 Wren AI 모델은 파생본으로 자동 동기화된다.

### 인프라 구성

| 항목 | 값 |
|------|-----|
| 서버 주소 | `http://localhost:8585` (도커 네트워크: `http://openmetadata-server:8585`) |
| 데이터베이스 서비스 | `bip-postgres` (PostgreSQL, `stockdb`) |
| 파이프라인 서비스 | `bip-airflow` (Airflow) |
| 인증 | `ingestion-bot` JWT 토큰 (`OM_BOT_TOKEN`) |

### 등록된 자산 규모

| 자산 유형 | 수량 | 설명 |
|-----------|------|------|
| 테이블 | 39개 | Raw/Derived/Gold/Application 레이어 |
| 용어집 용어 | 77개 | 투자 용어, 매크로 경제 용어 등 |
| API 엔드포인트 | 14개 | 외부 데이터 소스 (Naver, DART, Yahoo 등) |
| 파이프라인 (DAG) | 43개 | Airflow DAG 전체 등록 |
| 태그 분류 | 2개 | `DataLayer` (raw/derived/gold), `Domain` (market/financial 등) |

### 메타데이터 동기화 흐름

```mermaid
graph LR
    OM["OpenMetadata<br/>(원천)"]

    subgraph "동기화 DAG: 10_sync_metadata_daily"
        SYNC1["om_sync_comments.py"]
        SYNC2["om_sync_wrenai.py"]
    end

    DB[(PostgreSQL<br/>DB COMMENT)]
    WREN[Wren AI<br/>모델 description]

    OM --> SYNC1 --> DB
    OM --> SYNC2 --> WREN

    style OM fill:#fff3e0,stroke:#e65100
```

- **`om_sync_comments.py`**: OM의 테이블/컬럼 설명을 PostgreSQL의 `COMMENT ON` 구문으로 동기화
- **`om_sync_wrenai.py`**: OM의 설명을 Wren AI의 모델 description에 반영하고 재배포(Deploy)

### 전체 Lineage 체계

외부 API에서 최종 소비자까지의 전체 데이터 계보가 OM에 등록되어 있다.

```mermaid
graph LR
    subgraph "외부 소스 (apiEndpoint)"
        S1[Naver Finance]
        S2[DART API]
        S3[Yahoo Finance]
        S4[ECOS BOK]
        S5[GDELT]
        S6[KRX]
    end

    subgraph "파이프라인 (DAG)"
        D1[01_info]
        D2[02_price]
        D3[05_financial]
        D4[04_macro]
        D5[09_analytics]
    end

    subgraph "테이블"
        T1[stock_info]
        T2[stock_price_1d]
        T3[financial_statements]
        T4[macro_indicators]
        T5[analytics_stock_daily]
    end

    subgraph "소비자"
        C1[morning_report]
        C2[Wren AI NL2SQL]
        C3[FastAPI]
    end

    S1 --> D1 & D2
    S2 --> D3
    S3 --> D2
    S4 --> D4
    S5 --> D4
    S6 --> D1

    D1 --> T1
    D2 --> T2
    D3 --> T3
    D4 --> T4
    T1 & T2 & T3 & T4 --> D5 --> T5

    T5 --> C1 & C2 & C3

    style T5 fill:#c8e6c9
```

리니지 등록 방식:
- **자동**: Airflow 커넥터가 DAG 정의를 파싱하여 파이프라인-테이블 간 계보 생성
- **프로그래밍**: `utils/lineage.py`의 `register_table_lineage_async()` 함수로 DAG 코드 내에서 계보 등록
- **외부 소스**: `scripts/om_register_data_sources.py`로 apiEndpoint → DAG 계보 엣지 생성

### 커넥터 설정 파일

프로젝트의 OM 커넥터 설정은 `openmetadata/connectors/` 디렉토리에 관리된다:

| 파일 | 용도 |
|------|------|
| `bip_postgres.yaml` | PostgreSQL 스키마 스캔 (테이블/컬럼 메타데이터 수집) |
| `bip_profiler.yaml` | 프로파일러 (컬럼 통계 수집) |
| `bip_airflow.yaml` | Airflow DAG 메타데이터 및 계보 수집 |

### 프로파일러 보안 설정

보안 거버넌스(`docs/security_governance.md`)에 따라 프로파일러는 엄격하게 설정되어 있다:

- **`includeColumnSample: false`**: 실제 데이터 행(sample row)은 수집하지 않음
- **`generateSampleData: false`**: 샘플 데이터 생성 비활성화
- **통계만 수집**: `computeMetrics`, `computeTableMetrics`, `computeColumnMetrics`만 활성화
- **민감 테이블 제외**: `tableFilterPattern.excludes`에 민감 테이블 명시

제외된 민감 테이블:
- `portfolio`, `users`, `user_watchlist`, `holding`, `transaction`, `cash_transaction`
- `portfolio_snapshot` (파생이지만 사용자 재무 상태 노출)
- `monitor_alerts`

민감 컬럼 패턴 제외:
- `*_secret`, `*_key`, `*_token`, `*_password`, `email`, `phone`, `account_number`

### 자동화 스크립트

| 스크립트 | 용도 |
|----------|------|
| `scripts/om_build_glossary.py` | 용어집 일괄 생성/업데이트 |
| `scripts/om_tag_tables.py` | 테이블에 DataLayer/Domain 태그 일괄 적용 |
| `scripts/om_link_columns.py` | 용어집 용어를 컬럼에 매핑 |
| `scripts/om_enrich_metadata.py` | 컬럼 설명 일괄 보강 |
| `scripts/om_register_data_sources.py` | 외부 API 소스를 apiEndpoint로 등록 + 계보 연결 |
| `scripts/om_sync_comments.py` | OM 설명 → PostgreSQL DB COMMENT 동기화 |
| `scripts/om_sync_wrenai.py` | OM 설명 → Wren AI 모델 description 동기화 |

### 태그 분류 체계

**DataLayer 분류**
- `DataLayer.raw`: 원천 데이터 (stock_info, stock_price_1d, financial_statements 등)
- `DataLayer.derived`: 파생/계산 (stock_indicators, market_daily_summary 등)
- `DataLayer.gold`: 서빙용 통합 (analytics_stock_daily, analytics_valuation 등)
- `DataLayer.application`: 애플리케이션 (monitor_checklist, agent_audit_log 등)

**Domain 분류**
- `Domain.market`: 시장 데이터 (주가, 종목 정보)
- `Domain.financial`: 재무 데이터 (재무제표, 밸류에이션)
- `Domain.macro`: 거시경제 (금리, 환율, 지정학)
- `Domain.news`: 뉴스 데이터
- `Domain.portfolio`: 포트폴리오 (민감)
- `Domain.product`: 제품 가격
- `Domain.user`: 사용자 (민감)

### NL2SQL 연계

OM의 메타데이터 품질이 NL2SQL 정확도에 직접 영향을 미친다. 실제 테스트에서 Gold 컬럼 설명 커버리지를 31%에서 99%로 올린 결과, NL2SQL A등급이 58%에서 77%로 상승한 사례가 있다.

OM → Wren AI 동기화 체인:
1. OM에서 테이블/컬럼 설명 편집 (원천)
2. `10_sync_metadata_daily` DAG가 `om_sync_wrenai.py` 실행
3. Wren AI 모델 description에 반영 + Qdrant 임베딩 재배포
4. NL2SQL 질문 시 업데이트된 메타데이터 기반으로 SQL 생성

---

## 9. 참고

### 공식 자료

| 자료 | URL |
|------|-----|
| 공식 문서 | https://docs.open-metadata.org |
| GitHub | https://github.com/open-metadata/OpenMetadata |
| Slack 커뮤니티 | https://slack.open-metadata.org |
| Swagger API 문서 | `http://<host>:8585/swagger.html` |
| YouTube 채널 | https://www.youtube.com/@OpenMetadata |
| 릴리즈 노트 | https://github.com/open-metadata/OpenMetadata/releases |

### BIP-Pipeline 내부 문서

| 문서 | 설명 |
|------|------|
| `docs/metadata_governance.md` | 메타데이터 거버넌스 정책 (필수 준수) |
| `docs/security_governance.md` | 보안 거버넌스 (프로파일러 설정, 민감 테이블 정책) |
| `docs/data_architecture_review.md` | 전체 아키텍처, 테이블 카탈로그, Lineage 적용 범위 |
| `docs/wrenai_technical_guide.md` | Wren AI와 OM 간 메타데이터 동기화 상세 |
| `docs/nl2sql_project_plan.md` | NL2SQL 설계에서 OM 메타데이터 의존성 |
| `openmetadata/connectors/` | OM 커넥터 설정 파일 (postgres, profiler, airflow) |
| `scripts/om_*.py` | OM 자동화 스크립트 모음 |

### 버전 정보

- OpenMetadata: v1.x (Docker Compose 배포)
- Python SDK: `openmetadata-ingestion` (pip)
- BIP-Pipeline OM 구성: 39 테이블, 77 용어, 14 apiEndpoint, 43 DAG

---

## 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-04-13 | 초안 작성 |
| 2026-04-22 | 문서 헤더 정리 (작성일/대상 제거) |
