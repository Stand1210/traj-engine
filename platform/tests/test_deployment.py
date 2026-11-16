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

    def test_service_lifespan_initializes_database_and_records_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "lifespan.db"
            with patch.dict(
                "os.environ",
                {"TRAJ_DB_PATH": str(db_path), "TRAJ_PROFILE": "cloud-v4"},
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
