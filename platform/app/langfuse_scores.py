import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Protocol
from typing import Iterable

from platform.app.langfuse_source import LangfuseHttpError


TOTAL_SCORE_NAME = "traj-engine-total-score"
ALERT_SCORE_NAME = "traj-engine-alert"
ABSTAIN_SCORE_NAME = "traj-engine-abstain"


class ScoreTransport(Protocol):
    def __call__(self, url: str, body: bytes, headers: dict) -> dict:
        ...


class UrllibScoreTransport:
    def __call__(self, url: str, body: bytes, headers: dict) -> dict:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise LangfuseHttpError(error.code, error.read().decode("utf-8", errors="replace")) from error
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("Langfuse score writeback returned non-JSON response") from error


class LangfuseScoreWriter:
    @classmethod
    def from_config(cls, profile: dict, endpoints: dict, keys: dict, **kwargs):
        endpoint = endpoints["endpoints"]["scores"]["create"]
        limits = endpoints.get("limits", {})
        return cls(
            base_url=profile["baseUrl"],
            public_key=keys["publicKey"],
            secret_key=keys["secretKey"],
            scores_path=endpoint["path"],
            batch_size=int(limits.get("scoresCreateBatchSize", 100)),
            **kwargs,
        )

    def __init__(
        self,
        base_url: str,
        public_key: str,
        secret_key: str,
        scores_path: str = "/api/public/scores",
        batch_size: int = 100,
        transport: ScoreTransport | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.scores_path = scores_path if scores_path.startswith("/") else f"/{scores_path}"
        self.public_key = public_key
        self.secret_key = secret_key
        self.batch_size = max(1, int(batch_size))
        self.transport = transport or UrllibScoreTransport()
        self.max_retries = int(max_retries)
        self.retry_backoff_seconds = float(retry_backoff_seconds)

    def write_scores(self, score_rows: Iterable[dict], run: dict) -> dict:
        accepted = 0
        rejected = 0
        attempted = 0
        batches = 0
        errors: list[str] = []
        batch = []
        for row in score_rows:
            payloads = [self.build_score_payload(row, run)]
            payloads.extend(self.build_status_payloads(row, run))
            attempted += len(payloads)
            batch.extend(payloads)
            if len(batch) < self.batch_size:
                continue
            result = self._post_batch(batch)
            accepted += int(result["accepted"])
            rejected += int(result["rejected"])
            batches += 1
            errors.extend(result["errors"])
            batch = []
        if batch:
            result = self._post_batch(batch)
            accepted += int(result["accepted"])
            rejected += int(result["rejected"])
            batches += 1
            errors.extend(result["errors"])
        return {
            "attempted": attempted,
            "accepted": accepted,
            "rejected": rejected,
            "batches": batches,
            "errors": errors,
        }

    def build_score_payload(self, row: dict, run: dict) -> dict:
        trace_id = str(row["trace_id"])
        metadata = {
            "runId": run["id"],
            "cell": row.get("cell"),
            "resultScore": row.get("dims", {}).get("O"),
            "processScore": row.get("dims", {}).get("P"),
            "latencyScore": row.get("dims", {}).get("L"),
            "costScore": row.get("dims", {}).get("C"),
            "robustnessScore": row.get("dims", {}).get("R"),
            "grade": row.get("grade_abs"),
            "codeHash": run.get("code_hash"),
        }
        return {
            "id": self.score_id(run["id"], trace_id, TOTAL_SCORE_NAME),
            "traceId": trace_id,
            "name": TOTAL_SCORE_NAME,
            "value": float(row["S"]),
            "dataType": "NUMERIC",
            "source": "API",
            "timestamp": run["created_at"],
            "comment": "Traj-engine automatic trace quality score.",
            "metadata": metadata,
        }

    def build_status_payloads(self, row: dict, run: dict) -> list[dict]:
        trace_id = str(row["trace_id"])
        definitions = [
            (ALERT_SCORE_NAME, int(bool(row.get("alert")))),
            (ABSTAIN_SCORE_NAME, int(bool(row.get("novelty")))),
        ]
        payloads = []
        for name, value in definitions:
            payloads.append({
                "id": self.score_id(run["id"], trace_id, name),
                "traceId": trace_id,
                "name": name,
                "value": value,
                "dataType": "BOOLEAN",
                "source": "API",
                "timestamp": run["created_at"],
                "metadata": {"runId": run["id"], "cell": row.get("cell")},
            })
        return payloads

    def score_id(self, run_id: str, trace_id: str, name: str) -> str:
        digest = hashlib.sha256(f"{run_id}:{trace_id}:{name}".encode("utf-8")).hexdigest()
        return digest[:32]

    def _post_batch(self, batch: list[dict]) -> dict:
        body = json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self.transport(f"{self.base_url}{self.scores_path}", body, self._headers())
                return self._parse_response(response, len(batch))
            except LangfuseHttpError as error:
                if error.status_code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                    raise
                if self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds * (2**attempt))

    def _parse_response(self, response: dict, expected: int) -> dict:
        if "accepted" in response or "rejected" in response:
            errors = response.get("errors", [])
            messages = [str(error.get("message", error)) for error in errors if isinstance(error, dict)]
            return {
                "accepted": int(response.get("accepted", 0)),
                "rejected": int(response.get("rejected", 0)),
                "errors": messages,
            }
        if response == {} or response.get("message") == "Accepted":
            return {"accepted": expected, "rejected": 0, "errors": []}
        raise ValueError(f"unrecognized Langfuse score writeback response: {response!r}")

    def _headers(self) -> dict:
        token = base64.b64encode(
            f"{self.public_key}:{self.secret_key}".encode("utf-8")
        ).decode("ascii")
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "traj-engine/0.1",
        }
