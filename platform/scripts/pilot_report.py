import argparse
import json
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app import store
from platform.app.config import load_alert_config


class PilotReportError(RuntimeError):
    pass


def build_pilot_report(db_path: str | Path, run_id: str | None = None) -> dict:
    with closing(store.connect(db_path, initialize=True)) as connection:
        run = _select_run(connection, run_id)
        run_id = run["id"]
        tenant = connection.execute(
            "SELECT * FROM tenants WHERE id = ?", (run["tenant_id"],)
        ).fetchone()
        ontology = connection.execute(
            "SELECT * FROM ontologies WHERE id = ?", (run["ontology_id"],)
        ).fetchone()

        score_summary = connection.execute(
            """SELECT COUNT(*) AS trace_count,
                      AVG(total_score) AS average_score,
                      MIN(total_score) AS minimum_score,
                      MAX(total_score) AS maximum_score,
                      SUM(is_abstain) AS abstain_count,
                      SUM(is_alert) AS alert_count,
                      MAX(ABS(deduction_total - evidence_sum)) AS max_evidence_residual
               FROM trace_scores WHERE run_id = ?""",
            (run_id,),
        ).fetchone()
        if score_summary["trace_count"] == 0:
            raise PilotReportError(f"run has no trace scores: {run_id}")

        cells = connection.execute(
            """SELECT cell_key, label, dominant_action, size
               FROM cells WHERE run_id = ? ORDER BY size DESC""",
            (run_id,),
        ).fetchall()

        alert_counts = connection.execute(
            """SELECT status, COUNT(*) AS count
               FROM alert_decisions WHERE run_id = ? GROUP BY status""",
            (run_id,),
        ).fetchall()
        alert_status_counts = {row["status"]: row["count"] for row in alert_counts}
        alerted_count = alert_status_counts.get("alerted", 0)

        review_counts = connection.execute(
            """SELECT r.verdict, COUNT(*) AS count
               FROM human_reviews r
               JOIN trace_scores s ON s.id = r.trace_score_id
               WHERE s.run_id = ? GROUP BY r.verdict""",
            (run_id,),
        ).fetchall()
        review_verdicts = {row["verdict"]: row["count"] for row in review_counts}
        review_count = sum(review_verdicts.values())

        active_calibration = connection.execute(
            """SELECT id, label_count, alert_precision, ece, brier,
                      activated_at, created_by
               FROM review_calibrations
               WHERE source_run_id = ? AND activated_at IS NOT NULL
               ORDER BY activated_at DESC LIMIT 1""",
            (run_id,),
        ).fetchone()

        top_alerts = connection.execute(
            """SELECT s.trace_id, d.cause, d.cause_kind, d.status,
                      d.priority, d.priority_rank
               FROM alert_decisions d
               JOIN trace_scores s ON s.id = d.trace_score_id
               WHERE d.run_id = ? AND d.status = 'alerted'
               ORDER BY d.priority_rank LIMIT 10""",
            (run_id,),
        ).fetchall()

        lifecycle_evaluations = connection.execute(
            """SELECT decision, reason, COUNT(*) AS count
               FROM lifecycle_evaluations
               WHERE ontology_id = ? GROUP BY decision, reason
               ORDER BY count DESC""",
            (run["ontology_id"],),
        ).fetchall()

    budget = load_alert_config()["budgetPerRun"]
    max_evidence_residual = float(score_summary["max_evidence_residual"] or 0.0)
    gates = {
        "runSucceeded": run["status"] == "succeeded",
        "minimumTraces": score_summary["trace_count"] >= 20,
        "alertBudget": alerted_count <= budget,
        "zeroResidualEvidence": max_evidence_residual < 1e-7,
    }
    pending = {
        "minimumReviews": review_count >= 20,
        "activeCalibration": active_calibration is not None,
    }
    failed_gates = [name for name, passed in gates.items() if not passed]
    pending_items = [name for name, passed in pending.items() if not passed]
    overall_status = "failed" if failed_gates else ("pending" if pending_items else "passed")

    return {
        "status": overall_status,
        "run": {
            "id": run["id"],
            "runType": run["run_type"],
            "status": run["status"],
            "source": run["source"],
            "sourceRef": run["source_ref"],
            "windowStart": run["window_start"],
            "windowEnd": run["window_end"],
            "createdAt": run["created_at"],
            "endedAt": run["ended_at"],
            "durationSeconds": _duration_seconds(run["created_at"], run["ended_at"]),
        },
        "tenant": {
            "id": tenant["id"],
            "displayName": tenant["display_name"],
            "orgId": tenant["org_id"],
            "projectId": tenant["project_id"],
        },
        "ontology": {
            "id": ontology["id"],
            "displayName": ontology["display_name"],
            "tier": ontology["tier"],
        },
        "scores": {
            "traceCount": score_summary["trace_count"],
            "averageScore": _round_or_none(score_summary["average_score"]),
            "minimumScore": _round_or_none(score_summary["minimum_score"]),
            "maximumScore": _round_or_none(score_summary["maximum_score"]),
            "abstainCount": score_summary["abstain_count"],
            "alertCount": score_summary["alert_count"],
            "maxEvidenceResidual": max_evidence_residual,
        },
        "clusters": [dict(row) for row in cells],
        "alerts": {
            "budgetPerRun": budget,
            "statusCounts": alert_status_counts,
            "top": [dict(row) for row in top_alerts],
        },
        "reviews": {
            "count": review_count,
            "verdictCounts": review_verdicts,
        },
        "calibration": dict(active_calibration) if active_calibration else None,
        "lifecycleEvaluations": [dict(row) for row in lifecycle_evaluations],
        "gates": {"mandatory": gates, "pending": pending},
        "failedGates": failed_gates,
        "pendingGates": pending_items,
    }


def render_pilot_markdown(report: dict) -> str:
    run = report["run"]
    scores = report["scores"]
    alerts = report["alerts"]
    reviews = report["reviews"]
    calibration = report["calibration"]

    lines = [
        "# M7.0 试点验收报告",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Run：`{run['id']}`（{run['runType']}，{run['status']}）",
        f"- 租户：`{report['tenant']['displayName']}`",
        f"- 本体：`{report['ontology']['displayName']}`（{report['ontology']['tier']}）",
        f"- 结论：**{report['status'].upper()}**",
        "",
        "## 核心指标",
        "",
        "| 指标 | 数值 | 说明 |",
        "|---|---:|---|",
        f"| 轨迹数 | {scores['traceCount']} | 最小试点门槛 20 |",
        f"| 聚类数 | {len(report['clusters'])} | 簇分布见下表 |",
        f"| 弃权数 | {scores['abstainCount']} | 语义不确定，需积累后重聚类 |",
        f"| 正式告警数 | {alerts['statusCounts'].get('alerted', 0)} | 当前 Run 预算 {alerts['budgetPerRun']} |",
        f"| 人工复核数 | {reviews['count']} | 建议达到 20 后触发校准 |",
        f"| 最大扣分残差 | {scores['maxEvidenceResidual']:.8f} | 必须接近 0 |",
        "",
        "## 聚类分布",
        "",
        "| Cell | 标签 | 主导动作 | 数量 |",
        "|---|---|---|---:|",
    ]
    if report["clusters"]:
        for cell in report["clusters"]:
            lines.append(
                f"| `{cell['cell_key']}` | {cell['label'] or '-'} | "
                f"{cell['dominant_action'] or '-'} | {cell['size']} |"
            )
    else:
        lines.append("| - | - | - | 0 |")

    lines.extend([
        "",
        "## Top 告警",
        "",
        "| Rank | Trace | 原因 | 状态 | 优先级 |",
        "|---:|---|---|---|---:|",
    ])
    if alerts["top"]:
        for alert in alerts["top"]:
            lines.append(
                f"| {alert['priority_rank']} | `{alert['trace_id']}` | "
                f"{alert['cause']} / {alert['cause_kind']} | {alert['status']} | "
                f"{alert['priority']:.4f} |"
            )
    else:
        lines.append("| - | - | - | - | - |")

    lines.extend([
        "",
        "## 复核与校准",
        "",
        f"- 复核分布：agree {reviews['verdictCounts'].get('agree', 0)}，"
        f"disagree {reviews['verdictCounts'].get('disagree', 0)}，"
        f"uncertain {reviews['verdictCounts'].get('uncertain', 0)}。",
    ])
    if calibration:
        lines.append(
            f"- 已激活校准：`{calibration['id']}`，"
            f"标签 {calibration['label_count']} 条，"
            f"alert precision {calibration['alert_precision']:.4f}，"
            f"ECE {calibration['ece']:.4f}。"
        )
    else:
        lines.append("- 尚无基于本 Run 激活的校准版本。")

    lines.extend([
        "",
        "## 工程门禁",
        "",
        "| 门禁 | 状态 | 类型 |",
        "|---|---|---|",
    ])
    for name, passed in report["gates"]["mandatory"].items():
        lines.append(f"| {name} | {'✅ 通过' if passed else '❌ 失败'} | 必须通过 |")
    for name, passed in report["gates"]["pending"].items():
        lines.append(f"| {name} | {'✅ 通过' if passed else '⏳ 待完成'} | 试点建议 |")

    lines.extend([
        "",
        "## 人工检查",
        "",
        "- [ ] 抽查 Top 告警是否符合业务直觉。",
        "- [ ] 确认聚类标签可被业务方理解。",
        "- [ ] 复核弃权样本是否代表新工作流。",
        "- [ ] 确认告警处置成本可接受。",
        "- [ ] 将结论回填到 `platform/PILOT.md`。",
        "",
        "## 生命周期记录",
        "",
    ])
    if report["lifecycleEvaluations"]:
        for evaluation in report["lifecycleEvaluations"]:
            lines.append(
                f"- {evaluation['decision']} × {evaluation['count']}：{evaluation['reason']}"
            )
    else:
        lines.append("- 尚无生命周期调度记录。")
    lines.append("")
    return "\n".join(lines)


def _select_run(connection, run_id: str | None):
    if run_id:
        run = connection.execute(
            "SELECT * FROM cohort_runs WHERE id = ?", (run_id,)
        ).fetchone()
    else:
        run = connection.execute(
            """SELECT * FROM cohort_runs
               WHERE status = 'succeeded' AND run_type IN ('R1', 'R2')
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
    if run is None:
        raise PilotReportError(f"run not found: {run_id or '<latest succeeded run>'}")
    return run


def _duration_seconds(started_at: str | None, ended_at: str | None) -> float | None:
    if not started_at or not ended_at:
        return None
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(ended_at)
    return round((end - start).total_seconds(), 3)


def _round_or_none(value, digits: int = 6):
    return round(float(value), digits) if value is not None else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an M7.0 pilot acceptance report")
    parser.add_argument(
        "--db",
        default=str(ROOT / "platform" / "var" / "traj-engine.db"),
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--output",
        default=None,
        help="Markdown output path; omit to print JSON only",
    )
    args = parser.parse_args()

    report = build_pilot_report(args.db, args.run_id)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_pilot_markdown(report), encoding="utf-8")
        report["markdownPath"] = str(output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
