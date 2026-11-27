"""Phase E2: offline bge-m3 intent encoder.

Implements platform/EMBEDDING_REMEDIATION_PLAN.md phase E2:
- offline loader that verifies every pinned weight file SHA-256 before load
  and refuses to start on mismatch; no network access is ever attempted;
- batched, deterministic CPU inference via sentence-transformers;
- a SQLite embedding cache whose keys bind model fingerprint, input
  construction version and per-text hash, so stale reuse across model or
  preprocessing changes is impossible by construction.

The kernel stays standard-library only: heavy dependencies (torch,
sentence-transformers) are imported lazily here and confined to the platform
layer. Missing dependencies or weights fail with actionable errors.
"""

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from platform.app.encoder import EncoderContractError, ModelAsset


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = ROOT / "platform" / "config" / "model_assets.json"
DEFAULT_CACHE_PATH = ROOT / "platform" / "var" / "embedding-cache.db"
REGISTRY_VERSION = "model-asset-registry-v1"

# Input construction version: trace_intent_texts() semantics (raw intent_text,
# no rewriting). Bump when the text fed to the encoder changes.
INTENT_INPUT_VERSION = "intent-text:v1"
# Encode configuration version: sentence-transformers dense encode,
# L2-normalized float32 output. Bump when encode semantics change.
ENCODE_CONFIG_VERSION = "st-dense-l2:v1"

_MISSING_DEPS_REMEDIATION = (
    "remediation: install the pinned offline wheelhouse (requirements.txt: "
    "torch/sentence-transformers/transformers) on the target host; the kernel "
    "itself stays stdlib-only and does not need these packages"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EmbeddingCache:
    """Disposable SQLite cache; cache keys embed the model/cache fingerprint.

    The cache is non-authoritative: deleting the file only costs recompute.
    Keys are ``sha256(cache_fingerprint | text)`` so entries written under a
    different model, input construction or encode config can never collide.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS embedding_cache ("
                "  cache_key TEXT PRIMARY KEY,"
                "  embedding_json TEXT NOT NULL,"
                "  created_at TEXT NOT NULL"
                ")"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def get_many(self, keys: Sequence[str]) -> dict[str, list[float]]:
        if not keys:
            return {}
        hits: dict[str, list[float]] = {}
        with closing(self._connect()) as connection:
            for start in range(0, len(keys), 500):
                chunk = keys[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"SELECT cache_key, embedding_json FROM embedding_cache "
                    f"WHERE cache_key IN ({placeholders})",
                    list(chunk),
                ).fetchall()
                for key, payload in rows:
                    hits[key] = json.loads(payload)
        return hits

    def put_many(self, items: dict[str, list[float]]) -> None:
        if not items:
            return
        now = _now_iso()
        with closing(self._connect()) as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO embedding_cache "
                "(cache_key, embedding_json, created_at) VALUES (?, ?, ?)",
                [
                    (key, json.dumps(vector), now)
                    for key, vector in items.items()
                ],
            )
            connection.commit()


class BgeM3IntentEncoder:
    """Offline sentence-transformers encoder implementing the IntentEncoder contract."""

    def __init__(
        self,
        asset: ModelAsset,
        model_root: str | Path,
        batch_size: int = 32,
        cache: EmbeddingCache | None = None,
        eager: bool = True,
    ):
        if batch_size < 1:
            raise EncoderContractError("encoder batch_size must be at least 1")
        self._asset = asset
        self._model_root = Path(model_root)
        self._batch_size = int(batch_size)
        self._cache = cache
        self._model = None
        self._encode_lock = threading.Lock()
        self._cache_fingerprint = self._compute_cache_fingerprint()
        if eager:
            self._load_model()

    @property
    def asset(self) -> ModelAsset:
        return self._asset

    @property
    def batch_size(self) -> int:
        return self._batch_size

    def encode_config(self) -> dict:
        return {
            "input_version": INTENT_INPUT_VERSION,
            "encode_version": ENCODE_CONFIG_VERSION,
            "normalization": self._asset.normalization,
            "dtype": "float32",
        }

    def cache_fingerprint(self) -> str:
        return self._cache_fingerprint

    def _compute_cache_fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "asset_fingerprint": self._asset.fingerprint(),
                "encode_config": self.encode_config(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(
            f"{self._cache_fingerprint}|{text}".encode("utf-8")
        ).hexdigest()

    def _load_model(self) -> None:
        if self._model is not None:
            return
        self._asset.verify_weights(self._model_root)
        model = self._create_model()
        dimension_of = getattr(
            model, "get_embedding_dimension", None
        ) or model.get_sentence_embedding_dimension
        dimension = int(dimension_of())
        if dimension != self._asset.dimension:
            raise EncoderContractError(
                f"loaded model dimension mismatch expected={self._asset.dimension} "
                f"actual={dimension}; the offline package does not match the registry"
            )
        self._model = model

    def _create_model(self):
        """Build the SentenceTransformer strictly offline (no hub lookups)."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise EncoderContractError(
                f"sentence-transformers is not installed: {error}; "
                f"{_MISSING_DEPS_REMEDIATION}"
            ) from error
        previous = {
            name: os.environ.get(name)
            for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
        }
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            return SentenceTransformer(str(self._model_root), device="cpu")
        except Exception as error:
            raise EncoderContractError(
                f"failed to load offline model from {self._model_root}: {error}; "
                "restore the approved offline model package recorded in "
                "platform/config/model_assets.json"
            ) from error
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self._load_model()
        texts = [str(text) for text in texts]
        if self._cache is None:
            return self._encode_batch(texts)
        keys = [self._cache_key(text) for text in texts]
        hits = self._cache.get_many(keys)
        missing_positions = [i for i, key in enumerate(keys) if key not in hits]
        if missing_positions:
            fresh = self._encode_batch([texts[i] for i in missing_positions])
            self._cache.put_many(
                {keys[i]: vector for i, vector in zip(missing_positions, fresh)}
            )
            for i, vector in zip(missing_positions, fresh):
                hits[keys[i]] = vector
        return [hits[key] for key in keys]

    def _encode_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._encode_lock:
            try:
                encoded = self._model.encode(
                    texts,
                    batch_size=self._batch_size,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
            except Exception as error:
                raise EncoderContractError(
                    f"bge-m3 inference failed on a batch of {len(texts)} texts: "
                    f"{error}"
                ) from error
        return [row.tolist() for row in encoded]


def load_asset_registry(path: str | Path | None = None) -> dict:
    registry_path = Path(path or DEFAULT_REGISTRY_PATH)
    if not registry_path.exists():
        raise EncoderContractError(
            f"model asset registry is missing: {registry_path}; restore it from "
            "the repository (platform/config/model_assets.json)"
        )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("registry_version") != REGISTRY_VERSION:
        raise EncoderContractError(
            f"unsupported model asset registry version "
            f"{registry.get('registry_version')!r}; expected {REGISTRY_VERSION!r}"
        )
    return registry


def model_asset_from_registry(name: str, registry: dict) -> ModelAsset:
    entry = (registry.get("models") or {}).get(name)
    if entry is None:
        known = ", ".join(sorted(registry.get("models") or {}))
        raise EncoderContractError(
            f"unknown intent encoder {name!r} in asset registry (known: {known})"
        )
    return ModelAsset(
        provider=entry["provider"],
        model_name=entry["model_name"],
        revision=entry["revision"],
        dimension=int(entry["dimension"]),
        weights=dict(entry["weights"]),
        max_tokens=int(entry["max_tokens"]),
        truncation=entry["truncation"],
        normalization=entry["normalization"],
        backend=entry["backend"],
        cache_dir=entry.get("cache_dir"),
    )


def load_intent_encoder(
    name: str = "bge-m3",
    *,
    registry_path: str | Path | None = None,
    model_root: str | Path | None = None,
    cache_path: str | Path | None = None,
    batch_size: int = 32,
    eager: bool = True,
) -> BgeM3IntentEncoder:
    """Verify the pinned asset and return a ready-to-use offline encoder."""
    registry = load_asset_registry(registry_path)
    asset = model_asset_from_registry(name, registry)
    root = Path(model_root) if model_root else ROOT / str(asset.cache_dir)
    cache = EmbeddingCache(cache_path or DEFAULT_CACHE_PATH)
    return BgeM3IntentEncoder(
        asset, root, batch_size=batch_size, cache=cache, eager=eager
    )


def configure_engine_from_env(engine, env: dict | None = None):
    """Attach an intent encoder to a RunEngine from environment configuration.

    ``TRAJ_INTENT_ENCODER`` names a registry entry (empty/absent disables the
    encoder, preserving trace-field embedding behavior). Optional overrides:
    ``TRAJ_MODEL_ROOT``, ``TRAJ_EMBEDDING_CACHE``, ``TRAJ_ENCODER_BATCH_SIZE``.
    Load failures raise EncoderContractError so service startup fails loudly
    with an actionable message instead of running degraded.
    """
    env = os.environ if env is None else env
    name = (env.get("TRAJ_INTENT_ENCODER") or "").strip()
    if not name:
        engine.intent_encoder = None
        return None
    batch_size = int(env.get("TRAJ_ENCODER_BATCH_SIZE") or "32")
    encoder = load_intent_encoder(
        name,
        model_root=env.get("TRAJ_MODEL_ROOT") or None,
        cache_path=env.get("TRAJ_EMBEDDING_CACHE") or None,
        batch_size=batch_size,
    )
    engine.intent_encoder = encoder
    return encoder
