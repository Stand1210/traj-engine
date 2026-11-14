import unittest
import tempfile
from pathlib import Path

from platform.app import store
from platform.app.config import load_performance_config
from platform.app.engine import RunEngine, select_r2_training_traces
from platform.scripts.performance_baseline import ScaleTraceSource, load_base_traces, run_baseline


class PerformanceBaselineTest(unittest.TestCase):
    def test_scale_source_clones_unique_trace_ids(self):
        base_traces = load_base_traces("R1")
        source = ScaleTraceSource(base_traces, 5)
        traces = list(source.list_traces({"start": None, "end": None}, {"rate": 1.0}))

        self.assertEqual(5, len(traces))
        self.assertEqual(5, len({trace["trace_id"] for trace in traces}))
        self.assertEqual(5, len({trace["session_id"] for trace in traces}))
        self.assertEqual(base_traces[0]["spans"], traces[0]["spans"])

    def test_small_baseline_runs_r2_r1_scheduler_and_queries(self):
        report = run_baseline(
            regime="R1",
            trace_count=24,
            query_repeat=2,
            timeout_seconds=60,
        )

        self.assertEqual("completed", report["status"])
        self.assertEqual(24, report["r2Run"]["traceCount"])
        self.assertEqual(24, report["r1Run"]["traceCount"])
        self.assertEqual("succeeded", report["r2Run"]["status"])
        self.assertEqual("succeeded", report["r1Run"]["status"])
        self.assertGreater(report["database"]["sizeBytes"], 0)
        self.assertGreater(report["peakAllocatedBytes"], 0)
        self.assertEqual(6, len(report["queries"]))
        self.assertEqual("succeeded", report["scheduler"]["result"]["status"])
        self.assertGreaterEqual(report["scheduler"]["status"]["enabledSchedules"], 1)

    def test_scale_source_rejects_random_sampling(self):
        source = ScaleTraceSource(load_base_traces("R1"), 2)
        with self.assertRaises(ValueError):
            list(source.list_traces({}, {"rate": 0.5, "strategy": "random"}))

    def test_performance_config_is_validated(self):
        config = load_performance_config()
        self.assertGreaterEqual(config["r2TrainingLimit"], 2)

    def test_r2_training_selection_is_deterministic_and_bounded(self):
        traces = [{"trace_id": f"trace-{index}"} for index in range(101)]

        first = select_r2_training_traces(traces, 8)
        second = select_r2_training_traces(traces, 8)

        self.assertEqual(first, second)
        self.assertEqual(8, len(first))
        self.assertEqual("trace-0", first[0]["trace_id"])
        self.assertEqual("trace-100", first[-1]["trace_id"])

    def test_engine_samples_r2_training_then_scores_full_window(self):
        base_traces = load_base_traces("R1")[:30]
        traces = [
            {**trace, "trace_id": f"sample-r2-{index:09d}"}
            for index, trace in enumerate(base_traces)
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(
                    connection, "Owner", "perf-org", "perf-project", "pk", "sk"
                )
                ontology_id = store.create_ontology(
                    connection, tenant_id, "Sampled R2", "tier0"
                )
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "sample-r2", "R2",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0,
                    "test", None,
                )
            finally:
                connection.close()

            engine = RunEngine(
                db_path=db_path,
                var_root=root / "var",
                r2_training_limit=8,
            )
            try:
                engine.submit(
                    run_id, "sample-r2", 1.0, None,
                    trace_source=ScaleTraceSource(traces, len(traces)),
                    ontology_id=ontology_id,
                )
            finally:
                engine.close()

            connection = store.connect(db_path, initialize=False)
            try:
                run = store.get_run(connection, run_id)
                trace_count = connection.execute(
                    "SELECT COUNT(*) AS n FROM trace_scores WHERE run_id = ?", (run_id,)
                ).fetchone()["n"]
                algorithm_step = connection.execute(
                    """SELECT payload_json FROM run_steps
                       WHERE run_id = ? AND name = 'algorithm'""",
                    (run_id,),
                ).fetchone()["payload_json"]
            finally:
                connection.close()

            self.assertEqual("succeeded", run["status"])
            self.assertEqual(30, trace_count)
            self.assertIn('"sampled": true', algorithm_step)
            self.assertIn('"trainingTraceCount": 8', algorithm_step)
            self.assertIn('"fullTraceCount": 30', algorithm_step)


if __name__ == "__main__":
    unittest.main()
