CREATE TABLE IF NOT EXISTS stock_price (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10),
    timestamp TIMESTAMPTZ,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
