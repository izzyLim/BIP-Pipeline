-- ============================================
-- 뉴스 데이터베이스 스키마
-- 수요예측 설명 에이전트용
-- ============================================

-- pgvector 확장 (벡터 유사도 검색용)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- ENUM 타입 정의
-- ============================================
CREATE TYPE news_type AS ENUM ('smartphone', 'external_factor');
CREATE TYPE factor_type AS ENUM ('geopolitics', 'economy', 'supply_chain', 'regulation', 'disaster');
CREATE TYPE segment_type AS ENUM ('entry', 'mid-range', 'flagship');
CREATE TYPE region_type AS ENUM (
    'North America', 'Western Europe', 'Central Europe',
    'China', 'India', 'Japan', 'South Korea', 'Southeast Asia',
    'MEA', 'CALA', 'Asia Pacific Others'
);

-- ============================================
-- 1. 원본 데이터 테이블 (Raw Layer)
-- ============================================
CREATE TABLE news_raw (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    source VARCHAR(200),
    collection_date DATE NOT NULL,
    published_date DATE,

    -- GDELT 원본 필드
    themes TEXT,
    organizations TEXT,
    locations TEXT,
    tone_raw VARCHAR(100),

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(url, collection_date)
);

CREATE INDEX idx_news_raw_collection_date ON news_raw(collection_date);
CREATE INDEX idx_news_raw_published_date ON news_raw(published_date);

-- ============================================
-- 2. 정제된 뉴스 테이블 (Enriched Layer)
-- ============================================
CREATE TABLE news_article (
    id BIGSERIAL PRIMARY KEY,
    raw_id BIGINT REFERENCES news_raw(id),

    -- 기본 정보
    url TEXT NOT NULL UNIQUE,
    source VARCHAR(200),
    title TEXT,
    published_date DATE NOT NULL,

    -- 분류
    news_type news_type NOT NULL,

    -- 스마트폰 관련 (news_type = 'smartphone')
    brands TEXT[],

    -- 외부 요인 관련 (news_type = 'external_factor')
    factor factor_type,

    -- 권역 (Counterpoint 기준)
    regions region_type[],
    country_codes TEXT[],

    -- 감성 분석
    tone_score FLOAT,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_news_article_published_date ON news_article(published_date);
CREATE INDEX idx_news_article_news_type ON news_article(news_type);
CREATE INDEX idx_news_article_factor ON news_article(factor);
CREATE INDEX idx_news_article_regions ON news_article USING GIN(regions);
CREATE INDEX idx_news_article_brands ON news_article USING GIN(brands);

-- ============================================
-- 3. 벡터 임베딩 테이블 (Vector Layer)
-- ============================================
CREATE TABLE news_embedding (
    id BIGSERIAL PRIMARY KEY,
    article_id BIGINT REFERENCES news_article(id) ON DELETE CASCADE,

    embedding vector(1536),
    model_name VARCHAR(50) DEFAULT 'text-embedding-3-small',
    text_used TEXT,

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(article_id)
);

CREATE INDEX idx_news_embedding_vector
    ON news_embedding
    USING hnsw (embedding vector_cosine_ops);

-- ============================================
-- 4. 일별 요약 테이블 (Aggregation Layer)
-- ============================================
CREATE TABLE news_daily_summary (
    id BIGSERIAL PRIMARY KEY,

    summary_date DATE NOT NULL,
    region region_type NOT NULL,

    -- 스마트폰 뉴스 통계
    smartphone_count INT DEFAULT 0,
    smartphone_avg_tone FLOAT,

    -- 외부 요인별 통계
    geopolitics_count INT DEFAULT 0,
    geopolitics_avg_tone FLOAT,

    economy_count INT DEFAULT 0,
    economy_avg_tone FLOAT,

    supply_chain_count INT DEFAULT 0,
    supply_chain_avg_tone FLOAT,

    regulation_count INT DEFAULT 0,
    regulation_avg_tone FLOAT,

    disaster_count INT DEFAULT 0,
    disaster_avg_tone FLOAT,

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(summary_date, region)
);

CREATE INDEX idx_news_daily_summary_date ON news_daily_summary(summary_date);

-- ============================================
-- 5. 제품 출시 테이블 (Reference)
-- ============================================
CREATE TABLE product_release (
    id SERIAL PRIMARY KEY,

    brand VARCHAR(50) NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    segment segment_type NOT NULL,

    announce_date DATE,
    release_date DATE,

    regions region_type[],

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(brand, product_name)
);

CREATE INDEX idx_product_release_date ON product_release(release_date);
CREATE INDEX idx_product_release_brand ON product_release(brand);
CREATE INDEX idx_product_release_segment ON product_release(segment);

-- ============================================
-- 6. 거시지표 테이블 (Context)
-- ============================================
CREATE TABLE macro_indicators (
    id BIGSERIAL PRIMARY KEY,

    indicator_date DATE NOT NULL,
    region region_type NOT NULL,

    indicator_type VARCHAR(50) NOT NULL,  -- exchange_rate, interest_rate, pmi, oil_price, etc.
    value FLOAT,
    change_pct FLOAT,  -- 전월/전주 대비

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(indicator_date, region, indicator_type)
);

CREATE INDEX idx_macro_indicators_date ON macro_indicators(indicator_date);
