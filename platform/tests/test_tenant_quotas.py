import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from platform.app import store
from platform.app.config import load_performance_config
from platform.app.service import (
    ProjectQuotaInput,
    RunInput,
    create_run,
    update_project_quota,
)


class TenantQuotaTest(unittest.TestCase):
    def test_project_quota_limits_runs_and_can_be_updated(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "tenant-quota.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(
                    connection,
                    "Quota Owner",
                    "quota-org",
                    "quota-project",
                    "pk",
                    "sk",
                    max_traces_per_run=10,
                )
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")

                with self.assertRaises(store.ProjectQuotaExceeded):
                    store.ensure_project_run_quota(connection, tenant_id, 11)
                self.assertEqual(10, store.ensure_project_run_quota(connection, tenant_id, None))

                store.update_project_quota(connection, tenant_id, max_traces_per_run=20)
                row = connection.execute(
                    """SELECT max_traces_per_run
                       FROM tenants WHERE id = ?""",
                    (tenant_id,),
                ).fetchone()
                self.assertEqual((20,), tuple(row))

                with self.assertRaises(HTTPException) as context:
                    create_run(
                        RunInput(
                            tenantId=tenant_id,
                            ontologyId=ontology_id,
                            source="jsonl",
                            sourceRef="R1",
                            runType="R1",
                            windowStart="2026-01-01T00:00:00Z",
                            windowEnd="2026-01-02T00:00:00Z",
                            limit=21,
                        ),
                        connection,
                    )
                self.assertEqual(429, context.exception.status_code)

                updated = update_project_quota(
                    tenant_id,
                    ProjectQuotaInput(maxTracesPerRun=30),
                    connection,
                )
                self.assertEqual(30, updated["maxTracesPerRun"])
            finally:
                connection.close()

    def test_performance_config_exposes_positive_project_default(self):
        config = load_performance_config()

        self.assertEqual(100000, config["projectDefaultMaxTracesPerRun"])


if __name__ == "__main__":
    unittest.main()
