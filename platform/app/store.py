import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "platform" / "contracts" / "schema.sql"
DEFAULT_DB_PATH = ROOT / "platform" / "var" / "traj-engine.db"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


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


def create_tenant(
    connection: sqlite3.Connection,
    display_name: str,
    org_id: str,
    project_id: str,
    public_key: str,
    secret_key: str,
    queue_id: str | None = None,
) -> str:
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
            created_at, updated_at, deleted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
        (tenant_id, display_name, org_id, project_id, public_key, secret_key,
         queue_id, utcnow(), utcnow()),
    )
    connection.commit()
    return tenant_id


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
    ontology_id = new_id("ontology")
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
