-- ============================================================
-- Gold Layer DDL
-- analytics_macro_daily / analytics_stock_daily / analytics_valuation
--
-- 목적: NL2SQL 친화적 pre-joined 와이드 테이블
--       EAV(macro_indicators) → 컬럼 pivot
--       멀티조인(stock_price_1d + indicators + consensus) 제거
-- ============================================================


-- ──────────────────────────────────────────────────────────────
-- 1. analytics_macro_daily
--    macro_indicators (EAV) → 컬럼 pivot
--    하루 1행 | 월별 지표는 forward-fill
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analytics_macro_daily (
    indicator_date          DATE        PRIMARY KEY,

    -- ── 글로벌 변동성 / 심리 ──────────────────────────
    vix                     NUMERIC(10,4),   -- CBOE VIX (North America)
    vkospi                  NUMERIC(10,4),   -- 한국 변동성지수
    fear_greed_index        NUMERIC(10,4),   -- CNN Fear & Greed (0~100)
    global_risk_index       NUMERIC(10,4),   -- 글로벌 지정학 리스크 종합

    -- ── 미국 금리 ────────────────────────────────────
    us_10y                  NUMERIC(10,4),   -- 미국 10년 국채 수익률 (%)
    us_5y                   NUMERIC(10,4),   -- 미국 5년 국채 수익률 (%)
    us_3m                   NUMERIC(10,4),   -- 미국 3개월 국채 수익률 (%)
    us_yield_curve          NUMERIC(10,4),   -- 장단기 스프레드 (10y - 3m)

    -- ── 미국 주요 지수 ───────────────────────────────
    sp500                   NUMERIC(12,4),
    nasdaq                  NUMERIC(12,4),
    sox                     NUMERIC(12,4),   -- PHLX 반도체지수
    etf_smh                 NUMERIC(12,4),   -- 반도체 ETF (SMH)
    etf_soxx                NUMERIC(12,4),   -- 반도체 ETF (SOXX)

    -- ── 원자재 ──────────────────────────────────────
    oil_wti                 NUMERIC(12,4),   -- WTI 원유 (USD/배럴)
    gold                    NUMERIC(12,4),   -- 금 (USD/온스)
    copper                  NUMERIC(12,4),   -- 구리 (USD/파운드)
    btc                     NUMERIC(14,2),   -- 비트코인 (USD)

    -- ── 환율 ────────────────────────────────────────
    usd_krw                 NUMERIC(10,4),   -- 원/달러 환율
    usd_cny                 NUMERIC(10,4),   -- 위안/달러
    usd_jpy                 NUMERIC(10,4),   -- 엔/달러
    dollar_index            NUMERIC(10,4),   -- 달러인덱스 (DXY)

    -- ── 한국 금리 ───────────────────────────────────
    kr_base_rate            NUMERIC(8,4),    -- 한국은행 기준금리 (%)
    kr_call_rate            NUMERIC(8,4),    -- 콜금리 (%)
    kr_cd_91d               NUMERIC(8,4),    -- CD 91일물 (%)
    kr_cofix_new            NUMERIC(8,4),    -- COFIX 신규취급액 (%)
    kr_govt_3y              NUMERIC(8,4),    -- 국고채 3년 (%)
    kr_corp_3y              NUMERIC(8,4),    -- 회사채 3년 AA- (%)

    -- ── 한국 주요 지수 ──────────────────────────────
    kospi                   NUMERIC(12,4),
    kosdaq                  NUMERIC(12,4),

    -- ── 한국 경제지표 (월별, forward-fill) ──────────
    kr_cpi_yoy              NUMERIC(8,4),    -- 소비자물가 전년비 (%)
    kr_export_growth        NUMERIC(8,4),    -- 수출 증가율 (%)
    kr_gdp_growth           NUMERIC(8,4),    -- GDP 성장률 (%)

    -- ── 글로벌 주요 지수 ─────────────────────────────
    nikkei                  NUMERIC(12,4),
    shanghai                NUMERIC(12,4),
    eurostoxx               NUMERIC(12,4),

    -- ── 지정학 리스크 점수 (국가별) ─────────────────
    risk_score_us           NUMERIC(8,4),
    risk_score_cn           NUMERIC(8,4),
    risk_score_eu           NUMERIC(8,4),
    risk_score_jp           NUMERIC(8,4),
    risk_score_kr           NUMERIC(8,4),

    -- ── 뉴스 감성 ───────────────────────────────────
    news_sentiment_overall      NUMERIC(8,4),  -- 전체 뉴스 감성 (-1~1)
    news_sentiment_economic     NUMERIC(8,4),  -- 경제 뉴스 감성
    news_sentiment_geopolitical NUMERIC(8,4),  -- 지정학 뉴스 감성

    -- ── 한국 섹터 ETF (KRX) ─────────────────────────
    kr_sector_semiconductor NUMERIC(12,4),   -- KRX 반도체 섹터
    kr_sector_it            NUMERIC(12,4),   -- KRX IT 섹터
    kr_sector_auto          NUMERIC(12,4),   -- KRX 자동차 섹터
    kr_sector_banks         NUMERIC(12,4),   -- KRX 은행 섹터

    -- ── 메타 ────────────────────────────────────────
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE analytics_macro_daily IS
    'Gold layer: macro_indicators EAV 테이블을 일별 1행 피벗 테이블로 변환. '
    '하루 1행, 월별 지표는 forward-fill 적용. '
    'NL2SQL 친화적 — 복잡한 WHERE indicator_type = ... 조건 불필요.';

COMMENT ON COLUMN analytics_macro_daily.us_yield_curve IS '장단기 스프레드 (us_10y - us_3m). 음수=역전=경기침체 신호';
COMMENT ON COLUMN analytics_macro_daily.vix IS 'CBOE 변동성지수. 20 이하=안정, 30 이상=불안, 40 이상=공포';
COMMENT ON COLUMN analytics_macro_daily.fear_greed_index IS 'CNN Fear & Greed. 0=극단공포, 50=중립, 100=극단탐욕';
COMMENT ON COLUMN analytics_macro_daily.usd_krw IS '1달러당 원화. 높을수록 원화 약세';
COMMENT ON COLUMN analytics_macro_daily.kr_base_rate IS '한국은행 기준금리 (%). 월별 결정, forward-fill';
COMMENT ON COLUMN analytics_macro_daily.kr_cpi_yoy IS '소비자물가 전년 동월비 (%). 월별 발표, forward-fill';


-- ──────────────────────────────────────────────────────────────
-- 2. analytics_stock_daily
--    stock_price_1d + stock_indicators + consensus_estimates
--    (ticker, trade_date) 1행 | 한국 주식 중심
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analytics_stock_daily (
    ticker                  VARCHAR(20)     NOT NULL,
    trade_date              DATE            NOT NULL,

    -- ── 종목 기본 정보 (stock_info) ─────────────────
    stock_name              VARCHAR(100),
    market_type             VARCHAR(20),     -- KOSPI, KOSDAQ, NASDAQ, NYSE
    market_value            NUMERIC,         -- 시가총액 (억원)

    -- ── 시세 (stock_price_1d) ────────────────────────
    open                    NUMERIC,
    high                    NUMERIC,
    low                     NUMERIC,
    close                   NUMERIC,
    volume                  BIGINT,
    change_pct              NUMERIC(8,4),    -- 전일 대비 등락률 (%)
    after_hours_close       NUMERIC,         -- 시간외 종가
    after_hours_change_pct  NUMERIC(8,4),
    foreign_buy_volume      BIGINT,          -- 외국인 순매수 (주)
    institution_buy_volume  BIGINT,          -- 기관 순매수 (주)
    individual_buy_volume   BIGINT,          -- 개인 순매수 (주)
    foreign_ownership_pct   NUMERIC(8,4),    -- 외국인 보유 비중 (%)

    -- ── 기술적 지표 (stock_indicators) ──────────────
    ma5                     NUMERIC,
    ma20                    NUMERIC,
    ma60                    NUMERIC,
    ma120                   NUMERIC,
    ma200                   NUMERIC,
    rsi14                   NUMERIC(8,4),
    macd                    NUMERIC,
    macd_signal             NUMERIC,
    macd_hist               NUMERIC,
    bb_upper                NUMERIC,
    bb_middle               NUMERIC,
    bb_lower                NUMERIC,
    bb_pctb                 NUMERIC(8,4),    -- BB %B (위치)
    atr14                   NUMERIC,
    golden_cross            BOOLEAN,
    death_cross             BOOLEAN,
    high_52w                NUMERIC,
    low_52w                 NUMERIC,
    pct_from_52w_high       NUMERIC(8,4),    -- 52주 고가 대비 하락률 (%)
    volume_ma20             BIGINT,
    volume_ratio            NUMERIC(8,4),    -- 거래량 / volume_ma20

    -- ── 컨센서스 (consensus_estimates) ──────────────
    analyst_rating          NUMERIC(4,2),    -- 투자의견 (1~5, 5=Strong Buy)
    target_price            BIGINT,          -- 목표주가 (원)
    analyst_count           INT,             -- 추정 애널리스트 수
    est_eps                 BIGINT,          -- 예상 EPS (원)
    est_per                 NUMERIC(10,2),   -- 예상 PER
    est_pbr                 NUMERIC(10,2),   -- 예상 PBR
    est_roe                 NUMERIC(10,2),   -- 예상 ROE (%)

    -- ── 메타 ────────────────────────────────────────
    updated_at              TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (ticker, trade_date)
);

COMMENT ON TABLE analytics_stock_daily IS
    'Gold layer: stock_price_1d + stock_indicators + consensus_estimates + stock_info를 '
    '(ticker, trade_date) 기준으로 pre-join한 와이드 테이블. '
    'NL2SQL 친화적 — 복잡한 멀티조인 없이 단일 테이블로 주가/기술지표/컨센서스 조회 가능.';

COMMENT ON COLUMN analytics_stock_daily.market_value IS '시가총액. 단위: 억원 (×1억원 = 원)';
COMMENT ON COLUMN analytics_stock_daily.analyst_rating IS '투자의견 점수. 5=Strong Buy, 4=Buy, 3=Hold, 2=Underperform, 1=Sell';
COMMENT ON COLUMN analytics_stock_daily.pct_from_52w_high IS '52주 고가 대비 현재가 위치. 음수=고가 대비 하락, 0=52주 신고가';


-- ──────────────────────────────────────────────────────────────
-- 3. analytics_valuation
--    stock_info + financial_statements + consensus_estimates
--    (ticker, fiscal_year) 기준 밸류에이션 종합
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analytics_valuation (
    ticker                  VARCHAR(20)     NOT NULL,
    fiscal_year             INT             NOT NULL,

    -- ── 종목 기본 정보 ────────────────────────────────
    stock_name              VARCHAR(100),
    market_type             VARCHAR(20),
    market_value            NUMERIC,         -- 시가총액 (억원, 최신)
    market_value_krw        NUMERIC,         -- 시가총액 (원, market_value×1억)

    -- ── 재무제표 원본 (financial_statements, annual) ──
    revenue                 NUMERIC,         -- 매출액 (원)
    gross_profit            NUMERIC,         -- 매출총이익 (원)
    operating_profit        NUMERIC,         -- 영업이익 (원)
    net_income              NUMERIC,         -- 당기순이익 (원)
    total_assets            NUMERIC,         -- 자산총계 (원)
    total_equity            NUMERIC,         -- 자본총계 (원)
    total_liabilities       NUMERIC,         -- 부채총계 (원)
    cash_from_operating     NUMERIC,         -- 영업활동 현금흐름 (원)

    -- ── 계산 밸류에이션 지표 ─────────────────────────
    per_actual              NUMERIC(12,4),   -- 실제 PER = 시총 / 순이익
    pbr_actual              NUMERIC(12,4),   -- 실제 PBR = 시총 / 자본총계
    roe_actual              NUMERIC(8,4),    -- 실제 ROE = 순이익 / 자본총계 (%)
    roa_actual              NUMERIC(8,4),    -- 실제 ROA = 순이익 / 자산총계 (%)
    operating_margin        NUMERIC(8,4),    -- 영업이익률 = 영업이익 / 매출 (%)
    net_margin              NUMERIC(8,4),    -- 순이익률 = 순이익 / 매출 (%)
    debt_ratio              NUMERIC(8,4),    -- 부채비율 = 부채 / 자본 (%)
    equity_ratio            NUMERIC(8,4),    -- 자기자본비율 = 자본 / 자산 (%)

    -- ── 성장률 (전년 대비) ───────────────────────────
    revenue_growth          NUMERIC(8,4),    -- 매출 성장률 YoY (%)
    op_profit_growth        NUMERIC(8,4),    -- 영업이익 성장률 YoY (%)
    net_income_growth       NUMERIC(8,4),    -- 순이익 성장률 YoY (%)

    -- ── 컨센서스 추정치 ──────────────────────────────
    est_per                 NUMERIC(10,2),   -- 예상 PER (애널리스트)
    est_pbr                 NUMERIC(10,2),   -- 예상 PBR
    est_roe                 NUMERIC(10,2),   -- 예상 ROE (%)
    analyst_rating          NUMERIC(4,2),    -- 투자의견 (1~5)
    target_price            BIGINT,          -- 목표주가 (원)
    analyst_count           INT,

    -- ── 메타 ────────────────────────────────────────
    updated_at              TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (ticker, fiscal_year)
);

COMMENT ON TABLE analytics_valuation IS
    'Gold layer: stock_info + financial_statements(annual) + consensus_estimates를 '
    '(ticker, fiscal_year) 기준으로 pre-join. PER/PBR/ROE/성장률 등 pre-computed. '
    'NL2SQL 친화적 — 단위 변환(market_value 억원→원) 및 계산식이 이미 적용됨.';

COMMENT ON COLUMN analytics_valuation.per_actual IS '실제 PER = market_value_krw / net_income. NULL이면 순손실';
COMMENT ON COLUMN analytics_valuation.market_value IS '시가총액. 단위: 억원';
COMMENT ON COLUMN analytics_valuation.market_value_krw IS '시가총액. 단위: 원 (market_value × 100,000,000)';


-- ──────────────────────────────────────────────────────────────
-- 인덱스
-- ──────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_analytics_macro_date
    ON analytics_macro_daily (indicator_date DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_stock_ticker_date
    ON analytics_stock_daily (ticker, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_stock_date
    ON analytics_stock_daily (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_valuation_ticker
    ON analytics_valuation (ticker, fiscal_year DESC);
