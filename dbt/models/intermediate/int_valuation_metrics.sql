{{ config(materialized='ephemeral') }}

-- 재무제표 + 종목 메타를 결합해 PER/PBR/ROE 계산
-- ephemeral: 별도 테이블/뷰 생성 안 함, 참조 시 CTE로 인라인 삽입

WITH financials AS (
    SELECT
        ticker,
        fiscal_year,
        fiscal_quarter,
        report_type,
        revenue,
        operating_profit,
        net_income,
        total_assets,
        total_equity,
        total_liabilities
    FROM {{ source('bip_raw', 'financial_statements') }}
    WHERE report_type = 'annual'   -- 연간 확정 실적만
),

stock_meta AS (
    SELECT
        ticker,
        stock_name,
        market_value
    FROM {{ ref('stg_stock_info') }}
)

SELECT
    f.ticker,
    s.stock_name,
    f.fiscal_year,
    f.revenue,
    f.operating_profit,
    f.net_income,
    f.total_assets,
    f.total_equity,
    -- 단위 통일 매크로 사용 (alias 명시)
    {{ to_won('s.market_value', alias='market_value_won') }},
    -- 밸류에이션 지표 계산
    ROUND((s.market_value * 100000000 / NULLIF(f.net_income, 0))::numeric, 2) AS per_calc,
    ROUND((s.market_value * 100000000 / NULLIF(f.total_equity, 0))::numeric, 2) AS pbr_calc,
    ROUND((f.net_income::numeric / NULLIF(f.total_equity, 0) * 100), 2) AS roe_calc_pct,
    ROUND((f.total_liabilities::numeric / NULLIF(f.total_equity, 0) * 100), 2) AS debt_ratio_pct
FROM financials f
JOIN stock_meta s ON f.ticker = s.ticker
