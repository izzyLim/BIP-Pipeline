-- ============================================================
-- Curated Views for NL2SQL Semantic Layer
-- ============================================================
-- 목적:
--   Gold 테이블 위에 threshold 기반 boolean 분류와 파생 계산을 고정.
--   Wren AI에 모델로 등록되어 NL2SQL의 시맨틱 레이어 역할.
--
-- 원칙:
--   View = truth (계산 SSOT). Wren AI MDL이나 OM description에
--   같은 계산식을 넣지 않는다 (SSOT 중복 금지).
--
-- 실행:
--   docker exec -i bip-postgres psql -U user -d stockdb < postgres/curated_views.sql
--
-- 네이밍:
--   v_<domain>_<subject>__v<major>
--   Breaking change → 새 버전 생성
-- ============================================================


-- ── 1. v_latest_valuation ──────────────────────────────────
-- 종목별 최신 연도 밸류에이션 스냅샷 (1 ticker = 1 row)
-- analytics_stock_daily와 안전하게 JOIN 가능 (grain 일치)
-- ⚠️ analytics_valuation과 직접 Relationship 대신 이 뷰를 사용

DROP VIEW IF EXISTS v_latest_valuation CASCADE;

CREATE VIEW v_latest_valuation AS
SELECT av.*
FROM analytics_valuation av
INNER JOIN (
    SELECT ticker, MAX(fiscal_year) AS max_year
    FROM analytics_valuation
    GROUP BY ticker
) latest ON av.ticker = latest.ticker AND av.fiscal_year = latest.max_year;

COMMENT ON VIEW v_latest_valuation IS
    '종목별 최신 연도 밸류에이션 스냅샷 (1 ticker = 1 row). '
    'analytics_stock_daily와 안전하게 JOIN 가능 (grain 일치). '
    'analytics_valuation과 직접 Relationship 금지 (daily vs annual grain 불일치).';


-- ── 2. v_valuation_signals__v1 ─────────────────────────────
-- 밸류에이션 기반 threshold 분류 + 파생 계산

DROP VIEW IF EXISTS v_valuation_signals__v1 CASCADE;

CREATE VIEW v_valuation_signals__v1 AS
SELECT
    ticker,
    stock_name,
    market_type,
    fiscal_year,

    -- base metrics (Gold에서 그대로)
    per_actual,
    pbr_actual,
    roe_actual,
    roa_actual,
    revenue,
    operating_profit,
    net_income,
    total_assets,
    total_equity,
    total_liabilities,
    market_value,

    -- pre-computed metrics (파생 계산)
    operating_margin,
    net_margin,
    debt_ratio,
    equity_ratio,
    revenue_growth,
    op_profit_growth,
    net_income_growth,

    -- 단위 변환
    market_value * 100000000 AS market_value_krw,

    -- 컨센서스
    est_per, est_pbr, est_roe,
    analyst_rating, target_price, analyst_count,

    -- ── threshold 분류 (boolean flags) ──────────────────
    -- 기준이 바뀔 수 있으므로 Gold DAG이 아닌 View에 정의
    (per_actual > 0 AND per_actual < 10 AND pbr_actual < 1)
        AS is_value_stock,

    (per_actual > 0 AND per_actual < 10 AND roe_actual > 15)
        AS is_value_growth,

    (revenue_growth > 20 AND operating_margin > 10)
        AS is_growth_stock,

    (debt_ratio > 200)
        AS is_high_debt,

    (roe_actual > 20)
        AS is_high_roe,

    (per_actual > 0 AND per_actual < 5)
        AS is_deep_value

FROM analytics_valuation;

COMMENT ON VIEW v_valuation_signals__v1 IS
    'Gold 밸류에이션 + threshold 기반 분류. '
    'is_value_stock: PER<10 AND PBR<1. '
    'is_value_growth: PER<10 AND ROE>15. '
    'is_growth_stock: 매출성장>20% AND 영업이익률>10%. '
    'is_high_debt: 부채비율>200%. '
    'is_high_roe: ROE>20%. '
    'is_deep_value: PER<5.';


-- ── 3. v_technical_signals__v1 ─────────────────────────────
-- 기술지표 기반 threshold 분류 + 파생 계산

DROP VIEW IF EXISTS v_technical_signals__v1 CASCADE;

CREATE VIEW v_technical_signals__v1 AS
SELECT
    ticker,
    trade_date,
    stock_name,
    market_type,
    market_value,

    -- 시세
    open, high, low, close, volume,
    change_pct,
    after_hours_close,
    after_hours_change_pct,

    -- 기술지표 (Gold에서 그대로)
    ma5, ma20, ma60, ma120, ma200,
    rsi14,
    macd, macd_signal, macd_hist,
    bb_upper, bb_middle, bb_lower, bb_pctb,
    atr14,
    golden_cross, death_cross,
    high_52w, low_52w, pct_from_52w_high,
    volume_ma20, volume_ratio,

    -- 컨센서스 (Gold에 이미 포함)
    analyst_rating, target_price, analyst_count,
    est_eps, est_per, est_pbr, est_roe,

    -- ── threshold 분류 (boolean flags) ──────────────────

    (rsi14 IS NOT NULL AND rsi14 < 30)
        AS is_oversold_rsi,

    (rsi14 IS NOT NULL AND rsi14 > 70)
        AS is_overbought_rsi,

    (close < bb_lower AND bb_lower IS NOT NULL)
        AS is_below_bollinger,

    (close > bb_upper AND bb_upper IS NOT NULL)
        AS is_above_bollinger,

    (volume_ratio > 3 AND volume_ma20 IS NOT NULL)
        AS is_volume_spike,

    (pct_from_52w_high < -30 AND pct_from_52w_high IS NOT NULL)
        AS is_near_52w_low,

    -- ── 파생 계산 ───────────────────────────────────────

    ROUND(((close - ma20) * 100.0 / NULLIF(ma20, 0))::numeric, 2)
        AS disparity_20d,

    ROUND(((close - ma60) * 100.0 / NULLIF(ma60, 0))::numeric, 2)
        AS disparity_60d,

    ROUND(((close - ma120) * 100.0 / NULLIF(ma120, 0))::numeric, 2)
        AS disparity_120d,

    close * volume
        AS trading_value,

    CASE WHEN target_price > 0 AND close > 0 THEN
        ROUND(((target_price - close) * 100.0 / close)::numeric, 2)
    END AS target_upside_pct

FROM analytics_stock_daily;

COMMENT ON VIEW v_technical_signals__v1 IS
    'Gold 시세+기술지표 + threshold 분류. '
    'is_oversold_rsi: RSI<30. '
    'is_overbought_rsi: RSI>70. '
    'is_below_bollinger: 종가<BB하단. '
    'is_volume_spike: 거래량비율>3x. '
    'is_near_52w_low: 52주고점대비 -30%이상 하락. '
    'disparity_20d/60d/120d: 이격도(%). '
    'trading_value: 거래대금(close*volume). '
    'target_upside_pct: 목표가괴리율(%).';


-- ── 4. v_flow_signals__v1 ──────────────────────────────────
-- 수급 기반 파생 계산

DROP VIEW IF EXISTS v_flow_signals__v1 CASCADE;

CREATE VIEW v_flow_signals__v1 AS
SELECT
    ticker,
    trade_date,
    stock_name,
    market_type,
    close,
    volume,

    -- 수급 원본
    foreign_buy_volume,
    institution_buy_volume,
    individual_buy_volume,
    foreign_ownership_pct,

    -- ── 파생 계산 (금액 환산) ────────────────────────────

    foreign_buy_volume * close AS foreign_buy_amount,
    institution_buy_volume * close AS institution_buy_amount,
    individual_buy_volume * close AS individual_buy_amount,

    -- 수급 강도
    CASE WHEN volume > 0 THEN
        ROUND((foreign_buy_volume * 100.0 / volume)::numeric, 2)
    END AS foreign_ratio_pct,

    CASE WHEN volume > 0 THEN
        ROUND((institution_buy_volume * 100.0 / volume)::numeric, 2)
    END AS institution_ratio_pct,

    -- 순매수 방향 (boolean)
    (foreign_buy_volume > 0) AS is_foreign_net_buy,
    (institution_buy_volume > 0) AS is_institution_net_buy,

    -- 수급 방향 해석 (텍스트 — LLM 답변 품질 향상용)
    CASE
        WHEN foreign_buy_volume IS NULL THEN '데이터없음'
        WHEN foreign_buy_volume > 0 THEN '순매수'
        WHEN foreign_buy_volume < 0 THEN '순매도'
        ELSE '보합'
    END AS foreign_direction,
    CASE
        WHEN institution_buy_volume IS NULL THEN '데이터없음'
        WHEN institution_buy_volume > 0 THEN '순매수'
        WHEN institution_buy_volume < 0 THEN '순매도'
        ELSE '보합'
    END AS institution_direction,
    CASE
        WHEN individual_buy_volume IS NULL THEN '데이터없음'
        WHEN individual_buy_volume > 0 THEN '순매수'
        WHEN individual_buy_volume < 0 THEN '순매도'
        ELSE '보합'
    END AS individual_direction

FROM analytics_stock_daily;

COMMENT ON VIEW v_flow_signals__v1 IS
    'Gold 수급 데이터 + 금액 환산 + 순매수 방향. '
    'foreign/institution/individual_buy_volume: 순매수량(주). 양수=순매수, 음수=순매도, 음수는 정상값. '
    'foreign/institution/individual_direction: 수급 방향 텍스트(순매수/순매도/데이터없음). '
    'is_foreign_net_buy: 외국인순매수여부(boolean).';


-- ── 5. GRANT (nl2sql_exec 전용 계정) ───────────────────────

GRANT SELECT ON v_latest_valuation TO nl2sql_reader;
GRANT SELECT ON v_valuation_signals__v1 TO nl2sql_reader;
GRANT SELECT ON v_technical_signals__v1 TO nl2sql_reader;
GRANT SELECT ON v_flow_signals__v1 TO nl2sql_reader;
