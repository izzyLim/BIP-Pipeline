# 미국주식 SEC 공시 UI 개발 요청

## 개요

한국주식 종목 상세 화면의 **기업정보** 탭에 표시되는 "공시 내역"과 동등한 기능을 미국주식에도 추가하고 싶습니다. 데이터 파이프라인(Airflow)은 이미 구축되어 SEC EDGAR 공시가 PostgreSQL에 상시 적재되고 있으니, 백엔드 API 엔드포인트 추가 + 프론트엔드 화면 연결만 필요합니다.

## 목적

- 한국주식과 미국주식의 UI 경험을 일치시킴 (현재는 한국만 DART 공시가 보임)
- 종목 상세 진입 시 최근 SEC 공시를 리스트로 확인 가능
- 공시 원문 링크로 바로 이동 가능

## 데이터 소스 (이미 준비됨)

### 테이블: `sec_filings` (public 스키마)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | bigint PK | |
| `ticker` | varchar(20) | 종목 코드 (예: AAPL) — `stock_info.ticker`와 조인 가능 |
| `cik` | varchar(10) | SEC CIK 번호 (10자리 zero-padded) |
| `accession_no` | varchar(30) UNIQUE | SEC 공시 고유 ID (예: 0000320193-26-000123) |
| `form_type` | varchar(20) | 공시 폼 종류 (아래 "form_type 매핑" 참고) |
| `filing_date` | date | 공시 제출일 (SEC 기준) |
| `accepted_dt` | timestamptz | SEC 접수 시각 (초 단위) |
| `description` | text | 공시 설명. nullable (current_feed 경로는 최소 표시만, submissions 경로는 primaryDocDescription) |
| `filing_url` | text | SEC 원본 공시 URL (nullable) |
| `alerted_at` | timestamptz | **(deprecated)** 이전 알림 로직 잔존 필드. 무시 |
| `telegram_sent_at` | timestamptz | **UI 무관** (알림 경로는 현재 비활성) |
| `alert_decision` | varchar(30) | **UI 무관** (`sent`/`filtered_out`/`suppressed_backfill` 내부 상태) |
| `ingest_source` | varchar(30) | **UI 무관** (`current_feed`/`submissions_hot`/`submissions_nightly` 수집 경로) |
| `created_at` | timestamptz | |

**인덱스**: `(ticker, filing_date DESC)`가 있으므로 ticker 기반 조회는 효율적입니다.

### form_type 매핑 (프론트 표시용)

| form_type | 한글 라벨 | 설명 |
|---|---|---|
| `8-K` | 중요 이벤트 | M&A, CEO 교체, 실적 조기공시 등 |
| `8-K/A` | 중요 이벤트 (수정) | 8-K 수정본 |
| `10-K` | 연간 보고서 | 연간 사업보고서 |
| `10-K/A` | 연간 보고서 (수정) | |
| `10-Q` | 분기 보고서 | 분기 사업보고서 |
| `10-Q/A` | 분기 보고서 (수정) | |
| `4` | 내부자 거래 | 임원/대주주 매수매도 공시 |
| `4/A` | 내부자 거래 (수정) | |

### 데이터 적재 주기 (참고)

- **hot universe** (시총 상위 100 + 관심종목 + 보유종목 = 약 108개): **10분 주기** 갱신
- **전체 종목** (6,151개): **일 1회** (미국 동부 23:00 = 한국 오전 12:00) 갱신
- 그 외 종목: 당일 공시는 다음날 아침부터 조회 가능

## 백엔드 API 요청

### 엔드포인트: `GET /api/fundamental/filings/{ticker}`

한국주식의 기존 공시 엔드포인트(`/api/fundamental/disclosures/{ticker}` 등)와 동일한 규격으로 만들어주세요. 기존 스펙을 맞춰주시면 프론트 재사용성이 좋아집니다.

**경로 파라미터**:
- `ticker` (string, required): 종목 코드 (예: `AAPL`, `NVDA`)

**쿼리 파라미터**:
- `limit` (int, optional, default=50, max=200): 반환 건수
- `offset` (int, optional, default=0): 페이지네이션용
- `form_types` (string[], optional): 필터링할 form_type 배열 (예: `?form_types=8-K&form_types=10-K`)
- `start_date` (YYYY-MM-DD, optional): filing_date 하한 (inclusive)
- `end_date` (YYYY-MM-DD, optional): filing_date 상한 (inclusive)

**응답 예시**:
```json
{
  "ticker": "AAPL",
  "total": 127,
  "items": [
    {
      "id": 1312,
      "form_type": "8-K",
      "form_label": "중요 이벤트",
      "filing_date": "2026-04-03",
      "accepted_dt": "2026-04-03T20:15:42+00:00",
      "description": "Item 2.02 Results of Operations and Financial Condition",
      "filing_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123/aapl-20260403.htm",
      "accession_no": "0000320193-26-000123"
    }
  ]
}
```

**정렬**: `filing_date DESC, id DESC`

**쿼리 예시**:
```sql
SELECT id, form_type, filing_date, accepted_dt, description, filing_url, accession_no
FROM sec_filings
WHERE ticker = $1
  AND ($2::text[] IS NULL OR form_type = ANY($2))
  AND ($3::date IS NULL OR filing_date >= $3)
  AND ($4::date IS NULL OR filing_date <= $4)
ORDER BY filing_date DESC, id DESC
LIMIT $5 OFFSET $6;
```

**비고**:
- `telegram_sent_at`, `alert_decision`, `alerted_at`, `ingest_source`는 내부용이므로 응답에 포함하지 마세요
- `description`이 null인 경우 form_type의 한글 라벨만 표시하면 됩니다
- `filing_url`이 null인 경우 링크 비활성화 (드문 케이스)

### 선택사항: 요약 엔드포인트

기업정보 탭 첫 진입 시 "최근 공시 요약"을 보여주려면 다음 엔드포인트도 고려 가능합니다. 필수는 아닙니다.

`GET /api/fundamental/filings/{ticker}/summary`

최근 30일 기준 form_type별 건수 집계:
```json
{
  "ticker": "AAPL",
  "period_days": 30,
  "counts": {
    "8-K": 3,
    "10-Q": 1,
    "4": 12
  }
}
```

## 프론트엔드 요청

### 위치

- 미국주식 종목 상세 페이지 → **기업정보** 탭
- 한국주식 종목의 동일 탭 UI 구조를 그대로 재사용

### 표시 항목 (리스트 뷰)

각 공시 row:
- **form_type 배지**: 한글 라벨 (예: "중요 이벤트", "분기 보고서") — form_type별로 색상 구분 권장
  - 8-K / 8-K/A: 주황색 계열 (중요 이벤트 강조)
  - 10-K / 10-Q 계열: 파란색 계열 (정기 보고서)
  - 4 / 4/A: 회색 계열 (내부자 거래)
- **filing_date**: YYYY-MM-DD
- **description**: 1줄 요약 (길면 말줄임 …)
- **외부 링크 아이콘**: 클릭 시 `filing_url` 새 탭 오픈

### 필터/정렬

- form_type 체크박스 필터 (기본: 전체 선택)
- 기간 필터 (기본: 최근 1년)
- 정렬은 filing_date 역순 고정

### 페이지네이션

- "더 보기" 버튼 또는 무한 스크롤 (기존 DART 화면 방식에 맞춰서)
- 한 번에 50건씩

### 빈 상태

- 공시가 없는 종목 (주로 비주요 종목에서 lookback 범위 외):
  > "최근 공시 내역이 없습니다."

### 에러 상태

- API 500 등: "공시 내역을 불러오지 못했습니다. 잠시 후 다시 시도해주세요."

## 테스트 대상 종목

프론트/백엔드 개발 중 확인해볼 만한 티커 (현재 DB에 데이터 있음):

| ticker | 종목명 | 비고 |
|---|---|---|
| AAPL | Apple | 관심종목 |
| NVDA | NVIDIA | 시총 1위, 8-K 다수 |
| INTC | Intel | 최근 8-K 있음 |
| KO | Coca-Cola | Form 4 다수 (내부자 거래 테스트) |
| MSFT | Microsoft | 대형주 |

## 참고: 한국주식 공시와의 차이점

| 항목 | 한국 (DART) | 미국 (SEC EDGAR) |
|---|---|---|
| 테이블 | `financial_statements` + 기타 | `sec_filings` |
| 공시 식별자 | `rcept_no` | `accession_no` |
| 공시 분류 | DART 보고서 구분 코드 | SEC form_type (8-K, 10-K, 4 등) |
| 실시간성 | DART 기반 (분 단위) | 10분 주기 (주요 종목) / 일 1회 (전체) |
| 원문 링크 | DART 뷰어 URL | SEC Archives URL |

## 문의 / 컨택

- 데이터 파이프라인 관련 질문: `airflow/dags/stock_loader/dag_sec_edgar_hot.py`, `dag_sec_edgar_reconcile.py` 참조
- 테이블 스키마 확인: `psql -U user -d stockdb -c "\d sec_filings"`
- 추가 form_type이 필요하면 DAG의 `TARGET_FORMS` 수정 후 재수집 가능
