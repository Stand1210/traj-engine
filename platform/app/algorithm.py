import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Iterable
from typing import Callable

import yaml

from bench.runner import code_hash
from platform.app.encoder import (
    EncoderContractError,
    build_model_assets,
    encode_intents,
    trace_intent_texts,
    validate_trace_embeddings,
)
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
    "_tfidf_ctx",
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


# Governance keys an ontology YAML may pin. Anything absent falls back to the
# dynamic discovery in build_dynamic_ontology and is reported in `missing`, so
# a production run never silently operates on assumed constraints or prices.
ONTOLOGY_GOVERNANCE_KEYS = (
    "actions",
    "forbidden_actions",
    "required_steps",
    "optional_steps",
    "root_action",
    "kind_map",
    "unit_price",
    "context_window",
    "system_prompt_tokens",
    "models",
    "prompt_versions",
    "query_langs",
    "lang_token_factor",
    "time_windows",
    "slo_anchors",
    "validators",
    "tool_catalog",
)


def ontology_from_yaml(
    yaml_text: str,
    ontology_id: str,
    traces: list[dict],
) -> tuple[dict, list[str]]:
    """Build the kernel ontology dict from the active ontology YAML.

    The dynamic discovery over `traces` is the base layer (it reflects the
    observed span vocabulary); every governance key present in the YAML
    overrides the discovered value. Returns (ontology, missing) where
    `missing` lists the governance keys the YAML does not pin.
    """
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as error:
        raise ValueError("ontology yaml is not valid YAML") from error
    if not isinstance(parsed, dict):
        raise ValueError("ontology yaml must be a mapping")
    if parsed.get("id") not in (None, ontology_id):
        raise ValueError("ontology yaml id must match the ontology")
    ontology = build_dynamic_ontology(traces, ontology_id)
    for key in ONTOLOGY_GOVERNANCE_KEYS:
        if key not in parsed or parsed[key] is None:
            continue
        value = parsed[key]
        if key in {"models", "prompt_versions", "query_langs"}:
            try:
                value = [tuple(item) for item in value]
            except TypeError as error:
                raise ValueError(f"ontology yaml {key} must be a list of lists") from error
        if key == "unit_price":
            if not isinstance(value, dict):
                raise ValueError("ontology yaml unit_price must be a mapping")
            # The kernel cost model requires every price channel (tool_call,
            # cache_read, cache_write); channels the YAML does not pin inherit
            # the dynamic zero defaults instead of crashing ingest.
            merged = dict(ontology["unit_price"])
            merged.update(value)
            value = merged
        ontology[key] = value
    missing = [key for key in ONTOLOGY_GOVERNANCE_KEYS if parsed.get(key) is None]
    return ontology, missing


def run_production(
    traces: Iterable[dict],
    ontology_id: str,
    frozen_state: dict | None = None,
    run_mode: str | None = None,
    score_sink: Callable[[dict], None] | None = None,
    score_batch_size: int = 1000,
    intent_encoder=None,
    pattern_recipe: str | None = None,
    ontology_override: dict | None = None,
) -> tuple[dict, list[dict]]:
    traces = list(traces)
    if not traces:
        raise ValueError("production run requires at least one trace")
    trace_count = len(traces)

    spec_hash = _spec_hash(traces)
    if intent_encoder is not None:
        encoded = encode_intents(intent_encoder, trace_intent_texts(traces))
        traces = [
            {**trace, "embedding": vector} for trace, vector in zip(traces, encoded)
        ]
    embedding_dim = validate_trace_embeddings(
        traces, context=f"production run ontology={ontology_id}"
    )
    if frozen_state is not None:
        ontology = frozen_state["ontology"]
        if ontology.get("id") != ontology_id:
            raise ValueError("frozen structure belongs to a different ontology")
        _assert_frozen_embedding_compatible(frozen_state, embedding_dim)
        _assert_frozen_structural_compatible(frozen_state)
        anchor_version = frozen_state["anchor_version"]
        cold_start = False
    else:
        if ontology_override is not None:
            if ontology_override.get("id") != ontology_id:
                raise ValueError("ontology override belongs to a different ontology")
            ontology = ontology_override
        else:
            ontology = build_dynamic_ontology(traces, ontology_id)
        anchor_version = f"anchor-{ontology_id}-{spec_hash}"
        cold_start = len(traces) < RG.COLD_START_MIN_TRACES

    normalized = [ingest.normalize(trace, ontology) for trace in traces]
    feature_rows = [FEAT.extract(item, ontology) for item in normalized]
    FEAT.annotate_sessions(feature_rows, traces)
    del normalized
    del traces

    if frozen_state is None:
        assigns, cluster_info, frozen_state = _cluster_views_with_frozen_state(
            feature_rows,
            ontology,
            anchor_version,
            pattern_recipe=pattern_recipe,
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
    if score_sink is None:
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
        feature_by_trace = {feature["trace_id"]: feature for feature in feature_rows}
        for row in score_rows:
            row["a_cal"] = None
            _attach_trace_time(row, feature_by_trace.get(row["trace_id"]))
        scoring_summary = _scoring_summary(score_rows)
    else:
        score_rows = []
        scoring_summary = _stream_score_rows(
            feature_rows,
            assigns,
            stage,
            artifact,
            ontology,
            cold_start,
            set(drift_ids),
            anchor_version,
            score_sink,
            score_batch_size,
        )

    result = {
        "pipeline_version": PIPELINE_VERSION,
        "code_hash": code_hash(),
        "spec_hash": spec_hash,
        "ontology_id": ontology_id,
        "run_mode": run_mode or (
            "R1" if frozen_state is not None and cluster_info.get("frozen_structure") else "R2"
        ),
        "n": trace_count,
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
        "scoring": scoring_summary,
        "calibration": {"kind": "none", "n_labels": 0, "ece_oof": None},
        "model_assets": build_model_assets(intent_encoder, embedding_dim),
        "frozen_state": frozen_state,
    }
    return result, score_rows


def write_production_metrics(report_dir: Path, result: dict) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_result = {key: value for key, value in result.items() if key != "frozen_state"}
    with (report_dir / "metrics.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report_result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return report_dir


def write_production_scores(report_dir: Path, score_rows: Iterable[dict]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    with (report_dir / "scores.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in score_rows:
            handle.write(json.dumps(_slim_score_row(row), ensure_ascii=False, sort_keys=True) + "\n")
    return report_dir


def _slim_score_row(row: dict) -> dict:
    return {
        "trace_id": row["trace_id"],
        "ts_start": row.get("ts_start"),
        "ts_end": row.get("ts_end"),
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
    }


def _attach_trace_time(row: dict, feature: dict | None) -> None:
    if feature is None:
        return
    started = feature.get("ts_start")
    if started is not None:
        row["ts_start"] = started
        row["ts_end"] = started + float(feature.get("latency_total") or 0.0)


def _stream_score_rows(
    feature_rows: list[dict],
    assigns: list[dict],
    stage: dict,
    artifact: dict,
    ontology: dict,
    cold_start: bool,
    drift_ids: set[str],
    anchor_version: str,
    score_sink: Callable[[dict], None],
    batch_size: int,
) -> dict:
    if batch_size < 1:
        raise ValueError("score batch size must be positive")
    feature_by_trace = {feature["trace_id"]: feature for feature in feature_rows}
    ranking: dict[str | None, list[tuple[float, str, str]]] = {}
    summary = {
        "n": 0,
        "sum": 0.0,
        "min": None,
        "max": None,
        "n_alert": 0,
        "n_novelty": 0,
    }
    with tempfile.TemporaryDirectory(prefix="traj-score-") as directory:
        temporary_path = Path(directory) / "scores.jsonl"
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            for start in range(0, len(feature_rows), batch_size):
                batch_features = feature_rows[start : start + batch_size]
                batch_assigns = assigns[start : start + batch_size]
                rows = score.score_all(
                    batch_features,
                    batch_assigns,
                    stage,
                    artifact,
                    ontology,
                    cold_start=cold_start,
                    drift_map={trace_id: True for trace_id in drift_ids},
                    anchor_version=anchor_version,
                    model_version=PIPELINE_VERSION,
                )
                for row in rows:
                    row["a_cal"] = None
                    _attach_trace_time(row, feature_by_trace.get(row["trace_id"]))
                    _update_scoring_summary(summary, row)
                    ranking.setdefault(row["cell"], []).append(
                        (float(row["S"]), row["trace_id"], row["grade_abs"])
                    )
                    handle.write(
                        json.dumps(_slim_score_row(row), ensure_ascii=False, sort_keys=True) + "\n"
                    )
        grade_map = _relative_grade_map(ranking)
        with temporary_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    row["grade_rel"] = grade_map.get(row["trace_id"], row["grade_abs"])
                    score_sink(row)
    return {
        "n": summary["n"],
        "mean": summary["sum"] / summary["n"] if summary["n"] else None,
        "min": summary["min"],
        "max": summary["max"],
        "n_alert": summary["n_alert"],
        "n_novelty": summary["n_novelty"],
    }


def _update_scoring_summary(summary: dict, row: dict) -> None:
    value = float(row["S"])
    summary["n"] += 1
    summary["sum"] += value
    summary["min"] = value if summary["min"] is None else min(summary["min"], value)
    summary["max"] = value if summary["max"] is None else max(summary["max"], value)
    summary["n_alert"] += int(bool(row["alert"]))
    summary["n_novelty"] += int(bool(row["novelty"]))


def _relative_grade_map(
    ranking: dict[str | None, list[tuple[float, str, str]]],
    min_cell: int = 8,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for entries in ranking.values():
        if len(entries) < min_cell:
            for _score, trace_id, grade_abs in entries:
                result[trace_id] = grade_abs
            continue
        entries.sort(key=lambda item: (-item[0], item[1]))
        total = len(entries)
        for index, (_score, trace_id, _grade_abs) in enumerate(entries):
            fraction = index / float(total)
            result[trace_id] = (
                "A" if fraction < 0.25
                else "B" if fraction < 0.60
                else "C" if fraction < 0.85
                else "D"
            )
    return result


def write_production_report(report_dir: Path, result: dict, score_rows: list[dict]) -> Path:
    write_production_scores(report_dir, score_rows)
    write_production_metrics(report_dir, result)
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
    missing = [key for key in FROZEN_STATE_KEYS if key not in state
               and key != "_tfidf_ctx"]
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
    pattern_recipe: str | None = None,
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
            pattern_recipe=pattern_recipe or cluster.PATTERN_TOKEN_RECIPE,
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
            "embedding_dim": len(feature_rows[0]["embedding"]),
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
    tfidf_ctx = state.get("_tfidf_ctx")
    recipe = (tfidf_ctx or {}).get("config", {}).get(
        "span_key_recipe", cluster.PATTERN_TOKEN_RECIPE)
    vec_cache: dict = {}

    assigns = []
    for feature in feature_rows:
        embedding = feature["embedding"]
        intent = min(cl, key=lambda cluster_id: cluster.euclid(embedding, cents_i[cluster_id])) if cl else -1
        if tfidf_ctx is not None:
            skeleton = cluster.collapse(cluster.pattern_tokens(feature, recipe))
            pattern = (
                min(pl, key=lambda cluster_id: cluster.pattern_dist(
                    skeleton, med_p[cluster_id], tfidf_ctx, vec_cache))
                if pl
                else -1
            )
        else:
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


def _assert_frozen_embedding_compatible(state: dict, embedding_dim: int) -> None:
    expected = state.get("embedding_dim")
    if expected is None:
        expected = _legacy_frozen_embedding_dim(state)
    if not expected:
        raise EncoderContractError(
            "frozen structure predates intent embeddings and cannot label new "
            "traces; trigger a new R2 run with a configured IntentEncoder "
            "instead of reusing this structure"
        )
    if int(expected) != embedding_dim:
        raise EncoderContractError(
            f"embedding dimension mismatch with frozen structure "
            f"expected={expected} actual={embedding_dim}; the intent encoder or "
            "its input construction changed; trigger a new R2 run instead of "
            "reusing this structure"
        )


def _legacy_frozen_embedding_dim(state: dict) -> int:
    for vector in (state.get("cents_i") or {}).values():
        return len(vector)
    return 0


def _assert_frozen_structural_compatible(state: dict) -> None:
    ctx = state.get("_tfidf_ctx")
    fingerprint = (ctx or {}).get("fingerprint")
    if not fingerprint:
        raise EncoderContractError(
            "frozen structure predates the structural vectorizer fingerprint "
            "(E3); trigger a new R2 run instead of reusing this structure"
        )
    recipe = ctx.get("config", {}).get("span_key_recipe", cluster.PATTERN_TOKEN_RECIPE)
    expected = cluster.current_pattern_fingerprint(recipe)
    if fingerprint != expected:
        raise EncoderContractError(
            f"structural vectorizer fingerprint mismatch with frozen structure "
            f"expected={expected} actual={fingerprint} recipe={recipe}; the "
            "execution-view construction changed; trigger a new R2 run instead "
            "of reusing this structure"
        )


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
