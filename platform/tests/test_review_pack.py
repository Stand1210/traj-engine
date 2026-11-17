import csv
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from platform.app import store
from platform.app import service
from platform.scripts import review_pack


class ReviewPackTest(unittest.TestCase):
    def test_exports_imports_and_activates_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "review.db"
            output_path = Path(directory) / "review-pack.csv"
            self._seed_database(db_path)

            export_result = review_pack.export_review_pack(
                db_path,
                "run-review",
                output_path,
            )
            self.assertEqual(20, export_result["reviewCount"])
            self.assertTrue(output_path.is_file())
            self.assertTrue(output_path.with_suffix(".md").is_file())

            filled_path = Path(directory) / "filled-review-pack.csv"
            self._fill_review_pack(output_path, filled_path)

            import_result = review_pack.import_review_pack(
                db_path,
                "run-review",
                filled_path,
                reviewer="business-expert",
                trigger_calibration=True,
                activate=True,
            )

            self.assertEqual(20, import_result["imported"])
            self.assertEqual({"agree": 15, "disagree": 5, "uncertain": 0}, import_result["verdictCounts"])
            self.assertEqual(20, import_result["calibration"]["labelCount"])
            self.assertIsNotNone(import_result["calibration"]["activatedAt"])

            with closing(store.connect(db_path, initialize=False)) as connection:
                review_count = connection.execute(
                    "SELECT COUNT(*) AS n FROM human_reviews"
                ).fetchone()["n"]
                active_calibration = connection.execute(
                    "SELECT source_run_id FROM review_calibrations WHERE activated_at IS NOT NULL"
                ).fetchone()
            self.assertEqual(20, review_count)
            self.assertEqual("run-review", active_calibration["source_run_id"])

    def test_import_rejects_invalid_verdict_without_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "review.db"
            csv_path = Path(directory) / "invalid.csv"
            self._seed_database(db_path)
            review_pack.export_review_pack(db_path, "run-review", csv_path)
            self._fill_review_pack(csv_path, csv_path, verdict="invalid")

            with self.assertRaisesRegex(
                review_pack.ReviewPackError,
                "invalid verdict",
            ):
                review_pack.import_review_pack(
                    db_path,
                    "run-review",
                    csv_path,
                    reviewer="business-expert",
                )

            with closing(store.connect(db_path, initialize=False)) as connection:
                review_count = connection.execute(
                    "SELECT COUNT(*) AS n FROM human_reviews"
                ).fetchone()["n"]
            self.assertEqual(0, review_count)

    def test_service_imports_review_pack_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "review.db"
            csv_path = Path(directory) / "review-pack.csv"
            self._seed_database(db_path)
            review_pack.export_review_pack(db_path, "run-review", csv_path)
            self._fill_review_pack(csv_path, csv_path)

            with patch.dict("os.environ", {"TRAJ_DB_PATH": str(db_path)}):
                result = service.import_review_pack_csv(
                    "run-review",
                    service.ReviewPackImportInput(
                        csv=csv_path.read_text(encoding="utf-8-sig"),
                        reviewer="frontend-reviewer",
                    ),
                )

            self.assertEqual(20, result["imported"])
            self.assertEqual("frontend-reviewer", result["reviewer"])
            self.assertEqual({"agree": 15, "disagree": 5, "uncertain": 0}, result["verdictCounts"])

    def _seed_database(self, db_path: Path) -> None:
        created_at = store.utcnow()
        with closing(store.connect(db_path, initialize=True)) as connection:
            connection.execute(
                """INSERT INTO tenants
                   (id, display_name, org_id, project_id, public_key, secret_key,
                    created_at, updated_at)
                   VALUES ('tenant-review', 'Review Tenant', 'org-review',
                           'project-review', 'pk', 'sk', ?, ?)""",
                (created_at, created_at),
            )
            connection.execute(
                """INSERT INTO ontologies
                   (id, tenant_id, display_name, tier, created_at, updated_at)
                   VALUES ('ontology-review', 'tenant-review', 'Review Agent',
                           'tier0', ?, ?)""",
                (created_at, created_at),
            )
            connection.execute(
                """INSERT INTO ontology_versions
                   (id, ontology_id, version, yaml, code_hash, created_at)
                   VALUES ('ontology-version-review', 'ontology-review', 1,
                           'tier: tier0', 'kernel-hash', ?)""",
                (created_at,),
            )
            connection.execute(
                """INSERT INTO cohort_runs
                   (id, tenant_id, ontology_id, ontology_version_id, run_type,
                    source, source_ref, window_start, window_end, status,
                    code_hash, created_at, started_at, ended_at)
                   VALUES ('run-review', 'tenant-review', 'ontology-review',
                           'ontology-version-review', 'R1', 'langfuse',
                           'review-pack', '2026-11-12T08:00:00Z',
                           '2026-11-12T09:30:00Z', 'succeeded', 'kernel-hash',
                           ?, ?, ?)""",
                (created_at, created_at, created_at),
            )
            for index in range(20):
                score_id = f"score-{index:02d}"
                deduction = 0.5 if index < 5 else 0.1
                connection.execute(
                    """INSERT INTO trace_scores
                       (id, run_id, tenant_id, trace_id, total_score,
                        result_score, process_score, latency_score, cost_score,
                        robustness_score, deduction_total, evidence_sum,
                        is_alert, is_abstain, ontology_version_id, code_hash,
                        created_at)
                       VALUES (?, 'run-review', 'tenant-review', ?, ?, 0.8, 0.9,
                               0.7, 0.9, 0.8, ?, ?, 1, 0,
                               'ontology-version-review', 'kernel-hash', ?)""",
                    (score_id, f"trace-{index:02d}", 1.0 - deduction,
                     deduction, deduction, created_at),
                )
                connection.execute(
                    """INSERT INTO alert_decisions
                       (id, run_id, trace_score_id, group_key, cause, cause_kind,
                        priority, priority_rank, group_rank, group_size, status,
                        reasons_json, created_at)
                       VALUES (?, 'run-review', ?, ?, 'rule:test', 'rule', ?,
                               ?, ?, 1, 'alerted', '[]', ?)""",
                    (f"alert-{index:02d}", score_id, f"group-{index:02d}",
                     1.0 - deduction, index + 1, index + 1, created_at),
                )
                connection.execute(
                    """INSERT INTO score_evidence
                       (id, trace_score_id, dimension, span_id, contribution,
                        explanation, created_at)
                       VALUES (?, ?, 'result', NULL, ?, 'result contribution', ?)""",
                    (f"evidence-{index:02d}", score_id, -deduction, created_at),
                )
            connection.commit()

    def _fill_review_pack(self, source: Path, destination: Path, verdict: str = "mixed") -> None:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for index, row in enumerate(rows):
            if verdict == "mixed":
                row["verdict"] = "agree" if index < 15 else "disagree"
            else:
                row["verdict"] = verdict
            row["reviewer"] = "business-expert"
            row["label"] = "real_failure" if row["verdict"] == "agree" else "false_alarm"
            row["comment"] = "normal" if row["verdict"] == "agree" else "business context mismatch"
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=review_pack.CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
