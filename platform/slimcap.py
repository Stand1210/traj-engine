# -*- coding: utf-8 -*-
"""slimcap -- does the misrouted bucket still earn its keep AFTER required_steps was deleted
              AND the cap was fixed to 5 as an L2 constant?

The user's challenge
--------------------
"1 project = 1 ontology = 1 agent is a ratified contract. Another agent reporting into this
project is the business misusing it. We should not build machinery for that -- it is
over-design."

That challenge is aimed at F4's `misrouted` bucket, whose entire stated justification is:
"if we do not exclude foreign traffic, 5% pollution drops topk(15) precision 1.0 -> 0.60,
below OPS_STREAM_PRECISION_MIN = 0.80" (MODULES.md F4 table, DESIGN.md 6.2).

Checking that number against the data shows it was measured on an ontology we no longer ship:
    platform/tierexp-results.json
      full-05pct  (required_steps DECLARED)  topk_precision 0.6   tier2_B 199/200
      slim-05pct  (required_steps DELETED)   topk_precision 1.0
      slim-20pct  (required_steps DELETED)   topk_precision 1.0
The mechanism was: a foreign trace fulfils none of the declared patterns -> `unfulfilled`
(detect.py:279-280) -> `hard` (:388) -> unconditional alert (:631) -> tier 2, whose floor is
tier 1's ceiling (TIER_BANDS) -> foreign traces outrank every statistical anomaly and
monopolise top-K. **Deleting required_steps removes that unconditional trigger**, and tierexp
measured the alert storm collapsing with it (B alert_rate 0.995 -> 0.030 at 5%;
overall fpr 0.19113 -> 0.00597 at 20%, 32x).

So the ONLY pollution damage left in the slim arms is the clustering shattering
(n_pattern_clusters 4 -> 10, novelty 0.009 -> 0.04625 at 20%). But tierexp's slim arm changed
TWO things at once, because tierexp.py:113 derives the cap from the ontology:
    n_declared_patterns = len(ont.get("required_steps") or {})
    FULL -> len(3 steps) = 3 -> cap 5 ;  SLIM -> len({}) = 0 -> cap 8
i.e. "slim" conflated "required_steps deleted" with "cap loosened 5 -> 8". And this session
just decided (DESIGN.md 7.6) that production pins the cap at 5 via the L2 constant
PATTERN_CAP_NDEC_DEFAULT = 3, regardless of what the tenant ontology declares.

**The unmeasured intersection is therefore SLIM x cap 5.** If pinning the cap at 5 already
absorbs the pollution, the misrouted bucket defends against a failure mode that no longer
exists and should be deleted -- the user is right. If shattering survives, "business error"
still costs *us* something measurable, and that has to be said with a number.

Design: one variable at a time. Ontology fixed at SLIM (= the real Tier-1-minimal tenant
ontology). Sweep cap in {8, 5} x pollution in {0%, 5%, 20%}. The 0% control separates
"damage caused by pollution" from "damage caused by the cap".

Post-hoc and in-memory: writes nothing under data/ or reports/, touches no code_hash-closure
file. Reuses mixexp.build() so cohorts are byte-identical to mixexp/tierexp arms, and reuses
tierexp.pool_metrics / _tier_hist. Only the arm body is re-implemented, because tierexp.arm
hard-codes the cap derivation at :113 and injecting a fake `required_steps` to fake the cap
would re-enable the `unfulfilled` channel and invalidate the comparison.

Run:  python -u platform/slimcap.py        (about 11 min for 6 arms)
Writes platform/slimcap-results.json
"""
import io, json, os, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "platform"))
import mixexp as MX
import tierexp as TX
from kernel import ingest, features as FEAT, cluster, baseline as BL, binding as BD
from kernel import detect as DET, score, drift

SLIM = TX.SLIM                      # ontA with required_steps DELETED = the real tenant ontology
ARMS = [(0.0, 0, "cap8"), (0.0, 3, "cap5"),
        (0.05, 0, "cap8"), (0.05, 3, "cap5"),
        (0.20, 0, "cap8"), (0.20, 3, "cap5")]


def arm(frac, ndec, cap_tag):
    tag = "slim-%02dpct-%s" % (round(frac * 100), cap_tag)
    traces, gts = MX.build(frac)
    gt = dict((g["trace_id"], g) for g in gts)
    src = dict((t["trace_id"], t["_src"]) for t in traces)
    ont = SLIM
    t0 = time.time()
    norms = [ingest.normalize(t, ont) for t in traces]
    feats = [FEAT.extract(n, ont) for n in norms]
    FEAT.annotate_sessions(feats, traces)
    cluster.reset_cache()
    assigns, cinfo = cluster.cluster_views(
        feats, threshold=cluster.CONSENSUS_THRESHOLD, seed=MX.SEED, n_declared_patterns=ndec)
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
    dr = drift.detect_drift([(f["trace_id"], cell_of.get(f["trace_id"]),
                              par_of.get(f["trace_id"]), f["latency_total"]) for f in ordered])
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

    sizes = {}
    for a in assigns:
        if not a["novelty"]:
            sizes[a["cell"]] = sizes.get(a["cell"], 0) + 1
    sv = sorted(sizes.values())

    res = {"tag": tag, "frac": frac, "ndec": ndec, "cap_tag": cap_tag,
           "kmax_pat": max(2, min(cluster.K_MAX_PATTERN_ABS,
                                  (ndec or cluster.K_MAX_PATTERN_ABS)
                                  + cluster.K_MAX_PATTERN_HEADROOM)),
           "ontology": "slim", "n": len(tids), "n_B": len(Bt),
           "wall_s": round(time.time() - t0, 1),
           "n_intent_clusters": cinfo.get("n_intent_clusters"),
           "n_pattern_clusters": cinfo.get("n_pattern_clusters"),
           "novelty_rate_all": cinfo.get("novelty_rate"),
           "n_cells": len(sizes),
           "cell_size_min": sv[0] if sv else None,
           "cell_size_max": sv[-1] if sv else None,
           "n_cells_below_kappa": sum(1 for v in sv if v < BL.KAPPA),
           "n_bound_patterns": dinfo.get("n_bound_patterns"),
           "overall": TX.pool_metrics(pool, stage, y),
           "A": TX.pool_metrics(At, stage, y),
           "B": TX.pool_metrics(Bt, stage, y) if Bt else None,
           "topk_A_share": (round(sum(1 for t in topk if src[t] == "A") / float(len(topk)), 4)
                            if topk else None),
           "topk_precision": (round(sum(1 for t in topk if y[t]) / float(len(topk)), 4)
                              if topk else None),
           "topk_tiers": sorted(set(stage[t]["tier"] for t in topk)) if topk else []}
    for lbl, ids in (("A", At), ("B", Bt)):
        if not ids:
            continue
        nov = [t for t in ids if AS[t]["novelty"]]
        byc = {}
        for t in ids:
            if not AS[t]["novelty"]:
                byc.setdefault(AS[t]["cell"], []).append(t)
        res["census_" + lbl] = {
            "n": len(ids), "n_novelty": len(nov),
            "novelty_rate": round(len(nov) / float(len(ids)), 5),
            "n_cells_occupied": len(byc),
            "largest_cell": max((len(v) for v in byc.values()), default=None),
            "tier_hist": dict((str(k), v) for k, v in
                              sorted(TX._tier_hist(ids, stage).items())),
            "credibility_of_largest_cell": (round(BL.credibility(max(len(v) for v in byc.values())), 4)
                                            if byc else None)}
    return res


def main():
    out = {"_note": "SLIM ontology (required_steps DELETED = the real Tier-1-minimal tenant "
                    "ontology) x cap in {8, 5} x pollution in {0%, 5%, 20%}. One variable at a "
                    "time: tierexp.py:113 derived the cap FROM the ontology, so its 'slim' arm "
                    "conflated 'required_steps deleted' with 'cap 5 -> 8'. This isolates the "
                    "cap. Cohorts are byte-identical to mixexp/tierexp (MX.build, SEED=20261109).",
           "arms": []}
    t0 = time.time()
    for frac, ndec, cap_tag in ARMS:
        r = arm(frac, ndec, cap_tag)
        out["arms"].append(r)
        ov, B = r["overall"], r["B"]
        print("[%6.1fs] %-22s n=%-5d nB=%-4d kmax=%d n_pat=%-3s n_cells=%-3d nov=%-7s "
              "topk_prec=%-6s topk_A=%-7s fpr=%-8s f1=%-8s alert=%-7s B_alert=%s"
              % (time.time() - t0, r["tag"], r["n"], r["n_B"], r["kmax_pat"],
                 r["n_pattern_clusters"], r["n_cells"], r["novelty_rate_all"],
                 r["topk_precision"], r["topk_A_share"],
                 (ov or {}).get("fpr_pool"), (ov or {}).get("f1_pool"),
                 (ov or {}).get("alert_rate"), (B or {}).get("alert_rate")), flush=True)
    out["_wall_secs"] = round(time.time() - t0, 1)
    with io.open("platform/slimcap-results.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    print("\nwrote platform/slimcap-results.json  wall=%.1fs" % out["_wall_secs"], flush=True)


if __name__ == "__main__":
    main()
