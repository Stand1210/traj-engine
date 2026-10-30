"""Dataset coverage audit: does bench_v1 actually carry the raw material the 77-feature
contract (methodology appendix A) asks for, and is every emitted feature non-degenerate?

A feature that is constant across a regime cannot exercise the detector built on it, so
"the dataset exists" and "the dataset is sufficient" are different claims. This module
answers the second one mechanically, and is meant to be re-run whenever the generator or
the ontology changes.

Run:
    python -m bench.coverage            # ASCII report to stdout
    python -m bench.coverage --md       # also write data/bench_v1/COVERAGE.md (zh)

Console output is ASCII only (GBK-safe); Chinese lives in COVERAGE.md.
"""
import collections
import hashlib
import io
import json
import os
import sys

from kernel import ingest, features
from ontology.base import get_ontology
from bench import contract as CT

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "bench_v1")
REGIMES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
SAMPLE_N = 1500
# fields that identify a trace rather than describe it, plus post-repair diagnostics that
# are constant by construction (missing_field_ratio_post is 0 exactly when normalize worked)
NON_FEATURES = ("ts_start", "missing_field_ratio_post")

ANOMALY_TYPES = ["latency_spike", "token_bloat", "loop", "error", "missing_step",
                 "illegal_step", "unfinished", "truncation", "hallucinated_number"]

# Raw fields the contract needs but a span/trace may or may not carry. Each entry maps to
# the appendix-A features that become unimplementable without it.
REQUIRED_FIELDS = {
    "span": {
        "model": ["model_mix_cost_index", "per-model cost/latency baselines"],
        "ttft": ["ttft (A.2 #15)"],
        "tool_name": ["n_unique_tools", "tool_repeat_rate", "loop_count (param hash)"],
        "tool_params": ["loop_count (A.1 #10 needs normalized param hash)"],
        "level": ["error_span_ratio at WARN vs ERROR granularity"],
        "status_message": ["error taxonomy / retry classification"],
        "prompt_version": ["score reproducibility across prompt/model versions"],
        "tokens_system_prompt": ["system_prompt_ratio (A.3 #33)"],
        "tokens_cache_read": ["cache_hit_ratio (A.3 #34)", "total_tokens (A.3 #24)"],
        "tokens_cache_write": ["total_tokens (A.3 #24)", "cost_share_cache_write"],
        "cost_details": ["the five cost attribution shares (A.3)"],
        "arg_valid": ["tool_arg_valid_rate (A.4 #46)"],
        "subgoal_text": ["goal_drift_slope / goal_drift_max (A.4 #41/#42)"],
        "output_citations": ["citation_reachability (A.5 #56), retrieved side"],
        "verifier": ["verifier_pass_rate (A.5 #53)"],
    },
    "trace": {
        "golden_answer": ["ref_similarity", "bertscore_f1", "key_fact_recall"],
        "user_feedback": ["implicit_feedback (A.5 #64, Tier-6 weak supervision)"],
        "turn_index": ["multi-turn session context / abandonment detection"],
        "session_id": ["n_turns_in_session / reformulation_signal (A.4 #50/#51)"],
        "session_turn_count": ["n_turns_in_session cross-check against the session recount"],
        "query_lang": ["query_lang (A.4 #39) cell stratification"],
        "goal_text": ["goal_drift_* (A.4 #41/#42) reference vocabulary"],
        "answer_citations": ["citation_reachability (A.5 #56), cited side"],
        "contradicted_facts": ["contradiction_rate ground truth (A.5 #62)"],
    },
}

# Contract features that have a second, kernel-independent implementation in `probe` below.
# They used to be "computable but not yet implemented"; as of slice1-v0.1.0 the kernel emits
# all of them, so the list now drives a differential test instead of a gap list: if the two
# implementations disagree, one of them is not computing the corrected appendix-A formula.
# Measured on R1 (n=1500): the nine union-of-intervals features agree to max|diff| = 0.0
# exactly, which is the evidence that kernel/features.py implements the corrected formulas.
CROSSCHECK = ["max_width", "depth", "n_unique_tools", "tool_repeat_rate",
              "longest_repeated_subseq", "span_latency_p95", "bottleneck_share",
              "inter_step_gap_cv", "llm_time_ratio", "tool_time_ratio", "wait_time_ratio",
              "parallelism_ratio", "busy_union"]


def _load(rid):
    path = os.path.join(DATA, rid, "traces.jsonl")
    with io.open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _gt(rid):
    path = os.path.join(DATA, rid, "gt.jsonl")
    with io.open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _qs(vals):
    v = sorted(vals)
    if not v:
        return None
    return (v[0], v[len(v) // 2], v[int(0.99 * (len(v) - 1))], v[-1])


def _quant(sv, q):
    """Linear-interpolated quantile over an ascending list. Deliberately a second copy of
    kernel/features._quant: a differential test that imports the thing it is testing proves
    nothing."""
    if not sv:
        return None
    v = sorted(sv)
    if len(v) == 1:
        return v[0]
    h = (len(v) - 1) * q
    lo = int(h)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (h - lo) * (v[hi] - v[lo])


def _union_len(intervals):
    """Measure of the union of [start, end) intervals; the only correct way to aggregate
    durations when sibling spans may overlap (parallel tool calls)."""
    if not intervals:
        return 0.0
    iv = sorted(intervals)
    total = 0.0
    cur_s, cur_e = iv[0]
    for s, e in iv[1:]:
        if s > cur_e:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    return total + cur_e - cur_s


def probe(trace):
    """Derive the not-yet-implemented contract features, using union-of-intervals for every
    ratio so that overlapping siblings cannot push a share below 0 or above 1."""
    spans = trace["spans"]
    kids = collections.defaultdict(list)
    for s in spans:
        kids[s.get("parent_id")].append(s)
    roots = kids.get(None, [])
    root = roots[0] if roots else None
    wall = max(s["ts_end"] for s in spans) - min(s["ts_start"] for s in spans)
    wall = wall if wall > 0 else 1e-9
    children = [s for s in spans if s is not root]
    iv = lambda ss: [(s["ts_start"], s["ts_end"]) for s in ss]
    busy = _union_len(iv(children))

    depth = 0
    width = collections.Counter()
    stack = [(r, 1) for r in roots]
    while stack:
        s, d = stack.pop()
        depth = max(depth, d)
        width[d] += 1
        stack.extend((c, d + 1) for c in kids.get(s["span_id"], []))

    durs = sorted(s["ts_end"] - s["ts_start"] for s in children) or [0.0]
    ordered = sorted(children, key=lambda s: s["ts_start"])
    gaps = [g for g in (ordered[i + 1]["ts_start"] - ordered[i]["ts_end"]
                        for i in range(len(ordered) - 1)) if g > 0]
    mu = sum(gaps) / len(gaps) if gaps else 0.0
    var = sum((g - mu) ** 2 for g in gaps) / len(gaps) if gaps else 0.0

    # tool identity is `tool_name`, not `action`: the ontology maps one action to several
    # tools, so counting actions understates the tool vocabulary (measured max|diff| = 2 on R1
    # when probe counted actions). Spans with no tool_name are not tool calls.
    tools = [s["tool_name"] for s in spans if s.get("tool_name")]
    seq = [s["action"] for s in spans]
    best = 0
    for length in range(2, len(seq) // 2 + 1):
        seen = set()
        for i in range(len(seq) - length + 1):
            key = tuple(seq[i:i + length])
            if key in seen:
                best = max(best, length)
            seen.add(key)
    uniq = len(set(tools))
    sum_kid = sum(s["ts_end"] - s["ts_start"] for s in children)

    def kind_ratio(k):
        return _union_len(iv([s for s in children if s["kind"] == k])) / wall

    return {
        "max_width": max(width.values()) if width else 0,
        "depth": depth,
        "n_unique_tools": uniq,
        # None (not 0.0) whenever the denominator is empty, matching the kernel: a trace with
        # no tool call has an undefined repeat rate, not a repeat rate of zero.
        "tool_repeat_rate": (1.0 - uniq / float(len(tools))) if tools else None,
        "longest_repeated_subseq": best,
        # linear interpolation, not nearest rank: on 5-12 child spans the two differ by up to
        # 458 s (measured R1) because nearest rank stops one order statistic short of the tail.
        "span_latency_p95": _quant(durs, 0.95),
        "bottleneck_share": (durs[-1] / wall) if durs else None,
        "inter_step_gap_cv": ((var ** 0.5) / mu) if mu > 0 else None,
        "llm_time_ratio": kind_ratio("llm"),
        # tool and retrieval spans can overlap each other, so union them jointly; adding
        # two separate unions can exceed 1 (measured max 1.088 before this fix)
        "tool_time_ratio": _union_len(iv([s for s in children
                                          if s["kind"] in ("tool", "retrieval")])) / wall,
        "wait_time_ratio": (wall - busy) / wall,
        "parallelism_ratio": (1.0 - busy / sum_kid) if sum_kid > 0 else None,
        "busy_union": busy,
    }


def contract_audit(regimes=None, sample=200):
    """Resolve the 77-feature appendix-A contract against what the dataset actually emits.

    Field sets are unioned across regimes (a field only one regime emits is still a field) and
    ontology keys across every ontology in use; `impl_keys` is what `features.extract` really
    returns. Returns (rows, fidelity, summary).
    """
    regimes = regimes or REGIMES
    span_fields, trace_fields, onto_keys, ontos = set(), set(), set(), set()
    impl_keys, fidelity = None, None
    for rid in regimes:
        traces = _load(rid)[:sample]
        ontos.add(traces[0]["ontology_id"])
        trace_fields.update(traces[0].keys())
        for sp in traces[0]["spans"]:
            span_fields.update(sp.keys())
        ont = get_ontology(traces[0]["ontology_id"])
        if impl_keys is None:
            f0 = features.extract(ingest.normalize(traces[0], ont), ont)
            # `str` is in the tuple because A.4 #39 query_lang is a categorical column: it is a
            # genuinely emitted feature, and without `str` the resolver would report it as
            # DERIVABLE even though kernel/features.py returns it. `audit()` deliberately keeps
            # the narrower numeric-only test, because "is this string constant" is not the
            # variability question audit() asks of a feature column.
            impl_keys = [k for k in f0
                         if isinstance(f0[k], (int, float, str)) or f0[k] is None]
        if fidelity is None:
            fidelity = CT.fidelity_checks({"traces": traces})
    for oid in ontos:
        onto_keys.update(get_ontology(oid).keys())
    rows = CT.resolve(span_fields, trace_fields, onto_keys, impl_keys)
    return rows, fidelity, CT.summarize(rows, fidelity)


def report_contract(rows, fidelity, summ):
    print("")
    print("=== appendix-A 77-feature contract: dataset support ===")
    for st in CT_ORDER:
        print("  %-22s %3d" % (st, summ["counts"].get(st, 0)))
    print("  %-22s %3d" % ("TOTAL", summ["n"]))
    if summ["blockers"]:
        print("")
        print("  DATASET BLOCKERS (%d):" % len(summ["blockers"]))
        for r in summ["blockers"]:
            print("    #%-3d %-28s %-17s %s" % (r["n"], r["name"], r["status"], r["detail"]))
    else:
        print("  [PASS] no dataset blockers")
    print("")
    for name in sorted(fidelity):
        ok, got, want = fidelity[name]
        print("  [%s] fidelity %-26s got: %-40s want: %s"
              % ("PASS" if ok else "FAIL", name, got, want))


DASH = u"\u2014"
SEP = u"\uff5c"
NOT_RUN = u"\uff08\u672a\u8fd0\u884c\uff09"
FID_OK = u"**\u8fbe\u6807**"
FID_BAD = u"**\u4e0d\u8fbe\u6807**"
NO_BLOCKERS = (u"- **\u65e0**\u3002\u9644\u5f55 A \u7684 77 \u4e2a\u7279\u5f81\u91cc\uff0c"
               u"\u6ca1\u6709\u4efb\u4f55\u4e00\u4e2a\u56e0\u4e3a\u7f3a\u539f\u59cb\u5b57\u6bb5"
               u"\u6216\u7f3a\u672c\u4f53\u952e\u800c\u65e0\u6cd5\u5b9e\u73b0\u3002")

CT_ORDER = [CT.IMPLEMENTED, CT.IMPLEMENTED_ELSEWHERE, CT.DERIVABLE, CT.BLOCKED_FIELD,
            CT.BLOCKED_ONTOLOGY, CT.NEEDS_MODEL]


def crosscheck(rid="R1", sample=SAMPLE_N):
    """Differential test: independent `probe()` implementation vs `kernel/features.extract`.

    Reports, per feature, the largest absolute disagreement over the sample plus how many
    traces both sides called undefined. A zero max|diff| on the nine union-of-intervals
    features is the evidence that the kernel really computes the corrected appendix-A
    formulas, and not merely that some code somewhere returns a number in [0, 1].
    """
    traces = _load(rid)[:sample]
    ont = get_ontology(traces[0]["ontology_id"])
    worst = dict((k, 0.0) for k in CROSSCHECK)
    both_none = collections.Counter()
    disagree = collections.Counter()
    n = 0
    for t in traces:
        norm = ingest.normalize(t, ont)
        f = features.extract(norm, ont)
        pr = probe(norm)
        n += 1
        for k in CROSSCHECK:
            a, b = f.get(k), pr.get(k)
            if a is None and b is None:
                both_none[k] += 1
            elif a is None or b is None:
                disagree[k] += 1
            else:
                d = abs(float(a) - float(b))
                if d > worst[k]:
                    worst[k] = d
    return {"n": n, "maxdiff": worst, "both_none": both_none, "disagree": disagree}


RATIO_FEATURES = ("llm_time_ratio", "tool_time_ratio", "guard_time_ratio", "wait_time_ratio",
                  "bottleneck_share", "parallelism_ratio")


def truth_agreement(regimes=None):
    """Label <-> truth <-> feature agreement, over every trace of every regime.

    This is the check that catches a benchmark asking the kernel to detect a signal the data
    does not contain. It found a real one: the loop injector duplicated a span skeleton but
    tool_params were drawn from the advancing per-trace stream, so 7 of the 26 R1 traces
    labelled `loop` had no parameter-identical repeat in them at all - `gt.loop_true` was
    False on a trace whose `anomaly_types` said `loop`. Every check below is a two-sided
    equivalence wherever the generator promises one.
    """
    regimes = regimes or REGIMES
    bad = collections.Counter()
    counts = {"n": 0, "golden": 0, "feedback": 0, "loop": 0, "plan_revision": 0,
              "goal_drift": 0, "contradiction": 0, "fabricated_citation": 0,
              "arg_invalid_span": 0, "verifier_fail": 0, "cache_hit_span": 0,
              "multi_turn": 0}
    for rid in regimes:
        traces = _load(rid)
        gts = dict((g["trace_id"], g) for g in _gt(rid))
        ont = get_ontology(traces[0]["ontology_id"])
        forbidden = set(ont.get("forbidden_actions") or [])
        required = ont.get("required_steps") or {}
        # Batched on purpose. annotate_sessions() has to see whole sessions; extracting one
        # trace at a time would leave n_turns_in_session at its captured value and
        # reformulation_signal permanently None, which makes the session equivalence below
        # untestable rather than failing it. `nm` is the normalized record so the structural
        # invariants are checked on what the kernel actually reads, not on the raw file.
        norms = [ingest.normalize(t, ont) for t in traces]
        flist = [features.extract(nm, ont) for nm in norms]
        features.annotate_sessions(flist, traces)
        for t, nm, f in zip(traces, norms, flist):
            g = gts[t["trace_id"]]
            counts["n"] += 1
            types = set(g.get("anomaly_types") or [])
            seq = set(f["action_seq"])
            if abs((f["missing_field_ratio"] or 0.0) - g["mfr_true"]) > 1e-3:
                bad["mfr_disagrees_with_truth"] += 1
            if (f["loop_count"] > 0) != bool(g["loop_true"]):
                bad["loop_feature_disagrees_with_truth"] += 1
            if ("loop" in types) != bool(g["loop_true"]):
                bad["loop_label_disagrees_with_truth"] += 1
            counts["loop"] += 1 if g["loop_true"] else 0
            if g["has_golden"]:
                counts["golden"] += 1
                if not t.get("golden_facts"):
                    bad["golden_flag_without_facts"] += 1
                for fk, gk in (("key_fact_recall", "key_fact_recall_true"),
                               ("fact_precision", "fact_precision_true")):
                    if g[gk] is None or f[fk] is None or abs(f[fk] - g[gk]) > 1e-3:
                        bad["%s_disagrees_with_truth" % fk] += 1
            else:
                if f["key_fact_recall"] is not None:
                    bad["recall_present_without_golden"] += 1
            if f["has_feedback"]:
                counts["feedback"] += 1
            if "hallucinated_number" in types:
                r = f["traceable_number_ratio"]
                if r is not None and r >= 1.0:
                    bad["hallucination_not_visible_in_traceability"] += 1
                if g["has_golden"] and (f["fact_precision"] or 1.0) >= 1.0:
                    bad["hallucination_not_visible_in_precision"] += 1
            if "illegal_step" in types and not (seq & forbidden):
                bad["illegal_step_without_forbidden_action"] += 1
            if "truncation" in types and not any(
                    sp.get("finish_reason") == "length" for sp in t["spans"]):
                bad["truncation_without_length_finish"] += 1
            if "error" in types and not any(sp.get("status") == "error" for sp in t["spans"]):
                bad["error_label_without_error_span"] += 1
            if "missing_step" in types:
                need = set(required.get(g["pattern_id"]) or ())
                if need and need <= seq:
                    bad["missing_step_with_all_required_present"] += 1
            # ---- v3: feature <-> truth equivalences, two-sided ----------------------
            def _same(a, b, tol=1e-6):
                return (a is None) == (b is None) and (a is None or abs(a - b) <= tol)

            if not _same(f["tool_arg_valid_rate"], g["arg_valid_true"]):
                bad["arg_valid_feature_disagrees_with_truth"] += 1
            if not _same(f["verifier_pass_rate"], g["verifier_pass_true"]):
                bad["verifier_feature_disagrees_with_truth"] += 1
            if not _same(f["citation_reachability"], g["citation_reachable_true"]):
                bad["citation_feature_disagrees_with_truth"] += 1
            if (f["plan_revision_count"] > 0) != bool(g["plan_revision_true"]):
                bad["plan_revision_feature_disagrees_with_truth"] += 1
            if bool(f["goal_drift_max"] is not None and f["goal_drift_max"] >= 0.5) \
                    != bool(g["goal_drift_true"]):
                bad["goal_drift_feature_disagrees_with_truth"] += 1
            if f["query_lang"] != g["query_lang_true"]:
                bad["query_lang_feature_disagrees_with_truth"] += 1
            if f["n_turns_in_session"] != g["session_turn_count_true"]:
                bad["session_turns_recount_disagrees_with_truth"] += 1
            if f["cache_read_tokens"] != g["cache_read_true"]:
                bad["cache_read_feature_disagrees_with_truth"] += 1
            if f["cache_write_tokens"] != g["cache_write_true"]:
                bad["cache_write_feature_disagrees_with_truth"] += 1
            # system_prompt_ratio is only comparable when normalize() did not have to impute a
            # prompt volume, because the imputation legitimately changes the denominator. On the
            # 700-trace dev sample 93 traces disagreed and all 93 carried usage_estimated; what
            # has to hold on every trace is that neither token component exceeds its own prompt.
            if not nm["flags"]["usage_estimated"] and not _same(
                    f["system_prompt_ratio"], g["system_prompt_ratio_true"]):
                bad["system_prompt_ratio_disagrees_with_truth"] += 1
            for rk in ("system_prompt_ratio", "cache_hit_ratio"):
                if f[rk] is not None and f[rk] > 1.0 + 1e-9:
                    bad["token_component_exceeds_prompt:%s" % rk] += 1

            # ---- v3: structural invariants on the emitted record --------------------
            for spn in nm["spans"]:
                cdet = spn.get("cost_details")
                if cdet and spn.get("cost") is not None and \
                        abs(sum(cdet.values()) - spn["cost"]) > 1e-9 + 1e-9 * abs(spn["cost"]):
                    bad["cost_details_not_additive"] += 1
                if (spn.get("tokens_cache_read") or 0) > (spn.get("tokens_prompt") or 0):
                    bad["cache_read_exceeds_prompt"] += 1
                if (spn.get("tokens_system_prompt") or 0) > (spn.get("tokens_prompt") or 0):
                    bad["system_prompt_exceeds_prompt"] += 1
                if spn.get("tokens_cache_read") and spn.get("tokens_cache_write"):
                    bad["cache_read_and_write_both_nonzero"] += 1
                if spn.get("verifier") and not spn["verifier"].get("id"):
                    bad["verifier_without_id"] += 1

            # ---- v3: co-defect ground truth must be reproducible and coherent -------
            cf = set(t.get("contradicted_facts") or [])
            af = set(t.get("answer_facts") or [])
            if not cf <= af:
                bad["contradicted_fact_not_in_answer"] += 1
            exp_cf = round(len(cf & af) / float(len(af)), 6) if af else None
            if not _same(exp_cf, g["contradiction_true"]):
                bad["contradiction_truth_not_reproducible"] += 1
            if cf:
                counts["contradiction"] += 1
                if not g["is_anomaly"]:
                    bad["contradiction_without_anomaly"] += 1
            if g["fabricated_citation_count"]:
                counts["fabricated_citation"] += 1
                if not g["is_anomaly"]:
                    bad["fabricated_citation_without_anomaly"] += 1
            if g["goal_drift_true"]:
                counts["goal_drift"] += 1
                if not g["is_anomaly"]:
                    bad["goal_drift_without_anomaly"] += 1
            if g["plan_revision_true"]:
                counts["plan_revision"] += 1
            if (f["n_turns_in_session"] or 0) > 1:
                counts["multi_turn"] += 1
            counts["arg_invalid_span"] += sum(
                1 for spn in t["spans"] if spn.get("arg_valid") is False)
            counts["verifier_fail"] += sum(
                1 for spn in t["spans"]
                if spn.get("verifier") and not spn["verifier"].get("passed"))
            counts["cache_hit_span"] += sum(
                1 for spn in t["spans"] if (spn.get("tokens_cache_read") or 0) > 0)

            # a fabricated citation must actually be absent from the retrieved set, otherwise
            # citation_reachability cannot see it
            if g["fabricated_citation_count"]:
                got = set()
                for spn in t["spans"]:
                    got.update(spn.get("output_citations") or [])
                cited = set(t.get("answer_citations") or [])
                if cited <= got:
                    bad["fabricated_citation_still_reachable"] += 1
            for k in RATIO_FEATURES:
                v = f[k]
                if v is not None and (v < -1e-9 or v > 1.0 + 1e-9):
                    bad["ratio_out_of_range:%s" % k] += 1
    return bad, counts


def audit(regimes=None, sample=SAMPLE_N):
    regimes = regimes or REGIMES
    out = {"regimes": {}, "fields": {"trace": set(), "span": set()}, "gaps": []}
    impl_keys = None
    for rid in regimes:
        traces = _load(rid)
        gts = _gt(rid)
        ont = get_ontology(traces[0]["ontology_id"])
        out["fields"]["trace"].update(traces[0].keys())
        for s in traces[0]["spans"]:
            out["fields"]["span"].update(s.keys())
        head = traces[:sample]
        norms = [ingest.normalize(t, ont) for t in head]
        feats = [features.extract(n, ont) for n in norms]
        # Without this call n_turns_in_session keeps the captured value and
        # reformulation_signal stays None on every trace, which audit() would then report as a
        # constant feature. A sampled head truncates sessions at the boundary; that is fine
        # here because audit() only asks whether a feature varies, never whether it is right -
        # truth_agreement() runs the full list and does ask.
        features.annotate_sessions(feats, head)
        impl_keys = [k for k in feats[0]
                     if isinstance(feats[0][k], (int, float)) and k not in NON_FEATURES]
        acc = collections.defaultdict(list)
        nones = collections.Counter()
        for f in feats:
            for k in impl_keys:
                if f.get(k) is None:
                    nones[k] += 1
                else:
                    acc[k].append(f[k])
        deriv = collections.defaultdict(list)
        for n in norms:
            for k, v in probe(n).items():
                if v is not None:  # probe now returns None for empty denominators, as the
                    deriv[k].append(v)  # kernel does; None is "undefined", not a value
        types = collections.Counter()
        for g in gts:
            for a in g.get("anomaly_types") or []:
                types[a] += 1
        out["regimes"][rid] = {
            "n": len(traces),
            "n_sampled": len(head),
            # Counted on the intent *slot* prefix, not on the full string. The generator
            # interpolates an NE identifier and a time window into every wording, so the raw
            # string is unique per trace and this reported n_traces instead of the number of
            # intents the regime declares.
            "intents": len(set(t["intent_text"].split(":", 1)[0] for t in traces)),
            "emb_dim": len(traces[0]["embedding"]),
            "impl": dict((k, {"distinct": len(set(round(v, 6) for v in acc[k])),
                              "none_rate": nones[k] / float(len(head)), "qs": _qs(acc[k])})
                         for k in impl_keys),
            "deriv": dict((k, {"distinct": len(set(round(v, 6) for v in deriv[k])),
                               "qs": _qs(deriv[k])}) for k in CROSSCHECK),
            "anomalies": types,
            "n_anomaly": sum(1 for g in gts if g.get("is_anomaly")),
        }
    # --- gap detection -----------------------------------------------------
    span_fields = out["fields"]["span"]
    trace_fields = out["fields"]["trace"]
    for scope, table in (("span", span_fields), ("trace", trace_fields)):
        for field, blocked in REQUIRED_FIELDS[scope].items():
            if field not in table:
                out["gaps"].append("missing field `%s.%s` blocks: %s"
                                   % (scope, field, ", ".join(blocked)))
    # a feature that is constant on *every* regime is a single finding, not N of them
    constant = collections.defaultdict(list)
    for rid, r in out["regimes"].items():
        for k, info in r["impl"].items():
            if info["distinct"] <= 1:
                constant[("implemented", k, info["qs"][0] if info["qs"] else None)].append(rid)
        for k, info in r["deriv"].items():
            if info["distinct"] <= 1:
                constant[("derivable", k, info["qs"][0] if info["qs"] else None)].append(rid)
    for (kind, key, val), rids in sorted(constant.items()):
        out["gaps"].append("%s feature `%s` is constant (%s) on %s -- any detector built on "
                           "it is untested" % (kind, key, val, "/".join(rids)))
    return out


# A gap that has been investigated and consciously accepted carries its disposition here, so the
# audit report says *why* the hole is there instead of making every reader re-derive it. Keyed by
# a substring of the gap text; the value is rendered as an indented continuation of the same
# bullet. House rule applies: the entry has to carry the measurement that forced the decision and
# the alternatives that were rejected, negative results included.
#
# Dispositions are documentation only. They never enter the exit code, and adding one is not a way
# to make a finding disappear - the gap line itself is still printed verbatim above it.
GAP_DISPOSITIONS = [
    ("`reformulation_signal` is constant (0.0) on R3", u"""处置：**接受并记录，不修**——这是 regime 的属性，不是审计漏洞。
判定带 [0.55, 0.90] 是附录 A.4 #51 的合同值，作用在**会话内去均值**后的余弦上（原始余弦挤在
窄锥里，带内命中率 71.1%–100.0%，8/8 regime，特征会退化成常数）。去均值后 7 个 regime 的
命中率是 6.87%–28.95%，**R3 是 0 / 2344 对**：R3 独有 `intent_ambiguity = 0.50`，它把每个
向量都拖向**其他**意图的均值，去均值后的向量彼此靠拢，整个 R3 的去均值余弦上界只有 0.371，
够不到 0.55 的下沿。方向与直觉相反——歧义**压缩**去均值余弦，不是把它顶过带。
三条修法实测否决：带值不可动（合同项，且 7/8 regime 依赖它）；把 R3 歧义降到 0.55 会让
`novelty_rate` 掉到 0.0063（低于 0.03 下限），而 R3 本来只剩 4.4% 的上限余量；生成器主动发射
改写追问是唯一真修，代价是新 `GEN_VERSION` + 全量重生成 + 全矩阵重跑，只为修一个 7/8 regime
已覆盖的特征。逐 regime 实测表见 `kernel/features.py::_band_membership` 的 docstring。
gap 不进退出码，本条不影响 DATASET READY。"""),
]


def gap_disposition(gap):
    for key, txt in GAP_DISPOSITIONS:
        if key in gap:
            return txt
    return None


def _fmt_q(qs, nd=4):
    if not qs:
        return "all-None"
    return "min=%-9.4g p50=%-9.4g p99=%-9.4g max=%-9.4g" % qs


def report(res):
    print("=== bench_v1 coverage audit ===")
    print("emitted trace fields: %s" % ", ".join(sorted(res["fields"]["trace"])))
    print("emitted span  fields: %s" % ", ".join(sorted(res["fields"]["span"])))
    print("")
    print("=== anomaly x regime coverage ===")
    print("%-22s %s" % ("type", "  ".join("%6s" % r for r in res["regimes"])))
    for atype in ANOMALY_TYPES:
        print("%-22s %s" % (atype, "  ".join(
            "%6d" % res["regimes"][r]["anomalies"].get(atype, 0) for r in res["regimes"])))
    print("%-22s %s" % ("TOTAL anomalies", "  ".join(
        "%6d" % res["regimes"][r]["n_anomaly"] for r in res["regimes"])))
    print("")
    print("=== dataset shape ===")
    for rid, r in res["regimes"].items():
        print("%s n=%4d sampled=%4d intents=%d emb_dim=%d anomaly_rate=%.2f%%"
              % (rid, r["n"], r["n_sampled"], r["intents"], r["emb_dim"],
                 100.0 * r["n_anomaly"] / r["n"]))
    for rid, r in res["regimes"].items():
        print("")
        print("--- %s implemented features (kernel/features.py) ---" % rid)
        for k in sorted(r["impl"]):
            info = r["impl"][k]
            print("  %-26s distinct=%5d none=%5.1f%%  %s"
                  % (k, info["distinct"], 100.0 * info["none_rate"], _fmt_q(info["qs"])))
        print("--- %s cross-check vs independent probe() (contract appendix A) ---" % rid)
        for k in CROSSCHECK:
            info = r["deriv"][k]
            print("  %-26s distinct=%5d              %s" % (k, info["distinct"], _fmt_q(info["qs"])))
        break  # one regime in full; the rest are summarised by the gap list
    print("")
    print("=== gaps (%d) ===" % len(res["gaps"]))
    for g in res["gaps"]:
        print("  - %s" % g)
        disp = gap_disposition(g)
        if disp:
            for line in disp.split("\n"):
                print("      %s" % line)
    return 0


NARRATIVE = u"""# bench_v1 \u6570\u636e\u96c6\u8986\u76d6\u5ea6\u5ba1\u8ba1

\u7531 `python -m bench.coverage --md` \u751f\u6210\u3002\u56de\u7b54\u4e00\u4e2a\u95ee\u9898\uff1a**\u6570\u636e\u96c6\u5b58\u5728** \u4e0e **\u6570\u636e\u96c6\u8db3\u591f** \u662f\u4e24\u4ef6\u4e8b\u3002
\u5728\u67d0\u4e2a regime \u4e0a\u6052\u5b9a\u4e0d\u53d8\u7684\u7279\u5f81\uff0c\u65e0\u6cd5\u9a8c\u8bc1\u5efa\u5728\u5b83\u4e0a\u9762\u7684\u68c0\u6d4b\u5668\uff1b\u539f\u59cb\u5b57\u6bb5\u7f3a\u5931\u7684\u7279\u5f81\uff0c\u65e0\u8bba\u600e\u4e48\u5199\u4ee3\u7801\u90fd\u5b9e\u73b0\u4e0d\u4e86\u3002

## \u4e00\u3001\u5f53\u524d\u53d1\u5c04\u7684\u5b57\u6bb5

%(fields)s

## \u4e8c\u3001\u7ed3\u8bba\uff1a\u53ef\u4ee5\u5f00\u5de5

\u751f\u6210\u5668 `bench-gen-v2.2.0`\uff5c22800 \u6761\u8f68\u8ff9 / 117502 \u4e2a Span / 1851 \u6761\u5f02\u5e38 / 8 \u4e2a regime\uff5c\u5168\u90e8\u53ef\u590d\u73b0\uff08\u79cd\u5b50\u56fa\u5b9a\uff0c\u4e3b\u968f\u673a\u6d41\u672a\u88ab v2 \u5b57\u6bb5\u6270\u52a8\uff09\u3002

**\u5df2\u5e26\u771f\u503c\u3001\u53ef\u76f4\u63a5\u652f\u6491\u5f00\u53d1\u7684**
- \u7ed3\u6784 / \u65f6\u5ef6 / \u6210\u672c\u4e09\u7ec4\u4e3b\u5e72\u7279\u5f81\u5168\u90e8\u975e\u9000\u5316\uff08`latency_total` \u5728\u6bcf\u4e2a regime \u4e0a distinct \u2248 n\uff09
- \u53cc\u5cf0 / \u4e09\u5cf0 / \u91cd\u53e0 / \u7a00\u758f / \u6b8b\u7f3a / \u51b7\u542f\u52a8 / \u6f02\u79fb / \u5f02\u672c\u4f53 8 \u4e2a\u5206\u5e03 regime
- 9 \u7c7b\u5f02\u5e38 \u00d7 8 regime \u5168\u8986\u76d6\uff0c\u6bcf\u683c\u81f3\u5c11 4 \u6761\uff08\u7b2c\u56db\u8282\u77e9\u9635\uff09
- **\u7ed3\u679c\u7b26\u5408\u5ea6\u7ec4\uff08A.5\uff0cO \u7ef4\u6743\u91cd 0.40\uff09**\uff1a\u8f68\u8ff9\u5e26 `golden_answer` / `golden_facts`\uff0c\u5b9e\u6d4b 5875 \u6761\uff0825.8%%\uff0cgolden \u53ea\u5728\u6570\u503c\u578b\u7b54\u6848\u4e0a\u53d1\u5c04\uff09\uff0c\u771f\u503c\u5e26 `key_fact_recall_true` / `fact_precision_true` / `hallucinated_facts`\u3002\u201c\u4e0d\u5b8c\u6574\u201d\u4e0e\u201c\u4e0d\u5fe0\u5b9e\u201d\u88ab\u523b\u610f\u5206\u5f00\uff1a\u622a\u65ad / \u672a\u5b8c\u6210 / \u7f3a\u6b65\u53ea\u538b recall\uff0c\u7f16\u9020\u6570\u5b57\u53ea\u538b precision
- **\u6210\u672c\u7ec4**\uff1aSpan \u5e26 `model`\uff08\u542b\u4ef7\u683c\u500d\u7387\uff09\u3001`ttft`\u3001`prompt_version`\uff08\u7ea6 10~12%% \u6302\u5728 canary \u7248\u672c\u4e0a\uff09\uff0c\u771f\u503c\u5e26 `model_mix_true`\uff0c`model_mix_cost_index` \u5df2\u975e\u9000\u5316
- **\u5de5\u5177\u8eab\u4efd\u4e0e\u53c2\u6570**\uff1aSpan \u5e26 `tool_name` / `tool_params`\uff0c`loop_count` \u6309\u5408\u540c A.1 #10 \u7528 `(parent_id, action, \u53c2\u6570\u54c8\u5e0c)` \u5206\u7ec4\uff0c\u4e0d\u518d\u662f\u52a8\u4f5c\u8fde\u8dd1\u8fd1\u4f3c\uff1b\u771f\u503c\u5e26 `loop_true`\uff0c\u5168\u6570\u636e\u96c6 201 \u6761\u771f\u5faa\u73af\uff0c\u6807\u7b7e\u4e0e\u771f\u503c 0 \u5904\u4e0d\u4e00\u81f4
- **\u5f31\u76d1\u7763\uff08Tier-6\uff09**\uff1a5760 \u6761\uff0825.3%%\uff09\u5e26 `user_feedback`\uff08thumbs / retry / abandoned / human_takeover\uff09\u4e0e `turn_index`\uff0c\u53cd\u9988\u6309\u6f5c\u6807\u7b7e\u52a0\u566a\u91c7\u6837\uff0c\u771f\u503c\u5e26 `feedback_available`
- **\u6570\u636e\u8d28\u91cf\u4f4d**\uff1a`missing_field_ratio` \u5728\u4fee\u590d**\u4e4b\u524d**\u6d4b\u91cf\uff0c\u6309 Span \u7c7b\u578b\u7684\u6761\u4ef6\u53ef\u5f97\u5b57\u6bb5\u96c6\u7edf\u8ba1\uff1bR1 p50=0.0000 / p99=0.1000\uff0cR5\uff0845%% \u6b8b\u7f3a\u6ce8\u5165\uff09p50=0.0250 / p99=0.2000\uff0c`kernel/score.py:130` \u7684 `mfr > 0.20` \u5206\u652f\u88ab\u771f\u5b9e\u89e6\u53d1
- **\u672c\u4f53\u5fc5\u987b\u6b65\u9aa4 + \u7981\u6b62\u52a8\u4f5c** \u2192 A.6 \u8fc7\u7a0b\u4e00\u81f4\u6027\u7ec4\uff088 \u4e2a\u7279\u5f81\uff09\u53ef\u76f4\u63a5\u5b9e\u73b0

**\u4ecd\u7136\u4e0d\u8db3\u3001\u5f00\u5de5\u65f6\u5fc5\u987b\u77e5\u9053\u7684**
- **\u8bed\u4e49\u6587\u672c\u662f\u6a21\u677f\uff0c\u4e0d\u662f\u81ea\u7531\u6563\u6587**\u3002`input_text` / `output_text` \u7531\u672c\u4f53 `action_text` \u6a21\u677f\u751f\u6210\uff0cintent \u77ed\u8bed\u53ea\u6709 2~4 \u79cd\u3002A.4 \u8bed\u4e49\u884c\u4e3a\u7ec4\u91cc\u51e1\u662f\u8981\u8dd1\u771f\u5b9e NLP \u7684\u7279\u5f81\uff08`ref_similarity`\u3001`bertscore_f1`\u3001\u8bed\u6c14/\u60c5\u611f\uff09\u5728\u672c\u6570\u636e\u96c6\u4e0a\u53ea\u80fd\u9a8c\u7ba1\u9053\u901a\u4e0d\u901a\uff0c\u4e0d\u80fd\u9a8c\u6548\u679c
- **\u6570\u503c\u53ef\u8ffd\u6eaf\u6027\u8d70\u7ed3\u6784\u5316\u5b57\u6bb5**\u3002\u8bc1\u636e\u6765\u6e90\u662f `output_facts` / `answer_numbers`\uff0c\u6b63\u5219\u626b\u6563\u6587\u53ea\u662f legacy \u515c\u5e95\u3002\u771f\u5b9e\u6587\u672c\u91cc\u7684\u6570\u5b57\uff08SQL `LIMIT 200`\u3001`/nbi/v1/`\u3001`NE-92F8-27`\uff09\u4f1a\u88ab\u6b63\u5219\u8bef\u6293\u8fdb\u8bc1\u636e\u6c60\uff0c\u63a5\u771f\u5b9e\u4e1a\u52a1\u65f6\u5fc5\u987b\u6362\u6210\u7ed3\u6784\u5316\u5b57\u6bb5\u6216\u5e26\u7c7b\u578b\u7684\u62bd\u53d6\u5668
- **\u5d4c\u5165\u662f 16 \u7ef4\u5404\u5411\u540c\u6027\u9ad8\u65af blob**\uff0c\u771f\u5b9e\u662f 1024 \u7ef4\u5404\u5411\u5f02\u6027\u3001\u8bdd\u9898\u8fde\u7eed\u8c31 \u2192 \u805a\u7c7b\u95e8\u69db\u5728\u771f\u5b9e\u6570\u636e\u4e0a\u5fc5\u7136\u66f4\u96be\uff0c\u672c\u57fa\u51c6\u7684 ARI \u4e0a\u754c\u4e0d\u53ef\u5916\u63a8
- **v2 \u7279\u5f81\u5df2\u53d1\u5c04\u4f46\u672a\u63a5\u7ebf**\u3002`kernel/baseline.py:METRICS` \u4ecd\u662f v1 \u7684 11 \u4e2a\u6307\u6807\uff1bv2 \u7684 40+ \u4e2a\u7279\u5f81\u5728 `features.extract` \u91cc\u53ef\u53d6\uff0c\u4f46\u6ca1\u8fdb\u57fa\u7ebf\u3001\u6ca1\u8fdb\u6253\u5206\u3002\u63a5\u7ebf\u662f\u9700\u8981\u5355\u72ec\u6d4b\u91cf\u7684\u4e00\u8f6e\u5de5\u4f5c\uff08slice2\uff09
- **`implicit_feedback` \u6c38\u8fdc\u4e0d\u80fd\u8fdb METRICS**\u3002\u5b83\u4e0e\u6807\u7b7e\u6309\u8bbe\u8ba1\u76f8\u5173\uff08\u5f31\u76d1\u7763\uff09\uff0c\u8fdb\u57fa\u7ebf\u4f1a\u5e73\u51e1\u5730\u5237\u9ad8 F1

## \u4e09\u3001\u5ba1\u8ba1\u53d1\u73b0\u7684\u786c\u95ee\u9898\uff08\u5747\u5df2\u4fee\u590d\uff0c\u9644\u5b9e\u6d4b\u8bc1\u636e\uff09

**1. `missing_field_ratio` \u7ed3\u6784\u6027\u6052\u4e3a 0\u3002**
`kernel/ingest.py` \u539f\u5148\u5148\u4fee\u590d\u7f3a\u5931\u5b57\u6bb5\u518d\u7edf\u8ba1\u7f3a\u5931\u6570\uff0c\u6240\u4ee5\u5305\u62ec R5\uff08\u6ce8\u5165 45%% \u6b8b\u7f3a\uff09\u5728\u5185\u7684\u6240\u6709 regime \u4e0a\u5b83\u90fd\u662f 0\uff1adistinct=1\u3001\u503c\u6052 0.0\u3002\u540e\u679c\u662f `kernel/score.py:130` \u7684 `if mfr > 0.20` \u662f\u6b7b\u5206\u652f\uff0c\u9644\u5f55 A.7 \u8981\u6c42\u7684\u201c\u7f3a\u5931\u6bd4\u4f8b\u53c2\u4e0e\u5168\u5c40\u7f6e\u4fe1\u5ea6\u201d\u4ece\u672a\u88ab\u9a8c\u8bc1\u3002
\u4fee\u6cd5\uff1a\u5728\u4fee\u590d**\u4e4b\u524d**\u5148\u91cf\u4e00\u6b21\u539f\u59cb\u7f3a\u5931\u7387\uff0c\u5e76\u6309 Span \u7c7b\u578b\u7ed9\u6761\u4ef6\u53ef\u5f97\u5b57\u6bb5\u96c6 `EXPECTED_FIELDS`\uff08\u5de5\u5177 Span \u5408\u6cd5\u5730\u4e0d\u5e26 token\uff0c\u6df7\u8fdb\u53bb\u91cf\u7684\u5c31\u662f Span \u7c7b\u578b\u914d\u6bd4\u800c\u4e0d\u662f\u9065\u6d4b\u4e22\u5931\uff09\uff1b\u4fee\u590d\u540e\u7684\u503c\u53e6\u5b58\u4e3a `missing_field_ratio_post`\uff0c\u4e0d\u8986\u76d6\u539f\u503c\u3002
\u5b9e\u6d4b\uff1aR1 p50=0.0000 / p99=0.1000\uff0cR5 p50=0.0250 / p99=0.2000\u3002

**2. \u9644\u5f55 A \u91cc\u5360\u6bd4\u7c7b\u7279\u5f81\u7684\u516c\u5f0f\u5728\u5e76\u884c\u5b50 Span \u4e0b\u8d8a\u754c\u3002**
\u516c\u5f0f\u5199\u7684\u662f\u201c\u603b\u8017\u65f6\u51cf\u53bb\u6839\u8282\u70b9\u5404\u5b50 Span \u8017\u65f6\u201d\uff0c\u9690\u542b\u5047\u8bbe\u5b50 Span \u4e92\u4e0d\u91cd\u53e0\u3002\u672c\u57fa\u51c6\u6709 22%% \u6982\u7387\u751f\u6210\u91cd\u53e0\u5144\u5f1f\uff08\u5e76\u884c\u5de5\u5177\u8c03\u7528\uff0c\u771f\u5b9e\u573a\u666f\u540c\u6837\u4f1a\u91cd\u53e0\uff09\u3002
\u5b9e\u6d4b\u6309\u539f\u516c\u5f0f\uff1a`wait_time_ratio` \u6700\u4f4e **\u22121.94**\uff0c`llm_time_ratio` \u6700\u9ad8 **2.78**\uff0c`tool_time_ratio` \u4e0e retrieval \u5206\u522b\u6c42\u5e76\u96c6\u518d\u76f8\u52a0\u4f1a\u5230 **1.088**\uff1b\u6839 Span \u6309\u6784\u9020\u8986\u76d6\u5168\u90e8\u58c1\u949f\uff0c\u6240\u4ee5 `bottleneck_share` **\u6052\u7b49\u4e8e 1.0**\u3002
\u4fee\u6cd5\uff1a\u5360\u6bd4\u7c7b\u7279\u5f81\u4e00\u5f8b\u6539\u7528**\u533a\u95f4\u5e76\u96c6\u957f\u5ea6**\uff08`_union_len`\uff09\uff0ctool \u4e0e retrieval \u5fc5\u987b**\u8054\u5408**\u6c42\u5e76\u96c6\uff0c\u4e14\u4e00\u5f8b**\u6392\u9664\u6839 Span**\u3002
\u5b9e\u6d4b\u4fee\u590d\u540e\uff1a`wait_time_ratio` \u2208 [5.4e-06, 0.3737]\uff0c`llm_time_ratio` \u2264 1.0\uff0c`tool_time_ratio` \u2264 0.9685\uff0c`bottleneck_share` \u2208 [0.2158, 1.0]\uff1b\u5168\u91cf 22800 \u6761\u8f68\u8ff9\u8d8a\u754c\u8ba1\u6570 0\uff08\u7b2c\u4e03\u8282\uff09\u3002\u9644\u5f55 A \u7684\u516c\u5f0f\u884c\u5df2\u540c\u6b65\u6539\u6b63\u3002

**3. \u4e24\u4e2a\u8ba9\u5faa\u73af\u4fe1\u53f7\u5728\u6570\u636e\u91cc\u6839\u672c\u4e0d\u5b58\u5728\u7684\u751f\u6210\u5668\u7f3a\u9677\u3002**
(a) \u5de5\u5177\u53c2\u6570\u4e0d\u786e\u5b9a\uff1a\u5faa\u73af\u6ce8\u5165\u5668 `dict(base)` \u590d\u5236\u9aa8\u67b6\uff0c\u4f46 `tool_params` \u4ece\u63a8\u8fdb\u7684\u6bcf\u8f68\u8ff9\u968f\u673a\u6d41\u91cc\u62bd\uff0c\u590d\u5236\u51fa\u7684\u4e24\u4efd\u53c2\u6570\u4e0d\u540c\uff0c\u4e8e\u662f\u201c\u53c2\u6570\u5b8c\u5168\u76f8\u540c\u7684\u91cd\u590d\u201d\u6839\u672c\u4e0d\u5b58\u5728\u3002\u5b9e\u6d4b R1\uff1a`loop` \u6807\u7b7e 26 \u6761\u3001`loop_true` 23 \u6761\u3001\u4e24\u8005\u4e00\u81f4 19 \u6761\uff0c**7 \u6761\u88ab\u6807\u4e3a loop \u7684\u8f68\u8ff9\u91cc\u6570\u636e\u4e2d\u6ca1\u6709\u5faa\u73af**\u3002\u4fee\u6cd5\uff1a`_tool_identity(ont, action, ne, win, trace_id, cache)`\uff0c(\u8f68\u8ff9, \u52a8\u4f5c) \u7684\u7eaf\u51fd\u6570\u3002\u4fee\u590d\u540e 8 \u4e2a regime \u4e0a\u6807\u7b7e\u4e0e `loop_true` 0 \u5904\u4e0d\u4e00\u81f4\uff0c\u5168\u6570\u636e\u96c6\u771f\u5faa\u73af 201 \u6761\u3002
(b) \u5e7b\u5f71\u91cd\u590d Span\uff1a\u5e76\u884c\u5206\u652f\u53d1\u5c04\u5668\u63d0\u524d\u8ffd\u52a0\u7b2c k+1 \u6b65\u5e76\u628a `raw_w[k+1]` \u6e05\u96f6\u540e `continue`\uff0c\u4f46 `for` \u5faa\u73af\u8df3\u4e0d\u8fc7\u4e0b\u4e00\u6b21\u8fed\u4ee3\uff0c\u7b2c k+1 \u6b65\u53c8\u88ab\u8ffd\u52a0\u4e00\u6b21\uff0c\u53d8\u6210 4 ms \u9000\u5316 Span\u3002\u5b83\u628a `n_spans` \u62ac\u9ad8\u7ea6 10%%\uff0c\u628a\u76f8\u90bb\u540c\u52a8\u4f5c\u585e\u8fdb 22%% \u7684\u8f68\u8ff9\uff0c\u7ed9 `retry_count` \u548c `loop_count` \u5582\u5047\u4fe1\u53f7\u3002\u4fee\u6cd5\uff1a\u628a\u62bd\u7b7e\u63d0\u5230 `parallel = (k + 1 < len(steps)) and rng.random() < 0.22`\uff08\u4fdd\u7559\u539f\u77ed\u8def\u8bed\u4e49\uff0c\u968f\u673a\u6d41\u4e0d\u53d8\uff09+ \u4e00\u4e2a `skipped` \u6807\u5fd7\u3002Span \u603b\u6570 132648 \u2192 **117502**\uff08\u6bcf\u6761\u8f68\u8ff9 5.8 \u2192 \u7ea6 5.2\uff09\u3002

**4. R4 \u5728\u5e73\u7a33\u6570\u636e\u4e0a\u8bef\u62a5\u6f02\u79fb\uff08\u4e24\u5904\u6210\u56e0\u53e0\u52a0\uff09\u3002**
R4\uff08\u6781\u7a00\u758f\u683c\u5b50\uff0cn=1200\uff0c\u683c\u5b50\u5927\u5c0f 507/333/187/83/34/22/11/7/7/5/2/2\uff09\u5728\u5e73\u7a33\u6570\u636e\u4e0a\u62a5\u51fa\u4e86\u53d8\u70b9\u3002
\u6210\u56e0\u4e00\uff1a\u6700\u6162\u7684\u610f\u56fe `i3`\uff0892 \u6761\uff09\u5728\u683c\u5b50\u5c42\u4e0e\u7236\u5c42\u90fd\u4e0d\u8db3 30 \u6761\u53c2\u8003\u89c2\u6d4b\uff0c\u4e8e\u662f\u56de\u843d\u5230**\u5168\u5c40**\u57fa\u7ebf\uff0c\u800c\u5168\u5c40\u628a 1.5s \u7684\u603b\u4f53\u548c 120s \u7684\u603b\u4f53\u6df7\u5728\u4e00\u8d77 \u2192 z \u6052\u6b63\uff08`z_mean_ref = 0.181`\uff09\u3002\u539f\u59cb\u6570\u636e\u5176\u5b9e\u5e73\u7a33\uff086 \u4e2a\u5206\u6876\u7684\u6bcf\u610f\u56fe\u4e2d\u4f4d\u6570\uff1ai0 1.53/1.46/1.64/1.51/1.70/1.59\uff1bi1 9.63/8.39/8.71/9.43/8.81/10.19\uff09\u3002\u4fee\u6cd5\uff1a\u9636\u68af\u6539\u4e3a `cell \u2192 parent \u2192 \u5f03\u6743(z=None)`\uff0c**\u53d6\u6d88\u5168\u5c40\u515c\u5e95**\uff1b\u65b0\u589e `MAX_ABSTAIN_SHARE = 0.50`\uff0c\u8d85\u8fc7\u5c31\u8fd4\u56de `drift=False, reason="insufficient_support"`\uff08\u660e\u786e\u4e0d\u662f\u201c\u65e0\u6f02\u79fb\u201d\uff09\u3002\u4fee\u590d\u540e `z_mean_ref` 0.181 \u2192 0.041\uff0c\u4f46\u544a\u8b66\u4ecd\u5728\uff08\u7edf\u8ba1\u91cf 44.6 vs \u03bb 10.6\uff09\u3002
\u6210\u56e0\u4e8c\uff1a\u03bb \u662f\u4ece\u4e00\u4e2a\u4e2d\u5fc3**\u5df2\u7ecf\u6070\u597d\u7b49\u4e8e\u81ea\u8eab\u4e2d\u4f4d\u6570**\u7684\u7b26\u53f7\u5e8f\u5217\u91cc\u81ea\u4e3e\u51fa\u6765\u7684\uff0c\u96f6\u5047\u8bbe\u91cc**\u4e0d\u542b\u4e2d\u5fc3\u4f30\u8ba1\u8bef\u5dee**\u3002\u6bcf\u683c\u5b50\u53c2\u8003\u6837\u672c n = 112/67/30\uff0c30 \u4e2a\u5bf9\u6570\u6b63\u6001\u6837\u672c\u7684\u4e2d\u4f4d\u6570\u504f\u5dee\u8db3\u4ee5\u628a\u683c\u5b50 `i2|p2` \u7684\u5c3e\u90e8\u63a8\u5230 68.8%% \u9ad8\u4e8e\u5408\u5e76\u4e2d\u5fc3\u3002\u4fee\u6cd5\uff1a`calibrate_lambda(ref_z, \u2026)` \u6539\u6536\u539f\u59cb z \u503c\uff0c\u6bcf\u6b21\u91cd\u590d\u62bd**\u4e24\u4e2a**\u5757\u81ea\u4e3e\u91cd\u91c7\u6837\u2014\u2014A\uff08\u53c2\u8003\u957f\u5ea6\uff09\u4f9b `centre = median(A)`\uff0cB\uff08\u76d1\u6d4b\u957f\u5ea6\uff09\u5bf9\u7740\u5b83\u6253\u5206\u3002\u5b9e\u6d4b **\u03bb 10.6 \u2192 75.8**\uff0c\u7edf\u8ba1\u91cf 44.6 \u2192 \u4e0d\u518d\u68c0\u51fa\uff1bR7 \u7684\u771f\u6f02\u79fb\u4e0d\u53d7\u5f71\u54cd\uff08\u7edf\u8ba1\u91cf 996.8 vs \u03bb 65.0\uff0c\u6ede\u540e +8\uff09\u3002

**5. \u5f03\u6743\u4f1a\u628a\u805a\u7c7b\u8d28\u91cf\u4e70\u9ad8\uff0cR1 \u5df2\u5b9e\u6d4b\u5230\u8fd9\u4ef6\u4e8b\u3002**
`ari_pattern` \u53ea\u5728\u201c\u53ef\u5f52\u7c07\u6c60\u201d\u4e0a\u7b97\uff0c\u6240\u4ee5\u628a\u96be\u6837\u672c\u4e22\u8fdb novelty \u7f13\u51b2\u533a\u5c31\u80fd\u9760\u5c11\u6253\u5206\u6765\u591a\u5f97\u5206\u3002R1 \u5b9e\u6d4b\uff1a\u7f13\u51b2\u533a 433 \u6761\uff0810.8%% \u6d41\u91cf\uff09\uff0c\u5173\u6389\u5f03\u6743\u540e `ari_pattern` = 0.8368\uff0c\u6c60\u4e0a = 0.9856\uff0c\u5f03\u6743\u51c0\u4e70 **+0.149**\u3002\u800c\u7f13\u51b2\u533a\u91cc\u4e0d\u662f\u6a21\u7cca\u6837\u672c\uff1a`novelty_purity_pattern` = 0.9908\uff0c433 \u6761\u91cc 380 \u6761\u5c5e\u4e8e\u540c\u4e00\u4e2a\u771f\u5b9e\u6a21\u5f0f\uff1b\u6210\u56e0\u662f\u6a21\u5f0f\u89c6\u56fe\u5bf9 3 \u4e2a\u771f\u5b9e\u6a21\u5f0f\u8fd4\u56de\u4e86 k=6\uff0c\u5176\u4e2d\u4e00\u4e2a 383 \u6761\u7684\u788e\u7247\uff08\u7eaf\u5ea6 0.9922\uff09\u62ff\u5230\u4e86 \u22120.44 \u7684\u6210\u5458\u5e73\u5747\u5171\u8bc6\uff0c\u4e8e\u662f `(a\u2212b)/max(a,b)` \u8fb9\u9645\u628a\u4e00\u6b21**\u8fc7\u5ea6\u5207\u5206**\u8bfb\u6210\u4e86\u201c\u6211\u53eb\u4e0d\u51fa\u5b83\u5c5e\u4e8e\u54ea\u4e00\u7c7b\u201d\u3002\u7f13\u51b2\u533a\u5f02\u5e38\u7387 0.0901 \u9ad8\u4e8e\u6c60\u5185 0.0732\uff0c\u5373\u5f03\u6743\u6070\u597d\u4e22\u6389\u4e86\u98ce\u9669\u66f4\u9ad8\u7684\u90a3\u4e00\u7247\u3002
\u73b0\u72b6\uff1a`bench/runner.py` \u5df2\u628a `ari_*_all`\uff08\u5f03\u6743\u524d\uff09\u4e0e `novelty_purity_*` \u4e00\u5e76\u8f93\u51fa\u5230 `metrics.json` \u4e0e `report.md`\uff0c\u4f7f\u8fd9\u7b14\u4ea4\u6613\u65e0\u6cd5\u9690\u85cf\uff1b\u805a\u7c7b\u6a21\u578b\u987a\u5e8f\u672c\u8eab\u5c5e\u4e8e slice2\uff0c\u672a\u5728\u672c\u8f6e\u6539\u52a8\u3002R1 \u95e8\u7981\u53ea\u7ea6\u675f `novelty_rate \u2208 [0, 0.25]`\uff0c0.108 \u901a\u8fc7\u3002

## \u56db\u3001\u5f02\u5e38 \u00d7 regime \u8986\u76d6\u77e9\u9635

%(matrix)s

## \u4e94\u3001\u7279\u5f81\u6d3b\u6027\u660e\u7ec6\uff08R1\uff0c\u62bd\u6837 %(sample)d \u6761\uff09

%(liveness)s
"""


PROV_SECTION = u"""## 十、数据集新鲜度与溯源

「门槛全绿」并不蕴含「数据是这份代码生成的」。`meta.json` 里的 `spec_hash` 由
`sha256(generator_version + emb_dim + spec)` 得到，`bench/coverage.py::dataset_provenance()`
用**当前活的** `GEN_VERSION` 把它重算一遍再对账，任一 regime 不符即整个审计判失败。

这条断言是实测踩出来的：桥接机制回滚后，8 个 regime 里有 7 个的 `meta.json` 仍残留一个已经
不存在的键（`emb_geometry.intent_bridge`），说明那些元数据出自回滚前的生成器；而
`traces.jsonl` / `gt.jsonl` 恰好逐字节相同（该机制取 0.0 时不消耗随机流），于是门槛与覆盖率
审计**双双全绿**，没有任何信号提示元数据已过期。重算 `spec_hash` 一次抓住三类漂移：
生成器版本、regime 规格、嵌入维度。

| regime | meta 里的 spec_hash | 用当前生成器重算 | 判定 |
|---|---|---|---|
%(rows)s

配套的第二道断言在保真度检查里：`query_embedding` 不再只看维度，而是直接从数据算参与比
`PR = (Σ σ_d²)² / Σ σ_d⁴`，要求 `1 < PR < 0.75 x dim`。各向同性的 384 维高斯团 PR 恰为 384，
会被直接拒绝；实测本数据集为 %(pr)s，全部落在界内。这守住了嵌入几何的标定——几何一旦塌掉，
聚类门槛会变成任何内核改动都抬不动的死门槛。"""


CONTRACT_SECTION = u"""
## \u516b\u300177 \u7279\u5f81\u5408\u540c\u53ef\u652f\u6491\u6027\uff08\u9644\u5f55 A \u9010\u6761\u673a\u68b0\u5224\u5b9a\uff09

\u300c\u6570\u636e\u96c6\u591f\u4e0d\u591f\u300d\u4e0d\u9760\u53d9\u8ff0\u56de\u7b54\uff0c\u9760\u8fd9\u5f20\u8868\uff1a\u6bcf\u4e2a\u5408\u540c\u7279\u5f81\u58f0\u660e\u5b83\u9700\u8981\u7684**\u539f\u59cb Span \u5b57\u6bb5 / \u539f\u59cb trace \u5b57\u6bb5 / \u672c\u4f53\u952e**\uff0c\u72b6\u6001\u7531 `bench/contract.py` \u5bf9\u7740\u6570\u636e\u96c6\u4e0e\u672c\u4f53**\u5b9e\u9645\u53d1\u5c04\u7684\u4e1c\u897f**\u89e3\u6790\u51fa\u6765\u3002\u7ed9\u751f\u6210\u5668\u52a0\u4e00\u4e2a\u5b57\u6bb5\uff0c\u5bf9\u5e94\u7684\u963b\u585e\u9879\u81ea\u52a8\u6e05\u9664\uff1b\u5220\u4e00\u4e2a\uff0c\u5ba1\u8ba1\u76f4\u63a5\u628a\u6784\u5efa\u5224\u5931\u8d25\u3002

%(counts)s

| # | \u7ec4 | \u7279\u5f81 | \u72b6\u6001 | \u5224\u5b9a\u4f9d\u636e / \u8bf4\u660e |
|---|---|---|---|---|
%(table)s

**\u4fdd\u771f\u5ea6\u68c0\u67e5\uff08\u5b57\u6bb5\u5b58\u5728 \u2260 \u5b57\u6bb5\u591f\u7528\uff09**

%(fidelity)s

**\u6570\u636e\u96c6\u963b\u585e\u9879**

%(blockers)s

\u72b6\u6001\u8bcd\u8868\uff1a`implemented` = \u5185\u6838\u5df2\u6309\u6b64\u540d\u6216\u5df2\u8bb0\u5f55\u7684\u522b\u540d\u53d1\u5c04\uff1b`implemented_elsewhere` = \u6d41\u6c34\u7ebf\u91cc\u7b97\u8fc7\uff0c\u4f46\u4e0d\u5728\u7279\u5f81\u5411\u91cf\u91cc\uff08detect / score / cluster\uff09\uff1b`derivable` = \u539f\u59cb\u8f93\u5165\u9f50\u5907\uff0c\u662f\u5185\u6838\u5de5\u4f5c\u4e0d\u662f\u6570\u636e\u96c6\u5de5\u4f5c\uff1b`blocked_field` / `blocked_ontology` = **\u6570\u636e\u96c6\u7f3a\u9677**\uff1b`needs_model` = \u9700\u8981\u771f\u5b9e\u5d4c\u5165\u6a21\u578b / NLI / BERTScore\uff0c\u65e0\u6cd5\u5408\u6210\u2014\u2014\u4f2a\u9020\u5b83\u6bd4\u627f\u8ba4\u5b83\u66f4\u7cdf\uff0c\u6570\u636e\u96c6\u53ea\u63d0\u4f9b**\u8f93\u5165\u4e0e\u771f\u503c**\u8ba9\u7ba1\u9053\u80fd\u8dd1\u901a\uff0c\u6570\u503c\u672c\u8eab\u5728\u63a5\u5165\u771f\u5b9e\u6a21\u578b\u524d\u6ca1\u6709\u610f\u4e49\u3002

\u53ea\u6709 `blocked_field`\u3001`blocked_ontology` \u4e0e\u4fdd\u771f\u5ea6\u4e0d\u8fbe\u6807\u7b97\u6570\u636e\u96c6\u7f3a\u9677\uff1b`derivable` \u4e0e `needs_model` \u4e0d\u662f\u7f3a\u9677\uff0c\u5b83\u4eec\u662f\u5408\u6210\u6570\u636e\u80fd\u529b\u7684\u8fb9\u754c\u3002"""


def write_md(res, path=None, bad=None, counts=None, cc=None, ca=None, prov=None):
    path = path or os.path.join(DATA, "COVERAGE.md")
    fields = u"- trace\uff1a`%s`\n- span\uff1a`%s`" % (
        u"`, `".join(sorted(res["fields"]["trace"])),
        u"`, `".join(sorted(res["fields"]["span"])))
    regs = sorted(res["regimes"])
    lines = [u"| \u5f02\u5e38\u7c7b\u578b | " + u" | ".join(regs) + u" |",
             u"|---" * (len(regs) + 1) + u"|"]
    for atype in ANOMALY_TYPES:
        lines.append(u"| `%s` | " % atype + u" | ".join(
            u"%d" % res["regimes"][r]["anomalies"].get(atype, 0) for r in regs) + u" |")
    lines.append(u"| **\u5f02\u5e38\u8f68\u8ff9\u5408\u8ba1** | " + u" | ".join(
        u"**%d**" % res["regimes"][r]["n_anomaly"] for r in regs) + u" |")
    matrix = u"\n".join(lines)

    rid = "R1"
    r = res["regimes"][rid]
    liv = [u"**\u5df2\u5b9e\u73b0\uff08`kernel/features.py`\uff0c%d \u4e2a\u6807\u91cf\u7279\u5f81\uff1b"
           u"\u5176\u4e2d\u53ea\u6709 v1 \u7684 21 \u4e2a\u63a5\u5165\u4e86 `kernel/baseline.py:METRICS`\uff09**"
           % len(r["impl"]), u"",
           u"| \u7279\u5f81 | distinct | \u7f3a\u5931\u7387 | min | p50 | p99 | max |",
           u"|---|---|---|---|---|---|---|"]
    for k in sorted(r["impl"]):
        info = r["impl"][k]
        qs = info["qs"] or (None,) * 4
        liv.append(u"| `%s` | %d | %.1f%% | %s | %s | %s | %s |" % (
            k, info["distinct"], 100.0 * info["none_rate"],
            *[("%.4g" % x if x is not None else u"\u5168\u7f3a\u5931") for x in qs]))
    if ca:
        crows, cfid, csumm = ca
        trows = []
        # `row`, not `r`: `r` is bound above to res["regimes"]["R1"] and is still needed by the
        # NARRATIVE substitution below for r["n_sampled"]. Shadowing it here made every
        # `--md` invocation die with KeyError: 'n_sampled' as soon as a contract audit was
        # passed in - the plain `python -m bench.coverage` path never reached this line, which
        # is why the bug survived.
        for row in crows:
            detail = row["detail"] or DASH
            if row["note"]:
                detail = detail + SEP + row["note"]
            trows.append(u"| %d | %s | `%s` | `%s` | %s |"
                         % (row["n"], row["group"], row["name"], row["status"], detail))
        contract_table = u"\n".join(trows)
        counts_line = SEP.join(u"%s **%d**" % (st, csumm["counts"].get(st, 0)) for st in CT_ORDER) \
            + SEP + (u"\u5408\u8ba1 **%d**" % csumm["n"])
        if csumm["blockers"]:
            blocker_text = u"\n".join(
                u"- **#%d `%s`**\uff08%s\uff09\uff1a%s"
                % (r["n"], r["name"], r["status"], r["detail"]) for r in csumm["blockers"])
        else:
            blocker_text = NO_BLOCKERS
        flines = []
        for name in sorted(cfid):
            ok, got, want = cfid[name]
            flines.append(u"- %s `%s`\uff1a\u5b9e\u6d4b %s\uff5c\u8981\u6c42 %s"
                          % (FID_OK if ok else FID_BAD, name, got, want))
        fidelity_text = u"\n".join(flines)
    else:
        contract_table = counts_line = blocker_text = fidelity_text = NOT_RUN

    text = NARRATIVE % {"fields": fields, "matrix": matrix,
                        "liveness": u"\n".join(liv), "sample": r["n_sampled"]}

    # ---- section 6: differential test against the independent probe() ----
    text += (u"\n## \u516d\u3001\u72ec\u7acb\u53c2\u8003\u5b9e\u73b0\u4ea4\u53c9\u6821\u9a8c"
             u"\uff08`probe()` vs `kernel/features.py`\uff09\n\n")
    text += (u"`probe()` \u662f\u4e0e\u5185\u6838\u65e0\u5173\u7684\u7b2c\u4e8c\u4efd\u5b9e\u73b0"
             u"\uff08\u8fde\u5206\u4f4d\u6570\u90fd\u53e6\u5199\u4e86\u4e00\u4efd `_quant`\uff0c"
             u"\u56e0\u4e3a\u5bfc\u5165\u88ab\u6d4b\u5bf9\u8c61\u7684\u5dee\u5206\u6d4b\u8bd5"
             u"\u4ec0\u4e48\u4e5f\u8bc1\u4e0d\u4e86\uff09\u3002\u5b83\u56de\u7b54\u7684\u662f"
             u"\uff1a\u5185\u6838\u771f\u7684\u5728\u6309\u6539\u6b63\u540e\u7684\u9644\u5f55 A "
             u"\u516c\u5f0f\u7b97\u5417\uff1f\u533a\u95f4\u5e76\u96c6\u7c7b\u7279\u5f81\u4e00\u81f4"
             u"\u5230 0.0\uff0c\u624d\u7b97\u8bc1\u636e\uff1b\u201c\u8fd4\u56de\u4e86\u4e00\u4e2a"
             u"\u843d\u5728 [0,1] \u7684\u6570\u201d\u4e0d\u7b97\u3002\n\n")
    if cc:
        text += (u"\u62bd\u6837 %d \u6761\uff08R1\uff09\uff1a\n\n" % cc["n"])
        text += (u"| \u7279\u5f81 | \u6700\u5927\u7edd\u5bf9\u5dee | "
                 u"\u53cc\u65b9\u5747\u65e0\u5b9a\u4e49 | \u4e0d\u4e00\u81f4\u6761\u6570 |\n")
        text += u"|---|---|---|---|\n"
        for k in CROSSCHECK:
            text += u"| `%s` | %s | %d | %d |\n" % (
                k, (u"%.6g" % cc["maxdiff"][k]), cc["both_none"][k], cc["disagree"][k])
        worst = max(cc["maxdiff"].values())
        ndis = sum(cc["disagree"].values())
        text += (u"\n\u7ed3\u8bba\uff1a%d \u4e2a\u7279\u5f81\u5168\u90e8\u9010\u6761\u4e00\u81f4"
                 u"\uff08\u6700\u5927\u5dee %s\uff0c\u4e0d\u4e00\u81f4 %d \u6761\uff09\u3002\n"
                 % (len(CROSSCHECK), u"%.3g" % worst, ndis)) if ndis == 0 else (
                 u"\n\u7ed3\u8bba\uff1a**\u5b58\u5728\u4e0d\u4e00\u81f4**\uff08\u6700\u5927\u5dee %s"
                 u"\uff0c\u4e0d\u4e00\u81f4 %d \u6761\uff09\uff0c\u5fc5\u987b\u5148\u5b9a\u4f4d"
                 u"\u54ea\u4e00\u4fa7\u4e0d\u7b26\u5408\u5408\u540c\u3002\n"
                 % (u"%.3g" % worst, ndis))
    else:
        text += u"\uff08\u672a\u8fd0\u884c\uff09\n"

    # ---- section 7: label <-> truth <-> feature ----
    text += u"\n## \u4e03\u3001\u6807\u7b7e \u2194 \u771f\u503c \u2194 \u7279\u5f81 \u4e00\u81f4\u6027\uff08\u5168\u91cf %d \u6761\uff09\n\n" % (
        (counts or {}).get("n", 0))
    if counts:
        text += (u"- \u6709 golden \u7684\u8f68\u8ff9\uff1a%d \u6761\uff08%.1f%%\uff09\n"
                 u"- \u6709\u7528\u6237\u53cd\u9988\u7684\u8f68\u8ff9\uff1a%d \u6761\uff08%.1f%%\uff09\n"
                 u"- \u771f\u5b9e\u5faa\u73af\uff08\u53c2\u6570\u5b8c\u5168\u76f8\u540c\u7684 \u2265 3 \u6b21\u91cd\u590d\uff09\uff1a%d \u6761\n"
                 % (counts["golden"], 100.0 * counts["golden"] / max(1, counts["n"]),
                    counts["feedback"], 100.0 * counts["feedback"] / max(1, counts["n"]),
                    counts["loop"]))
        text += (u"- v3 \u4fe1\u53f7\uff1a\u8ba1\u5212\u4fee\u8ba2 %d \u6761\u3001\u76ee\u6807\u6f02\u79fb %d \u6761\u3001\u4e8b\u5b9e\u77db\u76fe %d \u6761\u3001\u865a\u6784\u5f15\u7528 %d \u6761\n" % (counts["plan_revision"], counts["goal_drift"], counts["contradiction"], counts["fabricated_citation"]))
        text += (u"- v3 span\uff1a\u53c2\u6570\u975e\u6cd5 %d\u3001\u6821\u9a8c\u5931\u8d25 %d\u3001\u7f13\u5b58\u547d\u4e2d %d\uff1b\u591a\u8f6e\u4f1a\u8bdd\u8f68\u8ff9 %d \u6761\n" % (counts["arg_invalid_span"], counts["verifier_fail"], counts["cache_hit_span"], counts["multi_turn"]))
    if bad:
        text += u"- **\u4e0d\u4e00\u81f4**\uff1a" + u"\uff1b".join(
            u"%s=%d" % (k, bad[k]) for k in sorted(bad)) + u"\n"
    else:
        text += u"- **\u5168\u90e8\u4e00\u81f4**\uff1a\u6807\u7b7e\u3001\u751f\u6210\u5668\u771f\u503c\u3001\u5185\u6838\u7279\u5f81\u4e09\u8005\u4e24\u4e24\u5bf9\u9f50\uff1b\u5360\u6bd4\u7c7b\u7279\u5f81\u8d8a\u754c\u8ba1\u6570 0\n"
    text += CONTRACT_SECTION % {"table": contract_table, "counts": counts_line,
                                "blockers": blocker_text, "fidelity": fidelity_text}
    text += u"\n## \u4e5d\u3001\u81ea\u52a8\u68c0\u51fa\u7684\u95ee\u9898\u6e05\u5355\n\n"
    for g in res["gaps"]:
        text += u"- %s\n" % g
        disp = gap_disposition(g)
        if disp:
            # two-space indent keeps the disposition inside the same bullet in rendered Markdown
            text += u"".join(u"  %s\n" % line for line in disp.split("\n"))
    if not res["gaps"]:
        text += u"- \uff08\u65e0\uff09\n"
    if prov:
        prows, pstale, ppr = prov
        rows_md = u"\n".join(
            u"| `%s` | `%s` | `%s` | %s |" % (rid, got or u"-", want or u"-",
                                              u"**一致**" if ok
                                              else u"**不一致**")
            for rid, got, want, ok, _v in prows)
        text += u"\n" + PROV_SECTION % {"rows": rows_md, "pr": ppr}
        if pstale:
            text += (u"\n> **数据集不新鲜**：%s 的 `spec_hash` "
                     u"与当前生成器不符，请重新生成。\n"
                     % u", ".join("`%s`" % r for r in pstale))
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _load_head(rid, n):
    """First n traces of a regime, parsed lazily.

    `_load` parses the whole file before the caller slices it, which is fine for the audits
    that need every record but wasteful for a statistic that only needs a sample. Embeddings
    are 384 floats, so the difference across 8 regimes is 22,800 parsed traces against 1,600.
    """
    out = []
    path = os.path.join(DATA, rid, "traces.jsonl")
    if not os.path.exists(path):
        return out
    with io.open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            out.append(json.loads(line))
    return out


def embedding_pr(regimes=None, sample=200):
    """Per-regime embedding participation ratio, measured from the data."""
    return [(rid, CT.participation_ratio(
        [t.get("embedding") or [] for t in _load_head(rid, sample)]))
        for rid in (regimes or REGIMES)]


def dataset_provenance(regimes=None):
    """Recompute every regime's spec_hash with the LIVE generator version and compare.

    "All gates green" does not imply "this data was produced by this code". spec_hash is
    sha256 over (generator_version, emb_dim, spec-minus-gates) and feeds anchor_version, but
    nothing ever re-derived it: it was written once at generation time and trusted. So a
    dataset left behind by an older generator keeps scoring against gates calibrated for the
    new one, silently.

    This was hit for real. After the embedding bridge mechanism was measured and fully
    reverted, 7 of the 8 regimes still carried emb_geometry.intent_bridge = 0.0 in meta.json -
    a key the generator no longer has - because their metadata predated the revert. Their
    traces.jsonl and gt.jsonl happened to be byte-identical (the mechanism consumes no random
    draws at 0.0), so the runner reported 8/8 ALL-PASS and the contract audit reported zero
    blockers, and nothing anywhere said the metadata was stale. Re-deriving spec_hash catches
    all three drift classes at once: generator version, regime spec, embedding dimension.

    Returns (rows, stale) where rows is [(rid, got, want, ok, gen_version)] and stale lists
    the regime ids that did not match.
    """
    from bench.generate import GEN_VERSION
    regimes = regimes or REGIMES
    rows, stale = [], []
    for rid in regimes:
        path = os.path.join(DATA, rid, "meta.json")
        if not os.path.exists(path):
            rows.append((rid, None, None, False, "meta.json missing"))
            stale.append(rid)
            continue
        meta = json.load(io.open(path, encoding="utf-8"))
        spec_txt = json.dumps({"generator_version": GEN_VERSION,
                               "emb_dim": meta.get("emb_dim"),
                               "spec": meta.get("spec")},
                              sort_keys=True, ensure_ascii=False)
        want = hashlib.sha256(spec_txt.encode("utf-8")).hexdigest()[:16]
        got = meta.get("spec_hash")
        ok = got == want
        rows.append((rid, got, want, ok, meta.get("generator_version")))
        if not ok:
            stale.append(rid)
    return rows, stale


def main(argv):
    # Provenance runs first and fails fast: every other number in this report is only
    # meaningful if the dataset on disk was produced by the generator that is about to
    # interpret it.
    prows, pstale = dataset_provenance()
    print("=== dataset provenance (spec_hash re-derived with the live generator) ===")
    for rid, got, want, ok, ver in prows:
        print("  [%s] %-3s stored=%s recomputed=%s gen=%s"
              % ("PASS" if ok else "FAIL", rid, got, want, ver))
    if pstale:
        print("  STALE: %s -> regenerate with: python -m bench.generate --regimes %s"
              % (", ".join(pstale), ",".join(pstale)))
    else:
        print("  all %d regimes match the live GEN_VERSION" % len(prows))
    print("")
    res = audit()
    report(res)
    bad, counts = truth_agreement()
    print("")
    print("=== label <-> truth <-> feature agreement (%d traces) ===" % counts["n"])
    print("  golden available on %d (%.1f%%), feedback on %d (%.1f%%), true loops %d"
          % (counts["golden"], 100.0 * counts["golden"] / max(1, counts["n"]),
             counts["feedback"], 100.0 * counts["feedback"] / max(1, counts["n"]),
             counts["loop"]))
    print("  v3 signals: plan_revision %d, goal_drift %d, contradiction %d, "
          "fabricated_citation %d" % (counts["plan_revision"], counts["goal_drift"], counts["contradiction"], counts["fabricated_citation"]))
    print("  v3 spans:   arg_invalid %d, verifier_fail %d, cache_hit %d; "
          "multi-turn traces %d" % (counts["arg_invalid_span"], counts["verifier_fail"], counts["cache_hit_span"], counts["multi_turn"]))
    if bad:
        for k in sorted(bad):
            print("  [FAIL] %s: %d" % (k, bad[k]))
    else:
        print("  [PASS] all agreement checks clean")
    ca = contract_audit()
    report_contract(*ca)
    cc = crosscheck()
    print("")
    print("=== differential test: probe() vs kernel/features.py (R1, n=%d) ===" % cc["n"])
    worst = max(cc["maxdiff"].values())
    ndis = sum(cc["disagree"].values())
    for k in CROSSCHECK:
        print("  %-26s max|diff|=%-10.6g both_none=%-5d disagree=%d"
              % (k, cc["maxdiff"][k], cc["both_none"][k], cc["disagree"][k]))
    if ndis == 0 and worst <= 1e-9:
        print("  [PASS] %d/%d features agree exactly" % (len(CROSSCHECK), len(CROSSCHECK)))
    else:
        print("  [FAIL] max|diff|=%.6g over %d features, %d disagreements"
              % (worst, len(CROSSCHECK), ndis))
    if "--md" in argv:
        pr_txt = u" / ".join(u"%s %.1f" % (rid, v) for rid, v in embedding_pr())
        print("wrote %s" % write_md(res, bad=bad, counts=counts, cc=cc, ca=ca,
                                    prov=(prows, pstale, pr_txt)))
    crows, cfid, csumm = ca
    nblock, nfid = len(csumm["blockers"]), len(csumm["bad_fidelity"])
    print("")
    print("=== contract verdict ===")
    print("  blockers: %d   fidelity failures: %d   stale regimes: %d   -> %s"
          % (nblock, nfid, len(pstale),
             "DATASET READY" if not (nblock or nfid or pstale) else "DATASET NOT READY"))
    return 1 if (bad or ndis or worst > 1e-9 or nblock or nfid or pstale) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))