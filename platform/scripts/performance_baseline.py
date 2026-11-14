import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
import tracemalloc
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app import store
from platform.app.algorithm import load_frozen_state
from platform.app.engine import RunEngine
from platform.app.lifecycle import evaluate_lifecycle_state
from platform.app.scheduler import LifecycleScheduler, scheduler_status


DEFAULT_OUTPUT = ROOT / "platform" / "var" / "performance-baseline.json"


class ScaleTraceSource:
    source_type = "scale"

    def __init__(self, traces: list[dict], trace_count: int, limit: int | None = None):
        if not traces:
            raise ValueError("scale source requires at least one base trace")
        if trace_count < 1:
            raise ValueError("trace_count must be positive")
        self.traces = traces
        self.trace_count = trace_count
        self.limit = limit

    def list_traces(self, window: dict, sampling: dict) -> Iterator[dict]:
        rate = float(sampling.get("rate", 1.0))
        if rate <= 0 or rate > 1:
            raise ValueError("sampling rate must be in (0, 1]")
        selected = [self._clone(index) for index in range(self.trace_count)]
        if rate < 1:
            strategy = sampling.get("strategy", "systematic")
            if strategy == "random":
                raise ValueError("scale benchmark requires systematic sampling")
            stride = max(1, round(1 / rate))
            selected = selected[::stride]
        if self.limit is not None:
            selected = selected[: self.limit]
        yield from selected

    def _clone(self, index: int) -> dict:
        trace = self.traces[index % len(self.traces)]
        return {
            **trace,
            "trace_id": f"perf-trace-{index:09d}",
            "session_id": f"perf-session-{index:09d}",
        }


def run_baseline(
    regime: str = "R1",
    trace_count: int = 100000,
    query_repeat: int = 20,
    timeout_seconds: float = 3600.0,
    include_r1: bool = True,
    include_scheduler: bool = True,
    include_queries: bool = True,
) -> dict:
    if trace_count < 1:
        raise ValueError("trace_count must be positive")
    if query_repeat < 1:
        raise ValueError("query_repeat must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    base_traces = load_base_traces(regime)
    source = ScaleTraceSource(base_traces, trace_count)
    run_ids: list[str] = []
    report: dict = {
        "schemaVersion": 1,
        "status": "running",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "regime": regime,
            "traceCount": trace_count,
            "queryRepeat": query_repeat,
            "timeoutSeconds": timeout_seconds,
            "includeR1": include_r1,
            "includeScheduler": include_scheduler,
            "includeQueries": include_queries,
        },
        "environment": {
            "pythonVersion": sys.version.split()[0],
            "platform": sys.platform,
            "machine": os.environ.get("PROCESSOR_ARCHITECTURE", "unknown"),
        },
    }

    workspace_root = Path(ROOT / "platform" / "var") / f"perf-{uuid.uuid4().hex[:12]}"
    db_path = workspace_root / "traj-engine.db"
    artifact_root = workspace_root / "artifacts"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = RunEngine(db_path=db_path, var_root=artifact_root)
    tracemalloc.start()
    try:
        with closing(store.connect(db_path, initialize=True)) as connection:
            tenant_id = store.create_tenant(
                connection,
                "Performance Baseline",
                "perf-org",
                f"perf-project-{uuid.uuid4().hex[:12]}",
                "perf-public-key",
                "perf-secret-key",
            )
            ontology_id = store.create_ontology(
                connection, tenant_id, "Performance Agent", "tier0"
            )

        source_ref = regime
        r2_run_id = _create_and_submit_run(
            engine,
            db_path,
            tenant_id,
            ontology_id,
            source,
            "R2",
            source_ref,
            frozen_state=None,
        )
        run_ids.append(r2_run_id)
        r2_result = _wait_for_run(db_path, r2_run_id, timeout_seconds)
        report["r2Run"] = _run_metrics(
            db_path, r2_run_id, r2_result["elapsedSeconds"], include_steps=True
        )

        if include_r1:
            with closing(store.connect(db_path, initialize=False)) as connection:
                active_structure = store.get_active_structure(connection, ontology_id)
                if active_structure is None or not active_structure["state_json"]:
                    raise RuntimeError("R2 did not create an active frozen structure")
                frozen_state = load_frozen_state(active_structure["state_json"])
                frozen_state["structure_id"] = active_structure["id"]

            r1_run_id = _create_and_submit_run(
                engine,
                db_path,
                tenant_id,
                ontology_id,
                source,
                "R1",
                source_ref,
                frozen_state=frozen_state,
            )
            run_ids.append(r1_run_id)
            r1_result = _wait_for_run(db_path, r1_run_id, timeout_seconds)
            report["r1Run"] = _run_metrics(
                db_path, r1_run_id, r1_result["elapsedSeconds"], include_steps=True
            )

        if include_scheduler:
            report["scheduler"] = _scheduler_metrics(db_path, ontology_id)
        report["database"] = _database_metrics(db_path, run_ids)
        if include_queries:
            report["queries"] = _query_metrics(db_path, run_ids, query_repeat)

        report["peakAllocatedBytes"] = tracemalloc.get_traced_memory()[1]
        report["artifactSizeBytes"] = _directory_size(artifact_root)
        report["status"] = "completed"
        return report
    finally:
        engine.close()
        tracemalloc.stop()
        _remove_directory(workspace_root)


def load_base_traces(regime: str) -> list[dict]:
    path = ROOT / "data" / "bench_v1" / regime / "traces.jsonl"
    if not path.exists():
        raise ValueError(f"benchmark traces not found: {path}")
    traces = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                traces.append(json.loads(line))
    if not traces:
        raise ValueError(f"benchmark traces are empty: {path}")
    return traces


def _create_and_submit_run(
    engine: RunEngine,
    db_path: Path,
    tenant_id: str,
    ontology_id: str,
    source: ScaleTraceSource,
    run_type: str,
    source_ref: str,
    frozen_state: dict | None,
) -> str:
    now = datetime.now(timezone.utc)
    with closing(store.connect(db_path, initialize=False)) as connection:
        run_id = store.create_run(
            connection,
            tenant_id,
            ontology_id,
            "langfuse",
            source_ref,
            run_type,
            (now - timedelta(hours=24)).isoformat(),
            now.isoformat(),
            1.0,
            f"performance-baseline:{run_type.lower()}",
            None,
        )
    engine.submit(
        run_id,
        source_ref,
        1.0,
        None,
        trace_source=source,
        ontology_id=ontology_id,
        frozen_state=frozen_state,
    )
    return run_id


def _wait_for_run(db_path: Path, run_id: str, timeout_seconds: float) -> dict:
    deadline = time.monotonic() + timeout_seconds
    started = time.perf_counter()
    last_run = None
    while time.monotonic() < deadline:
        try:
            with closing(store.connect(db_path, initialize=False)) as connection:
                last_run = store.get_run(connection, run_id)
        except sqlite3.OperationalError as error:
            if "locked" not in str(error).lower():
                raise
            time.sleep(0.5)
            continue
        if last_run is None:
            raise RuntimeError(f"run disappeared: {run_id}")
        if last_run["status"] in {"succeeded", "failed", "canceled"}:
            elapsed = time.perf_counter() - started
            if last_run["status"] != "succeeded":
                raise RuntimeError(
                    f"run {run_id} ended as {last_run['status']}: {last_run['error']}"
                )
            return {"elapsedSeconds": elapsed, "run": last_run}
        time.sleep(0.5)
    raise TimeoutError(f"run {run_id} did not finish within {timeout_seconds} seconds")


def _run_metrics(
    db_path: Path,
    run_id: str,
    elapsed_seconds: float,
    include_steps: bool,
) -> dict:
    with closing(store.connect(db_path, initialize=False)) as connection:
        run = store.get_run(connection, run_id)
        trace_count = connection.execute(
            "SELECT COUNT(*) AS n FROM trace_scores WHERE run_id = ?", (run_id,)
        ).fetchone()["n"]
        cell_count = connection.execute(
            "SELECT COUNT(*) AS n FROM cells WHERE run_id = ?", (run_id,)
        ).fetchone()["n"]
        alert_count = connection.execute(
            "SELECT COUNT(*) AS n FROM alert_decisions WHERE run_id = ?", (run_id,)
        ).fetchone()["n"]
        steps = [
            _serialize_step(row)
            for row in connection.execute(
                "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at, name",
                (run_id,),
            ).fetchall()
        ]
    return {
        "runId": run_id,
        "runType": run["run_type"],
        "status": run["status"],
        "elapsedSeconds": round(elapsed_seconds, 6),
        "millisecondsPerTrace": round(elapsed_seconds * 1000 / trace_count, 6),
        "traceCount": trace_count,
        "cellCount": cell_count,
        "alertCount": alert_count,
        "steps": steps if include_steps else None,
    }


def _database_metrics(db_path: Path, run_ids: list[str]) -> dict:
    with closing(store.connect(db_path, initialize=False)) as connection:
        counts = {}
        for table in (
            "cohort_runs", "run_steps", "cells", "trace_scores",
            "score_evidence", "alert_decisions", "structure_versions",
        ):
            counts[table] = connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    return {
        "sizeBytes": db_path.stat().st_size,
        "rowCounts": counts,
        "runIds": run_ids,
    }


def _query_metrics(db_path: Path, run_ids: list[str], repeat: int) -> list[dict]:
    latest_run_id = run_ids[-1]
    with closing(store.connect(db_path, initialize=False)) as connection:
        trace_score_id = connection.execute(
            "SELECT id FROM trace_scores WHERE run_id = ? ORDER BY trace_id LIMIT 1",
            (latest_run_id,),
        ).fetchone()["id"]
        ontology_id = connection.execute(
            "SELECT ontology_id FROM cohort_runs WHERE id = ?", (latest_run_id,)
        ).fetchone()["ontology_id"]

    queries: list[tuple[str, str, tuple]] = [
        ("runs_page", "SELECT * FROM cohort_runs WHERE ontology_id = ? ORDER BY COALESCE(ended_at, created_at) DESC, id LIMIT 50 OFFSET 0", (ontology_id,)),
        ("trace_scores_page", "SELECT * FROM trace_scores WHERE run_id = ? ORDER BY total_score ASC, trace_id LIMIT 50 OFFSET 0", (latest_run_id,)),
        ("alert_trace_scores", "SELECT * FROM trace_scores WHERE run_id = ? AND is_alert = 1", (latest_run_id,)),
        ("evidence_by_trace", "SELECT * FROM score_evidence WHERE trace_score_id = ? ORDER BY dimension", (trace_score_id,)),
        ("active_structure", "SELECT * FROM structure_versions WHERE ontology_id = ? AND active = 1 LIMIT 1", (ontology_id,)),
        ("scheduler_scan_page", "SELECT * FROM scheduler_scans ORDER BY started_at DESC, id LIMIT 20 OFFSET 0", ()),
    ]
    result = []
    with closing(store.connect(db_path, initialize=False)) as connection:
        for name, sql, parameters in queries:
            timings = []
            row_count = 0
            for _ in range(repeat):
                started = time.perf_counter()
                rows = connection.execute(sql, parameters).fetchall()
                timings.append((time.perf_counter() - started) * 1000)
                row_count = len(rows)
            result.append({
                "name": name,
                "elapsedMs": {
                    "median": round(statistics.median(timings), 6),
                    "min": round(min(timings), 6),
                    "max": round(max(timings), 6),
                },
                "rowCount": row_count,
                "repeat": repeat,
            })
    return result


def _scheduler_metrics(db_path: Path, ontology_id: str) -> dict:
    with closing(store.connect(db_path, initialize=False)) as connection:
        store.upsert_lifecycle_schedule(
            connection,
            ontology_id,
            True,
            "langfuse",
            "performance-baseline",
            24,
            24,
            1.0,
            None,
            0.15,
            0.20,
            False,
            50,
        )

    def evaluator(connection, evaluated_ontology_id: str) -> dict:
        state = evaluate_lifecycle_state(connection, evaluated_ontology_id, False)
        return {
            "ontologyId": evaluated_ontology_id,
            "decision": state["decision"],
            "reason": state["reason"],
            "createdRunId": None,
            "run": None,
        }

    scheduler = LifecycleScheduler(
        db_path=db_path,
        config={
            "intervalSeconds": 60,
            "leaseSeconds": 120,
            "watchdog": {
                "queuedTimeoutSeconds": 900,
                "runningTimeoutSeconds": 86400,
            },
        },
        evaluator=evaluator,
    )
    started = time.perf_counter()
    result = scheduler.execute_scan()
    elapsed_seconds = time.perf_counter() - started
    status = scheduler_status(db_path)
    return {
        "elapsedSeconds": round(elapsed_seconds, 6),
        "result": result,
        "status": status,
    }


def _serialize_step(row) -> dict:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json") or "{}")
    return item


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _remove_directory(path: Path) -> None:
    if path.exists():
        for item in reversed(sorted(path.rglob("*"))):
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
        path.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the M5.0 performance baseline")
    parser.add_argument("--regime", default="R1", choices=[f"R{i}" for i in range(1, 9)])
    parser.add_argument("--traces", type=int, default=100000)
    parser.add_argument("--query-repeat", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--skip-r1", action="store_true")
    parser.add_argument("--skip-scheduler", action="store_true")
    parser.add_argument("--skip-queries", action="store_true")
    args = parser.parse_args()

    report = run_baseline(
        regime=args.regime,
        trace_count=args.traces,
        query_repeat=args.query_repeat,
        timeout_seconds=args.timeout_seconds,
        include_r1=not args.skip_r1,
        include_scheduler=not args.skip_scheduler,
        include_queries=not args.skip_queries,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "output": str(output),
        "traceCount": report["parameters"]["traceCount"],
        "r2ElapsedSeconds": report["r2Run"]["elapsedSeconds"],
        "r1ElapsedSeconds": report.get("r1Run", {}).get("elapsedSeconds"),
        "databaseSizeBytes": report["database"]["sizeBytes"],
        "peakAllocatedBytes": report["peakAllocatedBytes"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
