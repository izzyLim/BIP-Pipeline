# BIP 모닝 브리핑 시스템

> 매일 오전 8:00 KST (평일), 전날 시장 데이터를 종합하여 AI 분석 리포트를 이메일로 발송하는 자동화 파이프라인

---

## 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           BIP 모닝 브리핑 시스템                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│   데이터 수집     │      │   리포트 생성     │      │     발송          │
│   (전날~새벽)     │ ───▶ │   (08:00 KST)    │ ───▶ │                  │
└──────────────────┘      └──────────────────┘      └──────────────────┘
        │                         │                         │
        ▼                         ▼                         ▼
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│ • 한국장 데이터   │      │ • DB 조회        │      │ • SMTP (Gmail)   │
│ • 미국장 데이터   │      │ • 히트맵 생성    │      │ • 개별 발송      │
│ • 매크로 지표    │      │ • 실시간 뉴스    │      │   (수신자 비공개) │
│ • 뉴스/섹터     │      │ • AI 분석        │      │                  │
└──────────────────┘      └──────────────────┘      └──────────────────┘
```

---

## 에이전트 데이터 흐름 도식

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        morning_report DAG (08:00 KST)                           │
│                              report_builder.py                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
│ macro_collector │        │ heatmap_generator│        │  realtime_news  │
│     .py         │        │      .py         │        │      .py        │
└─────────────────┘        └─────────────────┘        └─────────────────┘
          │                           │                           │
          ▼                           ▼                           ▼
┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
│   PostgreSQL    │        │   Plotly        │        │   Naver API     │
│   (stockdb)     │        │   Treemap       │        │   (News Search) │
└─────────────────┘        └─────────────────┘        └─────────────────┘
          │                           │                           │
          │   ┌───────────────────────┼───────────────────────┐   │
          │   │                       │                       │   │
          ▼   ▼                       ▼                       ▼   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         llm_analyzer_v2.py                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      프롬프트 구성                           │   │
│  │  • 시장 데이터 (한국/미국/코스닥/나스닥)                      │   │
│  │  • 매크로 지표 (환율, 금리, VIX, 원자재, 달러인덱스 등)        │   │
│  │  • 3개월 추세 데이터 (1주/1개월/3개월 변동률)                  │   │
│  │  • 글로벌/섹터 지수                                          │   │
│  │  • 실시간 뉴스 25건                                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      LLM API 호출                           │   │
│  │  • GPT-5.4 (기본)                                           │   │
│  │  • Claude Sonnet 4.5                                        │   │
│  │  • Claude Haiku 4.5                                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      HTML 템플릿 렌더링                              │
│                  templates/morning_report.html                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  • 주요 지수 (가로 테이블)                                    │   │
│  │  • 매크로 지표 (가로 테이블)                                  │   │
│  │  • 히트맵 4개 (KOSPI, KOSDAQ, S&P500, NASDAQ)                │   │
│  │  • 투자자 동향                                               │   │
│  │  • 반도체 가격                                               │   │
│  │  • AI 분석 본문                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        email_sender.py                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  SMTP 개별 발송 (수신자 간 이메일 비공개)                      │   │
│  │  • 한 번 연결 → 수신자별 개별 메시지 발송                      │   │
│  │  • 히트맵 이미지 인라인 첨부 (multipart/related)              │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 데이터 수집 상세 (macro_collector.py)

### 수집 데이터 항목

| 항목 | 함수 | 소스 테이블 | 내용 |
|------|------|-----------|------|
| `korea` | `get_korea_market_data()` | `stock_price_1d` + `stock_info` | KOSPI 시총 상위 200 종목, 등락률, 섹터 집계 |
| `kosdaq` | `get_kosdaq_market_data()` | `stock_price_1d` + `stock_info` | KOSDAQ 시총 상위 200 종목, 등락률, 섹터 집계 |
| `us` | `get_us_market_data()` | `stock_price_1d` + `stock_info` | S&P 500 종목, 등락률, 섹터 집계 |
| `nasdaq` | `get_nasdaq_market_data()` | `stock_price_1d` + `stock_info` | NASDAQ 시총 상위 200 종목, 등락률, 섹터 집계 |
| `investor_flow` | `get_investor_flow()` | `stock_price_1d` | 최근 5거래일 외국인·기관·개인 순매수 |
| `semiconductor` | `get_semiconductor_prices()` | `macro_indicators` | DRAM/NAND 현물가 + **1주/1개월/3개월 추세** |
| `indices` | `get_index_summary()` | `macro_indicators` | KOSPI, KOSDAQ, S&P 500, NASDAQ + **추세** |
| `exchange_rates` | `get_exchange_rates()` | `macro_indicators` | USD/KRW + **추세** |
| `fear_greed` | `get_fear_greed()` | `macro_indicators` | VIX, Fear&Greed, VKOSPI + **추세** |
| `commodities` | `get_commodities()` | `macro_indicators` | 금, WTI 원유 + **추세** |
| `interest_rates` | `get_interest_rates()` | `macro_indicators` | 미국 10년물, 한국 3년물 + **추세** |
| `bitcoin` | `get_bitcoin()` | `macro_indicators` | BTC 가격 + **추세** |
| `dollar_index` | `get_dollar_index()` | `macro_indicators` | 달러 인덱스 (DXY) + **추세** |
| `semiconductor_index` | `get_semiconductor_index()` | `macro_indicators` | SOX, SMH, SOXX ETF + **추세** |
| `global_indices` | `get_global_indices()` | `macro_indicators` | 닛케이, 상하이, 유로스톡스 + **추세** |
| `us_sectors` | `get_us_sectors()` | `macro_indicators` | 미국 섹터별 지수 (XLK, XLF 등) + **추세** |
| `kr_sectors` | `get_kr_sectors()` | `macro_indicators` | 한국 섹터별 지수 + **추세** |

### 추세 데이터 구조

모든 수치 지표는 다음 추세 데이터를 포함:

```python
{
    "value": 2845.32,           # 현재 값
    "change_pct": 1.25,         # 전일 대비 변동률
    "week_change_pct": 2.15,    # 1주일 전 대비 변동률
    "month_change_pct": 5.42,   # 1개월 전 대비 변동률
    "quarter_change_pct": 8.91  # 3개월 전 대비 변동률
}
```

---

## 히트맵 생성 (heatmap_generator.py)

Plotly Treemap을 사용하여 4개의 시장 히트맵 생성:

| 히트맵 | 데이터 소스 | 설명 |
|--------|-----------|------|
| KOSPI Top 100 | `korea["stocks"]` | 시총 기준 크기, 등락률 기준 색상 |
| KOSDAQ Top 100 | `kosdaq["stocks"]` | 코스닥 시총 상위 종목 |
| S&P 500 Top 100 | `us["stocks"]` | 미국 대형주 |
| NASDAQ Top 100 | `nasdaq["stocks"]` | 나스닥 기술주 중심 |

```
색상 스케일: -10% (빨강) ─ 0% (회색) ─ +10% (녹색)
```

---

## AI 분석 (llm_analyzer_v2.py)

### 지원 LLM 모델

| 모델 | 환경변수 | 설정값 |
|------|---------|-------|
| GPT-5.4 (기본) | `LLM_MODEL` | `gpt-5.4` |
| Claude Sonnet 4.5 | `LLM_MODEL` | `claude-sonnet` |
| Claude Haiku 4.5 | `LLM_MODEL` | `claude-haiku` |

### 프롬프트에 주입되는 데이터

```
📊 주요 지수
  - KOSPI, KOSDAQ, S&P500, NASDAQ (전일/1주/1개월/3개월 변동률)

📈 달러 인덱스 & 반도체 지수
  - DXY, SOX, SMH (추세 포함)

🌍 글로벌 지수
  - 닛케이225, 상하이종합, 유로스톡스50 (추세 포함)

🇺🇸 미국 섹터별 등락
  - XLK(기술), XLF(금융), XLE(에너지), XLV(헬스케어) 등 11개 섹터

🇰🇷 한국 섹터별 등락
  - 반도체, 자동차, 은행, 제약, 건설 등 10개 섹터

💹 한국 시장 (KOSPI/KOSDAQ)
  - 시장 등락률, 등락 종목 수, 섹터별 등락 상위/하위

💵 미국 시장 (S&P500/NASDAQ)
  - 시장 등락률, 섹터별 등락 상위/하위

🔄 투자자 동향
  - 외국인/기관/개인 최근 5일 순매수

🌐 매크로 지표
  - 환율, 금리, VIX, Fear&Greed, 비트코인, 금, 유가 (모두 추세 포함)

🔧 반도체 가격
  - DRAM DDR5/DDR4, NAND TLC/SLC (추세 포함)

📰 실시간 뉴스 (25건)
  - 시장 상황에 맞는 동적 쿼리로 수집
```

### 출력 구조 (2,500자 이상)

| 섹션 | 내용 |
|------|------|
| 📌 오늘의 핵심 | 가장 중요한 시장 이슈 2-3문장 요약 |
| 🌍 글로벌 정세 & 매크로 | 지정학 이슈, 달러/금리/원자재 흐름, 글로벌 지수 |
| 🇺🇸 미국 시장 심층 분석 | 전일 미국 시장 움직임, 섹터·종목 분석 |
| 🇰🇷 한국 시장 심층 분석 | 코스피/코스닥 원인 분석, 수급 해석 |
| 🔗 한국↔미국 연결고리 | 동조화/디커플링 분석 |
| 🔬 반도체 섹터 심층 분석 | DRAM/NAND 현물가, HBM 동향, 반도체 ETF |
| 💡 투자 아이디어 & 전략 | 기회/리스크 요인, 구체적 종목 언급 |
| 📅 이번 주 주요 이벤트 | FOMC, 실적 발표, 경제지표 등 |
| ✅ 오늘의 체크리스트 | 장 시작 전/중 모니터링 항목 |

---

## 이메일 발송 (email_sender.py)

### 발송 방식

- **SMTP**: Gmail (`smtp.gmail.com:587`, STARTTLS)
- **개별 발송**: 수신자별로 별도 메시지 발송 (개인정보 보호)
  - `To` 필드에 본인 이메일만 표시
  - 다른 수신자 이메일 비공개

```python
# 발송 흐름
with smtplib.SMTP(host, port) as server:
    server.starttls()
    server.login(user, password)

    for to_email in to_emails:
        msg = MIMEMultipart("related")
        msg["To"] = to_email  # 개별 수신자만 표시
        # ... 메시지 구성
        server.send_message(msg, to_addrs=[to_email])
```

---

## DAG 스케줄

| DAG | 실행 시간 (KST) | 대상 테이블 | 설명 |
|-----|----------------|------------|------|
| `02_price_kr_ohlcv_daily` | 전날 18:30 (평일) | `stock_price_1d` | KOSPI/KOSDAQ 일봉 |
| `05_kr_investor_trend_daily` | 전날 17:00 (평일) | `stock_price_1d` | 투자자 수급 |
| `02_price_us_ohlcv_daily` | **05:40** (화-토) | `stock_price_1d` | 미국 주식 일봉 |
| `04_macro_global_hourly` | **매시간** | `macro_indicators` | 매크로 지표 |
| `05_kr_sectors_daily` | 전날 18:00 (평일) | `macro_indicators` | 한국 섹터 지수 |
| `morning_report` | **08:00** (평일) | — | 리포트 생성 및 발송 |

---

## 환경변수 / Airflow Variables

| 키 | 설명 |
|----|------|
| `OPENAI_API_KEY` | GPT-5.4 API 키 |
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 실시간 뉴스 검색용 |
| `SMTP_USER` / `SMTP_PASSWORD` | Gmail SMTP 인증 |
| `LLM_MODEL` | 사용할 LLM 모델 (`gpt-5.4`, `claude-sonnet`, `claude-haiku`) |
| `morning_report_emails` | 수신자 이메일 목록 (Airflow Variable, 쉼표 구분) |

---

## 주요 파일

```
airflow/dags/
├── dag_morning_report.py          DAG 정의 (08:00 KST, 평일)
└── reports/
    ├── report_builder.py          전체 오케스트레이터
    ├── macro_collector.py         DB 데이터 수집 (18개 항목)
    ├── heatmap_generator.py       Plotly 트리맵 히트맵 (4개)
    ├── realtime_news.py           네이버 API 실시간 뉴스
    ├── llm_analyzer_v2.py         멀티 LLM 분석 (GPT/Claude)
    ├── email_sender.py            SMTP 개별 이메일 발송
    └── templates/
        └── morning_report.html    Jinja2 이메일 템플릿
```

---

## 변경 이력

| 날짜 | 변경 내용 |
|------|----------|
| 2026-03-18 | 코스닥/나스닥 히트맵 추가 |
| 2026-03-18 | 추세 데이터 (1주/1개월/3개월) 전 지표에 추가 |
| 2026-03-18 | 달러인덱스, 반도체 ETF, 글로벌 지수, 섹터 지수 추가 |
| 2026-03-18 | 멀티 LLM 지원 (GPT-5.4, Claude Sonnet/Haiku) |
| 2026-03-18 | 이메일 개별 발송 (개인정보 보호) |
| 2026-03-18 | 주요 지수/매크로 지표 가로 테이블 레이아웃 |
