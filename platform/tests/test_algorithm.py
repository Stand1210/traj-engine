import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platform.app.algorithm import build_dynamic_ontology, run_production, write_production_report
from platform.app import store
from platform.app.engine import RunEngine


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


if __name__ == "__main__":
    unittest.main()
