import base64
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Protocol


class IngestTransport(Protocol):
    def __call__(self, url: str, body: bytes, headers: dict) -> dict:
        ...


class UrllibIngestTransport:
    def __call__(self, url: str, body: bytes, headers: dict) -> dict:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise LangfuseIngestionError(error.code, error.read().decode("utf-8", errors="replace")) from error
        return _decode_response(text)


class LangfuseIngestionError(RuntimeError):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"Langfuse OTLP ingestion returned HTTP {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body


class LangfuseOTLPTraceIngestor:
    source_type = "langfuse-otlp"

    @classmethod
    def from_config(cls, profile: dict, endpoints: dict, keys: dict, **kwargs):
        endpoint = endpoints["endpoints"]["otelTraces"]["ingest"]
        return cls(
            base_url=profile["baseUrl"],
            public_key=keys["publicKey"],
            secret_key=keys["secretKey"],
            traces_path=endpoint["path"],
            **kwargs,
        )

    def __init__(self, base_url, public_key, secret_key, traces_path="/api/public/otel/v1/traces", transport=None):
        self.base_url = base_url.rstrip("/")
        self.traces_path = traces_path if traces_path.startswith("/") else f"/{traces_path}"
        self.public_key = public_key
        self.secret_key = secret_key
        self.transport = transport or UrllibIngestTransport()

    def ingest(self, trace: dict) -> dict:
        payload = build_otlp_trace_payload(trace)
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        response = self.transport(f"{self.base_url}{self.traces_path}", body, self._headers())
        accepted = response == {} or self._is_valid_ingestion_job(response)
        if not accepted:
            raise ValueError(f"Langfuse OTLP ingestion returned an unrecognized response: {response!r}")
        return {"status": "accepted", "mode": "sync" if response == {} else "async", "trace_id": trace["trace_id"], "spans": len(trace["spans"])}

    def _headers(self) -> dict:
        token = base64.b64encode(f"{self.public_key}:{self.secret_key}".encode("utf-8")).decode("ascii")
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-langfuse-ingestion-version": "4",
            "User-Agent": "traj-engine/0.1",
        }

    def _is_valid_ingestion_job(self, response: dict) -> bool:
        data = response.get("data")
        if response.get("name") != "otel-ingestion-job" or not isinstance(data, dict):
            return False
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return False
        auth_check = payload.get("authCheck")
        if not isinstance(auth_check, dict):
            return False
        job_payload = payload.get("data")
        if not isinstance(job_payload, dict) or "fileKey" not in job_payload:
            return False
        return bool(auth_check.get("validKey")) and auth_check.get("scope", {}).get("projectId") is not None


def build_otlp_trace_payload(trace: dict) -> dict:
    spans = [_build_otlp_span(span, trace) for span in trace["spans"]]
    if not spans:
        raise ValueError("Langfuse OTLP trace must contain at least one span")
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


def _build_otlp_span(span: dict, trace: dict) -> dict:
    trace_id = _hex_id(trace["trace_id"], 32, "trace_id")
    span_id = _hex_id(span["span_id"], 16, "span_id")
    parent_span_id = None
    if span.get("parent_id"):
        parent_span_id = _hex_id(span["parent_id"], 16, "parent_id")
    attributes = []
    trace_name = trace.get("intent_text") or "traj-engine-trace"
    observation_type = "agent" if not span.get("parent_id") else _observation_type(span)
    _add_string(attributes, "langfuse.observation.type", observation_type)
    _add_string(attributes, "langfuse.trace.name", trace_name)
    _add_string(attributes, "langfuse.trace.metadata.ontology_id", trace.get("ontology_id"))
    if trace.get("session_id"):
        _add_string(attributes, "langfuse.session.id", trace["session_id"])
    if trace.get("ontology_id"):
        _add_string(attributes, "langfuse.observation.metadata.ontology_id", trace["ontology_id"])
    _add_json(attributes, "langfuse.observation.input", span.get("input_text"))
    _add_json(attributes, "langfuse.observation.output", span.get("output_text"))
    if span.get("tool_name"):
        _add_string(attributes, "langfuse.observation.metadata.tool_name", span["tool_name"])
    if span.get("tool_params") is not None:
        _add_json(attributes, "langfuse.observation.metadata.tool_params", span["tool_params"])
    if span.get("model"):
        _add_string(attributes, "langfuse.observation.model.name", span["model"])
    usage = _usage_details(span)
    if usage:
        _add_json(attributes, "langfuse.observation.usage_details", usage)

    return {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": parent_span_id,
        "name": span.get("action") or span.get("tool_name") or trace_name,
        "kind": 1,
        "startTimeUnixNano": _unix_nano(span.get("ts_start", trace.get("ts_start"))),
        "endTimeUnixNano": _unix_nano(span.get("ts_end", trace.get("ts_start"))),
        "attributes": attributes,
    }


def _observation_type(span: dict) -> str:
    if span.get("kind") in {"tool", "action"}:
        return "tool"
    if span.get("kind") == "generation":
        return "generation"
    if span.get("kind") == "retrieval":
        return "retriever"
    if span.get("kind") == "guardrail":
        return "guardrail"
    return "span"


def _usage_details(span: dict) -> dict | None:
    values = {
        "input": span.get("tokens_prompt"),
        "output": span.get("tokens_completion"),
        "cacheRead": span.get("tokens_cache_read"),
        "cacheWrite": span.get("tokens_cache_write"),
    }
    return {key: value for key, value in values.items() if value is not None} or None


def _add_string(attributes: list, key: str, value) -> None:
    if value is not None:
        attributes.append({"key": key, "value": {"stringValue": str(value)}})


def _add_json(attributes: list, key: str, value) -> None:
    if value is None:
        return
    encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    _add_string(attributes, key, encoded)


def _hex_id(value: str, length: int, field: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) < length or any(character not in "0123456789abcdef" for character in normalized.lower()):
        raise ValueError(f"Langfuse OTLP {field} must be a hexadecimal id of at least {length} characters")
    return normalized.lower()[:length]


def _unix_nano(value) -> str:
    if value is None:
        raise ValueError("Langfuse OTLP span timestamps are required")
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return str(int(parsed.timestamp() * 1_000_000_000))


def _decode_response(body: str) -> dict:
    if not body.strip():
        return {}
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError("Langfuse OTLP ingestion returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Langfuse OTLP ingestion response must be a JSON object")
    return value
