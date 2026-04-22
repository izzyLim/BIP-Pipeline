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
- 분량: 600-900줄
- Mermaid 다이어그램: 최소 3개 (아키텍처, 데이터 흐름, 개념 관계)
- 코드 예시: 복사-붙여넣기 가능한 완전한 예시 (docker-compose.yml, 설정 파일 등)
- 각 기능마다: **무엇(what)**, **왜 필요(why)**, **사용 방법(how)** 구조
- 비교표: 유사 도구와 비교 (해당 시)
- BIP 경험 매핑: 기존 프로젝트와의 연관성 (해당 시)

**문서 헤더 템플릿:**
```markdown
# <도구명> 개념 및 사용 가이드

> **공식 문서:** <URL>
> **GitHub:** <URL>
> **라이선스:** <라이선스>
> **작성일:** <날짜>
```

### Step 4: HTML 변환

Python markdown 라이브러리로 HTML 변환:

```python
import markdown
# fenced_code, tables, codehilite, toc 확장 사용
# Mermaid 코드 블록 → <div class="mermaid"> 변환
# 표준 CSS 스타일 적용 (Pretendard 폰트, 다크/라이트 테이블, 코드 하이라이트)
```

생성 위치:
- `docs/html/guide_<주제>.html` (BIP-Pipeline repo)
- `/Users/yeji/Projects/docs/guide_<주제>.html` (Docs repo에 복사)

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

## 품질 기준

- [ ] 600줄 이상
- [ ] Mermaid 다이어그램 3개 이상
- [ ] Docker 설치 예시 포함 (해당 시)
- [ ] API 요청/응답 예시 포함 (해당 시)
- [ ] 공식 문서 URL 포함
- [ ] 코드 예시는 복사-붙여넣기 가능
- [ ] HTML 변환 + Docs repo 배포 완료
- [ ] index.html 업데이트 완료
