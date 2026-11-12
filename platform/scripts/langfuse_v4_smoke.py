import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app.config import load_endpoints, load_profile
from platform.app.langfuse_ingestion import LangfuseOTLPTraceIngestor
from platform.app.langfuse_source import LangfuseTraceSource


def build_trace(trace_id: str, started_at: int) -> dict:
    return {
        "trace_id": trace_id,
        "session_id": "traj-dev-session",
        "ontology_id": "ontology-dev",
        "intent_text": "traj-engine-dev",
        "ts_start": started_at,
        "spans": [
            {
                "span_id": "0123456789abcdef",
                "parent_id": None,
                "action": "traj-engine-dev-root",
                "kind": "agent",
                "input_text": {"query": "langfuse v4 connectivity smoke"},
                "output_text": {"answer": "ok"},
                "ts_start": started_at,
                "ts_end": started_at + 3,
            },
            {
                "span_id": "fedcba9876543210",
                "parent_id": "0123456789abcdef",
                "action": "api_call",
                "kind": "tool",
                "tool_name": "nbi.alarm_list",
                "tool_params": {"ne_id": "NE-1"},
                "ts_start": started_at + 1,
                "ts_end": started_at + 2,
            },
            {
                "span_id": "1111111111111111",
                "parent_id": "0123456789abcdef",
                "action": "generate_summary",
                "kind": "generation",
                "model": "traj-test-model",
                "tokens_prompt": 10,
                "tokens_completion": 3,
                "ts_start": started_at + 2,
                "ts_end": started_at + 3,
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed and read back one Langfuse v4 development trace")
    parser.add_argument("--profile", default="cloud-v4", choices=["cloud-v4", "selfhosted-v4"])
    parser.add_argument("--trace-id", default="0123456789abcdef0123456789abcdef")
    parser.add_argument("--wait-seconds", type=float, default=3.0)
    args = parser.parse_args()

    profile = load_profile(args.profile)
    endpoints = load_endpoints()
    keys = {
        "publicKey": os.environ.get("LANGFUSE_PUBLIC_KEY"),
        "secretKey": os.environ.get("LANGFUSE_SECRET_KEY"),
    }
    if not keys["publicKey"] or not keys["secretKey"]:
        raise SystemExit("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")

    started_at = int(time.time())
    trace = build_trace(args.trace_id, started_at)
    ingestor = LangfuseOTLPTraceIngestor.from_config(profile, endpoints, keys)
    result = ingestor.ingest(trace)

    if args.wait_seconds:
        time.sleep(args.wait_seconds)

    source = LangfuseTraceSource.from_config(profile, endpoints, keys, page_size=50)
    window = {
        "start": datetime.fromtimestamp(started_at - 1, tz=timezone.utc),
        "end": datetime.fromtimestamp(started_at + 10, tz=timezone.utc),
    }
    traces = list(source.list_traces(window, {}))
    selected = [item for item in traces if item["trace_id"] == args.trace_id]
    if len(selected) != 1:
        raise SystemExit(
            f"read-back verification failed: expected 1 trace, got {len(selected)} "
            f"(observations={source.traversal.get('observations')}, pages={source.traversal.get('pages')})"
        )

    selected_trace = selected[0]
    print(result)
    print(
        {
            "trace_id": selected_trace["trace_id"],
            "ontology_id": selected_trace["ontology_id"],
            "session_id": selected_trace["session_id"],
            "intent_text": selected_trace["intent_text"],
            "span_kinds": [span["kind"] for span in selected_trace["spans"]],
            "span_actions": [span["action"] for span in selected_trace["spans"]],
            "tool_names": [span["tool_name"] for span in selected_trace["spans"]],
            "models": [span["model"] for span in selected_trace["spans"]],
            "prompt_tokens": [span["tokens_prompt"] for span in selected_trace["spans"]],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
