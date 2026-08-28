-- schema.sql: PostgreSQL schema for REVIVE
-- Optimized for PostgreSQL 16 with JSONB indexing and strict referential integrity

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Webhook Ingestion Events (Inbox)
CREATE TABLE IF NOT EXISTS webhook_events (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(128) UNIQUE NOT NULL,
    event_type VARCHAR(64) NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_status ON webhook_events(status);
CREATE INDEX IF NOT EXISTS idx_webhook_events_event_id ON webhook_events(event_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_payload_gin ON webhook_events USING gin (payload_json);

-- 2. Decision Records
CREATE TABLE IF NOT EXISTS decision_records (
    id BIGSERIAL PRIMARY KEY,
    decision_id VARCHAR(128) UNIQUE NOT NULL,
    case_id VARCHAR(128) NOT NULL,
    feature_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    action VARCHAR(64),
    policy_version VARCHAR(64),
    model_version VARCHAR(64),
    prompt_version VARCHAR(64),
    scenario_version VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decision_records_case_id ON decision_records(case_id);
CREATE INDEX IF NOT EXISTS idx_decision_records_decision_id ON decision_records(decision_id);
CREATE INDEX IF NOT EXISTS idx_decision_records_features_gin ON decision_records USING gin (feature_json);

-- 3. Execution Intents (Transactional Outbox)
CREATE TABLE IF NOT EXISTS execution_intents (
    id BIGSERIAL PRIMARY KEY,
    decision_id VARCHAR(128) UNIQUE NOT NULL REFERENCES decision_records(decision_id) ON DELETE CASCADE,
    case_id VARCHAR(128) NOT NULL,
    action VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    result_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_execution_intents_case_id ON execution_intents(case_id);
CREATE INDEX IF NOT EXISTS idx_execution_intents_status ON execution_intents(status);
CREATE INDEX IF NOT EXISTS idx_execution_intents_payload_gin ON execution_intents USING gin (payload_json);

-- 4. Immutable Audit Logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    decision_id VARCHAR(128) REFERENCES decision_records(decision_id) ON DELETE SET NULL,
    event_id VARCHAR(128),
    case_id VARCHAR(128) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_case_id ON audit_logs(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_decision_id ON audit_logs(decision_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_payload_gin ON audit_logs USING gin (payload_json);

-- 5. Human Approval Queue (Escalation)
CREATE TABLE IF NOT EXISTS approval_queue (
    id BIGSERIAL PRIMARY KEY,
    case_id VARCHAR(128) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    reason TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    reviewer VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_approval_queue_case_id ON approval_queue(case_id);
CREATE INDEX IF NOT EXISTS idx_approval_queue_payload_gin ON approval_queue USING gin (payload_json);

-- 6. Merchant Dynamic Configuration
CREATE TABLE IF NOT EXISTS merchant_config (
    id BIGINT PRIMARY KEY DEFAULT 1,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 7. Role-Based Access Control (RBAC) & Engine-Enforced Append-Only Audit
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'revive_app') THEN
        CREATE ROLE revive_app LOGIN PASSWORD 'revive_app_password';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE revive TO revive_app;
GRANT USAGE ON SCHEMA public TO revive_app;

-- Full read/write permissions on operational state tables
GRANT SELECT, INSERT, UPDATE, DELETE ON webhook_events, decision_records, execution_intents, approval_queue, merchant_config TO revive_app;

-- Strict append-only enforcement: INSERT and SELECT only (NO UPDATE, NO DELETE granted)
GRANT SELECT, INSERT ON audit_logs TO revive_app;

-- Sequence usage permissions for BIGSERIAL generation
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO revive_app;
