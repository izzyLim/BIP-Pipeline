-- 종목 메타데이터 테이블
CREATE TABLE IF NOT EXISTS stock_metadata (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(100),
    market VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 초기 종목 데이터
INSERT INTO stock_metadata (ticker, name, market)
VALUES
    ('AAPL', 'Apple Inc.', 'NASDAQ'),
    ('MSFT', 'Microsoft Corporation', 'NASDAQ'),
    ('TSLA', 'Tesla Inc.', 'NASDAQ'),
    ('NVDA', 'NVIDIA Corporation', 'NASDAQ'),
    ('GOOGL', 'Alphabet Inc.', 'NASDAQ')
ON CONFLICT (ticker) DO NOTHING;

-- 공통 테이블 구조 함수화해서 생성: 1d, 1wk, 1mo
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'stock_price_1d') THEN
        CREATE TABLE stock_price_1d (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(10),
            timestamp TIMESTAMPTZ,
            timestamp_ny TIMESTAMPTZ,
            timestamp_kst TIMESTAMPTZ,
            open NUMERIC,
            high NUMERIC,
            low NUMERIC,
            close NUMERIC,
            volume BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (ticker, timestamp)
        );
    END IF;

    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'stock_price_1wk') THEN
        CREATE TABLE stock_price_1wk (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(10),
            timestamp TIMESTAMPTZ,
            timestamp_ny TIMESTAMPTZ,
            timestamp_kst TIMESTAMPTZ,
            open NUMERIC,
            high NUMERIC,
            low NUMERIC,
            close NUMERIC,
            volume BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (ticker, timestamp)
        );
    END IF;

    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'stock_price_1mo') THEN
        CREATE TABLE stock_price_1mo (
            id SERIAL PRIMARY KEY,
            ticker VARCHAR(10),
            timestamp TIMESTAMPTZ,
            timestamp_ny TIMESTAMPTZ,
            timestamp_kst TIMESTAMPTZ,
            open NUMERIC,
            high NUMERIC,
            low NUMERIC,
            close NUMERIC,
            volume BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (ticker, timestamp)
        );
    END IF;
END $$;
