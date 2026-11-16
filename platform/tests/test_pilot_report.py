import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from platform.app import store
from platform.scripts import pilot_report


class PilotReportTest(unittest.TestCase):
    def test_builds_report_and_renders_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "pilot.db"
            self._seed_database(db_path)

            report = pilot_report.build_pilot_report(db_path)

            self.assertEqual("pending", report["status"])
            self.assertEqual("run-pilot", report["run"]["id"])
            self.assertEqual("Langfuse Pilot", report["tenant"]["displayName"])
            self.assertEqual(25, report["scores"]["traceCount"])
            self.assertEqual(5, report["scores"]["abstainCount"])
            self.assertEqual(1, report["scores"]["alertCount"])
            self.assertLess(report["scores"]["maxEvidenceResidual"], 1e-7)
            self.assertEqual(1, len(report["clusters"]))
            self.assertEqual({"alerted": 1}, report["alerts"]["statusCounts"])
            self.assertEqual({"agree": 1}, report["reviews"]["verdictCounts"])
            self.assertIn("minimumReviews", report["pendingGates"])
            self.assertIn("activeCalibration", report["pendingGates"])

            markdown = pilot_report.render_pilot_markdown(report)
            self.assertIn("# M7.0 试点验收报告", markdown)
            self.assertIn("run-pilot", markdown)
            self.assertIn("工程门禁", markdown)
            self.assertIn("人工检查", markdown)

    def test_missing_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "pilot.db"
            store.connect(db_path, initialize=True).close()

            with self.assertRaisesRegex(
                pilot_report.PilotReportError,
                "latest succeeded run",
            ):
                pilot_report.build_pilot_report(db_path)

    def _seed_database(self, db_path: Path) -> None:
        created_at = store.utcnow()
        with closing(store.connect(db_path, initialize=True)) as connection:
            connection.execute(
                """INSERT INTO tenants
                   (id, display_name, org_id, project_id, public_key, secret_key,
                    created_at, updated_at)
                   VALUES ('tenant-pilot', 'Langfuse Pilot', 'org-pilot',
                           'project-pilot', 'pk', 'sk', ?, ?)""",
                (created_at, created_at),
            )
            connection.execute(
                """INSERT INTO ontologies
                   (id, tenant_id, display_name, tier, created_at, updated_at)
                   VALUES ('ontology-pilot', 'tenant-pilot', 'Pilot Agent',
                           'tier0', ?, ?)""",
                (created_at, created_at),
            )
            connection.execute(
                """INSERT INTO ontology_versions
                   (id, ontology_id, version, yaml, code_hash, created_at)
                   VALUES ('ontology-version-pilot', 'ontology-pilot', 1, 'tier: tier0',
                           'kernel-hash', ?)""",
                (created_at,),
            )
            connection.execute(
                """INSERT INTO structure_versions
                   (id, ontology_id, version, code_hash, state_json, created_at, active)
                   VALUES ('structure-pilot', 'ontology-pilot', 1, 'kernel-hash',
                           '{}', ?, 1)""",
                (created_at,),
            )
            connection.execute(
                """INSERT INTO cohort_runs
                   (id, tenant_id, ontology_id, ontology_version_id,
                    structure_version_id, run_type, source, source_ref,
                    window_start, window_end, status, code_hash, created_at,
                    started_at, ended_at)
                   VALUES ('run-pilot', 'tenant-pilot', 'ontology-pilot',
                           'ontology-version-pilot', 'structure-pilot', 'R2',
                           'langfuse', 'pilot-drill', '2026-11-01T00:00:00Z',
                           '2026-11-02T00:00:00Z', 'succeeded', 'kernel-hash',
                           ?, ?, ?)""",
                (created_at, created_at, created_at),
            )
            connection.execute(
                """INSERT INTO cells
                   (id, run_id, structure_version_id, cell_key, label, dominant_action,
                    size, metrics_json, created_at)
                   VALUES ('cell-pilot', 'run-pilot', 'structure-pilot', 'cell-1',
                           'normal-workflow', 'search', 25, '{}', ?)""",
                (created_at,),
            )
            for index in range(25):
                score_id = f"score-{index:02d}"
                is_abstain = int(index < 5)
                is_alert = int(index == 5)
                deduction = 0.2 if is_alert else 0.0
                connection.execute(
                    """INSERT INTO trace_scores
                       (id, run_id, tenant_id, trace_id, cell_id, total_score,
                        result_score, process_score, latency_score, cost_score,
                        robustness_score, deduction_total, evidence_sum, is_alert,
                        is_abstain, ontology_version_id, structure_version_id,
                        code_hash, created_at)
                       VALUES (?, 'run-pilot', 'tenant-pilot', ?, 'cell-pilot',
                               ?, 1.0, 1.0, 1.0, 1.0, 1.0, ?, ?, ?, ?,
                               'ontology-version-pilot', 'structure-pilot',
                               'kernel-hash', ?)""",
                    (
                        score_id,
                        f"trace-{index:02d}",
                        1.0 - deduction,
                        deduction,
                        deduction,
                        is_alert,
                        is_abstain,
                        created_at,
                    ),
                )
                if is_alert:
                    connection.execute(
                        """INSERT INTO alert_decisions
                           (id, run_id, trace_score_id, group_key, cause, cause_kind,
                            priority, priority_rank, group_rank, group_size, status,
                            reasons_json, created_at)
                           VALUES ('alert-pilot', 'run-pilot', ?, 'trace-05', 'latency',
                                   'statistical', 0.9, 1, 1, 1, 'alerted', '[]', ?)""",
                        (score_id, created_at),
                    )
                    connection.execute(
                        """INSERT INTO human_reviews
                           (id, trace_score_id, reviewer, verdict, label, comment,
                            created_at)
                           VALUES ('review-pilot', ?, 'reviewer', 'agree', 'real', 'ok', ?)""",
                        (score_id, created_at),
                    )
            connection.commit()


if __name__ == "__main__":
    unittest.main()
