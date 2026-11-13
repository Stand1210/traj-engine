import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from platform.app.alerts import compute_alert_decisions
from platform.app.calibration import compute_review_calibration
from platform.app import store
from platform.app.service import (
    CalibrationTriggerInput,
    activate_calibration,
    trigger_review_calibration,
)


ROOT = Path(__file__).resolve().parents[2]


class ReviewCalibrationTest(unittest.TestCase):
    def test_triggers_creates_version_and_activates_it(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "smoke", "R1",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0, "test", None,
                )
                ontology_version = connection.execute(
                    """SELECT id FROM ontology_versions WHERE ontology_id = ?
                       ORDER BY version LIMIT 1""",
                    (ontology_id,),
                ).fetchone()["id"]
                score_ids = self._insert_scores(
                    connection, run_id, tenant_id, ontology_version
                )
                self._insert_alerts(connection, run_id, score_ids)
                self._insert_reviews(connection, score_ids)

                config = {"minimumLabels": 6, "minimumReviewedAlerts": 3}
                with patch(
                    "platform.app.service.load_calibration_config", return_value=config
                ):
                    calibration = trigger_review_calibration(
                        run_id, CalibrationTriggerInput(createdBy="reviewer-a"), connection,
                    )
                activated = activate_calibration(calibration["id"], connection)

                self.assertEqual(run_id, calibration["sourceRunId"])
                self.assertEqual(6, calibration["labelCount"])
                self.assertEqual(3, calibration["traceCount"])
                self.assertEqual(2, calibration["verdictCounts"]["agree"])
                self.assertEqual(1, calibration["verdictCounts"]["disagree"])
                self.assertAlmostEqual(2 / 3, calibration["alertPrecision"], delta=1e-6)
                self.assertIsNotNone(calibration["ece"])
                self.assertIsNotNone(activated["activatedAt"])
            finally:
                connection.close()

    def test_rejects_calibration_below_sample_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "smoke", "R1",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0, "test", None,
                )
                ontology_version = connection.execute(
                    """SELECT id FROM ontology_versions WHERE ontology_id = ?
                       ORDER BY version LIMIT 1""",
                    (ontology_id,),
                ).fetchone()["id"]
                score_ids = self._insert_scores(
                    connection, run_id, tenant_id, ontology_version
                )
                self._insert_alerts(connection, run_id, score_ids)
                self._insert_reviews(connection, score_ids, count=1)

                with self.assertRaises(HTTPException) as context:
                    with patch(
                        "platform.app.service.load_calibration_config",
                        return_value={"minimumLabels": 6, "minimumReviewedAlerts": 3},
                    ):
                        trigger_review_calibration(
                            run_id,
                            CalibrationTriggerInput(createdBy="reviewer-a"),
                            connection,
                        )
                self.assertEqual(400, context.exception.status_code)
                self.assertEqual(
                    "calibration_insufficient_labels", context.exception.detail["code"]
                )
            finally:
                connection.close()

    def test_active_cause_adjustment_changes_alert_priority(self):
        score_rows = [
            self._score_row("score-1", 40.0),
            self._score_row("score-2", 40.0),
        ]
        evidence_rows = [self._evidence_row(score_id) for score_id in ("score-1", "score-2")]
        cell_sizes = {"cell-1": 2}
        baseline = compute_alert_decisions(score_rows, evidence_rows, cell_sizes, budget=5)
        adjusted = compute_alert_decisions(
            score_rows, evidence_rows, cell_sizes, budget=5,
            cause_adjustments={"rule:result_broken": 0.5},
        )

        self.assertEqual(2, len(baseline))
        self.assertEqual(2, len(adjusted))
        self.assertLess(adjusted[0]["priority"], baseline[0]["priority"])
        self.assertEqual(baseline[0]["cause"], "rule:result_broken")

    def test_cause_calibration_uses_reviewed_candidates_too(self):
        score_rows = [self._score_row(f"score-{index}", 40.0) for index in range(1, 6)]
        alert_rows = [
            {
                "trace_score_id": row["id"],
                "status": "alerted" if index == 1 else "candidate",
                "cause": "rule:result_broken",
            }
            for index, row in enumerate(score_rows, start=1)
        ]
        review_rows = [
            {
                "trace_score_id": row["id"],
                "verdict": "agree" if index == 1 else "disagree",
            }
            for index, row in enumerate(score_rows, start=1)
        ]

        result = compute_review_calibration(
            score_rows,
            review_rows,
            alert_rows,
            {"minimumLabels": 5, "minimumReviewedAlerts": 1, "minimumCauseSamples": 5},
        )

        self.assertEqual(1, result["alert_reviewed"])
        self.assertEqual(5, result["metrics"]["alertSignalReviewed"])
        self.assertEqual(5, result["metrics"]["causeStats"][0]["sampleCount"])
        self.assertEqual(0.5, result["parameters"]["causeSeverityAdjustments"]["rule:result_broken"])

    def _insert_scores(self, connection, run_id, tenant_id, ontology_id):
        score_ids = []
        for index, score in enumerate((90.0, 80.0, 30.0), start=1):
            score_id = f"score-{index}"
            deduction = 100 - score
            connection.execute(
                """INSERT INTO trace_scores
                   (id, run_id, tenant_id, trace_id, total_score, result_score,
                    process_score, latency_score, cost_score, robustness_score,
                    deduction_total, evidence_sum, is_alert, is_abstain,
                    ontology_version_id, structure_version_id, code_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, NULL, 'hash', ?)""",
                (score_id, run_id, tenant_id, f"trace-{index}", score, score, score,
                 score, score, score, deduction, deduction, ontology_id, "2026-01-01T00:00:00Z"),
            )
            score_ids.append(score_id)
        connection.commit()
        return score_ids

    def _insert_alerts(self, connection, run_id, score_ids):
        for rank, score_id in enumerate(score_ids, start=1):
            connection.execute(
                """INSERT INTO alert_decisions
                   (id, run_id, trace_score_id, group_key, cause, cause_kind,
                    priority, priority_rank, group_rank, group_size, status,
                    reasons_json, created_at)
                   VALUES (?, ?, ?, ?, 'rule:result_broken', 'rule', 80.0 - ?,
                           ?, 1, 1, 'alerted', '[]', '2026-01-01T00:00:00Z')""",
                (f"alert-{rank}", run_id, score_id,
                 f"cell-{rank}:rule:result_broken", rank, rank),
            )
        connection.commit()

    def _insert_reviews(self, connection, score_ids, count=6):
        verdicts = ("agree", "agree", "disagree")
        for index in range(count):
            score_index = index % len(score_ids)
            connection.execute(
                """INSERT INTO human_reviews
                   (id, trace_score_id, reviewer, verdict, label, comment, created_at)
                   VALUES (?, ?, ?, ?, NULL, NULL, ?)""",
                (f"review-{index + 1}", score_ids[score_index], "reviewer-a",
                 verdicts[score_index], "2026-01-01T00:00:00Z"),
            )
        connection.commit()

    def _score_row(self, score_id, score):
        return {
            "id": score_id,
            "trace_id": f"trace-{score_id}",
            "cell_id": "cell-1",
            "total_score": score,
            "result_score": score,
            "process_score": score,
            "latency_score": score,
            "cost_score": score,
            "robustness_score": score,
            "evidence_sum": 100 - score,
            "deduction_total": 100 - score,
            "is_alert": 1,
        }

    def _evidence_row(self, score_id):
        return {
            "trace_score_id": score_id,
            "payload_json": json.dumps({
                "kernel_evidence": [{"kind": "rule", "rule": "result_broken"}]
            }),
        }


if __name__ == "__main__":
    unittest.main()
