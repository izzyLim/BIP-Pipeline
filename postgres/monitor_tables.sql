-- 장중 모니터링 테이블
-- ============================================

-- 1. 체크리스트 룰 (모닝리포트 → Haiku 파싱 결과)
CREATE TABLE IF NOT EXISTS monitor_checklist (
    id BIGSERIAL PRIMARY KEY,
    rule_date DATE NOT NULL,                    -- 해당 날짜
    rule_order INT NOT NULL,                    -- 룰 순서
    rule_type VARCHAR(30) NOT NULL,             -- index_level, stock_change, fx_level, event, general
    original_text TEXT NOT NULL,                 -- 체크리스트 원문
    parsed_rule JSONB,                          -- 파싱된 구조화 룰
    triggered BOOLEAN DEFAULT FALSE,            -- 조건 충족 여부
    triggered_at TIMESTAMP,                     -- 조건 충족 시각
    triggered_value TEXT,                        -- 충족 시점의 실제 값
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(rule_date, rule_order)
);

CREATE INDEX idx_monitor_checklist_date ON monitor_checklist(rule_date);

-- 2. 알림 이력 (텔레그램 발송 기록)
CREATE TABLE IF NOT EXISTS monitor_alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_date DATE NOT NULL,                   -- 알림 날짜
    alert_time TIMESTAMP NOT NULL,              -- 알림 시각
    level VARCHAR(20) NOT NULL,                 -- 긴급, 주의, 참고, 체크리스트
    category VARCHAR(20) NOT NULL,              -- index, stock, fx, checklist
    title TEXT NOT NULL,
    description TEXT,
    data JSONB,                                 -- 원본 데이터
    checklist_id BIGINT REFERENCES monitor_checklist(id),  -- 체크리스트 룰 참조 (Layer 2만)
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_monitor_alerts_date ON monitor_alerts(alert_date);
CREATE INDEX idx_monitor_alerts_checklist ON monitor_alerts(checklist_id);
