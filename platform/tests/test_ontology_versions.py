import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from platform.app import store
from platform.app.service import (
    OntologyVersionInput,
    activate_ontology_version,
    list_ontology_versions,
    publish_ontology_version,
)


class OntologyVersionTest(unittest.TestCase):
    def test_publishes_activates_and_preserves_historical_run_version(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "ontology-versions.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(
                    connection, "Owner", "version-org", "version-project", "pk", "sk"
                )
                ontology_id = store.create_ontology(
                    connection, tenant_id, "Versioned Agent", "tier0"
                )
                old_run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "version-run",
                    "R1", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
                    1.0, "test", None,
                )
                old_version_id = connection.execute(
                    "SELECT ontology_version_id FROM cohort_runs WHERE id = ?",
                    (old_run_id,),
                ).fetchone()["ontology_version_id"]

                yaml_text = (
                    f"id: {ontology_id}\n"
                    "version: 2\n"
                    "unit_price:\n"
                    "  prompt: 0.0\n"
                    "  completion: 0.0\n"
                )
                published = publish_ontology_version(
                    ontology_id, OntologyVersionInput(yaml=yaml_text, activate=True), connection
                )

                new_run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "version-run-2",
                    "R1", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z",
                    1.0, "test", None,
                )
                new_version_id = connection.execute(
                    "SELECT ontology_version_id FROM cohort_runs WHERE id = ?",
                    (new_run_id,),
                ).fetchone()["ontology_version_id"]

                self.assertEqual(2, published["version"])
                self.assertTrue(published["activated"])
                self.assertNotEqual(old_version_id, new_version_id)
                self.assertEqual(old_version_id, connection.execute(
                    "SELECT ontology_version_id FROM cohort_runs WHERE id = ?",
                    (old_run_id,),
                ).fetchone()["ontology_version_id"])

                page = list_ontology_versions(ontology_id, 50, None, connection)
                self.assertEqual([2, 1], [item["version"] for item in page["data"]])
            finally:
                connection.close()

    def test_rejects_invalid_duplicate_and_missing_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "ontology-version-errors.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(
                    connection, "Owner", "error-org", "error-project", "pk", "sk"
                )
                ontology_id = store.create_ontology(
                    connection, tenant_id, "Version Error Agent", "tier0"
                )

                invalid_cases = [
                    f"id: other-ontology\nversion: 2\nunit_price:\n  prompt: 0\n  completion: 0\n",
                    f"id: {ontology_id}\nversion: 2\n",
                    f"id: {ontology_id}\nversion: 2\nunit_price:\n  prompt: -1\n  completion: 0\n",
                ]
                for yaml_text in invalid_cases:
                    with self.assertRaises(HTTPException) as context:
                        publish_ontology_version(
                            ontology_id, OntologyVersionInput(yaml=yaml_text), connection
                        )
                    self.assertEqual(400, context.exception.status_code)

                valid_yaml = (
                    f"id: {ontology_id}\n"
                    "version: 2\n"
                    "unit_price:\n"
                    "  prompt: 0.0\n"
                    "  completion: 0.0\n"
                )
                publish_ontology_version(
                    ontology_id, OntologyVersionInput(yaml=valid_yaml), connection
                )
                with self.assertRaises(HTTPException) as context:
                    publish_ontology_version(
                        ontology_id, OntologyVersionInput(yaml=valid_yaml), connection
                    )
                self.assertEqual(400, context.exception.status_code)

                with self.assertRaises(HTTPException) as context:
                    activate_ontology_version(ontology_id, 99, connection)
                self.assertEqual(404, context.exception.status_code)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
