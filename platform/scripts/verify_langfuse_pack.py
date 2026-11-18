import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a Langfuse verification pack with a Run")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--db", default=str(ROOT / "platform" / "var" / "traj-engine.db"))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    try:
        run = connection.execute(
            "SELECT id, run_type, status, window_start, window_end, created_at, ended_at "
            "FROM cohort_runs WHERE id = ?",
            (args.run_id,),
        ).fetchone()
        if run is None:
            raise SystemExit(f"run not found: {args.run_id}")

        anomaly_rows = _score_rows(
            connection,
            args.run_id,
            [item["traceId"] for item in manifest["anomalies"]],
        )
        normal_rows = _score_rows(
            connection,
            args.run_id,
            manifest["normalTraceIds"],
        )
        anomalies = []
        for expected in manifest["anomalies"]:
            score = anomaly_rows.get(expected["traceId"])
            anomalies.append({
                **expected,
                "found": score is not None,
                "detected": bool(score and score["is_alert"]),
                "abstained": bool(score and score["is_abstain"]),
                "totalScore": score["total_score"] if score else None,
                "alertStatus": score["alert_status"] if score else None,
            })
        false_positives = [
            {
                "traceId": row["trace_id"],
                "totalScore": row["total_score"],
                "alertStatus": row["alert_status"],
            }
            for row in normal_rows.values()
            if row["is_alert"]
        ]
        report = {
            "manifest": str(manifest_path),
            "run": dict(run),
            "summary": {
                "normalCount": len(normal_rows),
                "anomalyCount": len(anomalies),
                "detectedAnomalyCount": sum(item["detected"] for item in anomalies),
                "abstainedAnomalyCount": sum(item["abstained"] for item in anomalies),
                "missedAnomalyCount": sum(
                    item["found"] and not item["detected"] and not item["abstained"]
                    for item in anomalies
                ),
                "normalFalsePositiveCount": len(false_positives),
                "anomalyRecall": (
                    sum(item["detected"] for item in anomalies) / len(anomalies)
                    if anomalies else None
                ),
            },
            "anomalies": anomalies,
            "normalFalsePositives": false_positives,
        }
    finally:
        connection.close()

    output = Path(args.output) if args.output else (
        ROOT / "platform" / "var" / "verification" / f"result-{args.run_id}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(output),
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


def _score_rows(connection: sqlite3.Connection, run_id: str, trace_ids: list[str]) -> dict[str, dict]:
    if not trace_ids:
        return {}
    placeholders = ",".join("?" for _ in trace_ids)
    rows = connection.execute(
        f"""SELECT ts.trace_id, ts.total_score, ts.is_alert, ts.is_abstain,
                   ad.status AS alert_status
            FROM trace_scores AS ts
            LEFT JOIN alert_decisions AS ad ON ad.trace_score_id = ts.id
            WHERE ts.run_id = ? AND ts.trace_id IN ({placeholders})""",
        [run_id, *trace_ids],
    ).fetchall()
    return {row["trace_id"]: dict(row) for row in rows}


if __name__ == "__main__":
    sys.exit(main())
