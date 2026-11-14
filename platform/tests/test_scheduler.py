import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platform.app import store
from platform.app.config import load_scheduler_config
from platform.app.scheduler import LifecycleScheduler, scheduler_status


class SchedulerTest(unittest.TestCase):
    def test_scan_runs_watchdog_evaluates_and_records_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                store.upsert_lifecycle_schedule(
                    connection, ontology_id, True, "jsonl", "R1", 24, 24, 1, None, 1, 1, False
                )
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "jsonl", "R1", "R1",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1, "test", None,
                )
                old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
                connection.execute(
                    "UPDATE cohort_runs SET created_at = ? WHERE id = ?", (old_time, run_id)
                )
                connection.commit()
            finally:
                connection.close()

            evaluations = []

            def evaluator(current_connection, current_ontology_id):
                evaluations.append(current_ontology_id)
                return {
                    "ontologyId": current_ontology_id,
                    "decision": "created_r1",
                    "reason": "interval_due",
                    "createdRunId": "run-created",
                    "run": {"id": "run-created"},
                }

            scheduler = LifecycleScheduler(
                db_path=db_path,
                config={
                    "intervalSeconds": 1,
                    "leaseSeconds": 60,
                    "watchdog": {"queuedTimeoutSeconds": 60, "runningTimeoutSeconds": 60},
                },
                evaluator=evaluator,
            )
            result = scheduler.execute_scan()
            status = scheduler_status(db_path)

            connection = store.connect(db_path, initialize=False)
            try:
                run = store.get_run(connection, run_id)
                watchdog = connection.execute(
                    "SELECT * FROM run_steps WHERE run_id = ? AND name = 'watchdog'", (run_id,)
                ).fetchone()
                lock = store.get_scheduler_lock(connection)
            finally:
                connection.close()

            self.assertEqual("succeeded", result["status"])
            self.assertEqual([ontology_id], evaluations)
            self.assertEqual([run_id], result["watchdogFailedRuns"])
            self.assertEqual("failed", run["status"])
            self.assertIn("watchdog", run["error"])
            self.assertIsNotNone(watchdog)
            self.assertIsNone(lock)
            self.assertEqual(1, status["enabledSchedules"])
            self.assertEqual("succeeded", status["latestScan"]["status"])
            self.assertEqual(1, status["latestScan"]["evaluationCount"])
            self.assertEqual(1, status["latestScan"]["createdRunCount"])
            self.assertEqual(1, status["latestScan"]["watchdogFailedRuns"])

    def test_second_scheduler_is_skipped_while_lock_is_held(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                lock = store.acquire_scheduler_lock(connection, "other-owner", 60)
                self.assertEqual("other-owner", lock["owner_id"])
            finally:
                connection.close()

            scheduler = LifecycleScheduler(db_path=db_path, evaluator=lambda *_: {})
            result = scheduler.execute_scan()

            self.assertEqual("skipped", result["status"])
            self.assertEqual("lock_held", result["reason"])
            self.assertEqual("other-owner", result["lock"]["owner_id"])

    def test_scheduler_config_is_validated(self):
        config = load_scheduler_config()
        self.assertGreater(config["intervalSeconds"], 0)
        self.assertGreater(config["leaseSeconds"], 0)
        self.assertGreater(config["watchdog"]["queuedTimeoutSeconds"], 0)
        self.assertGreater(config["watchdog"]["runningTimeoutSeconds"], 0)


if __name__ == "__main__":
    unittest.main()
