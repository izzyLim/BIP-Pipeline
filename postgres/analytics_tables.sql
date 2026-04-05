-- 분석/사전 계산 테이블
-- ============================================

-- macro_indicators 복합 인덱스 (get_indicator_context 조회 성능)
CREATE INDEX IF NOT EXISTS idx_macro_indicators_type_region_date
    ON macro_indicators(indicator_type, region, indicator_date DESC);


-- 지표 시장 맥락 스냅샷 (일별 사전 계산)
-- BIP-Agents 체크리스트 모니터링 에이전트가 활용
CREATE TABLE IF NOT EXISTS indicator_context_snapshot (
    snapshot_date DATE NOT NULL,
    indicator_type VARCHAR(50) NOT NULL,
    region VARCHAR(50) NOT NULL DEFAULT '',

    -- 분류
    family VARCHAR(20) NOT NULL,                 -- fx, index, commodity, crypto, sentiment
    direction VARCHAR(20) NOT NULL,              -- higher_is_risk, higher_is_positive, neutral
    lookback_days INT NOT NULL DEFAULT 90,
    sample_size INT NOT NULL,

    -- 최신 DB 값
    latest_value NUMERIC(20,4),
    latest_value_date DATE,

    -- 90일 분포
    min_val NUMERIC(20,4),
    max_val NUMERIC(20,4),
    avg_val NUMERIC(20,4),
    median_val NUMERIC(20,4),
    stddev_val NUMERIC(20,4),

    -- 근사 percentile (스냅샷만으로 실시간 percentile 재현용)
    p10 NUMERIC(20,4),
    p25 NUMERIC(20,4),
    p50 NUMERIC(20,4),
    p75 NUMERIC(20,4),
    p90 NUMERIC(20,4),
    p95 NUMERIC(20,4),

    -- 추세/변동성
    avg_5d NUMERIC(20,4),
    avg_20d NUMERIC(20,4),
    volatility_20d_pct NUMERIC(10,4),
    trend_label VARCHAR(10),

    -- 극값 근접도
    days_from_high INT,
    days_from_low INT,

    created_at TIMESTAMP DEFAULT NOW(),

    PRIMARY KEY (snapshot_date, indicator_type, region)
);

CREATE INDEX IF NOT EXISTS idx_context_snapshot_date
    ON indicator_context_snapshot(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_context_snapshot_type
    ON indicator_context_snapshot(indicator_type, region);
