import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from platform.app import store
from platform.app.algorithm import (
    ONTOLOGY_GOVERNANCE_KEYS,
    build_dynamic_ontology,
    ontology_from_yaml,
    run_production,
)
from platform.app.service import RunInput, build_precheck_report, create_run
from platform.app.trace_source import SPAN_KEYS, TRACE_KEYS


def make_span(span_id="s1", parent_id=None, **overrides):
    span = {key: None for key in SPAN_KEYS}
    span.update(
        {
            "span_id": span_id,
            "parent_id": parent_id,
            "kind": "agent",
            "action": "plan",
            "status": "ok",
            "ts_start": 1.0,
            "ts_end": 2.0,
        }
    )
    span.update(overrides)
    return span


def make_trace(trace_id="t1", spans=None, **overrides):
    trace = {key: None for key in TRACE_KEYS}
    trace.update(
        {
            "trace_id": trace_id,
            "ts_start": 1.0,
            "spans": spans
            if spans is not None
            else [
                make_span("s1"),
                make_span(
                    "s2",
                    parent_id="s1",
                    kind="tool",
                    action="search",
                    tool_name="search",
                ),
            ],
        }
    )
    trace.update(overrides)
    return trace


def bench_traces(limit=40):
    path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "bench_v1"
        / "R1"
        / "traces.jsonl"
    )
    traces = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            traces.append(json.loads(line))
            if len(traces) == limit:
                break
    return traces


class OntologyFromYamlTest(unittest.TestCase):
    def test_overlay_and_missing(self):
        traces = [make_trace("t1"), make_trace("t2")]
        yaml_text = (
            "id: ontology-x\n"
            "unit_price: {prompt: 0.001, completion: 0.002}\n"
            "forbidden_actions: [delete]\n"
        )
        ontology, missing = ontology_from_yaml(yaml_text, "ontology-x", traces)
        self.assertEqual("ontology-x", ontology["id"])
        self.assertEqual(0.001, ontology["unit_price"]["prompt"])
        self.assertEqual(0.002, ontology["unit_price"]["completion"])
        self.assertEqual(0.0, ontology["unit_price"]["tool_call"])
        self.assertEqual(["delete"], ontology["forbidden_actions"])
        dynamic = build_dynamic_ontology(traces, "ontology-x")
        self.assertEqual(dynamic["actions"], ontology["actions"])
        self.assertEqual(
            sorted(set(ONTOLOGY_GOVERNANCE_KEYS) - {"unit_price", "forbidden_actions"}),
            sorted(missing),
        )

    def test_invalid_yaml_and_id_mismatch(self):
        traces = [make_trace("t1")]
        with self.assertRaises(ValueError):
            ontology_from_yaml("id: [unclosed", "ontology-x", traces)
        with self.assertRaises(ValueError):
            ontology_from_yaml(
                "id: other\nunit_price: {prompt: 1, completion: 1}\n",
                "ontology-x",
                traces,
            )

    def test_run_production_uses_override(self):
        traces = bench_traces()
        override, missing = ontology_from_yaml(
            "id: ontology-override\nunit_price: {prompt: 0.5, completion: 0.25}\n",
            "ontology-override",
            traces,
        )
        result, _ = run_production(
            traces, "ontology-override", ontology_override=override
        )
        unit_price = result["frozen_state"]["ontology"]["unit_price"]
        self.assertEqual(0.5, unit_price["prompt"])
        self.assertEqual(0.25, unit_price["completion"])
        self.assertIn("tool_call", unit_price)
        with self.assertRaises(ValueError):
            run_production(
                traces, "other-ontology", ontology_override=override
            )


class SchemaV12Test(unittest.TestCase):
    def test_columns_and_backfill(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                structure_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(structure_versions)"
                    ).fetchall()
                }
                self.assertIn("embedding_dim", structure_columns)
                self.assertIn("structural_fingerprint", structure_columns)
                run_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(cohort_runs)"
                    ).fetchall()
                }
                self.assertIn("degraded_json", run_columns)

                tenant_id = store.create_tenant(
                    connection, "Owner", "org", "project", "pk", "sk"
                )
                ontology_id = store.create_ontology(
                    connection, tenant_id, "Agent", "tier0"
                )
                state_json = json.dumps(
                    {
                        "format": "x",
                        "state": {
                            "embedding_dim": 1024,
                            "_tfidf_ctx": {"fingerprint": "fp-abc"},
                        },
                    }
                )
                connection.execute(
                    """INSERT INTO structure_versions
                       (id, ontology_id, version, code_hash, state_json, created_at, active)
                       VALUES ('sv1', ?, 1, 'hash', ?, '2026-01-01T00:00:00Z', 1)""",
                    (ontology_id, state_json),
                )
                store._backfill_structure_fingerprints(connection)
                row = connection.execute(
                    "SELECT embedding_dim, structural_fingerprint FROM structure_versions WHERE id = 'sv1'"
                ).fetchone()
                self.assertEqual(1024, row["embedding_dim"])
                self.assertEqual("fp-abc", row["structural_fingerprint"])
            finally:
                connection.close()

    def test_get_active_ontology_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                ids = store.create_tenant_with_tier0_ontology(
                    connection, "Owner", "org", "project", "pk", "sk", "Agent"
                )
                yaml_text = store.get_active_ontology_yaml(
                    connection, ids["ontology_id"]
                )
                self.assertIsNotNone(yaml_text)
                self.assertIn("unit_price:", yaml_text)
                self.assertIsNone(store.get_active_ontology_yaml(connection, "missing"))
            finally:
                connection.close()


class PrecheckE4Test(unittest.TestCase):
    def test_new_checks_present_on_sparse_traces(self):
        report = build_precheck_report([make_trace()], 100)
        self.assertEqual(15, len(report["checks"]))
        checks = {item["name"]: item for item in report["checks"]}
        self.assertEqual("warning", checks["cost_coverage"]["status"])
        self.assertEqual("failed", checks["intent_text_coverage"]["status"])
        self.assertEqual("failed", checks["embedding_model_availability"]["status"])
        self.assertEqual("warning", checks["embedding_dimension_consistency"]["status"])
        self.assertEqual("warning", checks["span_key_quality"]["status"])
        self.assertEqual("passed", checks["action_naming_stability"]["status"])
        self.assertEqual("warning", checks["ontology_price_validity"]["status"])
        self.assertEqual(
            "not_evaluated",
            checks["ontology_price_validity"]["metrics"]["reason"],
        )

    def test_rich_traces_pass_new_checks(self):
        spans = [
            make_span(
                f"s{i}",
                parent_id="s0" if i else None,
                kind="llm",
                action="plan" if i % 2 else "search",
                agent="planner",
                operation="reason",
                model="gpt-x",
                cost=0.01,
                tokens_prompt=10,
            )
            for i in range(4)
        ]
        trace = make_trace(
            "t1",
            spans=spans,
            intent_text="user intent",
            embedding=[0.1, 0.2, 0.3, 0.4],
        )
        report = build_precheck_report([trace], 100, encoder_available=True)
        checks = {item["name"]: item for item in report["checks"]}
        self.assertEqual("passed", checks["intent_text_coverage"]["status"])
        self.assertEqual("passed", checks["embedding_model_availability"]["status"])
        self.assertEqual("passed", checks["embedding_dimension_consistency"]["status"])
        self.assertEqual("passed", checks["span_key_quality"]["status"])
        self.assertEqual("passed", checks["cost_coverage"]["status"])

    def test_action_naming_instability_fails(self):
        spans = [
            make_span(f"s{i}", parent_id="s0" if i else None, action=f"action-{i}")
            for i in range(25)
        ]
        report = build_precheck_report([make_trace("t1", spans=spans)], 100)
        checks = {item["name"]: item for item in report["checks"]}
        self.assertEqual("failed", checks["action_naming_stability"]["status"])

    def test_ontology_price_validity(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                ids = store.create_tenant_with_tier0_ontology(
                    connection, "Owner", "org", "project", "pk", "sk", "Agent"
                )
                trace = make_trace(intent_text="intent", embedding=[0.1])
                report = build_precheck_report(
                    [trace],
                    100,
                    ontology_id=ids["ontology_id"],
                    connection=connection,
                    encoder_available=True,
                )
                checks = {item["name"]: item for item in report["checks"]}
                # Seed tier0 yaml has unit_price prompt/completion = 0.0
                self.assertEqual("warning", checks["ontology_price_validity"]["status"])
                store.publish_ontology_version(
                    connection,
                    ids["ontology_id"],
                    "id: %s\nunit_price: {prompt: 1.5, completion: 2.0}\n"
                    % ids["ontology_id"],
                    activate=True,
                )
                report = build_precheck_report(
                    [trace],
                    100,
                    ontology_id=ids["ontology_id"],
                    connection=connection,
                    encoder_available=True,
                )
                checks = {item["name"]: item for item in report["checks"]}
                self.assertEqual("passed", checks["ontology_price_validity"]["status"])
            finally:
                connection.close()


class R1FrozenStructureRejectionTest(unittest.TestCase):
    def test_unparseable_active_structure_rejects_r1(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = store.connect(Path(directory) / "test.db", initialize=True)
            try:
                ids = store.create_tenant_with_tier0_ontology(
                    connection, "Owner", "org", "project", "pk", "sk", "Agent"
                )
                connection.execute(
                    """INSERT INTO structure_versions
                       (id, ontology_id, version, code_hash, state_json, created_at, active)
                       VALUES ('sv-bad', ?, 1, 'hash', '{}', '2026-01-01T00:00:00Z', 1)""",
                    (ids["ontology_id"],),
                )
                connection.commit()
                with patch("platform.app.service.ENGINE.submit") as submit:
                    with self.assertRaises(HTTPException) as ctx:
                        create_run(
                            RunInput(
                                tenantId=ids["tenant_id"],
                                ontologyId=ids["ontology_id"],
                                source="langfuse",
                                sourceRef="lifecycle",
                                runType="R1",
                                windowStart="2026-01-01T00:00:00Z",
                                windowEnd="2026-01-02T00:00:00Z",
                            ),
                            connection,
                        )
                self.assertEqual(409, ctx.exception.status_code)
                self.assertEqual(
                    "frozen_structure_unusable", ctx.exception.detail["code"]
                )
                submit.assert_not_called()
                row = connection.execute(
                    "SELECT status, error FROM cohort_runs ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                self.assertEqual("failed", row["status"])
                self.assertIn("R2", row["error"])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
