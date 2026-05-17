{{ config(materialized='view') }}

-- Curated View — Boolean Flag 패턴
-- "저평가주 찾아줘" 같은 질문에 LLM이 단순 필터링만 하면 되도록

SELECT
    *,
    -- 저평가: PER < 10 AND PBR < 1
    (per_actual < 10 AND per_actual > 0 AND pbr_actual < 1 AND pbr_actual > 0) AS is_value_stock,
    -- 고ROE: ROE >= 15%
    (roe_actual >= 15) AS is_high_roe,
    -- 우량주: 저평가 + 고ROE 동시
    (per_actual < 15 AND per_actual > 0
        AND pbr_actual < 1.5 AND pbr_actual > 0
        AND roe_actual >= 10) AS is_quality_stock,
    -- 부채과다: debt_ratio > 200%
    (debt_ratio > 200) AS is_high_debt
FROM {{ ref('fct_valuation_yearly') }}
