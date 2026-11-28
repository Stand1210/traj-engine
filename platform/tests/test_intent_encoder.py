"""Phase E2 tests: offline bge-m3 loader, asset registry, cache, wiring.

Real-weight integration tests are skipped when the offline model package is
absent (e.g. bench-only checkouts); every contract that does not need the
2.3 GB weights runs unconditionally with fakes.
"""

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

from platform.app import intent_encoder as ie
from platform.app.encoder import EncoderContractError, ModelAsset, build_model_assets


WEIGHTS_ROOT = ie.ROOT / "platform" / "var" / "models" / "bge-m3"
WEIGHTS_AVAILABLE = (WEIGHTS_ROOT / "pytorch_model.bin").exists()


def _asset(weights: dict[str, str] | None = None, **overrides) -> ModelAsset:
    fields = dict(
        provider="BAAI (test)",
        model_name="BAAI/bge-m3",
        revision="5617a9f61b028005a4858fdac845db406aefb181",
        dimension=1024,
        weights=weights or {"pytorch_model.bin": "0" * 64},
        max_tokens=8192,
        truncation="tokenizer-right:8192",
        normalization="l2",
        backend="sentence-transformers==6.3.0 (test)",
        cache_dir=None,
    )
    fields.update(overrides)
    return ModelAsset(**fields)


class FakeSTModel:
    """Deterministic stand-in for SentenceTransformer (no weights needed)."""

    def __init__(self, dimension: int = 1024):
        self._dimension = dimension
        self.batch_calls: list[int] = []

    def get_sentence_embedding_dimension(self) -> int:
        return self._dimension

    def encode(self, texts, batch_size, show_progress_bar, convert_to_numpy, normalize_embeddings):
        self.batch_calls.append(len(texts))
        rows = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
            rng = np.random.default_rng(seed)
            vector = rng.standard_normal(self._dimension).astype(np.float32)
            if normalize_embeddings:
                vector = vector / np.linalg.norm(vector)
            rows.append(vector)
        return np.vstack(rows)


def _fake_encoder(cache=None, dimension: int = 1024, eager: bool = False) -> ie.BgeM3IntentEncoder:
    encoder = ie.BgeM3IntentEncoder(
        _asset(), Path("."), batch_size=4, cache=cache, eager=eager
    )
    encoder._model = FakeSTModel(dimension)
    return encoder


class RegistryTest(unittest.TestCase):
    def test_real_registry_loads_bge_m3(self):
        registry = ie.load_asset_registry()
        asset = ie.model_asset_from_registry("bge-m3", registry)
        self.assertEqual("BAAI/bge-m3", asset.model_name)
        self.assertEqual(1024, asset.dimension)
        self.assertEqual(8192, asset.max_tokens)
        self.assertEqual("l2", asset.normalization)
        self.assertEqual(10, len(asset.weights))
        self.assertIn("pytorch_model.bin", asset.weights)
        self.assertEqual(64, len(asset.weights["pytorch_model.bin"]))
        self.assertEqual("platform/var/models/bge-m3", asset.cache_dir)

    def test_unknown_model_name_rejected(self):
        registry = ie.load_asset_registry()
        with self.assertRaises(EncoderContractError):
            ie.model_asset_from_registry("no-such-model", registry)

    def test_missing_registry_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EncoderContractError):
                ie.load_asset_registry(Path(tmp) / "absent.json")

    def test_registry_version_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reg.json"
            path.write_text(json.dumps({"registry_version": "v0", "models": {}}))
            with self.assertRaises(EncoderContractError):
                ie.load_asset_registry(path)


class OfflineLoadGateTest(unittest.TestCase):
    """hash/weight failures must refuse the load before any inference."""

    def test_missing_weight_file_refuses_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = _asset(weights={"pytorch_model.bin": "0" * 64})
            with self.assertRaisesRegex(EncoderContractError, "missing"):
                ie.BgeM3IntentEncoder(asset, tmp, eager=True)

    def test_hash_mismatch_refuses_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pytorch_model.bin").write_bytes(b"tampered weights")
            asset = _asset(weights={"pytorch_model.bin": "0" * 64})
            with self.assertRaisesRegex(EncoderContractError, "hash mismatch"):
                ie.BgeM3IntentEncoder(asset, root, eager=True)

    def test_dimension_mismatch_after_load_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b"fake"
            digest = hashlib.sha256(payload).hexdigest()
            (root / "w.bin").write_bytes(payload)
            asset = _asset(weights={"w.bin": digest}, dimension=999)
            encoder = ie.BgeM3IntentEncoder(asset, root, eager=False)
            encoder._create_model = lambda: FakeSTModel(dimension=1024)
            with self.assertRaisesRegex(EncoderContractError, "dimension mismatch"):
                encoder._load_model()


class EncodeContractTest(unittest.TestCase):
    def test_deterministic_and_normalized(self):
        encoder = _fake_encoder()
        first = encoder.encode(["查询端口流量", "summarize timeline"])
        second = encoder.encode(["查询端口流量", "summarize timeline"])
        self.assertEqual(first, second)
        self.assertEqual(2, len(first))
        self.assertEqual(1024, len(first[0]))
        self.assertAlmostEqual(1.0, float(np.linalg.norm(first[0])), places=5)

    def test_empty_batch_returns_empty(self):
        self.assertEqual([], _fake_encoder().encode([]))

    def test_inference_failure_wrapped(self):
        class Boom(FakeSTModel):
            def encode(self, *args, **kwargs):
                raise RuntimeError("oom")

        encoder = _fake_encoder()
        encoder._model = Boom()
        with self.assertRaisesRegex(EncoderContractError, "inference failed"):
            encoder.encode(["x"])

    def test_provenance_includes_cache_fingerprint(self):
        encoder = _fake_encoder()
        payload = build_model_assets(encoder, 1024)
        encoder_payload = payload["intent_encoder"]
        self.assertEqual("encoder", payload["embedding_source"])
        self.assertEqual(encoder.asset.fingerprint(), encoder_payload["fingerprint"])
        self.assertEqual(
            encoder.cache_fingerprint(), encoder_payload["cache_fingerprint"]
        )


class CacheTest(unittest.TestCase):
    def test_cache_hit_avoids_recompute(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = ie.EmbeddingCache(Path(tmp) / "cache.db")
            encoder = _fake_encoder(cache=cache)
            texts = ["alpha", "beta", "gamma", "delta", "epsilon"]
            first = encoder.encode(texts)
            self.assertEqual([5], encoder._model.batch_calls)
            second = encoder.encode(texts)
            self.assertEqual(first, second)
            self.assertEqual([5], encoder._model.batch_calls)

    def test_cache_key_binds_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = ie.EmbeddingCache(Path(tmp) / "cache.db")
            encoder_a = _fake_encoder(cache=cache)
            encoder_b = _fake_encoder(cache=cache, dimension=512)
            encoder_b._asset = _asset(model_name="BAAI/other")
            encoder_b._cache_fingerprint = encoder_b._compute_cache_fingerprint()
            self.assertNotEqual(
                encoder_a._cache_key("alpha"), encoder_b._cache_key("alpha")
            )
            encoder_a.encode(["alpha"])
            encoder_b.encode(["alpha"])
            self.assertEqual([1], encoder_b._model.batch_calls)

    def test_cache_roundtrip_preserves_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.db"
            cache = ie.EmbeddingCache(path)
            encoder = _fake_encoder(cache=cache)
            fresh = encoder.encode(["hello world"])
            reopened = ie.EmbeddingCache(path)
            hits = reopened.get_many([encoder._cache_key("hello world")])
            self.assertEqual(fresh[0], hits[encoder._cache_key("hello world")])

    def test_cache_fingerprint_stable_and_sensitive(self):
        encoder = _fake_encoder()
        self.assertEqual(
            encoder.cache_fingerprint(), _fake_encoder().cache_fingerprint()
        )
        other = _fake_encoder()
        other._asset = _asset(revision="different-revision")
        other._cache_fingerprint = other._compute_cache_fingerprint()
        self.assertNotEqual(
            encoder.cache_fingerprint(), other.cache_fingerprint()
        )


class EnvWiringTest(unittest.TestCase):
    def test_disabled_without_env(self):
        engine = types.SimpleNamespace(intent_encoder="untouched")
        result = ie.configure_engine_from_env(engine, env={})
        self.assertIsNone(result)
        self.assertIsNone(engine.intent_encoder)

    def test_unknown_name_fails_loudly(self):
        engine = types.SimpleNamespace(intent_encoder=None)
        with self.assertRaises(EncoderContractError):
            ie.configure_engine_from_env(
                engine, env={"TRAJ_INTENT_ENCODER": "no-such-model"}
            )


@unittest.skipUnless(WEIGHTS_AVAILABLE, "offline bge-m3 package not installed")
class RealModelIntegrationTest(unittest.TestCase):
    """Acceptance: offline load, reproducibility, cache reuse with real weights."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cache = ie.EmbeddingCache(Path(cls.tmp.name) / "cache.db")
        cls.encoder = ie.load_intent_encoder(
            "bge-m3", cache_path=Path(cls.tmp.name) / "cache.db", batch_size=8
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_offline_load_and_contract(self):
        self.assertEqual(1024, self.encoder.asset.dimension)
        self.assertEqual(
            16, len(self.encoder.cache_fingerprint())
        )

    def test_reproducible_embeddings(self):
        texts = ["查询 NE-1 的端口流量并生成报告", "summarize the incident timeline"]
        first = self.encoder.encode(texts)
        second = self.encoder.encode(texts)
        self.assertEqual(first, second)
        self.assertAlmostEqual(1.0, float(np.linalg.norm(first[0])), places=5)

    def test_cache_persists_across_encoder_instances(self):
        import gc

        text = "cache reuse acceptance probe"
        before = self.encoder.encode([text])
        # Release the 2.3 GB model before loading a second instance: two
        # resident copies exceed available RAM on a dev machine.
        type(self).encoder._model = None
        gc.collect()
        fresh = ie.load_intent_encoder(
            "bge-m3", cache_path=Path(self.tmp.name) / "cache.db", batch_size=8
        )
        after = fresh.encode([text])
        self.assertEqual(before, after)
        type(self).encoder = fresh


class VerifyModelAssetsScriptTest(unittest.TestCase):
    """E6 ops verifier: exit codes must distinguish pass / package / registry errors."""

    def _write_registry(self, tmp: str, weights: dict[str, str]) -> Path:
        path = Path(tmp) / "reg.json"
        path.write_text(
            json.dumps(
                {
                    "registry_version": ie.REGISTRY_VERSION,
                    "models": {
                        "m": {
                            "provider": "test",
                            "model_name": "m",
                            "revision": "r",
                            "dimension": 4,
                            "weights": weights,
                            "max_tokens": 8,
                            "truncation": "t",
                            "normalization": "l2",
                            "backend": "b",
                            "cache_dir": "pkg",
                        }
                    },
                }
            )
        )
        return path

    def _run(self, argv: list[str]) -> int:
        from platform.scripts import verify_model_assets

        old_argv = sys.argv
        sys.argv = ["verify_model_assets", *argv]
        try:
            return verify_model_assets.main()
        finally:
            sys.argv = old_argv

    def test_pass_hash_mismatch_and_missing_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = b"tiny-weights"
            digest = hashlib.sha256(payload).hexdigest()
            registry = self._write_registry(tmp, {"w.bin": digest})
            root = Path(tmp) / "pkg"
            root.mkdir()
            (root / "w.bin").write_bytes(payload)
            base = ["--model", "m", "--root", str(root), "--registry", str(registry)]
            self.assertEqual(0, self._run(base))
            (root / "w.bin").write_bytes(b"tampered")
            self.assertEqual(1, self._run(base))
            (root / "w.bin").unlink()
            self.assertEqual(1, self._run(base))

    def test_registry_error_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(2, self._run(["--registry", str(Path(tmp) / "absent.json")]))


if __name__ == "__main__":
    unittest.main()
