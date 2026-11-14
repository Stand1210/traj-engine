import unittest

from platform.app import store
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


if __name__ == "__main__":
    unittest.main()
