import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from platform.app import service, store
from platform.app.langfuse_admin import LangfuseAdminClient


class FakeAdminTransport:
    def __call__(self, url: str, params: dict, headers: dict) -> dict:
        if url.endswith("/api/public/health"):
            return {"status": "OK", "version": "4.81.0"}
        if url.endswith("/api/public/projects"):
            return {"data": [{"id": "project-1", "name": "Production Agent"}]}
        raise AssertionError(f"unexpected URL: {url}")


class OnboardingTest(unittest.TestCase):
    def test_admin_client_checks_health_and_project(self):
        client = LangfuseAdminClient(
            base_url="https://langfuse.example",
            public_key="pk",
            secret_key="sk",
            transport=FakeAdminTransport(),
        )

        result = client.check_project("project-1")

        self.assertEqual("OK", result["status"])
        self.assertEqual("4.81.0", result["langfuseVersion"])
        self.assertEqual("Production Agent", result["project"]["name"])

    def test_register_project_creates_tenant_and_tier0_ontology(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "onboarding.db"
            with closing(store.connect(db_path, initialize=True)) as connection:
                input_data = service.OnboardingInput(
                    displayName="Production Agent",
                    orgId="org-1",
                    projectId="project-1",
                    publicKey="pk",
                    secretKey="sk",
                    ontologyDisplayName="告警研判 Agent",
                )

                class FakeAdminClient:
                    @classmethod
                    def from_config(cls, *_args, **_kwargs):
                        return cls()

                    def check_project(self, project_id: str) -> dict:
                        return {
                            "status": "OK",
                            "langfuseVersion": "4.81.0",
                            "project": {"id": project_id, "name": "Production Agent"},
                        }

                with patch.object(service, "LangfuseAdminClient", FakeAdminClient):
                    result = service.register_langfuse_project(input_data, connection)

                tenant = connection.execute(
                    "SELECT * FROM tenants WHERE id = ?", (result["tenant"]["id"],)
                ).fetchone()
                ontology = connection.execute(
                    "SELECT * FROM ontologies WHERE id = ?", (result["ontology"]["id"],)
                ).fetchone()

            self.assertEqual("pk", tenant["public_key"])
            self.assertEqual("sk", tenant["secret_key"])
            self.assertEqual("tier0", ontology["tier"])
            self.assertEqual(1, ontology["current_version"])
            self.assertEqual("4.81.0", result["langfuse"]["version"])

    def test_startup_record_keeps_langfuse_version_and_note(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "startup.db"
            with closing(store.connect(db_path, initialize=True)) as connection:
                store.record_startup(
                    connection,
                    {"profile": "cloud-v4", "baseUrl": "https://langfuse.example"},
                    "4.81.0",
                    "Langfuse health check succeeded",
                )
                row = connection.execute(
                    "SELECT * FROM startup_records ORDER BY checked_at DESC LIMIT 1"
                ).fetchone()

            self.assertEqual("4.81.0", row["langfuse_version"])
            self.assertEqual(0, row["skipped"])
            self.assertEqual("Langfuse health check succeeded", row["note"])


if __name__ == "__main__":
    unittest.main()
