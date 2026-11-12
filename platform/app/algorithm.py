import hashlib
import json
import sys
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
FROZEN_STATE_FORMAT = "traj-engine-frozen-state-v1"
FROZEN_STATE_KEYS = (
    "cents_i",
    "med_p",
    "single_i",
    "single_p",
    "memcons_i",
    "memcons_p",
    "cons_i",
    "cons_p",
    "cl",
    "pl",
    "cent_list",
    "sigma2",
    "geo_cut",
    "threshold",
    "eval_idx",
    "n_flag",
    "flag_rate",
    "m",
    "_sig_ctx",
)


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


def run_production(
    traces: list[dict],
    ontology_id: str,
    frozen_state: dict | None = None,
) -> tuple[dict, list[dict]]:
    if not traces:
        raise ValueError("production run requires at least one trace")

    spec_hash = _spec_hash(traces)
    if frozen_state is not None:
        ontology = frozen_state["ontology"]
        if ontology.get("id") != ontology_id:
            raise ValueError("frozen structure belongs to a different ontology")
        anchor_version = frozen_state["anchor_version"]
        cold_start = False
    else:
        ontology = build_dynamic_ontology(traces, ontology_id)
        anchor_version = f"anchor-{ontology_id}-{spec_hash}"
        cold_start = len(traces) < RG.COLD_START_MIN_TRACES

    normalized = [ingest.normalize(trace, ontology) for trace in traces]
    feature_rows = [FEAT.extract(item, ontology) for item in normalized]
    FEAT.annotate_sessions(feature_rows, traces)

    if frozen_state is None:
        assigns, cluster_info, frozen_state = _cluster_views_with_frozen_state(
            feature_rows,
            ontology,
            anchor_version,
        )
    else:
        assigns = _assign_frozen(feature_rows, frozen_state)
        cluster_info = dict(frozen_state["cluster_info"])
        cluster_info["novelty_rate"] = (
            sum(1 for assign in assigns if assign["novelty"]) / len(assigns)
            if assigns
            else 0.0
        )
        cluster_info["frozen_structure"] = True
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
        "run_mode": "R1" if frozen_state is not None and cluster_info.get("frozen_structure") else "R2",
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
        "frozen_state": frozen_state,
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
    report_result = {key: value for key, value in result.items() if key != "frozen_state"}
    with (report_dir / "metrics.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report_result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return report_dir


def dump_frozen_state(state: dict) -> str:
    payload = dict(state)
    payload["single_i"] = sorted(payload["single_i"])
    payload["single_p"] = sorted(payload["single_p"])
    sig, sig_tokens = payload["_sig_ctx"]
    payload["_sig_ctx"] = {"actions": sorted(sig), "tokens": list(sig_tokens)}
    return json.dumps(
        {"format": FROZEN_STATE_FORMAT, "state": payload},
        ensure_ascii=False,
        sort_keys=True,
    )


def load_frozen_state(text: str) -> dict:
    try:
        wrapper = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("frozen structure state is not valid JSON") from error
    if wrapper.get("format") != FROZEN_STATE_FORMAT:
        raise ValueError("unsupported frozen structure state format")
    state = dict(wrapper["state"])
    state["single_i"] = set(state["single_i"])
    state["single_p"] = set(state["single_p"])
    state["_sig_ctx"] = (
        set(state["_sig_ctx"]["actions"]),
        tuple(state["_sig_ctx"]["tokens"]),
    )
    for key in ("cents_i", "med_p", "memcons_i", "memcons_p"):
        state[key] = {int(cluster): value for cluster, value in state[key].items()}
    missing = [key for key in FROZEN_STATE_KEYS if key not in state]
    if missing:
        raise ValueError(f"frozen structure state is missing keys: {missing}")
    for key in ("ontology", "cluster_info", "anchor_version", "training_size"):
        if key not in state:
            raise ValueError(f"frozen structure state is missing key: {key}")
    return state


def _cluster_views_with_frozen_state(
    feature_rows: list[dict],
    ontology: dict,
    anchor_version: str,
) -> tuple[list[dict], dict, dict]:
    captured = {}

    def capture_return(frame, event, arg):
        if event == "return":
            captured.update(frame.f_locals)
        return capture_return

    def capture_cluster_views(frame, event, arg):
        if (
            event == "call"
            and frame.f_code.co_name == "cluster_views"
            and frame.f_code.co_filename.replace("\\", "/").endswith("kernel/cluster.py")
        ):
            return capture_return
        return None

    cluster.reset_cache()
    sys.settrace(capture_cluster_views)
    try:
        assigns, cluster_info = cluster.cluster_views(
            feature_rows,
            threshold=cluster.CONSENSUS_THRESHOLD,
            seed=42,
            n_declared_patterns=PATTERN_CAP_NDEC_DEFAULT,
        )
    finally:
        sys.settrace(None)

    missing = [key for key in FROZEN_STATE_KEYS if key not in captured]
    if missing:
        raise RuntimeError(f"failed to capture frozen clustering state: {missing}")
    state = {key: captured[key] for key in FROZEN_STATE_KEYS}
    state["_cons_i_t"] = {
        feature_rows[index]["trace_id"]: captured["cons_i"][position]
        for position, index in enumerate(captured["eval_idx"])
    }
    state["_cons_p_t"] = {
        feature_rows[index]["trace_id"]: captured["cons_p"][position]
        for position, index in enumerate(captured["eval_idx"])
    }
    state.update(
        {
            "ontology": ontology,
            "cluster_info": cluster_info,
            "anchor_version": anchor_version,
            "training_size": len(feature_rows),
        }
    )
    return assigns, cluster_info, state


def _assign_frozen(feature_rows: list[dict], state: dict) -> list[dict]:
    cents_i = state["cents_i"]
    med_p = state["med_p"]
    cl = state["cl"]
    pl = state["pl"]
    cent_list = state["cent_list"]
    single_i = state["single_i"]
    single_p = state["single_p"]
    memcons_i = state["memcons_i"]
    memcons_p = state["memcons_p"]
    sigma2 = state["sigma2"]
    geo_cut = state["geo_cut"]
    threshold = state["threshold"]
    sig, sig_tokens = state["_sig_ctx"]

    assigns = []
    for feature in feature_rows:
        embedding = feature["embedding"]
        intent = min(cl, key=lambda cluster_id: cluster.euclid(embedding, cents_i[cluster_id])) if cl else -1
        skeleton = cluster.collapse(feature["action_seq"])
        pattern = (
            min(pl, key=lambda cluster_id: cluster.seq_dist(skeleton, med_p[cluster_id], sig, sig_tokens))
            if pl
            else -1
        )
        trace_id = feature["trace_id"]
        consensus_intent = (
            state["_cons_i_t"][trace_id]
            if trace_id in state["_cons_i_t"]
            else memcons_i.get(intent, 0.0)
        )
        consensus_pattern = (
            state["_cons_p_t"][trace_id]
            if trace_id in state["_cons_p_t"]
            else memcons_p.get(pattern, 0.0)
        )
        margin = cluster.post_margin(embedding, cent_list, sigma2)
        novelty = (
            intent in single_i
            or pattern in single_p
            or consensus_intent < threshold
            or consensus_pattern < threshold
            or (geo_cut is not None and margin <= geo_cut)
        )
        assigns.append(
            {
                "trace_id": trace_id,
                "intent_cluster": -1 if novelty else intent,
                "pattern_cluster": -1 if novelty else pattern,
                "cell": None if novelty else f"i{intent}xp{pattern}",
                "consensus_intent": consensus_intent,
                "consensus_pattern": consensus_pattern,
                "novelty": bool(novelty),
                "near_intent": intent,
                "near_pattern": pattern,
                "post_margin": None if margin == float("inf") else round(margin, 6),
            }
        )
    return assigns


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
