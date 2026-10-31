"""Per-cell conditional baselines: leave-one-out partial pooling over merged samples.

Why conditional
  A single global threshold provably fails on heterogeneous agent traffic: the end-to-end
  latency histogram is a *mixture* of task classes, not a unimodal law, so robust global
  statistics get kidnapped by the majority cluster. Every statistic here is therefore
  conditioned on the analysis cell (intent cluster x pattern cluster).

Why pooling, and why over samples rather than over anchor values
  Small cells cannot estimate their own P99. Three layers are available - L3 cell, L2
  intent, L1 global - and they are blended with the classic credibility weight

      B = n / (n + KAPPA),  KAPPA = 30      B(n=30)=0.5,  B->1 as n->inf,  B->0 as n->0

  Two details matter and are easy to get wrong:
  1. The reference levels are built *leave-one-out* (intent excluding this cell, global
     excluding this intent). Without that, a cell which happens to be the whole intent
     contributes its own sample twice and a single outlier gets double weight.
  2. The blend is done on the **sample**, not on the resulting quantiles. Averaging P99
     values across levels is not robust: one 500s trace in a 1-sample reference level
     drags a 4000-sample cell's median by seconds. Instead we build a merged sample of
     POOL_W points where the cell contributes B of them and the LOO reference (1-B), then
     take quantiles of the merge. The limits are then exact: B->1 gives the cell's own
     quantiles, B->0 gives the reference quantiles, and a single outlier in the reference
     can only move the far tail.

Anchors are ideal=P10, good=P50, warn=P90, bad=P99 (mirrored for lower-is-worse metrics)
because quantiles are robust to the very anomalies being hunted. Degenerate ladders
(constant metric inside a cell) are separated by a per-metric minimum gap so that one
error span cannot zero a whole dimension.

The artifact also carries per cell: the pooled sample (empirical tail plus the fitted log-scale tail model), a learned
required-step profile and dominant terminal action (structural layer L4), and a first-order
Markov model of the action sequence (layer L5). No business action name appears here.
"""
import bisect
import math

KAPPA = 30.0
POOL_W = 400
SAMPLE_CAP = 400
SPAN_SAMPLE_CAP = 150
SPAN_MIN_N = 8
TAIL_MIN_N = 40
TAIL_GOF_TOL = 0.50
TAIL_SWITCH_K = 5
# Metrics that are positive, continuous and right-skewed, where a log-scale tail model is
# meaningful. Counts and ratios are left to the purely empirical tail: they are bounded or
# zero-inflated, so there is no continuum in log space to extrapolate along.
TAIL_METRICS = ("latency_total", "tokens_total", "cost_total")
# Standard-normal quantile spacings. They turn gaps between log-quantiles into a log-scale
# dispersion and let the fit be validated where the sample still has resolution:
#   Z_IQR   = z(.75) - z(.25) = 1.348978  ->  s = IQR(log x) / Z_IQR
#   Z_70_50 = z(.70) - z(.50) = 0.524401     Z_85_50 = z(.85) - z(.50) = 1.036433
Z_IQR = 1.3489784443716
Z_70_50 = 0.5244005127080
Z_85_50 = 1.0364333894937
SQRT2 = 1.4142135623730951
REQUIRED_PREVALENCE = 0.95
TERMINAL_PREVALENCE = 0.70
MARKOV_SMOOTH = 0.5

HIGHER_WORSE = ("latency_total", "tokens_total", "cost_total", "n_spans", "depth",
                "branch_factor", "retry_count", "error_ratio", "loop_count", "guard_hits",
                "missing_field_ratio")
LOWER_WORSE = ("traceable_number_ratio",)
METRICS = HIGHER_WORSE + LOWER_WORSE
DIRECTION = dict([(m, "higher_worse") for m in HIGHER_WORSE]
                 + [(m, "lower_worse") for m in LOWER_WORSE])

# metric families for family-wise multiple testing (correlated metrics share a family)
FAMILIES = {
    "latency": ["latency_total"],
    "usage": ["tokens_total", "cost_total"],
    "shape": ["n_spans", "depth", "branch_factor"],
    "robust": ["retry_count", "error_ratio", "loop_count", "guard_hits"],
    "quality": ["missing_field_ratio", "traceable_number_ratio"],
}
FAMILY_OF = dict((m, f) for f, ms in FAMILIES.items() for m in ms)

MIN_GAP = {"latency_total": 0.0, "tokens_total": 0.0, "cost_total": 0.0, "n_spans": 2.0,
           "depth": 1.0, "branch_factor": 0.5, "retry_count": 1.0, "error_ratio": 0.05,
           "loop_count": 1.0, "guard_hits": 1.0, "missing_field_ratio": 0.10,
           "traceable_number_ratio": 0.05}

QS = (("ideal", 0.10), ("good", 0.50), ("warn", 0.90), ("bad", 0.99))

# --- the slo_anchors surface, derived from its consumers rather than asserted ---
#
# A four-anchor ladder is only worth accepting for a metric that something reads.
# Measured, not assumed: kernel/score.py::_anch is called from exactly three places
# -- score.py:605 latency_total (dim L), :612 cost_total (C), :613 tokens_total (C).
# Every other entry of METRICS has anchors learned into the artefact and no reader.
ANCHOR_CONSUMED = ("latency_total", "cost_total", "tokens_total")

# Accepted slo_anchors key -> the metric it tightens. A dim letter is an alias only
# where that dim's anchor channel is unit-unique: "C" is money, so it maps to
# cost_total alone. tokens_total is a count and cannot share a currency ladder, so
# it is addressable by metric name and by nothing else -- something the removed
# dim->metric lookup (DIM_METRIC, deleted here) could not express at all.
SLO_KEY_TO_METRIC = {"L": "latency_total", "latency_total": "latency_total",
                     "C": "cost_total", "cost_total": "cost_total",
                     "tokens_total": "tokens_total"}


def validate_slo_anchors(slo):
    """Refuse, by name and at build time, any slo_anchors key nothing can honour.

    This exists because the previous behaviour was silence, and the silence had
    three distinct shapes. All three were measured against the _apply_slo truth
    table with a *direction-aware* ladder (stricter than the learned one in the
    metric's own DIRECTION), so that a "did not move" reading cannot be an
    artefact of the spec merely being laxer than the quantile anchors:

      * key "R" / "retry_count" and key "O" / "traceable_number_ratio" DID tighten
        the anchors stored in the artefact, and nothing downstream ever read them.
        A dead write that looks exactly like a live one from the adapter's side.
      * key "tokens_total" -- a LIVE anchor channel, score.py:613 -- could not be
        reached by ANY spelling, because the old loop matched keys against the
        values of the removed dim->metric lookup and tokens_total was absent from
        it. So an adapter who wrote a "C" ladder got half of dim C tightened
        (cost_total) with no way to tighten the other half (tokens_total) and
        nothing to tell them so. This is the worst of the three: the numbers do
        move, so from the outside it reads as working.
      * every other key was dropped outright, also silently.

    The defect fixed here is the silence, not the restriction. O / P / R are rule
    channels and legitimately have no anchor ladder; tighten them through the
    weights and saturation points of adapt/playbook.md section 2.1, or through the
    ontology's validators / forbidden_actions / required_steps. Accepting a key and
    then doing nothing about it is the part that is not legitimate.

    Unreachable on bench_v1 -- ontA and ontB both ship slo_anchors: {} -- so this
    moved no published figure. It is an adaptation-time guard, not a scoring change.
    """
    if not slo:
        return
    bad = []
    for cell in sorted(slo):
        per_dim = slo.get(cell)
        if not isinstance(per_dim, dict):
            bad.append((cell, "<value is %s, expected a dict>" % type(per_dim).__name__))
            continue
        for key in sorted(per_dim):
            if key not in SLO_KEY_TO_METRIC:
                bad.append((cell, key))
    if not bad:
        return
    detail = "; ".join("cell %r key %r" % (c, k) for c, k in bad)
    raise ValueError(
        "slo_anchors: refused %d key(s) that nothing downstream would honour (%s). "
        "Accepted keys are exactly {%s}, covering the three anchor channels %s. "
        "O / P / R are rule channels with no anchor ladder: tighten them via the "
        "weights and saturation points in adapt/playbook.md section 2.1, or via the "
        "ontology's validators / forbidden_actions / required_steps. Note that a "
        "C ladder reaches cost_total only -- tokens_total must be keyed by its own "
        "metric name. See validate_slo_anchors() for the measured failure modes "
        "this replaces."
        % (len(bad), detail, ", ".join(sorted(SLO_KEY_TO_METRIC)),
           " / ".join(ANCHOR_CONSUMED)))


def quantile(sv, q):
    n = len(sv)
    if n == 0:
        return None
    if n == 1:
        return sv[0]
    h = (n - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, n - 1)
    return sv[lo] + (h - lo) * (sv[hi] - sv[lo])


def credibility(n, kappa=KAPPA):
    return n / (n + kappa) if n > 0 else 0.0


def _equispaced(sv, k):
    """Exactly k points representing `sv` with equal weight (replicating when k > n)."""
    n = len(sv)
    if n == 0 or k <= 0:
        return []
    if n == 1 or k == 1:
        return [sv[0]] * k if k > 0 else []
    return [sv[int(round(i * (n - 1) / float(k - 1)))] for i in range(k)]


def _subsample(sv, cap=SAMPLE_CAP):
    n = len(sv)
    if n <= cap:
        return list(sv)
    return [sv[int(round(i * (n - 1) / float(cap - 1)))] for i in range(cap)]


def _exclude(sorted_all, sorted_sub):
    """sorted_all minus the sub-multiset sorted_sub (both ascending)."""
    out = []
    j = 0
    m = len(sorted_sub)
    for x in sorted_all:
        if j < m and sorted_sub[j] == x:
            j += 1
            continue
        out.append(x)
    return out


def _moments(sv):
    if not sv:
        return {"n": 0, "median": None, "mad": None}
    med = quantile(sv, 0.5)
    mad = quantile(sorted(abs(x - med) for x in sv), 0.5)
    return {"n": len(sv), "median": med, "mad": mad}


def _separate(a, metric, mad, direction):
    """Enforce a monotone, non-degenerate 4-anchor ladder."""
    if a is None:
        return None
    base = max(abs(a["good"]), 1e-12)
    gap = max(MIN_GAP.get(metric, 0.0), 0.05 * base, mad if mad else 0.0)
    if gap <= 0:
        gap = 1e-9
    out = dict(a)
    if direction == "higher_worse":
        out["ideal"] = min(out["ideal"], out["good"])
        out["warn"] = max(out["warn"], out["good"] + gap)
        out["bad"] = max(out["bad"], out["warn"] + gap)
    else:
        out["ideal"] = max(out["ideal"], out["good"])
        out["warn"] = min(out["warn"], out["good"] - gap)
        out["bad"] = min(out["bad"], out["warn"] - gap)
        out["warn"] = max(out["warn"], 0.0)
        out["bad"] = max(out["bad"], 0.0)
    return out


def _anchors_from(pool, direction):
    if not pool:
        return None
    if direction == "higher_worse":
        return {"ideal": quantile(pool, 0.10), "good": quantile(pool, 0.50),
                "warn": quantile(pool, 0.90), "bad": quantile(pool, 0.99)}
    return {"ideal": quantile(pool, 0.90), "good": quantile(pool, 0.50),
            "warn": quantile(pool, 0.10), "bad": quantile(pool, 0.01)}


def _profile(seqs):
    """Learned structural profile of a cell: near-universal actions + dominant terminal."""
    n = len(seqs)
    if n == 0:
        return {"required": [], "terminal": None, "n": 0}
    prev = {}
    terms = {}
    for seq in seqs:
        for a in set(seq):
            prev[a] = prev.get(a, 0) + 1
        if seq:
            terms[seq[-1]] = terms.get(seq[-1], 0) + 1
    required = sorted(a for a, c in prev.items() if c / float(n) >= REQUIRED_PREVALENCE)
    terminal = None
    if terms:
        t, c = max(sorted(terms.items()), key=lambda kv: kv[1])
        if c / float(n) >= TERMINAL_PREVALENCE:
            terminal = t
    return {"required": required, "terminal": terminal, "n": n}


def _markov(seqs):
    """First-order Markov chain over actions with START/END sentinels and Laplace smoothing."""
    trans = {}
    vocab = set()
    outdeg = {}
    for seq in seqs:
        toks = ["<S>"] + list(seq) + ["<E>"]
        for i in range(len(toks) - 1):
            a, b = toks[i], toks[i + 1]
            vocab.add(a)
            vocab.add(b)
            trans.setdefault(a, {})
            trans[a][b] = trans[a].get(b, 0) + 1
            outdeg[a] = outdeg.get(a, 0) + 1
    vocab.add("<S>")
    vocab.add("<E>")
    v = len(vocab)
    model = {}
    for a, nxt in trans.items():
        denom = outdeg[a] + MARKOV_SMOOTH * v
        row = dict((b, (c + MARKOV_SMOOTH) / denom) for b, c in nxt.items())
        row["__denom__"] = denom
        row["__v__"] = v
        model[a] = row
    return {"trans": model, "vocab": sorted(vocab), "n_seq": len(seqs), "__v__": v}


def markov_logp(model, seq):
    """Mean per-transition log probability of `seq` under a cell Markov model."""
    m = model["trans"]
    v = model.get("__v__", 1)
    toks = ["<S>"] + list(seq) + ["<E>"]
    tot = 0.0
    k = 0
    for i in range(len(toks) - 1):
        a, b = toks[i], toks[i + 1]
        row = m.get(a)
        if row is None:
            p = 1.0 / float(max(v, 1))
        else:
            p = row.get(b, MARKOV_SMOOTH / row["__denom__"])
        tot += math.log(max(p, 1e-12))
        k += 1
    return tot / float(k) if k else 0.0


def _collect(rows, keyfn):
    out = {}
    for r in rows:
        k = keyfn(r)
        if k is None:
            continue
        out.setdefault(k, []).append(r)
    return out


def build(records, ontology, anchor_version="anchor-v1"):
    """records: [{"cell": str|None, "intent": int, "feats": dict}] for assigned traces."""
    assigned = [r for r in records if r["cell"] is not None]
    cells = _collect(assigned, lambda r: r["cell"])
    intents = _collect(assigned, lambda r: r["intent"])
    cell_intent = {}
    for r in assigned:
        cell_intent.setdefault(r["cell"], r["intent"])

    cvals = {}
    for c, rs in cells.items():
        cvals[c] = dict((m, sorted(v for v in (r["feats"].get(m) for r in rs) if v is not None))
                        for m in METRICS)
    ivals = {}
    for i, rs in intents.items():
        ivals[i] = dict((m, sorted(v for v in (r["feats"].get(m) for r in rs) if v is not None))
                        for m in METRICS)
    gvals = dict((m, sorted(v for v in (r["feats"].get(m) for r in assigned) if v is not None))
                 for m in METRICS)
    gstat = dict((m, _moments(gvals[m])) for m in METRICS)

    slo = (ontology or {}).get("slo_anchors") or {}
    validate_slo_anchors(slo)
    cell_out = {}
    fallback_pairs = 0
    total_pairs = 0
    for c in sorted(cells):
        rs = cells[c]
        nc = len(rs)
        bc = credibility(nc)
        i = cell_intent[c]
        seqs = [r["feats"].get("action_seq") or [] for r in rs]
        ent = {"n": nc, "intent": i, "B_cell": bc, "B_intent": None,
               "level": "L3" if bc >= 0.5 else "L2", "profile": _profile(seqs),
               "markov": _markov(seqs), "anchors": {}, "stats": {}}
        k3 = int(round(POOL_W * bc))
        kref = POOL_W - k3
        for m in METRICS:
            cv = cvals[c][m]
            ref2 = _exclude(ivals[i][m], cv)
            ref1 = _exclude(gvals[m], ivals[i][m])
            bi = credibility(len(ref2))
            ent["B_intent"] = bi
            pts = _equispaced(cv, k3) if cv else []
            if not cv:
                kref = POOL_W
            kr2 = int(round(kref * bi))
            kr1 = kref - kr2
            if not ref2:
                kr1 += kr2
                kr2 = 0
            if not ref1:
                kr2 += kr1
                kr1 = 0
            pts = pts + _equispaced(ref2, kr2) + _equispaced(ref1, kr1)
            pool = sorted(pts)
            if not pool:
                pool = sorted(_equispaced(gvals[m], POOL_W))
            ent["level"] = "L3" if bc >= 0.5 else ("L2" if bi >= 0.5 else "L1")
            mom = _moments(pool)
            a = _separate(_anchors_from(pool, DIRECTION[m]), m, mom["mad"], DIRECTION[m])
            a = _apply_slo(a, m, c, slo)
            ent["anchors"][m] = a
            samp = _subsample(pool)
            ent["stats"][m] = {"n": len(cv), "median": mom["median"], "mad": mom["mad"],
                               "sample": samp, "level": ent["level"],
                               "tail": (fit_tail(samp) if m in TAIL_METRICS else None),
                               "B_cell": round(bc, 6), "B_intent": round(bi, 6)}
            total_pairs += 1
            if bc < 0.5:
                fallback_pairs += 1
        cell_out[c] = ent

    gseqs = [r["feats"].get("action_seq") or [] for r in assigned]
    span_stats, gspan_stats = _span_stats(cells, assigned)
    art = {
        "anchor_version": anchor_version,
        "kappa": KAPPA,
        "pool_w": POOL_W,
        "metrics": list(METRICS),
        "direction": DIRECTION,
        "families": FAMILIES,
        "n_assigned": len(assigned),
        "n_cells": len(cell_out),
        "global": dict((m, dict(_moments(gvals[m]), sample=_subsample(gvals[m]),
                                tail=(fit_tail(_subsample(gvals[m]))
                                      if m in TAIL_METRICS else None))) for m in METRICS),
        "intent": dict((str(i), dict((m, _moments(ivals[i][m])) for m in METRICS)) for i in ivals),
        "cell": cell_out,
        "global_profile": _profile(gseqs),
        "global_markov": _markov(gseqs),
        "span_stats": span_stats,
        "global_span_stats": gspan_stats,
        "fallback_ratio": (fallback_pairs / float(total_pairs)) if total_pairs else 1.0,
    }
    return art


def _span_stats(cells, assigned):
    """Per-(cell, action) and per-action span baselines: duration and token volume.

    Trace-level aggregates hide single-step blowups - a 12x span inside a 8-step trace
    moves the total by well under one cell sigma. L3 needs the distribution of a step
    against *its own peers*: the same action, inside the same cell.
    """
    def acc(rows):
        out = {}
        for r in rows:
            for s in r["feats"].get("spans") or []:
                a = s.get("action")
                if not a:
                    continue
                e = out.setdefault(a, {"dur": [], "tok": []})
                e["dur"].append(max(0.0, (s.get("ts_end") or 0.0) - (s.get("ts_start") or 0.0)))
                e["tok"].append(float((s.get("tokens_prompt") or 0)
                                      + (s.get("tokens_completion") or 0)))
        return out

    def summarize(raw):
        out = {}
        for a, e in raw.items():
            ent = {}
            for k in ("dur", "tok"):
                sv = sorted(e[k])
                mom = _moments(sv)
                samp = _subsample(sv, SPAN_SAMPLE_CAP)
                ent[k] = {"n": mom["n"], "median": mom["median"], "mad": mom["mad"],
                          "sample": samp, "tail": fit_tail(samp)}
            ent["n"] = len(e["dur"])
            out[a] = ent
        return out

    per_cell = {}
    for c in sorted(cells):
        per_cell[c] = summarize(acc(cells[c]))
    return per_cell, summarize(acc(assigned))


def span_baseline(art, cell, action, kind):
    """(median, mad, sample, tail, level) for one span metric; falls back cell -> global."""
    cs = ((art.get("span_stats") or {}).get(cell) or {}).get(action)
    if cs and (cs.get(kind) or {}).get("n", 0) >= SPAN_MIN_N and cs[kind]["mad"]:
        e = cs[kind]
        return e["median"], e["mad"], e["sample"], e.get("tail"), "L3span"
    gs = (art.get("global_span_stats") or {}).get(action)
    if gs and (gs.get(kind) or {}).get("n", 0) >= SPAN_MIN_N and gs[kind]["mad"]:
        e = gs[kind]
        return e["median"], e["mad"], e["sample"], e.get("tail"), "L1span"
    return None, None, [], None, "none"


def _apply_slo(a, metric, cell, slo):
    """Ontology SLO anchors override the learned ones, keeping whichever is stricter.

    Keys are matched through SLO_KEY_TO_METRIC, so both spellings of an honoured
    channel work ("C" and "cost_total" are equivalent). Supplying both is well
    defined rather than order-dependent: each rung keeps the stricter of the two
    values, and min/min (or max/max) is associative and commutative, so the result
    is the same for any dict iteration order. Metrics outside ANCHOR_CONSUMED are
    never reached, and validate_slo_anchors() has already refused any key that
    would have asked for one.
    """
    if a is None or not slo:
        return a
    for key in (cell, "*"):
        per_dim = slo.get(key)
        if not per_dim:
            continue
        for slo_key, target in SLO_KEY_TO_METRIC.items():
            if target != metric:
                continue
            spec = per_dim.get(slo_key)
            if not spec:
                continue
            out = dict(a)
            for k in ("ideal", "good", "warn", "bad"):
                if k not in spec or spec[k] is None:
                    continue
                if DIRECTION[metric] == "higher_worse":
                    out[k] = min(out[k], spec[k])
                else:
                    out[k] = max(out[k], spec[k])
            a = out
    return a


def get_cell(art, cell):
    return art["cell"].get(cell)


def eff_stats(art, cell, metric):
    """Pooled robust location/scale actually used by the detectors, with its provenance."""
    c = art["cell"].get(cell) if cell else None
    if c:
        st = c["stats"].get(metric) or {}
        if st.get("median") is not None:
            return st["median"], (st.get("mad") or 0.0), st.get("level", "L3"), st.get("B_cell", 0.0)
    g = art["global"].get(metric, {})
    return g.get("median"), (g.get("mad") or 0.0), "L1", 0.0


def eff_sample(art, cell, metric):
    """Pooled empirical sample + POT tail behind the p-values, with their provenance."""
    c = art["cell"].get(cell) if cell else None
    if c:
        st = c["stats"].get(metric) or {}
        if st.get("sample"):
            return st["sample"], st.get("tail"), st.get("level", "L3")
    g = art["global"].get(metric, {})
    return g.get("sample") or [], g.get("tail"), "L1"


def tail_prob(sv, x, direction):
    """One-sided empirical tail probability with continuity correction (ECOD style)."""
    n = len(sv)
    if n == 0 or x is None:
        return None
    if direction == "higher_worse":
        k = n - bisect.bisect_left(sv, x)
    else:
        k = bisect.bisect_right(sv, x)
    return (k + 0.5) / float(n + 1)


def fit_tail(sv, min_n=TAIL_MIN_N):
    """Contamination-robust log-scale tail model for positive right-skewed metrics.

    Why not peaks-over-threshold
      The textbook choice - fit an exponential to the exceedances above the 90th percentile
      (Balkema-de Haan) - is self-defeating at the prevalence this pipeline runs at. With
      7-10% anomalous traces and anomalies concentrated in the upper tail by construction,
      the top decile is *majority contaminated*, so any scale read off it (mean, median,
      Hill) is inflated by the very events under test. Measured on the bimodal benchmark:
      beta came out 1.4x too large, the modelled tail decayed ~10x too slowly, a 5x span
      spike reported p = 1.5e-2 instead of 1.4e-3, and the whole statistical channel
      collapsed to 6 alerts out of 3979 traces while precision sat at 0.99 - the detector
      had become a rule engine with a decorative p-value.

    What is used instead
      Location and scale of log(x) are estimated from the *bulk*, where the anomalies are
      not: m = median(log x), s = IQR(log x) / 1.348978. Both have breakdown point >= 25%,
      so a 10% contaminated upper tail cannot move them at all. The tail is then read off
      the normal survival function in log space,

          p(x) = pos_frac * 0.5 * erfc((log x - m) / (s * sqrt(2))),

      which is unbounded below and therefore survives a Bonferroni + Benjamini-Hochberg
      correction over ~1e5 tests. A counted empirical p-value is floored at ~1/(2N) and can
      never survive one, which is the reason a tail model is needed here in the first place.

    Validated, not assumed
      Extrapolating a parametric tail is only honest if the bulk really is log-normal, so
      the fit is checked where the sample still has resolution: the observed spacings
      y(.70)-y(.50) and y(.85)-y(.50) must match s*0.5244 and s*1.0364 within
      TAIL_GOF_TOL standard deviations. A residual mixture inside the cell - i.e. a
      clustering that failed to split the peaks - breaks that check, and the model is then
      *refused*: the p-value falls back to the purely empirical tail rather than
      extrapolating a shape the data contradicts. Both quantiles sit below the 85th
      percentile on purpose, so contamination cannot influence its own admission test.
    """
    n = len(sv)
    if n < min_n:
        return None
    ys = sorted(math.log(x) for x in sv if x is not None and x > 0)
    n_pos = len(ys)
    if n_pos < min_n:
        return None
    m = quantile(ys, 0.50)
    s = (quantile(ys, 0.75) - quantile(ys, 0.25)) / Z_IQR
    if s <= 1e-9:
        return None
    gof = max(abs((quantile(ys, 0.70) - m) / s - Z_70_50),
              abs((quantile(ys, 0.85) - m) / s - Z_85_50))
    if gof > TAIL_GOF_TOL:
        return None
    return {"m": m, "s": s, "pos_frac": n_pos / float(n), "gof": round(gof, 4),
            "n": n, "n_pos": n_pos, "switch": (TAIL_SWITCH_K + 0.5) / float(n + 1)}


def tail_pvalue(sv, tail, x, direction):
    """One-sided p-value: counted where the sample has resolution, modelled beyond it.

    Inside the resolvable region (more than TAIL_SWITCH_K sample points at or above x) the
    answer is purely non-parametric and no distributional assumption is made at all. Only
    once x moves past what the sample can support does the fitted log-scale tail take over,
    and even then the two are combined with min(), so the model can only ever make the test
    more sensitive in the region where counting has run out of information.
    """
    n = len(sv)
    if n == 0 or x is None:
        return None
    if direction != "higher_worse":
        k = bisect.bisect_right(sv, x)
        return (k + 0.5) / float(n + 1)
    k = n - bisect.bisect_left(sv, x)
    p_emp = (k + 0.5) / float(n + 1)
    if tail is None or x <= 0 or p_emp > tail["switch"]:
        return p_emp
    z = (math.log(x) - tail["m"]) / tail["s"]
    p_par = tail["pos_frac"] * 0.5 * math.erfc(z / SQRT2)
    return min(p_emp, p_par)


def anchor_score(anch, x, direction):
    """4-anchor piecewise-linear map metric value -> [0,1]; 1.0/0.8/0.5/0.0 at the anchors.

    higher_worse : score is non-increasing in x (latency, tokens, cost, errors...)
    lower_worse  : score is non-decreasing in x (traceable-number ratio)
    """
    if anch is None or x is None:
        return None
    i, g, w, b = anch["ideal"], anch["good"], anch["warn"], anch["bad"]
    if direction == "higher_worse":
        if x <= i:
            return 1.0
        if x <= g:
            return 1.0 - 0.2 * (x - i) / max(g - i, 1e-12)
        if x <= w:
            return 0.8 - 0.3 * (x - g) / max(w - g, 1e-12)
        if x <= b:
            return 0.5 - 0.5 * (x - w) / max(b - w, 1e-12)
        return 0.0
    if x >= i:
        return 1.0
    if x >= g:
        return 1.0 - 0.2 * (i - x) / max(i - g, 1e-12)
    if x >= w:
        return 0.8 - 0.3 * (g - x) / max(g - w, 1e-12)
    if x >= b:
        return 0.5 - 0.5 * (w - x) / max(w - b, 1e-12)
    return 0.0