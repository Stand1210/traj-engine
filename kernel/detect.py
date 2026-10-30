"""Multi-layer anomaly detection: label-free, FDR-controlled, evidence-bearing.

Layers
  L1 magnitude  : modified z-score 0.6745*(x-median)/MAD of trace-level metrics against the
                  *pooled cell* statistics, trigger |z| > 3.5 (Iglewicz-Hoaglin). 3.5 is not
                  a magic number: it is the Sidak-corrected two-sided normal quantile for
                  alpha=0.005 over M=11 metrics, i.e. the classic trigger already is a
                  family-wise error-rate statement.
  L2 shape      : one-sided tail probability against the pooled cell sample - empirical
                  below the cell's P90, peaks-over-threshold log-exponential above it (see
                  baseline.fit_tail). Direction comes from the feature dictionary instead of
                  ECOD's skewness heuristic - we know a long right tail is normal for
                  latency, so scoring the left tail there would flag "suspiciously fast".
  L3 span       : per-step attribution against same-action peers *inside the same cell*.
                  Trace-level aggregates structurally hide single-step blowups: a 12x span
                  inside an 8-step trace moves the total by well under one cell sigma, which
                  is exactly why a latency spike on one tool call goes unnoticed. L3 also
                  produces the responsible span id, so an alert can be drilled into.
  L4 contract   : ontology validators (numeric answer traceability), declared required-step
                  coverage via the fitted pattern binding, learned required-step coverage,
                  dominant-terminal (unfinished), forbidden actions, runaway loops,
                  truncated generation, unrecovered errors. Deterministic: no statistics.
  L5 sequential : first-order Markov log-likelihood of the action sequence under the cell
                  model, as a modified z. Catches legal-looking but implausible step orders.

Why some of these are rules and not p-values
  A *counted* empirical p-value cannot go below ~1/(2N): with a 400-point pooled sample the
  most extreme possible observation still reports p = 1.25e-3, and after multiplicity
  correction over ~4000 traces Benjamini-Hochberg can never reject it. Two consequences.
  Graded extremes get a modelled tail (POT, baseline.fit_tail) so their p-values reach 1e-9
  and survive the correction. Breaches that are *categorical* rather than graded - an
  untraceable number in the answer, a declared step that never ran, a generation cut off by
  the token limit, a forbidden tool - are enforced as deterministic L4 rules, because there
  is no continuum to place them on and no amount of tail modelling will produce one. Mixing
  the two up is what makes rule-based alerting noisy and statistics-based alerting blind.

Decision
  p(x)     = baseline.tail_pvalue: empirical below the cell's P90, POT above it.
             The modified z is deliberately NOT turned into a p-value. Reading a MAD z
             through the normal tail is invalid for gamma-skewed span durations and token
             counts: it understates the tail by orders of magnitude, and that single
             miscalibration produced a 13.5% false-positive rate on an otherwise clean 7:3
             bimodal regime. z is kept, but only as an effect size for the deviation score
             and for the evidence records.
  p_family = min(1, |family| * min_m p_m)            evidence/readability only, not gating
  p_trace  = min(1, n_tests * min p)                 ONE Bonferroni over every test this
             trace contributed: its M trace metrics plus its span tests. Not a chain of
             family-wise products - nesting Bonferroni inside Bonferroni multiplies the
             conservatism (up to |fam| x |m| ~ 40x here) and pushes p_trace back over the BH
             threshold, which is why the pre-EVT pipeline stalled at F1 = 0.47 on R1.
  alert    = BH over the traces of a cell at alpha, OR a hard L4 contract violation.
  Combination is min-p, not the Sidak/Fisher product: the alternative is "at least one
  metric blew up", and the product form answers a different question - it returns p ~ 0.6
  even for a 1e-23 tail because the other ten p-values are uniform, so BH rejects nothing.
  Novelty traces never alert: they have no conditional baseline to be judged against.

a_raw is the triage priority, not a probability: a severity tier (2 = confirmed contract
breach, 1 = statistical rejection, 0 = neither) selects a disjoint band, and the weighted
within-cell rank average of the layer deviations orders inside that band. Scale-free,
monotone, label-free, and the quantity used for Precision@k, for the operator-facing top-k
and for calibration.
"""
import math

from kernel import baseline as bl
from kernel import binding as BD

Z_TRIGGER = 3.5
Z_SAT = 10.0
Z_CAP = 50.0
# BH_ALPHA is the target FDR of the *triage set*, not of the operator-facing alert stream.
# The triage set is consumed by a bounded human review budget rather than read one by one,
# and what operators actually see is its top-k by a_raw (<= 5 per day). FDR is therefore the
# right control for the triage set, and it is a deployment tunable (adapt/playbook.md);
# operator fatigue is protected separately by the FPR gate (<= 0.05) and the alert budget.
# At ~7% prevalence, alpha = 0.20 with precision ~0.8 is what satisfies F1 >= 0.70 and
# FPR <= 0.05 at the same time; alpha = 0.05 buys FDR at the price of recall and fails both.
BH_ALPHA = 0.20
LAYER_WEIGHTS = {"L1": 0.24, "L2": 0.20, "L3": 0.24, "L4": 0.22, "L5": 0.10}
# Triage priority is severity-tiered before it is graded. a_raw used to be a plain weighted
# average of five within-cell layer ranks, so a merely suspicious trace whose statistics
# happened to be noisy could outrank a *confirmed* contract breach that entered only through
# the 0.22-weighted L4. Measured on the benchmark, before tiering: the foreign-ontology regime
# had 81 traces carrying a deterministic breach and only 6 of them reached the top 50 of the
# review queue, with 72 confirmed anomalies queued below them; the heavy-overlap regime had
# 184 breaches / 30 in the top 50 / 118 confirmed anomalies below; the sparse regime 74 / 22 /
# 42. Precision@50 came out at 0.700, 0.640 and 0.560 against gates of 0.75, 0.70 and 0.60.
# Every incident queue in operation is severity-tiered first, and for good reason: a confirmed
# compliance breach in a change-management answer is an audit finding that must be reviewed, a
# 4-sigma latency is a hypothesis. Disjoint bands make the ordering strict and make the
# calibrated probability informative (P(anomaly) ~ 1 in tier 2, ~ 0.8 in tier 1, ~ 0.02 in
# tier 0) instead of compressing three different kinds of statement into one scale. This is
# not circular reasoning: both tier flags are deterministic functions of the trace, and the
# label-free graded rank still orders everything inside a tier.
TIER_BANDS = {0: (0.00, 0.40), 1: (0.40, 0.75), 2: (0.75, 1.00)}
MISSING_HARD = 0.50
LOOP_HARD = 2
DEFAULT_MIN_RATIO = 1.0

_CONF_PENALTY = (("usage_estimated", 0.85), ("ts_repaired", 0.85), ("orphan_rebuilt", 0.92))
_SPAN_MODE = {"latency_total": "latency", "tokens_total": "usage", "cost_total": "usage",
              "error_ratio": "error", "retry_count": "error", "loop_count": "error",
              "guard_hits": "error"}


def mod_z(x, med, mad):
    if x is None or med is None:
        return None
    if mad and mad > 0:
        z = 0.6745 * (x - med) / mad
    else:
        z = 0.0 if abs(x - med) < 1e-12 else math.copysign(Z_CAP, x - med)
    return max(-Z_CAP, min(Z_CAP, z))


def z_to_dev(z):
    """Strictly increasing saturating map |z| -> [0,1); 0.5 at the trigger+saturation midpoint.

    The linear ramp (|z|-3.5)/6.5 clipped at 1.0 tied every trace beyond z=10 into a single
    block. Because a_raw is assembled from *within-cell ranks* of the layer deviations, a
    tie block at the top of a layer destroys exactly the resolution the ranking lives on:
    on the bimodal benchmark ~40% of the true anomalies sat inside the L1 tie and were
    ordered arbitrarily against each other. A hyperbolic ramp keeps dev strictly monotone in
    |z| while staying bounded, so no two distinct magnitudes ever share a rank.
    """
    if z is None:
        return 0.0
    a = abs(z)
    if a <= Z_TRIGGER:
        return 0.0
    r = a - Z_TRIGGER
    return r / (r + (Z_SAT - Z_TRIGGER))


def tail_to_dev(p, ln_sat):
    """Strictly increasing map p -> [0,1), calibrated to the decision boundary.

    ln_sat = -log(alpha / m_cell) is the negative log of the per-cell Benjamini-Hochberg
    rank-1 threshold, so dev = 0.5 exactly at the point where a trace becomes rejectable and
    keeps resolving below it. The previous normaliser log(n_sample) saturated dev at 1.0 for
    every p below 1/n_sample = 2.5e-3 - which is precisely the region the modelled tail
    exists to explore. A p of 1e-9 and a p of 2e-3 were indistinguishable, so the ordering
    inside the anomaly block, and therefore Precision@50, was decided by tie-breaking noise.
    """
    if p is None or ln_sat <= 0:
        return 0.0
    r = -math.log(max(p, 1e-300)) / ln_sat
    return r / (r + 1.0)


def bh_fdr(keys, pvals, alpha=BH_ALPHA):
    """Benjamini-Hochberg step-up. Returns the set of rejected keys."""
    m = len(pvals)
    if m == 0:
        return set()
    order = sorted(range(m), key=lambda i: (pvals[i], str(keys[i])))
    cut = -1
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= alpha * rank / float(m):
            cut = rank
    if cut < 0:
        return set()
    return set(keys[i] for i in order[:cut])


def _rank_norm(vals):
    n = len(vals)
    if n <= 1:
        return [0.5] * n
    order = sorted(range(n), key=lambda i: vals[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return [r / float(n - 1) for r in ranks]


def _worst_span(feats, mode):
    spans = feats.get("spans") or []
    if not spans:
        return None
    if mode == "latency":
        s = max(spans, key=lambda s: ((s["ts_end"] - s["ts_start"]), s["span_id"]))
    elif mode == "usage":
        s = max(spans, key=lambda s: (((s.get("tokens_prompt") or 0)
                                       + (s.get("tokens_completion") or 0)), s["span_id"]))
    elif mode == "error":
        errs = [s for s in spans if s["status"] == "error"]
        s = errs[0] if errs else None
    else:
        s = None
    return s["span_id"] if s else None


def parse_spec(spec):
    out = {}
    for part in (spec or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                out[k.strip()] = float(v)
            except ValueError:
                out[k.strip()] = v.strip()
    return out


def _validators(ontology):
    out = []
    for v in (ontology or {}).get("validators") or []:
        out.append({"kind": v.get("kind"), "target": v.get("target"),
                    "spec": parse_spec(v.get("spec"))})
    return out


def _confidence(feats, novelty, b_cell, missing_ratio):
    c = 1.0
    flags = feats.get("flags") or {}
    for k, mul in _CONF_PENALTY:
        if flags.get(k):
            c *= mul
    c *= (1.0 - 0.5 * min(1.0, max(0.0, missing_ratio)))
    c *= (0.70 + 0.30 * b_cell)
    if novelty:
        c *= 0.5
    return max(0.05, min(1.0, c))


def l4_contract(feats, art, cell, ontology, binding):
    """Deterministic contract layer: ontology validators + learned/declared step coverage."""
    req = BD.required_for(art, ontology, binding, cell)
    required = req["required"]
    declared = req["declared"]
    seq = feats.get("action_seq") or []
    present = set(seq)
    spans = feats.get("spans") or []

    missing = [a for a in required if a not in present]
    missing_frac = (len(missing) / float(len(required))) if required else 0.0
    missing_declared = [a for a in declared if a not in present]

    forbidden = set((ontology or {}).get("forbidden_actions") or [])
    illegal_actions = sorted(set(a for a in seq if a in forbidden))
    illegal = min(1.0, len(illegal_actions) / 2.0) if illegal_actions else 0.0

    term = ((art.get("cell", {}).get(cell, {}) or {}).get("profile") or {}).get("terminal")
    if term is None:
        term = (art.get("global_profile") or {}).get("terminal")
    unfinished = 0.0
    if term is not None and seq and seq[-1] != term:
        aborted = any(s.get("finish_reason") == "length" or s.get("status") == "error"
                      for s in spans)
        short = len([a for a in seq if a in set(required)]) < len(required)
        unfinished = 1.0 if (aborted or short) else 0.35

    truncated = 1.0 if any(s.get("finish_reason") == "length" for s in spans) else 0.0

    # An errored step the agent never retried successfully. A recovered error is a blemish,
    # not an incident - flagging both is what turns an alert queue into noise.
    unrecovered = []
    for s in spans:
        if s.get("status") != "error":
            continue
        rec = any(o.get("action") == s.get("action") and o.get("status") == "ok"
                  and o.get("ts_start", 0.0) >= s.get("ts_end", 0.0)
                  and o.get("span_id") != s.get("span_id") for o in spans)
        if not rec:
            unrecovered.append(s.get("span_id"))
    err_dev = min(1.0, len(unrecovered) / 2.0) if unrecovered else 0.0

    loop = feats.get("loop_count") or 0
    loop_rule = min(1.0, loop / 4.0) if loop >= LOOP_HARD else 0.0

    tr = feats.get("traceable_number_ratio")
    min_ratio = DEFAULT_MIN_RATIO
    for v in _validators(ontology):
        if v["kind"] == "number_traceable":
            min_ratio = float(v["spec"].get("min_ratio", DEFAULT_MIN_RATIO))
    traceable_viol = 0.0
    untraceable = 0
    if tr is not None:
        n_ans = feats.get("answer_number_count") or 0
        untraceable = int(round(n_ans * (1.0 - tr)))
        if tr < min_ratio - 1e-9:
            traceable_viol = min(1.0, (min_ratio - tr) / max(min_ratio, 1e-9) + 0.4)

    hard = bool(illegal_actions) or unfinished >= 1.0 or truncated > 0 \
        or bool(missing_declared) or missing_frac >= MISSING_HARD or bool(unrecovered) \
        or loop >= LOOP_HARD or traceable_viol > 0
    if hard:
        # A deterministic contract breach is categorical, not graded: there is no "how much"
        # to a forbidden tool call, a generation cut off by the token limit, or an answer
        # number that cannot be traced to any retrieved source. Weighting those breaches
        # into a partial dev let a merely-suspicious trace with noisy statistics outrank a
        # confirmed compliance incident in the triage queue - on the heavy-overlap regime a
        # borderline normal beat an untraceable-answer trace, and Precision@50 fell to 0.66.
        # The graded formula is kept for the sub-threshold blemishes, where "how much" is
        # exactly the right question.
        dev = 1.0
    else:
        dev = min(1.0, 0.40 * missing_frac + 0.50 * illegal + 0.40 * unfinished
                  + 0.50 * err_dev + 0.45 * loop_rule + 0.45 * truncated
                  + 0.55 * traceable_viol)
    return {"missing_frac": missing_frac, "missing_actions": missing,
            "missing_declared": missing_declared, "required": required,
            "required_source": req["source"], "pattern_id": req["pattern"],
            "illegal": illegal, "illegal_actions": illegal_actions,
            "unfinished": unfinished, "terminal": term, "truncated": truncated,
            "unrecovered_errors": unrecovered, "loop_rule": loop_rule,
            "traceable_viol": traceable_viol, "untraceable_numbers": untraceable,
            "min_ratio": min_ratio, "dev": dev, "hard": hard}


def l3_span(feats, art, cell, ln_sat):
    """Span-level attribution against same-action peers inside the cell."""
    spans = feats.get("spans") or []
    best_dev, best_ev = 0.0, None
    min_p, n_test = 1.0, 0
    for s in spans:
        a = s.get("action")
        if not a:
            continue
        dur = max(0.0, (s.get("ts_end") or 0.0) - (s.get("ts_start") or 0.0))
        tok = float((s.get("tokens_prompt") or 0) + (s.get("tokens_completion") or 0))
        for kind, val in (("dur", dur), ("tok", tok)):
            med, mad, samp, tl, lvl = bl.span_baseline(art, cell, a, kind)
            if med is None:
                continue
            n_test += 1
            z = mod_z(val, med, mad)
            p_e = bl.tail_pvalue(samp, tl, val, "higher_worse") if samp else None
            if p_e is not None:
                min_p = min(min_p, p_e)
            d = max(z_to_dev(z) if (z is not None and z > 0) else 0.0,
                    tail_to_dev(p_e, ln_sat))
            if d > best_dev:
                best_dev = d
                best_ev = {"kind": "span", "layer": "L3", "span_id": s.get("span_id"),
                           "action": a, "metric": kind, "value": val,
                           "peer_median": med, "z": (round(z, 3) if z is not None else None),
                           "baseline_level": lvl, "dev": round(d, 4)}
    p_l3 = min(1.0, n_test * min_p) if (n_test and min_p < 1.0) else 1.0
    return {"dev": best_dev, "p": p_l3, "min_p": min_p, "n_test": n_test,
            "evidence": best_ev}


def detect_all(features, assigns, art, ontology, binding=None, bh_alpha=BH_ALPHA):
    cell_of = dict((a["trace_id"], a["cell"]) for a in assigns)
    nov_of = dict((a["trace_id"], a["novelty"]) for a in assigns)
    intent_of = dict((a["trace_id"], a.get("near_intent", -1)) for a in assigns)
    binding = binding or {}

    # -log of the per-cell BH rank-1 threshold: the calibration point of tail_to_dev. A
    # deviation score that does not know where its own decision boundary sits cannot rank
    # the region that matters, so the boundary is threaded through explicitly.
    cell_n = {}
    for a in assigns:
        if not a["novelty"]:
            cell_n[a["cell"]] = cell_n.get(a["cell"], 0) + 1
    _al = max(bh_alpha, 1e-6)
    ln_sat_of = dict((c, math.log(max(2.0, n) / _al)) for c, n in cell_n.items())
    ln_sat_default = math.log(max(2.0, float(len(features))) / _al)

    ll_stats = {}
    seqs_by_cell = {}
    for f in features:
        seqs_by_cell.setdefault(cell_of.get(f["trace_id"]), []).append(f)
    for cell, fs in seqs_by_cell.items():
        model = ((art["cell"].get(cell, {}) or {}).get("markov") if cell else None) \
            or art.get("global_markov")
        lls = sorted(bl.markov_logp(model, f.get("action_seq") or []) for f in fs)
        med = bl.quantile(lls, 0.5) if lls else 0.0
        mad = bl.quantile(sorted(abs(x - med) for x in lls), 0.5) if lls else 0.0
        ll_stats[cell] = (model, med, mad)

    stage = {}
    for f in features:
        tid = f["trace_id"]
        cell = cell_of.get(tid)
        nov = bool(nov_of.get(tid))
        ln_sat = ln_sat_of.get(cell, ln_sat_default)
        zs, devs1, devs2, ps_e = {}, {}, {}, {}
        fallback = "L3"
        worst = []
        for m in bl.METRICS:
            x = f.get(m)
            if x is None:
                continue
            med, mad, lvl, b_c = bl.eff_stats(art, cell, m)
            if lvl != "L3" and fallback == "L3":
                fallback = lvl
            z = mod_z(x, med, mad)
            zs[m] = z
            # A zero pooled MAD means the metric is zero-inflated in this cell (errors,
            # loops, guard blocks). The modified z then degenerates for any nonzero value
            # and would convict on a single occurrence, so such metrics are left to the
            # empirical tail channel and to the contract layer instead.
            if z is not None and mad and mad > 0:
                devs1[m] = z_to_dev(z)
            else:
                devs1[m] = 0.0
            sv, tl, _slvl = bl.eff_sample(art, cell, m)
            p_e = bl.tail_pvalue(sv, tl, x, bl.DIRECTION[m])
            if p_e is not None:
                ps_e[m] = p_e
                devs2[m] = tail_to_dev(p_e, ln_sat)
            d = max(devs1.get(m, 0.0), devs2.get(m, 0.0))
            if d > 0:
                worst.append((d, {"kind": "metric", "metric": m, "dev": round(d, 4),
                                  "z": round(z, 3) if z is not None else None, "value": x,
                                  "cell_median": med,
                                  "span_id": _worst_span(f, _SPAN_MODE.get(m))}))
        worst.sort(key=lambda t: (-t[0], t[1]["metric"]))

        l3 = l3_span(f, art, cell, ln_sat)
        struct = l4_contract(f, art, cell, ontology, binding)

        model, med_ll, mad_ll = ll_stats.get(cell) or (art.get("global_markov"), 0.0, 0.0)
        ll = bl.markov_logp(model, f.get("action_seq") or [])
        z5 = mod_z(ll, med_ll, mad_ll)
        if z5 is not None:
            z5 = -z5
        dev5 = z_to_dev(z5)

        pmet = dict((m, p) for m, p in ps_e.items() if p is not None)
        pfam = {}
        for fam, ms in bl.FAMILIES.items():
            ps = [pmet[m] for m in ms if m in pmet]
            if ps:
                pfam[fam] = min(1.0, len(ps) * min(ps))
        if l3["n_test"]:
            pfam["span"] = l3["p"]
        all_p = list(pmet.values())
        n_tests = len(all_p)
        if l3["n_test"] and l3["min_p"] < 1.0:
            all_p.append(l3["min_p"])
            n_tests += l3["n_test"]
        p_trace = min(1.0, n_tests * min(all_p)) if all_p else 1.0

        d1 = max(devs1.values()) if devs1 else 0.0
        d2 = max(devs2.values()) if devs2 else 0.0
        layers = {"L1": d1, "L2": d2, "L3": l3["dev"], "L4": struct["dev"], "L5": dev5}

        evidence = [ev for _, ev in worst[:2]]
        if l3["evidence"] and l3["dev"] > 0:
            evidence.append(l3["evidence"])
        for rule, cond, extra in (
                ("forbidden_action", struct["illegal_actions"],
                 {"actions": struct["illegal_actions"]}),
                ("missing_declared_step", struct["missing_declared"],
                 {"missing": struct["missing_declared"]}),
                ("missing_step", struct["missing_frac"] > 0 and not struct["missing_declared"],
                 {"missing": struct["missing_actions"],
                  "frac": round(struct["missing_frac"], 3)}),
                ("unfinished", struct["unfinished"] > 0,
                 {"expected_terminal": struct["terminal"]}),
                ("truncated_generation", struct["truncated"] > 0, {}),
                ("runaway_loop", struct["loop_rule"] > 0,
                 {"loop_count": f.get("loop_count")}),
                ("unrecovered_error", struct["unrecovered_errors"],
                 {"span_id": (struct["unrecovered_errors"] or [None])[0],
                  "count": len(struct["unrecovered_errors"])}),
                ("untraceable_answer_number", struct["traceable_viol"] > 0,
                 {"traceable_ratio": f.get("traceable_number_ratio"),
                  "min_ratio": struct["min_ratio"],
                  "untraceable": struct["untraceable_numbers"]})):
            if cond:
                item = {"kind": "rule", "rule": rule, "span_id": None}
                item.update(extra)
                evidence.append(item)
        if dev5 > 0:
            evidence.append({"kind": "sequence", "rule": "markov_low_likelihood",
                             "z": round(z5, 3) if z5 is not None else None, "span_id": None})

        b_cell = ((art["cell"].get(cell, {}) or {}).get("B_cell", 0.0)) if cell else 0.0
        stage[tid] = {
            "trace_id": tid, "cell": cell, "intent": intent_of.get(tid, -1),
            "novelty": nov, "layers": layers, "z": zs, "p_trace": p_trace,
            "p_family": pfam, "struct": struct, "ll": ll, "ll_z": z5,
            "span_dev": l3["dev"], "span_evidence": l3["evidence"],
            "evidence": evidence, "fallback_level": fallback, "b_cell": b_cell,
            "conf": _confidence(f, nov, b_cell, f.get("missing_field_ratio", 0.0)),
            "dev_by_metric": dict((m, max(devs1.get(m, 0.0), devs2.get(m, 0.0)))
                                  for m in set(list(devs1) + list(devs2))),
        }

    by_cell = {}
    for tid, st in stage.items():
        by_cell.setdefault(st["cell"], []).append(tid)
    for cell, tids in by_cell.items():
        rej = bh_fdr(tids, [stage[t]["p_trace"] for t in tids], bh_alpha)
        for t in tids:
            stage[t]["alert_stat"] = (t in rej) and not stage[t]["novelty"]
            stage[t]["alert_rule"] = (not stage[t]["novelty"]) and stage[t]["struct"]["hard"]
            stage[t]["alert"] = bool(stage[t]["alert_stat"] or stage[t]["alert_rule"])

    for cell, tids in by_cell.items():
        for layer in LAYER_WEIGHTS:
            r = _rank_norm([stage[t]["layers"].get(layer, 0.0) for t in tids])
            for t, rv in zip(tids, r):
                stage[t].setdefault("_rk", {})[layer] = rv
        wsum = sum(LAYER_WEIGHTS.values())
        for t in tids:
            rk = stage[t].get("_rk", {})
            graded = sum(LAYER_WEIGHTS[l] * rk.get(l, 0.0) for l in LAYER_WEIGHTS) / wsum
            tier = 2 if stage[t]["alert_rule"] else (1 if stage[t]["alert_stat"] else 0)
            lo, hi = TIER_BANDS[tier]
            stage[t]["tier"] = tier
            stage[t]["graded"] = graded
            stage[t]["a_raw"] = lo + (hi - lo) * graded
            stage[t].pop("_rk", None)

    info = {
        "bh_alpha": bh_alpha, "n": len(stage),
        "n_alert_stat": sum(1 for s in stage.values() if s["alert_stat"]),
        "n_alert_rule": sum(1 for s in stage.values() if s["alert_rule"]),
        "n_alert": sum(1 for s in stage.values() if s["alert"]),
        "n_novelty": sum(1 for s in stage.values() if s["novelty"]),
        "fallback_share": (sum(1 for s in stage.values() if s["fallback_level"] != "L3")
                           / float(len(stage))) if stage else 0.0,
        "layers": sorted(LAYER_WEIGHTS),
        "layer_weights": dict(LAYER_WEIGHTS),
        "n_bound_patterns": len(binding),
    }
    return stage, info