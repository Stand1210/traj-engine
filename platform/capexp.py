"""capexp -- what does dropping `pattern_count` actually cost on CLEAN traffic?

Motivation
----------
The user challenged the proposed Tier-1 field `pattern_count` ("sounds unreliable, can we
drop it?"). Two facts make the question answerable rather than debatable:

  1. `pattern_count` is NOT WIRED. It exists only in platform/*.md prose. kernel/cluster.py:730
     defaults `n_declared_patterns=None`, and :794 `n_dec = None or K_MAX_PATTERN_ABS` -> cap 8.
     So "dropping it" means "do nothing", and production would run at cap 8.
  2. Every published benchmark number was produced at cap 5: bench/runner.py:213 passes
     len(ont["required_steps"]) and both shipped ontologies declare 3 -> min(8, 3+2) = 5.

platform/tierexp.py measured cap 8 only on POLLUTED arms (5% / 20% foreign traffic). The claim
in LIFECYCLE.md:107 / :228 that "the cost on clean traffic is small" was therefore NEVER
MEASURED -- it was inferred from the 5% arm not shattering. This script closes that gap:
8 clean regimes x {cap from declaration, cap 8}.

Reports, per regime and per arm: cluster counts, novelty rate, cell-size distribution and how
many cells fall under the credibility knee (n < KAPPA=30), baseline level mix, ARI against
ground truth, and the downstream detection / scoring numbers that actually matter.

Run:  python -u platform/capexp.py            (writes platform/capexp-results.json)
"""
import io, json, os, sys, time

sys.path.insert(0, os.getcwd())
from kernel import ingest, features as FEAT, cluster, baseline as BL, binding as BD
from kernel import detect as DET, score, drift, meta
import bench.regime as RG
import bench.runner as RUN
from ontology.base import get_ontology

RIDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
KAPPA = BL.KAPPA
TOPK = 15


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def arm(rid, ndec, tag):
    spec = RG.get(rid)
    d = os.path.join(RUN.ROOT, "data", "bench_v1", rid)
    traces = RUN.load_jsonl(os.path.join(d, "traces.jsonl"))
    gts = RUN.load_jsonl(os.path.join(d, "gt.jsonl"))
    ont = get_ontology(spec["ontology_id"])
    gt = dict((g["trace_id"], g) for g in gts)

    norms = [ingest.normalize(x, ont) for x in traces]
    feats = [FEAT.extract(x, ont) for x in norms]
    FEAT.annotate_sessions(feats, traces)

    cluster.reset_cache()
    assigns, cinfo = cluster.cluster_views(
        feats, threshold=cluster.CONSENSUS_THRESHOLD, seed=spec["seed"],
        n_declared_patterns=ndec)
    AS = dict((a["trace_id"], a) for a in assigns)

    records = [{"cell": a["cell"], "intent": a.get("near_intent", -1), "feats": f}
               for a, f in zip(assigns, feats) if not a["novelty"]]
    art = BL.build(records, ont, "anchor-%s-%s" % (rid, tag))
    binding = BD.bind_patterns(art, ont)
    stage, dinfo = DET.detect_all(feats, assigns, art, ont, binding=binding,
                                 bh_alpha=DET.BH_ALPHA)
    ordered = sorted(feats, key=lambda f: (f["ts_start"], f["trace_id"]))
    cell_of = dict((a["trace_id"], a["cell"]) for a in assigns)
    par_of = dict((a["trace_id"], "i%d" % a.get("near_intent", -1)) for a in assigns)
    stream = [(f["trace_id"], cell_of.get(f["trace_id"]), par_of.get(f["trace_id"]),
               f["latency_total"]) for f in ordered]
    dr = drift.detect_drift(stream)
    recs = score.score_all(feats, assigns, stage, art, ont,
                           cold_start=len(feats) < RG.COLD_START_MIN_TRACES,
                           drift_map=dict((x, True) for x in set(dr.get("suspects") or [])),
                           anchor_version="anchor-%s-%s" % (rid, tag), model_version=tag)
    R = dict((r["trace_id"], r) for r in recs)
    tids = [f["trace_id"] for f in feats]

    # ---- cell geometry ----
    sizes = {}
    for a in assigns:
        if not a["novelty"]:
            sizes[a["cell"]] = sizes.get(a["cell"], 0) + 1
    sv = list(sizes.values())
    n_small = sum(1 for v in sv if v < KAPPA)

    # ---- baseline level mix ----
    lv = {}
    cells_art = art.get("cell") or {}
    _it = cells_art.values() if isinstance(cells_art, dict) else cells_art
    for c in _it:
        k = c.get("level") if isinstance(c, dict) else None
        lv[k] = lv.get(k, 0) + 1

    # ---- clustering quality vs ground truth (pool = non-novelty, as runner does) ----
    pool = [t for t in tids if not AS[t]["novelty"]]
    ari_p = meta.ari([AS[t]["pattern_cluster"] for t in pool],
                     [gt[t]["pattern_id"] for t in pool]) if pool else None
    ari_i = meta.ari([AS[t]["intent_cluster"] for t in pool],
                     [gt[t]["intent_id"] for t in pool]) if pool else None

    # ---- detection ----
    y = dict((t, bool(gt[t]["is_anomaly"])) for t in tids if t in gt)
    al = [t for t in tids if t in y and R[t]["alert"]]
    an = [t for t in tids if t in y and y[t]]
    nm = [t for t in tids if t in y and not y[t]]
    tp = sum(1 for t in al if y[t])
    fp = sum(1 for t in al if not y[t])
    prec = tp / float(tp + fp) if (tp + fp) else None
    rec = tp / float(len(an)) if an else None
    f1 = (2 * prec * rec / (prec + rec)) if (prec and rec and (prec + rec)) else 0.0
    ranked = sorted([t for t in tids if t in y], key=lambda t: -R[t]["a_raw"])[:TOPK]
    tk_prec = (sum(1 for t in ranked if y[t]) / float(len(ranked))) if ranked else None

    return {
        "rid": rid, "arm": tag, "n": len(tids), "n_declared_patterns": ndec,
        "kmax_pat": max(2, min(cluster.K_MAX_PATTERN_ABS,
                               (ndec or cluster.K_MAX_PATTERN_ABS) + cluster.K_MAX_PATTERN_HEADROOM)),
        # REFERENCE FRAME (fixed 2026-11-11, after the run that produced capexp-results.json).
        # gt["pattern_id"] takes `n_patterns_per_intent` DISTINCT VALUES -- verified as exactly 3
        # on all eight regimes against data/bench_v1/*/gt.jsonl and reports/*/metrics.json ->
        # clustering.n_true_patterns. It is a PER-INTENT label, not a global one. The first
        # version of this script reported n_intents * n_patterns_per_intent, which made cap 5
        # look like it was under-splitting when it was in fact OVER-splitting (R1: 5 clusters vs
        # a true 3, not vs a true 6). `ari_pattern_pool` has always compared against the correct
        # per-intent labels, so no measured number in the results file was wrong -- only this one
        # reported field, which nothing consumes (capreport.py / asymreport.py both read
        # n_true_patterns from reports/*/metrics.json instead).
        # The product is also NOT n_true_cells: R4's is 12 while metrics.json says 11.
        "n_true_patterns": spec["n_patterns_per_intent"],
        "n_intent_clusters": cinfo.get("n_intent_clusters"),
        "n_pattern_clusters": cinfo.get("n_pattern_clusters"),
        "n_cells": len(sizes),
        "novelty_rate": cinfo.get("novelty_rate"),
        "instability_rate_measured": cinfo.get("instability_rate_measured"),
        "cell_size_min": min(sv) if sv else None,
        "cell_size_median": _median(sv),
        "cell_size_max": max(sv) if sv else None,
        "n_cells_below_kappa": n_small,
        "baseline_level_mix": lv,
        "ari_pattern_pool": ari_p, "ari_intent_pool": ari_i,
        "alert_rate": round(len(al) / float(len(y)), 5) if y else None,
        "fpr_pool": round(fp / float(len(nm)), 5) if nm else None,
        "recall_pool": round(rec, 5) if rec is not None else None,
        "f1_pool": round(f1, 5),
        "topk%d_precision" % TOPK: round(tk_prec, 5) if tk_prec is not None else None,
        "mean_G": round(sum(R[t]["G"] for t in tids) / float(len(tids)), 5),
        "mean_a_raw": round(sum(R[t]["a_raw"] for t in tids) / float(len(tids)), 5),
    }


def main():
    out = {"_note": "cap from declaration (=5 on both shipped ontologies) vs cap 8 (what "
                    "production gets if pattern_count is never wired). CLEAN regimes only; "
                    "tierexp.py already covers the polluted case.",
           "arms": []}
    t0 = time.time()
    for rid in RIDS:
        for ndec, tag in ((len(get_ontology(RG.get(rid)["ontology_id"]).get("required_steps") or {}),
                           "declared"), (0, "cap8")):
            t = time.time()
            r = arm(rid, ndec, tag)
            r["secs"] = round(time.time() - t, 1)
            out["arms"].append(r)
            print("[%6.1fs] %s %-9s kmax_pat=%d n_pat=%s n_cells=%d nov=%s ari_p=%s f1=%s topk=%s G=%s"
                  % (time.time() - t0, rid, tag, r["kmax_pat"], r["n_pattern_clusters"],
                     r["n_cells"], r["novelty_rate"],
                     ("%.4f" % r["ari_pattern_pool"]) if r["ari_pattern_pool"] is not None else "NA",
                     r["f1_pool"], r["topk%d_precision" % TOPK], r["mean_G"]), flush=True)
    out["_wall_secs"] = round(time.time() - t0, 1)
    with io.open("platform/capexp-results.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    print("\nwrote platform/capexp-results.json  wall=%.1fs" % out["_wall_secs"], flush=True)


if __name__ == "__main__":
    main()
