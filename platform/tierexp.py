# -*- coding: utf-8 -*-
"""Tier / novelty-gate experiment (arms 3 and 4 of the mixed-ontology study).

Post-hoc, in-memory: writes NO file under data/ or reports/, touches no code_hash-closure file.
Reuses mixexp.build() so the cohorts are byte-identical to arms 1-2 (mixexp-results.json).

Two questions, both settled by measurement (results in tierexp-results.json):

Q1  Does the novelty buffer / credibility floor catch coherent foreign-paradigm traffic and
    route it to low-confidence human review, as one might assume?
    ANSWER: NO. kernel/cluster.py:862 gates novelty on *stability*, not on *size*:
        nov = singleton(ci) or singleton(cp) or cons_i < 0.35 or cons_p < 0.35 or geo <= geo_cut
    A homogeneous group of 200 foreign traces is maximally reproducible across the R_RUNS=8
    bagging runs, so it clears the gate with room to spare. Measured at 5% pollution:
    B n=200, n_novelty=1, cell i2xp2 n=199, consensus_intent median 0.9565 (threshold 0.35).
    The sample-size mechanism that does exist, credibility(n) = n/(n+KAPPA), KAPPA=30
    (kernel/baseline.py:175), only blends the anchor pool and picks level L3/L2/L1
    (baseline.py:355-384). credibility(199) = 0.869 -> level L3 -> *fully trusted*.
    It never vetoes a cell and never routes anything to human review.

Q2  What actually puts foreign traces at the top of the operator's top-K stream?
    ANSWER (read from code, then measured): severity tiering, not within-cluster spread.
        kernel/detect.py:643  tier = 2 if alert_rule else (1 if alert_stat else 0)
        kernel/detect.py:96   TIER_BANDS = {0:(0.00,0.40), 1:(0.40,0.75), 2:(0.75,1.00)}
        kernel/detect.py:647  a_raw = lo + (hi - lo) * graded
    Band 2's floor is band 1's ceiling, so ANY non-novelty trace that fires a hard rule
    outranks EVERY statistically-detected anomaly. Measured:
        5%  arm: a_raw_min_tier2_B = 0.81003  >  a_raw_max_tier1 = 0.72777 ; tier1_B = 0
        20% arm: a_raw_min_tier2_B = 0.80830  >  a_raw_max_tier1 = 0.69434 ; tier1_B = 0
    This FALSIFIES an earlier explanation of mine ("a few foreign traces clump into one tight
    cell, the within-cell std collapses, so every member looks extreme"). Three reasons it was
    wrong: the B cell held n=199 traces, not a handful; `graded` is a within-cell *rank*
    (detect.py:636 _rank_norm), so no standard deviation enters; and the cell was level L3.

Q3  (the actionable one) Does deleting required_steps from the tenant ontology - i.e. shipping
    the Tier-1-minimal ontology of LIFECYCLE.md 2.5 - remove the alert storm?
    PREDICTION MADE BEFORE MEASURING, from kernel/detect.py:279-280:
        declared_all = ontology.get("required_steps") or {}
        unfulfilled  = bool(declared_all) and not any(v <= present ...)
    so with the key absent bool({}) is False and unfulfilled is False for EVERY trace, foreign
    ones included -> hard loses its only unconditional trigger -> alert_rule stops firing on B.
    Cost predicted in the same breath: A loses its own unfulfilled fires (ctrl rate 0.01375).
    MEASURED (see main() output / tierexp-results.json): prediction confirmed on both sides.
        B tier2 count   199/200 -> 6/200   (5%)    766/800 -> 31/800   (20%)
        B alert_rate    0.995   -> 0.030           0.9575  -> 0.065
        overall alert   0.106   -> 0.0512          0.2365  -> 0.0530
        overall fpr     0.0512  -> 0.00054 (5%)    0.19113 -> 0.00597  (20%)   [32x better]
        topk precision  0.60    -> 1.00            1.00    -> 1.00
        A f1_pool       0.88142 -> 0.80745         0.84634 -> 0.74300          [the cost]
        n_pattern_clust 4       -> 4               4       -> 10               [shattering]
        novelty_rate    0.009   -> 0.009           0.009   -> 0.04625          [5x]
    The 20% arm's n_pattern_clusters 4 -> 10 and novelty 0.009 -> 0.046 are the measured
    confirmation of the kernel/cluster.py:48-54 warning that the cap is the binding constraint:
    n_declared_patterns=0 -> cluster.py:794 n_dec = 0 or 8 = 8 -> kmax_pat = 8. This is exactly
    what the proposed `pattern_count` field (LIFECYCLE.md 2.4) is for.
    Note the A-side f1 cost is NOT pollution-specific: under FULL, pollution alone moved A's f1
    only 0.88931 -> 0.88142 (-0.008). So ~-0.074 of the -0.082 is the price of dropping the
    unfulfilled channel at all, paid whether or not the project is polluted.

Run:  python -u platform/tierexp.py            (about 7 min for all four arms)
"""
import io, json, os, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "platform"))
import mixexp as MX
from kernel import ingest, features as FEAT, cluster, baseline as BL, binding as BD
from kernel import detect as DET, score, drift
from ontology.base import get_ontology

FULL = get_ontology("ontA")
SLIM = dict((k, v) for k, v in FULL.items() if k != "required_steps")


def _tier_hist(ids, stage):
    h = {}
    for t in ids:
        k = stage[t]["tier"]
        h[k] = h.get(k, 0) + 1
    return h


def pool_metrics(ids, stage, y):
    ids = [t for t in ids if t in y]
    if not ids:
        return None
    al = [t for t in ids if stage[t]["alert"]]
    an = [t for t in ids if y[t]]
    nm = [t for t in ids if not y[t]]
    tp = sum(1 for t in al if y[t])
    fp = sum(1 for t in al if not y[t])
    prec = tp / float(tp + fp) if (tp + fp) else None
    rec = tp / float(len(an)) if an else None
    f1 = (2 * prec * rec / (prec + rec)) if (prec and rec and (prec + rec)) else 0.0
    return {"n": len(ids), "alert_rate": round(len(al) / float(len(ids)), 5),
            "fpr_pool": round(fp / float(len(nm)), 5) if nm else None,
            "recall_pool": round(rec, 5) if rec is not None else None,
            "f1_pool": round(f1, 5),
            "n_tier2": sum(1 for t in ids if stage[t]["tier"] == 2)}


def arm(frac, tag, ont, census=True):
    traces, gts = MX.build(frac)
    gt = dict((g["trace_id"], g) for g in gts)
    src = dict((t["trace_id"], t["_src"]) for t in traces)
    t0 = time.time()
    norms = [ingest.normalize(t, ont) for t in traces]
    feats = [FEAT.extract(n, ont) for n in norms]
    FEAT.annotate_sessions(feats, traces)
    cluster.reset_cache()
    assigns, cinfo = cluster.cluster_views(
        feats, threshold=cluster.CONSENSUS_THRESHOLD, seed=MX.SEED,
        n_declared_patterns=len(ont.get("required_steps") or {}))
    AS = dict((a["trace_id"], a) for a in assigns)
    records = [{"cell": a["cell"], "intent": a.get("near_intent", -1), "feats": f}
               for a, f in zip(assigns, feats) if not a["novelty"]]
    art = BL.build(records, ont, "anchor-%s" % tag)
    binding = BD.bind_patterns(art, ont)
    stage, dinfo = DET.detect_all(feats, assigns, art, ont, binding=binding,
                                  bh_alpha=DET.BH_ALPHA)
    ordered = sorted(feats, key=lambda f: (f["ts_start"], f["trace_id"]))
    cell_of = dict((a["trace_id"], a["cell"]) for a in assigns)
    par_of = dict((a["trace_id"], "i%d" % a.get("near_intent", -1)) for a in assigns)
    stream = [(f["trace_id"], cell_of.get(f["trace_id"]), par_of.get(f["trace_id"]),
               f["latency_total"]) for f in ordered]
    dr = drift.detect_drift(stream)
    recs = score.score_all(feats, assigns, stage, art, ont, cold_start=len(feats) < 1000,
                           drift_map=dict((x, True) for x in set(dr.get("suspects") or [])),
                           anchor_version="anchor-%s" % tag, model_version=tag)
    R = dict((r["trace_id"], r) for r in recs)
    tids = [f["trace_id"] for f in feats]
    y = dict((t, bool(gt[t]["is_anomaly"])) for t in tids if t in gt)
    pool = [t for t in tids if not R[t]["novelty"] and t in y]
    ranked = sorted(pool, key=lambda t: -stage[t]["a_raw"])
    topk = ranked[:MX.BUDGET_K]
    At = [t for t in tids if src[t] == "A"]
    Bt = [t for t in tids if src[t] == "B"]

    res = {"tag": tag, "frac": frac, "ontology": "slim" if ont is SLIM else "full",
           "wall_s": round(time.time() - t0, 1),
           "n_intent_clusters": cinfo.get("n_intent_clusters"),
           "n_pattern_clusters": cinfo.get("n_pattern_clusters"),
           "novelty_rate_all": cinfo.get("novelty_rate"),
           "n_bound_patterns": dinfo.get("n_bound_patterns"),
           "overall": pool_metrics(pool, stage, y),
           "A": pool_metrics(At, stage, y),
           "B": pool_metrics(Bt, stage, y) if Bt else None,
           "topk_A_share": round(sum(1 for t in topk if src[t] == "A") / float(len(topk)), 4),
           "topk_precision": round(sum(1 for t in topk if y[t]) / float(len(topk)), 4),
           "topk_tiers": sorted(set(stage[t]["tier"] for t in topk)),
           "a_raw_max_tier1": round(max([stage[t]["a_raw"] for t in pool
                                         if stage[t]["tier"] == 1], default=-1), 5),
           "a_raw_min_tier2_B": round(min([stage[t]["a_raw"] for t in topk
                                           if src[t] == "B"], default=-1), 5)}
    if census:
        for lbl, ids in (("A", At), ("B", Bt)):
            if not ids:
                continue
            nov = [t for t in ids if AS[t]["novelty"]]
            byc = {}
            for t in ids:
                if not AS[t]["novelty"]:
                    byc.setdefault(AS[t]["cell"], []).append(t)
            ci = sorted(AS[t]["consensus_intent"] for t in ids)
            res["census_" + lbl] = {
                "n": len(ids), "n_novelty": len(nov),
                "novelty_rate": round(len(nov) / float(len(ids)), 5),
                "cells": dict((c, len(v)) for c, v in sorted(byc.items())),
                "consensus_intent_min": round(ci[0], 4),
                "consensus_intent_median": round(ci[len(ci) // 2], 4),
                "tier_hist": dict((str(k), v) for k, v in sorted(_tier_hist(ids, stage).items())),
                "credibility_of_largest_cell": round(
                    BL.credibility(max(len(v) for v in byc.values())), 4) if byc else None}
    print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)
    return res


def main():
    out = []
    for frac, tag, ont in [(0.05, "full-05pct", FULL), (0.20, "full-20pct", FULL),
                           (0.05, "slim-05pct", SLIM), (0.20, "slim-20pct", SLIM)]:
        print("=== %s (required_steps %s) ==="
              % (tag, "declared" if ont is FULL else "DELETED"), flush=True)
        out.append(arm(frac, tag, ont))
    mxf = "platform/mixexp-results.json"
    full_overall = {}
    if os.path.exists(mxf):
        mx = json.load(io.open(mxf, encoding="utf-8"))
        for r in mx:
            if r.get("tag") in ("mix-05pct", "mix-20pct"):
                full_overall[r["tag"]] = {"overall": r.get("overall"), "A": r.get("A"),
                                          "B": r.get("B"),
                                          "topk_precision": r.get("topk_precision"),
                                          "topk_A_share": r.get("topk_A_share")}
    payload = {"_note": ("Regenerated by platform/tierexp.py. FULL = ontA as shipped "
                         "(required_steps declared); SLIM = ontA with required_steps DELETED, "
                         "i.e. the Tier-1-minimal tenant ontology of LIFECYCLE.md 2.5. Same "
                         "harness as mixexp.py: SEED=20261109, calibration skipped, post-hoc "
                         "in-memory. full_overall_from_mixexp is copied through from arms 1-2 "
                         "for single-table comparison."),
               "arms": out, "full_overall_from_mixexp": full_overall}
    with io.open("platform/tierexp-results.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("TIEREXP DONE", flush=True)


if __name__ == "__main__":
    main()
