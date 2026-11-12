import json
import tempfile
import unittest
from pathlib import Path

from platform.app.alerts import compute_alert_decisions, persist_alert_decisions
from platform.app import store


ROOT = Path(__file__).resolve().parents[2]


def score_row(score_id: str, trace_id: str, total: float, cell_id: str) -> dict:
    return {
        "id": score_id,
        "run_id": "run-test",
        "tenant_id": "tenant-test",
        "trace_id": trace_id,
        "cell_id": cell_id,
        "total_score": total,
        "result_score": 0.4,
        "process_score": 1.0,
        "latency_score": 0.5,
        "cost_score": 0.9,
        "robustness_score": 1.0,
        "deduction_total": -20.0,
        "evidence_sum": -20.0,
        "is_alert": 1,
        "is_abstain": 0,
        "ontology_version_id": "ontology-version-test",
        "structure_version_id": "structure-test",
        "code_hash": "hash",
        "created_at": "2026-01-01T00:00:00Z",
    }


def evidence_row(score_id: str, rule: str) -> dict:
    return {
        "id": f"evidence-{score_id}",
        "trace_score_id": score_id,
        "dimension": "result",
        "span_id": None,
        "contribution": -20.0,
        "explanation": "test",
        "payload_json": json.dumps({"kernel_evidence": [{"kind": "rule", "rule": rule}]}),
        "created_at": "2026-01-01T00:00:00Z",
    }


class AlertBudgetTest(unittest.TestCase):
    def test_prioritizes_deduplicates_and_applies_budget(self):
        rows = [
            score_row("score-low", "trace-low", 15.0, "cell-a"),
            score_row("score-duplicate", "trace-duplicate", 30.0, "cell-a"),
            score_row("score-other", "trace-other", 25.0, "cell-b"),
        ]
        evidence = [
            evidence_row("score-low", "result_broken"),
            evidence_row("score-duplicate", "result_broken"),
            evidence_row("score-other", "unrecovered_error"),
        ]

        decisions = compute_alert_decisions(rows, evidence, {"cell-a": 80, "cell-b": 20}, budget=1)

        self.assertEqual(3, len(decisions))
        self.assertEqual("alerted", decisions[0]["status"])
        self.assertEqual("score-low", decisions[0]["trace_score_id"])
        self.assertEqual("suppressed_duplicate", decisions[1]["status"])
        self.assertEqual("candidate", decisions[2]["status"])
        self.assertEqual(decisions[0]["group_key"], decisions[1]["group_key"])
        self.assertNotEqual(decisions[0]["group_key"], decisions[2]["group_key"])
        self.assertGreater(decisions[0]["priority"], decisions[1]["priority"])
        self.assertTrue(decisions[0]["reasons"])

    def test_persists_alert_decisions(self):
        rows = [
            score_row("score-low", "trace-low", 15.0, "cell-a"),
            score_row("score-duplicate", "trace-duplicate", 30.0, "cell-a"),
        ]
        evidence = [
            evidence_row("score-low", "result_broken"),
            evidence_row("score-duplicate", "result_broken"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                connection.execute(
                    """INSERT INTO tenants
                       (id, display_name, org_id, project_id, public_key, secret_key,
                        created_at, updated_at)
                       VALUES ('tenant-test', 'Owner', 'org-test', 'project-test', 'pk', 'sk',
                        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
                )
                connection.execute(
                    """INSERT INTO ontologies
                       (id, tenant_id, display_name, tier, current_version, created_at, updated_at)
                       VALUES ('ontology-test', 'tenant-test', 'Agent', 'tier0', 1,
                        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
                )
                connection.execute(
                    """INSERT INTO ontology_versions
                       (id, ontology_id, version, yaml, code_hash, created_at)
                       VALUES ('ontology-version-test', 'ontology-test', 1, 'id: test', 'hash',
                        '2026-01-01T00:00:00Z')"""
                )
                connection.execute(
                    """INSERT INTO structure_versions
                       (id, ontology_id, version, code_hash, state_json, created_at, active)
                       VALUES ('structure-test', 'ontology-test', 1, 'hash', '{}',
                        '2026-01-01T00:00:00Z', 1)"""
                )
                connection.execute(
                    """INSERT INTO cohort_runs
                       (id, tenant_id, ontology_id, ontology_version_id, run_type, source,
                        source_ref, window_start, window_end, sampling_rate, status,
                        trigger_reason, error, idempotency_key, code_hash, created_at)
                       VALUES ('run-test', 'tenant-test', 'ontology-test', 'ontology-version-test',
                        'R1', 'langfuse', 'test', '2026-01-01T00:00:00Z',
                        '2026-01-02T00:00:00Z', 1.0, 'succeeded', 'test', NULL, NULL, 'hash',
                        '2026-01-01T00:00:00Z')"""
                )
                connection.execute(
                    """INSERT INTO cells
                       (id, run_id, structure_version_id, cell_key, label, parent_id,
                        dominant_action, size, metrics_json, created_at)
                       VALUES ('cell-a', 'run-test', 'structure-test', 'cell-a', 'cell-a',
                        NULL, NULL, 2, '{}', '2026-01-01T00:00:00Z')"""
                )
                for row in rows:
                    connection.execute(
                    """INSERT INTO trace_scores
                       (id, run_id, tenant_id, trace_id, cell_id, total_score, result_score,
                        process_score, latency_score, cost_score, robustness_score,
                        deduction_total, evidence_sum, is_alert, is_abstain,
                        ontology_version_id, structure_version_id, code_hash, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    tuple(row[key] for key in (
                        "id", "run_id", "tenant_id", "trace_id", "cell_id", "total_score",
                        "result_score", "process_score", "latency_score", "cost_score",
                        "robustness_score", "deduction_total", "evidence_sum", "is_alert",
                        "is_abstain", "ontology_version_id", "structure_version_id", "code_hash",
                        "created_at"
                    )),
                )
                    connection.execute(
                        """INSERT INTO score_evidence
                           (id, trace_score_id, dimension, span_id, contribution,
                            explanation, payload_json, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (f"evidence-{row['id']}", row["id"], "result", None, -20.0,
                         "test", json.dumps({"kernel_evidence": [
                             {"kind": "rule", "rule": "result_broken"}
                         ]}), "2026-01-01T00:00:00Z"),
                    )
                connection.commit()

                summary = persist_alert_decisions(connection, "run-test", budget=1)
                persisted = connection.execute(
                    "SELECT * FROM alert_decisions WHERE run_id = ? ORDER BY priority_rank",
                    ("run-test",),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(
                {"budget": 1, "totalAlerts": 2, "groups": 1, "emitted": 1,
                 "candidates": 1, "statusCounts": {
                     "alerted": 1, "candidate": 0, "suppressed_duplicate": 1
                 }},
                summary,
            )
            self.assertEqual(2, len(persisted))
            self.assertEqual("alerted", persisted[0]["status"])
            self.assertEqual("suppressed_duplicate", persisted[1]["status"])


if __name__ == "__main__":
    unittest.main()
