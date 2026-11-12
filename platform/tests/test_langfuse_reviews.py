import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platform.app import store
from platform.app.langfuse_reviews import LangfuseAnnotationQueueClient
from platform.app.service import ReviewQueueInput, create_review_queue, sync_review_queue


ROOT = Path(__file__).resolve().parents[2]


class FakeReviewTransport:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, params, body, headers):
        self.calls.append({"method": method, "url": url, "params": params, "body": body})
        path = url.split("https://langfuse.example", 1)[1]
        if path == "/api/public/score-configs":
            return {"data": [
                {"id": "config-verdict", "name": "traj-engine-human-verdict", "dataType": "CATEGORICAL"},
                {"id": "config-label", "name": "traj-engine-human-label", "dataType": "TEXT"},
                {"id": "config-comment", "name": "traj-engine-human-comment", "dataType": "TEXT"},
            ], "meta": {"totalPages": 1}}
        if path == "/api/public/annotation-queues":
            return {"data": [{
                "id": "queue-1", "name": "traj-engine-review",
                "description": None, "scoreConfigIds": ["config-verdict"],
            }], "meta": {"totalPages": 1}}
        if path == "/api/public/annotation-queues/queue-1/items" and method == "POST":
            return {"id": "item-1", "queueId": "queue-1", "objectId": body["objectId"],
                    "objectType": "TRACE", "status": "PENDING"}
        if path == "/api/public/annotation-queues/queue-1/items":
            return {"data": [{
                "id": "item-1", "queueId": "queue-1", "objectId": "trace-1",
                "objectType": "TRACE", "status": "COMPLETED", "completedAt": "2026-01-02T00:00:00Z",
            }], "meta": {"totalPages": 1}}
        if path == "/api/public/v3/scores":
            return {"data": [
                {"id": "score-verdict", "name": "traj-engine-human-verdict", "value": "agree",
                 "subject": {"kind": "trace", "id": "trace-1"}, "authorUserId": "reviewer-1",
                 "queueId": "queue-1", "updatedAt": "2026-01-02T00:01:00Z"},
                {"id": "score-label", "name": "traj-engine-human-label", "value": "latency",
                 "subject": {"kind": "trace", "id": "trace-1"}, "queueId": "queue-1"},
                {"id": "score-comment", "name": "traj-engine-human-comment", "value": "confirmed",
                 "subject": {"kind": "trace", "id": "trace-1"}, "queueId": "queue-1"},
            ], "meta": {}}
        raise AssertionError(f"unexpected Langfuse call: {method} {path}")


class LangfuseReviewTest(unittest.TestCase):
    def test_client_builds_review_assets_and_items(self):
        transport = FakeReviewTransport()
        endpoints = {
            "annotationQueues": {
                "list": {"path": "/api/public/annotation-queues"},
                "create": {"path": "/api/public/annotation-queues"},
                "items": {
                    "list": {"path": "/api/public/annotation-queues/{queueId}/items"},
                    "create": {"path": "/api/public/annotation-queues/{queueId}/items"},
                },
            },
            "scoreConfigs": {
                "list": {"path": "/api/public/score-configs"},
                "create": {"path": "/api/public/score-configs"},
            },
            "scores": {"list": {"path": "/api/public/v3/scores", "query": {"fields": "details,subject,annotation"}}},
        }
        client = LangfuseAnnotationQueueClient(
            "https://langfuse.example", "pk", "sk", endpoints, transport=transport,
        )

        assets = client.ensure_review_assets()
        items = client.push_items("queue-1", ["trace-1"])
        remote_items = client.list_items("queue-1")
        scores = client.list_annotation_scores(["trace-1"], "queue-1")

        self.assertEqual("queue-1", assets["queue"]["id"])
        self.assertEqual(3, len(assets["scoreConfigs"]))
        self.assertEqual("item-1", items[0]["id"])
        self.assertEqual("COMPLETED", remote_items[0]["status"])
        self.assertEqual("agree", scores[0]["value"])
        self.assertEqual("trace-1", scores[0]["traceId"])
        self.assertEqual("trace-1", transport.calls[-1]["params"]["traceId"])
        self.assertEqual("queue-1", transport.calls[-1]["params"]["queueId"])

    def test_review_queue_push_and_sync_roundtrip(self):
        class FakeClient:
            def ensure_review_assets(self, queue_name):
                return {"queue": {"id": "queue-1", "name": queue_name}, "scoreConfigs": []}

            def push_items(self, queue_id, trace_ids):
                return [{"id": f"item-{trace_id}", "status": "PENDING"} for trace_id in trace_ids]

            def list_items(self, queue_id):
                return [{
                    "id": "item-trace-1", "queueId": queue_id, "objectId": "trace-1",
                    "objectType": "TRACE", "status": "COMPLETED",
                    "completedAt": "2026-01-02T00:00:00Z",
                }]

            def list_annotation_scores(self, trace_ids, queue_id):
                return [
                    {"name": "traj-engine-human-verdict", "value": 1,
                     "traceId": "trace-1", "authorUserId": "reviewer-1", "updatedAt": "2026-01-02T00:01:00Z"},
                    {"name": "traj-engine-human-label", "value": "latency", "traceId": "trace-1"},
                    {"name": "traj-engine-human-comment", "value": "confirmed", "traceId": "trace-1"},
                ]

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                ontology_version_id = connection.execute(
                    "SELECT id FROM ontology_versions WHERE ontology_id = ?", (ontology_id,)
                ).fetchone()["id"]
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "smoke", "R1",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0, "test", None,
                )
                connection.execute(
                    """INSERT INTO trace_scores
                       (id, run_id, tenant_id, trace_id, total_score, result_score,
                        process_score, latency_score, cost_score, robustness_score,
                        deduction_total, evidence_sum, is_alert, is_abstain,
                        ontology_version_id, structure_version_id, code_hash, created_at)
                       VALUES ('score-1', ?, ?, 'trace-1', 50, 1, 1, 0.5, 1, 1,
                               50, 50, 1, 0, ?, NULL,
                               'hash', '2026-01-01T00:00:00Z')""",
                    (run_id, tenant_id, ontology_version_id),
                )
                connection.commit()
                with patch("platform.app.service._annotation_client", return_value=FakeClient()):
                    pushed = create_review_queue(
                        run_id, ReviewQueueInput(scope="alerts", limit=10), connection,
                    )
                    synced = sync_review_queue(run_id, connection)
                    synced_again = sync_review_queue(run_id, connection)

                queue_item = connection.execute(
                    "SELECT * FROM review_queue_items WHERE run_id = ?", (run_id,)
                ).fetchone()
                review = connection.execute(
                    "SELECT * FROM human_reviews WHERE trace_score_id = 'score-1'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(1, pushed["pushed"])
            self.assertEqual(1, synced["imported"])
            self.assertEqual(0, synced_again["imported"])
            self.assertEqual("COMPLETED", queue_item["status"])
            self.assertIsNotNone(queue_item["human_review_id"])
            self.assertEqual("agree", review["verdict"])
            self.assertEqual("latency", review["label"])
            self.assertEqual("confirmed", review["comment"])


if __name__ == "__main__":
    unittest.main()
