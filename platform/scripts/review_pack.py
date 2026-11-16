import argparse
import csv
import json
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app import store
from platform.app.calibration import (
    activate_review_calibration,
    create_review_calibration,
    serialize_review_calibration,
)
from platform.app.config import load_calibration_config


CSV_FIELDS = [
    "traceScoreId",
    "traceId",
    "alertStatus",
    "priorityRank",
    "priority",
    "cause",
    "totalScore",
    "resultScore",
    "processScore",
    "latencyScore",
    "costScore",
    "robustnessScore",
    "reasons",
    "evidence",
    "verdict",
    "reviewer",
    "label",
    "comment",
]


class ReviewPackError(RuntimeError):
    pass


def export_review_pack(
    db_path: str | Path,
    run_id: str,
    output_path: str | Path,
) -> dict:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with closing(store.connect(db_path, initialize=True)) as connection:
        run = store.get_run(connection, run_id)
        if run is None:
            raise ReviewPackError(f"run not found: {run_id}")

        rows = connection.execute(
            """SELECT s.id AS trace_score_id, s.trace_id, s.total_score,
                      s.result_score, s.process_score, s.latency_score,
                      s.cost_score, s.robustness_score,
                      d.status AS alert_status, d.priority, d.priority_rank,
                      d.cause, d.reasons_json
               FROM trace_scores s
               JOIN alert_decisions d ON d.trace_score_id = s.id
               WHERE s.run_id = ? AND s.is_alert = 1
               ORDER BY d.priority_rank, s.total_score, s.trace_id""",
            (run_id,),
        ).fetchall()
        if not rows:
            raise ReviewPackError(f"run has no alert scores to review: {run_id}")

        evidence_by_score = _evidence_by_score(connection, run_id)

    csv_rows = []
    for row in rows:
        evidence = evidence_by_score.get(row["trace_score_id"], [])
        csv_rows.append({
            "traceScoreId": row["trace_score_id"],
            "traceId": row["trace_id"],
            "alertStatus": row["alert_status"] or "candidate",
            "priorityRank": row["priority_rank"] or "",
            "priority": _format_number(row["priority"]),
            "cause": row["cause"] or "",
            "totalScore": _format_number(row["total_score"]),
            "resultScore": _format_number(row["result_score"]),
            "processScore": _format_number(row["process_score"]),
            "latencyScore": _format_number(row["latency_score"]),
            "costScore": _format_number(row["cost_score"]),
            "robustnessScore": _format_number(row["robustness_score"]),
            "reasons": _format_reasons(row["reasons_json"]),
            "evidence": _format_evidence(evidence),
            "verdict": "",
            "reviewer": "",
            "label": "",
            "comment": "",
        })

    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(csv_rows)

    markdown_path = output.with_suffix(".md")
    markdown_path.write_text(
        _render_markdown(run, csv_rows),
        encoding="utf-8",
    )
    return {
        "runId": run_id,
        "reviewCount": len(csv_rows),
        "csvPath": str(output),
        "markdownPath": str(markdown_path),
    }


def import_review_pack(
    db_path: str | Path,
    run_id: str,
    csv_path: str | Path,
    *,
    reviewer: str,
    trigger_calibration: bool = False,
    activate: bool = False,
) -> dict:
    if not reviewer.strip():
        raise ReviewPackError("reviewer is required")
    input_path = Path(csv_path)
    if not input_path.is_file():
        raise ReviewPackError(f"review pack does not exist: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ReviewPackError("review pack is empty")

    imported = 0
    verdict_counts = {"agree": 0, "disagree": 0, "uncertain": 0}
    with closing(store.connect(db_path, initialize=True)) as connection:
        run = store.get_run(connection, run_id)
        if run is None:
            raise ReviewPackError(f"run not found: {run_id}")

        connection.execute(
            """DELETE FROM human_reviews
               WHERE reviewer = ?
                 AND trace_score_id IN (
                     SELECT id FROM trace_scores WHERE run_id = ?
                 )""",
            (reviewer, run_id),
        )

        for row in rows:
            score_id = row.get("traceScoreId", "").strip()
            verdict = row.get("verdict", "").strip().lower()
            if not score_id:
                raise ReviewPackError("a review row is missing traceScoreId")
            if verdict not in verdict_counts:
                raise ReviewPackError(
                    f"invalid verdict for score {score_id}: {verdict or '<empty>'}"
                )
            score = connection.execute(
                "SELECT id FROM trace_scores WHERE id = ? AND run_id = ?",
                (score_id, run_id),
            ).fetchone()
            if score is None:
                raise ReviewPackError(f"score does not belong to run: {score_id}")

            review_id = store.new_id("review")
            connection.execute(
                """INSERT INTO human_reviews
                   (id, trace_score_id, reviewer, verdict, label, comment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id,
                    score_id,
                    reviewer,
                    verdict,
                    row.get("label", "").strip() or None,
                    row.get("comment", "").strip() or None,
                    store.utcnow(),
                ),
            )
            verdict_counts[verdict] += 1
            imported += 1
        connection.commit()

        calibration = None
        calibration_error = None
        if trigger_calibration:
            try:
                calibration_row = create_review_calibration(
                    connection,
                    run_id,
                    reviewer,
                    load_calibration_config(),
                )
                if activate:
                    calibration_row = activate_review_calibration(
                        connection,
                        calibration_row["id"],
                    )
                calibration = serialize_review_calibration(calibration_row)
            except ValueError as error:
                calibration_error = str(error)

    return {
        "runId": run_id,
        "imported": imported,
        "reviewer": reviewer,
        "verdictCounts": verdict_counts,
        "calibration": calibration,
        "calibrationError": calibration_error,
    }


def _evidence_by_score(connection, run_id: str) -> dict[str, list[dict]]:
    rows = connection.execute(
        """SELECT e.trace_score_id, e.dimension, e.span_id,
                  e.contribution, e.explanation
           FROM score_evidence e
           JOIN trace_scores s ON s.id = e.trace_score_id
           WHERE s.run_id = ?
           ORDER BY e.trace_score_id, e.contribution, e.dimension""",
        (run_id,),
    ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["trace_score_id"], []).append(dict(row))
    return grouped


def _format_reasons(value: str | None) -> str:
    if not value:
        return ""
    try:
        reasons = json.loads(value)
    except json.JSONDecodeError:
        return value
    return "；".join(str(item) for item in reasons)


def _format_evidence(items: list[dict]) -> str:
    significant = [
        item for item in items
        if abs(float(item["contribution"])) >= 0.000001
    ]
    return "；".join(
        f"{item['dimension']}={float(item['contribution']):.4f}"
        for item in significant
    )


def _format_number(value) -> str:
    return "" if value is None else f"{float(value):.4f}"


def _render_markdown(run: dict, rows: list[dict]) -> str:
    lines = [
        "# M7.1 人工复核包",
        "",
        f"- Run：`{run['id']}`",
        f"- 类型：{run['run_type']}，状态：{run['status']}",
        f"- 时间窗：{run['window_start']} ~ {run['window_end']}",
        f"- 复核条数：{len(rows)}",
        "",
        "## 填写说明",
        "",
        "- 在 CSV 的 `verdict` 列填写 `agree`、`disagree` 或 `uncertain`。",
        "- `agree`：算法判断与业务判断一致。",
        "- `disagree`：算法判断与业务判断不一致，必须在 `comment` 写明原因。",
        "- `uncertain`：业务证据不足，说明缺少什么上下文。",
        "- `label` 可填写简短业务结论，例如 `real_failure`、`false_alarm`。",
        "- 不要修改 `traceScoreId`、`traceId` 与算法输出列。",
        "",
        "## 复核清单",
        "",
        "| # | Trace | 状态 | 原因 | 总分 | 结论 |",
        "|---:|---|---|---|---:|---|",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"| {index} | `{row['traceId']}` | {row['alertStatus']} | "
            f"{row['cause']} | {row['totalScore']} | {row['verdict'] or '待填写'} |"
        )
    lines.extend([
        "",
        "## 导入命令",
        "",
        "```powershell",
        "python platform/scripts/review_pack.py --db platform/var/traj-engine.db import `",
        f"  --run-id {run['id']} --csv <filled-review-pack.csv> --reviewer <reviewer>",
        "```",
        "",
        "达到 20 条标签后可追加 `--trigger-calibration --activate`。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export and import M7.1 review packs")
    parser.add_argument(
        "--db",
        default=str(ROOT / "platform" / "var" / "traj-engine.db"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="export a review pack")
    export_parser.add_argument("--run-id", required=True)
    export_parser.add_argument("--output", required=True)

    import_parser = subparsers.add_parser("import", help="import a filled review pack")
    import_parser.add_argument("--run-id", required=True)
    import_parser.add_argument("--csv", required=True)
    import_parser.add_argument("--reviewer", required=True)
    import_parser.add_argument("--trigger-calibration", action="store_true")
    import_parser.add_argument("--activate", action="store_true")

    args = parser.parse_args()
    if args.command == "export":
        result = export_review_pack(args.db, args.run_id, args.output)
    else:
        if args.activate and not args.trigger_calibration:
            parser.error("--activate requires --trigger-calibration")
        result = import_review_pack(
            args.db,
            args.run_id,
            args.csv,
            reviewer=args.reviewer,
            trigger_calibration=args.trigger_calibration,
            activate=args.activate,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
