{{ config(materialized='view') }}

WITH source AS (
    SELECT * FROM {{ source('bip_raw', 'stock_price_1d') }}
    -- 최근 90일만 (데모 속도 개선)
    WHERE timestamp >= CURRENT_DATE - INTERVAL '90 days'
),

-- 같은 ticker×date 중복 시 가장 최근 created_at 행만 유지
deduped AS (
    SELECT DISTINCT ON (ticker, timestamp::date)
        *
    FROM source
    ORDER BY ticker, timestamp::date, created_at DESC
)

SELECT
    ticker,
    timestamp::date AS trade_date,
    open AS open_price,
    high AS high_price,
    low AS low_price,
    close AS close_price,
    volume,
    -- 거래대금 계산 (close × volume)
    (close * volume)::bigint AS trading_value_calc,
    -- 외국인/기관/개인 수급
    foreign_buy_volume,
    institution_buy_volume,
    individual_buy_volume,
    foreign_ownership_pct,
    -- 등락률 (전일 대비)
    LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp) AS prev_close,
    ROUND(
        ((close - LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp))
        / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY timestamp), 0) * 100)::numeric,
        2
    ) AS change_pct
FROM deduped
