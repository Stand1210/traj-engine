"""Intent encoder contract and model-asset governance.

Implements phase E1 of platform/EMBEDDING_REMEDIATION_PLAN.md:
- pluggable platform-side ``IntentEncoder`` contract with a pinned ``ModelAsset``;
- hard failure on empty embeddings, dimension drift and count mismatch;
- run-level model asset provenance payloads.

Silent degradation is forbidden: a production run either has complete,
dimension-consistent intent embeddings or it fails with an actionable error.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from typing import Sequence


ENCODER_CONTRACT_VERSION = "intent-encoder-contract-v1"

TRACE_EMBEDDING_REMEDIATION = (
    "remediation: configure a platform IntentEncoder with a pinned ModelAsset "
    "(EMBEDDING_REMEDIATION_PLAN.md phase E2) or provide a non-empty `embedding` "
    "field in the trace metadata"
)


class EncoderContractError(ValueError):
    """Raised when the intent encoder contract is violated."""


@dataclass(frozen=True)
class ModelAsset:
    """Immutable description of a pinned embedding model asset."""

    provider: str
    model_name: str
    revision: str
    dimension: int
    weights: dict[str, str]
    max_tokens: int
    truncation: str
    normalization: str
    backend: str
    cache_dir: str | None = None

    def fingerprint(self) -> str:
        canonical = json.dumps(self.provenance(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def provenance(self) -> dict:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "revision": self.revision,
            "dimension": self.dimension,
            "weights": dict(sorted(self.weights.items())),
            "max_tokens": self.max_tokens,
            "truncation": self.truncation,
            "normalization": self.normalization,
            "backend": self.backend,
        }

    def verify_weights(self, root: str | Path) -> None:
        """Verify every declared weight file exists and matches its SHA-256."""
        base = Path(root)
        for relative, expected in self.weights.items():
            path = base / relative
            if not path.exists():
                raise EncoderContractError(
                    f"model weight file is missing: {path}; restore the offline "
                    "model package or fix the asset registry before starting runs"
                )
            actual = _sha256_file(path)
            if actual != expected:
                raise EncoderContractError(
                    f"model weight hash mismatch: {path} "
                    f"expected={expected} actual={actual}; refusing to load, "
                    "re-install the approved offline model package"
                )


class IntentEncoder(Protocol):
    """Platform-side intent embedding encoder contract (E2 provides bge-m3)."""

    @property
    def asset(self) -> ModelAsset:
        ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding per input text, in input order."""
        ...


def encode_intents(encoder: IntentEncoder, texts: Sequence[str]) -> list[list[float]]:
    """Encode intent texts and validate the output against the contract."""
    embeddings = encoder.encode(list(texts))
    validate_embeddings(
        embeddings,
        expected_count=len(texts),
        expected_dimension=encoder.asset.dimension,
        context=f"encoder {encoder.asset.model_name}@{encoder.asset.revision}",
    )
    return [list(vector) for vector in embeddings]


def validate_embeddings(
    embeddings: Sequence[Sequence[float]] | None,
    expected_count: int,
    expected_dimension: int | None = None,
    context: str = "embeddings",
) -> int:
    """Fail hard on missing, empty or dimension-inconsistent embeddings."""
    if embeddings is None:
        raise EncoderContractError(f"{context}: encoder returned no embeddings")
    if len(embeddings) != expected_count:
        raise EncoderContractError(
            f"{context}: embedding count mismatch expected={expected_count} "
            f"actual={len(embeddings)}; refusing to continue"
        )
    if expected_count == 0:
        raise EncoderContractError(f"{context}: no embeddings to validate")
    dimension: int | None = None
    for index, vector in enumerate(embeddings):
        if not vector:
            raise EncoderContractError(
                f"{context}: empty embedding at index {index}; "
                "silent degradation is forbidden"
            )
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise EncoderContractError(
                f"{context}: inconsistent embedding dimension at index {index} "
                f"expected={dimension} actual={len(vector)}"
            )
    if expected_dimension is not None and dimension != expected_dimension:
        raise EncoderContractError(
            f"{context}: embedding dimension mismatch "
            f"expected={expected_dimension} actual={dimension}"
        )
    return int(dimension or 0)


def validate_trace_embeddings(traces: Sequence[dict], context: str = "production run") -> int:
    """Every trace must carry a non-empty embedding of one consistent dimension."""
    missing = [str(trace.get("trace_id")) for trace in traces if not trace.get("embedding")]
    if missing:
        sample = ", ".join(missing[:5])
        raise EncoderContractError(
            f"{context}: {len(missing)}/{len(traces)} traces have empty intent "
            f"embeddings (e.g. {sample}); silent degradation is forbidden; "
            f"{TRACE_EMBEDDING_REMEDIATION}"
        )
    dimensions = {len(trace["embedding"]) for trace in traces}
    if len(dimensions) != 1:
        raise EncoderContractError(
            f"{context}: inconsistent embedding dimensions {sorted(dimensions)}; "
            f"{TRACE_EMBEDDING_REMEDIATION}"
        )
    return dimensions.pop()


def trace_intent_texts(traces: Sequence[dict]) -> list[str]:
    """Default intent text per trace; E2 owns the full input construction."""
    return [str(trace.get("intent_text") or "") for trace in traces]


def build_model_assets(encoder: IntentEncoder | None, embedding_dimension: int) -> dict:
    """Run provenance payload for model assets (persisted per cohort run)."""
    return {
        "encoder_contract_version": ENCODER_CONTRACT_VERSION,
        "embedding_source": "encoder" if encoder is not None else "trace_field",
        "embedding_dimension": embedding_dimension,
        "intent_encoder": (
            {**encoder.asset.provenance(), "fingerprint": encoder.asset.fingerprint()}
            if encoder is not None
            else None
        ),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
