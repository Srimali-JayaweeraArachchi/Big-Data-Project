CREATE TABLE IF NOT EXISTS meter_readings_clean (
    event_id TEXT PRIMARY KEY,
    meter_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    power_consumption_kwh DOUBLE PRECISION NOT NULL CHECK (power_consumption_kwh >= 0),
    solar_generation_kwh DOUBLE PRECISION NOT NULL CHECK (solar_generation_kwh >= 0),
    net_grid_usage_kwh DOUBLE PRECISION NOT NULL,
    renewable_ratio DOUBLE PRECISION NOT NULL,
    grid_zone TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_readings_event_time ON meter_readings_clean(event_time DESC);
CREATE INDEX IF NOT EXISTS idx_readings_zone_time ON meter_readings_clean(grid_zone, event_time DESC);

CREATE TABLE IF NOT EXISTS rejected_events (
    id BIGSERIAL PRIMARY KEY,
    raw_payload TEXT NOT NULL,
    rejection_reason TEXT NOT NULL,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS zone_metrics (
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    grid_zone TEXT NOT NULL,
    total_consumption_kwh DOUBLE PRECISION NOT NULL,
    total_solar_kwh DOUBLE PRECISION NOT NULL,
    net_grid_load_kwh DOUBLE PRECISION NOT NULL,
    renewable_ratio DOUBLE PRECISION NOT NULL,
    reading_count BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (window_start, grid_zone)
);

CREATE TABLE IF NOT EXISTS household_usage_daily (
    usage_date DATE NOT NULL,
    household_id TEXT NOT NULL,
    total_consumption_kwh DOUBLE PRECISION NOT NULL,
    total_solar_kwh DOUBLE PRECISION NOT NULL,
    net_grid_usage_kwh DOUBLE PRECISION NOT NULL,
    reading_count BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (usage_date, household_id)
);

CREATE TABLE IF NOT EXISTS tariffs (
    household_id TEXT NOT NULL,
    effective_date DATE NOT NULL,
    tariff_rate DOUBLE PRECISION NOT NULL CHECK (tariff_rate > 0),
    billing_tier TEXT NOT NULL,
    subsidy_flag BOOLEAN NOT NULL,
    source_file TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (household_id, effective_date)
);

CREATE TABLE IF NOT EXISTS batch_ingestion_audit (
    source_file TEXT PRIMARY KEY,
    row_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_billing_report (
    report_date DATE NOT NULL,
    household_id TEXT NOT NULL,
    total_consumption_kwh DOUBLE PRECISION NOT NULL,
    total_solar_kwh DOUBLE PRECISION NOT NULL,
    billable_grid_kwh DOUBLE PRECISION NOT NULL,
    tariff_rate DOUBLE PRECISION NOT NULL,
    subsidy_flag BOOLEAN NOT NULL,
    estimated_bill DOUBLE PRECISION NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (report_date, household_id)
);

CREATE TABLE IF NOT EXISTS pipeline_alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    message TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    threshold_value DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS pipeline_heartbeats (
    service_name TEXT PRIMARY KEY,
    last_seen_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

