{{ config(
    materialized='table',
    indexes=[
        {'columns': ['ticker', 'trade_date'], 'unique': true},
        {'columns': ['trade_date']}
    ]
) }}

-- 종목×일자 Gold 와이드 테이블
-- BIP의 analytics_stock_daily 대응

SELECT
    p.ticker,
    i.stock_name,
    i.market_type,
    i.sector,
    p.trade_date,
    p.open_price,
    p.high_price,
    p.low_price,
    p.close_price,
    p.volume,
    p.trading_value_calc,
    p.prev_close,
    p.change_pct,
    p.foreign_buy_volume,
    p.institution_buy_volume,
    p.individual_buy_volume,
    p.foreign_ownership_pct,
    -- 해석 컬럼 (BIP 패턴)
    CASE
        WHEN p.foreign_buy_volume IS NULL THEN '데이터없음'
        WHEN p.foreign_buy_volume > 0 THEN '순매수'
        WHEN p.foreign_buy_volume < 0 THEN '순매도'
        ELSE '보합'
    END AS foreign_direction,
    CASE
        WHEN p.change_pct IS NULL THEN '데이터없음'
        WHEN p.change_pct >= 3 THEN '강한 상승'
        WHEN p.change_pct >= 1 THEN '상승'
        WHEN p.change_pct > -1 THEN '보합'
        WHEN p.change_pct > -3 THEN '하락'
        ELSE '강한 하락'
    END AS change_label
FROM {{ ref('stg_stock_price') }} p
JOIN {{ ref('stg_stock_info') }} i ON p.ticker = i.ticker
