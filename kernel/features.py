"""Feature extraction (contracts/schemas.md section 2).

Two generations live side by side on purpose:

  v1 keys  the 21 scalars slice-1 detection/scoring consumes. Their definitions are frozen
           so that gate numbers stay comparable across dataset versions.
  v2 keys  the contract features that bench-gen-v2.0.0 unlocked (appendix A.1/A.2/A.3/A.5).
           They are emitted but not yet wired into kernel.baseline METRICS; wiring is a
           separate, separately measured step.
  v3 keys  the contract features that bench-gen-v3.0.0 unlocked: cache/system-prompt token
           decomposition, cost attribution, critical path, argument-schema validity, verifier
           outcomes, citation reachability, goal drift, query metadata and session context.
           Same rule as v2 - emitted, not wired, so the frozen gates stay comparable.

Two features are cross-record by definition and therefore cannot live in `extract`: they are
filled by `annotate_sessions()`, which every batch caller must invoke or the two keys stay None.

Three name collisions with the frozen v1 keys are resolved by emitting the appendix quantity
under a different name rather than by redefining the v1 one, because the detection gates were
calibrated on the v1 meaning: `tokens_total_contract` (appendix #24, includes cache tokens) vs
`tokens_total` (prompt + completion), `system_prompt_ratio` (appendix #33, system prompt /
input) vs `prompt_token_ratio` (prompt / total), and `parallelism_ratio_contract` (appendix #19,
1 - critical_path / sum(duration)) vs `parallelism_ratio` (1 - |union| / sum(duration)).

Two rules that are easy to get wrong and are therefore stated here rather than discovered:

  * Every *ratio of time* is computed over the union of intervals, never over the sum of
    durations. Sibling spans overlap whenever the agent parallelises tool calls, and the
    sum-based formula from appendix A goes negative (measured -1.94 on this benchmark) or
    above 1 (llm_time_ratio up to 2.78).
  * The root span spans the whole wall clock by construction, so any "slowest step" or
    "framework overhead" statistic must exclude it, otherwise bottleneck_share is
    identically 1.0.

Numeric traceability uses the structured `output_facts` / `answer_numbers` fields when they
are present and falls back to regexing prose only for legacy records. The fallback is not
safe on realistic text: SQL limits, API paths and NE identifiers all contain digits that
have nothing to do with the facts the answer cites.
"""
import json
import math
import re

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
TIME_KINDS = ("llm", "tool", "retrieval", "guard", "agent")


def _numbers(text):
    return _NUM.findall(text or "")


def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _union_len(intervals):
    """Lebesgue measure of the union of [start, end) intervals."""
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


def _dur(s):
    return max(0.0, s["ts_end"] - s["ts_start"])


def _param_hash(params):
    return json.dumps(params, sort_keys=True) if params is not None else "null"


def _quant(sorted_vals, q):
    if not sorted_vals:
        return None
    h = (len(sorted_vals) - 1) * q
    lo = int(h)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (h - lo) * (sorted_vals[hi] - sorted_vals[lo])


def _longest_repeated_subseq(seq):
    """Length of the longest contiguous subsequence occurring at least twice."""
    best = 0
    for length in range(2, len(seq) // 2 + 1):
        seen = set()
        for i in range(len(seq) - length + 1):
            key = tuple(seq[i:i + length])
            if key in seen:
                best = length
                break
            seen.add(key)
    return best


def _implicit_feedback(fb):
    """Weak-supervision synthesis (appendix A.5 #64). None when the operator said nothing:
    absence of feedback is not satisfaction."""
    if not fb:
        return None
    s = 0.50
    thumbs = fb.get("thumbs")
    if thumbs == 1:
        s += 0.25
    elif thumbs == -1:
        s -= 0.35
    if fb.get("retry"):
        s -= 0.10
    if fb.get("abandoned"):
        s -= 0.20
    if fb.get("human_takeover"):
        s -= 0.15
    return _clamp01(s)


# ---- v3 helpers ---------------------------------------------------------------------------
# bench/generate.py keeps a second, independent copy of `_content_tokens` on purpose. If the two
# tokenizers ever disagree, an off-goal detour can share a goal token and coverage.truth_agreement
# reports it as a goal_drift feature/truth mismatch instead of the drift silently never firing.
_EN_STOP = frozenset("""a all also an and any are as at be by can could do does down each every
for from give here his how i if in into is it its just me my need not of off on only or our out
over please show some than that the their them then there these they this to together up want we
what when where which who why with whether your""".split())
_CJK = re.compile(u"[\u4e00-\u9fff]")
_WORDS = re.compile(r"[^a-z0-9]+")
_INTENT_TAG = re.compile(r"^intent\d+:\s*")
_CLAUSE = re.compile(u"[,;:\uff0c\uff1b\uff1a\u3001]|\\b(?:and|or|then)\\b|"
                     u"\u5e76\u4e14|\u6216\u8005|\u7136\u540e|\u4ee5\u53ca")
_WH = re.compile(u"\\b(?:what|why|how|which|when|where|who)\\b|"
                 u"\u4ec0\u4e48|\u4e3a\u4ec0\u4e48|\u600e\u4e48|\u5982\u4f55|\u54ea\u4e9b|"
                 u"\u54ea\u4e2a|\u4f55\u65f6|\u54ea\u91cc")
_NE_ID = re.compile(r"NE-[0-9A-Fa-f]{4}-\d+")
_WINDOW = re.compile(r"\b\d+(?:\.\d+)?[smhd]\b")
_BARE_NUM = re.compile(r"\b\d+(?:\.\d+)?\b")
# Appendix A.4 #51: a rephrase is similar but not identical, so the similarity has to land in a
# band rather than above a threshold.
REFORM_BAND = (0.55, 0.90)
REFORM_RAMP = 0.10
# A step counts as progress when its output is not near-duplicate of an earlier one (A.3 #29).
PROGRESS_DUP = 0.90
COST_COMPONENTS = ("prompt", "completion", "tool_call", "cache_read", "cache_write")


def _content_tokens(text, lang):
    """Language-aware content vocabulary.

    zh has no whitespace, so a CJK unigram set is the only tokenizer available without a
    segmentation model; en is lowercased, word-split and stopword-filtered. Unigrams are coarse
    on purpose: goal_drift is a *containment* test, and a coarse vocabulary makes an off-goal
    detour provably disjoint from the goal instead of accidentally overlapping it.
    """
    text = text or ""
    if lang == "zh":
        return set(_CJK.findall(text))
    return set(w for w in _WORDS.split(text.lower()) if w and w not in _EN_STOP)


def _char_ngrams(text, n=3):
    """Character 3-gram set. Language-neutral, which is what a redundancy estimate needs."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) < n:
        return set([t]) if t else set()
    return set(t[i:i + n] for i in range(len(t) - n + 1))


def _jaccard(a, b):
    if not a or not b:
        return None
    return len(a & b) / float(len(a | b))


def _bigrams(seq):
    return set(zip(seq, seq[1:]))


def _lstsq_slope(ys):
    """Ordinary least squares slope of (0..n-1, ys); None below two points or with no spread."""
    n = len(ys)
    if n < 2:
        return None
    mx = (n - 1) / 2.0
    my = sum(ys) / float(n)
    den = sum((i - mx) ** 2 for i in range(n))
    if den <= 0:
        return None
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / den


def _gini(vals):
    """Gini coefficient over per-span cost. None below two values or with no cost at all.

    Uses the sorted closed form so the cost is O(n log n) rather than the O(n^2) pairwise
    definition; the two are algebraically identical.
    """
    v = sorted(x for x in vals if x is not None)
    n = len(v)
    tot = sum(v)
    if n < 2 or tot <= 0:
        return None
    return sum((2 * (i + 1) - n - 1) * x for i, x in enumerate(v)) / (n * tot)


def _cos(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0.0 or nb <= 0.0:
        return None
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _band_membership(c, lo, hi, ramp):
    """Trapezoidal membership of [lo, hi]: 1 inside, linear down to 0 within `ramp` outside.

    Raw cosine is unusable here. The embeddings all live in one narrow cone, so the appendix's
    [0.55, 0.90] band would fire on nearly every consecutive turn pair and the feature would be
    near-constant. Centring on the corpus mean removes the shared direction; what is left is rare
    enough to mean something. Measured on the shipped `bench-gen-v3.1.0` tree, whole files, over
    every adjacent turn pair of every session -- reproduce by running `annotate_sessions` over
    each `data/bench_v1/R*/traces.jsonl` and tabulating `_band_membership(...) > 0`:

        regime  pairs   raw cos min/p50/max        raw in-band  centred min/p50/max        in-band
        R1      3119     0.577 / 0.874 / 0.927       100.0%     -0.585 /  0.134 / 0.737    269 ( 8.62%)
        R2      3115     0.100 / 0.703 / 0.896        80.7%     -0.736 /  0.133 / 0.834    769 (24.69%)
        R3      2344     0.215 / 0.520 / 0.711        85.6%     -0.335 / -0.002 / 0.371      0 ( 0.00%)
        R4       930    -0.359 / 0.701 / 0.904        71.1%     -0.750 / -0.052 / 0.904    235 (25.27%)
        R5      2328     0.620 / 0.833 / 0.903       100.0%     -0.498 /  0.058 / 0.631    160 ( 6.87%)
        R6       463     0.612 / 0.838 / 0.901       100.0%     -0.480 /  0.098 / 0.613     38 ( 8.21%)
        R7      3117     0.360 / 0.825 / 0.908        99.9%     -0.631 /  0.093 / 0.761    275 ( 8.82%)
        R8      2342     0.003 / 0.673 / 0.916        79.6%     -0.791 /  0.099 / 0.854    678 (28.95%)

    R3 is the one regime where the feature is identically 0.0 (0 of 2344 pairs in band), and that
    is a property of the regime, not of this function. R3 alone carries `intent_ambiguity = 0.50`,
    which drags every embedding toward the mean of the *other* intents; the centred vectors
    therefore collapse toward one another and the whole centred range tops out at 0.371, well
    under the 0.55 floor. Note the direction -- ambiguity *compresses* the centred cosine, it
    does not push it above the band.

    Accepted as a documented boundary rather than fixed, because every fix measured worse:
      * widening REFORM_BAND is not available -- [0.55, 0.90] is appendix A.4 #51, a contract
        value, and it is load-bearing on the other seven regimes (raw-cos in-band 71-100%);
      * lowering R3's `intent_ambiguity` to 0.55 drops `novelty_rate` to 0.0063, under the 0.03
        floor, and R3 already sits at 0.2867 with only 4.4% headroom under the 0.30 cap;
      * emitting deliberately rephrased follow-up turns is the only real fix, and it costs a new
        `GEN_VERSION`, a full regeneration and a ~13 min matrix re-run, to repair one feature
        that seven of eight regimes already exercise.
    `bench.coverage` reports this as a *gap*, not a blocker: gaps do not enter the exit code.
    """
    if c <= lo - ramp or c >= hi + ramp:
        return 0.0
    if c < lo:
        return (c - (lo - ramp)) / ramp
    if c > hi:
        return ((hi + ramp) - c) / ramp
    return 1.0


def _entity_count(text):
    """Distinct NE identifiers + distinct time windows + distinct standalone numbers.

    Counted after removing the wider matches, otherwise the `-59` tail of `NE-6C1E-59` is also a
    bare number and every query with one NE id saturates the entity term of query_complexity.
    """
    nes = set(_NE_ID.findall(text))
    rest = _NE_ID.sub(" ", text)
    wins = set(_WINDOW.findall(rest))
    rest = _WINDOW.sub(" ", rest)
    return len(nes) + len(wins) + len(set(_BARE_NUM.findall(rest)))


def _query_body(intent_text):
    """The question itself, without the dataset's `intentN:` cell tag.

    The tag is constant per intent, so leaving it in would add a per-cell offset to query_len and
    a spurious shared token to query_complexity.
    """
    return _INTENT_TAG.sub("", (intent_text or "").strip())


def extract(trace, ontology):
    spans = trace["spans"]
    by_id = {s["span_id"]: s for s in spans}
    children = {}
    for s in spans:
        children.setdefault(s.get("parent_id"), []).append(s)
    n = len(spans)
    internal = sum(1 for s in spans if children.get(s["span_id"]))

    depth = 0
    width = {}
    stack = [(s, 1) for s in children.get(None, [])]
    while stack:
        s, d = stack.pop()
        depth = max(depth, d)
        width[d] = width.get(d, 0) + 1
        stack.extend((c, d + 1) for c in children.get(s["span_id"], []))

    t0 = min(s["ts_start"] for s in spans) if spans else trace.get("ts_start", 0.0)
    t1 = max(s["ts_end"] for s in spans) if spans else t0
    wall = max(1e-9, t1 - t0)

    root_ids = set(s["span_id"] for s in children.get(None, []))
    kids = [s for s in spans if s["span_id"] not in root_ids]

    kinds = {}
    for s in spans:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    tok_p = sum(s.get("tokens_prompt") or 0 for s in spans)
    tok_c = sum(s.get("tokens_completion") or 0 for s in spans)
    cost = sum(s.get("cost") or 0.0 for s in spans)
    errs = sum(1 for s in spans if s["status"] == "error")
    err_level = sum(1 for s in spans if s.get("level") == "ERROR")
    warn_level = sum(1 for s in spans if s.get("level") == "WARNING")
    guard_hits = sum(1 for s in spans if s["kind"] == "guard"
                     and (s["status"] == "error" or "block" in (s["output_text"] or "")))

    seq = [s["action"] for s in spans if s.get("action")]
    retry = 0
    max_run = 1
    run = 1
    for i in range(1, len(seq)):
        run = run + 1 if seq[i] == seq[i - 1] else 1
        max_run = max(max_run, run)
        if run == 2:
            retry += 1

    # Loop = the same step repeated with the same normalised parameters, among siblings.
    # Grouping by (parent, action, param-hash) is what separates a runaway loop from a
    # legitimate retry: a retry is one extra sibling (2 occurrences), a loop is 3+.
    groups = {}
    for s in spans:
        key = (s.get("parent_id"), s.get("action"), _param_hash(s.get("tool_params")))
        groups[key] = groups.get(key, 0) + 1
    loop_runs = [v for v in groups.values() if v >= 3]
    loop_count = max([v - 2 for v in loop_runs] or [0])

    answer = ""
    for s in spans:
        if s["kind"] in ("agent", "llm") and s.get("parent_id") is None:
            answer = s["output_text"] or ""
    if not answer and spans:
        answer = spans[-1]["output_text"] or ""

    pool = []
    for s in spans:
        if s["kind"] in ("tool", "retrieval"):
            facts = s.get("output_facts")
            pool.extend(list(facts) if facts is not None else _numbers(s["output_text"]))
    ans_nums = trace.get("answer_numbers")
    ans_nums = list(ans_nums) if ans_nums is not None else _numbers(answer)
    traceable = sum(1 for x in ans_nums if x in pool)

    # ---- v2: outcome conformance against the curated golden subset ----------
    golden = trace.get("golden_facts")
    if golden:
        inter = len(set(trace.get("answer_facts") or []) & set(golden))
        key_fact_recall = inter / float(len(set(golden)))
        ans_set = set(trace.get("answer_facts") or [])
        fact_precision = (inter / float(len(ans_set))) if ans_set else None
        unfaithful_facts = sorted(set(trace.get("answer_facts") or []) - set(golden))
    else:
        key_fact_recall = fact_precision = None
        unfaithful_facts = []

    # ---- v2: time budget, all union-based ----------------------------------
    kid_iv = [(s["ts_start"], s["ts_end"]) for s in kids]
    busy = _union_len(kid_iv)
    sum_kid_dur = sum(_dur(s) for s in kids)

    def kind_time(k):
        return _union_len([(s["ts_start"], s["ts_end"]) for s in kids if s["kind"] == k])

    kid_durs = sorted(_dur(s) for s in kids)
    ordered = sorted(kids, key=lambda s: (s["ts_start"], s["span_id"]))
    gaps = [g for g in (ordered[i + 1]["ts_start"] - ordered[i]["ts_end"]
                        for i in range(len(ordered) - 1)) if g > 0]
    mu = sum(gaps) / len(gaps) if gaps else 0.0
    var = sum((g - mu) ** 2 for g in gaps) / len(gaps) if gaps else 0.0

    llm_spans = [s for s in spans if s["kind"] == "llm" and s.get("ttft") is not None]
    if llm_spans:
        first = min(llm_spans, key=lambda s: s["ts_start"])
        ttft = (first["ts_start"] - t0) + first["ttft"]
    else:
        ttft = None

    tool_calls = [s for s in spans if s.get("tool_name")]
    uniq_tools = len(set(s["tool_name"] for s in tool_calls))

    seen_group = set()
    retry_dur = 0.0
    for s in ordered:
        key = (s.get("parent_id"), s.get("action"), _param_hash(s.get("tool_params")))
        if key in seen_group:
            retry_dur += _dur(s)
        else:
            seen_group.add(key)

    mult = dict((m[0], m[2]) for m in (ontology.get("models") or []))
    tok_by_model = {}
    for s in spans:
        m = s.get("model")
        if m:
            tok_by_model[m] = tok_by_model.get(m, 0) + (s.get("tokens_prompt") or 0) \
                + (s.get("tokens_completion") or 0)
    tok_model_sum = sum(tok_by_model.values())

    # ---- v3: token and cost decomposition (appendix A.3) ---------------------------
    tok_cr = sum(s.get("tokens_cache_read") or 0 for s in spans)
    tok_cw = sum(s.get("tokens_cache_write") or 0 for s in spans)
    tok_sys = sum(s.get("tokens_system_prompt") or 0 for s in spans)
    tokens_total_contract = tok_p + tok_c + tok_cr + tok_cw
    cost_comp = dict((k, 0.0) for k in COST_COMPONENTS)
    for s in spans:
        d = s.get("cost_details") or {}
        for k in COST_COMPONENTS:
            cost_comp[k] += d.get(k) or 0.0
    cost_comp_sum = sum(cost_comp.values())
    span_costs = [s.get("cost") or 0.0 for s in spans]

    # Cumulative prompt volume over the non-root spans in execution order: the context a
    # multi-step agent drags along. The root is excluded because its own prompt already holds the
    # question and including it would put a constant first term in every regression.
    cum = 0
    cum_series = []
    for s in ordered:
        cum += s.get("tokens_prompt") or 0
        cum_series.append(cum)
    context_growth_slope = _lstsq_slope(cum_series)

    cwin = ontology.get("context_window") or {}
    utils = []
    for s in spans:
        if s["kind"] not in ("llm", "agent"):
            continue
        w = cwin.get(s.get("model"), cwin.get("default"))
        if w:
            utils.append((s.get("tokens_prompt") or 0) / float(w))
    context_utilization = max(utils) if utils else None

    # ---- v3: critical path (appendix A.2 #14) --------------------------------------
    # Longest root-to-leaf duration chain, root excluded. Including the root returns
    # latency_total by construction and drives the contract's parallelism_ratio to exactly 0.
    chain_memo = {}

    def _chain(sp):
        sid = sp["span_id"]
        if sid not in chain_memo:
            below = children.get(sid) or []
            chain_memo[sid] = _dur(sp) + max([_chain(c) for c in below] or [0.0])
        return chain_memo[sid]

    forest = [c for r in (children.get(None) or []) for c in (children.get(r["span_id"]) or [])]
    critical_path = max([_chain(c) for c in forest]) if forest else None

    # ---- v3: semantics and behaviour (appendix A.4) --------------------------------
    all_ordered = sorted(spans, key=lambda s: (s["ts_start"], s["span_id"]))
    tool_spans = [s for s in spans if s["kind"] in ("tool", "retrieval")]
    tool_success_rate = (sum(1 for s in tool_spans if s["status"] != "error")
                         / float(len(tool_spans))) if tool_spans else None
    arg_flags = [s["arg_valid"] for s in spans if s.get("arg_valid") is not None]
    tool_arg_valid_rate = (sum(1 for v in arg_flags if v) / float(len(arg_flags))) \
        if arg_flags else None

    verifiers = [s["verifier"] for s in spans if s.get("verifier")]
    verifier_pass_rate = (sum(1 for v in verifiers if v.get("passed")) / float(len(verifiers))) \
        if verifiers else None

    retrieved = set()
    for s in spans:
        retrieved.update(s.get("output_citations") or [])
    ans_cit = set(trace.get("answer_citations") or [])
    citation_reachability = (len([c for c in ans_cit if c in retrieved]) / float(len(ans_cit))) \
        if ans_cit else None

    lang = trace.get("query_lang") or "en"
    goal_toks = _content_tokens(trace.get("goal_text"), lang)
    drifts = []
    if goal_toks:
        for s in all_ordered:
            if s.get("subgoal_text"):
                st = _content_tokens(s["subgoal_text"], lang)
                drifts.append(1.0 - len(goal_toks & st) / float(len(goal_toks)))
    goal_drift_max = max(drifts) if drifts else None
    goal_drift_slope = _lstsq_slope(drifts)

    # A self-correction is a same-action sibling that starts after an earlier one finished and
    # either replaces failed work or tries different arguments. Identical params with an
    # identical outcome is a retry, already counted by retry_count; counting it here as well
    # would make the two features collinear.
    self_correction_count = 0
    same_action = {}
    for s in ordered:
        same_action.setdefault((s.get("parent_id"), s.get("action")), []).append(s)
    for group in same_action.values():
        for i in range(1, len(group)):
            b = group[i]
            for a in group[:i]:
                if a["ts_end"] <= b["ts_start"] + 1e-9 and (
                        a["status"] == "error" or a.get("level") == "WARNING"
                        or _param_hash(a.get("tool_params")) != _param_hash(b.get("tool_params"))):
                    self_correction_count += 1
                    break

    # A plan revision is an entry-action span *temporally contained* in an earlier entry-action
    # span: the agent reopened the step it was still in. Containment is what separates it from a
    # loop, which repeats the step sequentially and never overlaps itself.
    #
    # Two other definitions were measured and rejected. "Count entry-action spans minus one" is
    # wrong because the loop injector can pick the entry span: on the 700-trace dev sample it did
    # on exactly one trace, where the naive count read 2 revisions on a trace whose truth is
    # `loop`. Adding "and the two must share a parent_id" is also wrong, because ingest.normalize
    # re-parents an orphaned span to the tightest span enclosing it, which turns the revision from
    # a nested sibling into a child; on the full 22,800-trace dataset that lost 10 of 1370
    # revisions, and all 10 were on traces with orphan_rebuilt set. Containment alone is
    # invariant under re-parenting.
    entry_actions = set(v[0] for v in (ontology.get("required_steps") or {}).values() if v)
    entry_spans = [s for s in all_ordered if s.get("action") in entry_actions]

    def _encloses(outer, inner):
        return outer["ts_start"] <= inner["ts_start"] + 1e-9 \
            and inner["ts_end"] <= outer["ts_end"] + 1e-9

    plan_revision_count = 0
    for b in entry_spans:
        for a in entry_spans:
            if a is b or not _encloses(a, b):
                continue
            da, db = a["ts_end"] - a["ts_start"], b["ts_end"] - b["ts_start"]
            # Strict containment is the normal case: the revision runs inside the step it
            # reopens. Identical intervals are the repaired case - normalize() clamps a span onto
            # the one it was re-parented to, and when the orphaned span *is* one half of a
            # revision pair both end up with the same interval, so containment holds in both
            # directions. Breaking that tie on span_id counts exactly one of the pair. Measured:
            # strict- containment-only lost 2 of 1370 revisions on the 22,800-trace dataset, both
            # on R5 traces carrying ts_repaired AND orphan_rebuilt.
            if da > db + 1e-9 or (abs(da - db) <= 1e-9 and a["span_id"] < b["span_id"]):
                plan_revision_count += 1
                break

    half = len(seq) // 2
    path_convergence = _jaccard(_bigrams(seq[:half]), _bigrams(seq[half:])) if len(seq) >= 4 \
        else None

    frags = [s["input_text"] for s in all_ordered if s.get("input_text")]
    redun = []
    for a, b in zip(frags, frags[1:]):
        j = _jaccard(_char_ngrams(a), _char_ngrams(b))
        if j is not None:
            redun.append(j)
    effective_info_ratio = (1.0 - sum(redun) / len(redun)) if redun else None

    seen_out = []
    progress = 0
    for s in all_ordered:
        if s.get("parent_id") is None:
            continue
        g = _char_ngrams(s.get("output_text"))
        if not any((_jaccard(g, p) or 0.0) >= PROGRESS_DUP for p in seen_out):
            progress += 1
        if g:
            seen_out.append(g)
    cost_per_step_of_progress = (cost / float(progress)) if progress else None

    qbody = _query_body(trace.get("intent_text"))
    query_len = len(qbody)
    query_complexity = (0.4 * min(len(_CLAUSE.findall(qbody)) + 1, 4) / 4.0
                        + 0.3 * min(len(_WH.findall(qbody)), 2) / 2.0
                        + 0.3 * min(_entity_count(qbody), 3) / 3.0)

    return {
        # ---- v1 (frozen) ---------------------------------------------------
        "trace_id": trace["trace_id"],
        "ts_start": t0,
        "latency_total": t1 - t0,
        "n_spans": n,
        "depth": depth,
        "branch_factor": ((n - 1) / internal) if internal else 1.0,
        "n_llm": kinds.get("llm", 0),
        "n_tool": kinds.get("tool", 0),
        "n_guard": kinds.get("guard", 0),
        "tokens_total": tok_p + tok_c,
        "prompt_token_ratio": (tok_p / (tok_p + tok_c)) if (tok_p + tok_c) else None,
        "cost_total": cost,
        "retry_count": retry,
        "error_ratio": (errs / n) if n else 0.0,
        "loop_count": loop_count,
        "guard_hits": guard_hits,
        "answer_number_count": len(ans_nums),
        "traceable_number_ratio": (traceable / len(ans_nums)) if ans_nums else None,
        "action_seq": seq,
        "action_kinds": [s["kind"] for s in spans],
        "embedding": list(trace.get("embedding") or []),
        "flags": trace.get("flags", {}),
        "missing_field_ratio": trace.get("missing_field_ratio", 0.0),
        "spans": spans,
        "by_id": by_id,
        # ---- v2: structure (appendix A.1) ----------------------------------
        "max_width": max(width.values()) if width else 0,
        "kind_ratio_llm": kinds.get("llm", 0) / float(n) if n else None,
        "kind_ratio_tool": kinds.get("tool", 0) / float(n) if n else None,
        "kind_ratio_retrieval": kinds.get("retrieval", 0) / float(n) if n else None,
        "kind_ratio_guard": kinds.get("guard", 0) / float(n) if n else None,
        "n_unique_tools": uniq_tools,
        "tool_repeat_rate": (1.0 - uniq_tools / float(len(tool_calls))) if tool_calls else None,
        "loop_group_count": len(loop_runs),
        "loop_run_max": max(0, max_run - 2),
        "longest_repeated_subseq": _longest_repeated_subseq(seq),
        "error_level_ratio": (err_level / n) if n else 0.0,
        "warn_level_ratio": (warn_level / n) if n else 0.0,
        # ---- v2: latency (appendix A.2) ------------------------------------
        "ttft": ttft,
        "busy_union": busy,
        "llm_time_ratio": kind_time("llm") / wall,
        "tool_time_ratio": _union_len([(s["ts_start"], s["ts_end"]) for s in kids
                                       if s["kind"] in ("tool", "retrieval")]) / wall,
        "guard_time_ratio": kind_time("guard") / wall,
        "wait_time_ratio": (wall - busy) / wall,
        "parallelism_ratio": (1.0 - busy / sum_kid_dur) if sum_kid_dur > 0 else None,
        "span_latency_p95": _quant(kid_durs, 0.95),
        "bottleneck_share": (kid_durs[-1] / wall) if kid_durs else None,
        "inter_step_gap_cv": ((var ** 0.5) / mu) if mu > 0 else None,
        "retry_latency_share": retry_dur / wall,
        # ---- v2: cost (appendix A.3) ---------------------------------------
        "cost_per_span": cost / float(n) if n else None,
        "tokens_per_span": (tok_p + tok_c) / float(n) if n else None,
        "model_count": len(tok_by_model),
        "model_mix_cost_index": (sum(v * mult.get(k, 1.0) for k, v in tok_by_model.items())
                                 / tok_model_sum) if tok_model_sum else None,
        "prompt_version_count": len(set(s.get("prompt_version") for s in spans
                                        if s.get("prompt_version"))),
        # ---- v2: outcome conformance (appendix A.5) ------------------------
        "key_fact_recall": key_fact_recall,
        "fact_precision": fact_precision,
        "unfaithful_fact_count": len(unfaithful_facts),
        "has_golden": bool(golden),
        "implicit_feedback": _implicit_feedback(trace.get("user_feedback")),
        "has_feedback": trace.get("user_feedback") is not None,
        # ---- v2: data quality (appendix A.7) -------------------------------
        "missing_fields": list(trace.get("missing_fields") or []),
        "missing_field_ratio_post": trace.get("missing_field_ratio_post", 0.0),
        "turn_index": trace.get("turn_index"),
        # ---- v3: cost decomposition (appendix A.3) ---------------------------------
        # `tokens_total_contract` is the appendix's total = input + output + cache_read +
        # cache_write. It is NOT the v1-frozen `tokens_total` (prompt + completion), which the
        # detection gates are calibrated on and which must not be silently redefined. Likewise
        # `system_prompt_ratio` is the appendix's prompt_token_ratio (system prompt / input),
        # distinct from the v1-frozen `prompt_token_ratio` (prompt / total).
        "tokens_total_contract": tokens_total_contract,
        "cache_read_tokens": tok_cr,
        "cache_write_tokens": tok_cw,
        "cache_hit_ratio": (tok_cr / float(tok_p)) if tok_p else None,
        "system_prompt_ratio": (tok_sys / float(tok_p)) if tok_p else None,
        "token_efficiency": (tok_c / float(tok_p)) if tok_p else None,
        "cost_concentration_gini": _gini(span_costs),
        "top1_cost_share": (max(span_costs) / cost) if (span_costs and cost > 0) else None,
        "context_growth_slope": context_growth_slope,
        "context_utilization": context_utilization,
        "cost_share_prompt": (cost_comp["prompt"] / cost_comp_sum) if cost_comp_sum else None,
        "cost_share_completion": (cost_comp["completion"] / cost_comp_sum) if cost_comp_sum
        else None,
        "cost_share_tool_call": (cost_comp["tool_call"] / cost_comp_sum) if cost_comp_sum
        else None,
        "cost_share_cache_read": (cost_comp["cache_read"] / cost_comp_sum) if cost_comp_sum
        else None,
        "cost_share_cache_write": (cost_comp["cache_write"] / cost_comp_sum) if cost_comp_sum
        else None,
        # ---- v3: latency and structure (appendix A.1 / A.2) -------------------------
        "critical_path": critical_path,
        "parallelism_ratio_contract": ((1.0 - critical_path / sum_kid_dur)
                                       if (critical_path is not None and sum_kid_dur > 0)
                                       else None),
        # ---- v3: semantics and behaviour (appendix A.4) -----------------------------
        "query_len": query_len,
        "query_lang": trace.get("query_lang"),
        "query_complexity": query_complexity,
        "goal_drift_slope": goal_drift_slope,
        "goal_drift_max": goal_drift_max,
        "self_correction_count": self_correction_count,
        "plan_revision_count": plan_revision_count,
        "tool_success_rate": tool_success_rate,
        "tool_arg_valid_rate": tool_arg_valid_rate,
        "path_convergence": path_convergence,
        "effective_info_ratio": effective_info_ratio,
        "cost_per_step_of_progress": cost_per_step_of_progress,
        # ---- v3: outcome conformance (appendix A.5) ---------------------------------
        "verifier_pass_rate": verifier_pass_rate,
        "citation_reachability": citation_reachability,
        # ---- v3: session context (appendix A.4 #50 / #51) ---------------------------
        # `n_turns_in_session` is seeded from the captured session metadata and recounted by
        # annotate_sessions(); `reformulation_signal` needs the *next* turn and therefore only
        # exists there. Both stay None for a caller that scores one trace in isolation, which the
        # kernel already treats as "undefined" rather than as a value.
        "n_turns_in_session": trace.get("session_turn_count"),
        "reformulation_signal": None,
    }


def annotate_sessions(feats, traces):
    """Fill the two appendix-A.4 features that are only defined across records of one session.

    `extract` sees a single trace, so it cannot see the next turn. Both features are computed
    here over an aligned (feats, traces) pair and written in place; the pair must be aligned by
    position, not by trace_id, so callers pass the same list they extracted from.

    `n_turns_in_session` is *recounted* from `session_id` rather than trusted from the record.
    The emitted `session_turn_count` is what the capture pipeline stored; appendix A.4 #50 asks
    for the count derived from the session linkage, and coverage.truth_agreement compares the
    recount against the generator's truth, so a truncated session window cannot pass silently.

    `reformulation_signal` is a trapezoidal membership of the rephrasing similarity band, scaled
    by whether the follow-up question got shorter. See `_band_membership` for why the cosine has
    to be mean-centred before the band means anything.
    """
    if not feats:
        return feats
    index = dict((t["trace_id"], i) for i, t in enumerate(traces))
    dim = 0
    for t in traces:
        emb = t.get("embedding") or []
        if emb:
            dim = len(emb)
            break
    mu = [0.0] * dim
    seen = 0
    if dim:
        for t in traces:
            emb = t.get("embedding") or []
            if len(emb) == dim:
                seen += 1
                for d in range(dim):
                    mu[d] += emb[d]
        if seen:
            mu = [x / seen for x in mu]

    by_sess = {}
    for t in traces:
        by_sess.setdefault(t.get("session_id"), []).append(t)

    lo, hi = REFORM_BAND
    for group in by_sess.values():
        group.sort(key=lambda x: (x.get("turn_index") or 0, x["trace_id"]))
        for t in group:
            i = index.get(t["trace_id"])
            if i is not None:
                feats[i]["n_turns_in_session"] = len(group)
        for a, b in zip(group, group[1:]):
            i = index.get(a["trace_id"])
            if i is None or not dim:
                continue
            ea, eb = a.get("embedding") or [], b.get("embedding") or []
            if len(ea) != dim or len(eb) != dim:
                continue
            c = _cos([ea[d] - mu[d] for d in range(dim)], [eb[d] - mu[d] for d in range(dim)])
            if c is None:
                continue
            band = _band_membership(c, lo, hi, REFORM_RAMP)
            shorter = 1.0 if len(_query_body(b.get("intent_text"))) \
                < len(_query_body(a.get("intent_text"))) else 0.0
            feats[i]["reformulation_signal"] = band * (0.7 + 0.3 * shorter)
    return feats
