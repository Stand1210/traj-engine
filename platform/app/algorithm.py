import hashlib
import json
from pathlib import Path

from bench.runner import code_hash
from kernel import baseline as BL
from kernel import binding as BD
from kernel import calib
from kernel import cluster
from kernel import detect
from kernel import drift
from kernel import features as FEAT
from kernel import ingest
from kernel import score
import bench.regime as RG


PIPELINE_VERSION = "platform-prod-v0.1.0"
PATTERN_CAP_NDEC_DEFAULT = 3


def build_dynamic_ontology(traces: list[dict], ontology_id: str) -> dict:
    actions: set[str] = set()
    models: set[str] = set()
    kind_map: dict[str, str] = {}
    tool_catalog: dict[str, set[str]] = {}
    root_action = "agent_run"

    for trace in traces:
        for span in trace.get("spans", []):
            action = span.get("action") or span.get("kind") or "span"
            actions.add(action)
            kind_map.setdefault(action, span.get("kind") or "span")
            if span.get("parent_id") is None:
                root_action = action
            if span.get("model"):
                models.add(span["model"])
            if span.get("tool_name") and span.get("kind") in {"tool", "retrieval"}:
                tool_catalog.setdefault(action, set()).add(span["tool_name"])

    if not actions:
        actions.add("agent_run")
        kind_map.setdefault("agent_run", "agent")
    models.add("default")
    return {
        "id": ontology_id,
        "actions": sorted(actions),
        "forbidden_actions": [],
        "required_steps": {},
        "optional_steps": sorted(actions),
        "root_action": root_action,
        "kind_map": kind_map,
        "unit_price": {
            "prompt": 0.0,
            "completion": 0.0,
            "tool_call": 0.0,
            "cache_read": 0.0,
            "cache_write": 0.0,
        },
        "context_window": {model: 16384 for model in models} | {"default": 16384},
        "system_prompt_tokens": {model: 0 for model in models} | {"default": 0},
        "models": [(model, 1.0 if model == "default" else 0.0, 1.0) for model in sorted(models)],
        "prompt_versions": [],
        "query_langs": [("en", 1.0)],
        "lang_token_factor": {"en": 1.0},
        "time_windows": [],
        "slo_anchors": {},
        "validators": [],
        "tool_catalog": {
            action: sorted(names) for action, names in sorted(tool_catalog.items())
        },
    }


def run_production(traces: list[dict], ontology_id: str) -> tuple[dict, list[dict]]:
    if not traces:
        raise ValueError("production run requires at least one trace")

    ontology = build_dynamic_ontology(traces, ontology_id)
    spec_hash = _spec_hash(traces)
    anchor_version = f"anchor-{ontology_id}-{spec_hash}"
    cold_start = len(traces) < RG.COLD_START_MIN_TRACES

    normalized = [ingest.normalize(trace, ontology) for trace in traces]
    feature_rows = [FEAT.extract(item, ontology) for item in normalized]
    FEAT.annotate_sessions(feature_rows, traces)

    cluster.reset_cache()
    assigns, cluster_info = cluster.cluster_views(
        feature_rows,
        threshold=cluster.CONSENSUS_THRESHOLD,
        seed=42,
        n_declared_patterns=PATTERN_CAP_NDEC_DEFAULT,
    )
    records = [
        {"cell": assign["cell"], "intent": assign.get("near_intent", -1), "feats": feature}
        for assign, feature in zip(assigns, feature_rows)
        if not assign["novelty"]
    ]
    artifact = BL.build(records, ontology, anchor_version)
    binding = BD.bind_patterns(artifact, ontology)
    stage, detection_info = detect.detect_all(
        feature_rows, assigns, artifact, ontology, binding=binding
    )

    ordered = sorted(feature_rows, key=lambda item: (item["ts_start"], item["trace_id"]))
    cell_of = {assign["trace_id"]: assign["cell"] for assign in assigns}
    parent_of = {
        assign["trace_id"]: f"i{assign.get('near_intent', -1)}" for assign in assigns
    }
    stream = [
        (item["trace_id"], cell_of[item["trace_id"]], parent_of[item["trace_id"]],
         item["latency_total"])
        for item in ordered
    ]
    drift_result = drift.detect_drift(stream)
    if cold_start:
        for item in stage.values():
            item["alert"] = False
            item["alert_stat"] = False
            item["alert_rule"] = False
        detection_info["n_alert"] = 0
        detection_info["n_alert_stat"] = 0
        detection_info["n_alert_rule"] = 0
        drift_result = {
            "drift": False,
            "reason": "cold_start_suppressed",
            "n": drift_result.get("n", 0),
            "suspects": [],
        }

    drift_ids = set(drift_result.get("suspects") or [])
    score_rows = score.score_all(
        feature_rows,
        assigns,
        stage,
        artifact,
        ontology,
        cold_start=cold_start,
        drift_map={trace_id: True for trace_id in drift_ids},
        anchor_version=anchor_version,
        model_version=PIPELINE_VERSION,
    )
    for row in score_rows:
        row["a_cal"] = None

    result = {
        "pipeline_version": PIPELINE_VERSION,
        "code_hash": code_hash(),
        "spec_hash": spec_hash,
        "ontology_id": ontology_id,
        "n": len(traces),
        "n_pool": sum(1 for assign in assigns if not assign["novelty"]),
        "cold_start": cold_start,
        "cluster_info": cluster_info,
        "detect_info": detection_info,
        "clustering": {
            **cluster_info,
            "coverage": sum(1 for assign in assigns if not assign["novelty"]) / len(assigns),
        },
        "detection": {
            "n_alert": detection_info["n_alert"],
            "n_alert_stat": detection_info["n_alert_stat"],
            "n_alert_rule": detection_info["n_alert_rule"],
            "cold_start_suppressed": cold_start,
        },
        "drift": drift_result,
        "scoring": _scoring_summary(score_rows),
        "calibration": {"kind": "none", "n_labels": 0, "ece_oof": None},
    }
    return result, score_rows


def write_production_report(report_dir: Path, result: dict, score_rows: list[dict]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    slim = []
    for row in score_rows:
        slim.append({
            "trace_id": row["trace_id"],
            "cell": row["cell"],
            "S": round(row["S"], 4),
            "G": round(row["G"], 6),
            "grade_abs": row["grade_abs"],
            "grade_rel": row["grade_rel"],
            "dims": {key: round(value, 5) for key, value in row["dims"].items()},
            "gates": row["gates"],
            "contrib": {key: round(value, 6) for key, value in row["contrib"].items()},
            "conf": round(row["conf"], 4),
            "alert": row["alert"],
            "a_raw": round(row["a_raw"], 5),
            "a_cal": row["a_cal"],
            "tier": row["tier"],
            "graded": round(row["graded"], 5),
            "alert_rule": row["alert_rule"],
            "alert_stat": row["alert_stat"],
            "novelty": row["novelty"],
            "cold_start": row["cold_start"],
            "anchor_version": row["anchor_version"],
            "model_version": row["model_version"],
            "evidence": row["evidence"][:3],
        })
    with (report_dir / "scores.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in slim:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with (report_dir / "metrics.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return report_dir


def _spec_hash(traces: list[dict]) -> str:
    digest = hashlib.sha256()
    for trace in traces:
        digest.update(json.dumps(trace, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()[:16]


def _scoring_summary(score_rows: list[dict]) -> dict:
    values = [row["S"] for row in score_rows]
    return {
        "n": len(values),
        "mean": sum(values) / len(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "n_alert": sum(1 for row in score_rows if row["alert"]),
        "n_novelty": sum(1 for row in score_rows if row["novelty"]),
    }
