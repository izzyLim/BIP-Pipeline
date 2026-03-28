"""
[09_analytics_macro_daily]
Gold layer: macro_indicators (EAV) → analytics_macro_daily (pivot)

- macro_indicators의 indicator_type/region 조합을 일별 1행 컬럼 구조로 변환
- 월별/주별 지표는 window 함수로 forward-fill 적용
- 증분 적재: analytics_macro_daily의 마지막 날짜 이후 데이터만 처리
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
from utils.db import get_pg_conn
from utils.config import PG_CONN_INFO
from utils.lineage import register_table_lineage_async
import logging

logger = logging.getLogger(__name__)


UPSERT_SQL = """
INSERT INTO analytics_macro_daily (
    indicator_date,
    -- 글로벌 변동성/심리
    vix, vkospi, fear_greed_index, global_risk_index,
    -- 미국 금리
    us_10y, us_5y, us_3m, us_yield_curve,
    -- 미국 주요 지수
    sp500, nasdaq, sox, etf_smh, etf_soxx,
    -- 원자재
    oil_wti, gold, copper, btc,
    -- 환율
    usd_krw, usd_cny, usd_jpy, dollar_index,
    -- 한국 금리
    kr_base_rate, kr_call_rate, kr_cd_91d, kr_cofix_new, kr_govt_3y, kr_corp_3y,
    -- 한국 주요 지수
    kospi, kosdaq,
    -- 한국 경제지표 (forward-fill)
    kr_cpi_yoy, kr_export_growth, kr_gdp_growth,
    -- 글로벌 주요 지수
    nikkei, shanghai, eurostoxx,
    -- 지정학 리스크 점수
    risk_score_us, risk_score_cn, risk_score_eu, risk_score_jp, risk_score_kr,
    -- 뉴스 감성
    news_sentiment_overall, news_sentiment_economic, news_sentiment_geopolitical,
    -- 한국 섹터 ETF
    kr_sector_semiconductor, kr_sector_it, kr_sector_auto, kr_sector_banks,
    updated_at
)
WITH raw_pivot AS (
    SELECT
        indicator_date,
        -- 글로벌 변동성/심리
        MAX(CASE WHEN indicator_type='vix'              AND region='North America' THEN value END) AS vix,
        MAX(CASE WHEN indicator_type='vkospi'           AND region='South Korea'  THEN value END) AS vkospi,
        MAX(CASE WHEN indicator_type='fear_greed_index' AND region='North America' THEN value END) AS fear_greed_index,
        MAX(CASE WHEN indicator_type='global_risk_index' AND region='North America' THEN value END) AS global_risk_index,
        -- 미국 금리
        MAX(CASE WHEN indicator_type='interest_rate_10y' AND region='North America' THEN value END) AS us_10y,
        MAX(CASE WHEN indicator_type='interest_rate_5y'  AND region='North America' THEN value END) AS us_5y,
        MAX(CASE WHEN indicator_type='interest_rate_3m'  AND region='North America' THEN value END) AS us_3m,
        -- 미국 주요 지수
        MAX(CASE WHEN indicator_type='stock_index_sp500'  AND region='North America' THEN value END) AS sp500,
        MAX(CASE WHEN indicator_type='stock_index_nasdaq' AND region='North America' THEN value END) AS nasdaq,
        MAX(CASE WHEN indicator_type='index_sox'          AND region='North America' THEN value END) AS sox,
        MAX(CASE WHEN indicator_type='etf_smh'            AND region='North America' THEN value END) AS etf_smh,
        MAX(CASE WHEN indicator_type='etf_soxx'           AND region='North America' THEN value END) AS etf_soxx,
        -- 원자재
        MAX(CASE WHEN indicator_type='commodity_oil'    AND region='North America' THEN value END) AS oil_wti,
        MAX(CASE WHEN indicator_type='commodity_gold'   AND region='North America' THEN value END) AS gold,
        MAX(CASE WHEN indicator_type='commodity_copper' AND region='North America' THEN value END) AS copper,
        MAX(CASE WHEN indicator_type='crypto_btc'       AND region='North America' THEN value END) AS btc,
        -- 환율 (각 region의 exchange_rate = 해당 통화/USD 기준)
        MAX(CASE WHEN indicator_type='exchange_rate' AND region='South Korea'   THEN value END) AS usd_krw,
        MAX(CASE WHEN indicator_type='exchange_rate' AND region='China'         THEN value END) AS usd_cny,
        MAX(CASE WHEN indicator_type='exchange_rate' AND region='Japan'         THEN value END) AS usd_jpy,
        MAX(CASE WHEN indicator_type='dollar_index'  AND region='North America' THEN value END) AS dollar_index,
        -- 한국 금리
        MAX(CASE WHEN indicator_type='korea_base_rate' AND region='South Korea' THEN value END) AS kr_base_rate,
        MAX(CASE WHEN indicator_type='korea_call_rate' AND region='South Korea' THEN value END) AS kr_call_rate,
        MAX(CASE WHEN indicator_type='korea_cd_91d'    AND region='South Korea' THEN value END) AS kr_cd_91d,
        MAX(CASE WHEN indicator_type='korea_cofix_new' AND region='South Korea' THEN value END) AS kr_cofix_new,
        MAX(CASE WHEN indicator_type='korea_govt_3y'   AND region='South Korea' THEN value END) AS kr_govt_3y,
        MAX(CASE WHEN indicator_type='korea_corp_3y'   AND region='South Korea' THEN value END) AS kr_corp_3y,
        -- 한국 주요 지수
        MAX(CASE WHEN indicator_type='stock_index_kospi'  AND region='South Korea' THEN value END) AS kospi,
        MAX(CASE WHEN indicator_type='stock_index_kosdaq' AND region='South Korea' THEN value END) AS kosdaq,
        -- 한국 경제지표 (월별)
        MAX(CASE WHEN indicator_type='korea_cpi_yoy'      AND region='South Korea' THEN value END) AS kr_cpi_yoy,
        MAX(CASE WHEN indicator_type='korea_export_growth' AND region='South Korea' THEN value END) AS kr_export_growth,
        MAX(CASE WHEN indicator_type='korea_gdp_growth'   AND region='South Korea' THEN value END) AS kr_gdp_growth,
        -- 글로벌 주요 지수
        MAX(CASE WHEN indicator_type='stock_index_nikkei'    AND region='Japan'          THEN value END) AS nikkei,
        MAX(CASE WHEN indicator_type='stock_index_shanghai'  AND region='China'          THEN value END) AS shanghai,
        MAX(CASE WHEN indicator_type='stock_index_eurostoxx' AND region='Western Europe' THEN value END) AS eurostoxx,
        -- 지정학 리스크
        MAX(CASE WHEN indicator_type='risk_score_us' AND region='North America'  THEN value END) AS risk_score_us,
        MAX(CASE WHEN indicator_type='risk_score_cn' AND region='China'          THEN value END) AS risk_score_cn,
        MAX(CASE WHEN indicator_type='risk_score_eu' AND region='Western Europe' THEN value END) AS risk_score_eu,
        MAX(CASE WHEN indicator_type='risk_score_jp' AND region='Japan'          THEN value END) AS risk_score_jp,
        MAX(CASE WHEN indicator_type='risk_score_kr' AND region='South Korea'    THEN value END) AS risk_score_kr,
        -- 뉴스 감성
        MAX(CASE WHEN indicator_type='news_sentiment_overall'      AND region='North America' THEN value END) AS news_sentiment_overall,
        MAX(CASE WHEN indicator_type='news_sentiment_economic'     AND region='North America' THEN value END) AS news_sentiment_economic,
        MAX(CASE WHEN indicator_type='news_sentiment_geopolitical' AND region='North America' THEN value END) AS news_sentiment_geopolitical,
        -- 한국 섹터 ETF
        MAX(CASE WHEN indicator_type='sector_kr_semiconductor' AND region='South Korea' THEN value END) AS kr_sector_semiconductor,
        MAX(CASE WHEN indicator_type='sector_kr_it'            AND region='South Korea' THEN value END) AS kr_sector_it,
        MAX(CASE WHEN indicator_type='sector_kr_auto'          AND region='South Korea' THEN value END) AS kr_sector_auto,
        MAX(CASE WHEN indicator_type='sector_kr_banks'         AND region='South Korea' THEN value END) AS kr_sector_banks
    FROM macro_indicators
    WHERE indicator_date >= %(start_date)s
      AND indicator_date <= %(end_date)s
    GROUP BY indicator_date
),
-- forward-fill: 월별 지표는 직전 값으로 채움
forward_filled AS (
    SELECT
        indicator_date,
        vix, vkospi, fear_greed_index, global_risk_index,
        us_10y, us_5y, us_3m,
        COALESCE(us_10y, 0) - COALESCE(us_3m, 0) AS us_yield_curve,
        sp500, nasdaq, sox, etf_smh, etf_soxx,
        oil_wti, gold, copper, btc,
        usd_krw, usd_cny, usd_jpy, dollar_index,
        -- 월별 지표: forward-fill (LAST non-NULL value)
        MAX(kr_base_rate) OVER w AS kr_base_rate,
        kr_call_rate, kr_cd_91d,
        MAX(kr_cofix_new) OVER w AS kr_cofix_new,
        kr_govt_3y, kr_corp_3y,
        kospi, kosdaq,
        MAX(kr_cpi_yoy)      OVER w AS kr_cpi_yoy,
        MAX(kr_export_growth) OVER w AS kr_export_growth,
        MAX(kr_gdp_growth)   OVER w AS kr_gdp_growth,
        nikkei, shanghai, eurostoxx,
        risk_score_us, risk_score_cn, risk_score_eu, risk_score_jp, risk_score_kr,
        news_sentiment_overall, news_sentiment_economic, news_sentiment_geopolitical,
        kr_sector_semiconductor, kr_sector_it, kr_sector_auto, kr_sector_banks
    FROM raw_pivot
    WINDOW w AS (ORDER BY indicator_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT
    indicator_date,
    vix, vkospi, fear_greed_index, global_risk_index,
    us_10y, us_5y, us_3m, us_yield_curve,
    sp500, nasdaq, sox, etf_smh, etf_soxx,
    oil_wti, gold, copper, btc,
    usd_krw, usd_cny, usd_jpy, dollar_index,
    kr_base_rate, kr_call_rate, kr_cd_91d, kr_cofix_new, kr_govt_3y, kr_corp_3y,
    kospi, kosdaq,
    kr_cpi_yoy, kr_export_growth, kr_gdp_growth,
    nikkei, shanghai, eurostoxx,
    risk_score_us, risk_score_cn, risk_score_eu, risk_score_jp, risk_score_kr,
    news_sentiment_overall, news_sentiment_economic, news_sentiment_geopolitical,
    kr_sector_semiconductor, kr_sector_it, kr_sector_auto, kr_sector_banks,
    NOW()
FROM forward_filled
ON CONFLICT (indicator_date) DO UPDATE SET
    vix                         = EXCLUDED.vix,
    vkospi                      = EXCLUDED.vkospi,
    fear_greed_index            = EXCLUDED.fear_greed_index,
    global_risk_index           = EXCLUDED.global_risk_index,
    us_10y                      = EXCLUDED.us_10y,
    us_5y                       = EXCLUDED.us_5y,
    us_3m                       = EXCLUDED.us_3m,
    us_yield_curve              = EXCLUDED.us_yield_curve,
    sp500                       = EXCLUDED.sp500,
    nasdaq                      = EXCLUDED.nasdaq,
    sox                         = EXCLUDED.sox,
    etf_smh                     = EXCLUDED.etf_smh,
    etf_soxx                    = EXCLUDED.etf_soxx,
    oil_wti                     = EXCLUDED.oil_wti,
    gold                        = EXCLUDED.gold,
    copper                      = EXCLUDED.copper,
    btc                         = EXCLUDED.btc,
    usd_krw                     = EXCLUDED.usd_krw,
    usd_cny                     = EXCLUDED.usd_cny,
    usd_jpy                     = EXCLUDED.usd_jpy,
    dollar_index                = EXCLUDED.dollar_index,
    kr_base_rate                = EXCLUDED.kr_base_rate,
    kr_call_rate                = EXCLUDED.kr_call_rate,
    kr_cd_91d                   = EXCLUDED.kr_cd_91d,
    kr_cofix_new                = EXCLUDED.kr_cofix_new,
    kr_govt_3y                  = EXCLUDED.kr_govt_3y,
    kr_corp_3y                  = EXCLUDED.kr_corp_3y,
    kospi                       = EXCLUDED.kospi,
    kosdaq                      = EXCLUDED.kosdaq,
    kr_cpi_yoy                  = EXCLUDED.kr_cpi_yoy,
    kr_export_growth            = EXCLUDED.kr_export_growth,
    kr_gdp_growth               = EXCLUDED.kr_gdp_growth,
    nikkei                      = EXCLUDED.nikkei,
    shanghai                    = EXCLUDED.shanghai,
    eurostoxx                   = EXCLUDED.eurostoxx,
    risk_score_us               = EXCLUDED.risk_score_us,
    risk_score_cn               = EXCLUDED.risk_score_cn,
    risk_score_eu               = EXCLUDED.risk_score_eu,
    risk_score_jp               = EXCLUDED.risk_score_jp,
    risk_score_kr               = EXCLUDED.risk_score_kr,
    news_sentiment_overall      = EXCLUDED.news_sentiment_overall,
    news_sentiment_economic     = EXCLUDED.news_sentiment_economic,
    news_sentiment_geopolitical = EXCLUDED.news_sentiment_geopolitical,
    kr_sector_semiconductor     = EXCLUDED.kr_sector_semiconductor,
    kr_sector_it                = EXCLUDED.kr_sector_it,
    kr_sector_auto              = EXCLUDED.kr_sector_auto,
    kr_sector_banks             = EXCLUDED.kr_sector_banks,
    updated_at                  = NOW()
"""


def build_analytics_macro(**context):
    """macro_indicators → analytics_macro_daily 증분 pivot"""
    with get_pg_conn(PG_CONN_INFO) as conn:
        with conn.cursor() as cur:
            # 마지막 적재일 조회
            cur.execute("SELECT MAX(indicator_date) FROM analytics_macro_daily")
            last_date = cur.fetchone()[0]

        if last_date is None:
            # 최초 실행: macro_indicators 전체 범위
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(indicator_date) FROM macro_indicators WHERE indicator_date >= '2025-01-01'")
                start_date = cur.fetchone()[0]
        else:
            start_date = last_date  # 마지막 날짜도 재처리 (당일 데이터 업데이트 반영)

        today = datetime.utcnow().date()
        logger.info(f"analytics_macro_daily 적재: {start_date} ~ {today}")

        with conn.cursor() as cur:
            cur.execute(UPSERT_SQL, {"start_date": start_date, "end_date": today})
            row_count = cur.rowcount

        conn.commit()
        logger.info(f"analytics_macro_daily upsert 완료: {row_count}행")

        register_table_lineage_async(
            "analytics_macro_daily",
            source_tables=["macro_indicators"]
        )


default_args = {
    "owner": "airflow",
    "start_date": datetime(2025, 1, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="09_analytics_macro_daily",
    default_args=default_args,
    description="Gold layer: macro_indicators EAV → analytics_macro_daily pivot (일별 1행)",
    schedule_interval="0 * * * *",       # 매시간 정각 (macro_indicators 수집 DAG와 동일 주기)
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    tags=["gold", "macro", "daily"],
) as dag:

    build_task = PythonOperator(
        task_id="build_analytics_macro",
        python_callable=build_analytics_macro,
        execution_timeout=timedelta(minutes=20),
    )
