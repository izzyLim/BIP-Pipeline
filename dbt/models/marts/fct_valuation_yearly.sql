{{ config(
    materialized='table',
    indexes=[
        {'columns': ['ticker', 'fiscal_year'], 'unique': true}
    ]
) }}

-- 종목×연도 Gold 밸류에이션
-- intermediate 계산 결과를 마트로 고정

SELECT
    ticker,
    stock_name,
    fiscal_year,
    revenue,
    operating_profit,
    net_income,
    total_assets,
    total_equity,
    market_value_won,
    per_calc AS per_actual,
    pbr_calc AS pbr_actual,
    roe_calc_pct AS roe_actual,
    debt_ratio_pct AS debt_ratio
FROM {{ ref('int_valuation_metrics') }}
