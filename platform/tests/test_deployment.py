import json
import asyncio
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from platform.app import store
from platform.app import service
from platform.app.deployment_smoke import initialize_database, run_deployment_smoke


class FakeResponse:
    def __init__(self, body: dict):
        self.body = body

    def read(self) -> bytes:
        return json.dumps(self.body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DeploymentTest(unittest.TestCase):
    def test_initialize_database_and_record_schema_version(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "deployment.db"
            result = initialize_database(db_path)

            self.assertEqual("initialized", result["status"])
            self.assertEqual(store.SCHEMA_VERSION, result["schema_version"])
            with closing(store.connect(db_path)) as connection:
                rows = connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            self.assertEqual([store.SCHEMA_VERSION], [row["version"] for row in rows])

    def test_upgrade_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "deployment.db"
            initialize_database(db_path)
            with closing(store.connect(db_path)) as connection:
                connection.execute("DELETE FROM schema_migrations")
                connection.commit()

            initialize_database(db_path)
            with closing(store.connect(db_path)) as connection:
                versions = connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            self.assertEqual([store.SCHEMA_VERSION], [row["version"] for row in versions])

    def test_deployment_smoke_checks_core_rest_contract(self):
        responses = {
            "http://127.0.0.1:8000/api/v1/health": {
                "status": "ok", "version": "0.1.0"
            },
            "http://127.0.0.1:8000/api/v1/config/profile": {
                "profile": "cloud-v4", "baseUrl": "https://example.com"
            },
            "http://127.0.0.1:8000/api/v1/startup-records/current": {
                "profile": "cloud-v4"
            },
            "http://127.0.0.1:8000/api/v1/tenants?limit=1": {"data": [{"id": "t1"}]},
            "http://127.0.0.1:8000/api/v1/ontologies?limit=1": {"data": [{"id": "o1"}]},
        }

        def opener(request, timeout):
            self.assertEqual(5.0, timeout)
            return FakeResponse(responses[request.full_url])

        result = run_deployment_smoke(
            "http://127.0.0.1:8000",
            expected_profile="cloud-v4",
            opener=opener,
        )

        self.assertEqual("passed", result["status"])
        self.assertEqual("cloud-v4", result["profile"])
        self.assertEqual(1, result["tenantCountChecked"])
        self.assertEqual(1, result["ontologyCountChecked"])

    def test_db_path_can_be_overridden_by_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            configured = Path(directory) / "override.db"
            with patch.dict("os.environ", {"TRAJ_DB_PATH": str(configured)}):
                self.assertEqual(configured, store.resolve_db_path())

    def test_trace_list_returns_final_alert_status(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "trace-status.db"
            with closing(store.connect(db_path, initialize=True)) as connection:
                connection.execute(
                    """INSERT INTO tenants
                       (id, display_name, org_id, project_id, public_key, secret_key, queue_id,
                        created_at, updated_at)
                       VALUES ('tenant-test', 'Test', 'org-test', 'project-test', 'pk', 'sk',
                        NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
                )
                connection.execute(
                    """INSERT INTO ontologies
                       (id, tenant_id, display_name, tier, current_version, created_at, updated_at)
                       VALUES ('ontology-test', 'tenant-test', 'Test Agent', 'tier0', 1,
                        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
                )
                connection.execute(
                    """INSERT INTO ontology_versions
                       (id, ontology_id, version, yaml, code_hash, created_at)
                       VALUES ('ontology-version-test', 'ontology-test', 1, 'id: test', 'hash',
                        '2026-01-01T00:00:00Z')"""
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
                connection.executemany(
                    """INSERT INTO trace_scores
                       (id, run_id, tenant_id, trace_id, total_score, result_score,
                        process_score, latency_score, cost_score, robustness_score,
                        deduction_total, evidence_sum, is_alert, is_abstain,
                        ontology_version_id, code_hash, created_at)
                       VALUES (?, 'run-test', 'tenant-test', ?, ?, 0.5, 1.0, 1.0, 1.0, 1.0,
                        0.0, 0.0, ?, 0, 'ontology-version-test', 'hash',
                        '2026-01-01T00:00:00Z')""",
                    [
                        ("score-alerted", "trace-alerted", 35.0, 1),
                        ("score-deduped", "trace-deduped", 18.0, 1),
                        ("score-normal", "trace-normal", 90.0, 0),
                    ],
                )
                connection.execute(
                    """UPDATE trace_scores SET gates_json = ?
                       WHERE id = 'score-alerted'""",
                    (json.dumps({"loop_runaway": 0.35}),),
                )
                connection.executemany(
                    """INSERT INTO alert_decisions
                       (id, run_id, trace_score_id, group_key, cause, cause_kind, priority,
                        priority_rank, group_rank, group_size, status, reasons_json, created_at)
                       VALUES (?, 'run-test', ?, 'group-test', 'test-cause', 'result', 1.0, 1, ?,
                        2, ?, '[]', '2026-01-01T00:00:00Z')""",
                    [
                        ("decision-alerted", "score-alerted", 1, "alerted"),
                        ("decision-deduped", "score-deduped", 2, "suppressed_duplicate"),
                    ],
                )
                connection.commit()

                result = service.list_trace_scores("run-test", limit=100, connection=connection)
                detail = service.get_trace_score("run-test", "trace-alerted", connection=connection)
                alert_only = service.list_trace_scores(
                    "run-test", alertOnly=True, limit=100, connection=connection
                )

            status_by_trace = {row["traceId"]: row["alertStatus"] for row in result["data"]}
            self.assertEqual(
                {
                    "trace-alerted": "alerted",
                    "trace-deduped": "suppressed_duplicate",
                    "trace-normal": None,
                },
                status_by_trace,
            )
            self.assertEqual(
                ["trace-deduped", "trace-alerted"],
                [row["traceId"] for row in alert_only["data"]],
            )
            self.assertEqual({"loop_runaway": 0.35}, detail["gates"])
            self.assertEqual(65.0, detail["gateDeduction"])

    def test_service_lifespan_initializes_database_and_records_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "lifespan.db"
            with patch.dict(
                "os.environ",
                {"TRAJ_DB_PATH": str(db_path), "TRAJ_PROFILE": "cloud-v4"},
            ):
                with patch.object(
                    service,
                    "_check_langfuse_version",
                    return_value=("4.81.0", "Langfuse health check succeeded"),
                ):
                    async def exercise_lifespan():
                        async with service.lifespan(service.app):
                            pass

                asyncio.run(exercise_lifespan())

            with closing(store.connect(db_path)) as connection:
                startup = connection.execute(
                    "SELECT profile_name FROM startup_records ORDER BY checked_at DESC LIMIT 1"
                ).fetchone()
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            self.assertIn("startup_records", {row["name"] for row in tables})
            self.assertEqual("cloud-v4", startup["profile_name"])


if __name__ == "__main__":
    unittest.main()
