import tempfile
import unittest
from pathlib import Path

from platform.app import store
from platform.app.service import build_precheck_report
from platform.app.trace_source import SPAN_KEYS, TRACE_KEYS


def trace(trace_id="t1", span_id="s1", parent_id=None):
    value = {key: None for key in TRACE_KEYS}
    value.update(
        {
            "trace_id": trace_id,
            "ontology_id": "ontA",
            "answer_facts": [trace_id],
            "answer_numbers": [],
            "answer_citations": [],
            "contradicted_facts": [],
            "spans": [span(span_id, parent_id)],
        }
    )
    return value


def span(span_id="s1", parent_id=None):
    value = {key: None for key in SPAN_KEYS}
    value.update(
        {
            "span_id": span_id,
            "parent_id": parent_id,
            "kind": "agent",
            "level": "DEFAULT",
            "status": "ok",
            "tokens_prompt": 1,
            "tokens_completion": 1,
            "cost_details": {
                "prompt": 0,
                "completion": 0,
                "cache_read": 0,
                "cache_write": 0,
                "tool_call": 0,
            },
        }
    )
    return value


class StoreTest(unittest.TestCase):
    def test_tenant_ontology_and_precheck_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(
                    connection, "Owner", "org", "project", "pk", "sk"
                )
                ontology_id = store.create_ontology(
                    connection, tenant_id, "Agent", "tier0"
                )
                ontology = connection.execute(
                    "SELECT * FROM ontologies WHERE id = ?", (ontology_id,)
                ).fetchone()
                version = connection.execute(
                    "SELECT * FROM ontology_versions WHERE ontology_id = ? AND version = 1",
                    (ontology_id,),
                ).fetchone()

                self.assertEqual(1, ontology["current_version"])
                self.assertIn("unit_price:", version["yaml"])
                self.assertIn("prompt: 0.0", version["yaml"])
                precheck_id = store.create_precheck(connection, ontology_id, 100)
                report = build_precheck_report([trace()], 100)
                store.finish_precheck(connection, precheck_id, "passed", report)

                row = connection.execute(
                    "SELECT * FROM prechecks WHERE id = ?", (precheck_id,)
                ).fetchone()

                self.assertEqual("passed", row["status"])
                self.assertEqual(8, len(report["checks"]))
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
