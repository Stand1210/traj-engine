import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app.config import load_endpoints, load_profile
from platform.app.langfuse_ingestion import LangfuseOTLPTraceIngestor
from platform.app.langfuse_source import LangfuseTraceSource


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a benchmark subset into Langfuse v4")
    parser.add_argument("--profile", default="cloud-v4", choices=["cloud-v4", "selfhosted-v4"])
    parser.add_argument("--regime", default="R1")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--wait-seconds", type=float, default=30.0)
    parser.add_argument("--spread-seconds", type=int, default=3600)
    parser.add_argument("--id-offset", type=int, default=0)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()
    if args.count < 1 or args.batch_size < 1:
        raise SystemExit("--count and --batch-size must be positive")

    profile = load_profile(args.profile)
    endpoints = load_endpoints()
    keys = {
        "publicKey": os.environ.get("LANGFUSE_PUBLIC_KEY"),
        "secretKey": os.environ.get("LANGFUSE_SECRET_KEY"),
    }
    if not keys["publicKey"] or not keys["secretKey"]:
        raise SystemExit("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")

    now = int(time.time())
    if args.verify_only:
        if not args.start or not args.end:
            raise SystemExit("--verify-only requires --start and --end")
        start_time = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        expected_ids = {f"{args.id_offset + index:032x}" for index in range(args.count)}
        accepted = args.count
    else:
        traces = load_benchmark_traces(args.regime, args.count)
        imported = [
            normalize_trace_for_langfuse(
                trace, index, now, args.spread_seconds, args.count, args.id_offset
            )
            for index, trace in enumerate(traces)
        ]
        ingestor = LangfuseOTLPTraceIngestor.from_config(profile, endpoints, keys)
        accepted = 0
        for start in range(0, len(imported), args.batch_size):
            batch = imported[start : start + args.batch_size]
            result = ingestor.ingest_many(batch)
            accepted += result["traces"]
            print({"accepted": accepted, "total": len(imported), "batch": result})

        if args.wait_seconds:
            time.sleep(args.wait_seconds)
        start_time = datetime.fromtimestamp(now - args.spread_seconds - 1, tz=timezone.utc)
        end_time = datetime.fromtimestamp(now + 60, tz=timezone.utc)
        expected_ids = {trace["trace_id"] for trace in imported}

    source = LangfuseTraceSource.from_config(
        profile,
        endpoints,
        keys,
        page_size=1000,
        max_traces=None if args.verify_only else args.count,
    )
    window = {"start": start_time, "end": end_time}
    readback = list(source.list_traces(window, {}))
    matched = [trace for trace in readback if trace["trace_id"] in expected_ids]
    print(
        {
            "submitted": args.count,
            "accepted": accepted,
            "readback": len(matched),
            "observations": source.traversal.get("observations"),
            "pages": source.traversal.get("pages"),
            "window": {
                "start": window["start"].isoformat(),
                "end": window["end"].isoformat(),
            },
            "sample_expected": sorted(expected_ids)[:3],
            "sample_readback": [trace["trace_id"] for trace in readback[:3]],
        }
    )
    return 0 if len(matched) == args.count else 1


def load_benchmark_traces(regime: str, count: int) -> list[dict]:
    path = ROOT / "data" / "bench_v1" / regime / "traces.jsonl"
    if not path.exists():
        raise SystemExit(f"benchmark traces not found: {path}")
    traces = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                traces.append(json.loads(line))
            if len(traces) == count:
                break
    if len(traces) < count:
        raise SystemExit(f"benchmark has only {len(traces)} traces, requested {count}")
    return traces


def normalize_trace_for_langfuse(
    trace: dict,
    index: int,
    now: int,
    spread_seconds: int,
    total: int,
    id_offset: int,
) -> dict:
    base_time = now - spread_seconds + int(index * spread_seconds / max(1, total))
    original_start = trace.get("ts_start") or min(
        span.get("ts_start", 0.0) for span in trace.get("spans", [])
    )
    identity = id_offset + index
    trace_id = f"{identity:032x}"
    root_span_id = f"{identity:016x}"
    spans = []
    for span_index, span in enumerate(trace.get("spans", [])):
        span_id = root_span_id if span_index == 0 else f"{identity:014x}{span_index:02x}"
        normalized = dict(span)
        normalized["span_id"] = span_id
        normalized["parent_id"] = None if span.get("parent_id") is None else root_span_id
        normalized["ts_start"] = base_time + float(span.get("ts_start", original_start) - original_start)
        normalized["ts_end"] = base_time + float(span.get("ts_end", original_start) - original_start)
        spans.append(normalized)
    normalized = {
        "trace_id": trace_id,
        "session_id": trace.get("session_id") or f"benchmark-{index // 50}",
        "ontology_id": "ontology-dev",
        "intent_text": trace.get("intent_text"),
        "ts_start": base_time,
        "spans": spans,
    }
    for key in (
        "answer_citations",
        "answer_facts",
        "answer_numbers",
        "contradicted_facts",
        "golden_answer",
        "golden_facts",
        "goal_text",
        "query_lang",
        "raw_flags",
        "session_turn_count",
        "turn_index",
        "user_feedback",
    ):
        normalized[key] = trace.get(key)
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
