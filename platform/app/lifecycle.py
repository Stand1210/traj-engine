import json
import math
from datetime import datetime, timedelta, timezone

from platform.app import store


def evaluate_lifecycle_state(connection, ontology_id: str, force_r2: bool = False) -> dict:
    schedule = get_lifecycle_schedule(connection, ontology_id)
    if schedule is None:
        raise ValueError("lifecycle schedule not found")
    if not int(schedule["enabled"]):
        return _result("skipped", "schedule_disabled", schedule, None, {})

    active_structure = store.get_active_structure(connection, ontology_id)
    latest_run = connection.execute(
        """SELECT * FROM cohort_runs WHERE ontology_id = ?
           ORDER BY COALESCE(ended_at, created_at) DESC, id LIMIT 1""",
        (ontology_id,),
    ).fetchone()
    if latest_run is not None and latest_run["status"] in {"queued", "running"}:
        return _result("skipped", "run_in_progress", schedule, latest_run, {})

    metrics = _latest_metrics(connection, latest_run)
    now = datetime.now(timezone.utc)
    elapsed_hours = None
    if latest_run is not None:
        reference = latest_run["ended_at"] or latest_run["created_at"]
        elapsed_hours = max(0.0, (now - _parse_time(reference)).total_seconds() / 3600.0)
    metrics["elapsedHours"] = round(elapsed_hours, 3) if elapsed_hours is not None else None

    if active_structure is None:
        return _result("created_r2", "cold_start", schedule, latest_run, metrics)
    if force_r2:
        return _result("created_r2", "forced_r2", schedule, latest_run, metrics)
    if metrics["noveltyRate"] is not None and metrics["noveltyRate"] >= float(schedule["r2_novelty_threshold"]):
        return _result("created_r2", "novelty_threshold", schedule, latest_run, metrics)
    if metrics["alertRate"] is not None and metrics["alertRate"] >= float(schedule["r2_alert_rate_threshold"]):
        return _result("created_r2", "alert_rate_threshold", schedule, latest_run, metrics)
    if elapsed_hours is None or elapsed_hours >= float(schedule["interval_hours"]):
        return _result("created_r1", "interval_due", schedule, latest_run, metrics)
    return _result("skipped", "not_due", schedule, latest_run, metrics)


def get_lifecycle_schedule(connection, ontology_id: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM lifecycle_schedules WHERE ontology_id = ?", (ontology_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def serialize_schedule(row: dict) -> dict:
    return {
        "id": row["id"],
        "ontologyId": row["ontology_id"],
        "enabled": bool(row["enabled"]),
        "source": row["source"],
        "sourceRef": row["source_ref"],
        "intervalHours": row["interval_hours"],
        "windowHours": row["window_hours"],
        "samplingRate": row["sampling_rate"],
        "maxTraces": row["max_traces"],
        "r2NoveltyThreshold": row["r2_novelty_threshold"],
        "r2AlertRateThreshold": row["r2_alert_rate_threshold"],
        "writebackToLangfuse": bool(row["writeback_to_langfuse"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def serialize_evaluation(row: dict) -> dict:
    return {
        "id": row["id"],
        "ontologyId": row["ontology_id"],
        "decision": row["decision"],
        "reason": row["reason"],
        "metrics": json.loads(row["metrics_json"] or "{}"),
        "createdRunId": row["created_run_id"],
        "createdAt": row["created_at"],
    }


def _latest_metrics(connection, latest_run) -> dict:
    if latest_run is None:
        return {"runId": None, "traceCount": 0, "noveltyRate": None, "alertRate": None}
    row = connection.execute(
        """SELECT COUNT(*) AS trace_count,
                  SUM(is_abstain) AS novelty_count,
                  SUM(is_alert) AS alert_count
           FROM trace_scores WHERE run_id = ?""",
        (latest_run["id"],),
    ).fetchone()
    trace_count = int(row["trace_count"] or 0)
    return {
        "runId": latest_run["id"],
        "traceCount": trace_count,
        "noveltyRate": _ratio(row["novelty_count"], trace_count),
        "alertRate": _ratio(row["alert_count"], trace_count),
    }


def _result(decision: str, reason: str, schedule: dict, latest_run, metrics: dict) -> dict:
    now = datetime.now(timezone.utc)
    interval_seconds = max(1.0, float(schedule["interval_hours"]) * 3600.0)
    bucket_timestamp = math.floor(now.timestamp() / interval_seconds) * interval_seconds
    evaluation_bucket = datetime.fromtimestamp(bucket_timestamp, timezone.utc).isoformat()
    return {
        "decision": decision,
        "reason": reason,
        "schedule": schedule,
        "latestRunId": latest_run["id"] if latest_run is not None else None,
        "metrics": metrics,
        "windowStart": (now - timedelta(hours=float(schedule["window_hours"]))).isoformat(),
        "windowEnd": now.isoformat(),
        "evaluationBucket": evaluation_bucket,
    }


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ratio(numerator, denominator: int) -> float | None:
    if denominator == 0 or numerator is None:
        return None
    return round(int(numerator) / denominator, 6)
