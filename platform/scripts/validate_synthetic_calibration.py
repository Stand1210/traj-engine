import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException

from platform.app import store
from platform.app.service import (
    CalibrationTriggerInput,
    _alert_decisions,
    activate_calibration,
    trigger_review_calibration,
)


REVIEWER = "synthetic-benchmark"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the M3.4 calibration loop with deterministic synthetic labels."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--db-path", default=str(ROOT / "platform" / "var" / "traj-engine.db"))
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    connection = store.connect(args.db_path, initialize=True)
    try:
        run = store.get_run(connection, args.run_id)
        if run is None:
            raise SystemExit(f"run not found: {args.run_id}")

        connection.execute(
            """UPDATE review_calibrations SET activated_at = NULL
               WHERE tenant_id = ? AND source_run_id = ?""",
            (run["tenant_id"], args.run_id),
        )
        connection.commit()
        before = _alert_decisions(connection, args.run_id, None)
        decisions_by_id = {item["trace_score_id"]: item for item in before}
        labels = _build_labels(before)
        if len(labels) < args.count:
            raise SystemExit(f"only {len(labels)} synthetic labels available")
        labels = labels[:args.count]

        if args.dry_run:
            print(json.dumps({"runId": args.run_id, "labels": labels}, ensure_ascii=False, indent=2))
            return 0

        connection.execute(
            """DELETE FROM human_reviews
               WHERE reviewer = ?
                 AND trace_score_id IN (
                     SELECT id FROM trace_scores WHERE run_id = ?
                 )""",
            (REVIEWER, args.run_id),
        )
        for index, label in enumerate(labels, start=1):
            review_id = f"synthetic-review-{index:03d}"
            connection.execute(
                """INSERT INTO human_reviews
                   (id, trace_score_id, reviewer, verdict, label, comment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id,
                    label["trace_score_id"],
                    REVIEWER,
                    label["verdict"],
                    "synthetic",
                    "generated-from-alert-workflow; development validation only",
                    store.utcnow(),
                ),
            )
        connection.commit()

        calibration = trigger_review_calibration(
            args.run_id,
            CalibrationTriggerInput(createdBy=REVIEWER),
            connection,
        )
        activated = activate_calibration(calibration["id"], connection)
        after = _alert_decisions(connection, args.run_id, None)

        before_map = {item["trace_score_id"]: item["priority"] for item in before}
        changed = [
            {
                "trace_score_id": item["trace_score_id"],
                "cause": item["cause"],
                "before": before_map[item["trace_score_id"]],
                "after": item["priority"],
            }
            for item in after
            if abs(before_map[item["trace_score_id"]] - item["priority"]) > 1e-9
        ]
        result = {
            "runId": args.run_id,
            "labelCount": len(labels),
            "formalAlertsReviewed": sum(
                1 for label in labels
                if decisions_by_id[label["trace_score_id"]]["status"] == "alerted"
            ),
            "calibrationId": calibration["id"],
            "activatedAt": activated["activatedAt"],
            "alertPrecision": calibration["alertPrecision"],
            "ece": calibration["ece"],
            "brier": calibration["brier"],
            "causeSeverityAdjustments": calibration["parameters"][
                "causeSeverityAdjustments"
            ],
            "changedPriorities": changed,
        }
        assert result["labelCount"] == args.count
        assert result["formalAlertsReviewed"] >= 5
        assert calibration["labelCount"] == args.count
        assert activated["activatedAt"] is not None
        assert changed, "active calibration did not change alert priority"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except HTTPException as error:
        print(json.dumps(error.detail, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        connection.close()


def _build_labels(decisions: list[dict]) -> list[dict]:
    labels: list[dict] = []
    for decision in decisions:
        labels.append({
            "trace_score_id": decision["trace_score_id"],
            "verdict": "agree" if decision["status"] == "alerted" else "disagree",
        })

    return labels


if __name__ == "__main__":
    raise SystemExit(main())
