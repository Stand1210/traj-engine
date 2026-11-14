import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platform.app.algorithm import (
    build_dynamic_ontology,
    dump_frozen_state,
    load_frozen_state,
    run_production,
    write_production_report,
    write_production_scores,
)
from platform.app import store
from platform.app.engine import RunEngine
from platform.app.service import get_lineage


ROOT = Path(__file__).resolve().parents[2]


class FakeTraceSource:
    source_type = "fake"

    def __init__(self, traces):
        self.traces = traces

    def list_traces(self, window, sampling):
        yield from self.traces


class ProductionAlgorithmTest(unittest.TestCase):
    def test_runs_dynamic_ontology_on_benchmark_subset(self):
        traces = []
        with (ROOT / "data" / "bench_v1" / "R1" / "traces.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                traces.append(json.loads(line))
                if len(traces) == 100:
                    break

        ontology = build_dynamic_ontology(traces, "ontology-test")
        result, scores = run_production(traces, "ontology-test")

        self.assertIn("plan", ontology["actions"])
        self.assertEqual({}, ontology["required_steps"])
        self.assertEqual(100, result["n"])
        self.assertTrue(result["cold_start"])
        self.assertEqual(100, len(scores))
        self.assertTrue(all(row["alert"] is False for row in scores))

        with tempfile.TemporaryDirectory() as directory:
            report_dir = write_production_report(Path(directory), result, scores)
            persisted = [json.loads(line) for line in (report_dir / "scores.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(100, len(persisted))

    def test_streaming_score_output_is_equivalent_to_list_output(self):
        traces = []
        with (ROOT / "data" / "bench_v1" / "R1" / "traces.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                traces.append(json.loads(line))
                if len(traces) == 100:
                    break

        list_result, list_scores = run_production(traces, "ontology-stream-test")
        streamed_rows = []
        streaming_result, returned_scores = run_production(
            traces,
            "ontology-stream-test",
            score_sink=streamed_rows.append,
            score_batch_size=7,
        )

        self.assertEqual([], returned_scores)
        self.assertEqual(100, len(streamed_rows))
        self.assertEqual(list_result["scoring"], streaming_result["scoring"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            list_report = write_production_scores(root / "list", list_scores)
            stream_report = write_production_scores(root / "stream", streamed_rows)
            self.assertEqual(
                (list_report / "scores.jsonl").read_bytes(),
                (stream_report / "scores.jsonl").read_bytes(),
            )

    def test_engine_persists_production_run(self):
        traces = []
        with (ROOT / "data" / "bench_v1" / "R1" / "traces.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                traces.append(json.loads(line))
                if len(traces) == 20:
                    break

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "smoke", "R1",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0, "test", None,
                )
            finally:
                connection.close()

            engine = RunEngine(db_path)
            try:
                with patch("platform.app.engine.VAR_ROOT", root / "var"):
                    engine.submit(
                        run_id, "smoke", 1.0, 20, trace_source=FakeTraceSource(traces),
                        window={"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
                        ontology_id=ontology_id,
                    )
            finally:
                engine.close()

            connection = store.connect(db_path)
            try:
                run = store.get_run(connection, run_id)
                score_count = connection.execute(
                    "SELECT COUNT(*) AS n FROM trace_scores WHERE run_id = ?", (run_id,)
                ).fetchone()["n"]
            finally:
                connection.close()

            self.assertEqual("succeeded", run["status"])
            self.assertEqual(20, score_count)

            connection = store.connect(db_path)
            frozen_row = connection.execute(
                """SELECT id, state_json FROM structure_versions
                   WHERE ontology_id = ? ORDER BY version DESC LIMIT 1""",
                (ontology_id,),
            ).fetchone()
            frozen_state = load_frozen_state(frozen_row["state_json"])
            frozen_state["structure_id"] = frozen_row["id"]
            second_run_id = store.create_run(
                connection, tenant_id, ontology_id, "langfuse", "smoke-r1", "R1",
                "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z", 1.0, "test", None,
            )
            connection.close()

            engine = RunEngine(db_path)
            try:
                with patch("platform.app.engine.VAR_ROOT", root / "var"):
                    engine.submit(
                        second_run_id, "smoke-r1", 1.0, 20,
                        trace_source=FakeTraceSource(traces),
                        window={"start": "2026-01-02T00:00:00Z", "end": "2026-01-03T00:00:00Z"},
                        ontology_id=ontology_id,
                        frozen_state=frozen_state,
                    )
            finally:
                engine.close()

            connection = store.connect(db_path)
            try:
                second_run = store.get_run(connection, second_run_id)
                structure_count = connection.execute(
                    "SELECT COUNT(*) AS n FROM structure_versions WHERE ontology_id = ?",
                    (ontology_id,),
                ).fetchone()["n"]
            finally:
                connection.close()

            self.assertEqual("succeeded", second_run["status"])
            self.assertEqual(frozen_row["id"], second_run["structure_version_id"])
            self.assertEqual(1, structure_count)

    def test_score_writeback_failure_does_not_fail_run_by_default(self):
        traces = []
        with (ROOT / "data" / "bench_v1" / "R1" / "traces.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                traces.append(json.loads(line))
                if len(traces) == 20:
                    break

        class FailingWriter:
            def write_scores(self, score_rows, run):
                raise RuntimeError("network unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "smoke", "R1",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0, "test", None,
                )
            finally:
                connection.close()

            engine = RunEngine(db_path)
            try:
                with patch("platform.app.engine.VAR_ROOT", root / "var"):
                    engine.submit(
                        run_id, "smoke", 1.0, 20, trace_source=FakeTraceSource(traces),
                        ontology_id=ontology_id, score_writer=FailingWriter(),
                    )
            finally:
                engine.close()

            connection = store.connect(db_path)
            try:
                run = store.get_run(connection, run_id)
                step = connection.execute(
                    "SELECT status, payload_json FROM run_steps WHERE run_id = ? AND name = 'score_writeback'",
                    (run_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual("succeeded", run["status"])
            self.assertEqual("failed", step["status"])

    def test_engine_creates_r2_structure(self):
        traces = []
        with (ROOT / "data" / "bench_v1" / "R1" / "traces.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                traces.append(json.loads(line))
                if len(traces) == 20:
                    break

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "smoke-r2", "R2",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0, "test", None,
                )
                second_run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "smoke-r2-2", "R2",
                    "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z", 1.0, "test-r2", None,
                )
            finally:
                connection.close()

            engine = RunEngine(db_path)
            try:
                with patch("platform.app.engine.VAR_ROOT", root / "var"):
                    engine.submit(
                        run_id, "smoke-r2", 1.0, 20,
                        trace_source=FakeTraceSource(traces),
                        window={"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
                        ontology_id=ontology_id,
                    )
                    engine.submit(
                        second_run_id, "smoke-r2-2", 1.0, 20,
                        trace_source=FakeTraceSource(traces),
                        window={"start": "2026-01-02T00:00:00Z", "end": "2026-01-03T00:00:00Z"},
                        ontology_id=ontology_id,
                    )
            finally:
                engine.close()

            connection = store.connect(db_path)
            try:
                run = store.get_run(connection, run_id)
                structures = connection.execute(
                    "SELECT COUNT(*) AS n FROM structure_versions WHERE ontology_id = ?",
                    (ontology_id,),
                ).fetchone()["n"]
                lineage = connection.execute(
                    "SELECT relation, COUNT(*) AS n FROM cell_lineage WHERE run_id = ? GROUP BY relation",
                    (second_run_id,),
                ).fetchall()
                lineage_edges = get_lineage(second_run_id, connection)
            finally:
                connection.close()

            self.assertEqual("succeeded", run["status"])
            self.assertEqual(2, structures)
            self.assertTrue(lineage)
            self.assertTrue(all(row["relation"] == "continued" for row in lineage))
            self.assertTrue(lineage_edges)
            self.assertTrue(all(
                edge["oldCellKey"] is not None and edge["newCellKey"] is not None
                for edge in lineage_edges
            ))

    def test_frozen_state_roundtrip_replays_assignments(self):
        traces = []
        with (ROOT / "data" / "bench_v1" / "R1" / "traces.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                traces.append(json.loads(line))
                if len(traces) == 40:
                    break

        initial_result, initial_scores = run_production(traces, "ontology-frozen-test")
        frozen_state = load_frozen_state(dump_frozen_state(initial_result["frozen_state"]))
        frozen_result, frozen_scores = run_production(
            traces, "ontology-frozen-test", frozen_state=frozen_state
        )

        initial_cells = [(row["trace_id"], row["cell"], row["novelty"]) for row in initial_scores]
        frozen_cells = [(row["trace_id"], row["cell"], row["novelty"]) for row in frozen_scores]
        self.assertEqual("R2", initial_result["run_mode"])
        self.assertEqual("R1", frozen_result["run_mode"])
        self.assertEqual(initial_cells, frozen_cells)
        self.assertTrue(frozen_result["cluster_info"]["frozen_structure"])


if __name__ == "__main__":
    unittest.main()
