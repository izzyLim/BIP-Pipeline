---
name: write-doc
description: 기술 문서를 표준 포맷으로 작성하고 HTML 변환 + Docs repo 배포까지 자동화
user-invocable: true
---

# 기술 문서 작성 스킬

사용자가 `/write-doc <주제>` 형태로 호출하면, 표준 포맷에 맞춰 상세 기술 문서를 작성하고 HTML 변환 + Docs repo 배포까지 수행한다.

## 실행 절차

### Step 1: 포맷 레퍼런스 확인

기존 잘 작성된 문서의 구조를 참조한다. 대표 레퍼런스:
- `/Users/yeji/Projects/BIP-Pipeline/docs/guide_cubejs.md` (800줄, 11섹션)
- `/Users/yeji/Projects/BIP-Pipeline/docs/guide_openmetadata.md` (1114줄, 9섹션)

이 문서들의 공통 구조:
```
1. 개요 (정의, 핵심 가치, 라이선스)
2. 아키텍처 (mermaid diagram, 컴포넌트 설명)
3. 핵심 개념 (각 개념별 상세 + 코드 예시)
4. 데이터 소스 / 연결 설정
5. API (REST/GraphQL, 요청/응답 예시)
6. Docker 컨테이너 설치 (docker-compose.yml 전체 예시)
7. 사용법 / 모델 작성법 (실전 예시)
8. NL2SQL / BIP 경험 연동 (해당 시)
9. 주의사항 및 한계
10. BIP-Pipeline 현재 설정 (해당 시)
11. 참고 (공식 문서, GitHub, 관련 내부 문서)
```

### Step 2: 주제 조사

WebFetch로 해당 도구/기술의 공식 문서를 조사한다:
- 공식 문서 메인 페이지
- 설치/Quick Start 페이지
- 핵심 개념/Features 페이지
- API 레퍼런스
- GitHub README

최소 5개 이상의 공식 페이지를 읽어야 한다.

### Step 3: 문서 작성

**파일명:** `docs/guide_<주제>.md` (소문자, 언더스코어)

**작성 규칙:**
- 언어: 한국어
- 분량: 1000-1500줄 (코드만 많은 짧은 가이드 금지)
- Mermaid 다이어그램: 최소 7개 (아키텍처, 동작 원리, 컴포넌트 관계, 시퀀스, 비교 등)
- 코드 예시: 복사-붙여넣기 가능한 완전한 예시 (docker-compose.yml, 설정 파일 등)
- 비교표: 유사 도구와 비교 (해당 시)
- BIP 경험 매핑: 기존 프로젝트와의 연관성 (해당 시)

**작성 원칙 — 설명 위주 (코드만 나열 금지):**

1. **비유로 시작하라**
   - "이 도구는 ~~와 같다" 식으로 직관적 이해를 먼저 만든다
   - 예: "Cube.js는 BI 메트릭의 표준화 레이어 (도서관 분류 체계와 같음)"
   - 예: "OpenMetadata는 데이터의 Wikipedia/도서관 사서"
   - 예: "Wren AI는 자연어 → SQL 통역사 + 시맨틱 레이어 통합기"

2. **Why → What → How 순서**
   - 코드를 보여주기 **전에** 반드시 "왜 필요한가"부터 설명
   - "왜 이걸 쓰지 않으면 문제가 되는가" 시나리오 제시
   - 그 다음 "무엇인가" 정의
   - 마지막에 "어떻게 쓰는가" 코드/설정

3. **코드 위 설명 박스 필수**
   - 모든 코드 블록 직전에 인용구 1-2문장:
     ```markdown
     > **이 코드가 하는 일:** ...
     ```
   - 코드만 있고 설명이 없으면 안 된다

4. **함정 박스 ⚠️ 다수 추가 (5개 이상)**
   - "이렇게 하면 안 된다" 명시
   - BIP 경험에서 발견된 실제 함정 우선
   - 형식:
     ```markdown
     > ⚠️ **함정 — 짧은 제목**: 설명
     ```

5. **실무 팁 박스 💡 다수 추가 (5개 이상)**
   - "실무에서는 이렇게 한다" 노하우
   - 형식:
     ```markdown
     > 💡 **실무 팁 — 짧은 제목**: 설명
     ```

6. **현실적 사례 우선**
   - 추상적 설명보다 "실무에서 이런 상황에 쓴다" 시나리오
   - 가능하면 BIP 실제 경험 인용 (예: "BIP에서 boolean flag 0% → 87% 개선")

**금지 사항:**
- ❌ 코드만 나열하고 설명 없는 섹션
- ❌ "사용법"이라며 코드 블록만 던지기
- ❌ 비유/맥락 없이 바로 기술 개념 설명
- ❌ 함정/실수 포인트 누락 (도구 장점만 나열)

**문서 구조 패턴:**
```
1. 개요 — 비유 + 핵심 가치
2. 핵심 가치 / 왜 필요한가 — 4가지 시나리오
3. 아키텍처 — mermaid + 단계별 설명
4. 핵심 개념 — 각 개념마다 (비유 → Why → What → How → 예시 + 함정/팁)
5. 데이터 소스 / 연결
6. API
7. 설치 / 배포
8. 실전 사용법
9. 다른 도구와 비교 (해당 시)
10. 알려진 한계 + 함정 정리
11. BIP 적용 (해당 시)
12. 참고
13. 변경 이력
```

**문서 헤더 템플릿 (간결하게):**
```markdown
# <도구명> 개념 및 사용 가이드

> **공식 문서:** <URL>
```

**문서 맨 아래 — 변경 이력 (필수):**
```markdown
---

## 변경 이력

| 날짜 | 내용 |
|------|------|
| YYYY-MM-DD | 초안 작성 |
```

**주의:**
- 헤더에 작성일/대상/목적 등 불필요한 메타데이터를 넣지 않는다
- 날짜는 변경 이력 테이블에서만 관리한다

### Step 4: HTML 변환

**반드시 `scripts/md_to_html.py`를 사용한다.** 직접 HTML을 생성하지 않는다.

```bash
python3 scripts/md_to_html.py docs/guide_<주제>.md docs/html/guide_<주제>.html
```

이 스크립트는 다음을 자동 처리:
- 사이드바 목차 (TOC) 자동 생성
- 다크/라이트 테마 전환 버튼
- Mermaid 다이어그램 렌더링 (codehilite 충돌 방지, subgraph 자동 색상 분배)
- 스크롤 위치 하이라이트
- 반응형 모바일 대응

생성 후 Docs repo에 복사:
```bash
cp docs/html/guide_<주제>.html /Users/yeji/Projects/docs/
```

### Step 5: index.html 업데이트

`/Users/yeji/Projects/docs/index.html`의 적절한 섹션에 추가:

```html
<li><a class="card" href="guide_<주제>.html">
  <span class="card-title"><도구명> 사용 가이드</span>
  <span class="card-sep">—</span>
  <span class="card-desc"><한줄 설명></span>
</a></li>
```

배지 숫자도 업데이트한다.

### Step 6: 커밋 + 푸시

**BIP-Pipeline repo:**
```bash
cd /Users/yeji/Projects/BIP-Pipeline
git add docs/guide_<주제>.md docs/html/guide_<주제>.html
git commit -m "docs: <도구명> 상세 가이드 신규"
git push
```

**Docs repo:**
```bash
cd /Users/yeji/Projects/docs
git add guide_<주제>.html index.html
git commit -m "docs: <도구명> 가이드 추가"
git push
```

### Step 7: 완료 보고

작성된 문서의 요약을 사용자에게 보고:
- 파일 경로
- 줄 수
- 포함된 섹션 목록
- Mermaid 다이어그램 수
- 배포 상태

---

## 기존 문서 업데이트 절차

사용자 요청에 기존 파일명이 언급되거나, 기존 문서에 내용 추가/수정을 요청하면 이 절차를 따른다.

### 판단 기준
- 새 주제 (예: "Neo4j 가이드 작성") → 신규 (위의 절차)
- 기존 파일명 언급 (예: "guide_cubejs에 ~~ 추가") → 업데이트
- 파일명 없이 맥락 기반 (예: "지금 논의한 내용 문서에 업데이트 해줘") → 대화 맥락에서 관련 문서를 판단하여 업데이트. 여러 문서에 걸치면 각각 업데이트.

**맥락 기반 판단 방법:**
1. 현재 대화에서 논의한 주제 파악
2. `docs/` 디렉토리에서 관련 문서 탐색 (Grep/Glob)
3. 해당 문서에 이미 있는 내용인지 확인
4. 없으면 추가, 있으면 수정

### 업데이트 Step 1: 기존 문서 읽기
해당 .md 파일을 읽고 현재 구조를 파악한다.

### 업데이트 Step 2: 내용 수정
- 기존 섹션에 추가: 해당 섹션 찾아서 내용 삽입
- 새 섹션 추가: 적절한 위치에 섹션 추가
- 내용 수정: 기존 내용 교체
- 삭제 요청: 해당 내용 제거

### 업데이트 Step 3: 변경 이력 추가
문서 맨 아래 "변경 이력" 테이블에 행 추가:
```markdown
| YYYY-MM-DD | 변경 내용 간략 설명 |
```

### 업데이트 Step 4: HTML 재생성 + 배포
```bash
python3 scripts/md_to_html.py docs/<파일>.md docs/html/<파일>.html
cp docs/html/<파일>.html /Users/yeji/Projects/docs/
```

### 업데이트 Step 5: 커밋 + 푸시
BIP-Pipeline repo + Docs repo 양쪽 모두.

---

## 품질 기준

### 신규 문서
- [ ] 1000줄 이상 (코드만 많으면 안 됨)
- [ ] Mermaid 다이어그램 7개 이상
- [ ] **모든 핵심 개념에 비유 포함** (도구를 처음 쓰는 사람도 이해 가능)
- [ ] **Why → What → How 순서** 준수 (코드 전에 반드시 시나리오/맥락)
- [ ] **모든 코드 블록 위에 설명 인용구** (`> 이 코드가 하는 일:`)
- [ ] **함정 박스 ⚠️ 5개 이상**
- [ ] **실무 팁 박스 💡 5개 이상**
- [ ] Docker 설치 예시 포함 (해당 시)
- [ ] API 요청/응답 예시 포함 (해당 시)
- [ ] 공식 문서 URL 포함
- [ ] 코드 예시는 복사-붙여넣기 가능
- [ ] 변경 이력 섹션 포함
- [ ] HTML 변환 + Docs repo 배포 완료
- [ ] index.html 업데이트 완료

### 기존 문서 업데이트
- [ ] 변경 이력 테이블에 행 추가
- [ ] HTML 재생성
- [ ] Docs repo 배포 완료
