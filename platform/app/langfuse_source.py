import base64
import json
import random
import urllib.error
import urllib.parse
import urllib.request
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterator, Protocol

from platform.app.trace_source import to_epoch, validate_trace


DEFAULT_FIELDS = "core,basic,time,io,metadata,model,usage,prompt,metrics,trace_context"


class Transport(Protocol):
    def __call__(self, url: str, params: dict, headers: dict) -> dict:
        ...


class LangfuseHttpError(RuntimeError):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"Langfuse API returned HTTP {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body


class UrllibTransport:
    def __call__(self, url: str, params: dict, headers: dict) -> dict:
        query = urllib.parse.urlencode(params, doseq=True)
        request = urllib.request.Request(f"{url}?{query}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise LangfuseHttpError(error.code, error.read().decode("utf-8", errors="replace")) from error
        return _decode_json(body)


class LangfuseTraceSource:
    source_type = "langfuse"

    @classmethod
    def from_config(cls, profile: dict, endpoints: dict, keys: dict, **kwargs):
        observation_endpoint = endpoints["endpoints"]["observations"]["list"]
        query = observation_endpoint.get("query", {})
        capabilities = profile.get("capabilities", {})
        if capabilities.get("observationsApi") != "v2":
            raise ValueError("Langfuse profile must expose observationsApi=v2")
        default_page_size = int(endpoints.get("limits", {}).get("observationsPageSizeDefault", 50))
        return cls(
            base_url=profile["baseUrl"],
            public_key=keys["publicKey"],
            secret_key=keys["secretKey"],
            observations_path=observation_endpoint["path"],
            fields=query.get("fields", DEFAULT_FIELDS),
            page_size=int(kwargs.pop("page_size", default_page_size)),
            expand_metadata=query.get("expandMetadata"),
            **kwargs,
        )

    def __init__(self, base_url, public_key, secret_key, observations_path="/api/public/v2/observations", fields=DEFAULT_FIELDS, page_size=1000, expand_metadata=None, transport=None, max_traces=None, max_retries=3, retry_backoff_seconds=0.1):
        self.base_url = base_url.rstrip("/")
        self.observations_path = observations_path if observations_path.startswith("/") else f"/{observations_path}"
        self.public_key = public_key
        self.secret_key = secret_key
        self.fields = fields
        self.page_size = min(int(page_size), 1000)
        self.expand_metadata = expand_metadata
        self.transport = transport or UrllibTransport()
        self.max_traces = max_traces
        self.max_retries = int(max_retries)
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self.traversal = {}
        if self.page_size <= 0:
            raise ValueError("page_size must be in [1, 1000]")

    def list_traces(self, window: dict, sampling: dict) -> Iterator[dict]:
        if window.get("start") is None or window.get("end") is None:
            raise ValueError("Langfuse ingestion requires an explicit start and end time")

        observations: dict[str, list[dict]] = defaultdict(list)
        cursors: list[str] = []
        page_count = 0
        empty_pages = 0
        last_page_size = 0
        cursor = None

        while True:
            params = {
                "fields": self.fields,
                "limit": self.page_size,
                "fromStartTime": _iso8601(window["start"]),
                "toStartTime": _iso8601(window["end"]),
            }
            if self.expand_metadata:
                params["expandMetadata"] = self.expand_metadata
            if cursor is not None:
                params["cursor"] = cursor

            response = self._request(f"{self.base_url}{self.observations_path}", params)
            _validate_page(response, page_count + 1)
            page = response["data"]
            for observation in page:
                _validate_observation(observation, page_count + 1)
                observations[observation["traceId"]].append(observation)

            page_count += 1
            last_page_size = len(page)
            if not page:
                empty_pages += 1
            cursor = response["meta"].get("cursor")
            if cursor is not None:
                cursors.append(cursor)
            if cursor is None:
                break

        traces = []
        incomplete_traces = []
        for trace_id, items in sorted(observations.items()):
            roots = [
                item for item in items
                if item.get("isRootObservation") is True or item.get("parentObservationId") is None
            ]
            if len(roots) != 1:
                incomplete_traces.append(trace_id)
                continue
            traces.append(_map_trace(items))
        traces = _sample(traces, sampling)
        if self.max_traces is not None:
            traces = traces[: self.max_traces]

        for trace in traces:
            validate_trace(trace, "langfuse-observations", trace["trace_id"])
            yield trace

        self.traversal = {
            "pages": page_count,
            "empty_pages": empty_pages,
            "last_page_size": last_page_size,
            "observations": sum(len(items) for items in observations.values()),
            "traces": len(observations),
            "incomplete_traces": len(incomplete_traces),
            "incomplete_trace_ids": incomplete_traces[:20],
            "returned_traces": len(traces),
            "cursors": cursors,
        }

    def _headers(self) -> dict:
        token = base64.b64encode(f"{self.public_key}:{self.secret_key}".encode("utf-8")).decode("ascii")
        return {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "traj-engine/0.1",
        }

    def _request(self, url: str, params: dict) -> dict:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return self.transport(url, params, self._headers())
            except LangfuseHttpError as error:
                if error.status_code != 429 or attempt == self.max_retries:
                    raise
                last_error = error
            except (OSError, TimeoutError) as error:
                if attempt == self.max_retries:
                    raise
                last_error = error
            if self.retry_backoff_seconds:
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))
        raise last_error


def _decode_json(body: str) -> dict:
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError("Langfuse API returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Langfuse API response must be a JSON object")
    return value


def _validate_page(response: dict, page_number: int) -> None:
    data = response.get("data")
    meta = response.get("meta")
    if not isinstance(data, list) or not isinstance(meta, dict):
        raise ValueError(f"invalid Langfuse observations page {page_number}: data must be a list and meta an object")


def _validate_observation(observation: object, page_number: int) -> None:
    if not isinstance(observation, dict):
        raise ValueError(f"Langfuse observation on page {page_number} must be an object")
    for key in ("id", "traceId", "startTime", "projectId", "type"):
        if key not in observation:
            raise ValueError(f"Langfuse observation on page {page_number} is missing core key {key}")


def _iso8601(value) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sample(traces: list[dict], sampling: dict) -> list[dict]:
    rate = float(sampling.get("rate", 1.0))
    if rate <= 0 or rate > 1:
        raise ValueError("sampling rate must be in (0, 1]")
    if rate == 1:
        return traces
    if sampling.get("strategy", "systematic") == "random":
        seed = int(sampling.get("seed", 0))
        take = max(1, round(len(traces) * rate))
        return random.Random(seed).sample(traces, take)
    stride = max(1, round(1 / rate))
    return traces[::stride]


def _map_trace(items: list[dict]) -> dict:
    ordered = sorted(items, key=lambda item: (item.get("startTime") or "", item["id"]))
    roots = [item for item in ordered if item.get("isRootObservation") is True or item.get("parentObservationId") is None]
    if not roots:
        raise ValueError(f"Langfuse trace {ordered[0]['traceId']} has no root observation")
    if len(roots) != 1:
        raise ValueError(f"Langfuse trace {ordered[0]['traceId']} has multiple root observations: " + ", ".join(item["id"] for item in roots))
    root = roots[0]
    root_metadata = _metadata(root)

    return {
        "answer_citations": _metadata_value(root_metadata, "answer_citations"),
        "answer_facts": _metadata_value(root_metadata, "answer_facts"),
        "answer_numbers": _metadata_value(root_metadata, "answer_numbers"),
        "contradicted_facts": _metadata_value(root_metadata, "contradicted_facts", []),
        "embedding": _metadata_value(root_metadata, "embedding"),
        "goal_text": _metadata_value(root_metadata, "goal_text"),
        "golden_answer": _metadata_value(root_metadata, "golden_answer"),
        "golden_facts": _metadata_value(root_metadata, "golden_facts"),
        "intent_text": _metadata_value(root_metadata, "intent_text") or _text(root.get("input")),
        "ontology_id": _metadata_value(root_metadata, "ontology_id"),
        "query_lang": _metadata_value(root_metadata, "query_lang"),
        "raw_flags": _metadata_value(root_metadata, "raw_flags", {}),
        "session_id": root.get("sessionId"),
        "session_turn_count": _metadata_value(root_metadata, "session_turn_count"),
        "spans": [_map_span(item) for item in ordered],
        "trace_id": root["traceId"],
        "ts_start": to_epoch(root.get("startTime")),
        "turn_index": _metadata_value(root_metadata, "turn_index"),
        "user_feedback": _metadata_value(root_metadata, "user_feedback"),
    }


def _map_span(item: dict) -> dict:
    metadata = _metadata(item)
    usage = item.get("usageDetails") or {}
    cost_details = _normalize_cost_details(item.get("costDetails"))

    return {
        "action": item.get("name"),
        "arg_valid": _metadata_value(metadata, "arg_valid"),
        "cost": item.get("totalCost"),
        "cost_details": cost_details,
        "finish_reason": _metadata_value(metadata, "finish_reason"),
        "input_text": _text(item.get("input")),
        "kind": _kind(item),
        "level": item.get("level") or "DEFAULT",
        "model": item.get("model"),
        "output_citations": _metadata_value(metadata, "output_citations"),
        "output_facts": _metadata_value(metadata, "output_facts"),
        "output_text": _text(item.get("output")),
        "parent_id": item.get("parentObservationId"),
        "prompt_version": item.get("promptName") or item.get("promptId"),
        "span_id": item["id"],
        "status": _status(item),
        "status_message": item.get("statusMessage"),
        "subgoal_text": _metadata_value(metadata, "subgoal_text"),
        "tokens_cache_read": _usage_value(usage, ("cacheRead", "cache_read", "inputCacheRead")),
        "tokens_cache_write": _usage_value(usage, ("cacheWrite", "cache_write", "inputCacheWrite")),
        "tokens_completion": _usage_value(usage, ("output", "completion", "outputTokens")),
        "tokens_prompt": _usage_value(usage, ("input", "prompt", "inputTokens")),
        "tokens_system_prompt": _metadata_value(metadata, "tokens_system_prompt"),
        "tool_name": _metadata_value(metadata, "tool_name"),
        "tool_params": _metadata_value(metadata, "tool_params"),
        "ts_end": to_epoch(item.get("endTime")),
        "ts_start": to_epoch(item.get("startTime")),
        "ttft": item.get("timeToFirstToken"),
        "verifier": _metadata_value(metadata, "verifier"),
    }


def _metadata(item: dict) -> dict:
    value = item.get("metadata")
    return value if isinstance(value, dict) else {}


def _metadata_value(metadata: dict, key: str, default=None):
    if key not in metadata:
        return default
    value = metadata[key]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in ("", "null"):
            return None
        if stripped.startswith(("[", "{")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
        if stripped in ("true", "false"):
            return stripped == "true"
    return value


def _kind(item: dict) -> str:
    if item.get("isRootObservation") is True or item.get("parentObservationId") is None:
        return "agent"
    mapping = {"GENERATION": "llm", "TOOL": "tool", "RETRIEVER": "retrieval", "EVALUATOR": "verifier", "GUARDRAIL": "verifier", "EMBEDDING": "embedding"}
    return mapping.get(str(item.get("type", "")).upper(), "process")


def _status(item: dict) -> str:
    level = str(item.get("level") or "").upper()
    if level == "ERROR":
        return "error"
    if level == "WARNING":
        return "warning"
    return "ok"


def _text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _usage_value(usage: dict, aliases: tuple[str, ...]):
    for alias in aliases:
        if alias in usage and usage[alias] is not None:
            return int(usage[alias])
    return None


def _normalize_cost_details(value):
    if not isinstance(value, dict):
        return None
    aliases = {
        "cache_read": ("cacheRead", "cache_read", "inputCacheRead"),
        "cache_write": ("cacheWrite", "cache_write", "inputCacheWrite"),
        "completion": ("output", "completion", "outputTokens"),
        "prompt": ("input", "prompt", "inputTokens"),
        "tool_call": ("toolCall", "tool_call"),
    }
    return {target: float(next((value[key] for key in keys if key in value), 0.0)) for target, keys in aliases.items()}
