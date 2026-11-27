import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platform.app import store
from platform.app.algorithm import run_production
from platform.app.encoder import (
    ENCODER_CONTRACT_VERSION,
    EncoderContractError,
    ModelAsset,
    build_model_assets,
    encode_intents,
    validate_embeddings,
    validate_trace_embeddings,
)
from platform.app.engine import RunEngine


ROOT = Path(__file__).resolve().parents[2]


def make_asset(dimension: int = 8, revision: str = "v1") -> ModelAsset:
    return ModelAsset(
        provider="test",
        model_name="fake-encoder",
        revision=revision,
        dimension=dimension,
        weights={"weights.bin": "0" * 64},
        max_tokens=512,
        truncation="right",
        normalization="l2",
        backend="fake",
    )


def hash_vector(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [(digest[index % len(digest)] / 255.0) - 0.5 for index in range(dimension)]


class FakeIntentEncoder:
    def __init__(self, dimension: int = 8, vectors=None):
        self._asset = make_asset(dimension=dimension)
        self._vectors = vectors

    @property
    def asset(self) -> ModelAsset:
        return self._asset

    def encode(self, texts):
        if self._vectors is not None:
            return self._vectors
        return [hash_vector(text, self._asset.dimension) for text in texts]


class FakeTraceSource:
    source_type = "fake"

    def __init__(self, traces):
        self.traces = traces

    def list_traces(self, window, sampling):
        yield from self.traces


def load_benchmark_traces(count: int) -> list[dict]:
    traces = []
    with (ROOT / "data" / "bench_v1" / "R1" / "traces.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            traces.append(json.loads(line))
            if len(traces) == count:
                break
    return traces


class EncoderContractTest(unittest.TestCase):
    def test_encode_intents_happy_path(self):
        encoder = FakeIntentEncoder(dimension=8)
        embeddings = encode_intents(encoder, ["alpha", "beta", "alpha"])
        self.assertEqual(3, len(embeddings))
        self.assertTrue(all(len(vector) == 8 for vector in embeddings))
        self.assertEqual(embeddings[0], embeddings[2])

    def test_encode_intents_rejects_empty_vector(self):
        encoder = FakeIntentEncoder(vectors=[[0.1] * 8, [], [0.2] * 8])
        with self.assertRaisesRegex(EncoderContractError, "empty embedding at index 1"):
            encode_intents(encoder, ["a", "b", "c"])

    def test_encode_intents_rejects_wrong_dimension(self):
        encoder = FakeIntentEncoder(vectors=[[0.1] * 4] * 3)
        with self.assertRaisesRegex(EncoderContractError, "dimension mismatch expected=8 actual=4"):
            encode_intents(encoder, ["a", "b", "c"])

    def test_encode_intents_rejects_inconsistent_dimensions(self):
        encoder = FakeIntentEncoder(vectors=[[0.1] * 8, [0.2] * 8, [0.3] * 4])
        with self.assertRaisesRegex(EncoderContractError, "inconsistent embedding dimension"):
            encode_intents(encoder, ["a", "b", "c"])

    def test_encode_intents_rejects_count_mismatch(self):
        encoder = FakeIntentEncoder(vectors=[[0.1] * 8] * 2)
        with self.assertRaisesRegex(EncoderContractError, "count mismatch expected=3 actual=2"):
            encode_intents(encoder, ["a", "b", "c"])

    def test_validate_embeddings_rejects_none(self):
        with self.assertRaisesRegex(EncoderContractError, "no embeddings"):
            validate_embeddings(None, expected_count=1)

    def test_model_asset_fingerprint_is_stable_and_sensitive(self):
        asset = make_asset()
        self.assertEqual(asset.fingerprint(), make_asset().fingerprint())
        self.assertNotEqual(asset.fingerprint(), make_asset(revision="v2").fingerprint())
        self.assertNotEqual(asset.fingerprint(), make_asset(dimension=16).fingerprint())

    def test_verify_weights_checks_existence_and_sha256(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"fake-weights"
            (root / "weights.bin").write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()

            asset = ModelAsset(
                provider="test", model_name="m", revision="r", dimension=8,
                weights={"weights.bin": digest}, max_tokens=512,
                truncation="right", normalization="l2", backend="fake",
            )
            asset.verify_weights(root)

            tampered = ModelAsset(
                provider="test", model_name="m", revision="r", dimension=8,
                weights={"weights.bin": "0" * 64}, max_tokens=512,
                truncation="right", normalization="l2", backend="fake",
            )
            with self.assertRaisesRegex(EncoderContractError, "hash mismatch"):
                tampered.verify_weights(root)

            missing = ModelAsset(
                provider="test", model_name="m", revision="r", dimension=8,
                weights={"absent.bin": digest}, max_tokens=512,
                truncation="right", normalization="l2", backend="fake",
            )
            with self.assertRaisesRegex(EncoderContractError, "missing"):
                missing.verify_weights(root)

    def test_validate_trace_embeddings_reports_missing_and_inconsistent(self):
        traces = [
            {"trace_id": "t1", "embedding": [0.1, 0.2]},
            {"trace_id": "t2", "embedding": None},
            {"trace_id": "t3", "embedding": []},
        ]
        with self.assertRaisesRegex(EncoderContractError, "2/3 traces have empty"):
            validate_trace_embeddings(traces)

        mixed = [
            {"trace_id": "t1", "embedding": [0.1, 0.2]},
            {"trace_id": "t2", "embedding": [0.1, 0.2, 0.3]},
        ]
        with self.assertRaisesRegex(EncoderContractError, "inconsistent embedding dimensions"):
            validate_trace_embeddings(mixed)

    def test_build_model_assets_payload(self):
        encoder = FakeIntentEncoder(dimension=8)
        payload = build_model_assets(encoder, 8)
        self.assertEqual(ENCODER_CONTRACT_VERSION, payload["encoder_contract_version"])
        self.assertEqual("encoder", payload["embedding_source"])
        self.assertEqual(8, payload["embedding_dimension"])
        self.assertEqual(encoder.asset.fingerprint(), payload["intent_encoder"]["fingerprint"])

        source_payload = build_model_assets(None, 384)
        self.assertEqual("trace_field", source_payload["embedding_source"])
        self.assertIsNone(source_payload["intent_encoder"])


class ProductionEmbeddingGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.traces = load_benchmark_traces(60)

    def test_production_run_records_trace_field_model_assets(self):
        result, scores = run_production(list(self.traces), "ontology-gate-test")
        self.assertEqual(60, result["n"])
        assets = result["model_assets"]
        self.assertEqual(ENCODER_CONTRACT_VERSION, assets["encoder_contract_version"])
        self.assertEqual("trace_field", assets["embedding_source"])
        self.assertEqual(384, assets["embedding_dimension"])
        self.assertIsNone(assets["intent_encoder"])
        self.assertEqual(384, result["frozen_state"]["embedding_dim"])

    def test_production_run_fails_on_empty_embeddings(self):
        stripped = [{**trace, "embedding": []} for trace in self.traces]
        with self.assertRaisesRegex(EncoderContractError, "remediation:.*IntentEncoder"):
            run_production(stripped, "ontology-gate-test")

    def test_production_run_fails_on_inconsistent_dimensions(self):
        mixed = [
            {**trace, "embedding": trace["embedding"][: 384 if index % 2 == 0 else 12]}
            for index, trace in enumerate(self.traces)
        ]
        with self.assertRaisesRegex(EncoderContractError, "inconsistent embedding dimensions"):
            run_production(mixed, "ontology-gate-test")

    def test_intent_encoder_hook_encodes_and_records_fingerprint(self):
        stripped = [{**trace, "embedding": []} for trace in self.traces]
        encoder = FakeIntentEncoder(dimension=8)
        result, _scores = run_production(
            stripped, "ontology-gate-test", intent_encoder=encoder
        )
        assets = result["model_assets"]
        self.assertEqual("encoder", assets["embedding_source"])
        self.assertEqual(8, assets["embedding_dimension"])
        self.assertEqual(encoder.asset.fingerprint(), assets["intent_encoder"]["fingerprint"])
        self.assertEqual(8, result["frozen_state"]["embedding_dim"])

    def test_r1_rejects_embedding_dimension_mismatch(self):
        stripped = [{**trace, "embedding": []} for trace in self.traces]
        initial, _ = run_production(
            stripped, "ontology-gate-test", intent_encoder=FakeIntentEncoder(dimension=8)
        )
        with self.assertRaisesRegex(EncoderContractError, "dimension mismatch.*expected=8 actual=384"):
            run_production(
                list(self.traces),
                "ontology-gate-test",
                frozen_state=initial["frozen_state"],
            )

    def test_r1_rejects_legacy_empty_embedding_structure(self):
        stripped = [{**trace, "embedding": []} for trace in self.traces]
        encoder = FakeIntentEncoder(dimension=8)
        initial, _ = run_production(
            stripped, "ontology-gate-test", intent_encoder=encoder
        )
        legacy_state = dict(initial["frozen_state"])
        del legacy_state["embedding_dim"]
        legacy_state["cents_i"] = {key: [] for key in legacy_state["cents_i"]}
        with self.assertRaisesRegex(EncoderContractError, "predates intent embeddings"):
            run_production(
                [{**trace, "embedding": []} for trace in self.traces],
                "ontology-gate-test",
                frozen_state=legacy_state,
                intent_encoder=encoder,
            )

    def test_engine_persists_model_assets_provenance(self):
        traces = load_benchmark_traces(20)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "test.db"
            connection = store.connect(db_path, initialize=True)
            try:
                tenant_id = store.create_tenant(connection, "Owner", "org", "project", "pk", "sk")
                ontology_id = store.create_ontology(connection, tenant_id, "Agent", "tier0")
                run_id = store.create_run(
                    connection, tenant_id, ontology_id, "langfuse", "smoke", "R1",
                    "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", 1.0, "test", None,
                )
            finally:
                connection.close()

            engine = RunEngine(db_path)
            try:
                with patch("platform.app.engine.VAR_ROOT", root / "var"):
                    engine.submit(
                        run_id, "smoke", 1.0, 20, trace_source=FakeTraceSource(traces),
                        window={"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
                        ontology_id=ontology_id,
                    )
            finally:
                engine.close()

            connection = store.connect(db_path)
            try:
                run = store.get_run(connection, run_id)
                step = connection.execute(
                    "SELECT payload_json FROM run_steps WHERE run_id = ? AND name = 'algorithm'",
                    (run_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual("succeeded", run["status"])
            assets = json.loads(run["model_assets_json"])
            self.assertEqual("trace_field", assets["embedding_source"])
            self.assertEqual(384, assets["embedding_dimension"])
            step_assets = json.loads(step["payload_json"])["model_assets"]
            self.assertEqual(assets, step_assets)


if __name__ == "__main__":
    unittest.main()
