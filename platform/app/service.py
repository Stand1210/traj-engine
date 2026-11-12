import base64
import json
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from platform.app import store
from platform.app.config import load_alert_config, load_endpoints, resolve_profile_from_args
from platform.app.algorithm import load_frozen_state
from platform.app.alerts import (
    DEFAULT_ALERT_BUDGET,
    compute_alert_decisions,
    summarize_decisions,
)
from platform.app.engine import ENGINE
from platform.app.langfuse_source import LangfuseHttpError, LangfuseTraceSource
from platform.app.langfuse_scores import LangfuseScoreWriter
from platform.app.langfuse_reviews import (
    COMMENT_SCORE_NAME,
    LABEL_SCORE_NAME,
    LangfuseAnnotationQueueClient,
    VERDICT_SCORE_NAME,
)


app = FastAPI(
    title="Traj Engine Platform API",
    version="0.1.0",
    description="M1 backend for agent trajectory quality evaluation.",
)


class RunInput(BaseModel):
    tenantId: str
    ontologyId: str
    source: Literal["jsonl", "langfuse"] = "jsonl"
    sourceRef: str = "R1"
    runType: Literal["R1", "R2", "R3"] = "R1"
    windowStart: str
    windowEnd: str
    samplingRate: float = Field(default=1.0, ge=0.0, le=1.0)
    limit: int | None = Field(default=None, ge=1)
    triggerReason: str | None = None
    idempotencyKey: str | None = None
    writebackToLangfuse: bool = False
    writebackStrict: bool = False


class ReviewInput(BaseModel):
    traceScoreId: str
    reviewer: str
    verdict: Literal["agree", "disagree", "uncertain"]
    label: str | None = None
    comment: str | None = None


class ReviewQueueInput(BaseModel):
    scope: Literal["alerts", "abstains", "all"] = "all"
    limit: int = Field(default=50, ge=1, le=100)
    queueName: str = Field(default="traj-engine-review", min_length=1, max_length=120)


class TenantInput(BaseModel):
    orgId: str
    projectId: str
    displayName: str
    publicKey: str
    secretKey: str
    queueId: str | None = None


class OntologyInput(BaseModel):
    tenantId: str
    tier: Literal["tier0", "tier1"]
    displayName: str = "Agent"


class PrecheckInput(BaseModel):
    sampleSize: int = Field(default=100, ge=100)


def get_connection() -> Any:
    connection = store.connect(initialize=False)
    try:
        yield connection
    finally:
        connection.close()


@app.on_event("startup")
def startup() -> None:
    with closing(store.connect(initialize=True)) as connection:
        store.ensure_internal_benchmark(connection)
        store.record_startup(connection, resolve_profile_from_args())


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/v1/config/profile")
def current_profile() -> dict:
    profile = resolve_profile_from_args()
    return {
        "profile": profile["profile"],
        "baseUrl": profile["baseUrl"],
        "versionConstraint": profile["versionConstraint"],
    }


@app.get("/api/v1/startup-records/current")
def current_startup(connection=Depends(get_connection)) -> dict:
    row = connection.execute(
        "SELECT * FROM startup_records ORDER BY checked_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "startup_record_not_found"})
    return serialize_startup(row)


@app.get("/api/v1/tenants")
def list_tenants(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    connection=Depends(get_connection),
) -> dict:
    offset = decode_cursor(cursor)
    rows = connection.execute(
        "SELECT * FROM tenants ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total = connection.execute("SELECT COUNT(*) AS n FROM tenants").fetchone()["n"]
    return page([serialize_tenant(row) for row in rows], limit, offset, total)


@app.get("/api/v1/tenants/{tenant_id}")
def get_tenant(tenant_id: str, connection=Depends(get_connection)) -> dict:
    row = connection.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "tenant_not_found"})
    return serialize_tenant(row)


@app.post("/api/v1/tenants", status_code=201)
def register_tenant(input_data: TenantInput, connection=Depends(get_connection)) -> dict:
    try:
        tenant_id = store.create_tenant(
            connection,
            input_data.displayName,
            input_data.orgId,
            input_data.projectId,
            input_data.publicKey,
            input_data.secretKey,
            input_data.queueId,
        )
    except ValueError:
        raise HTTPException(status_code=409, detail={"code": "tenant_already_exists"})
    row = connection.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    return serialize_tenant(row)


@app.get("/api/v1/ontologies")
def list_ontologies(
    tenantId: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    connection=Depends(get_connection),
) -> dict:
    offset = decode_cursor(cursor)
    where = "WHERE tenant_id = ?" if tenantId else ""
    values = [tenantId] if tenantId else []
    rows = connection.execute(
        f"SELECT * FROM ontologies {where} ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
        values + [limit, offset],
    ).fetchall()
    count = connection.execute(
        f"SELECT COUNT(*) AS n FROM ontologies {where}", values
    ).fetchone()["n"]
    return page([serialize_ontology(row) for row in rows], limit, offset, count)


@app.get("/api/v1/ontologies/{ontology_id}")
def get_ontology(ontology_id: str, connection=Depends(get_connection)) -> dict:
    row = connection.execute("SELECT * FROM ontologies WHERE id = ?", (ontology_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "ontology_not_found"})
    return serialize_ontology(row)


@app.get("/api/v1/ontologies/{ontology_id}/versions/current")
def get_current_ontology_version(ontology_id: str, connection=Depends(get_connection)) -> dict:
    row = connection.execute(
        """SELECT v.* FROM ontologies o
           JOIN ontology_versions v ON v.ontology_id = o.id AND v.version = o.current_version
           WHERE o.id = ?""",
        (ontology_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "ontology_version_not_found"})
    return {
        "ontologyId": row["ontology_id"],
        "version": row["version"],
        "yaml": row["yaml"],
        "codeHash": row["code_hash"],
        "createdAt": row["created_at"],
    }


@app.post("/api/v1/ontologies", status_code=201)
def create_ontology(input_data: OntologyInput, connection=Depends(get_connection)) -> dict:
    try:
        ontology_id = store.create_ontology(
            connection, input_data.tenantId, input_data.displayName, input_data.tier
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"code": str(error)})
    row = connection.execute("SELECT * FROM ontologies WHERE id = ?", (ontology_id,)).fetchone()
    return serialize_ontology(row)


@app.get("/api/v1/ontologies/{ontology_id}/prechecks")
def list_prechecks(
    ontology_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    connection=Depends(get_connection),
) -> dict:
    offset = decode_cursor(cursor)
    rows = connection.execute(
        """SELECT * FROM prechecks WHERE ontology_id = ?
           ORDER BY created_at DESC, id LIMIT ? OFFSET ?""",
        (ontology_id, limit, offset),
    ).fetchall()
    total = connection.execute(
        "SELECT COUNT(*) AS n FROM prechecks WHERE ontology_id = ?", (ontology_id,)
    ).fetchone()["n"]
    return page([serialize_precheck(row) for row in rows], limit, offset, total)


@app.post("/api/v1/ontologies/{ontology_id}/prechecks", status_code=202)
def run_precheck(
    ontology_id: str,
    input_data: PrecheckInput,
    connection=Depends(get_connection),
) -> dict:
    row = connection.execute(
        """SELECT o.id AS ontology_id, t.* FROM ontologies o
           JOIN tenants t ON t.id = o.tenant_id WHERE o.id = ?""",
        (ontology_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "ontology_not_found"})
    try:
        precheck_id = store.create_precheck(connection, ontology_id, input_data.sampleSize)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"code": str(error)})

    profile = resolve_profile_from_args()
    endpoints = load_endpoints()
    source = LangfuseTraceSource.from_config(
        profile,
        endpoints,
        {"publicKey": row["public_key"], "secretKey": row["secret_key"]},
        max_traces=input_data.sampleSize,
    )
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    try:
        traces = list(source.list_traces({"start": start, "end": end}, {}))
    except (LangfuseHttpError, ValueError, OSError) as error:
        report = {
            "error": {
                "type": type(error).__name__,
                "statusCode": getattr(error, "status_code", None),
                "message": str(error),
            },
            "checks": [],
        }
        store.finish_precheck(connection, precheck_id, "failed", report)
        raise HTTPException(status_code=502, detail={"code": "langfuse_precheck_failed"})

    report = build_precheck_report(traces, input_data.sampleSize)
    report["sourceTraversal"] = source.traversal
    status = "failed" if any(item["status"] == "failed" for item in report["checks"]) else (
        "warning" if any(item["status"] == "warning" for item in report["checks"]) else "passed"
    )
    store.finish_precheck(connection, precheck_id, status, report)
    result = connection.execute("SELECT * FROM prechecks WHERE id = ?", (precheck_id,)).fetchone()
    return serialize_precheck(result)


@app.post("/api/v1/runs", status_code=201)
def create_run(input_data: RunInput, connection=Depends(get_connection)) -> dict:
    if input_data.source == "jsonl" and input_data.sourceRef not in {f"R{i}" for i in range(1, 9)}:
        raise HTTPException(status_code=400, detail={"code": "invalid_source_ref"})
    langfuse_tenant = None
    if input_data.source == "langfuse":
        langfuse_tenant = connection.execute(
            """SELECT t.* FROM ontologies o
               JOIN tenants t ON t.id = o.tenant_id
               WHERE o.id = ? AND o.current_version > 0""",
            (input_data.ontologyId,),
        ).fetchone()
        if langfuse_tenant is None:
            raise HTTPException(status_code=400, detail={"code": "ontology_version_not_published"})
    if input_data.runType != "R1":
        raise HTTPException(status_code=400, detail={"code": "current_release_only_supports_r1"})
    if input_data.samplingRate <= 0:
        raise HTTPException(status_code=400, detail={"code": "sampling_rate_must_be_positive"})
    if input_data.idempotencyKey:
        existing = connection.execute(
            "SELECT id FROM cohort_runs WHERE tenant_id = ? AND idempotency_key = ?",
            (input_data.tenantId, input_data.idempotencyKey),
        ).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict"})
    try:
        run_id = store.create_run(
            connection, input_data.tenantId, input_data.ontologyId, input_data.source,
            input_data.sourceRef, input_data.runType, input_data.windowStart,
            input_data.windowEnd, input_data.samplingRate, input_data.triggerReason,
            input_data.idempotencyKey,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"code": "invalid_run_request", "message": str(error)})
    frozen_state = None
    active_structure = store.get_active_structure(connection, input_data.ontologyId)
    if active_structure is not None and active_structure["state_json"]:
        try:
            frozen_state = load_frozen_state(active_structure["state_json"])
            frozen_state["structure_id"] = active_structure["id"]
        except ValueError:
            frozen_state = None
    trace_source = None
    window = None
    score_writer = None
    writeback_strict = False
    if input_data.source == "langfuse":
        profile = resolve_profile_from_args()
        endpoints = load_endpoints()
        trace_source = LangfuseTraceSource.from_config(
            profile,
            endpoints,
            {
                "publicKey": langfuse_tenant["public_key"],
                "secretKey": langfuse_tenant["secret_key"],
            },
            max_traces=input_data.limit,
        )
        window = {"start": input_data.windowStart, "end": input_data.windowEnd}
        if input_data.writebackToLangfuse:
            score_writer = LangfuseScoreWriter.from_config(
                profile,
                endpoints,
                {
                    "publicKey": langfuse_tenant["public_key"],
                    "secretKey": langfuse_tenant["secret_key"],
                },
            )
            writeback_strict = input_data.writebackStrict
    ENGINE.submit(
        run_id,
        input_data.sourceRef,
        input_data.samplingRate,
        input_data.limit,
        trace_source=trace_source,
        window=window,
        ontology_id=input_data.ontologyId,
        frozen_state=frozen_state,
        score_writer=score_writer,
        writeback_strict=writeback_strict,
    )
    row = connection.execute("SELECT * FROM cohort_runs WHERE id = ?", (run_id,)).fetchone()
    return serialize_run(row)


@app.get("/api/v1/runs")
def list_runs(
    tenantId: str | None = None,
    ontologyId: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    connection=Depends(get_connection),
) -> dict:
    clauses, values = [], []
    if tenantId:
        clauses.append("tenant_id = ?")
        values.append(tenantId)
    if ontologyId:
        clauses.append("ontology_id = ?")
        values.append(ontologyId)
    if status:
        clauses.append("status = ?")
        values.append(status)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    offset = decode_cursor(cursor)
    rows = connection.execute(
        f"SELECT * FROM cohort_runs {where} ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
        values + [limit, offset],
    ).fetchall()
    total = connection.execute(
        f"SELECT COUNT(*) AS n FROM cohort_runs {where}", values
    ).fetchone()["n"]
    return page([serialize_run(row) for row in rows], limit, offset, total)


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, connection=Depends(get_connection)) -> dict:
    row = connection.execute("SELECT * FROM cohort_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    return serialize_run(row)


@app.post("/api/v1/runs/{run_id}/cancel")
def cancel_run(run_id: str, connection=Depends(get_connection)) -> dict:
    row = connection.execute("SELECT * FROM cohort_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    if row["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail={"code": "run_not_cancelable"})
    store.set_run_status(connection, run_id, "canceled", ended=True)
    ENGINE.cancel(run_id)
    row = connection.execute("SELECT * FROM cohort_runs WHERE id = ?", (run_id,)).fetchone()
    return serialize_run(row)


@app.get("/api/v1/runs/{run_id}/steps")
def list_run_steps(run_id: str, connection=Depends(get_connection)) -> list[dict]:
    ensure_run(connection, run_id)
    rows = connection.execute(
        "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at, name", (run_id,)
    ).fetchall()
    return [serialize_step(row) for row in rows]


@app.get("/api/v1/runs/{run_id}/cells")
def list_cells(run_id: str, connection=Depends(get_connection)) -> list[dict]:
    ensure_run(connection, run_id)
    rows = connection.execute(
        "SELECT * FROM cells WHERE run_id = ? ORDER BY size DESC, cell_key", (run_id,)
    ).fetchall()
    return [serialize_cell(row) for row in rows]


@app.get("/api/v1/runs/{run_id}/traces")
def list_trace_scores(
    run_id: str,
    cellId: str | None = None,
    alertOnly: bool = False,
    abstainOnly: bool = False,
    minScore: float | None = None,
    maxScore: float | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    connection=Depends(get_connection),
) -> dict:
    ensure_run(connection, run_id)
    clauses = ["run_id = ?"]
    values: list[Any] = [run_id]
    if cellId:
        clauses.append("cell_id = ?")
        values.append(cellId)
    if alertOnly:
        clauses.append("is_alert = 1")
    if abstainOnly:
        clauses.append("is_abstain = 1")
    if minScore is not None:
        clauses.append("total_score >= ?")
        values.append(minScore)
    if maxScore is not None:
        clauses.append("total_score <= ?")
        values.append(maxScore)
    where = "WHERE " + " AND ".join(clauses)
    offset = decode_cursor(cursor)
    rows = connection.execute(
        f"SELECT * FROM trace_scores {where} ORDER BY total_score ASC, trace_id LIMIT ? OFFSET ?",
        values + [limit, offset],
    ).fetchall()
    total = connection.execute(f"SELECT COUNT(*) AS n FROM trace_scores {where}", values).fetchone()["n"]
    return page([serialize_trace_score(row) for row in rows], limit, offset, total)


@app.get("/api/v1/runs/{run_id}/traces/{trace_id}")
def get_trace_score(run_id: str, trace_id: str, connection=Depends(get_connection)) -> dict:
    ensure_run(connection, run_id)
    row = connection.execute(
        "SELECT * FROM trace_scores WHERE run_id = ? AND trace_id = ?",
        (run_id, trace_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "trace_score_not_found"})
    evidence_rows = connection.execute(
        "SELECT * FROM score_evidence WHERE trace_score_id = ? ORDER BY dimension",
        (row["id"],),
    ).fetchall()
    result = serialize_trace_score(row)
    result["evidence"] = [serialize_evidence(item) for item in evidence_rows]
    return result


@app.get("/api/v1/runs/{run_id}/alerts")
def list_alerts(
    run_id: str,
    budget: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=100),
    connection=Depends(get_connection),
) -> list[dict]:
    ensure_run(connection, run_id)
    decisions = _alert_decisions(connection, run_id, budget)
    decisions = [item for item in decisions if item["status"] == "alerted"][:limit]
    score_rows = _alert_score_rows(connection, run_id)
    return [_serialize_alert_score(score_rows[item["trace_score_id"]], item) for item in decisions]


@app.get("/api/v1/runs/{run_id}/alert-candidates")
def list_alert_candidates(
    run_id: str,
    budget: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=100),
    connection=Depends(get_connection),
) -> list[dict]:
    ensure_run(connection, run_id)
    decisions = _alert_decisions(connection, run_id, budget)
    decisions = [
        item for item in decisions
        if item["status"] in {"candidate", "suppressed_duplicate"}
    ][:limit]
    score_rows = _alert_score_rows(connection, run_id)
    return [_serialize_alert_score(score_rows[item["trace_score_id"]], item) for item in decisions]


@app.get("/api/v1/runs/{run_id}/alerts/summary")
def get_alert_summary(
    run_id: str,
    budget: int | None = Query(default=None, ge=0, le=100),
    connection=Depends(get_connection),
) -> dict:
    ensure_run(connection, run_id)
    decisions = _alert_decisions(connection, run_id, budget)
    summary = summarize_decisions(decisions, _effective_budget(budget))
    top_groups: dict[str, dict] = {}
    for decision in decisions:
        group = top_groups.setdefault(decision["group_key"], {
            "groupKey": decision["group_key"],
            "cause": decision["cause"],
            "causeKind": decision["cause_kind"],
            "groupSize": decision["group_size"],
            "topPriority": decision["priority"],
            "status": decision["status"],
        })
        group["topPriority"] = max(group["topPriority"], decision["priority"])
    summary["topGroups"] = sorted(
        top_groups.values(), key=lambda item: (-item["topPriority"], item["groupKey"])
    )[:10]
    return summary


@app.get("/api/v1/config/alerts")
def get_alert_config() -> dict:
    return load_alert_config()


@app.get("/api/v1/runs/{run_id}/lineage")
def get_lineage(run_id: str, connection=Depends(get_connection)) -> list[dict]:
    ensure_run(connection, run_id)
    rows = connection.execute(
        "SELECT * FROM cell_lineage WHERE run_id = ? ORDER BY relation", (run_id,)
    ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/v1/runs/{run_id}/calibration")
def get_calibration(run_id: str, connection=Depends(get_connection)) -> dict:
    ensure_run(connection, run_id)
    row = connection.execute(
        "SELECT * FROM calibration_runs WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "calibration_not_found"})
    return serialize_calibration(row)


@app.post("/api/v1/runs/{run_id}/reviews", status_code=201)
def submit_review(run_id: str, input_data: ReviewInput, connection=Depends(get_connection)) -> dict:
    ensure_run(connection, run_id)
    score = connection.execute(
        "SELECT id FROM trace_scores WHERE id = ? AND run_id = ?",
        (input_data.traceScoreId, run_id),
    ).fetchone()
    if score is None:
        raise HTTPException(status_code=404, detail={"code": "trace_score_not_found"})
    review_id = store.new_id("review")
    connection.execute(
        """INSERT INTO human_reviews
           (id, trace_score_id, reviewer, verdict, label, comment, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (review_id, input_data.traceScoreId, input_data.reviewer, input_data.verdict,
         input_data.label, input_data.comment, store.utcnow()),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM human_reviews WHERE id = ?", (review_id,)).fetchone()
    return dict(row)


@app.get("/api/v1/reviews")
def list_reviews(
    tenantId: str | None = None,
    runId: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    connection=Depends(get_connection),
) -> dict:
    clauses, values = [], []
    if tenantId:
        clauses.append("s.tenant_id = ?")
        values.append(tenantId)
    if runId:
        clauses.append("s.run_id = ?")
        values.append(runId)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    offset = decode_cursor(cursor)
    rows = connection.execute(
        f"""SELECT r.* FROM human_reviews r
            JOIN trace_scores s ON s.id = r.trace_score_id
            {where} ORDER BY r.created_at DESC, r.id LIMIT ? OFFSET ?""",
        values + [limit, offset],
    ).fetchall()
    total = connection.execute(
        f"""SELECT COUNT(*) AS n FROM human_reviews r
            JOIN trace_scores s ON s.id = r.trace_score_id {where}""",
        values,
    ).fetchone()["n"]
    return page([dict(row) for row in rows], limit, offset, total)


@app.post("/api/v1/runs/{run_id}/review-queue", status_code=201)
def create_review_queue(run_id: str, input_data: ReviewQueueInput, connection=Depends(get_connection)) -> dict:
    ensure_run(connection, run_id)
    tenant = _tenant_for_run(connection, run_id)
    client = _annotation_client(tenant)
    assets = client.ensure_review_assets(input_data.queueName)
    queue = assets["queue"]
    connection.execute(
        "UPDATE tenants SET queue_id = ?, updated_at = ? WHERE id = ?",
        (queue["id"], store.utcnow(), tenant["id"]),
    )
    conditions = {
        "alerts": "s.is_alert = 1",
        "abstains": "s.is_abstain = 1",
        "all": "(s.is_alert = 1 OR s.is_abstain = 1)",
    }
    rows = connection.execute(
        f"""SELECT s.id, s.trace_id FROM trace_scores s
            LEFT JOIN review_queue_items rqi ON rqi.trace_score_id = s.id
            WHERE s.run_id = ? AND rqi.id IS NULL AND {conditions[input_data.scope]}
            ORDER BY s.total_score ASC, s.trace_id LIMIT ?""",
        (run_id, input_data.limit),
    ).fetchall()
    items = client.push_items(queue["id"], [row["trace_id"] for row in rows])
    inserted = []
    for score_row, item in zip(rows, items):
        queue_item_id = store.new_id("review-item")
        connection.execute(
            """INSERT INTO review_queue_items
               (id, run_id, trace_score_id, trace_id, queue_id, item_id,
                status, pushed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (queue_item_id, run_id, score_row["id"], score_row["trace_id"],
             queue["id"], item["id"], item.get("status") or "PENDING", store.utcnow()),
        )
        inserted.append({
            "id": queue_item_id,
            "traceScoreId": score_row["id"],
            "traceId": score_row["trace_id"],
            "itemId": item["id"],
            "status": item.get("status") or "PENDING",
        })
    connection.commit()
    store.upsert_run_step(
        connection, run_id, "review_queue", "succeeded",
        {"queueId": queue["id"], "scope": input_data.scope, "pushed": len(inserted)},
        ended=True,
    )
    return {
        "runId": run_id,
        "queueId": queue["id"],
        "scope": input_data.scope,
        "selected": len(rows),
        "pushed": len(inserted),
        "items": inserted,
    }


@app.post("/api/v1/runs/{run_id}/review-queue/sync")
def sync_review_queue(run_id: str, connection=Depends(get_connection)) -> dict:
    ensure_run(connection, run_id)
    tenant = _tenant_for_run(connection, run_id)
    if not tenant["queue_id"]:
        raise HTTPException(status_code=400, detail={"code": "review_queue_not_created"})
    client = _annotation_client(tenant)
    remote_items = {item["id"]: item for item in client.list_items(tenant["queue_id"])}
    local_items = connection.execute(
        "SELECT * FROM review_queue_items WHERE run_id = ? AND queue_id = ?",
        (run_id, tenant["queue_id"]),
    ).fetchall()
    completed = 0
    for item in local_items:
        remote = remote_items.get(item["item_id"])
        if remote is None:
            continue
        if remote.get("status") != item["status"]:
            connection.execute(
                "UPDATE review_queue_items SET status = ?, completed_at = ? WHERE id = ?",
                (remote["status"], remote.get("completedAt"), item["id"]),
            )
            if remote["status"] == "COMPLETED":
                completed += 1

    pending_sync = connection.execute(
        """SELECT * FROM review_queue_items
           WHERE run_id = ? AND queue_id = ? AND status = 'COMPLETED'
             AND human_review_id IS NULL""",
        (run_id, tenant["queue_id"]),
    ).fetchall()
    scores = client.list_annotation_scores(
        [item["trace_id"] for item in pending_sync], tenant["queue_id"]
    )
    scores_by_trace: dict[str, dict] = {}
    for score in scores:
        trace_id = score.get("traceId")
        if not trace_id or score.get("name") not in {VERDICT_SCORE_NAME, LABEL_SCORE_NAME, COMMENT_SCORE_NAME}:
            continue
        current = scores_by_trace.setdefault(trace_id, {})
        previous = current.get(score["name"])
        if previous is None or (score.get("updatedAt") or "") >= (previous.get("updatedAt") or ""):
            current[score["name"]] = score

    imported = 0
    for item in pending_sync:
        annotations = scores_by_trace.get(item["trace_id"], {})
        verdict_score = annotations.get(VERDICT_SCORE_NAME)
        if not verdict_score:
            continue
        verdict_value = verdict_score.get("value")
        numeric_verdicts = {1: "agree", 2: "disagree", 3: "uncertain"}
        if isinstance(verdict_value, (int, float)):
            verdict = numeric_verdicts.get(int(verdict_value), "")
        else:
            verdict = str(verdict_value or "").lower()
        if verdict not in {"agree", "disagree", "uncertain"}:
            continue
        reviewer = verdict_score.get("authorUserId") or "langfuse-annotation"
        review_id = store.new_id("review")
        connection.execute(
            """INSERT INTO human_reviews
               (id, trace_score_id, reviewer, verdict, label, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (review_id, item["trace_score_id"], reviewer, verdict,
             annotations.get(LABEL_SCORE_NAME, {}).get("value"),
             annotations.get(COMMENT_SCORE_NAME, {}).get("value"),
             store.utcnow()),
        )
        connection.execute(
            "UPDATE review_queue_items SET human_review_id = ?, synced_at = ? WHERE id = ?",
            (review_id, store.utcnow(), item["id"]),
        )
        imported += 1
    connection.commit()
    store.upsert_run_step(
        connection, run_id, "review_sync", "succeeded",
        {"queueId": tenant["queue_id"], "statusUpdates": completed, "imported": imported},
        ended=True,
    )
    return {
        "runId": run_id,
        "queueId": tenant["queue_id"],
        "statusUpdates": completed,
        "awaitingReview": len(pending_sync),
        "imported": imported,
    }


@app.get("/api/v1/trace-scores/{trace_score_id}/evidence")
def list_evidence(trace_score_id: str, connection=Depends(get_connection)) -> list[dict]:
    rows = connection.execute(
        "SELECT * FROM score_evidence WHERE trace_score_id = ? ORDER BY dimension",
        (trace_score_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail={"code": "evidence_not_found"})
    return [serialize_evidence(row) for row in rows]


def ensure_run(connection, run_id: str) -> None:
    row = connection.execute("SELECT id FROM cohort_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})


def _effective_budget(budget: int | None) -> int:
    if budget is not None:
        return budget
    config = load_alert_config()
    return int(config.get("budgetPerRun", DEFAULT_ALERT_BUDGET))


def _alert_score_rows(connection, run_id: str) -> dict[str, dict]:
    return {
        row["id"]: dict(row)
        for row in connection.execute(
            "SELECT * FROM trace_scores WHERE run_id = ? AND is_alert = 1", (run_id,)
        ).fetchall()
    }


def _alert_decisions(connection, run_id: str, budget: int | None) -> list[dict]:
    effective_budget = _effective_budget(budget)
    persisted = [
        dict(row) for row in connection.execute(
            "SELECT * FROM alert_decisions WHERE run_id = ? ORDER BY priority_rank", (run_id,)
        ).fetchall()
    ]
    if persisted and effective_budget == _effective_budget(None):
        return _decode_persisted_decisions(persisted)

    score_rows = list(_alert_score_rows(connection, run_id).values())
    evidence_rows = []
    for row in score_rows:
        evidence_rows.extend(
            dict(item) for item in connection.execute(
                "SELECT * FROM score_evidence WHERE trace_score_id = ? ORDER BY dimension", (row["id"],)
            ).fetchall()
        )
    cell_sizes = {
        row["id"]: int(row["size"])
        for row in connection.execute("SELECT id, size FROM cells WHERE run_id = ?", (run_id,)).fetchall()
    }
    return compute_alert_decisions(score_rows, evidence_rows, cell_sizes, effective_budget)


def _decode_persisted_decisions(rows: list[dict]) -> list[dict]:
    decisions = []
    for row in rows:
        decisions.append({
            "trace_score_id": row["trace_score_id"],
            "group_key": row["group_key"],
            "cause": row["cause"],
            "cause_kind": row["cause_kind"],
            "priority": row["priority"],
            "group_rank": row["group_rank"],
            "group_size": row["group_size"],
            "status": row["status"],
            "rank": row["priority_rank"],
            "reasons": json.loads(row["reasons_json"] or "[]"),
        })
    return decisions


def _tenant_for_run(connection, run_id: str):
    tenant = connection.execute(
        """SELECT t.* FROM cohort_runs r
           JOIN ontologies o ON o.id = r.ontology_id
           JOIN tenants t ON t.id = o.tenant_id
           WHERE r.id = ?""",
        (run_id,),
    ).fetchone()
    if tenant is None:
        raise HTTPException(status_code=404, detail={"code": "tenant_not_found"})
    return tenant


def _annotation_client(tenant) -> LangfuseAnnotationQueueClient:
    return LangfuseAnnotationQueueClient.from_config(
        resolve_profile_from_args(),
        load_endpoints(),
        {"publicKey": tenant["public_key"], "secretKey": tenant["secret_key"]},
    )


def decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")))
    except Exception as error:
        raise HTTPException(status_code=400, detail={"code": "invalid_cursor"}) from error


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def page(data: list[dict], limit: int, offset: int, total: int) -> dict:
    next_offset = offset + limit
    return {
        "data": data,
        "page": {
            "nextCursor": encode_cursor(next_offset) if next_offset < total else None,
            "limit": limit,
        },
    }


def build_precheck_report(traces: list[dict], requested_sample_size: int) -> dict:
    spans = [span for trace in traces for span in trace["spans"]]
    trace_ids = [trace["trace_id"] for trace in traces]
    duplicate_trace_ids = len(trace_ids) - len(set(trace_ids))
    root_errors = sum(1 for trace in traces if sum(span["kind"] == "agent" for span in trace["spans"]) != 1)
    parent_errors = sum(
        1
        for trace in traces
        for span in trace["spans"]
        if span["parent_id"] is not None
        and span["parent_id"] not in {item["span_id"] for item in trace["spans"]}
    )
    timestamp_missing = sum(
        1 for span in spans if span["ts_start"] is None or span["ts_end"] is None
    )
    timestamp_disordered = sum(
        1
        for span in spans
        if span["ts_start"] is not None
        and span["ts_end"] is not None
        and span["ts_end"] < span["ts_start"]
    )
    usage_present = sum(
        1
        for span in spans
        if any(span[key] is not None for key in (
            "tokens_prompt", "tokens_completion", "tokens_cache_read", "tokens_cache_write"
        ))
    )
    ontology_present = sum(1 for trace in traces if trace["ontology_id"] is not None)
    action_present = sum(1 for span in spans if span["action"] is not None)

    checks = [
        _check("sample_available", "failed" if not traces else ("warning" if len(traces) < requested_sample_size else "passed"),
               {"requested": requested_sample_size, "actual": len(traces)}),
        _check("trace_id_unique", "failed" if duplicate_trace_ids else "passed", {"duplicates": duplicate_trace_ids}),
        _check("single_root", "failed" if root_errors else "passed", {"invalidTraces": root_errors}),
        _check("parent_closure", "failed" if parent_errors else "passed", {"orphanSpans": parent_errors}),
        _check("timestamps_ordered", "failed" if timestamp_disordered else ("warning" if timestamp_missing else "passed"),
               {"disordered": timestamp_disordered, "missing": timestamp_missing}),
        _check("usage_coverage", "warning" if spans and usage_present == 0 else "passed",
               {"present": usage_present, "total": len(spans)}),
        _check("ontology_metadata_coverage", "warning" if traces and ontology_present == 0 else "passed",
               {"present": ontology_present, "total": len(traces)}),
        _check("action_name_coverage", "failed" if spans and action_present == 0 else "passed",
               {"present": action_present, "total": len(spans)}),
    ]
    return {
        "requestedSampleSize": requested_sample_size,
        "actualTraces": len(traces),
        "actualSpans": len(spans),
        "checks": checks,
    }


def _check(name: str, status: str, metrics: dict) -> dict:
    return {"name": name, "status": status, "metrics": metrics}


def serialize_startup(row) -> dict:
    return {
        "id": row["id"], "profile": row["profile_name"], "profileHash": row["profile_hash"],
        "langfuseVersion": row["langfuse_version"], "checkedAt": row["checked_at"],
        "skipped": bool(row["skipped"]),
    }


def serialize_tenant(row) -> dict:
    return {
        "id": row["id"], "orgId": row["org_id"], "projectId": row["project_id"],
        "queueId": row["queue_id"], "displayName": row["display_name"],
        "createdAt": row["created_at"],
    }


def serialize_ontology(row) -> dict:
    return {
        "id": row["id"], "tenantId": row["tenant_id"], "currentVersion": row["current_version"],
        "tier": row["tier"], "createdAt": row["created_at"],
    }


def serialize_precheck(row) -> dict:
    return {
        "id": row["id"], "ontologyId": row["ontology_id"], "status": row["status"],
        "report": json.loads(row["report_json"] or "{}"), "sampleSize": row["sample_size"],
        "createdAt": row["created_at"], "finishedAt": row["finished_at"],
    }


def serialize_run(row) -> dict:
    return {
        "id": row["id"], "tenantId": row["tenant_id"], "ontologyId": row["ontology_id"],
        "ontologyVersion": 1, "parentRunId": row["parent_run_id"],
        "runType": row["run_type"], "source": row["source"], "sourceRef": row["source_ref"],
        "windowStart": row["window_start"], "windowEnd": row["window_end"],
        "samplingRate": row["sampling_rate"], "status": row["status"],
        "structureVersion": row["structure_version_id"], "anchorVersion": None,
        "codeHash": row["code_hash"], "error": row["error"], "createdAt": row["created_at"],
        "startedAt": row["started_at"], "endedAt": row["ended_at"],
    }


def serialize_step(row) -> dict:
    return {
        "id": row["id"], "runId": row["run_id"], "name": row["name"], "status": row["status"],
        "startedAt": row["started_at"], "endedAt": row["ended_at"],
        "payload": json.loads(row["payload_json"] or "null"),
    }


def serialize_cell(row) -> dict:
    return {
        "id": row["id"], "runId": row["run_id"], "structureVersion": row["structure_version_id"],
        "cellKey": row["cell_key"], "label": row["label"], "parentId": row["parent_id"],
        "dominantAction": row["dominant_action"], "size": row["size"],
        "metrics": json.loads(row["metrics_json"] or "{}"),
    }


def serialize_trace_score(row) -> dict:
    return {
        "id": row["id"], "runId": row["run_id"], "traceId": row["trace_id"],
        "cellId": row["cell_id"], "totalScore": row["total_score"],
        "resultScore": row["result_score"], "processScore": row["process_score"],
        "latencyScore": row["latency_score"], "costScore": row["cost_score"],
        "robustnessScore": row["robustness_score"], "isAlert": bool(row["is_alert"]),
        "isAbstain": bool(row["is_abstain"]), "structureVersion": row["structure_version_id"],
        "ontologyVersion": 1, "codeHash": row["code_hash"],
    }


def _serialize_alert_score(row: dict, decision: dict) -> dict:
    result = serialize_trace_score(row)
    result.update({
        "alertStatus": decision["status"],
        "priority": decision["priority"],
        "priorityRank": decision["rank"],
        "groupKey": decision["group_key"],
        "groupRank": decision["group_rank"],
        "groupSize": decision["group_size"],
        "cause": decision["cause"],
        "causeKind": decision["cause_kind"],
        "reasons": decision["reasons"],
    })
    return result


def serialize_evidence(row) -> dict:
    return {
        "id": row["id"], "traceScoreId": row["trace_score_id"], "dimension": row["dimension"],
        "spanId": row["span_id"], "contribution": row["contribution"],
        "explanation": row["explanation"], "payload": json.loads(row["payload_json"] or "null"),
    }


def serialize_calibration(row) -> dict:
    return {
        "runId": row["run_id"], "kind": row["kind"], "labelCount": row["label_count"],
        "ece": row["ece"], "metrics": json.loads(row["metrics_json"] or "{}"),
    }
