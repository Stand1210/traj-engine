import json
import math
from collections import defaultdict

from platform.app import store


DEFAULT_ALERT_BUDGET = 5

RULE_SEVERITY = {
    "result_broken": 1.0,
    "forbidden_action": 1.0,
    "unrecovered_error": 0.95,
    "truncated_generation": 0.9,
    "unfinished": 0.8,
    "missing_step": 0.75,
    "untraceable_answer_number": 0.7,
    "untraceable_answer_fact": 0.7,
    "runaway_loop": 0.85,
}


def compute_alert_decisions(
    score_rows: list[dict],
    evidence_rows: list[dict],
    cell_sizes: dict[str, int],
    budget: int = DEFAULT_ALERT_BUDGET,
) -> list[dict]:
    if not score_rows:
        return []
    budget = max(0, int(budget))
    evidence_by_score: dict[str, list[dict]] = defaultdict(list)
    for row in evidence_rows:
        evidence_by_score[row["trace_score_id"]].append(row)

    total_traces = sum(int(size) for size in cell_sizes.values()) or len(score_rows)
    candidates = []
    for row in score_rows:
        if not int(row["is_alert"] or 0):
            continue
        primary = _primary_cause(evidence_by_score.get(row["id"], []))
        priority = _priority(row, primary, cell_sizes.get(row["cell_id"], 0), total_traces)
        candidates.append({
            "trace_score_id": row["id"],
            "group_key": f"{row['cell_id'] or 'no-cell'}:{primary['cause']}",
            "cause": primary["cause"],
            "cause_kind": primary["kind"],
            "priority": priority,
            "reasons": _reasons(row, primary, priority),
        })

    candidates.sort(key=lambda item: (
        -item["priority"], _score_row_by_id(score_rows, item["trace_score_id"])["total_score"],
        _score_row_by_id(score_rows, item["trace_score_id"])["trace_id"],
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index
    groups: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate["group_key"]].append(candidate)

    decisions = []
    emitted = 0
    for group_key in sorted(groups, key=lambda key: (-groups[key][0]["priority"], key)):
        members = groups[group_key]
        for group_rank, member in enumerate(members, start=1):
            if group_rank == 1 and emitted < budget:
                status = "alerted"
                emitted += 1
            elif group_rank == 1:
                status = "candidate"
            else:
                status = "suppressed_duplicate"
            decisions.append({
                **member,
                "group_rank": group_rank,
                "group_size": len(members),
                "status": status,
                "rank": member["rank"],
            })
    return decisions


def persist_alert_decisions(connection, run_id: str, budget: int = DEFAULT_ALERT_BUDGET) -> dict:
    score_rows = [
        dict(row) for row in connection.execute(
            "SELECT * FROM trace_scores WHERE run_id = ? AND is_alert = 1", (run_id,)
        ).fetchall()
    ]
    score_ids = [row["id"] for row in score_rows]
    evidence_rows = []
    for score_id in score_ids:
        evidence_rows.extend(
            dict(row) for row in connection.execute(
                "SELECT * FROM score_evidence WHERE trace_score_id = ? ORDER BY dimension", (score_id,)
            ).fetchall()
        )
    cell_sizes = {
        row["id"]: int(row["size"])
        for row in connection.execute("SELECT id, size FROM cells WHERE run_id = ?", (run_id,)).fetchall()
    }
    decisions = compute_alert_decisions(score_rows, evidence_rows, cell_sizes, budget)
    connection.execute("DELETE FROM alert_decisions WHERE run_id = ?", (run_id,))
    for decision in decisions:
        connection.execute(
            """INSERT INTO alert_decisions
               (id, run_id, trace_score_id, group_key, cause, cause_kind, priority,
                priority_rank, group_rank, group_size, status, reasons_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_decision_id(run_id, decision["trace_score_id"]), run_id,
             decision["trace_score_id"], decision["group_key"], decision["cause"],
             decision["cause_kind"], decision["priority"], decision["rank"],
             decision["group_rank"], decision["group_size"], decision["status"],
             json.dumps(decision["reasons"], ensure_ascii=False, sort_keys=True),
             store.utcnow()),
        )
    connection.commit()
    return _summary(decisions, budget)


def summarize_decisions(decisions: list[dict], budget: int) -> dict:
    return _summary(decisions, budget)


def _primary_cause(evidence_rows: list[dict]) -> dict:
    rules = []
    metrics = []
    for row in evidence_rows:
        payload = json.loads(row["payload_json"] or "{}")
        for item in payload.get("kernel_evidence") or []:
            if item.get("kind") == "rule" and item.get("rule"):
                rules.append({"rule": str(item["rule"]), "severity": RULE_SEVERITY.get(item["rule"], 0.55)})
            if item.get("kind") == "metric" and item.get("metric"):
                metrics.append({
                    "metric": str(item["metric"]),
                    "z": abs(float(item.get("z") or 0.0)),
                })
            if item.get("kind") == "span" and item.get("action") and item.get("metric"):
                metrics.append({
                    "metric": f"{item['action']}:{item['metric']}",
                    "z": abs(float(item.get("z") or 0.0)),
                })

    unique_rules = {}
    for rule in rules:
        unique_rules.setdefault(rule["rule"], rule)
    if unique_rules:
        rule_name, rule = sorted(unique_rules.items(), key=lambda pair: (-pair[1]["severity"], pair[0]))[0]
        return {"cause": f"rule:{rule_name}", "kind": "rule", "severity": rule["severity"]}
    if metrics:
        metric = sorted(metrics, key=lambda item: (-item["z"], item["metric"]))[0]
        return {
            "cause": f"metric:{metric['metric']}",
            "kind": "metric",
            "severity": min(1.0, metric["z"] / 50.0 + 0.35),
        }
    return {"cause": "alert:unspecified", "kind": "unspecified", "severity": 0.5}


def _priority(row: dict, primary: dict, cell_size: int, total_traces: int) -> float:
    severity = _clamp((100.0 - float(row["total_score"])) / 100.0)
    dimension_impact = _clamp(1.0 - min(
        float(row["result_score"]), float(row["process_score"]), float(row["latency_score"]),
        float(row["cost_score"]), float(row["robustness_score"]),
    ))
    deduction_strength = _clamp(abs(float(row["evidence_sum"] or row["deduction_total"])) / 30.0)
    cluster_impact = _clamp(math.log1p(cell_size) / math.log1p(max(total_traces, 1)))
    return round(100.0 * (
        0.34 * severity
        + 0.20 * dimension_impact
        + 0.16 * deduction_strength
        + 0.20 * float(primary["severity"])
        + 0.10 * cluster_impact
    ), 4)


def _reasons(row: dict, primary: dict, priority: float) -> list[str]:
    worst_dimension = min(
        ("result", row["result_score"]), ("process", row["process_score"]),
        ("latency", row["latency_score"]), ("cost", row["cost_score"]),
        ("robustness", row["robustness_score"]),
        key=lambda pair: pair[1],
    )
    return [
        f"total_score={float(row['total_score']):.4f}",
        f"worst_dimension={worst_dimension[0]}:{float(worst_dimension[1]):.4f}",
        f"deduction={float(row['evidence_sum'] or row['deduction_total']):.4f}",
        f"primary_cause={primary['cause']}",
        f"priority={priority:.4f}",
    ]


def _score_row_by_id(score_rows: list[dict], score_id: str) -> dict:
    return next(row for row in score_rows if row["id"] == score_id)


def _summary(decisions: list[dict], budget: int) -> dict:
    counts = {"alerted": 0, "candidate": 0, "suppressed_duplicate": 0}
    for decision in decisions:
        counts[decision["status"]] += 1
    groups = {decision["group_key"] for decision in decisions}
    return {
        "budget": budget,
        "totalAlerts": len(decisions),
        "groups": len(groups),
        "emitted": counts["alerted"],
        "candidates": counts["candidate"] + counts["suppressed_duplicate"],
        "statusCounts": counts,
    }


def _decision_id(run_id: str, trace_score_id: str) -> str:
    import hashlib
    digest = hashlib.sha256(f"{run_id}:{trace_score_id}".encode("utf-8")).hexdigest()
    return f"alert-{digest[:24]}"


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
