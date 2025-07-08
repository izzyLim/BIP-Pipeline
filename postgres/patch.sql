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
