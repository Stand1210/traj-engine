import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app.config import load_endpoints, load_profile
from platform.app.langfuse_ingestion import LangfuseOTLPTraceIngestor
from platform.app.langfuse_source import LangfuseTraceSource
from platform.scripts.langfuse_benchmark_import import normalize_trace_for_langfuse


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a labeled verification pack into Langfuse")
    parser.add_argument("--profile", default="cloud-v4", choices=["cloud-v4", "selfhosted-v4"])
    parser.add_argument("--regime", default="R1")
    parser.add_argument("--normal-count", type=int, default=180)
    parser.add_argument("--anomaly-count", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--wait-seconds", type=float, default=60.0)
    parser.add_argument("--spread-seconds", type=int, default=1800)
    parser.add_argument("--id-offset", type=int, default=500000000000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if args.normal_count < 0 or args.anomaly_count < 1:
        raise SystemExit("--normal-count must be non-negative and --anomaly-count must be positive")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")

    selected = select_traces(args.regime, args.normal_count, args.anomaly_count)
    now = int(time.time())
    imported = [
        normalize_trace_for_langfuse(
            item["trace"], index, now, args.spread_seconds, len(selected), args.id_offset
        )
        for index, item in enumerate(selected)
    ]
    manifest = {
        "profile": args.profile,
        "regime": args.regime,
        "submittedAt": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "normalCount": args.normal_count,
        "anomalyCount": args.anomaly_count,
        "spreadSeconds": args.spread_seconds,
        "idOffset": args.id_offset,
        "normalTraceIds": [trace["trace_id"] for trace in imported[: args.normal_count]],
        "anomalies": [
            {
                "traceId": trace["trace_id"],
                "benchmarkTraceId": item["benchmark_trace_id"],
                "anomalyTypes": item["anomaly_types"],
            }
            for trace, item in zip(imported[args.normal_count:], selected[args.normal_count:])
        ],
    }

    keys = {
        "publicKey": os.environ.get("LANGFUSE_PUBLIC_KEY"),
        "secretKey": os.environ.get("LANGFUSE_SECRET_KEY"),
    }
    if not args.dry_run:
        if not keys["publicKey"] or not keys["secretKey"]:
            raise SystemExit("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")
        profile = load_profile(args.profile)
        endpoints = load_endpoints()
        ingestor = LangfuseOTLPTraceIngestor.from_config(profile, endpoints, keys)
        accepted = 0
        for start in range(0, len(imported), args.batch_size):
            batch = imported[start : start + args.batch_size]
            result = ingestor.ingest_many(batch)
            accepted += result["traces"]
            print({"accepted": accepted, "total": len(imported), "batch": result})
        if args.wait_seconds:
            time.sleep(args.wait_seconds)

        source = LangfuseTraceSource.from_config(
            profile, endpoints, keys, page_size=1000, max_traces=len(imported)
        )
        window = {
            "start": datetime.fromtimestamp(now - args.spread_seconds - 1, timezone.utc),
            "end": datetime.fromtimestamp(now + 60, timezone.utc),
        }
        readback = list(source.list_traces(window, {}))
        expected_ids = {trace["trace_id"] for trace in imported}
        matched = [trace for trace in readback if trace["trace_id"] in expected_ids]
        manifest["ingestion"] = {
            "accepted": accepted,
            "readback": len(matched),
            "window": {
                "start": window["start"].isoformat(),
                "end": window["end"].isoformat(),
            },
        }
    else:
        manifest["ingestion"] = {"dryRun": True}

    output = Path(args.output) if args.output else (
        ROOT / "platform" / "var" / "verification" / f"langfuse-pack-{now}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"manifest": str(output), "manifestSummary": {
        "normal": manifest["normalCount"],
        "anomalies": len(manifest["anomalies"]),
        "ingestion": manifest["ingestion"],
    }})
    if not args.dry_run and manifest["ingestion"]["readback"] != len(imported):
        return 1
    return 0


def select_traces(regime: str, normal_count: int, anomaly_count: int) -> list[dict]:
    base = ROOT / "data" / "bench_v1" / regime
    ground_truth_path = base / "gt.jsonl"
    traces_path = base / "traces.jsonl"
    if not ground_truth_path.exists() or not traces_path.exists():
        raise SystemExit(f"benchmark regime not found: {base}")

    ground_truth = []
    with ground_truth_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                ground_truth.append(json.loads(line))
    traces = {}
    with traces_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                trace = json.loads(line)
                traces[trace["trace_id"]] = trace

    normal_rows = [row for row in ground_truth if not row.get("is_anomaly")]
    anomaly_rows = [row for row in ground_truth if row.get("is_anomaly")]
    if len(normal_rows) < normal_count or len(anomaly_rows) < anomaly_count:
        raise SystemExit("benchmark does not contain enough labeled traces")

    anomalies_by_type = defaultdict(list)
    for row in anomaly_rows:
        for anomaly_type in row.get("anomaly_types") or ["unspecified"]:
            anomalies_by_type[anomaly_type].append(row)
    selected_anomalies = []
    available_types = sorted(anomalies_by_type)
    while len(selected_anomalies) < anomaly_count:
        progressed = False
        for anomaly_type in available_types:
            rows = anomalies_by_type[anomaly_type]
            if rows and len(selected_anomalies) < anomaly_count:
                selected_anomalies.append((rows.pop(0), anomaly_type))
                progressed = True
        if not progressed:
            break

    selected = [
        {"benchmark_trace_id": row["trace_id"], "anomaly_types": row.get("anomaly_types") or [], "trace": traces[row["trace_id"]]}
        for row in normal_rows[:normal_count]
    ]
    selected.extend(
        {
            "benchmark_trace_id": row["trace_id"],
            "anomaly_types": row.get("anomaly_types") or [],
            "trace": traces[row["trace_id"]],
        }
        for row, _ in selected_anomalies
    )
    missing = [item for item in selected if item["trace"] is None]
    if missing:
        raise SystemExit(f"benchmark trace rows missing: {[item['benchmark_trace_id'] for item in missing]}")
    return selected


if __name__ == "__main__":
    raise SystemExit(main())
