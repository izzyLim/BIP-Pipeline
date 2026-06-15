CREATE TABLE IF NOT EXISTS stock_info (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) UNIQUE,                  -- 종목 코드 (예: NVDA, 005930) - UNIQUE 지정
    stock_name VARCHAR(100),                    -- 한글 이름
    stock_name_eng VARCHAR(100),                -- 영어 이름
    market_type VARCHAR(20),                    -- KOSPI, NASDAQ, NYSE 등
    exchange_code VARCHAR(10),                  -- 거래소 코드 (예: NSQ, NYS)
    currency_code VARCHAR(10),                  -- USD, KRW 등
    listing_date DATE,                          -- 상장일
    par_value NUMERIC,                          -- 액면가
    total_shares BIGINT,                        -- 상장 주식수
    market_value NUMERIC,                       -- 시가총액 (옵션)
    data_source VARCHAR(50),                    -- ex) 'naver', 'krx', 'yfinance'
    is_active BOOLEAN DEFAULT TRUE,
    update_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 컨센서스 데이터 테이블 (네이버 금융/WiseReport 기반)
CREATE TABLE IF NOT EXISTS consensus_estimates (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,                -- 종목 코드 (예: 005930.KS)
    stock_code VARCHAR(10) NOT NULL,            -- 6자리 종목코드 (예: 005930)

    -- 투자의견
    rating NUMERIC(3,2),                        -- 투자의견 점수 (1-5, 5=Strong Buy)
    target_price BIGINT,                        -- 목표주가 (원)
    analyst_count INT,                          -- 애널리스트 수

    -- 예상 실적 (컨센서스)
    estimate_year INT,                          -- 예상 연도
    est_eps BIGINT,                             -- 예상 EPS (원)
    est_per NUMERIC(10,2),                      -- 예상 PER
    est_pbr NUMERIC(10,2),                      -- 예상 PBR
    est_roe NUMERIC(10,2),                      -- 예상 ROE (%)
    est_dividend BIGINT,                        -- 예상 배당금 (원)

    -- 메타데이터
    data_source VARCHAR(50) DEFAULT 'wisereport',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (ticker, estimate_year)
);

CREATE INDEX IF NOT EXISTS idx_consensus_ticker ON consensus_estimates(ticker);
CREATE INDEX IF NOT EXISTS idx_consensus_year ON consensus_estimates(estimate_year);

-- ============================================================
-- 기업정보 테이블 (DART 사업보고서 기반)
-- ============================================================

-- 1. 배당 정보
CREATE TABLE IF NOT EXISTS company_dividend (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    corp_code VARCHAR(10),
    fiscal_year INT NOT NULL,
    stock_type VARCHAR(50),                  -- 주식종류 (보통주/우선주)
    cash_dividend_per_share BIGINT,          -- 주당 현금배당금 (원)
    dividend_yield DECIMAL(10,4),            -- 시가배당률 (%)
    payout_ratio DECIMAL(10,4),              -- 배당성향 (%)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(ticker, fiscal_year, stock_type)
);
CREATE INDEX IF NOT EXISTS idx_company_dividend_ticker ON company_dividend(ticker);

-- 2. 직원 현황
CREATE TABLE IF NOT EXISTS company_employees (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    corp_code VARCHAR(10),
    fiscal_year INT NOT NULL,
    department VARCHAR(100),                 -- 부문명
    gender VARCHAR(10),                      -- 성별
    employee_type VARCHAR(20),               -- 정규직/계약직
    employee_count INT,                      -- 직원수
    avg_service_years DECIMAL(5,2),          -- 평균근속연수
    avg_salary BIGINT,                       -- 평균급여 (천원)
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(ticker, fiscal_year, department, gender, employee_type)
);
CREATE INDEX IF NOT EXISTS idx_company_employees_ticker ON company_employees(ticker);

-- 3. 임원 현황
CREATE TABLE IF NOT EXISTS company_executives (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    corp_code VARCHAR(10),
    fiscal_year INT NOT NULL,
    name VARCHAR(100),                       -- 성명
    gender VARCHAR(10),                      -- 성별
    position VARCHAR(100),                   -- 직위
    is_ceo BOOLEAN DEFAULT FALSE,            -- 대표이사 여부
    is_registered BOOLEAN DEFAULT TRUE,      -- 등기임원 여부
    tenure_start DATE,                       -- 임기 시작
    tenure_end DATE,                         -- 임기 종료
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(ticker, fiscal_year, name, position)
);
CREATE INDEX IF NOT EXISTS idx_company_executives_ticker ON company_executives(ticker);

-- 4. 감사의견
CREATE TABLE IF NOT EXISTS company_audit (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    corp_code VARCHAR(10),
    fiscal_year INT NOT NULL,
    auditor VARCHAR(100),                    -- 감사인
    opinion VARCHAR(50),                     -- 감사의견 (적정/한정/부적정/의견거절)
    emphasis TEXT,                           -- 강조사항
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(ticker, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_company_audit_ticker ON company_audit(ticker);

-- 5. 자기주식
CREATE TABLE IF NOT EXISTS company_treasury_stock (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    corp_code VARCHAR(10),
    fiscal_year INT NOT NULL,
    stock_type VARCHAR(50),                  -- 주식종류
    beginning_shares BIGINT,                 -- 기초수량
    acquired BIGINT,                         -- 취득
    disposed BIGINT,                         -- 처분
    retired BIGINT,                          -- 소각
    ending_shares BIGINT,                    -- 기말수량
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(ticker, fiscal_year, stock_type)
);
CREATE INDEX IF NOT EXISTS idx_company_treasury_ticker ON company_treasury_stock(ticker);

-- 6. 최대주주
CREATE TABLE IF NOT EXISTS company_shareholders (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    corp_code VARCHAR(10),
    fiscal_year INT NOT NULL,
    shareholder_name VARCHAR(200),           -- 주주명
    relation VARCHAR(100),                   -- 관계
    shares BIGINT,                           -- 주식수
    ownership_ratio DECIMAL(10,4),           -- 지분율 (%)
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(ticker, fiscal_year, shareholder_name)
);
CREATE INDEX IF NOT EXISTS idx_company_shareholders_ticker ON company_shareholders(ticker);

-- 7. 임원보수 (5억 이상 개별 공시)
CREATE TABLE IF NOT EXISTS company_exec_compensation (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    corp_code VARCHAR(10),
    fiscal_year INT NOT NULL,
    name VARCHAR(100),                       -- 성명
    position VARCHAR(100),                   -- 직위
    total_compensation BIGINT,               -- 총 보수액 (원)
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(ticker, fiscal_year, name)
);
CREATE INDEX IF NOT EXISTS idx_company_exec_comp_ticker ON company_exec_compensation(ticker);

-- ============================================================
-- 해외 AI 뉴스 다이제스트 (모닝리포트 "🌐 AI 동향" 섹션용)
-- - RSS 수집(TechCrunch/VentureBeat/Verge 등) → Haiku 번역·요약 → 저장
-- - 모닝리포트가 최근 24h 다이제스트를 read-only 조회
-- ============================================================
CREATE TABLE IF NOT EXISTS overseas_ai_news_digest (
    id BIGSERIAL PRIMARY KEY,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sources JSONB,                              -- 사용된 RSS 소스 목록
    raw_count INTEGER DEFAULT 0,                -- 수집된 원본 기사 수
    digest TEXT NOT NULL,                       -- Haiku 번역·요약 결과 (한국어)
    raw_items JSONB,                            -- 원본 기사 메타 (title/link/pub_date/source)
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_overseas_ai_news_digest_collected_at
    ON overseas_ai_news_digest(collected_at DESC);
