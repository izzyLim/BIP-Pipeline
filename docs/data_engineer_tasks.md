# 데이터 엔지니어 작업 요청서

> 데이터 분석 과정에서 발견된 파이프라인 결함 및 개선 요청 사항을 정리한 문서입니다.
> 작업 완료 시 상태를 업데이트해 주세요.

**작성일**: 2026-03-21
**전달일**: 2026-03-21
**작성자**: 데이터 분석팀

---

## 요청 목록 요약

| # | 제목 | 우선순위 | 난이도 | 상태 |
|---|------|---------|--------|------|
| [DE-001](#de-001-재무제표-수집-dag-api-호출량-초과-문제-해결-긴급) | 재무제표 수집 DAG API 호출량 초과 해결 | **긴급** | 하 | ✅ 완료 (2026-03-22) |
| [DE-002](#de-002-컨센서스-수집-dag-자동화) | 컨센서스 수집 DAG 자동화 | 높음 | 하 | ✅ 완료 (2026-03-23) |
| [DE-003](#de-003-기관-세부-수급-및-공매도-데이터-수집) | 기관 세부 수급 + 공매도 데이터 수집 | 중간 | 중 | 전달완료 (2026-03-21) |
| [DE-004](#de-004-미국-종목-펀더멘털-수집-추가) | 미국 종목 펀더멘털 수집 추가 | 중간 | 하 | 전달완료 (2026-03-21) |
| [DE-005](#de-005-analytics-파생-지표-테이블-구축) | Analytics 파생 지표 테이블 구축 | 중간 | 중 | 전달완료 (2026-03-21) |
| [DE-006](#de-006-네이버-스크래핑-의존도-리스크-대응) | 네이버 스크래핑 의존도 리스크 대응 | 낮음 | 중 | 전달완료 (2026-03-21) |

---

## DE-001: 재무제표 수집 DAG API 호출량 초과 문제 해결 (긴급)

> ⚠️ 초기 요청 내용("커버리지 확대") 수정. 실제 확인된 문제는 API 한도 초과임.

### 배경 및 실제 문제

- `company_dart_info`: **2,661개** (수동 스크립트로 채워진 상태)
- `collect_financial_statements()` task는 `company_dart_info` 전체를 처리
- 주간 DAG 실행 시 예상 호출량: **2,661 × 4 × 5 = 53,220건/주**
- DART API 일일 한도 **10,000건** 대비 최대 5배 초과
- 실행 소요 시간: 약 **14.8시간** → 주간 실행 주기(7일)와 충돌 위험

```
[현재 구조 - 문제]
company_dart_info: 2,661개
collect_financial_statements(): 전체 2,661개 × 4보고서 × 5년 처리 시도
→ DART API 한도 초과, 실행시간 초과 위험

[목표 구조]
한도 내에서 중요 종목 우선 갱신 + 나머지는 분리 처리
```

### 요청 작업

**Option A (단기, 즉시 적용)**: 수집 기간 단축

`collect_financial_statements()` 내 `years_to_fetch = 5` → `years_to_fetch = 2` 변경
- 2,661 × 4 × 2 = 21,288건/주 (CFS+OFS 최대 42,576건)
- 실행시간 약 5.9시간으로 단축
- 5년치 이전 데이터는 이미 적재되어 있으므로 실질적 손실 없음

**Option B (권장)**: 시총 우선순위 + 수집 기간 단축 병행

`collect_financial_statements()` 쿼리를 아래처럼 수정:

```python
cursor.execute("""
    SELECT d.ticker, d.corp_code, d.corp_name
    FROM company_dart_info d
    LEFT JOIN stock_info s ON d.ticker = s.ticker
    WHERE d.corp_code IS NOT NULL
    ORDER BY s.market_value DESC NULLS LAST
    LIMIT 500
""")
# years_to_fetch = 2 로 변경
```

- 500 × 4 × 2 = 4,000건/주 → DART 한도 내 안전
- 나머지 2,161개는 별도 월간 DAG로 처리

**Option C (근본 해결, 중장기)**: DART 증분 수집

- DART `list` API로 최신 공시 목록 조회
- 마지막 수집 이후 새로 공시된 보고서만 처리
- 호출량 최소화, 구현 복잡도 높음

### DART API 호출량 비교

| 방안 | 주간 호출량 (CFS만) | CFS+OFS 최대 | 일평균 |
|------|-------------------|-------------|-------|
| 현재 (2,661 × 4 × 5) | 53,220건 | 106,440건 | **초과** |
| Option A (2,661 × 4 × 2) | 21,288건 | 42,576건 | 6,082건 ✓ |
| Option B (500 × 4 × 2) | 4,000건 | 8,000건 | 1,143건 ✓✓ |

### 적용된 구현 내용 (2026-03-22 완료)

파일: `airflow/dags/stock_loader/dag_financial_statements.py`

1. **시총 순 정렬 + 30일 내 갱신 종목 스킵** (143~157행)
   - `company_dart_info` LEFT JOIN `stock_info` → `market_value DESC` 정렬
   - `financial_statements.updated_at > NOW() - INTERVAL '30 days'` 종목 제외
   - 효과: 이미 최신 상태인 종목 재수집 방지, 시총 대형주 우선 처리

2. **수집 기간 단축** (166행)
   - `years_to_fetch = context.get("years_to_fetch", 2)` — 주간 DAG 기본값 5→2

3. **수동 백필 DAG 분리** (285행)
   - `05_kr_financial_stmt_manual` DAG에 `op_kwargs={"years_to_fetch": 5}` 부여
   - 전체 히스토리 재수집 필요 시 수동 트리거로 분리

### 수정 후 예상 호출량

| 상태 | 예상 호출량 |
|------|-----------|
| 수정 전 | 최대 106,440건/주 (한도 초과) |
| 수정 후 첫 실행 | 최대 42,576건/주 (5.9시간) |
| 수정 후 이후 실행 | 신규 공시분만, 대폭 감소 |

### 검수 기준

- [ ] DAG 첫 실행 완료 시간 7시간 이내 확인
- [ ] DART API 일일 호출량 10,000건 미만 확인 (Airflow 로그)
- [ ] 시총 상위 종목 최신 분기 데이터 갱신 확인
- [ ] 두 번째 실행부터 30일 필터 동작으로 실행시간 단축 확인

### 잔여 과제

- 첫 실행 시 2,661개 전체 대상으로 여전히 한도 초과 가능성 있음
- 근본 해결책(DART `list` API 기반 증분 수집) 중장기 검토 필요

---

## DE-002: 컨센서스 수집 DAG 자동화

**업데이트**: 2026-03-23 (현황 분석 후 요청 내용 구체화)

### 현황 파악 (2026-03-23 기준)

- 수동 스크립트 최근 실행: 2026-03-13, 2026-03-14 (2회)
- 수집 결과: 835개 대상 → **301개 성공**, 534개 SKIP (애널리스트 커버리지 없음)
- 현재 DB: 561개 종목, 832건 (2025년 추정치 311건 + 2026년 추정치 521건)
- 실행 소요 시간: **약 6분** (부담 없음)
- `consensus_history` 테이블: 존재하나 수동 실행 시 미연동 상태 (2026-03-22 557건만 존재)

### 요청 작업

#### Task 1. `collect_consensus.py` → Airflow DAG 전환

| 항목 | 내용 |
|------|------|
| DAG ID | `05_kr_consensus_weekly` |
| 스케줄 | 매주 화요일 19:00 KST |
| 수집 대상 | `stock_info`에서 active=true인 전체 KR 종목 (`.KS`, `.KQ`) |
| 소요 시간 | 약 6분 (835종목 × 0.5초 딜레이) |
| 기존 코드 | `collect_consensus.py` 그대로 사용, DAG wrapper만 추가 |

수집 대상 쿼리 (기존 INNER JOIN 제거, 전체 스캔으로 변경):
```sql
SELECT ticker, stock_name
FROM stock_info
WHERE (ticker LIKE '%.KS' OR ticker LIKE '%.KQ')
  AND active = true
ORDER BY market_value DESC NULLS LAST
```
→ 기존 INNER JOIN 방식은 재무제표 없는 종목을 원천 제외했으나,
  실제로는 신규 상장 등 재무제표 미적재 상태에서도 컨센서스가 있는 종목이 존재할 수 있음.
  데이터 없으면 기존 로직대로 자동 SKIP되므로 부작용 없음.

#### Task 2. `consensus_history` 연동 추가 (핵심 요청)

수집 시마다 `consensus_estimates` UPSERT 외에 **`consensus_history`에도 INSERT** 추가.
목표주가 revision momentum 분석을 위해 반드시 필요.

```sql
-- 매 수집마다 INSERT (UPSERT 아님 — 변경 이력 보존이 목적)
INSERT INTO consensus_history (
    ticker, stock_code, collected_date, estimate_year,
    rating, target_price, analyst_count,
    est_eps, est_per, est_revenue, est_operating_profit, est_net_income,
    data_source
)
VALUES (...)
-- ON CONFLICT 없음 — 동일 종목이라도 수집일마다 새 레코드
```

`consensus_history` 테이블 스키마 확인: `(ticker, collected_date, estimate_year)` 조합으로 중복 방지 인덱스 추가 권고.

#### Task 3. 수동 백필 DAG 분리

| DAG ID | 스케줄 | 용도 |
|--------|--------|------|
| `05_kr_consensus_weekly` | 매주 화요일 19:00 | 정기 갱신 |
| `05_kr_consensus_manual` | 수동 트리거 | 전체 재수집, 긴급 갱신 |

### 데이터 흐름

```
매주 화요일 19:00
  → stock_info 전체 KR 종목 조회 (835개 내외)
  → WiseReport + FnGuide 스크래핑 (약 6분)
  → consensus_estimates UPSERT  ← 현재 최신값 유지
  → consensus_history INSERT    ← 변경 이력 누적 (신규 추가)
  → 수집 결과 로그 (성공/스킵/에러 건수)
```

### 검수 기준

- [ ] 매주 화요일 19:00 자동 실행 확인
- [ ] `consensus_estimates.updated_at` 300개 이상 최신화 확인
- [ ] `consensus_history`에 수집일 기준 신규 레코드 300개 이상 INSERT 확인
- [ ] 2회 이상 실행 후 `consensus_history`에 날짜별 이력 누적 확인
- [ ] 실패 시 Airflow 이메일 알림 동작 확인

---

## DE-003: 기관 세부 수급 및 공매도 데이터 수집

### 배경 및 문제

현재 `stock_price_1d`에는 외국인/기관 순매수 합계만 존재.
투자 분석에서 **연기금 순매수**는 중장기 방향성 신호로 신뢰도가 매우 높으며,
**공매도 잔고 비율**은 투자심리 및 단기 수급 판단에 필수적.

### 요청 작업

#### 3-1. KRX 기관 세부 수급 수집

- 데이터 소스: KRX 데이터포털 (`data.krx.co.kr`) — 무료 API 제공
- 수집 항목: 연기금, 투신, 사모펀드, 은행, 보험, 기타금융
- 저장 테이블: `investor_trend_detail` (신규 생성)
- 스케줄: 평일 17:30 KST (현재 `05_kr_investor_trend` 이후)

```sql
-- 신규 테이블 스키마 (예시)
CREATE TABLE investor_trend_detail (
    ticker          VARCHAR(20),
    trade_date      DATE,
    pension_fund    BIGINT,   -- 연기금 순매수
    trust           BIGINT,   -- 투신
    private_fund    BIGINT,   -- 사모
    bank            BIGINT,   -- 은행
    insurance       BIGINT,   -- 보험
    other_finance   BIGINT,   -- 기타금융
    updated_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ticker, trade_date)
);
```

#### 3-2. 공매도 잔고 수집

- 데이터 소스: KRX 공매도 종합포털 또는 데이터포털
- 수집 항목: 공매도 잔고 수량, 잔고 금액, 잔고 비율(%)
- 저장 테이블: `short_selling` (신규 생성)
- 스케줄: 평일 18:00 KST (T+1 공시 기준)

```sql
-- 신규 테이블 스키마 (예시)
CREATE TABLE short_selling (
    ticker              VARCHAR(20),
    trade_date          DATE,
    short_balance       BIGINT,       -- 공매도 잔고 수량
    short_balance_amt   BIGINT,       -- 공매도 잔고 금액 (원)
    short_balance_ratio DECIMAL(6,2), -- 잔고 비율 (%)
    updated_at          TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ticker, trade_date)
);
```

### 검수 기준

- [ ] 삼성전자, SK하이닉스 등 주요 종목 기관 세부 수급 데이터 적재 확인
- [ ] 공매도 잔고 비율이 KRX 공시 수치와 일치 확인 (5개 종목 샘플)
- [ ] 주말/공휴일 수집 스킵 로직 동작 확인

---

## DE-004: 미국 종목 펀더멘털 수집 추가

### 배경 및 문제

NASDAQ/NYSE 종목은 일봉 시세와 기술지표만 수집 중.
밸류에이션(P/E, EV/EBITDA), 재무제표, 애널리스트 컨센서스 없이는
**한국 종목과 동일한 수준의 분석이 불가능**.

### 요청 작업

`yfinance`의 `Ticker` 객체를 활용한 미국 종목 펀더멘털 수집 DAG 추가:

- DAG ID: `05_us_fundamentals_weekly`
- 스케줄: 매주 토요일 06:00 KST (미국 시장 마감 후)
- 수집 대상: `stock_info`에서 `.` 없는 ticker (NASDAQ/NYSE)
- 수집 항목:

```python
ticker = yf.Ticker("AAPL")

# 밸류에이션
ticker.info["trailingPE"]       # P/E
ticker.info["priceToBook"]      # P/B
ticker.info["enterpriseToEbitda"]  # EV/EBITDA
ticker.info["targetMeanPrice"]  # 애널리스트 평균 목표주가
ticker.info["recommendationMean"]  # 투자의견 점수

# 재무제표 (연간)
ticker.financials     # 손익계산서
ticker.balance_sheet  # 재무상태표
ticker.cashflow       # 현금흐름표
```

- 저장 테이블: 기존 `financial_statements`에 저장 (ticker 기준 호환)
- 밸류에이션은 `consensus_estimates` 또는 별도 `us_valuation` 테이블

### 검수 기준

- [ ] AAPL, NVDA, MSFT 등 10개 종목 재무제표 적재 확인
- [ ] P/E, 목표주가가 Yahoo Finance 웹과 일치 확인
- [ ] yfinance 오류(rate limit 등) 시 재시도 로직 동작 확인

---

## DE-005: Analytics 파생 지표 테이블 구축

### 배경 및 문제

현재 각 테이블(`stock_price_1d`, `financial_statements`, `consensus_estimates`)은
독립적으로 적재되고 cross-table 분석 지표가 전혀 없음.
분석 레이어에서 매번 조인 쿼리를 작성해야 하며, 성능 및 일관성 문제 발생 가능.

### 요청 작업

`analytics_*` 테이블 군을 신규 생성하고, 매일 새벽 사전 계산:

#### 5-1. `analytics_valuation` — 밸류에이션 종합

```sql
CREATE TABLE analytics_valuation (
    ticker              VARCHAR(20),
    base_date           DATE,
    -- 현재 시세
    close_price         BIGINT,
    market_cap          BIGINT,
    -- 재무 기반 계산
    per_trailing        DECIMAL(10,2),  -- 실적 기반 PER
    pbr                 DECIMAL(10,2),
    psr                 DECIMAL(10,2),
    -- 컨센서스 기반
    per_forward         DECIMAL(10,2),  -- 예상 EPS 기반 PER
    consensus_target    BIGINT,         -- 애널리스트 평균 목표주가
    upside_pct          DECIMAL(8,2),   -- 목표주가 대비 괴리율(%)
    analyst_count       INT,
    updated_at          TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ticker, base_date)
);
```

#### 5-2. `analytics_earnings_surprise` — 실적 서프라이즈

```sql
CREATE TABLE analytics_earnings_surprise (
    ticker              VARCHAR(20),
    fiscal_year         INT,
    fiscal_quarter      INT,
    -- 실제 실적 (DART)
    actual_revenue      BIGINT,
    actual_op_profit    BIGINT,
    actual_net_income   BIGINT,
    -- 컨센서스 추정 (수집 시점 기준)
    est_revenue         BIGINT,
    est_op_profit       BIGINT,
    est_net_income      BIGINT,
    -- 서프라이즈 계산
    revenue_surprise_pct    DECIMAL(8,2),
    op_profit_surprise_pct  DECIMAL(8,2),
    updated_at          TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ticker, fiscal_year, fiscal_quarter)
);
```

#### 5-3. DAG 구성

- DAG ID: `09_analytics_daily`
- 스케줄: 매일 01:00 KST (전일 데이터 기준)
- Task 순서: valuation 계산 → earnings_surprise 계산 → (향후) 기술지표 복합신호

### 검수 기준

- [ ] 삼성전자의 `upside_pct`가 수동 계산값과 일치 확인
- [ ] `earnings_surprise_pct`가 (실제 - 추정) / |추정| 공식으로 계산됨 확인
- [ ] DAG 실행 시간 30분 이내 완료 확인

---

## DE-006: 네이버 스크래핑 의존도 리스크 대응

### 배경 및 문제

현재 네이버 금융 스크래핑에 의존하는 데이터:
- `stock_info` (종목 메타데이터, 시가총액)
- `investor_trend` (외국인/기관 순매수)
- `kr_sectors` (업종별 등락률)
- `consensus_estimates` (WiseReport/FnGuide)

네이버 금융 페이지 구조 변경 시 위 항목이 **전면 장애** 가능. 이미 WiseReport 셀렉터 변경 전례 있음.

### 요청 작업

단기 리스크 완화 목적의 대체 소스 파악 및 일부 전환:

| 현재 소스 | 대체 소스 후보 | 우선도 |
|---------|--------------|-------|
| 네이버 금융 종목 정보 | KRX Open API (`data.krx.co.kr`) | 높음 |
| 네이버 투자자 수급 | KRX 데이터포털 API | 높음 (DE-003과 병행) |
| WiseReport 컨센서스 | FnGuide 직접 연동 또는 유료 API 검토 | 중간 |
| 업종 등락률 | KRX 업종지수 API | 낮음 |

**즉시 요청**: KRX Open API 가입 및 API Key 발급 후 종목 정보/수급 엔드포인트 테스트
- KRX 데이터포털: `data.krx.co.kr`
- 주요 API: 주식 기본정보, 투자자별 거래실적, 업종별 현황

### 검수 기준

- [ ] KRX API로 삼성전자 당일 외국인 순매수 조회 성공
- [ ] 네이버 금융과 KRX 데이터 일치 여부 비교 (최소 10 거래일)
- [ ] DAG fallback 로직: 네이버 실패 시 KRX API로 전환하는 구조 설계

---

## 참고: 작업 우선순위 판단 기준

```
긴급 (즉시): 현재 데이터가 stale 또는 부정확하여 분석 신뢰도에 영향
높음 (2주 내): 있어야 할 데이터가 없어 분석 범위가 제한됨
중간 (1달 내): 분석 품질 향상에 기여하나 현재 기능에 영향 없음
낮음 (분기): 리스크 예방 목적, 당장 장애 가능성 낮음
```

---

*완료된 작업은 요약 표의 상태를 `완료`로 변경하고, 실제 구현 내용(파일 경로, 테이블명 변경 등)을 해당 섹션에 기록해 주세요.*
