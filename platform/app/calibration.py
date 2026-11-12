import json
from collections import defaultdict

from platform.app import store


DEFAULT_CALIBRATION_CONFIG = {
    "minimumLabels": 20,
    "minimumReviewedAlerts": 10,
    "minimumCauseSamples": 5,
    "scoreBins": 10,
    "targetAlertPrecision": 0.8,
    "minimumCauseAdjustment": 0.5,
    "maximumCauseAdjustment": 2.0,
}


def compute_review_calibration(
    score_rows: list[dict],
    review_rows: list[dict],
    alert_rows: list[dict],
    config: dict,
) -> dict:
    scores_by_id = {row["id"]: row for row in score_rows}
    alerts_by_score = {row["trace_score_id"]: row for row in alert_rows}
    reviews_by_score: dict[str, list[dict]] = defaultdict(list)
    for review in review_rows:
        reviews_by_score[review["trace_score_id"]].append(review)

    aggregated = []
    for score_id, reviews in reviews_by_score.items():
        counts = {"agree": 0, "disagree": 0, "uncertain": 0}
        for review in reviews:
            counts[review["verdict"]] += 1
        if counts["agree"] > counts["disagree"]:
            verdict = "agree"
        elif counts["disagree"] > counts["agree"]:
            verdict = "disagree"
        else:
            verdict = "uncertain"
        score = scores_by_id.get(score_id)
        alert = alerts_by_score.get(score_id)
        aggregated.append({
            "trace_score_id": score_id,
            "verdict": verdict,
            "counts": counts,
            "score": score,
            "alert": alert,
        })

    label_count = len(review_rows)
    trace_count = len(aggregated)
    verdict_counts = {"agree": 0, "disagree": 0, "uncertain": 0}
    for item in aggregated:
        verdict_counts[item["verdict"]] += 1

    alert_total = sum(1 for row in alert_rows if row["status"] == "alerted")
    alert_reviewed = [item for item in aggregated if item["alert"] is not None]
    alerted_reviewed = [item for item in alert_reviewed if item["alert"]["status"] == "alerted"]
    alert_decided = [item for item in alerted_reviewed if item["verdict"] != "uncertain"]
    alert_agree = sum(1 for item in alert_decided if item["verdict"] == "agree")
    alert_disagree = sum(1 for item in alert_decided if item["verdict"] == "disagree")
    alert_precision = _ratio(alert_agree, len(alert_decided))

    cause_stats = _cause_stats(alerted_reviewed)
    overall_decided = alert_decided or [
        item for item in aggregated if item["verdict"] != "uncertain"
    ]
    overall_agree = sum(1 for item in overall_decided if item["verdict"] == "agree")
    overall_decided_count = len(overall_decided)
    overall_precision = _ratio(overall_agree, overall_decided_count)

    decided_scored = [
        item for item in aggregated
        if item["verdict"] != "uncertain" and item["score"] is not None
    ]
    reliability = _reliability(decided_scored, int(config.get("scoreBins", 10)))
    eligible = (
        label_count >= int(config.get("minimumLabels", 20))
        and len(alerted_reviewed) >= int(config.get("minimumReviewedAlerts", 10))
    )

    metrics = {
        "labelCount": label_count,
        "traceCount": trace_count,
        "verdictCounts": verdict_counts,
        "runTraceCount": len(score_rows),
        "alertTotal": alert_total,
        "alertReviewed": len(alerted_reviewed),
        "alertAgree": alert_agree,
        "alertDisagree": alert_disagree,
        "alertPrecision": alert_precision,
        "alertCoverage": _ratio(len(alerted_reviewed), alert_total),
        "reviewCoverage": _ratio(trace_count, len(score_rows)),
        "reliability": reliability,
        "causeStats": cause_stats,
        "targetAlertPrecision": float(config.get("targetAlertPrecision", 0.8)),
        "eligible": eligible,
    }
    parameters = {
        "kind": "human-review-v1",
        "causeSeverityAdjustments": _cause_adjustments(
            cause_stats,
            overall_precision,
            int(config.get("minimumCauseSamples", 5)),
            float(config.get("minimumCauseAdjustment", 0.5)),
            float(config.get("maximumCauseAdjustment", 2.0)),
        ),
        "priorityWeights": _current_priority_weights(),
    }
    return {
        "label_count": label_count,
        "trace_count": trace_count,
        "agree_count": verdict_counts["agree"],
        "disagree_count": verdict_counts["disagree"],
        "uncertain_count": verdict_counts["uncertain"],
        "alert_reviewed": len(alerted_reviewed),
        "alert_agree": alert_agree,
        "alert_disagree": alert_disagree,
        "alert_precision": alert_precision,
        "ece": reliability["ece"],
        "brier": reliability["brier"],
        "metrics": metrics,
        "parameters": parameters,
    }


def create_review_calibration(
    connection,
    run_id: str,
    created_by: str,
    config: dict,
) -> dict:
    run = store.get_run(connection, run_id)
    if run is None:
        raise ValueError("run not found")
    score_rows = [dict(row) for row in connection.execute(
        "SELECT * FROM trace_scores WHERE run_id = ?", (run_id,)
    ).fetchall()]
    review_rows = [dict(row) for row in connection.execute(
        """SELECT r.* FROM human_reviews r
           JOIN trace_scores s ON s.id = r.trace_score_id
           WHERE s.run_id = ? ORDER BY r.created_at, r.id""",
        (run_id,),
    ).fetchall()]
    alert_rows = [dict(row) for row in connection.execute(
        "SELECT * FROM alert_decisions WHERE run_id = ?", (run_id,)
    ).fetchall()]
    result = compute_review_calibration(score_rows, review_rows, alert_rows, config)
    if not result["metrics"]["eligible"]:
        raise ValueError("insufficient review labels")

    calibration_id = store.new_id("calibration")
    connection.execute(
        """INSERT INTO review_calibrations
           (id, tenant_id, source_run_id, label_count, trace_count, agree_count,
            disagree_count, uncertain_count, alert_reviewed, alert_agree,
            alert_disagree, alert_precision, ece, brier, metrics_json,
            parameters_json, code_hash, created_by, created_at, activated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
        (
            calibration_id, run["tenant_id"], run_id, result["label_count"],
            result["trace_count"], result["agree_count"], result["disagree_count"],
            result["uncertain_count"], result["alert_reviewed"], result["alert_agree"],
            result["alert_disagree"], result["alert_precision"], result["ece"],
            result["brier"],
            json.dumps(result["metrics"], ensure_ascii=False, sort_keys=True),
            json.dumps(result["parameters"], ensure_ascii=False, sort_keys=True),
            run["code_hash"], created_by, store.utcnow(),
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM review_calibrations WHERE id = ?", (calibration_id,)
    ).fetchone()
    return dict(row)


def activate_review_calibration(connection, calibration_id: str) -> dict:
    row = connection.execute(
        "SELECT * FROM review_calibrations WHERE id = ?", (calibration_id,)
    ).fetchone()
    if row is None:
        raise ValueError("calibration not found")
    connection.execute(
        "UPDATE review_calibrations SET activated_at = NULL WHERE tenant_id = ? AND activated_at IS NOT NULL",
        (row["tenant_id"],),
    )
    connection.execute(
        "UPDATE review_calibrations SET activated_at = ? WHERE id = ?",
        (store.utcnow(), calibration_id),
    )
    connection.commit()
    return dict(connection.execute(
        "SELECT * FROM review_calibrations WHERE id = ?", (calibration_id,)
    ).fetchone())


def active_review_calibration(connection, tenant_id: str) -> dict | None:
    row = connection.execute(
        """SELECT * FROM review_calibrations
           WHERE tenant_id = ? AND activated_at IS NOT NULL
           ORDER BY activated_at DESC LIMIT 1""",
        (tenant_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def serialize_review_calibration(row: dict) -> dict:
    return {
        "id": row["id"],
        "tenantId": row["tenant_id"],
        "sourceRunId": row["source_run_id"],
        "labelCount": row["label_count"],
        "traceCount": row["trace_count"],
        "verdictCounts": {
            "agree": row["agree_count"],
            "disagree": row["disagree_count"],
            "uncertain": row["uncertain_count"],
        },
        "alertReviewed": row["alert_reviewed"],
        "alertAgree": row["alert_agree"],
        "alertDisagree": row["alert_disagree"],
        "alertPrecision": row["alert_precision"],
        "ece": row["ece"],
        "brier": row["brier"],
        "metrics": json.loads(row["metrics_json"] or "{}"),
        "parameters": json.loads(row["parameters_json"] or "{}"),
        "codeHash": row["code_hash"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "activatedAt": row["activated_at"],
    }


def _cause_stats(reviewed_alerts: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in reviewed_alerts:
        grouped[item["alert"]["cause"]].append(item)
    stats = []
    for cause, items in grouped.items():
        decided = [item for item in items if item["verdict"] != "uncertain"]
        agree = sum(1 for item in decided if item["verdict"] == "agree")
        stats.append({
            "cause": cause,
            "sampleCount": len(items),
            "decidedCount": len(decided),
            "agreeCount": agree,
            "disagreeCount": len(decided) - agree,
            "precision": _ratio(agree, len(decided)),
        })
    return sorted(stats, key=lambda item: (-item["sampleCount"], item["cause"]))


def _cause_adjustments(
    cause_stats: list[dict],
    overall_precision: float,
    minimum_samples: int,
    lower: float,
    upper: float,
) -> dict[str, float]:
    adjustments = {}
    for stat in cause_stats:
        if stat["decidedCount"] < minimum_samples:
            continue
        base = overall_precision if overall_precision > 0 else 1.0
        adjustment = stat["precision"] / base
        adjustments[stat["cause"]] = round(_clamp(adjustment, lower, upper), 4)
    return adjustments


def _reliability(items: list[dict], bins: int) -> dict:
    if not items:
        return {"ece": None, "brier": None, "bins": []}
    bin_count = max(2, bins)
    buckets = [[] for _ in range(bin_count)]
    for item in items:
        probability = _clamp(float(item["score"]["total_score"]) / 100.0)
        index = min(bin_count - 1, int(probability * bin_count))
        buckets[index].append((probability, 1.0 if item["verdict"] == "agree" else 0.0))
    total = len(items)
    ece = 0.0
    brier = 0.0
    rendered_bins = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        mean_probability = sum(value[0] for value in bucket) / len(bucket)
        mean_actual = sum(value[1] for value in bucket) / len(bucket)
        weight = len(bucket) / total
        ece += weight * abs(mean_probability - mean_actual)
        brier += sum(
            (probability - actual) ** 2 for probability, actual in bucket
        )
        rendered_bins.append({
            "index": index,
            "count": len(bucket),
            "meanProbability": round(mean_probability, 6),
            "meanActual": round(mean_actual, 6),
            "gap": round(abs(mean_probability - mean_actual), 6),
        })
    return {
        "ece": round(ece, 6),
        "brier": round(brier / total, 6),
        "bins": rendered_bins,
    }


def _current_priority_weights() -> dict[str, float]:
    return {
        "severity": 0.34,
        "dimensionImpact": 0.20,
        "deductionStrength": 0.16,
        "causeSeverity": 0.20,
        "clusterImpact": 0.10,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
