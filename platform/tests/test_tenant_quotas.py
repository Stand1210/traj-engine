import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from platform.app import store
from platform.app.config import load_performance_config
from platform.app.service import (
    RunInput,
    TenantQuotaInput,
    create_run,
    update_tenant_quotas,
)


class TenantQuotaTest(unittest.TestCase):
    def test_tenant_quotas_limit_runs_and_can_be_updated(self):
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
                    max_runs_per_day=2,
                    max_concurrent_runs=1,
                )
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")

                with self.assertRaises(store.TenantQuotaExceeded):
                    store.ensure_tenant_run_quota(connection, tenant_id, 11)
                self.assertEqual(10, store.ensure_tenant_run_quota(connection, tenant_id, None))

                first_run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "quota",
                    "R1", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
                    1.0, "test", None,
                )
                with self.assertRaises(store.TenantQuotaExceeded):
                    store.ensure_tenant_run_quota(connection, tenant_id, 1)

                connection.execute(
                    "UPDATE cohort_runs SET status = 'succeeded' WHERE id = ?",
                    (first_run_id,),
                )
                connection.commit()
                store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "quota-2",
                    "R1", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z",
                    1.0, "test", None,
                )
                with self.assertRaises(store.TenantQuotaExceeded):
                    store.ensure_tenant_run_quota(connection, tenant_id, 1)

                store.update_tenant_quotas(
                    connection, tenant_id,
                    max_traces_per_run=20,
                    max_runs_per_day=10,
                    max_concurrent_runs=2,
                )
                row = connection.execute(
                    """SELECT max_traces_per_run, max_runs_per_day, max_concurrent_runs
                       FROM tenants WHERE id = ?""",
                    (tenant_id,),
                ).fetchone()
                self.assertEqual((20, 10, 2), tuple(row))

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

                updated = update_tenant_quotas(
                    tenant_id,
                    TenantQuotaInput(
                        maxTracesPerRun=30,
                        maxRunsPerDay=20,
                        maxConcurrentRuns=2,
                    ),
                    connection,
                )
                self.assertEqual(
                    (30, 20, 2),
                    (
                        updated["maxTracesPerRun"],
                        updated["maxRunsPerDay"],
                        updated["maxConcurrentRuns"],
                    ),
                )
            finally:
                connection.close()

    def test_performance_config_exposes_positive_tenant_defaults(self):
        config = load_performance_config()

        self.assertEqual(
            {
                "maxTracesPerRun": 100000,
                "maxRunsPerDay": 24,
                "maxConcurrentRuns": 1,
            },
            config["tenantDefaults"],
        )


if __name__ == "__main__":
    unittest.main()
