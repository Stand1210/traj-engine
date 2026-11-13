import argparse
import hashlib
import json
import os
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app import store
from platform.app.engine import RunEngine
from platform.app.langfuse_source import LangfuseTraceSource
from platform.app.config import load_endpoints, load_profile
from platform.scripts.langfuse_production_smoke import IdRangeTraceSource, _find_project


EXPECTED_CODE_HASH = "2064664e6aa5fb46"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run two controlled R2 runs and validate cell lineage")
    parser.add_argument("--source", choices=["langfuse", "benchmark"], default="langfuse")
    parser.add_argument("--profile", default="cloud-v4", choices=["cloud-v4", "selfhosted-v4"])
    parser.add_argument("--project-name", default="development_env")
    parser.add_argument("--minutes", type=int, default=240)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--id-offset", type=int, default=None)
    parser.add_argument("--id-count", type=int, default=None)
    parser.add_argument("--benchmark-regime", default="R1")
    parser.add_argument(
        "--db",
        default=str(ROOT / "platform" / "var" / "traj-engine.db"),
        help="SQLite database path (default: platform/var/traj-engine.db)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    profile = None
    endpoints = None
    keys = None
    trace_source_factory = None
    window = None

    if args.source == "langfuse":
        profile = load_profile(args.profile)
        endpoints = load_endpoints()
        keys = {
            "publicKey": os.environ.get("LANGFUSE_PUBLIC_KEY"),
            "secretKey": os.environ.get("LANGFUSE_SECRET_KEY"),
        }
        if not keys["publicKey"] or not keys["secretKey"]:
            raise SystemExit("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")
        project = _find_project(profile, endpoints, keys, args.project_name)
        if args.id_offset is not None and (args.id_count is None or args.id_count < 1):
            raise SystemExit("--id-offset requires --id-count >= 1")
        end = datetime.now(timezone.utc) + timedelta(minutes=5)
        start = end - timedelta(minutes=args.minutes)
        window = {"start": start.isoformat(), "end": end.isoformat()}

        def langfuse_factory():
            source = LangfuseTraceSource.from_config(
                profile, endpoints, keys,
                max_traces=None if args.id_offset is not None else args.limit,
                max_retries=5,
                retry_backoff_seconds=1.0,
            )
            if args.id_offset is not None:
                return IdRangeTraceSource(source, args.id_offset, args.id_count)
            return source

        trace_source_factory = langfuse_factory
        org_id = project["organization"]["id"]
        project_id = project["id"]
        display_name = f"R2 validation {project['name']}"
    else:
        benchmark_path = ROOT / "data" / "bench_v1" / args.benchmark_regime
        if not benchmark_path.exists():
            raise SystemExit(f"benchmark regime not found: {benchmark_path}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        org_id = f"r2-validation-{stamp}"
        project_id = org_id
        display_name = "R2 benchmark validation"
        window = {
            "start": "2025-12-31T00:00:00Z",
            "end": "2026-01-02T00:00:00Z",
        }

        def benchmark_factory():
            return ListTraceSource(_benchmark_traces(args.benchmark_regime, args.limit))

        trace_source_factory = benchmark_factory

    with closing(store.connect(db_path, initialize=True)) as connection:
        tenant = connection.execute(
            "SELECT * FROM tenants WHERE org_id = ? AND project_id = ?", (org_id, project_id)
        ).fetchone()
        if tenant is None:
            tenant_id = store.create_tenant(
                connection,
                display_name,
                org_id,
                project_id,
                keys["publicKey"] if keys else "internal",
                keys["secretKey"] if keys else "internal",
            )
        else:
            tenant_id = tenant["id"]

        ontology = connection.execute(
            "SELECT * FROM ontologies WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if ontology is None:
            ontology_id = store.create_ontology(connection, tenant_id, display_name, "tier0")
        else:
            ontology_id = ontology["id"]

        structure_count_before = int(
            connection.execute(
                "SELECT COUNT(*) AS n FROM structure_versions WHERE ontology_id = ?",
                (ontology_id,),
            ).fetchone()["n"]
        )
        source = "langfuse" if args.source == "langfuse" else "jsonl"
        source_ref = "r2-lineage-validation-langfuse" if source == "langfuse" else args.benchmark_regime
        first_run_id = store.create_run(
            connection, tenant_id, ontology_id, source, source_ref, "R2",
            window["start"], window["end"], 1.0, "r2_lineage_validation:first", None,
        )
        second_run_id = store.create_run(
            connection, tenant_id, ontology_id, source, source_ref, "R2",
            window["start"], window["end"], 1.0, "r2_lineage_validation:second", None,
        )

    engine = RunEngine(db_path)
    try:
        engine.submit(
            first_run_id, source_ref, 1.0, args.limit,
            trace_source=trace_source_factory(), window=window, ontology_id=ontology_id,
        )
        first_run = _wait_for_run(db_path, first_run_id)
        if first_run["status"] != "succeeded":
            raise RuntimeError(f"first R2 run failed: {first_run['error']}")
        first_score_digest = _score_digest(db_path, first_run_id)
        engine.submit(
            second_run_id, source_ref, 1.0, args.limit,
            trace_source=trace_source_factory(), window=window, ontology_id=ontology_id,
        )
    finally:
        engine.close()

    with closing(store.connect(db_path, initialize=False)) as connection:
        first_run = store.get_run(connection, first_run_id)
        second_run = store.get_run(connection, second_run_id)
        structure_count_after = int(
            connection.execute(
                "SELECT COUNT(*) AS n FROM structure_versions WHERE ontology_id = ?",
                (ontology_id,),
            ).fetchone()["n"]
        )
        active_structure = store.get_active_structure(connection, ontology_id)
        first_scores = _score_rows(connection, first_run_id)
        second_scores = _score_rows(connection, second_run_id)
        lineage = connection.execute(
            "SELECT * FROM cell_lineage WHERE run_id = ? ORDER BY relation, old_cell_id, new_cell_id",
            (second_run_id,),
        ).fetchall()

    checks = {
        "firstRunSucceeded": first_run["status"] == "succeeded",
        "secondRunSucceeded": second_run["status"] == "succeeded",
        "structureVersionsCreated": structure_count_after - structure_count_before == 2,
        "activeStructureIsSecond": active_structure is not None and second_run["structure_version_id"] == active_structure["id"],
        "firstScoresImmutable": _score_digest(db_path, first_run_id) == first_score_digest,
        "firstScoresPresent": len(first_scores) > 0,
        "secondScoresPresent": len(second_scores) > 0,
        "lineagePresent": len(lineage) > 0,
        "lineageRelationsValid": all(row["relation"] in {"continued", "split", "merged"} for row in lineage),
        "lineageOverlapValid": all(0 < float(row["overlap"]) <= 1 for row in lineage),
        "codeHashPreserved": first_run["code_hash"] == EXPECTED_CODE_HASH and second_run["code_hash"] == EXPECTED_CODE_HASH,
    }
    result = {
        "source": args.source,
        "firstRunId": first_run_id,
        "secondRunId": second_run_id,
        "firstRunStatus": first_run["status"],
        "secondRunStatus": second_run["status"],
        "structureVersionsBefore": structure_count_before,
        "structureVersionsAfter": structure_count_after,
        "activeStructureId": active_structure["id"] if active_structure else None,
        "firstTraceCount": len(first_scores),
        "secondTraceCount": len(second_scores),
        "lineageEdgeCount": len(lineage),
        "lineageRelationCounts": {
            relation: sum(1 for row in lineage if row["relation"] == relation)
            for relation in ("continued", "split", "merged")
        },
        "firstScoreDigest": first_score_digest,
        "checks": checks,
        "passed": all(checks.values()),
    }
    if not result["passed"]:
        result["errors"] = {
            "firstRun": first_run["error"],
            "secondRun": second_run["error"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


def _score_rows(connection, run_id: str) -> list[dict]:
    return connection.execute(
        """SELECT trace_id, cell_id, total_score, result_score, process_score,
                  latency_score, cost_score, robustness_score, deduction_total, evidence_sum
           FROM trace_scores WHERE run_id = ? ORDER BY trace_id""",
        (run_id,),
    ).fetchall()


def _wait_for_run(db_path: Path, run_id: str, timeout_seconds: int = 600) -> dict:
    deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds
    while datetime.now(timezone.utc).timestamp() < deadline:
        with closing(store.connect(db_path, initialize=False)) as connection:
            run = store.get_run(connection, run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for run {run_id}")


def _score_digest(db_path: Path, run_id: str) -> str:
    with closing(store.connect(db_path, initialize=False)) as connection:
        payload = "\n".join(
            json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
            for row in _score_rows(connection, run_id)
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ListTraceSource:
    source_type = "r2-validation-list"

    def __init__(self, traces: list[dict]):
        self.traces = traces
        self.traversal = {"traces": len(traces)}

    def list_traces(self, window: dict, sampling: dict):
        yield from self.traces


def _benchmark_traces(regime: str, count: int) -> list[dict]:
    path = ROOT / "data" / "bench_v1" / regime / "traces.jsonl"
    if not path.exists():
        raise SystemExit(f"benchmark traces not found: {path}")
    traces = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                traces.append(json.loads(line))
            if len(traces) == count:
                break
    if len(traces) < count:
        raise SystemExit(f"benchmark has only {len(traces)} traces, requested {count}")
    return traces


if __name__ == "__main__":
    raise SystemExit(main())
