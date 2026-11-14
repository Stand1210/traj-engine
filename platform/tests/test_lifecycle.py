import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platform.app import store
from platform.app.lifecycle import evaluate_lifecycle_state, get_lifecycle_schedule
from platform.app.service import LifecycleEvaluateInput, LifecycleInput, configure_lifecycle
from platform.app.service import evaluate_lifecycle, serialize_run


class LifecycleTest(unittest.TestCase):
    def test_lifecycle_decisions_and_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                configure_lifecycle(
                    ontology_id,
                    LifecycleInput(
                        enabled=True,
                        source="langfuse",
                        sourceRef="lifecycle",
                        intervalHours=24,
                        windowHours=24,
                        r2NoveltyThreshold=0.15,
                        r2MinNoveltyTraces=0,
                        r2AlertRateThreshold=0.20,
                    ),
                    connection,
                )

                cold_start = evaluate_lifecycle_state(connection, ontology_id)
                self.assertEqual("created_r2", cold_start["decision"])
                self.assertEqual("cold_start", cold_start["reason"])

                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "lifecycle", "R1",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0, "test", None,
                )
                ontology_version = connection.execute(
                    "SELECT id FROM ontology_versions WHERE ontology_id = ? LIMIT 1",
                    (ontology_id,),
                ).fetchone()["id"]
                structure_id = store.new_id("structure")
                connection.execute(
                    """INSERT INTO structure_versions
                       (id, ontology_id, version, code_hash, state_json, created_at, active)
                       VALUES (?, ?, 1, 'hash', '{}', '2026-01-01T00:00:00Z', 1)""",
                    (structure_id, ontology_id),
                )
                connection.execute(
                    """INSERT INTO trace_scores
                       (id, run_id, tenant_id, trace_id, total_score, result_score,
                        process_score, latency_score, cost_score, robustness_score,
                        deduction_total, evidence_sum, is_alert, is_abstain,
                        ontology_version_id, structure_version_id, code_hash, created_at)
                       VALUES
                       ('score-1', ?, ?, 'trace-1', 80, 80, 80, 80, 80, 80,
                        20, 20, 1, 0, ?, ?, 'hash', '2026-01-01T00:00:00Z'),
                       ('score-2', ?, ?, 'trace-2', 80, 80, 80, 80, 80, 80,
                        20, 20, 0, 1, ?, ?, 'hash', '2026-01-01T00:00:00Z')""",
                    (run_id, tenant_id, ontology_version, structure_id,
                     run_id, tenant_id, ontology_version, structure_id),
                )
                store.set_run_status(connection, run_id, "succeeded", ended=True)
                connection.commit()

                novelty = evaluate_lifecycle_state(connection, ontology_id)
                self.assertEqual("created_r2", novelty["decision"])
                self.assertEqual("novelty_threshold", novelty["reason"])
                self.assertEqual(0.5, novelty["metrics"]["noveltyRate"])

                schedule = get_lifecycle_schedule(connection, ontology_id)
                store.upsert_lifecycle_schedule(
                    connection, ontology_id, False, schedule["source"],
                    schedule["source_ref"], schedule["interval_hours"],
                    schedule["window_hours"], schedule["sampling_rate"],
                    schedule["max_traces"], 1.0, 1.0, False,
                )
                disabled = evaluate_lifecycle_state(connection, ontology_id)
                self.assertEqual("skipped", disabled["decision"])
                self.assertEqual("schedule_disabled", disabled["reason"])
            finally:
                connection.close()

    def test_invalid_lifecycle_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                with self.assertRaises(Exception):
                    configure_lifecycle(
                        ontology_id,
                        LifecycleInput(intervalHours=24, r2MinNoveltyTraces=-1),
                        connection,
                    )
            finally:
                connection.close()

    def test_lifecycle_evaluation_is_recorded_without_run_when_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                configure_lifecycle(
                    ontology_id,
                    LifecycleInput(enabled=False, source="jsonl", sourceRef="R1"),
                    connection,
                )

                result = evaluate_lifecycle(
                    ontology_id, LifecycleEvaluateInput(forceR2=False), connection
                )

                self.assertEqual("skipped", result["decision"])
                self.assertEqual("schedule_disabled", result["reason"])
                self.assertIsNone(result["run"])
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM lifecycle_evaluations WHERE ontology_id = ?",
                    (ontology_id,),
                ).fetchone()
                self.assertEqual(1, row["n"])
            finally:
                connection.close()

    def test_repeated_evaluation_reuses_run_in_same_bucket(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                configure_lifecycle(
                    ontology_id,
                    LifecycleInput(
                        enabled=True, source="jsonl", sourceRef="R1", intervalHours=24
                    ),
                    connection,
                )

                calls = []

                def create_test_run(input_data, current_connection):
                    calls.append(input_data)
                    run_id = store.create_run(
                        current_connection,
                        input_data.tenantId,
                        input_data.ontologyId,
                        input_data.source,
                        input_data.sourceRef,
                        input_data.runType,
                        input_data.windowStart,
                        input_data.windowEnd,
                        input_data.samplingRate,
                        input_data.triggerReason,
                        input_data.idempotencyKey,
                    )
                    row = current_connection.execute(
                        "SELECT * FROM cohort_runs WHERE id = ?", (run_id,)
                    ).fetchone()
                    return serialize_run(row)

                with patch("platform.app.service.create_run", side_effect=create_test_run):
                    first = evaluate_lifecycle(
                        ontology_id, LifecycleEvaluateInput(forceR2=False), connection
                    )
                    store.set_run_status(connection, first["run"]["id"], "succeeded", ended=True)
                    second = evaluate_lifecycle(
                        ontology_id, LifecycleEvaluateInput(forceR2=False), connection
                    )

                self.assertEqual("created_r2", first["decision"])
                self.assertEqual(first["run"]["id"], second["run"]["id"])
                self.assertEqual(1, len(calls))
            finally:
                connection.close()

    def test_r2_waits_for_accumulated_novelty_traces(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                configure_lifecycle(
                    ontology_id,
                    LifecycleInput(
                        enabled=True,
                        source="jsonl",
                        sourceRef="lifecycle",
                        intervalHours=24,
                        r2NoveltyThreshold=0.15,
                        r2MinNoveltyTraces=2,
                    ),
                    connection,
                )
                ontology_version = connection.execute(
                    "SELECT id FROM ontology_versions WHERE ontology_id = ? LIMIT 1",
                    (ontology_id,),
                ).fetchone()["id"]

                anchor_run_id = store.create_run(
                    connection, tenant_id, ontology_id, "jsonl", "lifecycle", "R2",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0,
                    "cold_start", None,
                )
                structure_id = store.new_id("structure")
                connection.execute(
                    """INSERT INTO structure_versions
                       (id, ontology_id, version, code_hash, state_json, created_at, active)
                       VALUES (?, ?, 1, 'hash', '{}', '2026-01-01T00:00:00Z', 1)""",
                    (structure_id, ontology_id),
                )
                connection.execute(
                    "UPDATE cohort_runs SET structure_version_id = ? WHERE id = ?",
                    (structure_id, anchor_run_id),
                )
                store.set_run_status(connection, anchor_run_id, "succeeded", ended=True)

                first_run_id = store.create_run(
                    connection, tenant_id, ontology_id, "jsonl", "lifecycle", "R1",
                    "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z", 1.0,
                    "interval_due", None,
                )
                self._insert_score(
                    connection, first_run_id, tenant_id, "novel-trace-1",
                    ontology_version, structure_id, True,
                )
                store.set_run_status(connection, first_run_id, "succeeded", ended=True)

                below_minimum = evaluate_lifecycle_state(connection, ontology_id)
                self.assertEqual("skipped", below_minimum["decision"])
                self.assertEqual("novelty_below_minimum", below_minimum["reason"])
                self.assertEqual(1, below_minimum["metrics"]["accumulatedNoveltyTraces"])

                repeated_run_id = store.create_run(
                    connection, tenant_id, ontology_id, "jsonl", "lifecycle", "R1",
                    "2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z", 1.0,
                    "interval_due", None,
                )
                self._insert_score(
                    connection, repeated_run_id, tenant_id, "novel-trace-1",
                    ontology_version, structure_id, True,
                )
                store.set_run_status(connection, repeated_run_id, "succeeded", ended=True)

                still_below = evaluate_lifecycle_state(connection, ontology_id)
                self.assertEqual("skipped", still_below["decision"])
                self.assertEqual(1, still_below["metrics"]["accumulatedNoveltyTraces"])

                qualified_run_id = store.create_run(
                    connection, tenant_id, ontology_id, "jsonl", "lifecycle", "R1",
                    "2026-01-04T00:00:00Z", "2026-01-05T00:00:00Z", 1.0,
                    "interval_due", None,
                )
                self._insert_score(
                    connection, qualified_run_id, tenant_id, "novel-trace-2",
                    ontology_version, structure_id, True,
                )
                store.set_run_status(connection, qualified_run_id, "succeeded", ended=True)

                triggered = evaluate_lifecycle_state(connection, ontology_id)
                self.assertEqual("created_r2", triggered["decision"])
                self.assertEqual("novelty_threshold", triggered["reason"])
                self.assertEqual(2, triggered["metrics"]["accumulatedNoveltyTraces"])
            finally:
                connection.close()

    def _insert_score(
        self,
        connection,
        run_id: str,
        tenant_id: str,
        trace_id: str,
        ontology_version_id: str,
        structure_id: str,
        is_abstain: bool,
    ) -> None:
        connection.execute(
            """INSERT INTO trace_scores
               (id, run_id, tenant_id, trace_id, total_score, result_score,
                process_score, latency_score, cost_score, robustness_score,
                deduction_total, evidence_sum, is_alert, is_abstain,
                ontology_version_id, structure_version_id, code_hash, created_at)
               VALUES (?, ?, ?, ?, 80, 80, 80, 80, 80, 80, 20, 20, 0, ?,
                       ?, ?, 'hash', '2026-01-01T00:00:00Z')""",
            (store.new_id("score"), run_id, tenant_id, trace_id,
             int(is_abstain), ontology_version_id, structure_id),
        )
        connection.commit()
