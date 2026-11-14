import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from collections import Counter
from pathlib import Path
from typing import Any

from bench.runner import run_regime
from platform.app.algorithm import dump_frozen_state, run_production, write_production_report
from platform.app.alerts import persist_alert_decisions

from platform.app import store
from platform.app.trace_source import JsonlTraceSource


ROOT = Path(__file__).resolve().parents[2]
VAR_ROOT = ROOT / "platform" / "var"
DIMENSION_MAP = {
    "O": "result",
    "P": "process",
    "L": "latency",
    "C": "cost",
    "R": "robustness",
}


class RunEngine:
    def __init__(
        self,
        db_path: str | Path = store.DEFAULT_DB_PATH,
        max_workers: int = 1,
        var_root: str | Path = VAR_ROOT,
    ):
        self.db_path = Path(db_path)
        self.var_root = Path(var_root)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="traj-run")
        self.canceled_runs: set[str] = set()

    def submit(
        self,
        run_id: str,
        source_ref: str,
        sampling_rate: float,
        limit: int | None,
        trace_source=None,
        window: dict | None = None,
        ontology_id: str | None = None,
        frozen_state: dict | None = None,
        score_writer=None,
        writeback_strict: bool = False,
    ) -> None:
        self.executor.submit(
            self._execute, run_id, source_ref, sampling_rate, limit,
            trace_source, window, ontology_id,
            frozen_state, score_writer, writeback_strict,
        )

    def cancel(self, run_id: str) -> None:
        self.canceled_runs.add(run_id)

    def _is_canceled(self, run_id: str) -> bool:
        return run_id in self.canceled_runs

    def _execute(
        self,
        run_id: str,
        source_ref: str,
        sampling_rate: float,
        limit: int | None,
        trace_source=None,
        window: dict | None = None,
        ontology_id: str | None = None,
        frozen_state: dict | None = None,
        score_writer=None,
        writeback_strict: bool = False,
    ) -> None:
        run_dir = self.var_root / "runs" / run_id
        data_root = run_dir / "data"
        out_root = run_dir / "reports"
        try:
            data_root.mkdir(parents=True, exist_ok=True)
            out_root.mkdir(parents=True, exist_ok=True)
            with closing(store.connect(self.db_path)) as connection:
                store.set_run_status(connection, run_id, "running", started=True)

            with closing(store.connect(self.db_path)) as connection:
                store.upsert_run_step(connection, run_id, "load_source", "running")
            source = trace_source or JsonlTraceSource(source_ref, limit=limit)
            effective_window = window or {"start": None, "end": None}
            traces = list(source.list_traces(
                effective_window,
                {"rate": sampling_rate, "seed": 0, "strategy": "systematic"},
            ))
            if not traces:
                raise ValueError("selected trace source is empty")
            regime_dir = data_root / source_ref
            regime_dir.mkdir(parents=True, exist_ok=True)
            with (regime_dir / "traces.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
                for trace in traces:
                    handle.write(json.dumps(trace, ensure_ascii=False, sort_keys=True) + "\n")
            is_benchmark = isinstance(source, JsonlTraceSource)
            if is_benchmark:
                benchmark_root = ROOT / "data" / "bench_v1" / source_ref
                shutil.copy2(benchmark_root / "gt.jsonl", regime_dir / "gt.jsonl")
                shutil.copy2(benchmark_root / "meta.json", regime_dir / "meta.json")
            with closing(store.connect(self.db_path)) as connection:
                store.upsert_run_step(
                    connection, run_id, "load_source", "succeeded",
                    {"n_traces": len(traces), "source_ref": source_ref}, ended=True,
                )

            with closing(store.connect(self.db_path)) as connection:
                store.upsert_run_step(connection, run_id, "algorithm", "running")
            if is_benchmark:
                result = run_regime(source_ref, data_root=data_root, out_root=out_root)
            else:
                result, score_rows = run_production(
                    traces,
                    ontology_id or source_ref,
                    frozen_state=frozen_state,
                )
                write_production_report(out_root / source_ref, result, score_rows)
            if self._is_canceled(run_id):
                return
            with closing(store.connect(self.db_path)) as connection:
                store.upsert_run_step(
                    connection, run_id, "algorithm", "succeeded",
                    {"code_hash": result["code_hash"], "spec_hash": result["spec_hash"],
                     "n": result["n"], "cold_start": result.get("cold_start")},
                    ended=True,
                )

            with closing(store.connect(self.db_path)) as connection:
                store.upsert_run_step(connection, run_id, "persist", "running")
                self._persist_results(connection, run_id, result, out_root / source_ref)
                baseline_path = ROOT / "reports" / source_ref / "scores.jsonl"
                exact = None
                if is_benchmark and source_ref == "R1" and sampling_rate == 1.0 and limit is None:
                    generated = (out_root / source_ref / "scores.jsonl").read_bytes()
                    expected = baseline_path.read_bytes()
                    exact = generated == expected
                    if not exact:
                        raise RuntimeError("M1 reproducibility check failed: scores.jsonl differs")
                store.upsert_run_step(
                    connection, run_id, "persist", "succeeded",
                    {"benchmark_exact": exact}, ended=True,
                )
                alert_summary = persist_alert_decisions(connection, run_id)
                store.upsert_run_step(
                    connection, run_id, "alert_budget", "succeeded", alert_summary, ended=True,
                )
                if score_writer is None:
                    store.upsert_run_step(
                        connection, run_id, "score_writeback", "skipped",
                        {"reason": "not_requested"}, ended=True,
                    )
                else:
                    store.upsert_run_step(connection, run_id, "score_writeback", "running")
                    writeback = None
                    try:
                        score_rows = []
                        with (out_root / source_ref / "scores.jsonl").open(encoding="utf-8") as handle:
                            for line in handle:
                                if line.strip():
                                    score_rows.append(json.loads(line))
                        run = store.get_run(connection, run_id)
                        writeback = score_writer.write_scores(score_rows, run)
                        writeback_status = "succeeded" if writeback["rejected"] == 0 else "failed"
                        store.upsert_run_step(
                            connection, run_id, "score_writeback", writeback_status, writeback, ended=True,
                        )
                        if writeback_status == "failed" and writeback_strict:
                            raise RuntimeError("Langfuse score writeback rejected at least one score")
                    except Exception as error:
                        payload = writeback if writeback is not None else {"error": str(error)}
                        if writeback_strict:
                            store.upsert_run_step(
                                connection, run_id, "score_writeback", "failed", payload, ended=True,
                            )
                            raise
                        store.upsert_run_step(
                            connection, run_id, "score_writeback", "failed",
                            payload, ended=True,
                        )
                store.set_run_status(connection, run_id, "succeeded", ended=True)
                self.canceled_runs.discard(run_id)
        except Exception as error:
            with closing(store.connect(self.db_path)) as connection:
                store.set_run_status(connection, run_id, "failed", error=str(error), ended=True)
                store.upsert_run_step(connection, run_id, "failure", "failed", {"error": str(error)}, ended=True)
            raise

    def _persist_results(
        self,
        connection: Any,
        run_id: str,
        result: dict,
        report_dir: Path,
    ) -> None:
        run = store.get_run(connection, run_id)
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        frozen_state = result.get("frozen_state")
        reuse_structure_id = (
            frozen_state.get("structure_id")
            if result.get("run_mode") == "R1" and frozen_state is not None
            else None
        )
        if reuse_structure_id is not None:
            structure_row = connection.execute(
                "SELECT id FROM structure_versions WHERE id = ? AND ontology_id = ?",
                (reuse_structure_id, run["ontology_id"]),
            ).fetchone()
            if structure_row is None:
                raise ValueError("frozen structure version not found")
            structure_id = reuse_structure_id
        else:
            previous_run = connection.execute(
                """SELECT id FROM cohort_runs
                   WHERE ontology_id = ? AND id <> ? AND status = 'succeeded'
                   ORDER BY COALESCE(ended_at, created_at) DESC LIMIT 1""",
                (run["ontology_id"], run_id),
            ).fetchone()
            old_assignments = {}
            if previous_run is not None:
                old_assignments = {
                    row["trace_id"]: row["cell_id"]
                    for row in connection.execute(
                        """SELECT trace_id, cell_id FROM trace_scores
                           WHERE run_id = ? AND cell_id IS NOT NULL""",
                        (previous_run["id"],),
                    ).fetchall()
                }
            structure_id = store.new_id("structure")
            next_structure_version = 1 + int(
                connection.execute(
                    "SELECT COALESCE(MAX(version), 0) AS max_version FROM structure_versions WHERE ontology_id = ?",
                    (run["ontology_id"],),
                ).fetchone()["max_version"]
            )
            connection.execute(
                "UPDATE structure_versions SET active = 0 WHERE ontology_id = ? AND active = 1",
                (run["ontology_id"],),
            )
            persisted_state = dict(frozen_state or {})
            persisted_state["structure_id"] = structure_id
            connection.execute(
                """INSERT INTO structure_versions
                   (id, ontology_id, version, code_hash, state_json, created_at, active)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (structure_id, run["ontology_id"], next_structure_version, result["code_hash"],
                 dump_frozen_state(persisted_state), store.utcnow()),
            )
        connection.execute(
            "UPDATE cohort_runs SET structure_version_id = ? WHERE id = ?",
            (structure_id, run_id),
        )

        score_rows = []
        with (report_dir / "scores.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    score_rows.append(json.loads(line))

        cell_sizes: dict[str, int] = {}
        for row in score_rows:
            cell_key = row.get("cell")
            if cell_key is not None:
                cell_sizes[cell_key] = cell_sizes.get(cell_key, 0) + 1

        cell_ids: dict[str, str] = {}
        for cell_key, size in sorted(cell_sizes.items()):
            cell_id = store.new_id("cell")
            cell_ids[cell_key] = cell_id
            connection.execute(
                """INSERT INTO cells
                   (id, run_id, structure_version_id, cell_key, label, parent_id,
                    dominant_action, size, metrics_json, created_at)
                   VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)""",
                (cell_id, run_id, structure_id, cell_key, cell_key, size,
                 json.dumps({"size": size}, sort_keys=True), store.utcnow()),
            )

        if reuse_structure_id is None:
            self._record_cell_lineage(
                connection, run_id, old_assignments, score_rows, cell_ids
            )

        trace_score_ids: dict[str, str] = {}
        for row in score_rows:
            trace_id = row["trace_id"]
            evidence_sum = float(sum(row.get("contrib", {}).values()))
            trace_score_id = store.new_id("score")
            trace_score_ids[trace_id] = trace_score_id
            connection.execute(
                """INSERT INTO trace_scores
                   (id, run_id, tenant_id, trace_id, cell_id, total_score,
                    result_score, process_score, latency_score, cost_score,
                    robustness_score, deduction_total, evidence_sum, is_alert,
                    is_abstain, ontology_version_id, structure_version_id,
                    code_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trace_score_id, run_id, run["tenant_id"], trace_id,
                 cell_ids.get(row.get("cell")), float(row["S"]),
                 float(row["dims"]["O"]), float(row["dims"]["P"]),
                 float(row["dims"]["L"]), float(row["dims"]["C"]),
                 float(row["dims"]["R"]), evidence_sum, evidence_sum,
                 int(bool(row.get("alert"))), int(bool(row.get("novelty"))),
                 run["ontology_version_id"], structure_id, result["code_hash"],
                 store.utcnow()),
            )
            evidence_payload = row.get("evidence") or []
            for dimension_key, contribution in row.get("contrib", {}).items():
                dimension = DIMENSION_MAP[dimension_key]
                connection.execute(
                    """INSERT INTO score_evidence
                       (id, trace_score_id, dimension, span_id, contribution,
                        explanation, payload_json, created_at)
                       VALUES (?, ?, ?, NULL, ?, ?, ?, ?)""",
                    (store.new_id("evidence"), trace_score_id, dimension,
                     float(contribution),
                     f"Dimension {dimension} contribution for trace {trace_id}",
                     json.dumps({"kernel_evidence": evidence_payload}, ensure_ascii=False,
                                sort_keys=True), store.utcnow()),
                )

        calibration = result.get("calibration") or {}
        connection.execute(
            """INSERT INTO calibration_runs
               (id, run_id, kind, model_version, label_count, ece, metrics_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (store.new_id("calibration"), run_id,
             calibration.get("kind") or "none", result.get("pipeline_version"),
             calibration.get("n_labels"), calibration.get("ece_oof"),
             json.dumps(calibration, ensure_ascii=False, sort_keys=True), store.utcnow()),
        )
        connection.commit()

    def _record_cell_lineage(
        self,
        connection: Any,
        run_id: str,
        old_assignments: dict[str, str],
        score_rows: list[dict],
        new_cell_ids: dict[str, str],
    ) -> None:
        if not old_assignments or not new_cell_ids:
            return
        new_assignments = {
            row["trace_id"]: row.get("cell")
            for row in score_rows
            if row.get("cell") is not None
        }
        overlap: dict[tuple[str, str], int] = {}
        for trace_id, old_cell_id in old_assignments.items():
            new_cell_key = new_assignments.get(trace_id)
            if new_cell_key is not None:
                key = (old_cell_id, new_cell_ids[new_cell_key])
                overlap[key] = overlap.get(key, 0) + 1
        if not overlap:
            return

        old_out: dict[str, int] = {}
        new_in: dict[str, int] = {}
        for (old_cell_id, new_cell_id), count in overlap.items():
            old_out[old_cell_id] = old_out.get(old_cell_id, 0) + 1
            new_in[new_cell_id] = new_in.get(new_cell_id, 0) + 1
        old_sizes = dict(Counter(old_assignments.values()))
        for (old_cell_id, new_cell_id), count in overlap.items():
            if old_out[old_cell_id] == 1 and new_in[new_cell_id] == 1:
                relation = "continued"
            elif old_out[old_cell_id] > 1:
                relation = "split"
            else:
                relation = "merged"
            connection.execute(
                """INSERT INTO cell_lineage
                   (id, run_id, old_cell_id, new_cell_id, relation, overlap, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (store.new_id("lineage"), run_id, old_cell_id, new_cell_id, relation,
                 count / max(old_sizes.get(old_cell_id, count), 1), store.utcnow()),
            )

    def close(self) -> None:
        self.executor.shutdown(wait=True)


ENGINE = RunEngine()
