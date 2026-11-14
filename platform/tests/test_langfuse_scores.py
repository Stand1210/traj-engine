import json
import unittest

from platform.app.langfuse_scores import LangfuseScoreWriter


class FakeScoreTransport:
    def __init__(self, responses=None):
        self.responses = responses or [{"message": "Accepted"}]
        self.requests = []

    def __call__(self, url, body, headers):
        self.requests.append({"url": url, "body": json.loads(body), "headers": headers})
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


class LangfuseScoreWriterTest(unittest.TestCase):
    def test_builds_total_and_boolean_scores(self):
        row = {
            "trace_id": "trace-1",
            "S": 92.5,
            "cell": "cell-1",
            "alert": True,
            "novelty": False,
            "grade_abs": "A",
            "dims": {"O": 1.0, "P": 0.9, "L": 0.8, "C": 0.7, "R": 0.6},
        }
        run = {"id": "run-1", "created_at": "2026-01-01T00:00:00Z", "code_hash": "hash"}
        writer = LangfuseScoreWriter("https://langfuse.example", "pk", "sk")
        total = writer.build_score_payload(row, run)
        statuses = writer.build_status_payloads(row, run)

        self.assertEqual("trace-1", total["traceId"])
        self.assertEqual("NUMERIC", total["dataType"])
        self.assertEqual(92.5, total["value"])
        self.assertEqual(32, len(total["id"]))
        self.assertEqual({"runId": "run-1", "cell": "cell-1"}, statuses[0]["metadata"])
        self.assertEqual(1, statuses[0]["value"])
        self.assertEqual(0, statuses[1]["value"])

    def test_batches_and_accepts_202_response(self):
        transport = FakeScoreTransport()
        writer = LangfuseScoreWriter(
            "https://langfuse.example/", "pk", "sk", "/custom/scores",
            batch_size=3, transport=transport,
        )
        result = writer.write_scores([
            {"trace_id": f"trace-{i}", "S": 90.0, "dims": {}}
            for i in range(2)
        ], {"id": "run-1", "created_at": "2026-01-01T00:00:00Z"})

        self.assertEqual(2, len(transport.requests))
        self.assertEqual("https://langfuse.example/custom/scores", transport.requests[0]["url"])
        self.assertEqual("Basic cGs6c2s=", transport.requests[0]["headers"]["Authorization"])
        self.assertEqual({"attempted": 6, "accepted": 6, "rejected": 0, "batches": 2, "errors": []}, result)

    def test_reports_207_partial_rejection(self):
        transport = FakeScoreTransport([
            {"accepted": 2, "rejected": 1, "errors": [{"message": "invalid trace"}]}
        ])
        writer = LangfuseScoreWriter("https://langfuse.example", "pk", "sk", transport=transport)
        result = writer.write_scores(
            [{"trace_id": "trace-1", "S": 90.0, "dims": {}}],
            {"id": "run-1", "created_at": "2026-01-01T00:00:00Z"},
        )

        self.assertEqual(1, result["rejected"])
        self.assertEqual(["invalid trace"], result["errors"])

    def test_accepts_streaming_rows_without_materializing_a_list(self):
        transport = FakeScoreTransport()
        writer = LangfuseScoreWriter(
            "https://langfuse.example", "pk", "sk",
            batch_size=3, transport=transport,
        )
        rows = ({"trace_id": f"trace-{index}", "S": 90.0, "dims": {}} for index in range(2))

        result = writer.write_scores(
            rows, {"id": "run-1", "created_at": "2026-01-01T00:00:00Z"}
        )

        self.assertEqual({"attempted": 6, "accepted": 6, "rejected": 0, "batches": 2, "errors": []}, result)

    def test_uses_endpoint_config(self):
        profile = {"baseUrl": "https://langfuse.example"}
        endpoints = {
            "endpoints": {"scores": {"create": {"path": "/custom/scores"}}},
            "limits": {"scoresCreateBatchSize": 17},
        }
        writer = LangfuseScoreWriter.from_config(profile, endpoints, {"publicKey": "pk", "secretKey": "sk"})

        self.assertEqual("https://langfuse.example", writer.base_url)
        self.assertEqual("/custom/scores", writer.scores_path)
        self.assertEqual(17, writer.batch_size)


if __name__ == "__main__":
    unittest.main()
