"""The 77-feature contract (methodology appendix A) as a machine-checkable register.

"Is the dataset enough to start?" was answered in prose, and prose goes stale the moment the
generator changes. This module answers it mechanically instead: every contract feature declares
the raw span fields, raw trace fields and ontology keys it needs, and the status is *resolved*
against what the dataset and the ontology actually emit. Add a field to the generator and the
corresponding blocker clears itself; remove one and the audit fails the build.

Statuses
    implemented           kernel/features.py emits it (under this name or a documented alias)
    implemented_elsewhere  the pipeline computes it, but in detect/score/cluster, not as a
                           features.py key - it has no feature-vector column yet
    derivable              every raw input is present; this is kernel work, not dataset work
    blocked_field          a raw span/trace field the contract needs is not emitted
    blocked_ontology       an ontology key the contract needs is not declared
    needs_model            requires a real embedder / NLI / BERTScore. Cannot be synthesized,
                           and faking it would be worse than admitting it: the dataset supplies
                           the *inputs* and the *ground truth* so the plumbing is testable,
                           but the number itself is meaningless until a model is plugged in.

Only `blocked_field`, `blocked_ontology` and a failed fidelity check are dataset defects.
`derivable` and `needs_model` are not - they are the boundary of what synthetic data can do.

Fidelity is checked separately from presence, because a field can exist and still be too weak
to validate anything: a 16-dim isotropic Gaussian blob satisfies `query_embedding`'s type and
tells you nothing about whether the clustering survives 1024-dim anisotropic real embeddings.
"""

import re

IMPLEMENTED = "implemented"
IMPLEMENTED_ELSEWHERE = "implemented_elsewhere"
DERIVABLE = "derivable"
BLOCKED_FIELD = "blocked_field"
BLOCKED_ONTOLOGY = "blocked_ontology"
NEEDS_MODEL = "needs_model"

DATASET_BLOCKERS = (BLOCKED_FIELD, BLOCKED_ONTOLOGY)

# Contract feature names that the kernel emits under a different (v1-frozen) key. The alias is
# documented rather than renamed so that historical gate numbers stay comparable.
ALIASES = {
    "total_latency": "latency_total",
    "total_cost": "cost_total",
    "error_span_ratio": "error_level_ratio",
    "numeric_grounding_ratio": "traceable_number_ratio",
    "ungrounded_element_count": "unfaithful_fact_count",
    "entity_recall": "key_fact_recall",
    # Three contract names collide with a frozen v1 key of the same spelling that means
    # something else. The detection gates were calibrated on the v1 meaning, so the appendix
    # quantity is emitted under a new name and aliased here rather than the v1 key being
    # silently redefined.
    "total_tokens": "tokens_total_contract",        # + cache_read + cache_write
    "prompt_token_ratio": "system_prompt_ratio",    # system_prompt / input, not input / total
    "parallelism_ratio": "parallelism_ratio_contract",  # 1 - critical_path / sum(duration)
}

# name -> the contract feature it stands in for, with the substitution on the record
SUBSTITUTIONS = {
    "cluster_strength": ("consensus_intent/consensus_pattern",
                         "HDBSCAN membership strength has no analogue in a consensus-partition "
                         "clustering; the bagged co-association margin plays the same role as a "
                         "global confidence factor"),
}

# Contract features whose emitted column is a deliberate, documented approximation of the
# appendix formula. They still resolve to IMPLEMENTED -- the kernel really does emit a column
# under this name -- but the report prints the substitution, because anyone comparing the number
# against the appendix definition has to know the two are not the same statistic.
PROXIES = {
    "goal_drift_slope":
        "appendix asks 1 - cos(goal_emb, subgoal_k_emb) regressed on k; kernel emits 1 - "
        "|G n S_k| / |G| over language-aware content tokens, because embedding every subgoal "
        "would cost another 384 floats per span. Measured equivalent on this dataset: the "
        "generator guarantees an off-goal detour shares no content token with the goal, so the "
        "lexical proxy is exactly 1.0 on a detour and exactly 0.0 on-goal, and it agrees with "
        "goal_drift_true two-sided on 700/700 dev traces.",
    "goal_drift_max": "same lexical containment proxy as goal_drift_slope",
    "context_utilization":
        "appendix asks max *cumulative* input tokens / context window; kernel emits max "
        "per-call tokens_prompt / context window. Cumulative-across-calls would divide a "
        "running total by a budget that resets on every call, so it grows without bound and "
        "stops being a utilization. The per-call form is the quantity that actually predicts a "
        "context-overflow rejection.",
    "reformulation_signal":
        "appendix asks cos(this answer, next query); the dataset carries an embedding of the "
        "query only, so the kernel emits a trapezoidal membership of the [0.55, 0.90] band over "
        "the *mean-centred* cosine of consecutive query embeddings in one session, scaled by "
        "whether the follow-up got shorter. Centring is load-bearing: raw cosines sit in a "
        "narrow cone (0.22-0.94, median 0.80), so the band would fire on nearly every pair.",
    "self_correction_count":
        "appendix allows name-based detection (retry/fix/revise); the ontology has no such "
        "action names, so the kernel detects it structurally: a same-action sibling that starts "
        "after an earlier one finished and either replaces failed work or carries different "
        "arguments. Identical params with an identical outcome is a retry, already counted by "
        "retry_count.",
    "cost_per_step_of_progress":
        "appendix specifies MinHash LSH at 0.9; kernel computes exact character-3gram Jaccard. "
        "MinHash is an approximation of the same quantity, and at 6 spans per trace the exact "
        "form is cheaper than the sketch.",
    "query_len":
        "character length of the question with the dataset's constant `intentN:` cell tag "
        "stripped; leaving the tag in would add a per-cell offset that query_len cannot explain.",
    "plan_revision_count":
        "entry-action span nested inside an earlier entry-action span of the same parent. "
        "Nesting is what separates a revision from a loop, which repeats the step sequentially; "
        "the naive count-minus-one reads a looped plan as 2 revisions (1 dev trace in 700).",
}

# (n, group, name, span_fields, trace_fields, ontology_keys, alias_or_impl_name, note)
# span/trace/ontology entries are the RAW inputs; the resolver checks them mechanically.
CONTRACT = [
    # ---- A.1 structure (12) ----
    (1, "A.1", "n_spans", ["span_id"], ["spans"], [], None, ""),
    (2, "A.1", "depth", ["span_id", "parent_id"], ["spans"], [], None, ""),
    (3, "A.1", "max_width", ["span_id", "parent_id"], ["spans"], [], None, ""),
    (4, "A.1", "branch_factor", ["span_id", "parent_id"], ["spans"], [], None, ""),
    (5, "A.1", "kind_ratio_llm", ["kind"], ["spans"], [], None,
     "only llm/tool/retrieval are registered; the six kind ratios sum to 1 and are collinear"),
    (6, "A.1", "kind_ratio_tool", ["kind"], ["spans"], [], None, ""),
    (7, "A.1", "kind_ratio_retrieval", ["kind"], ["spans"], [], None, ""),
    (8, "A.1", "n_unique_tools", ["tool_name"], ["spans"], ["tool_catalog"], None,
     "tool identity is tool_name, not action: the ontology maps one action to several tools"),
    (9, "A.1", "tool_repeat_rate", ["tool_name"], ["spans"], [], None, ""),
    (10, "A.1", "loop_count", ["parent_id", "action", "tool_params"], ["spans"], ["param_keys"],
     None, "grouped by (parent_id, action, normalized param hash), max(0, count-2) over count>=3"),
    (11, "A.1", "longest_repeated_subseq", ["action"], ["spans"], [], None, ""),
    (12, "A.1", "error_span_ratio", ["level"], ["spans"], [], None, ""),

    # ---- A.2 latency (11) ----
    (13, "A.2", "total_latency", ["ts_start", "ts_end"], ["spans"], [], None, ""),
    (14, "A.2", "critical_path", ["span_id", "parent_id", "ts_start", "ts_end"], ["spans"], [],
     None, "longest root-to-leaf serial chain, ROOT EXCLUDED: the root spans the whole wall "
           "clock, so including it returns latency_total and drives #19 to exactly 0"),
    (15, "A.2", "ttft", ["ttft"], ["spans"], [], None, "conditional: llm/agent spans only"),
    (16, "A.2", "llm_time_ratio", ["kind", "ts_start", "ts_end", "parent_id"], ["spans"], [],
     None, "union of intervals, root span excluded"),
    (17, "A.2", "tool_time_ratio", ["kind", "ts_start", "ts_end", "parent_id"], ["spans"], [],
     None, "TOOL and RETRIEVAL must be unioned jointly"),
    (18, "A.2", "wait_time_ratio", ["ts_start", "ts_end", "parent_id"], ["spans"], [], None,
     "union of intervals, root span excluded"),
    (19, "A.2", "parallelism_ratio", ["ts_start", "ts_end", "parent_id"], ["spans"], [], None, ""),
    (20, "A.2", "span_latency_p95", ["ts_start", "ts_end", "parent_id"], ["spans"], [], None,
     "root span excluded"),
    (21, "A.2", "bottleneck_share", ["ts_start", "ts_end", "parent_id"], ["spans"], [], None,
     "root span excluded, otherwise identically 1.0"),
    (22, "A.2", "inter_step_gap_cv", ["ts_start", "ts_end"], ["spans"], [], None, ""),
    (23, "A.2", "retry_latency_share", ["parent_id", "action", "tool_params", "ts_start",
                                        "ts_end"], ["spans"], [], None,
     "a retry is a repeated (parent_id, action, param hash)"),

    # ---- A.3 cost (13) ----
    (24, "A.3", "total_tokens", ["tokens_prompt", "tokens_completion", "tokens_cache_read",
                                 "tokens_cache_write"], ["spans"], [], None,
     "contract total = input + output + cache_read + cache_write; the v1-frozen "
     "`tokens_total` is prompt + completion only and must NOT be silently redefined"),
    (25, "A.3", "input_tokens", ["tokens_prompt"], ["spans"], [], None, ""),
    (26, "A.3", "output_tokens", ["tokens_completion"], ["spans"], [], None, ""),
    (27, "A.3", "total_cost", ["cost"], ["spans"], ["unit_price"], None,
     "cost_details is only needed for per-component attribution, not for the total"),
    (28, "A.3", "cost_per_span", ["cost"], ["spans"], [], None, ""),
    (29, "A.3", "cost_per_step_of_progress", ["cost", "output_text"], ["spans"], [], None,
     "a step counts as progress when its output is not near-duplicate (MinHash < 0.9) of an "
     "earlier one; needs tool outputs with realistic redundancy"),
    (30, "A.3", "cost_concentration_gini", ["cost"], ["spans"], [], None, ""),
    (31, "A.3", "top1_cost_share", ["cost"], ["spans"], [], None, ""),
    (32, "A.3", "token_efficiency", ["tokens_prompt", "tokens_completion"], ["spans"], [], None,
     ""),
    (33, "A.3", "prompt_token_ratio", ["tokens_system_prompt", "tokens_prompt"], ["spans"], [],
     None, "contract definition is system_prompt_tokens / input_tokens. NAME COLLISION: the "
           "v1-frozen kernel feature of the same name is tokens_prompt / tokens_total, a "
           "different quantity. The contract one is emitted as `system_prompt_ratio`"),
    (34, "A.3", "cache_hit_ratio", ["tokens_cache_read", "tokens_prompt"], ["spans"], [], None,
     ""),
    (35, "A.3", "context_growth_slope", ["tokens_prompt", "ts_start"], ["spans"], [], None,
     "least-squares slope of (step index, cumulative input tokens)"),
    (36, "A.3", "model_mix_cost_index", ["model", "tokens_prompt", "tokens_completion"],
     ["spans"], ["models"], None, ""),

    # ---- A.4 semantics and behaviour (15) ----
    (37, "A.4", "query_embedding", [], ["embedding"], [], None,
     "clustering and similarity only; never enters the score formula"),
    (38, "A.4", "query_len", [], ["intent_text"], [], None, ""),
    (39, "A.4", "query_lang", [], ["query_lang"], [], None,
     "a stratification variable, not a numeric feature: token density differs per language, so "
     "mixing languages inside one cell pollutes the cost baseline"),
    (40, "A.4", "query_complexity", [], ["intent_text"], [], None,
     "composed from clause count, wh-word count and entity count; needs varied query wording "
     "within one intent, otherwise it is constant per cell and cannot explain anything"),
    (41, "A.4", "goal_drift_slope", ["subgoal_text"], ["intent_text", "goal_text"], [], None,
     "1 - cos(original goal, step-k subgoal), regressed on step index"),
    (42, "A.4", "goal_drift_max", ["subgoal_text"], ["intent_text", "goal_text"], [], None,
     "max of the same drift quantity; catches a single severe detour the slope averages away. "
     "The trace embedding is NOT an input: drift is measured against goal_text, not against the "
     "query embedding"),
    (43, "A.4", "self_correction_count", ["action", "tool_params", "status"], ["spans"], [], None,
     "retry/fix/revise naming, or near-identical params with a different result"),
    (44, "A.4", "plan_revision_count", ["action", "ts_start"], ["spans"], [], None,
     "needs the generator to emit more than one plan span when the plan is regenerated"),
    (45, "A.4", "tool_success_rate", ["kind", "status"], ["spans"], [], None, ""),
    (46, "A.4", "tool_arg_valid_rate", ["tool_name", "tool_params", "arg_valid"], ["spans"],
     ["param_schema"], None, "needs a JSON schema per tool plus injected invalid arguments"),
    (47, "A.4", "path_convergence", ["action"], ["spans"], [], None,
     "n-gram overlap between the second half and the first half of the action sequence"),
    (48, "A.4", "context_utilization", ["tokens_prompt", "model"], ["spans"],
     ["context_window"], None, "max cumulative input tokens / model context window"),
    (49, "A.4", "effective_info_ratio", ["input_text"], ["spans"], [], None,
     "1 - redundant context / total context, redundancy estimated by n-gram Jaccard between "
     "adjacent context fragments"),
    (50, "A.4", "n_turns_in_session", [], ["session_id", "turn_index"], [], None, ""),
    (51, "A.4", "reformulation_signal", [], ["session_id", "turn_index", "intent_text",
                                             "embedding"], [], None,
     "next-turn query vs this-turn answer: cosine in [0.55, 0.90] and shorter -> the user "
     "rephrased. Sessions are linked by session_id so this is a self-join, not a new field"),

    # ---- A.5 outcome conformance (13) ----
    (52, "A.5", "hard_fail_count", ["level", "status", "finish_reason", "output_text"],
     ["spans"], [], None, "> 0 triggers the scoring gate"),
    (53, "A.5", "verifier_pass_rate", ["verifier"], ["spans"], ["validators"], None,
     "the only zero-cost objective correctness signal; needs per-span verifier outcomes"),
    (54, "A.5", "numeric_grounding_ratio", ["output_facts"], ["answer_numbers"], [], None,
     "structured facts are the evidence pool; regex over prose is a legacy fallback that "
     "would scrape SQL LIMIT 200, /nbi/v1/ and NE-92F8-27 into it"),
    (55, "A.5", "ungrounded_element_count", ["output_facts"], ["answer_numbers",
                                                                "answer_facts"], [], None, ""),
    (56, "A.5", "citation_reachability", ["output_citations"], ["answer_citations"], [], None,
     "share of the answer's URLs / file paths / line numbers that actually occur in the "
     "retrieved result set; catches fabricated references"),
    (57, "A.5", "entity_recall", [], ["golden_facts", "answer_facts"], [], None, ""),
    (58, "A.5", "ref_similarity", [], ["golden_answer", "intent_text", "embedding"], [], None,
     "needs a real sentence encoder; the dataset supplies the golden text and a synthetic "
     "embedding so the plumbing runs, the value is not meaningful"),
    (59, "A.5", "bertscore_f1", [], ["golden_answer"], [], None,
     "needs contextual embeddings from a real model; cannot be synthesized"),
    (60, "A.5", "key_fact_recall", [], ["golden_facts", "answer_facts"], [], None,
     "the primary metric when a golden exists"),
    (61, "A.5", "nli_entailment", ["output_text"], ["golden_answer"], [], None,
     "needs a real cross-encoder; premise = concatenated tool outputs, hypothesis = answer "
     "clauses, length-weighted"),
    (62, "A.5", "contradiction_rate", ["output_facts"], ["contradicted_facts"], [], None,
     "the feature needs a real NLI model, but the DATASET must carry contradiction ground "
     "truth, and 'contradicts the evidence' is a different failure from 'not supported by "
     "the evidence'. > 0.1 is a strong anomaly"),
    (63, "A.5", "peer_z", [], ["embedding"], [], None,
     "z-distance to the centroid of successful peers inside the same cell"),
    (64, "A.5", "implicit_feedback", [], ["user_feedback", "session_id"], [], None,
     "MUST NEVER enter baseline METRICS: it correlates with the label by construction "
     "(weak supervision) and would inflate F1 trivially"),

    # ---- A.6 process consistency and metadata (8) ----
    (65, "A.6", "fitness_replay", ["action"], ["spans"], ["required_steps"], None,
     "token replay against the cell's reference process model, strict mode"),
    (66, "A.6", "fitness_align", ["action"], ["spans"], ["required_steps"], None,
     "optimal alignment allowing insertions and skips"),
    (67, "A.6", "missing_tokens", ["action"], ["spans"], ["required_steps"], None, ""),
    (68, "A.6", "remaining_tokens", ["action"], ["spans"], ["required_steps"], None, ""),
    (69, "A.6", "illegal_transition_count", ["action"], ["spans"], ["required_steps"], None, ""),
    (70, "A.6", "forbidden_step_hit", ["action"], ["spans"], ["forbidden_actions"], None,
     "a hit triggers the scoring gate"),
    (71, "A.6", "seq_sim_to_medoid", ["action"], ["spans"], [], None, ""),
    (72, "A.6", "tree_edit_distance_norm", ["span_id", "parent_id", "action"], ["spans"], [],
     None, "Zhang-Shasha / APTED against the cell's reference span tree"),

    # ---- A.7 data quality indicators (5) ----
    (73, "A.7", "ts_repaired", ["ts_start", "ts_end"], ["raw_flags"], [], None,
     "latency-dimension confidence x0.7"),
    (74, "A.7", "usage_estimated", ["tokens_prompt", "tokens_completion", "cost"],
     ["raw_flags"], [], None, "cost-dimension confidence x0.6"),
    (75, "A.7", "orphan_span_rebuilt", ["parent_id"], ["raw_flags"], [], None, ""),
    (76, "A.7", "missing_field_ratio", [], ["spans"], [], None,
     "measured BEFORE repair, over the per-span-kind conditionally available field set"),
    (77, "A.7", "cluster_strength", [], [], [], None, ""),
]

# Fidelity is a separate axis from presence: the field exists but may be too weak to validate
# anything built on it. Each entry is (feature, requirement text, checker).
EMB_DIM_CONTRACT_MIN = 384          # appendix A.4 #37: d = 384 / 768 / 1024
TEXT_VARIETY_MIN = 8                # distinct output skeletons per action
TEXT_VARIETY_MIN_OBS = 30           # spans an action needs before it is averaged into the above
QUERY_VARIETY_MIN = 8               # distinct query skeletons per intent
SIGNAL_RATE_MIN = 0.01              # min share of traces on which a binary signal must fire
# Upper bound on the embedding participation ratio, as a fraction of the dimension. An
# isotropic Gaussian blob has every dim carrying equal variance, so PR = dim exactly; a
# signal collapsed onto one dim has PR = 1. Neither can exercise the clustering view, and
# the dim check alone accepts both. 0.75 is deliberately loose: measured PR on this dataset
# is 40.0-125.9 of 384 (n=200 sample, R7 lowest / R6 highest), so the bound sits 2.3-7.2x
# above what the generator actually produces while still rejecting anything near isotropic.
EMB_PR_MAX_FRAC = 0.75


_SKELETON_RULES = [
    (re.compile(r"NE-[0-9A-Fa-f]{4}-\d+"), "#ne"),
    (re.compile(r"\b\d+(?:\.\d+)?[smhd]\b"), "#win"),
    (re.compile(r"-?\d+(?:\.\d+)?"), "#n"),
]


def skeleton(text):
    """Digit- and identifier-normalised form of a text.

    Counting raw strings lets one template that interpolates an NE identifier report
    thousands of "distinct" texts. Normalising NE ids, time windows and numbers away counts
    templates, which is what the appendix means by distinct realizations. Measured on the
    120-trace smoke run: raw-string counting reported 80.3 distinct outputs per action,
    inflated almost entirely by the interpolated numbers.
    """
    t = text or ""
    for pat, rep in _SKELETON_RULES:
        t = pat.sub(rep, t)
    return t


def _distinct_ratio(values, keys, min_obs=0):
    """Average number of distinct value skeletons per distinct key.

    Returns (mean, kept, n_keys_dropped) where `kept` maps each surviving key to
    (n_observations, n_distinct_skeletons). Keys with fewer than
    `min_obs` observations are dropped rather than counted as failures: a rare action cannot
    exhibit 8 distinct realizations in a finite sample, and averaging it in measures the
    sample size instead of the generator. Measured action counts on the 120-trace smoke run
    were agent_run 114, plan 20, sql_query 48, summarize 67, retrieve_kb 29,
    schema_retrieval 24, api_call 15, verify 3, approve 2, force_delete 1; the single-digit
    ones are purely small-sample, so the floor is what keeps the check honest on a small run
    without weakening it on a full one.
    """
    seen = {}
    for v, k in zip(values, keys):
        d = seen.setdefault(k, [set(), 0])
        d[1] += 1
        d[0].add(skeleton(v))
    kept = dict((k, (d[1], len(d[0]))) for k, d in seen.items() if d[1] >= min_obs)
    dropped = len(seen) - len(kept)
    if not kept:
        return 0.0, {}, dropped
    return sum(c for _, c in kept.values()) / float(len(kept)), kept, dropped


def _rate(pred, traces):
    """Share of traces satisfying `pred`; drives the signal-presence checks.
    """
    return sum(1 for t in traces if pred(t)) / float(len(traces)) if traces else 0.0

def participation_ratio(embs):
    """Effective number of dimensions carrying the signal: (sum v)^2 / sum v^2 over the
    per-dimension variance v. Returns dim for an isotropic blob (all v equal) and 1 when
    all the variance sits on a single dim, so it is the one scalar that separates a 384-dim
    embedding from a 384-dim embedding that actually has 384 independent directions.

    The bound `1.0 < PR < EMB_PR_MAX_FRAC * dim` is applied to the n=200 sample that
    `coverage.embedding_pr()` draws, so both ends were measured at that sample size instead of
    being assumed from the asymptotics.

      isotropic 384-d Gaussian, PR by n:  367.8 (n=50)  375.7 (100)  380.2 (200)
                                          382.4 (400)   383.3 (1000) 383.8 (4000)
        -> above the 288 ceiling at every n, so the upper bound has teeth even on the smallest
           sample the audit would ever draw.
      lower bound, n=200:  exactly one non-zero dim -> PR = 1.0000, rejected by the *strict*
           `1.0 <` (this is why the inequality is strict); constant vector -> 0.0; all-zero
           -> 0.0; energy on 7 dims -> 6.45; on 192 dims -> 190.1; the generator's own shape
           (16 signal dims over a flat 0.41 background) -> 17.2.

    PR reads as "effective dimensionality" across four orders of magnitude of anisotropy, which
    is what makes one scalar sufficient.

    Sampling bias, measured: the n=200 estimate runs *below* the whole-file value because
    per-dim variance is noisier on a small sample (the isotropic fixture drops from 383.8 at
    n=4000 to 367.8 at n=50). On the shipped dataset `coverage.embedding_pr()` reports
    40.0-125.9 while `meta.json`'s whole-file `emb_geometry.participation_ratio` is
    72.3-131.7. The two are not in conflict and neither is a typo; the audit's number is the
    smaller one. The underestimate is the direction that would matter if a future geometry were
    calibrated to sit near the ceiling, so re-measure at the audit's own sample size before
    moving `EMB_PR_MAX_FRAC`.
    """
    n = len(embs)
    d = len(embs[0]) if (embs and embs[0]) else 0
    if not n or not d:
        return 0.0
    mu = [sum(e[j] for e in embs) / n for j in range(d)]
    var = [sum((e[j] - mu[j]) ** 2 for e in embs) / n for j in range(d)]
    tot = sum(var)
    sq = sum(v * v for v in var)
    return (tot * tot) / sq if sq > 0 else 0.0


def fidelity_checks(bundle):
    """Mechanical fidelity checks over one regime's raw records.

    `bundle` is {"traces": [...], "emb_dim": int}. Returns {feature: (ok, measured,
    required)}.

    Presence and fidelity are different questions. A field can exist on every span and still
    be unable to validate anything built on it: a citation field that is never fabricated
    leaves citation_reachability pinned at 1.0, an arg_valid that is never False leaves
    tool_arg_valid_rate pinned at 1.0, and a 16-dim isotropic Gaussian blob satisfies
    query_embedding's type while telling you nothing about whether clustering survives
    384-dim anisotropic real embeddings. Every check below asserts that the variation the
    feature is supposed to measure is actually present in the data.
    """
    traces = bundle["traces"]
    out = {}

    dim = bundle.get("emb_dim")
    if dim is None:
        dim = len(traces[0].get("embedding") or []) if traces else 0
    # This check used to assert the dimension only, while its own `required` string already
    # promised "anisotropic, topic continuum" - and the docstring above names a 16-dim
    # isotropic blob as the exact failure mode. PR closes that gap. It is computed from the
    # data rather than read out of meta.json, so a future retune that silently collapses the
    # geometry fails here instead of surfacing much later as a clustering gate that no amount
    # of kernel work can lift.
    pr = participation_ratio([t.get("embedding") or [] for t in traces])
    pr_hi = EMB_PR_MAX_FRAC * dim
    out["query_embedding"] = (
        dim >= EMB_DIM_CONTRACT_MIN and 1.0 < pr < pr_hi,
        "%d dims, participation ratio %.1f (isotropic would be %d)" % (dim, pr, dim),
        ">= %d dims AND 1 < participation_ratio < %.2f x dim = %.0f (near dim means every "
        "direction is noise, near 1 means the topic signal collapsed onto a single dim)"
        % (EMB_DIM_CONTRACT_MIN, EMB_PR_MAX_FRAC, pr_hi))

    actions, outputs = [], []
    for t in traces:
        for s in t.get("spans") or []:
            actions.append(s.get("action"))
            outputs.append(s.get("output_text"))
    # Guard-kind actions are exempt from the per-action floor. A guard emits a verdict, so its
    # whole output vocabulary is "pass" and "block - policy violation", and skeletonising it
    # yields 2 forms no matter how many spans there are (measured on 200 traces: verify 67 spans
    # -> 2 skeletons, approve 39 -> 2). Demanding 8 would mean inventing verdicts that do not
    # exist, and the guard branch in bench/generate.py deliberately skips the out_frames wrapper
    # so that kernel/features.py can keep detecting a hit by the substring "block". Every
    # non-guard action clears 8 by a wide margin (measured weakest: plan 20 over 209 spans).
    kind_of = {}
    for t in traces:
        for s in t.get("spans") or []:
            kind_of.setdefault(s.get("action"), s.get("kind"))
    variety, kept, ndrop = _distinct_ratio(outputs, actions, TEXT_VARIETY_MIN_OBS)
    nonguard = dict((a, c) for a, (o, c) in kept.items() if kind_of.get(a) != "guard")
    weakest = sorted(nonguard.items(), key=lambda kc: kc[1])[:3]
    worst_n = min(nonguard.values()) if nonguard else 0
    out["effective_info_ratio"] = (
        variety >= TEXT_VARIETY_MIN and worst_n >= TEXT_VARIETY_MIN,
        "mean %.1f distinct output skeletons per action, weakest non-guard %s, over %d actions "
        "(%d below the %d-observation floor)"
        % (variety, weakest, len(kept), ndrop, TEXT_VARIETY_MIN_OBS),
        "mean >= %d AND every non-guard action >= %d (templated text makes every n-gram "
        "redundancy feature degenerate)" % (TEXT_VARIETY_MIN, TEXT_VARIETY_MIN))
    out["cost_per_step_of_progress"] = out["effective_info_ratio"]

    intents, texts = [], []
    for t in traces:
        intents.append((t.get("ontology_id"), t.get("intent_text", "").split(":", 1)[0]))
        texts.append(t.get("intent_text"))
    qvar, qkept, qndrop = _distinct_ratio(texts, intents)
    qworst = sorted(((k, c) for k, (o, c) in qkept.items()), key=lambda kc: kc[1])[:3]
    qmin = min([c for _, c in qkept.values()] or [0])
    out["query_complexity"] = (qvar >= QUERY_VARIETY_MIN and qmin >= QUERY_VARIETY_MIN,
                               "mean %.1f distinct query skeletons per intent, weakest %s, "
                               "over %d intents" % (qvar, qworst, len(qkept)),
                               "mean >= %d AND every intent >= %d (with one fixed phrase per "
                               "intent the feature is constant inside a cell)"
                               % (QUERY_VARIETY_MIN, QUERY_VARIETY_MIN))
    def _any_span(t, pred):
        return any(pred(s) for s in (t.get("spans") or []))

    def _cited(t):
        got = set()
        for s in (t.get("spans") or []):
            got.update(s.get("output_citations") or [])
        return got

    unreach = _rate(lambda t: bool(t.get("answer_citations"))
                    and not set(t["answer_citations"]) <= _cited(t), traces)
    out["citation_reachability"] = (unreach >= SIGNAL_RATE_MIN,
                                    "%.2f pct of traces cite something unreachable"
                                    % (100.0 * unreach),
                                    ">= %.2f pct (a citation field that is never fabricated pins "
                                    "the feature at 1.0)" % (100.0 * SIGNAL_RATE_MIN))

    inval = _rate(lambda t: _any_span(t, lambda s: s.get("arg_valid") is False), traces)
    out["tool_arg_valid_rate"] = (inval >= SIGNAL_RATE_MIN,
                                  "%.2f pct of traces carry an invalid tool argument"
                                  % (100.0 * inval),
                                  ">= %.2f pct (an arg_valid that is never False pins the "
                                  "feature at 1.0)" % (100.0 * SIGNAL_RATE_MIN))

    vfail = _rate(lambda t: _any_span(t, lambda s: bool(s.get("verifier"))
                                      and not s["verifier"].get("passed")), traces)
    out["verifier_pass_rate"] = (vfail >= SIGNAL_RATE_MIN,
                                 "%.2f pct of traces fail a validator" % (100.0 * vfail),
                                 ">= %.2f pct (a verifier that always passes carries no "
                                 "signal)" % (100.0 * SIGNAL_RATE_MIN))

    drift = _rate(lambda t: bool(t.get("goal_text")) and _any_span(
        t, lambda s: bool(s.get("subgoal_text"))), traces)
    out["goal_drift_max"] = (drift >= 0.50,
                             "%.1f pct of traces carry a goal and at least one subgoal"
                             % (100.0 * drift),
                             ">= 50 pct (goal_drift is a lexical containment test, so it needs "
                             "both a goal_text and a subgoal_text on the same trace)")

    return out


def resolve(span_fields, trace_fields, ontology_keys, impl_keys, emb_dim=None):
    """Resolve every contract feature to a status against what is actually emitted."""
    impl = set(impl_keys)
    rows = []
    for n, group, name, sfields, tfields, okeys, _alias, note in CONTRACT:
        miss_span = sorted(f for f in sfields if f not in span_fields)
        miss_trace = sorted(f for f in tfields if f not in trace_fields)
        miss_onto = sorted(k for k in okeys if k not in ontology_keys)
        impl_name = ALIASES.get(name, name)
        if name in SUBSTITUTIONS:
            status, detail = IMPLEMENTED_ELSEWHERE, "substituted by %s" % SUBSTITUTIONS[name][0]
        elif miss_span or miss_trace:
            status = BLOCKED_FIELD
            detail = "missing " + ", ".join(
                ["span.%s" % f for f in miss_span] + ["trace.%s" % f for f in miss_trace])
        elif miss_onto:
            status = BLOCKED_ONTOLOGY
            detail = "missing ontology " + ", ".join(miss_onto)
        elif name in ("ref_similarity", "bertscore_f1", "nli_entailment", "contradiction_rate"):
            status, detail = NEEDS_MODEL, "inputs present"
        elif impl_name in impl:
            status, detail = IMPLEMENTED, ("as `%s`" % impl_name if impl_name != name else "")
            if name in PROXIES:
                detail = (detail + " | " if detail else "") + "proxy: " + PROXIES[name]
        elif name in ("hard_fail_count", "forbidden_step_hit", "illegal_transition_count",
                      "fitness_replay", "fitness_align", "missing_tokens", "remaining_tokens",
                      "seq_sim_to_medoid", "peer_z", "cluster_strength",
                      # A.7 #73/#74/#75 are per-trace booleans the kernel keeps in the `flags`
                      # dict rather than as scalar columns; detect._CONF_PENALTY and score.py
                      # both read them from there.
                      "ts_repaired", "usage_estimated", "orphan_span_rebuilt"):
            status, detail = IMPLEMENTED_ELSEWHERE, "computed in detect/score/cluster"
        else:
            status, detail = DERIVABLE, "kernel work only"
        rows.append({"n": n, "group": group, "name": name, "status": status, "detail": detail,
                     "note": note, "missing_span": miss_span, "missing_trace": miss_trace,
                     "missing_ontology": miss_onto})
    return rows


def summarize(rows, fidelity=None):
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    blockers = [r for r in rows if r["status"] in DATASET_BLOCKERS]
    bad_fidelity = []
    for r in rows:
        if fidelity and r["name"] in fidelity and not fidelity[r["name"]][0]:
            bad_fidelity.append((r["name"], fidelity[r["name"]]))
    return {"counts": counts, "blockers": blockers, "bad_fidelity": bad_fidelity,
            "n": len(rows), "ok": not blockers and not bad_fidelity}