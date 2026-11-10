# -*- coding: utf-8 -*-
"""Mixed-ontology cohort experiment (arm 2: type-correct stat + budget crowding-out metrics).

Post-hoc, in-memory: writes NO file under data/ or reports/, touches no code_hash-closure file.

Question: under `one project = one ontology`, a tenant's project may still contain foreign-paradigm
traces. The user proposes NOT handling that noise. This measures what it costs.

Mechanism found by reading the code before measuring (kernel/detect.py:280, :388, :631):
    unfulfilled = bool(declared_all) and not any(v <= present for v in declared_all.values())
    hard        = bool(illegal_actions) or unfinished >= 1.0 or truncated > 0
                  or bool(missing_declared) or unfulfilled or missing_frac >= MISSING_HARD ...
    alert_rule  = (not novelty) and struct["hard"]
A foreign trace implements none of the registered ontology's declared patterns -> unfulfilled=True
-> hard=True -> alert_rule=True unconditionally. So the predicted damage is NOT "legit traces get
false alarms" but "the alert budget is eaten alive", which would show up as recall collapse on the
legit traces. Both are measured separately below.

Splice artefacts checked beforehand:
  * session_id collides across regimes (658 shared ids, both name sessions `sess-00000`) -> ontB
    session ids namespaced, else annotate_sessions merges two paradigms' turns and silently
    corrupts session_turn_count / turn_index / reformulation_signal.
  * trace_id / span_id do NOT collide (regime-prefixed).
  * ts_start ranges already overlap (both ~72 h from the same epoch) -> no shifting needed.
    Shifting would have been required because drift.detect_drift sorts by ts_start.
  * root action `agent_run` IS shared by ontA and ontB, so a naive "declared-vocabulary
    intersection is empty" pollution test never fires. foreign_ratio() excludes the root on
    purpose. This corrects an earlier claim of mine.
"""
import io, json, os, random, sys, time

sys.path.insert(0, os.getcwd())
from kernel import ingest, features as FEAT, cluster, baseline as BL, binding as BD
from kernel import detect as DET, score, drift, meta
from ontology.base import get_ontology

ONT = get_ontology("ontA")
ALLOWED = set(ONT["actions"]) | set(ONT["forbidden_actions"])
ROOT = ONT["root_action"]
SEED = 20261109
BUDGET_K = 15          # bench/regime.py: ALERT_BUDGET_PER_DAY = 5 over days = 3.0
STRUCT_NUM = ["missing_frac", "unfinished", "truncated", "loop_rule", "traceable_viol"]
STRUCT_LIST = ["illegal_actions", "missing_declared", "unrecovered_errors", "untraceable_numbers"]
STRUCT_BOOL = ["unfulfilled", "hard"]


def load(rid, kind):
    out = []
    with io.open("data/bench_v1/%s/%s.jsonl" % (rid, kind), encoding="utf-8") as f:
        for line in f:
            out.append(json.loads(line))
    return out


def foreign_ratio(tr):
    ns = [s for s in tr["spans"] if s["action"] != ROOT]
    if not ns:
        return 0.0
    return sum(1 for s in ns if s["action"] not in ALLOWED) / float(len(ns))


def fired(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return x > 0
    if isinstance(x, (list, tuple, set, dict)):
        return len(x) > 0
    return x is not None


def run(traces, gts, tag):
    t0 = time.time()
    gt = dict((g["trace_id"], g) for g in gts)
    src = dict((t["trace_id"], t["_src"]) for t in traces)
    raw = dict((t["trace_id"], t) for t in traces)

    norms = [ingest.normalize(t, ONT) for t in traces]
    feats = [FEAT.extract(n, ONT) for n in norms]
    FEAT.annotate_sessions(feats, traces)
    cluster.reset_cache()
    assigns, cinfo = cluster.cluster_views(
        feats, threshold=cluster.CONSENSUS_THRESHOLD, seed=SEED,
        n_declared_patterns=len(ONT.get("required_steps") or {}))
    cold_start = len(feats) < 1000
    anchor_version = "anchor-mixexp-%s" % tag
    records = [{"cell": a["cell"], "intent": a.get("near_intent", -1), "feats": f}
               for a, f in zip(assigns, feats) if not a["novelty"]]
    art = BL.build(records, ONT, anchor_version)
    binding = BD.bind_patterns(art, ONT)
    bdetail = BD.binding_detail(art, ONT)
    stage, dinfo = DET.detect_all(feats, assigns, art, ONT, binding=binding,
                                  bh_alpha=DET.BH_ALPHA)
    ordered = sorted(feats, key=lambda f: (f["ts_start"], f["trace_id"]))
    cell_of = dict((a["trace_id"], a["cell"]) for a in assigns)
    par_of = dict((a["trace_id"], "i%d" % a.get("near_intent", -1)) for a in assigns)
    stream = [(f["trace_id"], cell_of.get(f["trace_id"]), par_of.get(f["trace_id"]),
               f["latency_total"]) for f in ordered]
    dr = drift.detect_drift(stream)
    recs = score.score_all(feats, assigns, stage, art, ONT, cold_start=cold_start,
                           drift_map=dict((x, True) for x in set(dr.get("suspects") or [])),
                           anchor_version=anchor_version, model_version="mixexp")
    R = dict((r["trace_id"], r) for r in recs)
    wall = time.time() - t0

    tids = [f["trace_id"] for f in feats]
    y = dict((t, bool(gt[t]["is_anomaly"])) for t in tids if t in gt)
    pool = [t for t in tids if not R[t]["novelty"] and t in y]

    # --- budget crowding-out: who occupies the operator's top-K stream? ---
    ranked = sorted(pool, key=lambda t: -stage[t]["a_raw"])
    topk = ranked[:BUDGET_K]
    topk_A = sum(1 for t in topk if src[t] == "A")
    topk_true = sum(1 for t in topk if y[t])
    topk_A_true = sum(1 for t in topk if src[t] == "A" and y[t])

    def stat(ids):
        ids = [t for t in ids if t in y]
        if not ids:
            return None
        p = [t for t in ids if not R[t]["novelty"]]
        norm = [t for t in ids if not y[t]]
        anom = [t for t in ids if y[t]]
        pn = [t for t in p if not y[t]]
        st = dict((t, (stage[t].get("struct") or {})) for t in ids if t in stage)
        o = {"n": len(ids), "n_pool": len(p),
             "novelty_rate": sum(1 for t in ids if R[t]["novelty"]) / float(len(ids)),
             "mean_S": sum(R[t]["S"] for t in ids) / float(len(ids)),
             "alert_rate": sum(1 for t in ids if R[t]["alert"]) / float(len(ids)),
             "alert_rule_rate": sum(1 for t in ids if R[t]["alert_rule"]) / float(len(ids)),
             "foreign_ratio_mean": sum(foreign_ratio(raw[t]) for t in ids) / float(len(ids)),
             "foreign_ratio_gt0": sum(1 for t in ids if foreign_ratio(raw[t]) > 0) / float(len(ids))}
        if norm:
            o["mean_S_normal"] = sum(R[t]["S"] for t in norm) / float(len(norm))
        if anom:
            o["mean_S_anom"] = sum(R[t]["S"] for t in anom) / float(len(anom))
        if pn:
            o["fpr_pool"] = sum(1 for t in pn if R[t]["alert"]) / float(len(pn))
        if anom:
            o["recall_pool"] = sum(1 for t in anom if R[t]["alert"]) / float(len(anom))
        for k in STRUCT_NUM + STRUCT_LIST + STRUCT_BOOL:
            v = [s.get(k) for s in st.values() if s.get(k) is not None]
            if v:
                o["fire_" + k] = sum(1 for x in v if fired(x)) / float(len(v))
        if len(p) > 2:
            yp = [y[t] for t in p]
            ar = [stage[t]["a_raw"] for t in p]
            o["f1_pool"] = meta.prf(yp, [R[t]["alert"] for t in p])["f1"]
            o["auc_pool"] = meta.roc_auc(ar, yp)
            o["p_at_50"] = meta.precision_at_k(ar, yp, 50)
        return dict((kk, (round(vv, 5) if isinstance(vv, float) else vv)) for kk, vv in o.items())

    res = {"tag": tag, "wall_s": round(wall, 1), "n": len(tids), "n_pool": len(pool),
           "prevalence": round(sum(1 for t in tids if y.get(t)) / float(len(y)), 4),
           "novelty_rate": round(sum(1 for t in tids if R[t]["novelty"]) / float(len(tids)), 5),
           "n_cells": len(set(R[t]["cell"] for t in pool)),
           "n_cells_A": len(set(R[t]["cell"] for t in pool if src[t] == "A")),
           "n_cells_B": len(set(R[t]["cell"] for t in pool if src[t] == "B")),
           "shared_cells": len(set(R[t]["cell"] for t in pool if src[t] == "A") &
                               set(R[t]["cell"] for t in pool if src[t] == "B")),
           "n_bound_cells": sum(1 for c, b in (bdetail or {}).items() if b),
           "n_bindable_cells": len(bdetail or {}),
           "drift_detected": bool(dr.get("drift")),
           "topk_A_share": round(topk_A / float(len(topk)), 4) if topk else None,
           "topk_precision": round(topk_true / float(len(topk)), 4) if topk else None,
           "topk_A_precision": round(topk_A_true / float(topk_A), 4) if topk_A else None,
           "overall": stat(tids), "A": stat([t for t in tids if src[t] == "A"]),
           "B": stat([t for t in tids if src[t] == "B"])}
    print(json.dumps(res, ensure_ascii=False, sort_keys=True), flush=True)
    return res


def build(frac):
    k = int(round(4000 * frac))
    rng = random.Random(SEED)
    a = load("R1", "traces"); ga = load("R1", "gt")
    b = load("R8", "traces"); gb = load("R8", "gt")
    if k:
        a = rng.sample(a, 4000 - k); b = rng.sample(b, k)
    else:
        a = a[:4000]; b = []
    ka = set(t["trace_id"] for t in a); kb = set(t["trace_id"] for t in b)
    ga = [g for g in ga if g["trace_id"] in ka]
    gb = [g for g in gb if g["trace_id"] in kb]
    for t in a:
        t["_src"] = "A"
    for t in b:
        t["_src"] = "B"; t["session_id"] = "x8-" + str(t["session_id"])
    tr = a + b
    rng.shuffle(tr)
    return tr, ga + gb


def main():
    out = []
    for frac, tag in [(0.0, "ctrl-0pct"), (0.05, "mix-05pct"),
                      (0.20, "mix-20pct"), (0.50, "mix-50pct")]:
        tr, g = build(frac)
        print("=== %s : n=%d (B=%d) ===" % (tag, len(tr), sum(1 for t in tr if t["_src"] == "B")),
              flush=True)
        out.append(run(tr, g, tag))
    with io.open("_mixexp.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("DONE", flush=True)


# Guard added 2026-11-10: without it, `import mixexp` from a diagnostic script silently
# re-ran all four arms (~7 min) before the caller's own code started.
if __name__ == "__main__":
    main()
