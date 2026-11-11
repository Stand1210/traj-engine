# -*- coding: utf-8 -*-
"""freezeexp -- does pollution arriving AFTER a clean structure was frozen trip an R2 trigger?

The question this settles
-------------------------
DESIGN.md 6.5.7 deleted the `foreign_ratio` criterion. Its stated residual risk was: foreign
paradigms silently crush the task taxonomy (slimcap measured n_cells 8 -> 4, cell_size_min
8 -> 349 at 20% pollution), and nothing detects it until the M2 batch's R item lands.

But that residual risk rests on an unmeasured premise. slimcap measured the FROM-SCRATCH
setting: cluster a polluted pool in one shot. Production does not work that way. Production
freezes the structure at an R2 and then, every day, R1 labels *new* traces against the frozen
cells and refreshes baselines (LIFECYCLE.md 3.1: "R1 ... cell definitions unchanged").

So the real question is: when foreign traces meet FROZEN clean cells, does `novelty_rate`
rise above the R2 trigger band [0.00, 0.25] (LIFECYCLE.md 3.3)?

  * If YES -> R2 fires -> lineage runs -> lineage reports "merged" (LIFECYCLE.md 3.2a)
              -> the crush is NOT silent -> DESIGN.md pending item T is unnecessary. DELETE it.
  * If NO  -> R2 never fires -> lineage never runs -> the crush is silent and permanent
              -> item T (or something like it) is the only guard. KEEP it.

Two mechanisms point in opposite directions, which is exactly why this needs measuring
rather than reasoning:

  1. AGAINST a rise: `post_margin` (cluster.py:592-608) is a *log-posterior margin*,
     geo(x) = (d2_2nd - d2_own) / (2 sigma^2), zero on the decision boundary and GROWING
     without bound as x moves inside its own class. A foreign trace sitting far out in space
     can therefore have a LARGE geo -- confidently assigned, not flagged.
     And non-sampled traces inherit `memcons_i[ci]` (cluster.py:859), the mean consensus of
     the frozen cluster's sampled members, which is high by construction. So both consensus
     channels also say "confident".
  2. FOR a rise: in the frozen setting `geo_cut` becomes an ABSOLUTE boundary inherited from
     the clean era, whereas in a from-scratch run it is re-derived as the `flag_rate` quantile
     of the current pool (cluster.py:843-850) and is therefore rate-matched and
     self-normalising -- it *cannot* flag more than flag_rate of the pool no matter how much
     foreign traffic arrives. Freezing removes that self-normalisation.

Which one wins is an empirical question about the R1/R8 embedding geometry.

★ Fidelity problem, and how this script handles it
--------------------------------------------------
**The kernel has no R1 assign-only path.** `bench/runner.py:210` always calls
`cluster_views` from scratch, and `structure_version` appears nowhere under `kernel/`.
R1's "cell definitions unchanged" is documented intent (LIFECYCLE.md 3.1) with no code path
yet -- it is platform-layer work (B3/B4) that has not been built. So this script cannot call
a real R1; it must RE-IMPLEMENT the documented semantics.

A re-implementation is only worth reading if it is proven faithful, so:

  * The frozen state is CAPTURED from the kernel, not recomputed. A `sys.settrace` return-event
    spy snapshots `cluster_views`'s frame locals (cents_i, med_p, single_i/p, memcons_i/p,
    sigma2, geo_cut, _sig_ctx, cl, pl, cent_list, threshold). Nothing about the clustering is
    re-derived here. (Cheap because EVAL_M=400 caps the heavy consensus work at 400 points
    regardless of n, so full line tracing costs seconds, not minutes.)
  * `frozen_assign()` replays cluster.py:852-875 verbatim against that captured state.
  * **MANDATORY SELF-CHECK**: replaying it on the SAME features the kernel just clustered must
    reproduce the kernel's own `assigns` exactly, on every key, for every trace. If the replay
    diverges, the re-implementation is wrong and every number below is void -- the script
    raises instead of writing results.

Hold-out design (no leakage)
----------------------------
`mixexp.build(0.0)` gives 4000 clean A traces. Split deterministically at SEED=20261109:
2000 to LEARN the structure, 2000 held out as the STREAM. B traces come from R8 (3000
available) with the same `_src`/session_id relabelling mixexp uses, so A and B sessions stay
disjoint. Arms: clean-holdout (control, 2000 A), poll-05pct (+105 B), poll-20pct (+500 B).
The control is essential: if frozen assignment flags unseen CLEAN traces at a high rate, the
trigger fires for benign reasons and the whole comparison is noise.

`FEAT.annotate_sessions` is run on the learn set and on each stream SEPARATELY, because R1
labels a window as it arrives; sessions never span the boundary (B's are prefixed "x8-").

Post-hoc and in-memory: writes nothing under data/ or reports/, touches no code_hash-closure
file, so code_hash stays 2064664e6aa5fb46 and no published report needs re-running.

Run:  python -u platform/freezeexp.py       (about 3-5 min)
Writes platform/freezeexp-results.json
"""
import io, json, os, pickle, random, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "platform"))
import mixexp as MX
import tierexp as TX
from kernel import ingest, features as FEAT, cluster, drift

SLIM = TX.SLIM                    # ontA with required_steps DELETED = the real tenant ontology
SEED = MX.SEED                    # 20261109 -- same as mixexp/tierexp/slimcap
NDEC = 3                          # -> cap 5, the L2 constant PATTERN_CAP_NDEC_DEFAULT (DESIGN 7.6)
N_LEARN = 2000
NOV_BAND = (0.00, 0.25)           # LIFECYCLE 3.3 == reports/*/metrics.json gates.novelty_rate.want
ARMS = [("clean-holdout", 0.0), ("poll-05pct", 0.05), ("poll-20pct", 0.20),
        ("poll-25pct", 0.25), ("poll-30pct", 0.30), ("poll-40pct", 0.40)]
STATE_CACHE = os.path.join("platform", "_frozen_state.pkl")
KEYS = ["trace_id", "intent_cluster", "pattern_cluster", "cell", "consensus_intent",
        "consensus_pattern", "novelty", "near_intent", "near_pattern", "post_margin"]


# ---------------------------------------------------------------- state capture
def spy_cluster_views(feats, ndec):
    """Run the real kernel cluster_views and snapshot its frame locals at return."""
    cap = {}

    def _local(fr, ev, ar):
        if ev == "return":
            cap.update(fr.f_locals)
        return _local

    def _global(fr, ev, ar):
        if (ev == "call" and fr.f_code.co_name == "cluster_views"
                and fr.f_code.co_filename.replace("\\", "/").endswith("kernel/cluster.py")):
            return _local
        return None

    cluster.reset_cache()
    sys.settrace(_global)
    try:
        assigns, cinfo = cluster.cluster_views(
            feats, threshold=cluster.CONSENSUS_THRESHOLD, seed=SEED, n_declared_patterns=ndec)
    finally:
        sys.settrace(None)
    need = ["cents_i", "med_p", "single_i", "single_p", "memcons_i", "memcons_p",
            "cons_i", "cons_p", "cl", "pl", "cent_list", "sigma2", "geo_cut",
            "threshold", "eval_idx", "n_flag", "flag_rate", "m", "_sig_ctx"]
    missing = [k for k in need if k not in cap]
    assert not missing, "spy failed to capture: %s" % missing
    # Re-key the sampled-point consensus by trace_id so ONE code path serves both the
    # self-check (learn feats, which ARE sampled) and the streams (which are NOT). This is
    # exactly equivalent to the kernel's `p = pos_of.get(i)` because trace ids are unique.
    st = dict((k, cap[k]) for k in need)
    st["_cons_i_t"] = dict((feats[i]["trace_id"], cap["cons_i"][p])
                           for p, i in enumerate(cap["eval_idx"]))
    st["_cons_p_t"] = dict((feats[i]["trace_id"], cap["cons_p"][p])
                           for p, i in enumerate(cap["eval_idx"]))
    return assigns, cinfo, st


def frozen_assign(feats, st):
    """Replay kernel/cluster.py:852-875 verbatim against a captured, frozen structure."""
    cents_i, med_p = st["cents_i"], st["med_p"]
    cl, pl, cent_list = st["cl"], st["pl"], st["cent_list"]
    single_i, single_p = st["single_i"], st["single_p"]
    memcons_i, memcons_p = st["memcons_i"], st["memcons_p"]
    sigma2, geo_cut, threshold = st["sigma2"], st["geo_cut"], st["threshold"]
    sig, sig_tok = st["_sig_ctx"]
    out = []
    for i in range(len(feats)):
        f = feats[i]
        e = f["embedding"]
        ci = min(cl, key=lambda c: cluster.euclid(e, cents_i[c])) if cl else -1
        sk = cluster.collapse(f["action_seq"])
        cp = (min(pl, key=lambda c: cluster.seq_dist(sk, med_p[c], sig, sig_tok))
              if pl else -1)
        tid = f["trace_id"]
        vi = st["_cons_i_t"][tid] if tid in st["_cons_i_t"] else memcons_i.get(ci, 0.0)
        vp = st["_cons_p_t"][tid] if tid in st["_cons_p_t"] else memcons_p.get(cp, 0.0)
        geo = cluster.post_margin(e, cent_list, sigma2)
        nov = ((ci in single_i) or (cp in single_p) or (vi < threshold) or (vp < threshold)
               or (geo_cut is not None and geo <= geo_cut))
        out.append({
            "trace_id": tid,
            "intent_cluster": -1 if nov else ci,
            "pattern_cluster": -1 if nov else cp,
            "cell": None if nov else ("i%dxp%d" % (ci, cp)),
            "consensus_intent": vi,
            "consensus_pattern": vp,
            "novelty": bool(nov),
            "near_intent": ci,
            "near_pattern": cp,
            "post_margin": (None if geo == float("inf") else round(geo, 6)),
        })
    return out


# ---------------------------------------------------------------- helpers
def feats_of(traces, ont):
    norms = [ingest.normalize(t, ont) for t in traces]
    fs = [FEAT.extract(n, ont) for n in norms]
    FEAT.annotate_sessions(fs, traces)
    return fs


def p50(v):
    if not v:
        return None
    sv = sorted(v)
    n = len(sv)
    return sv[n // 2] if n % 2 else 0.5 * (sv[n // 2 - 1] + sv[n // 2])


def main():
    t_start = time.time()
    ont = SLIM

    # ---- cohorts: hold-out split of the clean A pool + an R8 foreign pool -------------
    trA, _ = MX.build(0.0)
    assert len(trA) == 4000 and all(t["_src"] == "A" for t in trA)
    order = list(range(len(trA)))
    random.Random(SEED).shuffle(order)
    learn_set = set(order[:N_LEARN])
    A_learn = [trA[i] for i in range(len(trA)) if i in learn_set]
    A_stream = [trA[i] for i in range(len(trA)) if i not in learn_set]
    assert len(A_learn) == N_LEARN and len(A_stream) == len(trA) - N_LEARN
    assert not (set(t["trace_id"] for t in A_learn) & set(t["trace_id"] for t in A_stream))

    trB = MX.load("R8", "traces")
    for t in trB:
        t["_src"] = "B"
        t["session_id"] = "x8-" + str(t["session_id"])
    B_pool = random.Random(SEED + 1).sample(trB, 1500)

    # ---- learn the frozen structure on clean traffic ---------------------------------
    print("=== learning frozen structure on %d clean A traces ===" % len(A_learn), flush=True)
    f_learn = feats_of(A_learn, ont)
    t0 = time.time()
    if os.path.exists(STATE_CACHE) and "--refresh" not in sys.argv:
        # The traced cluster_views call costs ~350s (sys.settrace intercepts every nested
        # call event). Cache the captured state so re-runs and extra arms cost seconds.
        # **pickle, not JSON**: the state contains int-keyed dicts (cents_i / med_p /
        # memcons_i / memcons_p), sets (single_i / single_p / sig) and a tuple (sig_tok).
        # JSON would stringify the int keys -- which then reach `"i%dxp%d" % (ci, cp)` and
        # raise -- and would refuse to serialise the sets at all. pickle round-trips exactly.
        with open(STATE_CACHE, "rb") as fh:
            blob = pickle.load(fh)
        ST, assigns_learn, cinfo_learn = blob["state"], blob["assigns_learn"], blob["cinfo_learn"]
        print("=== loaded cached frozen structure from %s ===" % STATE_CACHE, flush=True)
    else:
        assigns_learn, cinfo_learn, ST = spy_cluster_views(f_learn, NDEC)
        blob = {"state": ST, "assigns_learn": assigns_learn, "cinfo_learn": cinfo_learn}
        with open(STATE_CACHE, "wb") as fh:
            pickle.dump(blob, fh, protocol=4)
        print("=== cached frozen structure to %s ===" % STATE_CACHE, flush=True)
    print("    cluster_views %.1fs  n_cells=%s  n_intent=%s  n_pattern=%s  novelty=%s"
          % (time.time() - t0, cinfo_learn.get("n_cells"), cinfo_learn.get("n_intent_clusters"),
             cinfo_learn.get("n_pattern_clusters"), cinfo_learn.get("novelty_rate")), flush=True)
    # `_sig_ctx` is a tuple local; grab it explicitly (the spy stores all locals).
    print("    sigma2=%.6g  geo_cut=%s  n_flag=%s/%s  flag_rate=%.6g"
          % (ST["sigma2"], ST["geo_cut"], ST["n_flag"], ST["m"], ST["flag_rate"]), flush=True)

    # ---- MANDATORY SELF-CHECK: replay must reproduce the kernel exactly --------------
    replay = frozen_assign(f_learn, ST)
    assert len(replay) == len(assigns_learn)
    bad = []
    for r, k in zip(replay, assigns_learn):
        for key in KEYS:
            a, b = r.get(key), k.get(key)
            if isinstance(a, float) and isinstance(b, float):
                if abs(a - b) > 1e-12:
                    bad.append((r["trace_id"], key, a, b))
            elif a != b:
                bad.append((r["trace_id"], key, a, b))
    if bad:
        raise SystemExit("SELF-CHECK FAILED: frozen_assign diverges from the kernel on %d "
                         "field(s); first 5: %s -- every number below would be void."
                         % (len(bad), bad[:5]))
    print("    SELF-CHECK PASS: replay reproduces the kernel on %d traces x %d keys"
          % (len(replay), len(KEYS)), flush=True)

    learn_sizes = {}
    for a in assigns_learn:
        if not a["novelty"]:
            learn_sizes[a["cell"]] = learn_sizes.get(a["cell"], 0) + 1

    # ---- arms ------------------------------------------------------------------------
    results = []
    for tag, frac in ARMS:
        k = int(round(N_LEARN * frac / (1.0 - frac))) if frac > 0 else 0
        stream = list(A_stream) + (list(B_pool[:k]) if k else [])
        t0 = time.time()
        f_stream = feats_of(stream, ont)
        asg = frozen_assign(f_stream, ST)
        src = dict((t["trace_id"], t["_src"]) for t in stream)
        lat = dict((t["trace_id"], t.get("latency_total")) for t in stream)
        # feature-side latency (feats carry the normalised value the baseline actually uses)
        latf = dict((f["trace_id"], f.get("latency_total")) for f in f_stream)
        for tid in latf:
            if latf[tid] is not None:
                lat[tid] = latf[tid]
        A = dict((a["trace_id"], a) for a in asg)

        def nov_rate(pred):
            sel = [t for t in A if pred(t)]
            return (sum(1 for t in sel if A[t]["novelty"]) / float(len(sel))) if sel else None

        nr_all = sum(1 for a in asg if a["novelty"]) / float(len(asg))
        nr_A = nov_rate(lambda t: src[t] == "A")
        nr_B = nov_rate(lambda t: src[t] == "B")

        # where do the foreign traces go?
        absorb = {}
        for t in A:
            if src[t] == "B" and not A[t]["novelty"]:
                absorb[A[t]["cell"]] = absorb.get(A[t]["cell"], 0) + 1
        n_B = sum(1 for t in A if src[t] == "B")
        n_B_nov = sum(1 for t in A if src[t] == "B" and A[t]["novelty"])

        # geo distributions -- the mechanism evidence
        def geo_stats(pred):
            v = sorted(A[t]["post_margin"] for t in A
                       if pred(t) and A[t]["post_margin"] is not None)
            if not v:
                return None
            return {"n": len(v), "p10": v[max(0, int(0.10 * len(v)))],
                    "p50": v[len(v) // 2], "p90": v[min(len(v) - 1, int(0.90 * len(v)))],
                    "frac_below_geo_cut": (sum(1 for x in v if ST["geo_cut"] is not None
                                               and x <= ST["geo_cut"]) / float(len(v)))}

        # baseline contamination: R1 REFRESHES baselines, so absorbed B moves the cell's P50
        cells = sorted(set(a["cell"] for a in asg if not a["novelty"]))
        contam = []
        for c in cells:
            memA = [lat[t] for t in A if A[t]["cell"] == c and src[t] == "A" and lat.get(t) is not None]
            memAll = [lat[t] for t in A if A[t]["cell"] == c and lat.get(t) is not None]
            nB_in_c = len(memAll) - len(memA)
            if not memA or not nB_in_c:
                continue
            pa, pall = p50(memA), p50(memAll)
            contam.append({"cell": c, "n_A": len(memA), "n_B_absorbed": nB_in_c,
                           "p50_A_only": round(pa, 4), "p50_mixed": round(pall, 4),
                           "p50_shift_ratio": round(pall / pa, 4) if pa else None})
        contam.sort(key=lambda d: -(d["n_B_absorbed"]))
        worst = max((abs(d["p50_shift_ratio"] - 1.0) for d in contam
                     if d["p50_shift_ratio"]), default=None)

        # does drift fire on the frozen-labelled stream?
        ordered = sorted(f_stream, key=lambda f: (f["ts_start"], f["trace_id"]))
        cell_of = dict((a["trace_id"], a["cell"]) for a in asg)
        par_of = dict((a["trace_id"], "i%d" % a.get("near_intent", -1)) for a in asg)
        dr = drift.detect_drift([(f["trace_id"], cell_of.get(f["trace_id"]),
                                  par_of.get(f["trace_id"]), f["latency_total"])
                                 for f in ordered])

        sizes = {}
        for a in asg:
            if not a["novelty"]:
                sizes[a["cell"]] = sizes.get(a["cell"], 0) + 1
        sv = sorted(sizes.values())

        res = {
            "tag": tag, "frac": frac, "k_B": k, "n_stream": len(asg),
            "n_A": sum(1 for t in src if src[t] == "A"), "n_B": n_B,
            "wall_s": round(time.time() - t0, 1),
            "novelty_rate_all": round(nr_all, 5),
            "novelty_rate_A": (round(nr_A, 5) if nr_A is not None else None),
            "novelty_rate_B": (round(nr_B, 5) if nr_B is not None else None),
            "R2_trigger_novelty_band": NOV_BAND,
            "R2_fires_on_novelty": bool(nr_all > NOV_BAND[1]),
            "drift_detected": bool(dr.get("drift_detected")),
            "drift_n_suspects": len(dr.get("suspects") or []),
            "R2_fires_at_all": bool(nr_all > NOV_BAND[1] or dr.get("drift_detected")),
            "n_cells_occupied": len(sizes),
            "cell_size_min": sv[0] if sv else None,
            "cell_size_max": sv[-1] if sv else None,
            "B_absorbed": n_B - n_B_nov,
            "B_absorbed_frac": (round((n_B - n_B_nov) / float(n_B), 4) if n_B else None),
            "B_absorb_census": absorb,
            "geo_A": geo_stats(lambda t: src[t] == "A"),
            "geo_B": geo_stats(lambda t: src[t] == "B"),
            "baseline_contamination_top5": contam[:5],
            "worst_p50_shift_abs": (round(worst, 4) if worst is not None else None),
        }
        results.append(res)
        print("=== %-14s n=%4d (B=%3d)  nov_all=%.4f nov_A=%.4f nov_B=%s  "
              "R2_fires=%s  B_absorbed=%s/%s  cells=%d  worst_p50_shift=%s  (%.1fs)"
              % (tag, len(asg), n_B, nr_all, nr_A or -1,
                 ("%.4f" % nr_B) if nr_B is not None else "-", res["R2_fires_at_all"],
                 n_B - n_B_nov, n_B, len(sizes), res["worst_p50_shift_abs"],
                 res["wall_s"]), flush=True)

    out = {
        "_note": ("Frozen-structure (documented R1 semantics) hold-out experiment. Structure "
                  "learned on 2000 clean A traces from mixexp.build(0.0); streams are the "
                  "disjoint 2000 A hold-out plus k R8 foreign traces. State is SPY-CAPTURED "
                  "from the real kernel cluster_views (sys.settrace return event), not "
                  "recomputed; frozen_assign replays cluster.py:852-875 and is SELF-CHECKED to "
                  "reproduce the kernel's own assigns exactly before any arm is measured. "
                  "Answers DESIGN.md 6.5.7 / pending item T: does pollution trip an R2 trigger?"),
        "_self_check": "PASS: %d traces x %d keys identical to the kernel" % (len(replay), len(KEYS)),
        "_structure": {
            "n_learn": len(A_learn), "seed": SEED, "ndec": NDEC,
            "cap": max(2, min(cluster.K_MAX_PATTERN_ABS, NDEC + cluster.K_MAX_PATTERN_HEADROOM)),
            "n_cells_learn": len(learn_sizes),
            "cell_sizes_learn": dict(sorted(learn_sizes.items(), key=lambda kv: -kv[1])),
            "n_intent_clusters": cinfo_learn.get("n_intent_clusters"),
            "n_pattern_clusters": cinfo_learn.get("n_pattern_clusters"),
            "novelty_rate_learn": cinfo_learn.get("novelty_rate"),
            "sigma2": ST["sigma2"], "geo_cut": ST["geo_cut"],
            "n_flag": ST["n_flag"], "m": ST["m"], "flag_rate": ST["flag_rate"],
        },
        "_wall_secs": round(time.time() - t_start, 1),
        "arms": results,
    }
    with io.open("platform/freezeexp-results.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=False)
    print("DONE in %.1fs -> platform/freezeexp-results.json" % out["_wall_secs"], flush=True)


if __name__ == "__main__":
    main()
