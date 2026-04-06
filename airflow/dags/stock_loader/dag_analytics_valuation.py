"""
[09_analytics_valuation]
Gold layer: stock_info + financial_statements(annual) + consensus_estimates
→ analytics_valuation (ticker, fiscal_year, data_type) 밸류에이션 종합 테이블

- data_type='actual': 확정 실적 (financial_statements 기반)
- data_type='estimate': 컨센서스 추정치 (consensus_estimates 기반)
- PER/PBR/ROE/ROA/영업이익률/순이익률 pre-computed
- YoY 성장률 (매출/영업이익/순이익) 계산
- 전체 재처리 방식 (재무제표는 소량, 빠름)
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.db import get_pg_conn
from utils.config import PG_CONN_INFO
from utils.lineage import register_table_lineage_async
import logging

logger = logging.getLogger(__name__)


UPSERT_ACTUAL_SQL = """
INSERT INTO analytics_valuation (
    ticker, fiscal_year, data_type,
    stock_name, market_type, market_value, market_value_krw,
    revenue, gross_profit, operating_profit, net_income,
    total_assets, total_equity, total_liabilities, cash_from_operating,
    per_actual, pbr_actual, roe_actual, roa_actual,
    operating_margin, net_margin, debt_ratio, equity_ratio,
    revenue_growth, op_profit_growth, net_income_growth,
    est_per, est_pbr, est_roe, analyst_rating, target_price, analyst_count,
    updated_at
)
WITH
-- 연간 재무제표만 사용
fs AS (
    SELECT * FROM financial_statements
    WHERE report_type = 'annual'
),
-- 전년도 재무: YoY 성장률 계산용
fs_prev AS (
    SELECT
        ticker,
        fiscal_year + 1              AS fiscal_year,   -- 비교 기준을 다음 연도로 shift
        revenue                      AS prev_revenue,
        operating_profit             AS prev_op_profit,
        net_income                   AS prev_net_income
    FROM financial_statements
    WHERE report_type = 'annual'
),
-- 컨센서스: 티커별 최신 1건
latest_consensus AS (
    SELECT DISTINCT ON (ticker)
        ticker,
        rating          AS analyst_rating,
        target_price,
        analyst_count,
        est_per,
        est_pbr,
        est_roe
    FROM consensus_estimates
    ORDER BY ticker, estimate_year DESC, collected_at DESC
)
SELECT
    fs.ticker,
    fs.fiscal_year,
    'actual'::varchar AS data_type,
    -- 종목 기본 정보 (최신 시총)
    si.stock_name,
    si.market_type,
    si.market_value,
    si.market_value * 100000000                                             AS market_value_krw,

    -- 재무제표 원본
    fs.revenue,
    fs.gross_profit,
    fs.operating_profit,
    fs.net_income,
    fs.total_assets,
    fs.total_equity,
    fs.total_liabilities,
    fs.cash_from_operating,

    -- ── 계산 밸류에이션 지표 ────────────────────────────────────────────────
    -- PER: 시총(원) / 순이익. 순손실이면 NULL
    CASE
        WHEN fs.net_income > 0 AND si.market_value IS NOT NULL
        THEN ROUND((si.market_value * 100000000.0 / fs.net_income)::numeric, 4)
    END                                                                     AS per_actual,

    -- PBR: 시총(원) / 자본총계
    CASE
        WHEN fs.total_equity > 0 AND si.market_value IS NOT NULL
        THEN ROUND((si.market_value * 100000000.0 / fs.total_equity)::numeric, 4)
    END                                                                     AS pbr_actual,

    -- ROE: 순이익 / 자본총계 × 100 (%)
    CASE
        WHEN fs.total_equity > 0
             AND ABS(fs.net_income * 100.0 / fs.total_equity) <= 9999
        THEN ROUND((fs.net_income * 100.0 / fs.total_equity)::numeric, 4)
    END                                                                     AS roe_actual,

    -- ROA: 순이익 / 자산총계 × 100 (%)
    CASE
        WHEN fs.total_assets > 0
             AND ABS(fs.net_income * 100.0 / fs.total_assets) <= 9999
        THEN ROUND((fs.net_income * 100.0 / fs.total_assets)::numeric, 4)
    END                                                                     AS roa_actual,

    -- 영업이익률: 영업이익 / 매출 × 100 (%)
    CASE
        WHEN fs.revenue > 0
             AND ABS(fs.operating_profit * 100.0 / fs.revenue) <= 9999
        THEN ROUND((fs.operating_profit * 100.0 / fs.revenue)::numeric, 4)
    END                                                                     AS operating_margin,

    -- 순이익률: 순이익 / 매출 × 100 (%)
    CASE
        WHEN fs.revenue > 0
             AND ABS(fs.net_income * 100.0 / fs.revenue) <= 9999
        THEN ROUND((fs.net_income * 100.0 / fs.revenue)::numeric, 4)
    END                                                                     AS net_margin,

    -- 부채비율: 부채 / 자본 × 100 (%)
    CASE
        WHEN fs.total_equity > 0
             AND ABS(fs.total_liabilities * 100.0 / fs.total_equity) <= 9999
        THEN ROUND((fs.total_liabilities * 100.0 / fs.total_equity)::numeric, 4)
    END                                                                     AS debt_ratio,

    -- 자기자본비율: 자본 / 자산 × 100 (%)
    CASE
        WHEN fs.total_assets > 0
        THEN ROUND((fs.total_equity * 100.0 / fs.total_assets)::numeric, 4)
    END                                                                     AS equity_ratio,

    -- ── YoY 성장률 ─────────────────────────────────────────────────────────
    CASE
        WHEN fp.prev_revenue > 0
             AND ABS((fs.revenue - fp.prev_revenue) * 100.0 / fp.prev_revenue) <= 9999
        THEN ROUND(((fs.revenue - fp.prev_revenue) * 100.0 / fp.prev_revenue)::numeric, 4)
    END                                                                     AS revenue_growth,

    CASE
        WHEN fp.prev_op_profit > 0
             AND ABS((fs.operating_profit - fp.prev_op_profit) * 100.0 / fp.prev_op_profit) <= 9999
        THEN ROUND(((fs.operating_profit - fp.prev_op_profit) * 100.0 / fp.prev_op_profit)::numeric, 4)
    END                                                                     AS op_profit_growth,

    CASE
        WHEN fp.prev_net_income > 0
             AND ABS((fs.net_income - fp.prev_net_income) * 100.0 / fp.prev_net_income) <= 9999
        THEN ROUND(((fs.net_income - fp.prev_net_income) * 100.0 / fp.prev_net_income)::numeric, 4)
    END                                                                     AS net_income_growth,

    -- ── 컨센서스 ────────────────────────────────────────────────────────────
    ce.est_per,
    ce.est_pbr,
    ce.est_roe,
    ce.analyst_rating,
    ce.target_price,
    ce.analyst_count,

    NOW()

FROM fs
JOIN stock_info si ON fs.ticker = si.ticker
LEFT JOIN fs_prev fp ON fs.ticker = fp.ticker AND fs.fiscal_year = fp.fiscal_year
LEFT JOIN latest_consensus ce ON fs.ticker = ce.ticker

ON CONFLICT (ticker, fiscal_year, data_type) DO UPDATE SET
    stock_name          = EXCLUDED.stock_name,
    market_type         = EXCLUDED.market_type,
    market_value        = EXCLUDED.market_value,
    market_value_krw    = EXCLUDED.market_value_krw,
    revenue             = EXCLUDED.revenue,
    gross_profit        = EXCLUDED.gross_profit,
    operating_profit    = EXCLUDED.operating_profit,
    net_income          = EXCLUDED.net_income,
    total_assets        = EXCLUDED.total_assets,
    total_equity        = EXCLUDED.total_equity,
    total_liabilities   = EXCLUDED.total_liabilities,
    cash_from_operating = EXCLUDED.cash_from_operating,
    per_actual          = EXCLUDED.per_actual,
    pbr_actual          = EXCLUDED.pbr_actual,
    roe_actual          = EXCLUDED.roe_actual,
    roa_actual          = EXCLUDED.roa_actual,
    operating_margin    = EXCLUDED.operating_margin,
    net_margin          = EXCLUDED.net_margin,
    debt_ratio          = EXCLUDED.debt_ratio,
    equity_ratio        = EXCLUDED.equity_ratio,
    revenue_growth      = EXCLUDED.revenue_growth,
    op_profit_growth    = EXCLUDED.op_profit_growth,
    net_income_growth   = EXCLUDED.net_income_growth,
    est_per             = EXCLUDED.est_per,
    est_pbr             = EXCLUDED.est_pbr,
    est_roe             = EXCLUDED.est_roe,
    analyst_rating      = EXCLUDED.analyst_rating,
    target_price        = EXCLUDED.target_price,
    analyst_count       = EXCLUDED.analyst_count,
    updated_at          = NOW()
"""


UPSERT_ESTIMATE_SQL = """
INSERT INTO analytics_valuation (
    ticker, fiscal_year, data_type,
    stock_name, market_type, market_value, market_value_krw,
    revenue, operating_profit, net_income,
    total_assets, total_equity, total_liabilities,
    per_actual, pbr_actual, roe_actual,
    operating_margin, net_margin,
    est_per, est_pbr, est_roe, analyst_rating, target_price, analyst_count,
    updated_at
)
SELECT
    ce.ticker,
    ce.estimate_year AS fiscal_year,
    'estimate'::varchar AS data_type,

    si.stock_name,
    si.market_type,
    si.market_value,
    si.market_value * 100000000 AS market_value_krw,

    -- 컨센서스 추정 실적 (consensus_estimates는 억원 단위 → 원 단위로 변환)
    ce.est_revenue * 100000000 AS revenue,
    ce.est_operating_profit * 100000000 AS operating_profit,
    ce.est_net_income * 100000000 AS net_income,

    NULL AS total_assets,
    NULL AS total_equity,
    NULL AS total_liabilities,

    -- 추정 밸류에이션
    ce.est_per AS per_actual,
    ce.est_pbr AS pbr_actual,
    ce.est_roe AS roe_actual,

    -- 추정 마진 계산
    CASE WHEN ce.est_revenue > 0 THEN
        ROUND((ce.est_operating_profit * 100.0 / ce.est_revenue)::numeric, 4)
    END AS operating_margin,
    CASE WHEN ce.est_revenue > 0 THEN
        ROUND((ce.est_net_income * 100.0 / ce.est_revenue)::numeric, 4)
    END AS net_margin,

    ce.est_per, ce.est_pbr, ce.est_roe,
    ce.rating AS analyst_rating,
    ce.target_price,
    ce.analyst_count,

    NOW()

FROM consensus_estimates ce
JOIN stock_info si ON ce.ticker = si.ticker
WHERE ce.est_revenue IS NOT NULL AND ce.est_revenue > 0

ON CONFLICT (ticker, fiscal_year, data_type) DO UPDATE SET
    stock_name          = EXCLUDED.stock_name,
    market_type         = EXCLUDED.market_type,
    market_value        = EXCLUDED.market_value,
    market_value_krw    = EXCLUDED.market_value_krw,
    revenue             = EXCLUDED.revenue,
    operating_profit    = EXCLUDED.operating_profit,
    net_income          = EXCLUDED.net_income,
    per_actual          = EXCLUDED.per_actual,
    pbr_actual          = EXCLUDED.pbr_actual,
    roe_actual          = EXCLUDED.roe_actual,
    operating_margin    = EXCLUDED.operating_margin,
    net_margin          = EXCLUDED.net_margin,
    est_per             = EXCLUDED.est_per,
    est_pbr             = EXCLUDED.est_pbr,
    est_roe             = EXCLUDED.est_roe,
    analyst_rating      = EXCLUDED.analyst_rating,
    target_price        = EXCLUDED.target_price,
    analyst_count       = EXCLUDED.analyst_count,
    updated_at          = NOW()
"""


ESTIMATE_GROWTH_SQL = """
UPDATE analytics_valuation est
SET
    revenue_growth = CASE
        WHEN prev.revenue > 0
             AND ABS((est.revenue - prev.revenue) * 100.0 / prev.revenue) <= 9999
        THEN ROUND(((est.revenue - prev.revenue) * 100.0 / prev.revenue)::numeric, 4)
    END,
    op_profit_growth = CASE
        WHEN prev.operating_profit > 0
             AND ABS((est.operating_profit - prev.operating_profit) * 100.0 / prev.operating_profit) <= 9999
        THEN ROUND(((est.operating_profit - prev.operating_profit) * 100.0 / prev.operating_profit)::numeric, 4)
    END,
    net_income_growth = CASE
        WHEN prev.net_income > 0
             AND ABS((est.net_income - prev.net_income) * 100.0 / prev.net_income) <= 9999
        THEN ROUND(((est.net_income - prev.net_income) * 100.0 / prev.net_income)::numeric, 4)
    END,
    updated_at = NOW()
FROM analytics_valuation prev
WHERE est.data_type = 'estimate'
  AND prev.data_type = 'actual'
  AND est.ticker = prev.ticker
  AND est.fiscal_year = prev.fiscal_year + 1
  AND prev.revenue IS NOT NULL
"""


def build_analytics_valuation(**context):
    """financial_statements + stock_info + consensus → analytics_valuation (actual + estimate)"""
    with get_pg_conn(PG_CONN_INFO) as conn:
        with conn.cursor() as cur:
            # 1) 확정 실적 (data_type='actual')
            cur.execute(UPSERT_ACTUAL_SQL)
            actual_count = cur.rowcount

            # 2) 컨센서스 추정치 (data_type='estimate')
            cur.execute(UPSERT_ESTIMATE_SQL)
            estimate_count = cur.rowcount

            # 3) 추정치 YoY 성장률 계산 (전년 actual 대비)
            cur.execute(ESTIMATE_GROWTH_SQL)
            growth_count = cur.rowcount

        conn.commit()
        logger.info(f"analytics_valuation upsert 완료: actual={actual_count}행, estimate={estimate_count}행, growth_update={growth_count}행")

    register_table_lineage_async(
        "analytics_valuation",
        source_tables=["financial_statements", "stock_info", "consensus_estimates"]
    )


default_args = {
    "owner": "airflow",
    "start_date": datetime(2025, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="09_analytics_valuation",
    default_args=default_args,
    description="Gold layer: stock_info + financial_statements(annual) + consensus → analytics_valuation (매일 시총 반영)",
    schedule_interval="0 9 * * 1-5",   # 평일 18:00 KST = UTC 09:00 (한국장 마감 후 시총 반영)
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    tags=["gold", "financial", "daily"],
) as dag:

    build_task = PythonOperator(
        task_id="build_analytics_valuation",
        python_callable=build_analytics_valuation,
        execution_timeout=timedelta(minutes=20),
    )
