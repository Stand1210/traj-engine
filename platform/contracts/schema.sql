-- Traj Engine M0 storage schema.
-- M1 target is SQLite; types and syntax remain PostgreSQL-compatible.
-- JSON is stored as TEXT in M1. PostgreSQL migration may convert selected
-- columns to JSONB, but must preserve field names and constraints.

CREATE TABLE IF NOT EXISTS startup_records (
    id TEXT PRIMARY KEY,
    profile_name TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    base_url TEXT NOT NULL,
    langfuse_version TEXT,
    checked_at TEXT,
    skipped INTEGER NOT NULL CHECK (skipped IN (0, 1)),
    note TEXT
);

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    org_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    public_key TEXT NOT NULL,
    secret_key TEXT NOT NULL,
    queue_id TEXT,
    max_traces_per_run INTEGER NOT NULL DEFAULT 100000,
    max_runs_per_day INTEGER NOT NULL DEFAULT 24,
    max_concurrent_runs INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE (org_id, project_id)
);

CREATE TABLE IF NOT EXISTS ontologies (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('tier0', 'tier1')),
    current_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants (id)
);

CREATE TABLE IF NOT EXISTS ontology_versions (
    id TEXT PRIMARY KEY,
    ontology_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    yaml TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (ontology_id, version),
    FOREIGN KEY (ontology_id) REFERENCES ontologies (id)
);

CREATE TABLE IF NOT EXISTS prechecks (
    id TEXT PRIMARY KEY,
    ontology_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'warning', 'failed')),
    report_json TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (ontology_id) REFERENCES ontologies (id)
);

CREATE TABLE IF NOT EXISTS structure_versions (
    id TEXT PRIMARY KEY,
    ontology_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    code_hash TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    UNIQUE (ontology_id, version),
    FOREIGN KEY (ontology_id) REFERENCES ontologies (id)
);

CREATE TABLE IF NOT EXISTS cohort_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    ontology_id TEXT NOT NULL,
    ontology_version_id TEXT NOT NULL,
    structure_version_id TEXT,
    parent_run_id TEXT,
    run_type TEXT NOT NULL CHECK (run_type IN ('R1', 'R2', 'R3')),
    source TEXT NOT NULL CHECK (source IN ('jsonl', 'langfuse')),
    source_ref TEXT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    sampling_rate REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')),
    trigger_reason TEXT,
    error TEXT,
    idempotency_key TEXT,
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    FOREIGN KEY (tenant_id) REFERENCES tenants (id),
    FOREIGN KEY (ontology_id) REFERENCES ontologies (id),
    FOREIGN KEY (ontology_version_id) REFERENCES ontology_versions (id),
    FOREIGN KEY (structure_version_id) REFERENCES structure_versions (id),
    FOREIGN KEY (parent_run_id) REFERENCES cohort_runs (id),
    UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS run_steps (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'skipped')),
    payload_json TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    FOREIGN KEY (run_id) REFERENCES cohort_runs (id),
    UNIQUE (run_id, name)
);

CREATE TABLE IF NOT EXISTS cells (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    structure_version_id TEXT NOT NULL,
    cell_key TEXT NOT NULL,
    label TEXT,
    parent_id TEXT,
    dominant_action TEXT,
    size INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES cohort_runs (id),
    FOREIGN KEY (structure_version_id) REFERENCES structure_versions (id),
    FOREIGN KEY (parent_id) REFERENCES cells (id),
    UNIQUE (run_id, cell_key)
);

CREATE TABLE IF NOT EXISTS cell_lineage (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    old_cell_id TEXT NOT NULL,
    new_cell_id TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('continued', 'split', 'merged', 'born', 'died')),
    overlap REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES cohort_runs (id),
    FOREIGN KEY (old_cell_id) REFERENCES cells (id),
    FOREIGN KEY (new_cell_id) REFERENCES cells (id)
);

CREATE TABLE IF NOT EXISTS trace_scores (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    cell_id TEXT,
    total_score REAL NOT NULL,
    result_score REAL NOT NULL,
    process_score REAL NOT NULL,
    latency_score REAL NOT NULL,
    cost_score REAL NOT NULL,
    robustness_score REAL NOT NULL,
    deduction_total REAL NOT NULL,
    evidence_sum REAL NOT NULL,
    is_alert INTEGER NOT NULL CHECK (is_alert IN (0, 1)),
    is_abstain INTEGER NOT NULL CHECK (is_abstain IN (0, 1)),
    ontology_version_id TEXT NOT NULL,
    structure_version_id TEXT,
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES cohort_runs (id),
    FOREIGN KEY (tenant_id) REFERENCES tenants (id),
    FOREIGN KEY (cell_id) REFERENCES cells (id),
    FOREIGN KEY (ontology_version_id) REFERENCES ontology_versions (id),
    FOREIGN KEY (structure_version_id) REFERENCES structure_versions (id),
    UNIQUE (run_id, trace_id),
    CHECK (ABS(deduction_total - evidence_sum) < 0.0000001)
);

CREATE TABLE IF NOT EXISTS score_evidence (
    id TEXT PRIMARY KEY,
    trace_score_id TEXT NOT NULL,
    dimension TEXT NOT NULL CHECK (dimension IN ('result', 'process', 'latency', 'cost', 'robustness')),
    span_id TEXT,
    contribution REAL NOT NULL,
    explanation TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (trace_score_id) REFERENCES trace_scores (id)
);

CREATE TABLE IF NOT EXISTS calibration_runs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('none', 'isotonic', 'Platt')),
    model_version TEXT,
    label_count INTEGER,
    ece REAL,
    metrics_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES cohort_runs (id)
);

CREATE TABLE IF NOT EXISTS human_reviews (
    id TEXT PRIMARY KEY,
    trace_score_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('agree', 'disagree', 'uncertain')),
    label TEXT,
    comment TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (trace_score_id) REFERENCES trace_scores (id)
);

CREATE TABLE IF NOT EXISTS review_queue_items (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    trace_score_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    queue_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'COMPLETED')),
    human_review_id TEXT,
    pushed_at TEXT NOT NULL,
    completed_at TEXT,
    synced_at TEXT,
    FOREIGN KEY (run_id) REFERENCES cohort_runs (id),
    FOREIGN KEY (trace_score_id) REFERENCES trace_scores (id),
    FOREIGN KEY (human_review_id) REFERENCES human_reviews (id),
    UNIQUE (run_id, trace_score_id),
    UNIQUE (queue_id, item_id)
);

CREATE TABLE IF NOT EXISTS alert_decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    trace_score_id TEXT NOT NULL,
    group_key TEXT NOT NULL,
    cause TEXT NOT NULL,
    cause_kind TEXT NOT NULL,
    priority REAL NOT NULL,
    priority_rank INTEGER NOT NULL,
    group_rank INTEGER NOT NULL,
    group_size INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('alerted', 'candidate', 'suppressed_duplicate')),
    reasons_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES cohort_runs (id),
    FOREIGN KEY (trace_score_id) REFERENCES trace_scores (id),
    UNIQUE (run_id, trace_score_id)
);

CREATE TABLE IF NOT EXISTS review_calibrations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    label_count INTEGER NOT NULL,
    trace_count INTEGER NOT NULL,
    agree_count INTEGER NOT NULL,
    disagree_count INTEGER NOT NULL,
    uncertain_count INTEGER NOT NULL,
    alert_reviewed INTEGER NOT NULL,
    alert_agree INTEGER NOT NULL,
    alert_disagree INTEGER NOT NULL,
    alert_precision REAL,
    ece REAL,
    brier REAL,
    metrics_json TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    FOREIGN KEY (tenant_id) REFERENCES tenants (id),
    FOREIGN KEY (source_run_id) REFERENCES cohort_runs (id)
);

CREATE TABLE IF NOT EXISTS lifecycle_schedules (
    id TEXT PRIMARY KEY,
    ontology_id TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    source TEXT NOT NULL CHECK (source IN ('jsonl', 'langfuse')),
    source_ref TEXT NOT NULL,
    interval_hours REAL NOT NULL CHECK (interval_hours > 0),
    window_hours REAL NOT NULL CHECK (window_hours > 0),
    sampling_rate REAL NOT NULL DEFAULT 1.0 CHECK (sampling_rate > 0 AND sampling_rate <= 1.0),
    max_traces INTEGER CHECK (max_traces IS NULL OR max_traces > 0),
    r2_novelty_threshold REAL NOT NULL CHECK (r2_novelty_threshold >= 0 AND r2_novelty_threshold <= 1),
    r2_min_novelty_traces INTEGER NOT NULL DEFAULT 50 CHECK (r2_min_novelty_traces >= 0),
    r2_alert_rate_threshold REAL NOT NULL CHECK (r2_alert_rate_threshold >= 0 AND r2_alert_rate_threshold <= 1),
    writeback_to_langfuse INTEGER NOT NULL DEFAULT 0 CHECK (writeback_to_langfuse IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (ontology_id) REFERENCES ontologies (id)
);

CREATE TABLE IF NOT EXISTS lifecycle_evaluations (
    id TEXT PRIMARY KEY,
    ontology_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('created_r1', 'created_r2', 'skipped')),
    reason TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_run_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (ontology_id) REFERENCES ontologies (id),
    FOREIGN KEY (created_run_id) REFERENCES cohort_runs (id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_tenant_created
    ON cohort_runs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_ontology_created
    ON cohort_runs (ontology_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trace_scores_run_alert
    ON trace_scores (run_id, is_alert, total_score);
CREATE INDEX IF NOT EXISTS idx_trace_scores_cell
    ON trace_scores (run_id, cell_id);
CREATE INDEX IF NOT EXISTS idx_reviews_score
    ON human_reviews (trace_score_id, created_at);
CREATE INDEX IF NOT EXISTS idx_review_queue_items_run
  ON review_queue_items (run_id, status);
CREATE INDEX IF NOT EXISTS idx_alert_decisions_run_status
  ON alert_decisions (run_id, status, priority_rank);
CREATE INDEX IF NOT EXISTS idx_review_calibrations_tenant_created
  ON review_calibrations (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lifecycle_evaluations_ontology_created
  ON lifecycle_evaluations (ontology_id, created_at DESC);

CREATE TABLE IF NOT EXISTS scheduler_locks (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduler_scans (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    watchdog_failed_runs INTEGER NOT NULL DEFAULT 0,
    evaluation_count INTEGER NOT NULL DEFAULT 0,
    created_run_count INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL,
    error TEXT
);
