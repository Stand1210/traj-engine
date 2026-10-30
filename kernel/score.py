"""Explorable scoring: 5 dimensions x 4 anchors x hard gates x LMDI zero-residual attribution.

Shape of the score
    S = 100 * G * Q,   Q = exp( sum_d u_d w_d ln(s_d) / sum_d u_d w_d ),   s_d in [EPS, 1]
  s_d : each dimension is mapped from raw metrics through the *cell-conditional* 4-anchor
        piecewise ladder of kernel.baseline (ideal=1.0, good=0.8, warn=0.5, bad=0.0), so the
        same 90s latency scores 1.0 in a deep-analysis cell and 0.0 in a simple-query cell.
  G   : product of triggered hard-gate multipliers (guard block, forbidden action, broken
        result, unfinished, runaway loop, drift suspect, novelty). Gates are business
        vetoes, not statistics, so they multiply instead of subtract.
  u_d : per-dimension confidence. A cost estimated from missing usage tokens (flag
        usage_estimated) must not be allowed to convict a trace, so its vote is downweighted
        instead of being silently trusted.
  EPS : floor of 0.02 keeps the geometric mean defined and bounded when a dimension collapses.

Why geometric mean: it is a *conjunctive* aggregator - one collapsed dimension cannot be
compensated by excellence elsewhere, which is exactly the semantics an SRE wants.

Outcome dimension (slice2): channels are admitted by measured contamination
---------------------------------------------------------------------------------
slice1 scored O from a single v1 proxy, `0.70*traceable_number_ratio + 0.30*(1-error_ratio/
ERR_SAT)` times a truncation multiplier, with a missing ratio substituted by the constant 0.90.
Measured against the generator's own per-dimension truth `dim_dev["O"]` over all 22,800 traces of
bench_v1, that composite ranks *worse than every one of its own ingredients*: mean Spearman
+0.4394 (worst regime +0.2906) against +0.7248 for traceable_number_ratio alone, +0.6575 for
fact_precision, +0.5887 for verifier_pass_rate. Two defects, both structural rather than tuned:
the 0.90 constant tied every answer-without-numbers (13.4% of bench_v1, 32.7% of R8) at exactly
0.93, so a clean trace was indistinguishable from a fabricating one with ten numbers; and O had
no completeness channel at all, so the `unfinished` class (truth 0.55) scored 1.000.

Admission rule. A channel may charge O only if it stays put on every defect class whose outcome
truth is 1.0. Contamination is measured as the trace-weighted |mean(channel | class) -
mean(channel | normal)| summed over those five classes (illegal_step, latency_spike, loop,
missing_step, token_bloat):

    traceable_number_ratio  0.0     fact_precision       0.0     error_ratio  3.2
    verifier_pass_rate     24.5     citation_reachability 27.3    key_fact_recall 65.6

The three contaminated channels are reading defects that belong to another dimension --
key_fact_recall falls to 0.659 on missing_step (a P defect), verifier_pass_rate to 0.813 on
illegal_step (P), citation_reachability to 0.932 / 0.936 on missing_step / token_bloat (P / C).
Wiring them into O would book one defect against two dimensions, which is precisely what the
zero-residual attribution below promises not to do: an auditor asking "which dimension cost how
many points" would get the same defect counted twice. They remain emitted as features and remain
usable by detection; they simply do not vote in O.

`key_fact_recall` was the documented slice2 candidate and is rejected on measurement, not taste:
25.9% availability (it needs `golden_facts`), the highest contamination of the six, and
rank-redundant once the structural completeness channel is present -- mean Spearman is +0.9561
with it and +0.9561 without. `1 - struct.unfinished` says the same thing on 100% of traffic, and
detect.py only reaches 1.0 on *confirmed* non-completion (aborted, or a required step short), so
the 0.35 "ended on an unusual step" soft case is left to P where it is already graded. The
generator's `unfinished` pops trailing spans, so the last action is no longer the cell's dominant
terminal and detect reports 1.0; `missing_step` deletes an *interior* required step, the terminal
survives and detect reports 0.0. The discriminator is real, not fitted.

Selection. A 6x6 grid over (GROUND_SAT, completeness weight) was scored by mean Spearman against
`dim_dev["O"]` subject to zero class-order inversions, because Spearman over a whole regime is
blind to ordering *within* the small anomaly classes: each is under 1.1% of traffic, so moving
truncation below hallucinated_number costs nothing measurable while reversing what a triage queue
shows. Mean Spearman turned out to be a plateau (+0.9559..+0.9561) across the entire grid, i.e.
the grid is really choosing the ordering, and this cell has the widest margin. GROUND_SAT = 2.0
saturates the grounding channel at traceable_number_ratio = 0.5, exactly where TR_FLOOR hands over
to the t0_result_broken veto, so the graded channel and the hard gate meet with neither a gap nor
an overlap. The slice1 truncation multiplier is dropped: truncation is already that veto and
already depresses traceable_number_ratio (0.637 on the class), and multiplying on top is what
caused the inversion. sat_g 2.5 ties on margin but saturates at 0.4 and would overlap the veto
band; 1.5 and 1.25 stay inversion-free only at margins of +0.0312 and +0.0044.

Result. Offline over all 22,800 traces with an *oracle* completeness channel
(`gt.process_flags.unfinished`): mean Spearman vs dim_dev["O"] +0.4394 -> +0.9561, worst regime
+0.2906 -> +0.8898; class means hallucinated 0.550 < truncation 0.655 < unfinished 0.740 <
error 0.819 < normal 0.999 against truth 0.15 < 0.35 < 0.55 < 0.75 < 1.00, minimum adjacent
margin +0.0793, zero inversions. Shipped code substitutes detect.l4_contract's `struct.unfinished`
for that oracle and loses little: on R4 the realized `scoring.per_dim.O.spearman` is
0.5089 -> 0.9347. Realized per-regime figures belong in reports/<rid>/metrics.json, not here, so
that this comment need not be re-edited (and the code re-hashed) after every matrix run.

One deliberate trade, measured. R4 `scoring.score_auc` goes 0.8598 -> 0.8525. The slice1 constant
was accidentally discriminating: it charged 0.93 instead of 1.00 to every trace whose answer
carries no numbers (3046 of 22800 = 13.4% of bench_v1, 32.7% of R8), and that set is 1.42x
enriched in anomalies (11.2% vs 7.9%), concentrated in missing_step (3.4x baseline) and
unfinished (1.9x). So O was borrowing a little detection power from a defect it cannot name.
Dropping the constant returns it: mean_S_normal 89.93 -> 90.13, mean_S_anomaly flat at
51.13 -> 51.15. Everything that is supposed to improve does -- spearman_vs_oracle
0.7811 -> 0.7879, kendall_vs_oracle 0.5992 -> 0.6063, grade_separation 38.81 -> 38.98 -- and
per_dim for P/L/C/R plus every gate value stay bit-identical, because O is the only block touched.

Two more channels measured and rejected. `unfaithful_fact_count` is the cleanest channel in the
whole contract -- 100% available, contamination exactly 0.00, and on bench_v1 a perfect
truncation/hallucination discriminator (truncation only ever carries 1, hallucinated_number only
ever 2, all else 0) -- but it is nearly empty: 102 nonzero values in 22,800 traces (0.45%).
Wired in as 1 - min(1, count / FAITH_SAT) it moves mean Spearman by +0.00002 and *costs* the
binding margin, +0.0793 -> +0.0680 / +0.0634 / +0.0595 at weight 0.05 / 0.10 / 0.15 / 0.20,
because it reads 1.0 on unfinished and error and drags both up toward normal. Substituting it for
`fact_precision` is no better (+0.95611 either way). A channel that buys nothing on rank fidelity
while shrinking the margin the entire ordering rests on is a net loss; it stays a detection
feature and does not vote in O. `verifier_pass_rate` and `citation_reachability` fail earlier,
on contamination.

Robustness dimension (slice3): three exact-zero channels replace two proxies
----------------------------------------------------------------------------
slice2 left R the worst dimension by a wide margin. Realized mean Spearman against the
generator's own `dim_dev["R"]` was +0.3260 (worst regime +0.2665), while R's best single
ingredient, `error_ratio`, reaches +0.7504 alone -- the composite ranked below its own parts,
the same pathology slice2 removed from O. Three structural defects, in descending damage:

  1. `retry_count` (weight 0.30, anchored, constant-filled to 1.0 when no anchor exists).
     Retrying is ordinary traffic, not a robustness defect: it is nonzero on 16% of *clean*
     traces, mean 0.1714 there against 0.2045 / 1.1404 / 0.9908 on the error / loop /
     error-recovered classes. That is an effect size of d = 1.596 of spread *inside* the group
     carrying 98.2% of the traffic whose R truth is a flat 1.0, i.e. pure dilution.
  2. `guard_hits` (weight 0.30). Contaminated, trace-weighted deviation 0.28 against the defect
     classes whose R truth is 1.0, worst `illegal_step` at 64.0, because the generator inserts a
     `guard_block` span for that class. It also double-booked the `guard_violation` veto below,
     so a single guard hit was charged twice in one score.
  3. Constant-filling a missing channel -- exactly the slice1 O defect, still present here.

R truth has four levels and is 1.0 on 22,381 of 22,800 traces (98.2%), so R's Spearman is almost
entirely "can the 419 low-truth traces be separated cleanly". Any channel that varies inside the
ok group is noise by construction, which makes *exactness* the selection criterion rather than
effect size.

Admission rule, as in O: a channel may charge R only if it stays put on every defect class whose
R truth is 1.0 (illegal_step, latency_spike, missing_step, token_bloat, truncation,
hallucinated_number, unfinished). Contamination is the trace-weighted |mean(ch | class) -
mean(ch | normal)| summed over those seven:

    error_ratio 0.00   unrecovered_errors 0.00   loop_rule 0.00   self_correction_count 0.00
    retry_count 0.34   guard_hits 0.28   n_guard 0.57   n_spans 3.44

`error_ratio`, `len(unrecovered_errors)` and `loop_rule` are not merely low-contamination, they
are *exactly zero* on all 22,381 ok traces (nonzero count 0). A clean trace therefore gets
s_r = 1.0 exactly and adds nothing to within-group tie noise. Four more channels pass admission
but are rank-redundant with these three and were dropped: `self_correction_count` (0.9817 on
error-recovered, 0 elsewhere), `loop_run_max` / `loop_count` (3.13 / 3.01 on loop, 0 elsewhere),
`path_convergence` (66% nonzero on loop). `warn_level_ratio`, `plan_revision_count`,
`kind_ratio_guard` and `guard_time_ratio` carry no signal at all (effect size <= 0.27, solo
Spearman ~ 0).

Selection: a 153-cell simplex at step 0.05 over the three weights, scored by mean Spearman
against `dim_dev["R"]` subject to zero class-order inversions, then by widest minimum adjacent
margin. Mean Spearman is a plateau here too (range 6e-5 over all 153 cells), so the grid selects
the *ordering*, not the rank fidelity. Chosen 0.20 / 0.50 / 0.30.

Result, offline over all 22,800 traces: mean Spearman +0.3260 -> +0.9987, worst regime +0.2665 ->
+0.9896, zero inversions, minimum adjacent margin +0.1121. Class means error 0.6154 < loop
0.7750 < error-recovered 0.8879 < ok 1.0000 against truth 0.35 < 0.55 < 0.60 < 1.00.

Recovery needs no term of its own. The generator writes R truth 0.60 for an error that was
recovered and 0.35 for one that was not, and the two error channels already diverge exactly
there: `error_ratio` counts the errored step either way, `unrecovered_errors` only counts what
survived. Recovery is therefore encoded as the *gap* between x_fail and x_unrec, which is
detect.l4_contract's own semantics ("a recovered error is a blemish, not an incident"). Adding
`self_correction_count` -- the obvious explicit recovery term -- was measured both ways and
rejected both ways: as a fourth penalty it inverts error-recovered below loop (0.6915 vs 0.8125,
margin -0.1210); as a credit it leaves mean Spearman at +0.998693, identical to five decimals,
while shrinking the margin the whole ordering rests on, +0.1121 -> +0.0793.

Every admitted channel is load-bearing. Dropping `unrecovered_errors` inverts error above loop
(0.7347 vs 0.5500); dropping `loop_rule` scores the loop class 1.0000 and falls to +0.7504;
`unrecovered_errors` alone gives +0.5719 with two inversions. The rejected additions are
quantitatively catastrophic rather than merely unhelpful: `retry_count` at weight 0.25 drags mean
Spearman to +0.3506, `guard_hits` at 0.25 to +0.9107, and the slice2 form reproduces offline at
+0.3274 against the +0.3260 it realized, so the harness is faithful.

Two deliberate non-changes. `ERR_SAT` is *shared* with O instead of getting its own `ERR_SAT_R`:
a separate 0.25 reaches margin +0.1231, but mean Spearman is identical to five decimals
(+0.998691 vs +0.998693, the shared value marginally higher) and the zero-inversion feasible
region is narrower, 42 of 153 cells against 47. One physical quantity -- the fraction of steps
that errored -- gets one saturation point; two knobs would silently couple O and R in the adapt
playbook. And `error_ratio` voting in both O and R does not break zero-residual attribution,
because the *generator* double-books it: the error-injection branch sets `dim["O"]` and
`dim["R"]` for the same injected error. The admission rule forbids a channel whose target
dimension's truth does not move; `error_ratio` has contamination 0.00 against both O's and R's
truth-1.0 class sets, so it is admissible in both.

L was measured and left alone; see the slice3 note in README for the oracle ceiling table.

Zero-residual attribution (LMDI)
    S_base = 100*G            L = (S - S_base) / (ln S - ln S_base)
    contrib_d = L * (u_d w_d / sum u w) * ln(s_d)
    => sum_d contrib_d == S - S_base   exactly (logarithmic-mean identity, no residual).
  Gate losses are reported separately in `gates` rather than being smeared across
  dimensions, so the audit trail answers "which dimension cost how many points" and
  "which veto cost how many points" without a leftover bucket.
"""
import math

from kernel import baseline as bl

EPS = 0.02
WEIGHTS = {"O": 0.40, "P": 0.20, "L": 0.15, "C": 0.15, "R": 0.10}
GATES = {"guard_violation": 0.15, "t0_result_broken": 0.25, "t1_unfinished": 0.25,
         "forbidden_action": 0.30, "loop_runaway": 0.35, "drift_suspect": 0.50,
         "t2_untraceable_number": 0.60, "novelty": 0.80}
GRADE_ABS = (("A", 90.0), ("B", 75.0), ("C", 60.0))
ERR_SAT = 0.30
LOOP_SAT = 3.0
TR_FLOOR = 0.5
# Saturating gain on the *untraceable* fraction of the answer's numbers. 2.0 exhausts the
# grounding channel at traceable_number_ratio = 0.5, which is TR_FLOOR: below that the
# t0_result_broken veto governs, so the graded channel and the hard gate meet exactly.
GROUND_SAT = 2.0
# Outcome channels. Absent channels are dropped and these renormalised -- never replaced by a
# constant, which is the defect that cost slice1 half its rank fidelity. See the docstring.
W_O_NUM = 0.70      # traceable_number_ratio, saturated by GROUND_SAT   contamination 0.0
W_O_PREC = 0.15     # fact_precision (needs golden_facts, 25.9% of traffic)  contamination 0.0
W_O_EXEC = 0.30     # 1 - error_ratio / ERR_SAT                            contamination 3.2
W_O_COMP = 0.25     # structural completeness, 1 - confirmed unfinished
# Saturating gain on the count of errored steps the agent never retried successfully. LOCKED at
# 2.0 because it mirrors detect.l4_contract's own err_dev = min(1.0, len(unrecovered) / 2.0);
# diverging here would decouple the scorer from the detector's definition of the same quantity.
UNREC_SAT = 2.0
# Robustness channels, same drop-and-renormalise rule as O. `retry_count` and `guard_hits` were
# dropped in slice3 on measurement and GUARD_SAT was deleted with them: see the docstring.
W_R_FAIL = 0.20     # 1 - error_ratio / ERR_SAT (shared with O)             contamination 0.00
W_R_UNREC = 0.50    # 1 - len(unrecovered_errors) / UNREC_SAT               contamination 0.00
W_R_LOOP = 0.30     # 1 - loop_rule                                         contamination 0.00
MODEL_VERSION = "kernel-v0.3.0"


def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _anch(art, cell, metric, x):
    if x is None:
        return None, None
    ent = art["cell"].get(cell) if cell else None
    a = (ent or {}).get("anchors", {}).get(metric)
    if a is None:
        g = art["global"].get(metric, {})
        med = g.get("median")
        if med is None:
            return None, None
        a = {"ideal": med, "good": med, "warn": med, "bad": med}
    return bl.anchor_score(a, x, bl.DIRECTION[metric]), a


def _truncated(feats):
    for s in feats.get("spans") or []:
        if s.get("finish_reason") == "length":
            return True
    return False


def score_one(feats, assign, det, art, ontology, cold_start=False, drift_suspect=False,
              anchor_version="anchor-v1", model_version=MODEL_VERSION):
    cell = assign.get("cell")
    nov = bool(assign.get("novelty"))
    struct = (det or {}).get("struct") or {}
    flags = feats.get("flags") or {}
    mfr = feats.get("missing_field_ratio", 0.0) or 0.0

    u = {"O": 1.0, "P": 1.0, "L": 1.0, "C": 1.0, "R": 1.0}

    tr = feats.get("traceable_number_ratio")
    err = feats.get("error_ratio") or 0.0
    err_r = _clamp01(err / ERR_SAT)
    trunc = 1.0 if _truncated(feats) else 0.0
    g_num = None if tr is None else _clamp01(1.0 - GROUND_SAT * (1.0 - tr))
    f_prec = feats.get("fact_precision")
    unf = struct.get("unfinished") if struct else None
    x_comp = None if unf is None else (0.0 if unf >= 1.0 else 1.0)
    o_num = o_den = 0.0
    for wgt, val in ((W_O_NUM, g_num), (W_O_PREC, f_prec),
                     (W_O_EXEC, 1.0 - err_r), (W_O_COMP, x_comp)):
        if val is None:
            continue
        o_num += wgt * val
        o_den += wgt
    s_o = _clamp01((o_num / o_den) if o_den else 1.0)
    if g_num is None:
        u["O"] *= 0.90
        if f_prec is None:
            u["O"] *= 0.85
    if x_comp is None:
        u["O"] *= 0.80

    missing_frac = struct.get("missing_frac", 0.0) or 0.0
    illegal = 1.0 if struct.get("illegal_actions") else 0.0
    unfinished = struct.get("unfinished", 0.0) or 0.0
    loop = feats.get("loop_count") or 0
    s_p = 1.0 - min(1.0, 0.40 * missing_frac + 0.45 * illegal + 0.30 * unfinished
                    + 0.20 * min(1.0, loop / float(LOOP_SAT)))
    s_p = _clamp01(s_p)
    if not struct.get("required"):
        u["P"] *= 0.70

    s_l_val, _ = _anch(art, cell, "latency_total", feats.get("latency_total"))
    s_l = 1.0 if s_l_val is None else s_l_val
    if s_l_val is None:
        u["L"] *= 0.6
    if flags.get("ts_repaired"):
        u["L"] *= 0.70

    s_cost, _ = _anch(art, cell, "cost_total", feats.get("cost_total"))
    s_tok, _ = _anch(art, cell, "tokens_total", feats.get("tokens_total"))
    parts, wts = [], []
    if s_cost is not None:
        parts.append(s_cost)
        wts.append(0.6)
    if s_tok is not None:
        parts.append(s_tok)
        wts.append(0.4)
    s_c = (sum(p * w for p, w in zip(parts, wts)) / sum(wts)) if wts else 1.0
    if not wts:
        u["C"] *= 0.6
    if flags.get("usage_estimated"):
        u["C"] *= 0.60

    guard = feats.get("guard_hits") or 0      # read for the guard_violation veto, not for s_r
    unrec = struct.get("unrecovered_errors") if struct else None
    lr = struct.get("loop_rule") if struct else None
    x_unrec = None if unrec is None else 1.0 - _clamp01(len(unrec) / UNREC_SAT)
    x_loop = None if lr is None else 1.0 - _clamp01(lr)
    r_num = r_den = 0.0
    for wgt, val in ((W_R_FAIL, 1.0 - err_r), (W_R_UNREC, x_unrec), (W_R_LOOP, x_loop)):
        if val is None:
            continue
        r_num += wgt * val
        r_den += wgt
    s_r = _clamp01((r_num / r_den) if r_den else 1.0)
    if x_unrec is None:
        u["R"] *= 0.75
    if x_loop is None:
        u["R"] *= 0.85

    if mfr > 0.20:
        for d in u:
            u[d] *= 0.80
    if nov:
        u["L"] *= 0.50
        u["C"] *= 0.50
        u["R"] *= 0.70

    dims = {"O": s_o, "P": s_p, "L": s_l, "C": s_c, "R": s_r}

    gates = {}
    if guard > 0:
        gates["guard_violation"] = GATES["guard_violation"]
    if illegal > 0:
        gates["forbidden_action"] = GATES["forbidden_action"]
    if (tr is not None and tr < TR_FLOOR) or trunc > 0:
        gates["t0_result_broken"] = GATES["t0_result_broken"]
    elif struct.get("traceable_viol"):
        # the ontology validator is breached but the answer is still mostly grounded:
        # a veto would be disproportionate, a graded multiplier is not.
        gates["t2_untraceable_number"] = GATES["t2_untraceable_number"]
    if unfinished > 0:
        gates["t1_unfinished"] = GATES["t1_unfinished"]
    if loop >= LOOP_SAT:
        gates["loop_runaway"] = GATES["loop_runaway"]
    if drift_suspect:
        gates["drift_suspect"] = GATES["drift_suspect"]
    if nov:
        gates["novelty"] = GATES["novelty"]
    g = 1.0
    for v in gates.values():
        g *= v

    num = 0.0
    den = 0.0
    for d, w in WEIGHTS.items():
        sd = max(dims[d], EPS)
        num += u[d] * w * math.log(sd)
        den += u[d] * w
    q = math.exp(num / den) if den > 0 else EPS
    s_base = 100.0 * g
    s = s_base * q

    contrib = {}
    if den > 0 and abs(s - s_base) > 1e-12 and s > 0 and s_base > 0:
        lmean = (s - s_base) / (math.log(s) - math.log(s_base))
        for d, w in WEIGHTS.items():
            contrib[d] = lmean * (u[d] * w / den) * math.log(max(dims[d], EPS))
    else:
        contrib = dict((d, 0.0) for d in WEIGHTS)

    conf = (det or {}).get("conf", 1.0)
    hw = 3.0 + 12.0 * (1.0 - conf)
    grade = "D"
    for name, cut in GRADE_ABS:
        if s >= cut:
            grade = name
            break
    return {
        "trace_id": feats["trace_id"],
        "cell": cell,
        "dims": dims,
        "dim_conf": u,
        "gates": gates,
        "G": g,
        "Q": q,
        "S": s,
        "S_base": s_base,
        "grade_abs": grade,
        "grade_rel": grade,
        "contrib": contrib,
        "ci": [max(0.0, s - hw), min(100.0, s + hw)],
        "conf": conf,
        "cold_start": bool(cold_start),
        "model_version": model_version,
        "anchor_version": anchor_version,
        "alert": bool((det or {}).get("alert")),
        "alert_stat": bool((det or {}).get("alert_stat")),
        "alert_rule": bool((det or {}).get("alert_rule")),
        "a_raw": (det or {}).get("a_raw", 0.0),
        "tier": int((det or {}).get("tier", 0)),
        "graded": float((det or {}).get("graded", 0.0)),
        "evidence": (det or {}).get("evidence", []),
        "novelty": nov,
    }


def score_all(features, assigns, stage, art, ontology, cold_start=False, drift_map=None,
              anchor_version="anchor-v1", model_version=MODEL_VERSION):
    amap = dict((a["trace_id"], a) for a in assigns)
    dmap = drift_map or {}
    out = []
    for f in features:
        tid = f["trace_id"]
        out.append(score_one(f, amap.get(tid, {}), stage.get(tid), art, ontology,
                             cold_start=cold_start, drift_suspect=bool(dmap.get(tid)),
                             anchor_version=anchor_version, model_version=model_version))
    assign_relative_grades(out)
    return out


def assign_relative_grades(recs, min_cell=8):
    """Within-cell relative grade: top 25% A / next 35% B / next 25% C / bottom 15% D."""
    by = {}
    for r in recs:
        by.setdefault(r["cell"], []).append(r)
    for cell, rs in by.items():
        if len(rs) < min_cell:
            for r in rs:
                r["grade_rel"] = r["grade_abs"]
            continue
        rs.sort(key=lambda r: (-r["S"], r["trace_id"]))
        n = len(rs)
        for i, r in enumerate(rs):
            f = i / float(n)
            r["grade_rel"] = "A" if f < 0.25 else ("B" if f < 0.60 else ("C" if f < 0.85 else "D"))
    return recs