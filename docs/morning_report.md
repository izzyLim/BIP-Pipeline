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
| `semiconductor` | `get_semiconductor_prices()` | `macro_indicators` | DRAM/NAND 현물가 9종 + **1주/1개월 추세** |
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

| 모델 | 설정값 | 성능 | 속도 | 비용 |
|------|-------|------|------|------|
| **Claude Opus 4.5** | `claude-opus` | ⭐⭐⭐⭐⭐ 최고 | 느림 | $$$$ |
| Claude Sonnet 4 (기본) | `claude-sonnet` | ⭐⭐⭐⭐ 고품질 | 중간 | $$ |
| Claude Haiku 4.5 | `claude-haiku` | ⭐⭐⭐ 양호 | 빠름 | $ |
| GPT-5.4 | `gpt-5.4` | ⭐⭐⭐⭐ 고품질 | 중간 | $$$ |

설정: Airflow Variable `llm_model` 또는 환경변수 `LLM_MODEL`

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

🔧 반도체 가격 (9개 제품)
  - DRAM: DDR5 16Gb, DDR4 16Gb, DDR4 8Gb, DDR3 4Gb
  - NAND: TLC 512Gb, TLC 256Gb, TLC 128Gb, MLC 64Gb, MLC 32Gb
  - 전일/1주/1개월 변동률 포함
  - NAND 보합 시: 마지막 변동일 표시 (예: "3/17 +3.5%")

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

### 프롬프트 핵심 원칙

```
## 분석 원칙

1. **실제 데이터 우선**: 뉴스와 데이터가 다를 경우 반드시 실제 데이터 기준으로 분석
2. **깊이 있는 설명**: "왜 그런지", "어떤 의미인지", "앞으로 어떻게 될 수 있는지" 충분히 설명
3. **구체적 근거 제시**: 뉴스, 데이터, 과거 사례를 인용하며 분석
4. **실행 가능한 인사이트**: 구체적인 행동 지침 제공
5. **균형 잡힌 시각**: 기회와 리스크를 모두 분석
6. **이벤트 감지 필수**: GTC, FOMC, 지정학적 이슈 등 반드시 심층 분석

## 뉴스 활용 방식

❌ 절대 금지:
- "뉴스에서 자주 언급된..."
- "뉴스에 따르면..."
- 뉴스 헤드라인 그대로 나열

✅ 올바른 방식:
- 뉴스에서 팩트만 추출 → 데이터와 연결하여 분석
- 독자적인 해석과 인사이트 제시
- 예: "SK하이닉스의 HBM3E 양산 확대(뉴스)와 DRAM 현물가 3주 연속 상승(+2.3%, 데이터)을
     종합하면, 메모리 업황 회복이 가시화되고 있습니다."

## 이상치 우선 분석

시스템이 자동 탐지한 특이점(급등락, 이상 수급 등)을 최우선으로 분석.
일반적인 시황보다 "평소와 다른 점"에 집중.

## 시간순 분석 (중요!)

1. 🇰🇷 [과거] 어제 한국 시장 마감 - 미국장 언급 금지 (인과관계 역전 방지)
2. 🇺🇸 [밤사이] 미국 시장 마감 - 한국장 마감 후 움직임
3. 🔮 [오늘] 한국 시장 전망 - 야간선물, 갭 예측
```

---

## 용어 설명 자동 추가 (glossary.py)

AI 분석 결과에 어려운 금융 약어/전문용어를 자동으로 설명 추가합니다.

### 예시

| 원문 | 변환 후 |
|------|---------|
| VIX가 18.5로 하락 | VIX(공포지수, 높을수록 시장 불안)가 18.5로 하락 |
| HBM 수요 증가 | HBM(AI용 고성능메모리, 엔비디아 GPU에 탑재) 수요 증가 |
| FOMC 회의 | FOMC(미국 금리결정회의) 회의 |

### 등록된 용어 카테고리

- **지수/지표**: VIX, VKOSPI, DXY, SOX, PMI, CPI, PPI, PCE
- **밸류에이션**: PER, PBR, EPS, BPS, ROE, ROA, EV/EBITDA, PSR
- **반도체**: HBM, HBM3E, DDR5, DDR4, NAND, DRAM, eSSD, CoWoS
- **중앙은행**: FOMC, Fed, BOJ, ECB, BOK, QT, QE, dovish, hawkish
- **투자/수급**: Risk-On, Risk-Off, ETF, EWY, TLT, HYG, SPY, QQQ
- **시장 용어**: 갭상승, 갭하락, 데드캣바운스, 숏커버링, 윈도드레싱
- **기타**: YoY, QoQ, MoM, WoW, bps, GTC, WWDC, CES

---

## PDF 첨부 (pdf_generator.py)

이메일 본문과 동일한 내용을 PDF로 생성하여 첨부합니다.

### 특징

- 이메일 클라이언트에서 이미지가 차단되어도 PDF로 확인 가능
- 히트맵 이미지 포함 (CID → Data URI 변환)
- 파일명: `BIP_모닝브리핑_YYYYMMDD.pdf`
- weasyprint 라이브러리 사용

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
    ├── llm_analyzer_v2.py         멀티 LLM 분석 (Opus/Sonnet/Haiku/GPT)
    ├── glossary.py                용어 사전 (약어 설명 자동 추가)
    ├── pdf_generator.py           PDF 생성 (weasyprint)
    ├── anomaly_detector.py        시장 이상치 자동 탐지
    ├── email_sender.py            SMTP 개별 이메일 발송 + PDF 첨부
    └── templates/
        └── morning_report.html    Jinja2 이메일 템플릿
```

---

## 장중 모니터링 시스템 (Market Pulse Monitor)

> 모닝리포트 체크리스트 기반 장중 자동 모니터링 + 텔레그램 알림

### 아키텍처

```
08:10  모닝리포트 DAG → 이메일 (전체) + 텔레그램 (체크리스트 원문)
08:20  [테스트] Sonnet 모닝리포트 (본인 DM/이메일)
08:25  체크리스트 파싱 DAG → DB 저장 + 장전 에이전트 분석 발송
08:30  [테스트] GPT-5.4 모닝리포트 (본인 DM/이메일)
08:40  preopen DAG → 예상 체결가 + 갭 방향 분석 (한투 API)
09:00~15:30  장중 모니터링 (10분 간격)
  └── Layer 1: 이상치 감지 (지수/환율/수급/원자재/크립토)
09:00 / 10:00 / 12:00 / 14:30  정기 현황 (BIP-Agents 에이전트 분석)
15:35  장 마감 복기 (체크리스트 전체 기반 + 내일 관찰 포인트)
```

### 에이전트 분석 흐름 (B 아키텍처)

```
Airflow DAG → POST http://bip-agents-api:8100/api/checklist/analyze
  → LangGraph 에이전트 (Haiku + MCP 도구)
    → 한투 API: 종목 현재가, 지수, 투자자 수급, 프로그램 매매
    → ExchangeRate API: 환율
    → yfinance: EWY 야간선물, 닛케이 등 글로벌 지수
    → Upbit API: BTC/ETH
    → 네이버 뉴스 API: 관련 뉴스 검색
  → 체크리스트 항목별 데이터 기반 판단 + 종합 전망
  → 텔레그램 발송 (채널 + DM)
```

### 모니터링 DAGs

| DAG | 스케줄 | 역할 |
|-----|--------|------|
| `market_monitor_checklist_parse` | 평일 08:25 | 체크리스트 DB 저장 + 장전 에이전트 분석 발송 |
| `market_monitor_preopen` | 평일 08:40 | 한투 API 예상 체결가 + 갭 방향 분석 |
| `market_monitor_intraday` | 평일 09:00~15:50 / 10분 | 이상치 감지 + 정기 현황 (09/10/12/14:30) |
| `market_monitor_close` | 평일 15:35 | 장 마감 체크리스트 복기 + 내일 관찰 포인트 |

**모델 비교 테스트 DAG (본인 DM/이메일 전용, 2026-04-05 추가):**
| DAG | 스케줄 | 모델 |
|-----|--------|------|
| `morning_report_test_sonnet` | 평일 08:20 | Claude Sonnet 4.6 |
| `morning_report_test_gpt` | 평일 08:30 | GPT-5.4 |

### 이상치 알림 기준 (Layer 1)

| 항목 | 🟡 주의 | 🔴 긴급 | 데이터 소스 |
|------|---------|---------|------------|
| KOSPI/KOSDAQ | ±2% | ±3% | 네이버 금융 |
| 환율 (원/달러) | ±0.7% | ±1.5% | 네이버 금융 |
| 외국인/기관 수급 | ±4조 | ±5조 | 네이버 금융 |
| WTI | ±5% | ±8% | 네이버 금융 |
| 금 | ±3% | ±5% | 네이버 금융 |
| BTC/ETH | ±8% | ±12% | Upbit API |

### 체크리스트 모니터링 (에이전트 기반)

- 모닝리포트 체크리스트 원문을 DB에 통째로 저장
- BIP-Agents API로 에이전트 호출 → MCP 도구로 실시간 데이터 수집
- 시간대별 필터링: pre_market (장전), intraday (장중), close (마감)
- 삼성전자/SK하이닉스는 체크리스트에 없어도 항상 포함
- 투자자 수급은 에이전트가 한투 API로 실시간 조회
- 비용: Haiku ~$0.005/회 (하루 ~$0.03)

### DB 테이블

| 테이블 | 용도 |
|--------|------|
| `monitor_checklist` | 체크리스트 원문 (날짜별 1건) |
| `monitor_alerts` | 이상치 알림 발송 이력 |

### 주요 파일

| 파일 (BIP-Pipeline) | 역할 |
|------|------|
| `reports/market_monitor.py` | 모니터링 엔진 (이상치 감지, 에이전트 API 호출, 텔레그램) |
| `dag_market_monitor.py` | Airflow DAGs (4개) |
| `reports/telegram_sender.py` | 텔레그램 발송 (채널 + DM, 테스트 모드) |

| 파일 (BIP-Agents) | 역할 |
|------|------|
| `langgraph/api.py` | FastAPI 서버 (Airflow에서 HTTP 호출) |
| `langgraph/checklist_agent.py` | 체크리스트 분석 에이전트 (Haiku + MCP) |
| `langgraph/checklist_graph.py` | LangGraph 그래프 |
| `mcp-servers/bip-stock-mcp/realtime.py` | 한투 API/Upbit/yfinance 실시간 도구 |
| `mcp-servers/bip-stock-mcp/server.py` | MCP 서버 (22개 도구) |

---

## 변경 이력

| 날짜 | 변경 내용 |
|------|----------|
| 2026-04-05 | **Phase 1/2/3 구현** — get_indicator_context MCP 도구, LangGraph 4단계 파이프라인, 룰 엔진 분리 (`docs/checklist_agent_architecture.md`) |
| 2026-04-05 | **08:40 preopen DAG 추가** — 한투 API 예상 체결가 + 갭 방향 Haiku 분석 |
| 2026-04-05 | **주요 종목 10개로 확장** — 삼성전자/SK하이닉스/LG엔솔/삼성바이오/현대차/기아/POSCO/NAVER/카카오/삼성SDI |
| 2026-04-05 | **감사 로그 통합** — BIP-Agents API 응답 → Airflow `record_agent_audit()` |
| 2026-04-05 | **Sonnet/GPT 비교 테스트 DAG 추가** — 본인 DM/이메일 전용, 08:20/08:30 |
| 2026-04-05 | **체크리스트 시간대 필터링** — pre_market/intraday/close 분기 |
| 2026-04-05 | **장 마감 메시지 체크리스트 복기 + 내일 관찰 포인트** 형식으로 전환 |
| 2026-04-03 | **BIP-Agents 에이전트 연동** — 체크리스트 분석을 LangGraph + MCP 에이전트로 전환 |
| 2026-04-03 | **한투 API 실시간** — 종목/지수/수급/프로그램매매 실시간 (MCP 도구) |
| 2026-04-03 | **텔레그램 채널/DM 분리** — 채널(운영) + DM(테스트) 동시 발송 |
| 2026-04-03 | **메시지 포맷 개선** — 텔레그램 마크다운 호환, 시간대별 필터링 |
| 2026-04-02 | **장중 모니터링 시스템** 추가 (Market Pulse Monitor) |
| 2026-04-02 | **텔레그램 체크리스트 발송** — 모닝리포트에서 체크리스트만 텔레그램 발송 |
| 2026-04-02 | **KRX 섹터 퍼포먼스 개선** — 공식 업종 지수 데이터 + 별칭 매핑 |
| 2026-04-02 | **Upbit 크립토 실시간** — BTC/ETH 실시간 시세 (Upbit API) |
| 2026-03-24 | **Claude Opus 4.5 지원** 추가 (최고 성능 모델) |
| 2026-03-24 | **용어 설명 자동 추가** (glossary.py) - VIX, HBM, FOMC 등 70+개 용어 |
| 2026-03-24 | **PDF 첨부** 기능 추가 (pdf_generator.py) |
| 2026-03-24 | 반도체 가격표 확장 (4개→9개 제품), 1주/1개월 추세 컬럼 추가 |
| 2026-03-24 | NAND 보합 처리: 마지막 변동일 표시 (예: "3/17 +3.5%") |
| 2026-03-24 | 기본 LLM을 GPT-5.4 → Claude Sonnet으로 변경 |
| 2026-03-18 | 코스닥/나스닥 히트맵 추가 |
| 2026-03-18 | 추세 데이터 (1주/1개월/3개월) 전 지표에 추가 |
| 2026-03-18 | 달러인덱스, 반도체 ETF, 글로벌 지수, 섹터 지수 추가 |
| 2026-03-18 | 멀티 LLM 지원 (GPT-5.4, Claude Sonnet/Haiku) |
| 2026-03-18 | 이메일 개별 발송 (개인정보 보호) |
| 2026-03-18 | 주요 지수/매크로 지표 가로 테이블 레이아웃 |
