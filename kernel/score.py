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
GUARD_SAT = 2.0
LOOP_SAT = 3.0
TR_FLOOR = 0.5
MODEL_VERSION = "kernel-v0.1.0"


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
    if tr is None:
        tr_score, u["O"] = 0.90, u["O"] * 0.80
    else:
        tr_score = tr
    err = feats.get("error_ratio") or 0.0
    err_r = _clamp01(err / ERR_SAT)
    trunc = 1.0 if _truncated(feats) else 0.0
    s_o = (0.70 * tr_score + 0.30 * (1.0 - err_r)) * (1.0 - 0.40 * trunc)
    s_o = _clamp01(s_o)

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

    s_retry, _ = _anch(art, cell, "retry_count", feats.get("retry_count"))
    if s_retry is None:
        s_retry = 1.0
    guard = feats.get("guard_hits") or 0
    guard_r = _clamp01(guard / GUARD_SAT)
    s_r = 0.40 * (1.0 - err_r) + 0.30 * s_retry + 0.30 * (1.0 - guard_r)
    s_r = _clamp01(s_r)

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