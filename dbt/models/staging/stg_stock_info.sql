{{ config(materialized='view') }}

WITH source AS (
    SELECT * FROM {{ source('bip_raw', 'stock_info') }}
)

SELECT
    ticker,
    stock_name,
    market_type,
    sector,
    industry_name AS industry,
    market_value,
    -- 한국 종목 여부 (.KS / .KQ 접미사)
    CASE
        WHEN ticker LIKE '%.KS' OR ticker LIKE '%.KQ' THEN TRUE
        ELSE FALSE
    END AS is_korea,
    -- 6자리 종목코드 (한국용)
    CASE
        WHEN ticker LIKE '%.KS' THEN SPLIT_PART(ticker, '.', 1)
        WHEN ticker LIKE '%.KQ' THEN SPLIT_PART(ticker, '.', 1)
        ELSE NULL
    END AS stock_code
FROM source
