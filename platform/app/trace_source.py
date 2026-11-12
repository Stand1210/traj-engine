import json
import random
from datetime import datetime
from pathlib import Path
from typing import Iterator, Protocol


ROOT = Path(__file__).resolve().parents[2]
BENCH_ROOT = ROOT / "data" / "bench_v1"
TRACE_KEYS = {
    "answer_citations", "answer_facts", "answer_numbers", "contradicted_facts",
    "embedding", "goal_text", "golden_answer", "golden_facts", "intent_text",
    "ontology_id", "query_lang", "raw_flags", "session_id", "session_turn_count",
    "spans", "trace_id", "ts_start", "turn_index", "user_feedback",
}
SPAN_KEYS = {
    "action", "arg_valid", "cost", "cost_details", "finish_reason", "input_text",
    "kind", "level", "model", "output_citations", "output_facts", "output_text",
    "parent_id", "prompt_version", "span_id", "status", "status_message",
    "subgoal_text", "tokens_cache_read", "tokens_cache_write", "tokens_completion",
    "tokens_prompt", "tokens_system_prompt", "tool_name", "tool_params",
    "ts_end", "ts_start", "ttft", "verifier",
}


class TraceSource(Protocol):
    source_type: str

    def list_traces(self, window: dict, sampling: dict) -> Iterator[dict]:
        ...


class JsonlTraceSource:
    source_type = "jsonl"

    def __init__(self, regime_id: str, data_root: Path = BENCH_ROOT, limit: int | None = None):
        self.regime_id = regime_id
        self.data_root = Path(data_root)
        self.limit = limit

    def list_traces(self, window: dict, sampling: dict) -> Iterator[dict]:
        path = self.data_root / self.regime_id / "traces.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"benchmark traces not found: {path}")

        selected: list[dict] = []
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    trace = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid JSON at {path}:{line_number}") from error
                validate_trace(trace, path, line_number)
                if self._in_window(trace, window):
                    selected.append(trace)

        rate = float(sampling.get("rate", 1.0))
        strategy = sampling.get("strategy", "systematic")
        if rate <= 0 or rate > 1:
            raise ValueError("sampling rate must be in (0, 1]")
        if rate < 1:
            if strategy == "random":
                seed = int(sampling.get("seed", 0))
                take = max(1, round(len(selected) * rate))
                selected = random.Random(seed).sample(selected, take)
            else:
                stride = max(1, round(1 / rate))
                selected = selected[::stride]

        if self.limit is not None:
            selected = selected[: self.limit]
        yield from selected

    def _in_window(self, trace: dict, window: dict) -> bool:
        start = window.get("start")
        end = window.get("end")
        timestamp = trace.get("ts_start")
        if timestamp is None:
            return True
        start_value = to_epoch(start)
        end_value = to_epoch(end)
        if start_value is not None and timestamp < start_value:
            return False
        if end_value is not None and timestamp > end_value:
            return False
        return True


def validate_trace(trace: dict, path: Path, line_number: int) -> None:
    trace_id = trace.get("trace_id", f"line-{line_number}")
    missing = TRACE_KEYS - set(trace)
    extra = set(trace) - TRACE_KEYS
    if missing or extra:
        raise ValueError(
            f"invalid trace contract at {path}:{line_number} trace={trace_id} "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    spans = trace.get("spans")
    if not isinstance(spans, list):
        raise ValueError(f"spans must be a list: {path}:{line_number} trace={trace_id}")
    for span in spans:
        missing = SPAN_KEYS - set(span)
        extra = set(span) - SPAN_KEYS
        if missing or extra:
            raise ValueError(
                f"invalid span contract at {path}:{line_number} trace={trace_id} "
                f"span={span.get('span_id')} missing={sorted(missing)} extra={sorted(extra)}"
            )


def to_epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.timestamp()
