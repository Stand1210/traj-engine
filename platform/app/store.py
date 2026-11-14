import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "platform" / "contracts" / "schema.sql"
DEFAULT_DB_PATH = ROOT / "platform" / "var" / "traj-engine.db"


class TenantQuotaExceeded(ValueError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _ensure_schema_migrations(connection: sqlite3.Connection) -> None:
    tenant_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(tenants)").fetchall()
    }
    tenant_quota_columns = {
        "max_traces_per_run": 100000,
        "max_runs_per_day": 24,
        "max_concurrent_runs": 1,
    }
    for column_name, default_value in tenant_quota_columns.items():
        if column_name not in tenant_columns:
            connection.execute(
                f"""ALTER TABLE tenants
                    ADD COLUMN {column_name} INTEGER NOT NULL DEFAULT {default_value}"""
            )
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(lifecycle_schedules)").fetchall()
    }
    if "r2_min_novelty_traces" not in columns:
        connection.execute(
            """ALTER TABLE lifecycle_schedules
               ADD COLUMN r2_min_novelty_traces INTEGER NOT NULL DEFAULT 50"""
        )


def connect(db_path: str | Path = DEFAULT_DB_PATH, initialize: bool = False) -> sqlite3.Connection:
    path = Path(db_path)
    if initialize:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if initialize:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _ensure_schema_migrations(connection)
        connection.commit()
    return connection


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def ensure_internal_benchmark(connection: sqlite3.Connection) -> dict[str, str]:
    tenant_id = "tenant-benchmark"
    ontology_id = "ontology-benchmark-ontA"
    now = utcnow()
    connection.execute(
        """INSERT OR IGNORE INTO tenants
           (id, display_name, org_id, project_id, public_key, secret_key, queue_id,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
        (tenant_id, "Benchmark Dataset Owner", "internal", "benchmark-v1",
         "internal", "internal", now, now),
    )
    connection.execute(
        """INSERT OR IGNORE INTO ontologies
           (id, tenant_id, display_name, tier, current_version, created_at, updated_at)
           VALUES (?, ?, ?, 'tier0', 1, ?, ?)""",
        (ontology_id, tenant_id, "Benchmark ontA", now, now),
    )
    yaml_text = "id: ontA\ntier: tier0\nsource: benchmark\n"
    from bench.runner import code_hash
    connection.execute(
        """INSERT OR IGNORE INTO ontology_versions
           (id, ontology_id, version, yaml, code_hash, created_at)
           VALUES (?, ?, 1, ?, ?, ?)""",
        ("ontology-version-benchmark-1", ontology_id, yaml_text, code_hash(), now),
    )
    connection.commit()
    return {"tenant_id": tenant_id, "ontology_id": ontology_id}


def record_startup(connection: sqlite3.Connection, profile: dict, langfuse_version: str | None = None) -> str:
    startup_id = new_id("startup")
    import hashlib
    profile_hash = hashlib.sha256(
        json.dumps(profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    connection.execute(
        """INSERT INTO startup_records
           (id, profile_name, profile_hash, base_url, langfuse_version, checked_at,
            skipped, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (startup_id, profile["profile"], profile_hash, profile["baseUrl"],
         langfuse_version, utcnow(), 1 if langfuse_version is None else 0,
         "M1 internal mode; Langfuse version check deferred to M2"),
    )
    connection.commit()
    return startup_id


def create_run(
    connection: sqlite3.Connection,
    tenant_id: str,
    ontology_id: str,
    source: str,
    source_ref: str,
    run_type: str,
    window_start: str,
    window_end: str,
    sampling_rate: float,
    trigger_reason: str | None,
    idempotency_key: str | None,
) -> str:
    ontology = connection.execute(
        "SELECT id, current_version FROM ontologies WHERE id = ?", (ontology_id,)
    ).fetchone()
    tenant = connection.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if tenant is None or ontology is None:
        raise ValueError("tenant or ontology not found")
    ontology_version = connection.execute(
        "SELECT id FROM ontology_versions WHERE ontology_id = ? AND version = ?",
        (ontology_id, ontology["current_version"]),
    ).fetchone()
    if ontology_version is None:
        raise ValueError("ontology version not found")

    run_id = new_id("run")
    from bench.runner import code_hash
    connection.execute(
        """INSERT INTO cohort_runs
           (id, tenant_id, ontology_id, ontology_version_id, structure_version_id,
            parent_run_id, run_type, source, source_ref, window_start, window_end, sampling_rate,
            status, trigger_reason, error, idempotency_key, code_hash, created_at)
           VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, 'queued', ?, NULL, ?, ?, ?)""",
        (run_id, tenant_id, ontology_id, ontology_version["id"], run_type, source,
         source_ref, window_start, window_end, sampling_rate, trigger_reason, idempotency_key,
         code_hash(), utcnow()),
    )
    connection.execute(
        """INSERT INTO run_steps (id, run_id, name, status, payload_json, started_at, ended_at)
           VALUES (?, ?, 'queue', 'succeeded', ?, ?, ?)""",
        (new_id("step"), run_id, json.dumps({"sourceRef": source_ref}, ensure_ascii=False),
         utcnow(), utcnow()),
    )
    connection.commit()
    return run_id


def get_active_structure(connection: sqlite3.Connection, ontology_id: str) -> dict | None:
    row = connection.execute(
        """SELECT * FROM structure_versions
           WHERE ontology_id = ? AND active = 1
           ORDER BY version DESC, created_at DESC
           LIMIT 1""",
        (ontology_id,),
    ).fetchone()
    return row_to_dict(row)


def create_tenant(
    connection: sqlite3.Connection,
    display_name: str,
    org_id: str,
    project_id: str,
    public_key: str,
    secret_key: str,
    queue_id: str | None = None,
    max_traces_per_run: int = 100000,
    max_runs_per_day: int = 24,
    max_concurrent_runs: int = 1,
) -> str:
    if max_traces_per_run < 1 or max_runs_per_day < 1 or max_concurrent_runs < 1:
        raise ValueError("tenant quotas must be positive")
    existing = connection.execute(
        "SELECT id FROM tenants WHERE org_id = ? AND project_id = ?",
        (org_id, project_id),
    ).fetchone()
    if existing is not None:
        raise ValueError("tenant org/project already registered")
    tenant_id = new_id("tenant")
    connection.execute(
        """INSERT INTO tenants
           (id, display_name, org_id, project_id, public_key, secret_key, queue_id,
            max_traces_per_run, max_runs_per_day, max_concurrent_runs,
            created_at, updated_at, deleted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
        (tenant_id, display_name, org_id, project_id, public_key, secret_key,
         queue_id, max_traces_per_run, max_runs_per_day, max_concurrent_runs,
         utcnow(), utcnow()),
    )
    connection.commit()
    return tenant_id


def update_tenant_quotas(
    connection: sqlite3.Connection,
    tenant_id: str,
    max_traces_per_run: int,
    max_runs_per_day: int,
    max_concurrent_runs: int,
) -> None:
    if max_traces_per_run < 1 or max_runs_per_day < 1 or max_concurrent_runs < 1:
        raise ValueError("tenant quotas must be positive")
    if connection.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone() is None:
        raise ValueError("tenant not found")
    connection.execute(
        """UPDATE tenants
           SET max_traces_per_run = ?, max_runs_per_day = ?, max_concurrent_runs = ?,
               updated_at = ?
           WHERE id = ?""",
        (max_traces_per_run, max_runs_per_day, max_concurrent_runs, utcnow(), tenant_id),
    )
    connection.commit()


def ensure_tenant_run_quota(
    connection: sqlite3.Connection,
    tenant_id: str,
    requested_limit: int | None,
) -> int:
    tenant = connection.execute(
        """SELECT max_traces_per_run, max_runs_per_day, max_concurrent_runs
           FROM tenants WHERE id = ?""",
        (tenant_id,),
    ).fetchone()
    if tenant is None:
        raise ValueError("tenant not found")
    if requested_limit is not None and requested_limit > tenant["max_traces_per_run"]:
        raise TenantQuotaExceeded(
            f"requested limit {requested_limit} exceeds tenant max traces per run "
            f"{tenant['max_traces_per_run']}"
        )
    active_count = connection.execute(
        """SELECT COUNT(*) AS n FROM cohort_runs
           WHERE tenant_id = ? AND status IN ('queued', 'running')""",
        (tenant_id,),
    ).fetchone()["n"]
    if active_count >= tenant["max_concurrent_runs"]:
        raise TenantQuotaExceeded(
            f"tenant already has {active_count} active runs; max concurrent runs is "
            f"{tenant['max_concurrent_runs']}"
        )
    today = datetime.now(timezone.utc).date().isoformat()
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    daily_count = connection.execute(
        """SELECT COUNT(*) AS n FROM cohort_runs
           WHERE tenant_id = ? AND created_at >= ? AND created_at < ?""",
        (tenant_id, today, tomorrow),
    ).fetchone()["n"]
    if daily_count >= tenant["max_runs_per_day"]:
        raise TenantQuotaExceeded(
            f"tenant already created {daily_count} runs today; max runs per day is "
            f"{tenant['max_runs_per_day']}"
        )
    return requested_limit if requested_limit is not None else tenant["max_traces_per_run"]


def create_ontology(
    connection: sqlite3.Connection,
    tenant_id: str,
    display_name: str,
    tier: str,
) -> str:
    if tier not in {"tier0", "tier1"}:
        raise ValueError("tier must be tier0 or tier1")
    if connection.execute("SELECT id FROM tenants WHERE id = ?", (tenant_id,)).fetchone() is None:
        raise ValueError("tenant not found")
    if connection.execute("SELECT id FROM ontologies WHERE tenant_id = ?", (tenant_id,)).fetchone() is not None:
        raise ValueError("tenant already has an ontology")
    ontology_id = new_id("ontology")
    from bench.runner import code_hash
    if tier == "tier0":
        yaml_text = (
            f"id: {ontology_id}\n"
            "version: 1\n"
            "unit_price:\n"
            "  prompt: 0.0\n"
            "  completion: 0.0\n"
        )
        connection.execute(
            """INSERT INTO ontologies
               (id, tenant_id, display_name, tier, current_version, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (ontology_id, tenant_id, display_name, tier, utcnow(), utcnow()),
        )
        connection.execute(
            """INSERT INTO ontology_versions
               (id, ontology_id, version, yaml, code_hash, created_at)
               VALUES (?, ?, 1, ?, ?, ?)""",
            (new_id("ontology-version"), ontology_id, yaml_text, code_hash(), utcnow()),
        )
    else:
        connection.execute(
            """INSERT INTO ontologies
               (id, tenant_id, display_name, tier, current_version, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)""",
            (ontology_id, tenant_id, display_name, tier, utcnow(), utcnow()),
        )
    connection.commit()
    return ontology_id


def create_precheck(connection: sqlite3.Connection, ontology_id: str, sample_size: int) -> str:
    if connection.execute("SELECT id FROM ontologies WHERE id = ?", (ontology_id,)).fetchone() is None:
        raise ValueError("ontology not found")
    precheck_id = new_id("precheck")
    connection.execute(
        """INSERT INTO prechecks
           (id, ontology_id, status, report_json, sample_size, created_at, finished_at)
           VALUES (?, ?, 'running', '{}', ?, ?, NULL)""",
        (precheck_id, ontology_id, sample_size, utcnow()),
    )
    connection.commit()
    return precheck_id


def finish_precheck(
    connection: sqlite3.Connection,
    precheck_id: str,
    status: str,
    report: dict,
) -> None:
    if status not in {"running", "passed", "warning", "failed"}:
        raise ValueError("invalid precheck status")
    connection.execute(
        """UPDATE prechecks SET status = ?, report_json = ?, finished_at = ?
           WHERE id = ?""",
        (status, json.dumps(report, ensure_ascii=False, sort_keys=True), utcnow(), precheck_id),
    )
    connection.commit()


def get_run(connection: sqlite3.Connection, run_id: str) -> dict | None:
    row = connection.execute("SELECT * FROM cohort_runs WHERE id = ?", (run_id,)).fetchone()
    return row_to_dict(row)


def upsert_lifecycle_schedule(
    connection: sqlite3.Connection,
    ontology_id: str,
    enabled: bool,
    source: str,
    source_ref: str,
    interval_hours: float,
    window_hours: float,
    sampling_rate: float,
    max_traces: int | None,
    r2_novelty_threshold: float,
    r2_alert_rate_threshold: float,
    writeback_to_langfuse: bool,
    r2_min_novelty_traces: int = 50,
) -> str:
    if connection.execute("SELECT id FROM ontologies WHERE id = ?", (ontology_id,)).fetchone() is None:
        raise ValueError("ontology not found")
    if source not in {"jsonl", "langfuse"}:
        raise ValueError("invalid source")
    if interval_hours <= 0 or window_hours <= 0:
        raise ValueError("interval and window must be positive")
    if not 0 < sampling_rate <= 1:
        raise ValueError("sampling rate must be in (0, 1]")
    if not 0 <= r2_novelty_threshold <= 1 or not 0 <= r2_alert_rate_threshold <= 1:
        raise ValueError("thresholds must be in [0, 1]")
    if r2_min_novelty_traces < 0:
        raise ValueError("minimum novelty traces must be non-negative")

    row = connection.execute(
        "SELECT id FROM lifecycle_schedules WHERE ontology_id = ?", (ontology_id,)
    ).fetchone()
    now = utcnow()
    if row is None:
        schedule_id = new_id("schedule")
        connection.execute(
            """INSERT INTO lifecycle_schedules
               (id, ontology_id, enabled, source, source_ref, interval_hours,
                window_hours, sampling_rate, max_traces, r2_novelty_threshold,
                 r2_min_novelty_traces, r2_alert_rate_threshold,
                 writeback_to_langfuse, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (schedule_id, ontology_id, int(enabled), source, source_ref, interval_hours,
             window_hours, sampling_rate, max_traces, r2_novelty_threshold,
             r2_min_novelty_traces, r2_alert_rate_threshold,
             int(writeback_to_langfuse), now, now),
        )
    else:
        schedule_id = row["id"]
        connection.execute(
            """UPDATE lifecycle_schedules
               SET enabled = ?, source = ?, source_ref = ?, interval_hours = ?,
                   window_hours = ?, sampling_rate = ?, max_traces = ?,
                   r2_novelty_threshold = ?, r2_alert_rate_threshold = ?,
                   r2_min_novelty_traces = ?, writeback_to_langfuse = ?, updated_at = ?
               WHERE id = ?""",
            (int(enabled), source, source_ref, interval_hours, window_hours, sampling_rate,
             max_traces, r2_novelty_threshold, r2_alert_rate_threshold,
             r2_min_novelty_traces, int(writeback_to_langfuse), now, schedule_id),
        )
    connection.commit()
    return schedule_id


def record_lifecycle_evaluation(
    connection: sqlite3.Connection,
    ontology_id: str,
    decision: str,
    reason: str,
    metrics: dict,
    created_run_id: str | None,
) -> str:
    evaluation_id = new_id("evaluation")
    connection.execute(
        """INSERT INTO lifecycle_evaluations
           (id, ontology_id, decision, reason, metrics_json, created_run_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (evaluation_id, ontology_id, decision, reason,
         json.dumps(metrics, ensure_ascii=False, sort_keys=True), created_run_id, utcnow()),
    )
    connection.commit()
    return evaluation_id


def acquire_scheduler_lock(
    connection: sqlite3.Connection,
    owner_id: str,
    lease_seconds: int,
) -> dict | None:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=lease_seconds)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM scheduler_locks WHERE id = 'singleton'"
        ).fetchone()
        if row is not None:
            expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            if expires_at > now:
                connection.rollback()
                return dict(row)
            connection.execute("DELETE FROM scheduler_locks WHERE id = 'singleton'")
        connection.execute(
            """INSERT INTO scheduler_locks (id, owner_id, acquired_at, expires_at)
               VALUES ('singleton', ?, ?, ?)""",
            (owner_id, utcnow(), expires.isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {
        "id": "singleton",
        "owner_id": owner_id,
        "acquired_at": utcnow(),
        "expires_at": expires.isoformat(),
    }


def heartbeat_scheduler_lock(
    connection: sqlite3.Connection,
    owner_id: str,
    lease_seconds: int,
) -> bool:
    expires = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    cursor = connection.execute(
        """UPDATE scheduler_locks
           SET expires_at = ?
           WHERE id = 'singleton' AND owner_id = ?""",
        (expires.isoformat(), owner_id),
    )
    connection.commit()
    return cursor.rowcount == 1


def release_scheduler_lock(connection: sqlite3.Connection, owner_id: str) -> bool:
    cursor = connection.execute(
        "DELETE FROM scheduler_locks WHERE id = 'singleton' AND owner_id = ?", (owner_id,)
    )
    connection.commit()
    return cursor.rowcount == 1


def get_scheduler_lock(connection: sqlite3.Connection) -> dict | None:
    row = connection.execute(
        "SELECT * FROM scheduler_locks WHERE id = 'singleton'"
    ).fetchone()
    return dict(row) if row is not None else None


def record_scheduler_scan(connection: sqlite3.Connection) -> str:
    scan_id = new_id("scan")
    connection.execute(
        """INSERT INTO scheduler_scans
           (id, status, started_at, finished_at, watchdog_failed_runs,
            evaluation_count, created_run_count, result_json, error)
           VALUES (?, 'running', ?, NULL, 0, 0, 0, '{}', NULL)""",
        (scan_id, utcnow()),
    )
    connection.commit()
    return scan_id


def finish_scheduler_scan(
    connection: sqlite3.Connection,
    scan_id: str,
    status: str,
    watchdog_failed_runs: int,
    evaluation_count: int,
    created_run_count: int,
    result: dict,
    error: str | None = None,
) -> None:
    if status not in {"succeeded", "failed"}:
        raise ValueError("scheduler scan status must be succeeded or failed")
    connection.execute(
        """UPDATE scheduler_scans
           SET status = ?, finished_at = ?, watchdog_failed_runs = ?,
               evaluation_count = ?, created_run_count = ?, result_json = ?, error = ?
           WHERE id = ?""",
        (status, utcnow(), watchdog_failed_runs, evaluation_count, created_run_count,
         json.dumps(result, ensure_ascii=False, sort_keys=True), error, scan_id),
    )
    connection.commit()


def fail_timed_out_runs(
    connection: sqlite3.Connection,
    queued_timeout_seconds: int,
    running_timeout_seconds: int,
) -> list[str]:
    now = datetime.now(timezone.utc)
    updates = []
    rows = connection.execute(
        "SELECT id, status, created_at, started_at FROM cohort_runs WHERE status IN ('queued', 'running')"
    ).fetchall()
    for row in rows:
        reference = row["started_at"] if row["status"] == "running" else row["created_at"]
        reference_time = datetime.fromisoformat(reference.replace("Z", "+00:00"))
        timeout = running_timeout_seconds if row["status"] == "running" else queued_timeout_seconds
        age = (now - reference_time).total_seconds()
        if age < timeout:
            continue
        error = (
            f"run watchdog failed {row['status']} run after {int(age)} seconds"
        )
        set_run_status(connection, row["id"], "failed", error, ended=True)
        upsert_run_step(
            connection, row["id"], "watchdog", "failed",
            {"error": error, "ageSeconds": int(age)}, ended=True,
        )
        updates.append(row["id"])
    return updates


def set_run_status(
    connection: sqlite3.Connection,
    run_id: str,
    status: str,
    error: str | None = None,
    started: bool = False,
    ended: bool = False,
) -> None:
    assignments = ["status = ?", "error = ?"]
    values: list[Any] = [status, error]
    if started:
        assignments.append("started_at = ?")
        values.append(utcnow())
    if ended:
        assignments.append("ended_at = ?")
        values.append(utcnow())
    values.append(run_id)
    connection.execute(f"UPDATE cohort_runs SET {', '.join(assignments)} WHERE id = ?", values)
    connection.commit()


def upsert_run_step(
    connection: sqlite3.Connection,
    run_id: str,
    name: str,
    status: str,
    payload: dict | None = None,
    ended: bool = False,
) -> None:
    existing = connection.execute(
        "SELECT id FROM run_steps WHERE run_id = ? AND name = ?", (run_id, name)
    ).fetchone()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload is not None else None
    if existing is None:
        connection.execute(
            """INSERT INTO run_steps (id, run_id, name, status, payload_json, started_at, ended_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (new_id("step"), run_id, name, status, payload_json, utcnow(), utcnow() if ended else None),
        )
    else:
        assignments = ["status = ?", "payload_json = ?"]
        values: list[Any] = [status, payload_json]
        if ended:
            assignments.append("ended_at = ?")
            values.append(utcnow())
        values.extend([run_id, name])
        connection.execute(
            f"UPDATE run_steps SET {', '.join(assignments)} WHERE run_id = ? AND name = ?", values
        )
    connection.commit()
