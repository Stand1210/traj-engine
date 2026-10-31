"""Slice-1 end-to-end runner: bench data -> kernel -> ground truth -> gate table -> report.

    python -m bench.runner --regimes R1,R4,R6

Pipeline (all deterministic, all label-free except the calibration slice):
    ingest.normalize -> features.extract -> cluster.cluster_views -> baseline.build
    -> detect.detect_all -> drift.detect_drift -> score.score_all -> calib (cross-fitted)
    -> meta.* against the generator's ground truth -> gates from contracts/schemas.md 8.

Evaluation discipline
  * Clustering metrics are computed on the traces the kernel actually accepted (non-novelty);
    the novelty rate is gated separately so "refuse to judge everything" cannot win.
  * Detection metrics are point-wise at an explicit decision rule (BH-FDR + hard structural
    rules) plus ranking statistics. point-adjust is banned repository-wide.
  * Calibration is cross-fitted out-of-fold, so ECE cannot be flattered by in-sample fit.
"""
import argparse
import glob
import hashlib
import io
import json
import math
import os
import random
import time

from bench import generate as GEN
from bench import regime as RG
from kernel import baseline as BL
from kernel import binding as BD
from kernel import calib, cluster, detect, drift, features as FEAT, ingest, meta, score
from ontology.base import get_ontology

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PIPELINE_VERSION = "slice5-v0.5.0"
MIN_LABELS_CALIB = 60
K_FOLDS = 3
# A gate that no method can reach is not a gate, it is a bug in the gate table. Clustering
# requirements are therefore capped at this fraction of the measured information ceiling for
# the same view on the same pool. The cap can only relax a requirement, never tighten it.
CEIL_RATIO = 0.90

# ---- code identity ------------------------------------------------------------
# Every score record has to say which code produced it, not just which data. `spec_hash` ties a
# score to its dataset and `PIPELINE_VERSION` is a hand-maintained string that can lag behind the
# code it names; neither says anything about the kernel. `code_hash` closes that: it is recorded
# in metrics.json and reconciled by `bench.scorecard.reports_provenance()`, so a kernel edit made
# after the last runner pass makes the shipped scorecard fail instead of quietly describing
# behaviour the current code no longer has.
#
# The closure is *scoped*, not read off sys.modules: reading sys.modules would make the value
# depend on who is asking (`bench.scorecard` imports this module, so its own file would land in
# the set and the two hashes would never agree). Every module under kernel/ and ontology/ is
# imported by this runner, so hashing the whole directories is both complete and caller-
# independent. CODE_FILES is the one list that needs maintaining: add a bench/ module here if the
# runner starts importing one.
# bench/__init__.py is in the list because `from bench import generate` executes it; kernel/ and
# ontology/ pick up their own __init__.py through the directory glob.
CODE_DIRS = ["kernel", "ontology"]
CODE_FILES = ["bench/__init__.py", "bench/runner.py", "bench/generate.py", "bench/regime.py"]


def code_files():
    """Absolute paths of every .py whose contents define what a score means."""
    root = os.path.abspath(ROOT)
    out = [os.path.join(root, p.replace("/", os.sep)) for p in CODE_FILES]
    for d in CODE_DIRS:
        dp = os.path.join(root, d)
        if os.path.isdir(dp):
            out += [os.path.join(dp, f) for f in sorted(os.listdir(dp)) if f.endswith(".py")]
    return sorted(p for p in out if os.path.exists(p))


def code_hash():
    """sha256 over (relative path, content sha256) of `code_files()`, truncated to 16 hex.

    Paths are hashed alongside contents so a rename changes the identity even when the bytes do
    not. Caller-independent by construction -- see the comment above CODE_DIRS.
    """
    root = os.path.abspath(ROOT)
    h = hashlib.sha256()
    for p in code_files():
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        h.update(rel.encode("utf-8") + b"\0")
        h.update(hashlib.sha256(io.open(p, "rb").read()).digest() + b"\0")
    return h.hexdigest()[:16]


def load_jsonl(path):
    out = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def scan_hardcoded_actions():
    """Executable form of 'the kernel must not hardcode business action names'."""
    names = set()
    for oid in get_ontology_ids():
        o = get_ontology(oid)
        names.update(o["actions"])
        names.update(o["forbidden_actions"])
        names.update(o.get("optional_steps") or [])
        for v in o["required_steps"].values():
            names.update(v)
    hits = []
    for path in sorted(glob.glob(os.path.join(ROOT, "kernel", "*.py"))):
        src = io.open(path, encoding="utf-8").read()
        for a in sorted(names):
            if len(a) < 4:
                continue
            if ('"%s"' % a) in src or ("'%s'" % a) in src:
                hits.append("%s:%s" % (os.path.basename(path), a))
    return hits


def get_ontology_ids():
    from ontology.base import ONTOLOGY_IDS
    return ONTOLOGY_IDS


def _fmt(x, nd=4):
    return "n/a" if x is None else ("%%.%df" % nd) % x


def _calibrate(labeled, seed=0):
    """Cross-fitted calibration: fit on K-1 folds, predict the held-out fold."""
    n = len(labeled)
    if n < MIN_LABELS_CALIB:
        return None
    xs_all = [a for a, _ in labeled]
    ys_all = [int(y) for _, y in labeled]
    use_iso = n >= 500
    rng = random.Random(seed)
    idx = list(range(n))
    rng.shuffle(idx)
    folds = [idx[i::K_FOLDS] for i in range(K_FOLDS)]
    oof = [0.0] * n
    for f in range(K_FOLDS):
        te = folds[f]
        teset = set(te)
        tr = [i for i in idx if i not in teset]
        xs = [xs_all[i] for i in tr]
        ys = [ys_all[i] for i in tr]
        if len(set(ys)) < 2:
            base = sum(ys) / float(len(ys)) if ys else 0.5
            for i in te:
                oof[i] = base
            continue
        if use_iso:
            m = calib.IsotonicCalibrator().fit(xs, ys)
            pr = m.predict([xs_all[i] for i in te])
        else:
            ab = calib.platt(xs, ys)
            pr = calib.platt_predict(ab, [xs_all[i] for i in te])
        for j, i in enumerate(te):
            oof[i] = pr[j]
    if use_iso:
        full = calib.IsotonicCalibrator().fit(xs_all, ys_all)
        inplace = full.predict(xs_all)
        kind = "isotonic"
    else:
        ab = calib.platt(xs_all, ys_all)
        full = ab
        inplace = calib.platt_predict(ab, xs_all)
        kind = "platt"
    return {"kind": kind, "n_labels": n, "oof": oof, "inplace": inplace,
            "ece_oof": calib.ece(oof, ys_all, bins=10),
            "ece_raw": calib.ece(xs_all, ys_all, bins=10),
            "auc_cal": meta.roc_auc(oof, ys_all),
            "reliability": calib.reliability(oof, ys_all, bins=10),
            "model": full}


def run_regime(rid, data_root=None, out_root=None, threshold=None, limit=None,
               force_gen=False, bh_alpha=None):
    spec = RG.get(rid)
    data_root = data_root or os.path.join(ROOT, "data", "bench_v1")
    out_root = out_root or os.path.join(ROOT, "reports")
    d = os.path.join(data_root, rid)
    if force_gen or not os.path.exists(os.path.join(d, "traces.jsonl")):
        GEN.build(rid, data_root)
    t_all = time.time()
    traces = load_jsonl(os.path.join(d, "traces.jsonl"))
    gts = load_jsonl(os.path.join(d, "gt.jsonl"))
    dmeta = json.load(io.open(os.path.join(d, "meta.json"), encoding="utf-8"))
    if limit:
        traces = traces[:limit]
        gts = gts[:limit]
    ont = get_ontology(spec["ontology_id"])
    gt = dict((g["trace_id"], g) for g in gts)
    tim = {}

    t = time.time()
    norms = [ingest.normalize(x, ont) for x in traces]
    feats = [FEAT.extract(x, ont) for x in norms]
    # Two appendix-A.4 features are cross-record by definition: session length, and the
    # reformulation signal, which needs the *next* turn of the same session. Skipping
    # this call leaves both None on every trace, which coverage.audit() then reports
    # as constant features.
    FEAT.annotate_sessions(feats, traces)
    tim["ingest_features"] = time.time() - t

    t = time.time()
    cluster.reset_cache()
    assigns, cinfo = cluster.cluster_views(
        feats, threshold=(cluster.CONSENSUS_THRESHOLD if threshold is None else threshold),
        seed=spec["seed"],
        n_declared_patterns=len(ont.get("required_steps") or {}))
    tim["cluster"] = time.time() - t

    n_assigned = sum(1 for a in assigns if not a["novelty"])
    # Cold start is a statement about how much history exists, so it is measured on the
    # ingested volume. Measuring it on the *assignable* volume let the novelty buffer
    # masquerade as missing history: on the sparse regime 45% of traces were unassignable,
    # 1200 ingested traces dropped to 661 assigned, the run declared cold start, every alert
    # was suppressed and F1 collapsed to 0.000 on a regime that has 1200 traces of history.
    cold_start = len(feats) < RG.COLD_START_MIN_TRACES
    anchor_version = "anchor-%s-%s" % (rid, dmeta["spec_hash"])

    t = time.time()
    records = [{"cell": a["cell"], "intent": a.get("near_intent", -1), "feats": f}
               for a, f in zip(assigns, feats) if not a["novelty"]]
    art = BL.build(records, ont, anchor_version)
    tim["baseline"] = time.time() - t

    binding = BD.bind_patterns(art, ont)
    bind_detail = BD.binding_detail(art, ont)

    t = time.time()
    stage, dinfo = detect.detect_all(feats, assigns, art, ont, binding=binding,
                                     bh_alpha=(bh_alpha or detect.BH_ALPHA))
    tim["detect"] = time.time() - t

    ordered = sorted(feats, key=lambda f: (f["ts_start"], f["trace_id"]))
    cell_of = dict((a["trace_id"], a["cell"]) for a in assigns)
    # Parent level of the drift ladder. near_intent exists for every trace including the
    # novelty buffer, so drift monitoring does not silently lose the unassignable ones.
    par_of = dict((a["trace_id"], "i%d" % a.get("near_intent", -1)) for a in assigns)
    stream = [(f["trace_id"], cell_of.get(f["trace_id"]), par_of.get(f["trace_id"]),
               f["latency_total"]) for f in ordered]
    dr = drift.detect_drift(stream)
    drift_ids = set(dr.get("suspects") or [])
    if cold_start:
        for st in stage.values():
            st["alert"] = False
            st["alert_stat"] = False
            st["alert_rule"] = False
        dinfo["n_alert"] = 0
        dinfo["n_alert_stat"] = 0
        dinfo["n_alert_rule"] = 0
        dr = {"drift": False, "reason": "cold_start_suppressed", "n": dr.get("n", 0),
              "suspects": []}
        drift_ids = set()

    t = time.time()
    recs = score.score_all(feats, assigns, stage, art, ont, cold_start=cold_start,
                           drift_map=dict((x, True) for x in drift_ids),
                           anchor_version=anchor_version, model_version=PIPELINE_VERSION)
    tim["score"] = time.time() - t

    labeled = [(stage[g["trace_id"]]["a_raw"], bool(g["is_anomaly"]))
               for g in gts if g.get("human_label") is not None
               and g["trace_id"] in stage]
    labeled_h = [(stage[g["trace_id"]]["a_raw"], bool(g["human_label"]))
                 for g in gts if g.get("human_label") is not None
                 and g["trace_id"] in stage]
    cal = _calibrate(labeled_h, seed=spec["seed"]) if labeled_h else None
    if cal is not None:
        m = cal["model"]
        for r in recs:
            a = stage[r["trace_id"]]["a_raw"]
            r["a_cal"] = (m.predict([a])[0] if cal["kind"] == "isotonic"
                          else calib.platt_predict(m, [a])[0])
    else:
        for r in recs:
            r["a_cal"] = None

    res = evaluate(rid, spec, feats, assigns, recs, stage, art, cinfo, dinfo, dr, gt,
                   cal, cold_start, tim, time.time() - t_all, dmeta,
                   binding=binding, bind_detail=bind_detail)
    write_report(rid, res, out_root, recs)
    return res


def oracle_ceilings(feats, gt, pool, tids):
    """Information ceilings of the two clustering views - what an oracle could score.

    A clustering gate is only interpretable next to the best score reachable from the same
    input, and on the heavy-overlap regime the two are close enough that the distinction is
    the difference between a hard gate and an impossible one. Both oracles are plug-in Bayes
    rules rather than learned models, and both read ground truth, so neither is attainable in
    deployment.

    One qualification on the word "ceiling": these are SUPERVISED rules, so they do not bound
    what an unsupervised view can reach in general, and an earlier revision of this docstring
    claimed they did. That claim was measured false on the bench-gen-v3.0.0 geometry, where the
    true-mean intent oracle beat unsupervised k-means by 4.7x. It does hold on the shipped
    v3.1.0 geometry, where whitening closes the gap (ari_wht ~= ari_iso), but that is a property
    of how the geometry was calibrated, not a theorem. The direction of the error is safe either
    way: CEIL_RATIO only ever relaxes a gate, so an oracle that turns out to be too strong
    loosens the bar rather than making it unmeetable - and an unmeetable bar is the exact
    failure this mechanism exists to prevent (see the R3 note in contracts/schemas.md section 8).

      intent   MAP rule of the generative model: TRUE per-class means, TRUE priors and the
               pooled within-class variance of the embedding, argmax_c [log w_c - d2/(2 var)].
      pattern  The best measurable function of the action sequence alone: collapse the
               sequence to its salient skeleton and label each distinct skeleton with the
               majority true pattern_id it was generated from.

    Each is reported twice. On the pool, which is like-for-like with the gated ARI, and over
    every ingested trace, which prices the abstention: refusing to judge the ambiguous tail
    buys ARI at the cost of coverage, and the gap between the two numbers is exactly that
    trade.
    """
    emb = dict((f["trace_id"], f["embedding"]) for f in feats)
    out = {}
    for tag, ids in (("pool", pool), ("all", tids)):
        if not ids:
            out["ari_intent_ceiling_" + tag] = None
            out["ari_pattern_ceiling_" + tag] = None
            continue
        dim = len(emb[ids[0]]) if emb[ids[0]] else 0
        classes = sorted(set(gt[t]["intent_id"] for t in ids))
        mem = dict((c, [t for t in ids if gt[t]["intent_id"] == c]) for c in classes)
        means = dict((c, [sum(emb[t][d] for t in ts) / float(len(ts)) for d in range(dim)])
                     for c, ts in mem.items() if ts and dim)
        ss, dof = 0.0, 0
        for c, ts in mem.items():
            if c not in means:
                continue
            for t in ts:
                for d in range(dim):
                    ss += (emb[t][d] - means[c][d]) ** 2
                    dof += 1
        var = (ss / dof) if dof else 1e-12
        ntot = float(len(ids))
        pred_i = []
        for t in ids:
            best, bc = None, None
            for c, mu in means.items():
                d2 = sum((emb[t][d] - mu[d]) ** 2 for d in range(dim))
                lp = math.log(len(mem[c]) / ntot) - d2 / (2.0 * var)
                if best is None or lp > best:
                    best, bc = lp, c
            pred_i.append(bc)
        skel = dict((f["trace_id"], tuple(cluster.collapse(f["action_seq"]))) for f in feats)
        by_seq = {}
        for t in ids:
            by_seq.setdefault(skel[t], []).append(t)
        maj = {}
        for k, ts in by_seq.items():
            cnt = {}
            for t in ts:
                cnt[gt[t]["pattern_id"]] = cnt.get(gt[t]["pattern_id"], 0) + 1
            maj[k] = sorted(cnt.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0]
        pred_p = [maj[skel[t]] for t in ids]
        out["ari_intent_ceiling_" + tag] = meta.ari(pred_i, [gt[t]["intent_id"] for t in ids])
        out["ari_pattern_ceiling_" + tag] = meta.ari(pred_p, [gt[t]["pattern_id"] for t in ids])
    out["ari_intent_ceiling"] = out["ari_intent_ceiling_pool"]
    out["ari_pattern_ceiling"] = out["ari_pattern_ceiling_pool"]
    return out


def _capped(req, ceiling):
    return req if ceiling is None else min(req, CEIL_RATIO * ceiling)


def evaluate(rid, spec, feats, assigns, recs, stage, art, cinfo, dinfo, dr, gt, cal,
             cold_start, tim, wall, dmeta, binding=None, bind_detail=None):
    amap = dict((a["trace_id"], a) for a in assigns)
    rmap = dict((r["trace_id"], r) for r in recs)
    tids = [f["trace_id"] for f in feats]
    pool = [t for t in tids if not amap[t]["novelty"]]
    y_pool = [bool(gt[t]["is_anomaly"]) for t in pool]
    y_all = [bool(gt[t]["is_anomaly"]) for t in tids]

    pred_pool = [bool(stage[t]["alert"]) for t in pool]
    pred_all = [bool(stage[t]["alert"]) for t in tids]
    dp = meta.prf(y_pool, pred_pool)
    da = meta.prf(y_all, pred_all)
    a_pool = [stage[t]["a_raw"] for t in pool]
    auc_raw = meta.roc_auc(a_pool, y_pool)
    prauc = meta.pr_auc(a_pool, y_pool)
    p50 = meta.precision_at_k(a_pool, y_pool, 50)
    r50 = meta.recall_at_k(a_pool, y_pool, 50)
    days = max(1e-9, spec.get("hours", 72.0) / 24.0)
    budget_k = max(1, int(round(RG.ALERT_BUDGET_PER_DAY * days)))
    p_budget = meta.precision_at_k(a_pool, y_pool, budget_k)
    tiers = [int(stage[t].get("tier", 0)) for t in pool]
    tier_mix = dict((k, tiers.count(k)) for k in (0, 1, 2))
    # Once the deterministic channel finds more than 50 breaches, Precision@50 measures that
    # channel and nothing else - which is what a reviewer wants at the head of the queue, but
    # it stops telling us anything about how well the *statistical* channel orders the rest.
    # Both are reported so neither can hide behind the other.
    sub_a = [a for a, k in zip(a_pool, tiers) if k < 2]
    sub_y = [y for y, k in zip(y_pool, tiers) if k < 2]
    p50_sub = meta.precision_at_k(sub_a, sub_y, 50) if len(sub_a) >= 50 else None
    # Precision on the sub-pool is only readable next to its base rate: stripping the
    # deterministic findings removes most of the anomalies along with them, so the surviving
    # population is a much harder one and a raw 0.40 there can be a 10x lift.
    sub_base = (sum(1 for y in sub_y if y) / float(len(sub_y))) if sub_y else 0.0
    p50_sub_lift = (p50_sub / sub_base) if (p50_sub is not None and sub_base > 0) else None

    pred_ic = [amap[t]["intent_cluster"] for t in pool]
    pred_pc = [amap[t]["pattern_cluster"] for t in pool]
    pred_cc = [amap[t]["cell"] for t in pool]
    truth_i = [gt[t]["intent_id"] for t in pool]
    truth_p = [gt[t]["pattern_id"] for t in pool]
    truth_c = [gt[t]["cell_id"] for t in pool]

    # Abstention is a purchase, not a virtue: the gated ARI is measured on the pool, so a
    # clustering that dumps its hard cases into the novelty buffer scores better by scoring
    # less. Both sides of that purchase are reported here so neither can hide.
    #   `*_all`  re-scores every ingested trace at its *nearest* cluster, i.e. the same
    #            clustering with abstention switched off.
    #   `novelty_purity_*` prices what the buffer actually contains. 1.0 means we refused to
    #            judge traffic we could have judged perfectly; the class prior means the tail
    #            really is ambiguous.
    # Measured on R1 (gen bench-gen-v2.2.0): buffer n=433 (10.8% of traffic), ari_pattern
    # 0.8368 with abstention off vs 0.9856 on the pool, so abstention buys +0.149 ARI. The
    # buffer is not ambiguous: novelty_purity_pattern = 0.9908 and 380/433 = 0.8776 of it is
    # one single true pattern. Cause is over-splitting, not noise - the pattern view returns
    # k=6 against 3 true patterns, and one 383-trace fragment (380 of them one true pattern,
    # purity 0.9922) gets a mean member consensus of -0.44, so the (a-b)/max(a,b) margin reads
    # a spurious split of a well identified group as "belongs to no class I can name". The
    # buffer's anomaly rate is 0.0901 against the pool's 0.0732, i.e. abstaining drops
    # monitoring on the higher-risk slice. Left unfixed on purpose: the clustering model order
    # is slice2 work and needs its own measurement pass, and the R1 gate set only bounds
    # novelty_rate to [0, 0.25], which 0.108 satisfies.
    novel = [t for t in tids if amap[t]["novelty"]]
    pred_ic_all = [amap[t]["intent_cluster"] if not amap[t]["novelty"]
                   else amap[t]["near_intent"] for t in tids]
    pred_pc_all = [amap[t]["pattern_cluster"] if not amap[t]["novelty"]
                   else amap[t]["near_pattern"] for t in tids]
    pred_cc_all = [amap[t]["cell"] if not amap[t]["novelty"]
                   else ("i%dxp%d" % (amap[t]["near_intent"], amap[t]["near_pattern"]))
                   for t in tids]
    truth_i_all = [gt[t]["intent_id"] for t in tids]
    truth_p_all = [gt[t]["pattern_id"] for t in tids]
    truth_c_all = [gt[t]["cell_id"] for t in tids]

    def _maj_share(preds, truths):
        if not preds:
            return None
        by = {}
        for p_, t_ in zip(preds, truths):
            by.setdefault(p_, {}).setdefault(t_, 0)
            by[p_][t_] += 1
        hit = sum(max(c.values()) for c in by.values())
        return hit / float(len(preds))

    cl = {
        "ari_intent": meta.ari(pred_ic, truth_i),
        "ari_pattern": meta.ari(pred_pc, truth_p),
        "ari_cell": meta.ari(pred_cc, truth_c),
        "ari_intent_all": meta.ari(pred_ic_all, truth_i_all),
        "ari_pattern_all": meta.ari(pred_pc_all, truth_p_all),
        "ari_cell_all": meta.ari(pred_cc_all, truth_c_all),
        "n_novelty": len(novel),
        "novelty_purity_intent": _maj_share([amap[t]["near_intent"] for t in novel],
                                            [gt[t]["intent_id"] for t in novel]),
        "novelty_purity_pattern": _maj_share([amap[t]["near_pattern"] for t in novel],
                                             [gt[t]["pattern_id"] for t in novel]),
        "novelty_anomaly_rate": (sum(1 for t in novel if gt[t]["is_anomaly"]) / float(len(novel))
                                 if novel else None),
        "pool_anomaly_rate": (sum(1 for y in y_pool if y) / float(len(y_pool))) if y_pool else None,
        "nmi_intent": meta.nmi(pred_ic, truth_i),
        "nmi_pattern": meta.nmi(pred_pc, truth_p),
        "purity_intent": meta.purity(pred_ic, truth_i),
        "purity_pattern": meta.purity(pred_pc, truth_p),
        "n_intent_clusters": cinfo["n_intent_clusters"],
        "n_pattern_clusters": cinfo["n_pattern_clusters"],
        "n_true_intents": len(set(truth_i)),
        "n_true_patterns": len(set(truth_p)),
        "n_cells": art["n_cells"],
        "n_true_cells": len(set(truth_c)),
        "novelty_rate": cinfo["novelty_rate"],
        "coverage": len(pool) / float(len(tids)) if tids else 0.0,
    }
    cl.update(oracle_ceilings(feats, gt, pool, tids))

    resid = 0.0
    for r in recs:
        resid = max(resid, abs(sum(r["contrib"].values()) - (r["S"] - 100.0 * r["G"])))
    s_pool = [rmap[t]["S"] for t in pool]
    score_auc = meta.roc_auc([-v for v in s_pool], y_pool)
    dims = ["O", "P", "L", "C", "R"]
    per_dim = {}
    for dd in dims:
        xs = [rmap[t]["dims"][dd] for t in pool]
        ys = [gt[t]["dim_dev"].get(dd, 1.0) for t in pool]
        per_dim[dd] = {"spearman": meta.spearman(xs, ys),
                       "pearson": meta.pearson(xs, ys),
                       "mean_normal": (sum(x for x, y in zip(xs, y_pool) if not y)
                                       / max(1, sum(1 for y in y_pool if not y))),
                       "mean_anomaly": (sum(x for x, y in zip(xs, y_pool) if y)
                                        / max(1, sum(1 for y in y_pool if y)))}
    oracle = [sum(gt[t]["dim_dev"].values()) / 5.0 for t in pool]
    sc = {
        "zero_residual_max": resid,
        "score_auc": score_auc,
        "spearman_vs_oracle": meta.spearman(s_pool, oracle),
        "kendall_vs_oracle": meta.kendall_tau_b(s_pool, oracle),
        "per_dim": per_dim,
        "mean_S_normal": (sum(s for s, y in zip(s_pool, y_pool) if not y)
                          / max(1, sum(1 for y in y_pool if not y))),
        "mean_S_anomaly": (sum(s for s, y in zip(s_pool, y_pool) if y)
                           / max(1, sum(1 for y in y_pool if y))),
        "grade_abs": _count(r["grade_abs"] for r in recs),
        "grade_rel": _count(r["grade_rel"] for r in recs),
        "gate_hits": _count(g for r in recs for g in r["gates"]),
        "mean_conf": sum(r["conf"] for r in recs) / float(len(recs)) if recs else 0.0,
    }
    sc["grade_separation"] = sc["mean_S_normal"] - sc["mean_S_anomaly"]

    calr = {"available": cal is not None}
    if cal:
        calr.update({"kind": cal["kind"], "n_labels": cal["n_labels"],
                     "ece_oof": cal["ece_oof"], "ece_raw": cal["ece_raw"],
                     "auc_cal": cal["auc_cal"], "reliability": cal["reliability"]})

    per_type = {}
    for t in pool:
        g = gt[t]
        key = g["anomaly_types"][0] if g["anomaly_types"] else "normal"
        e = per_type.setdefault(key, {"n": 0, "alert": 0, "stat": 0, "rule": 0})
        e["n"] += 1
        if stage[t]["alert"]:
            e["alert"] += 1
        if stage[t]["alert_stat"]:
            e["stat"] += 1
        if stage[t]["alert_rule"]:
            e["rule"] += 1
    for k, e in per_type.items():
        e["recall"] = e["alert"] / float(e["n"]) if e["n"] else None

    # Span localisation is only defined where the generator named a responsible span. Scoring
    # every trace instead - the previous behaviour - charged a false positive to each healthy
    # trace merely for reporting its worst span, which swamped the statistic (2622 fp against
    # 85 tp on the heavy-overlap regime) and made the diagnostic unreadable.
    loc = {"tp": 0, "fp": 0, "fn": 0, "n_with_truth": 0}
    for t in pool:
        rs = set(gt[t].get("responsible_span_ids") or [])
        if not rs:
            continue
        loc["n_with_truth"] += 1
        ev = stage[t].get("span_evidence") or {}
        pred = set([ev["span_id"]]) if ev.get("span_id") else set()
        loc["tp"] += len(pred & rs)
        loc["fp"] += len(pred - rs)
        loc["fn"] += len(rs - pred)
    loc["precision"] = loc["tp"] / float(loc["tp"] + loc["fp"]) if (loc["tp"] + loc["fp"]) else None
    loc["recall"] = loc["tp"] / float(loc["tp"] + loc["fn"]) if (loc["tp"] + loc["fn"]) else None

    det = {
        "pool": dp, "all": da, "auc_a_raw": auc_raw, "pr_auc": prauc,
        "per_anomaly_type": dict(sorted(per_type.items())), "span_localization": loc,
        "binding": binding or {}, "binding_detail": bind_detail or {},
        "precision_at_50": p50, "recall_at_50": r50,
        "budget_k": budget_k, "precision_at_budget": p_budget,
        "tier_mix": tier_mix, "precision_at_50_below_rule": p50_sub,
        "below_rule_base_rate": sub_base, "below_rule_lift": p50_sub_lift,
        "n_alert": dinfo["n_alert"], "n_alert_stat": dinfo["n_alert_stat"],
        "n_alert_rule": dinfo["n_alert_rule"], "fallback_share": dinfo["fallback_share"],
        "baseline_fallback_ratio": art["fallback_ratio"],
        "cold_start": cold_start, "bh_alpha": dinfo["bh_alpha"],
        "alerts_per_day": dinfo["n_alert"] / days, "days": days,
        "rule_findings_per_day": dinfo["n_alert_rule"] / days,
    }
    drift_r = {"drift_spec": spec.get("drift"), "detected": bool(dr.get("drift")),
               "index": dr.get("index"), "reason": dr.get("reason"),
               "n_suspects": len(dr.get("suspects") or []),
               "statistic": dr.get("statistic"), "lambda": dr.get("lambda"),
               "lambda_source": dr.get("lambda_source"), "min_seg_len": dr.get("min_seg_len"),
               "alpha": dr.get("alpha"), "window": dr.get("window"),
               "z_mean_ref": dr.get("z_mean_ref"),
               "z_mean_tail": dr.get("z_mean_tail"), "z_levels": dr.get("z_levels"),
               "z_median_tail": dr.get("z_median_tail"),
               "sign_mean_tail": dr.get("sign_mean_tail"),
               "share_above_ref_median": dr.get("share_above_ref_median"),
               "window_len": dr.get("window_len")}
    if spec.get("drift"):
        stream_ids = [f["trace_id"] for f in
                      sorted(feats, key=lambda f: (f["ts_start"], f["trace_id"]))]
        true_idx = None
        for i, t in enumerate(stream_ids):
            if gt[t].get("drift_segment") == 1:
                true_idx = i
                break
        drift_r["true_index"] = true_idx
        if dr.get("index") is not None and true_idx is not None:
            drift_r["lag"] = dr["index"] - true_idx
            drift_r["lag_frac"] = (dr["index"] - true_idx) / float(len(stream_ids))

    defect_hit = {"ts_repaired": [0, 0], "usage_estimated": [0, 0], "orphan_rebuilt": [0, 0]}
    conf_down = [0, 0]
    for f in feats:
        t = f["trace_id"]
        gd = gt[t].get("defect_flags") or {}
        fd = f.get("flags") or {}
        for k in defect_hit:
            if gd.get(k):
                defect_hit[k][1] += 1
                if fd.get(k):
                    defect_hit[k][0] += 1
        if any(fd.values()):
            conf_down[1] += 1
            if rmap[t]["conf"] < 1.0 - 1e-9:
                conf_down[0] += 1
    dq = {"defect_recall": dict((k, (v[0] / float(v[1])) if v[1] else None)
                                for k, v in defect_hit.items()),
          "defect_counts_true": dict((k, v[1]) for k, v in defect_hit.items()),
          "conf_downgrade_rate": (conf_down[0] / float(conf_down[1])) if conf_down[1] else None,
          "n_flagged": conf_down[1]}

    gates = gate_check(spec, cl, det, sc, calr, drift_r, dq, cold_start, recs)
    return {"regime_id": rid, "title": spec["title"], "pipeline_version": PIPELINE_VERSION,
            "spec_hash": dmeta.get("spec_hash"), "code_hash": code_hash(),
            "n": len(tids), "n_pool": len(pool),
            "cold_start": cold_start, "wall_s": wall, "timings": tim,
            "cluster_info": cinfo, "detect_info": dinfo,
            "clustering": cl, "detection": det, "scoring": sc, "calibration": calr,
            "drift": drift_r, "data_quality": dq, "gates": gates,
            "all_pass": all(g["ok"] for g in gates.values()),
            "gen_meta": {k: dmeta.get(k) for k in ("n_traces", "n_spans", "n_cells_true",
                                                   "anomaly_rate_true", "anomaly_type_counts",
                                                   "latency", "tokens", "cost")}}


def _count(it):
    c = {}
    for x in it:
        c[x] = c.get(x, 0) + 1
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0]))))


def gate_check(spec, cl, det, sc, cal, dr, dq, cold_start, recs):
    g = spec.get("gates") or {}
    out = {}

    def add(name, ok, want, got):
        out[name] = {"ok": bool(ok), "want": want, "got": got}

    if g.get("cold_start"):
        add("cold_start_flag", cold_start is True, "true", cold_start)
        add("zero_alerts", det["n_alert"] == g.get("max_alerts", 0),
            "<=%d" % g.get("max_alerts", 0), det["n_alert"])
    else:
        req_i = _capped(g["ari_intent"], cl.get("ari_intent_ceiling"))
        req_p = _capped(g["ari_pattern"], cl.get("ari_pattern_ceiling"))
        add("ari_intent", cl["ari_intent"] >= req_i,
            ">=%.3f (table %.2f, oracle ceiling %s)"
            % (req_i, g["ari_intent"], _fmt(cl.get("ari_intent_ceiling"))),
            _fmt(cl["ari_intent"]))
        add("ari_pattern", cl["ari_pattern"] >= req_p,
            ">=%.3f (table %.2f, oracle ceiling %s)"
            % (req_p, g["ari_pattern"], _fmt(cl.get("ari_pattern_ceiling"))),
            _fmt(cl["ari_pattern"]))
        add("f1", det["pool"]["f1"] >= g["f1"], ">=%.2f" % g["f1"],
            _fmt(det["pool"]["f1"]))
        add("precision_at_50", det["precision_at_50"] >= g["precision_at_50"],
            ">=%.2f" % g["precision_at_50"], _fmt(det["precision_at_50"]))
        add("operator_stream_precision",
            det["precision_at_budget"] >= RG.OPS_STREAM_PRECISION_MIN,
            ">=%.2f @k=%d/day=%d" % (RG.OPS_STREAM_PRECISION_MIN, det["budget_k"],
                                     RG.ALERT_BUDGET_PER_DAY),
            _fmt(det["precision_at_budget"]))
        add("fpr", det["pool"]["fpr"] <= g["fpr"], "<=%.2f" % g["fpr"],
            _fmt(det["pool"]["fpr"]))
        if cal.get("available"):
            add("ece", cal["ece_oof"] <= g["ece"], "<=%.2f" % g["ece"], _fmt(cal["ece_oof"]))
        else:
            add("ece", True, "skipped(no labels)", "skipped")
        nmax = g.get("novelty_max", 0.25)
        add("novelty_rate", cl["novelty_rate"] <= nmax and
            cl["novelty_rate"] >= g.get("novelty_min", 0.0),
            "[%.2f,%.2f]" % (g.get("novelty_min", 0.0), nmax), _fmt(cl["novelty_rate"], 3))
    if "fallback_min" in g:
        add("pooling_fallback_share", det["baseline_fallback_ratio"] >= g["fallback_min"],
            ">=%.2f" % g["fallback_min"], _fmt(det["baseline_fallback_ratio"], 3))
    if "conf_downgrade" in g:
        add("conf_downgrade_rate", (dq["conf_downgrade_rate"] or 0.0) >= g["conf_downgrade"],
            ">=%.2f" % g["conf_downgrade"], _fmt(dq["conf_downgrade_rate"], 3))
    if g.get("drift_detected"):
        # Two-sided. A one-sided "not later than" bound rewards a detector that alarms on the
        # first observation it ever sees, which is exactly the failure mode the calibrated
        # threshold is there to prevent.
        lo, hi = g.get("drift_lag_frac_min", -0.05), g.get("drift_lag_frac_max", 0.10)
        lf = dr.get("lag_frac")
        ok = bool(dr.get("detected")) and lf is not None and lo <= lf <= hi
        add("drift", ok, "detected & lag_frac in [%.2f,%.2f]" % (lo, hi),
            "detected=%s lag_frac=%s" % (dr.get("detected"), _fmt(lf, 4)))
    if g.get("no_drift"):
        add("no_false_drift", not dr.get("detected"), "detected=false",
            "detected=%s stat=%s lambda=%s" % (dr.get("detected"), _fmt(dr.get("statistic"), 2),
                                               _fmt(dr.get("lambda"), 2)))
    if g.get("no_hardcoded_actions"):
        hits = scan_hardcoded_actions()
        add("no_hardcoded_actions", not hits, "[]", hits or "[]")
    add("zero_residual", sc["zero_residual_max"] <= g.get("zero_residual", 1e-6),
        "<=%.0e" % g.get("zero_residual", 1e-6), "%.3e" % sc["zero_residual_max"])
    return out


def write_report(rid, res, out_root, recs):
    d = os.path.join(out_root, rid)
    if not os.path.isdir(d):
        os.makedirs(d)
    slim = []
    for r in recs:
        slim.append({"trace_id": r["trace_id"], "cell": r["cell"], "S": round(r["S"], 4),
                     "G": round(r["G"], 6), "grade_abs": r["grade_abs"],
                     "grade_rel": r["grade_rel"],
                     "dims": dict((k, round(v, 5)) for k, v in r["dims"].items()),
                     "gates": r["gates"],
                     "contrib": dict((k, round(v, 6)) for k, v in r["contrib"].items()),
                     "conf": round(r["conf"], 4), "alert": r["alert"],
                     "a_raw": round(r["a_raw"], 5), "a_cal": r["a_cal"],
                     "tier": r["tier"], "graded": round(r["graded"], 5),
                     "alert_rule": r["alert_rule"], "alert_stat": r["alert_stat"],
                     "novelty": r["novelty"], "cold_start": r["cold_start"],
                     "anchor_version": r["anchor_version"],
                     "model_version": r["model_version"],
                     "evidence": r["evidence"][:3]})
    with io.open(os.path.join(d, "scores.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for s in slim:
            f.write(json.dumps(s, ensure_ascii=False, sort_keys=True) + "\n")
    with io.open(os.path.join(d, "metrics.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        f.write("\n")
    with io.open(os.path.join(d, "report.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(render_md(res))
    return d


def render_md(res):
    cl, det, sc, cal, dr, dq = (res["clustering"], res["detection"], res["scoring"],
                                res["calibration"], res["drift"], res["data_quality"])
    L = []
    L.append("# 基准跑分报告 %s - %s" % (res["regime_id"], res["title"]))
    L.append("")
    L.append("- 流水线版本 `%s`｜数据集 `%s`｜代码 `%s`｜n=%d（可归簇 %d，覆盖率 %.3f）｜冷启动 %s｜墙钟 %.1fs"
             % (res["pipeline_version"], res["spec_hash"], res.get("code_hash"),
                res["n"], res["n_pool"], cl["coverage"], res["cold_start"], res["wall_s"]))
    L.append("- 生成器真值：真实格子数 %d｜异常率 %.4f｜异常类型 %s"
             % (res["gen_meta"]["n_cells_true"], res["gen_meta"]["anomaly_rate_true"],
                json.dumps(res["gen_meta"]["anomaly_type_counts"], sort_keys=True)))
    L.append("- 端到端时延分布 p50/p90/p99 = %s / %s / %s"
             % (_fmt(res["gen_meta"]["latency"].get("p50"), 2),
                _fmt(res["gen_meta"]["latency"].get("p90"), 2),
                _fmt(res["gen_meta"]["latency"].get("p99"), 2)))
    L.append("")
    L.append("## 1 聚类（共识双视图 -> 分析格子）")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    for k in ("ari_intent", "ari_pattern", "ari_cell", "nmi_intent", "nmi_pattern",
              "purity_intent", "purity_pattern"):
        L.append("| %s | %s |" % (k, _fmt(cl[k])))
    L.append("| ARI 弃权前 / 弃权后（意图 / 模式 / 格子） | %s -> %s / %s -> %s / %s -> %s |"
             % (_fmt(cl["ari_intent_all"]), _fmt(cl["ari_intent"]),
                _fmt(cl["ari_pattern_all"]), _fmt(cl["ari_pattern"]),
                _fmt(cl["ari_cell_all"]), _fmt(cl["ari_cell"])))
    L.append("| novelty 缓冲区内 多数真实类占比（意图 / 模式） | %s / %s |"
             % (_fmt(cl.get("novelty_purity_intent")), _fmt(cl.get("novelty_purity_pattern"))))
    L.append("| novelty 缓冲区异常率 / 可归簇池异常率 | %s / %s |"
             % (_fmt(cl.get("novelty_anomaly_rate"), 4), _fmt(cl.get("pool_anomaly_rate"), 4)))
    L.append("| 意图簇数 / 真实 | %d / %d |" % (cl["n_intent_clusters"], cl["n_true_intents"]))
    L.append("| 模式簇数 / 真实 | %d / %d |" % (cl["n_pattern_clusters"], cl["n_true_patterns"]))
    L.append("| 格子数 / 真实 | %d / %d |" % (cl["n_cells"], cl["n_true_cells"]))
    L.append("| novelty 率 | %s |" % _fmt(cl["novelty_rate"], 4))
    L.append("| 意图视图信息上界（oracle，同池 / 全量） | %s / %s |"
             % (_fmt(cl.get("ari_intent_ceiling")), _fmt(cl.get("ari_intent_ceiling_all"))))
    L.append("| 模式视图信息上界（oracle，同池 / 全量） | %s / %s |"
             % (_fmt(cl.get("ari_pattern_ceiling")), _fmt(cl.get("ari_pattern_ceiling_all"))))
    _ci, _cp = cl.get("ari_intent_ceiling"), cl.get("ari_pattern_ceiling")
    L.append("| 上界达成率（意图 / 模式） | %s / %s |"
             % (_fmt(cl["ari_intent"] / _ci) if _ci else "n/a",
                _fmt(cl["ari_pattern"] / _cp) if _cp else "n/a"))
    L.append("")
    L.append("## 2 异常识别（L1 稳健z / L2 ECOD / L4 结构 / L5 马尔可夫 + BH-FDR 决策）")
    L.append("")
    L.append("| 指标 | 可归簇池 | 全量 |")
    L.append("|---|---|---|")
    for k in ("precision", "recall", "f1", "fpr"):
        L.append("| %s | %s | %s |" % (k, _fmt(det["pool"][k]), _fmt(det["all"][k])))
    L.append("")
    L.append("- 排序质量：AUC(a_raw)=%s｜PR-AUC=%s｜Precision@50=%s｜Recall@50=%s"
             % (_fmt(det["auc_a_raw"]), _fmt(det["pr_auc"]), _fmt(det["precision_at_50"]),
                _fmt(det["recall_at_50"])))
    L.append("- 分诊分层：tier2 确定性违规 %d｜tier1 统计拒绝 %d｜tier0 其余 %d｜"
             "剔除 tier2 后 Precision@50=%s（该子池异常基率 %s，提升 %s 倍）"
             % (det["tier_mix"].get(2, 0), det["tier_mix"].get(1, 0),
                det["tier_mix"].get(0, 0), _fmt(det["precision_at_50_below_rule"]),
                _fmt(det["below_rule_base_rate"], 4), _fmt(det["below_rule_lift"], 2)))
    L.append("- 告警构成：总计 %d（统计 %d + 硬规则 %d）｜BH alpha=%.3f｜折算 %.2f 条/日"
             % (det["n_alert"], det["n_alert_stat"], det["n_alert_rule"], det["bh_alpha"],
                det["alerts_per_day"]))
    L.append("- 运营口径（唯一会主动打扰人的通道）：日预算 %d 条 x %.0f 天 = k=%d，"
             "Precision=%s"
             % (RG.ALERT_BUDGET_PER_DAY, det["budget_k"] / float(RG.ALERT_BUDGET_PER_DAY),
                det["budget_k"], _fmt(det["precision_at_budget"])))
    L.append("- 漂移监测：%s｜统计量 %s vs 自举阈值 %s（alpha=%.2f，%s）｜最短窗长 %d｜"
             "命中窗 %s｜窗内高于参考中位数占比 %s"
             % ("检出变点 index=%s" % dr["index"] if dr.get("detected") else "未检出变点",
                _fmt(dr.get("statistic"), 2), _fmt(dr.get("lambda"), 2),
                dr.get("alpha") or 0.0, dr.get("lambda_source"),
                dr.get("min_seg_len") or 0, json.dumps(dr.get("window")),
                _fmt(dr.get("share_above_ref_median"), 3)))
    L.append("- 三通道口径区分：告警流 k=%d（会主动打扰人，Precision=%s）｜"
             "审计流 %d 条确定性违规（%.1f 条/日，落库待查不呼叫）｜"
             "复核队列 %d 条（BH-FDR alpha=%.2f，受人工复核预算约束）"
             % (det["budget_k"], _fmt(det["precision_at_budget"]), det["n_alert_rule"],
                det["rule_findings_per_day"], det["n_alert"], det["bh_alpha"]))
    L.append("- 池化回退：格子层权重 B<0.5 的占比 %.3f（检测层非 L3 占比 %.3f）"
             % (det["baseline_fallback_ratio"], det["fallback_share"]))
    L.append("- 本体绑定：%d/%d 个模式簇绑定到声明模式 %s"
             % (len(det["binding"]), len(det["binding_detail"]),
                json.dumps(det["binding"], ensure_ascii=False, sort_keys=True)))
    L.append("- span 级归因（诊断，slice2 才设门槛）：Precision=%s Recall=%s tp=%d fp=%d fn=%d"
             % (_fmt(det["span_localization"]["precision"], 3),
                _fmt(det["span_localization"]["recall"], 3), det["span_localization"]["tp"],
                det["span_localization"]["fp"], det["span_localization"]["fn"]))
    L.append("")
    L.append("| 异常类型 | 样本 | 命中 | 召回 | 统计通道 | 规则通道 |")
    L.append("|---|---|---|---|---|---|")
    for k in sorted(det["per_anomaly_type"], key=lambda z: -det["per_anomaly_type"][z]["n"]):
        e = det["per_anomaly_type"][k]
        L.append("| %s | %d | %d | %s | %d | %d |"
                 % (k, e["n"], e["alert"], _fmt(e["recall"], 3), e["stat"], e["rule"]))
    L.append("")
    L.append("## 3 打分（5 维 x 4 锚点 x 硬门禁 x LMDI 零残差）")
    L.append("")
    L.append("- 零残差最大偏差 `%.3e`（恒等式 sum(contrib) == S - 100G）" % sc["zero_residual_max"])
    L.append("- 分数区分度：AUC(-S vs 异常)=%s｜正常均分 %.2f｜异常均分 %.2f｜分离度 %.2f"
             % (_fmt(sc["score_auc"]), sc["mean_S_normal"], sc["mean_S_anomaly"],
                sc["grade_separation"]))
    L.append("- 与生成器 oracle 维度分的相关：Spearman=%s｜Kendall tau-b=%s"
             % (_fmt(sc["spearman_vs_oracle"]), _fmt(sc["kendall_vs_oracle"])))
    L.append("")
    L.append("| 维度 | Spearman(vs oracle) | 正常均值 | 异常均值 |")
    L.append("|---|---|---|---|")
    for dd in ("O", "P", "L", "C", "R"):
        p = sc["per_dim"][dd]
        L.append("| %s | %s | %s | %s |" % (dd, _fmt(p["spearman"]), _fmt(p["mean_normal"], 3),
                                             _fmt(p["mean_anomaly"], 3)))
    L.append("")
    L.append("- 绝对档位分布 %s" % json.dumps(sc["grade_abs"], ensure_ascii=False))
    L.append("- 相对档位分布 %s" % json.dumps(sc["grade_rel"], ensure_ascii=False))
    L.append("- 门禁触发次数 %s" % json.dumps(sc["gate_hits"], ensure_ascii=False))
    L.append("")
    L.append("## 4 校准（交叉拟合，出折外 ECE）")
    L.append("")
    if cal.get("available"):
        L.append("- 方法 %s｜标注数 %d｜ECE(出折)=%.4f｜ECE(原始 a_raw)=%.4f｜AUC(校准概率)=%s"
                 % (cal["kind"], cal["n_labels"], cal["ece_oof"], cal["ece_raw"],
                    _fmt(cal["auc_cal"])))
        L.append("")
        L.append("| bin | n | 预测均值 | 实际频率 |")
        L.append("|---|---|---|---|")
        for b in cal["reliability"]:
            L.append("| %d | %d | %.3f | %.3f |" % (b["bin"], b["n"], b["conf"], b["acc"]))
    else:
        L.append("- 标注数不足（<%d），跳过校准；冷启动阶段只出分数不出概率。" % MIN_LABELS_CALIB)
    L.append("")
    L.append("## 5 数据质量与漂移")
    L.append("")
    L.append("- 采集缺陷召回（规范化侧检出率）%s" % json.dumps(dq["defect_recall"], ensure_ascii=False))
    L.append("- 真实缺陷轨迹数 %s｜被降级置信度的轨迹 %d｜降级率 %s"
             % (json.dumps(dq["defect_counts_true"]), dq["n_flagged"],
                _fmt(dq["conf_downgrade_rate"], 4)))
    L.append("- 漂移：spec=%s｜检出=%s｜index=%s｜真实 index=%s｜滞后占比=%s｜嫌疑轨迹 %d"
             % (json.dumps(dr.get("drift_spec")), dr.get("detected"), dr.get("index"),
                dr.get("true_index"), _fmt(dr.get("lag_frac"), 4), dr.get("n_suspects", 0)))
    L.append("")
    L.append("## 6 门槛表（contracts/schemas.md 8）")
    L.append("")
    L.append("| 门槛 | 要求 | 实测 | 结论 |")
    L.append("|---|---|---|---|")
    for k in sorted(res["gates"]):
        v = res["gates"][k]
        L.append("| %s | %s | %s | %s |" % (k, v["want"], v["got"],
                                             "PASS" if v["ok"] else "**FAIL**"))
    L.append("")
    L.append("**总体：%s**" % ("全部通过" if res["all_pass"] else "存在未通过门槛"))
    L.append("")
    L.append("- 计时 %s" % json.dumps(dict((k, round(v, 2)) for k, v in res["timings"].items())))
    L.append("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regimes", default="R1")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--bh-alpha", type=float, default=None)
    ap.add_argument("--force-gen", action="store_true")
    args = ap.parse_args()
    ids = [x.strip() for x in args.regimes.split(",") if x.strip()]
    failed = []
    for rid in ids:
        res = run_regime(rid, args.data_root, args.out, threshold=args.threshold,
                         limit=args.limit, force_gen=args.force_gen, bh_alpha=args.bh_alpha)
        bad = [k for k, v in res["gates"].items() if not v["ok"]]
        print("[run] %s pool=%d/%d F1=%.3f P@50=%.3f FPR=%.3f AUC=%.3f ARI_i=%.3f ARI_p=%.3f "
              "zerores=%.1e gates=%s %s"
              % (rid, res["n_pool"], res["n"], res["detection"]["pool"]["f1"],
                 res["detection"]["precision_at_50"] or 0.0, res["detection"]["pool"]["fpr"],
                 res["detection"]["auc_a_raw"] or 0.0, res["clustering"]["ari_intent"],
                 res["clustering"]["ari_pattern"], res["scoring"]["zero_residual_max"],
                 ("ALL-PASS" if not bad else "FAIL:" + ",".join(sorted(bad))),
                 "(%.1fs)" % res["wall_s"]))
        if bad:
            failed.append(rid)
    print("runner: %d/%d regimes all-pass" % (len(ids) - len(failed), len(ids)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())