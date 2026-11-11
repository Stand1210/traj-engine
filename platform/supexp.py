# -*- coding: utf-8 -*-
"""supexp -- can a DATA-DRIVEN support floor replace the business-facing `pattern_count`?

Question
--------
capexp.py measured that dropping `pattern_count` (=> cap 8) is NOT free on clean traffic:
R2/R3/R4 all lose pattern-view ARI and f1_pool, and R2's novelty_rate rises 13x. So the cap
is load-bearing. But the *business-facing field* is still broken, because:

  * it saturates: kmax_pat = max(2, min(8, n + 2)), so every n >= 6 gives cap 8 == not filling
    it in at all. The only informative settings (1..5) all restrict DOWNWARD, and downward is
    the unrecoverable direction (cluster.py:468-472).
  * it is a modelling hyperparameter, not a statement about what counts as correct behaviour,
    so by the ratified layering principle it belongs in L2 (platform), not L1 (business).

This script tests the L2 replacement: **a support floor on pattern-cluster mass.**

Mechanism (read from kernel/cluster.py, no kernel edit)
-------------------------------------------------------
`select_cut_height` (:440) sweeps HEIGHT_GRID, keeps heights that are *admissible*
(`2 <= k <= k_max` AND clusters of >= min_size unique sequences cover >= min_cover of the
trace mass), scores them with the k-neutral silhouette, then takes the FINEST height inside a
tolerance band below the best score (:504-506). Since the statistic is monotone toward finer
partitions once its k-bias is removed (:51-53), **the cap is the only thing bounding k.**

So the cap can be replaced by a *second admissibility constraint* that is computed from the
data: every pattern cluster must hold at least S traces. S needs no business input -- it is the
same quantity the credibility knee already uses downstream (baseline.py KAPPA=30).

Zero kernel change: the platform runs one cheap pre-sweep at cap 8, reads off the k that the
support floor would have chosen (k_sup), and passes `n_declared_patterns = k_sup - HEADROOM`
into the EXISTING `cluster_views` formal parameter. This is exactly the rule already written
down at ROADMAP.md:159 ("platform-side capabilities go through cluster_views' existing
parameters").

How the pre-sweep gets the *exact* inputs
-----------------------------------------
The pattern view's distance matrix is built inside `cluster_views` from a seeded EVAL_M sample
whose rng has already been consumed by the intent view, so re-deriving it offline would be
fragile. Instead this script installs a spy on `cluster.select_cut_height` from the harness
(process-local monkeypatch, kernel files untouched => code_hash unchanged) and captures the
`dm` / `weights` / `min_size` / `min_cover` that `cluster_views` actually built. The sweep is
then replayed offline against those captured inputs, and S=0 must reproduce the kernel's own
choice -- that equality is asserted, which makes the replication self-checking.

★★ RESULT: THE SUPPORT FLOOR IS REJECTED -- MEASURED, NOT ARGUED
---------------------------------------------------------------
Stage A on R1 (n=4000, u=83 unique sequences): the k the support floor would choose, over
absolute floors S = [0, 10, 15, 20, 25, 30, 40, 50], is

    [6, 2, 2, 2, 2, 2, 2, 2]

i.e. EVERY floor >= 10 traces collapses the pattern view to k = 2. The true pattern count on
all eight regimes is 3, so k = 2 is UNDER-SPLITTING -- exactly the direction cluster.py:468-472
calls "not recoverable anywhere downstream ... a cell that silently mixes two workflows has a
bimodal conditional distribution". The mechanism is that pattern clusters are strongly
unbalanced (one dominant cluster plus a tail of small ones), so a *minimum* mass constraint
does not trim the tail, it vetoes every intermediate cut and falls straight through to the
coarsest admissible partition. A constraint that pushes toward the unrecoverable failure is
worse than no constraint. Recorded as a rejected alternative; do not re-propose it.

Stages
------
  A   for each clean regime: run the pipeline at cap 8, capture, and report k_sup(S) over a
      grid of absolute and relative support floors.   ~12 min
  B S  for each clean regime: re-run the full pipeline with the cap implied by floor S and
      report the downstream numbers, to be compared against capexp's declared / cap8 arms.
      ~12 min

Run:  python -u platform/supexp.py A
      python -u platform/supexp.py B 30
Writes: platform/supexp-stageA.json , platform/supexp-stageB-S<S>.json
"""
import io, json, os, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "platform"))
from kernel import cluster as C, baseline as BL
import bench.regime as RG

RIDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
CAP8 = C.K_MAX_PATTERN_ABS
KAPPA = BL.KAPPA
ABS_FLOORS = [0, 10, 15, 20, 25, 30, 40, 50]
REL_FLOORS = [0.0, 0.025, 0.05, 0.075, 0.10]

# ---------------------------------------------------------------- spy (process-local)
CAPT = {}
_ORIG = C.select_cut_height


def _spy(dm, u, grid=C.HEIGHT_GRID, k_max=C.K_MAX_PATTERN, min_size=2, min_cover=0.90,
         weights=None):
    h, s, curve = _ORIG(dm, u, grid=grid, k_max=k_max, min_size=min_size,
                        min_cover=min_cover, weights=weights)
    CAPT.clear()
    CAPT.update(dm=[list(r) for r in dm], u=u, k_max=k_max, min_size=min_size,
                min_cover=min_cover, w=list(weights) if weights else [1.0] * u,
                chosen_h=h, chosen_sil=s, curve=curve)
    return h, s, curve


C.select_cut_height = _spy


# ---------------------------------------------------------------- offline replay
def sweep(cap):
    """Replay select_cut_height's grid against the captured matrix, recording mass stats.

    silhouette is computed only where the kernel would compute it (base-admissible heights);
    a support floor can only *remove* candidates, so reusing those scores is exact.
    """
    dm, u, w = CAPT["dm"], CAPT["u"], CAPT["w"]
    ms, mc = CAPT["min_size"], CAPT["min_cover"]
    tot_w = sum(w) or 1.0
    sched = C.upgma(dm, u)
    rows = []
    for h in C.HEIGHT_GRID:
        cid = C.cut_from_schedule(sched, u, h)
        lab = [cid.get(i, i) for i in range(u)]
        sizes, mass = {}, {}
        for j, l in enumerate(lab):
            sizes[l] = sizes.get(l, 0) + 1
            mass[l] = mass.get(l, 0.0) + w[j]
        covered = sum(v for l, v in mass.items() if sizes[l] >= ms)
        k = len(sizes)
        base = (2 <= k <= cap) and covered >= mc * tot_w
        mv = list(mass.values())
        rows.append({"h": h, "k": k, "sil": (C.silhouette_dm(dm, lab, w) if base else None),
                     "base_adm": base, "min_mass": round(min(mv), 3),
                     "max_mass": round(max(mv), 3),
                     "n_below_kappa": sum(1 for v in mv if v < KAPPA),
                     "cover": round(covered / tot_w, 5)})
    return rows, tot_w


def pick(rows, S):
    """The kernel's own selection rule, plus the support floor S as a second constraint."""
    adm = [r for r in rows if r["base_adm"] and r["sil"] is not None and r["min_mass"] >= S]
    if not adm:
        return None
    best = max(r["sil"] for r in adm)
    floor = best - max(C.SIL_TOL * abs(best), C.SIL_ABS_TOL)
    return min((r for r in adm if r["sil"] >= floor), key=lambda r: r["h"])


# ---------------------------------------------------------------- stages
def stage_a():
    import capexp
    out = {"_note": "Stage A: support-floor pre-sweep at cap 8 on CLEAN regimes. "
                    "S=0 must reproduce the kernel's own choice (asserted).",
           "kappa": KAPPA, "cap8": CAP8, "sil_tol": C.SIL_TOL, "sil_abs_tol": C.SIL_ABS_TOL,
           "abs_floors": ABS_FLOORS, "rel_floors": REL_FLOORS, "regimes": []}
    t0 = time.time()
    for rid in RIDS:
        r = capexp.arm(rid, 0, "cap8_probe")
        rows, tot_w = sweep(CAP8)
        base = pick(rows, 0.0)
        assert base is not None, rid
        # Fidelity check: the offline replay must reproduce the kernel's chosen CUT HEIGHT.
        # It must NOT be expected to reproduce n_pattern_clusters -- those are different
        # objects. `base["k"]` is the number of clusters the dendrogram cut yields over the
        # u UNIQUE action sequences; cinfo["n_pattern_clusters"] is len(groups_p)
        # (cluster.py:878), the number of consensus groups over the m SAMPLED TRACES after
        # _consensus(). My first version asserted they were equal and failed on R2 (7 vs 8).
        # That assert was wrong, not the replication; the height match is the real check.
        assert base["h"] == CAPT["chosen_h"], (rid, base["h"], CAPT["chosen_h"])
        # select_cut_height returns round(silhouette_dm(...), 4) (cluster.py:508); compare at
        # the same precision. First version compared the unrounded value and failed on R1
        # (0.6559400320246704 vs 0.6559) -- a rounding artefact, not a replication error.
        assert round(base["sil"], 4) == CAPT["chosen_sil"], (rid, base["sil"], CAPT["chosen_sil"])
        rec = {"rid": rid, "n": r["n"], "u": CAPT["u"], "tot_w": tot_w,
               "eval_m": C.EVAL_M, "k_cut_base": base["k"], "h_base": base["h"],
               "sil_base": base["sil"], "grid": rows,
               "n_pat_reported": r["n_pattern_clusters"], "n_cells": r["n_cells"],
               "novelty_rate": r["novelty_rate"], "ari_pattern_pool": r["ari_pattern_pool"],
               "f1_pool": r["f1_pool"], "true_patterns_per_intent":
                   RG.get(rid)["n_patterns_per_intent"],
               "abs": {}, "rel": {}}
        for S in ABS_FLOORS:
            p = pick(rows, float(S))
            rec["abs"][str(S)] = ({"k_cut": p["k"], "h": p["h"], "sil": p["sil"],
                                   "min_mass": p["min_mass"],
                                   "n_below_kappa": p["n_below_kappa"],
                                   "ndec": max(1, p["k"] - C.K_MAX_PATTERN_HEADROOM)}
                                  if p else None)
        for rho in REL_FLOORS:
            p = pick(rows, rho * tot_w)
            rec["rel"][str(rho)] = ({"k_cut": p["k"], "h": p["h"],
                                     "S": round(rho * tot_w, 2),
                                     "sil": p["sil"], "min_mass": p["min_mass"],
                                     "n_below_kappa": p["n_below_kappa"],
                                     "ndec": max(1, p["k"] - C.K_MAX_PATTERN_HEADROOM)}
                                    if p else None)
        out["regimes"].append(rec)
        ks = [rec["abs"][str(S)]["k_cut"] if rec["abs"][str(S)] else None for S in ABS_FLOORS]
        kr = [rec["rel"][str(q)]["k_cut"] if rec["rel"][str(q)] else None for q in REL_FLOORS]
        ntp = RG.get(rid)["n_patterns_per_intent"]
        under = sum(1 for k in ks[1:] if k is not None and k < ntp)
        print("[%6.1fs] %s n=%-5d u=%-4d k_cut_base=%d (consensus groups=%d, true=%d)\n"
              "        k_cut by ABS floor %s = %s\n"
              "        k_cut by REL floor %s = %s   under-split settings: %d/%d"
              % (time.time() - t0, rid, r["n"], CAPT["u"], base["k"],
                 r["n_pattern_clusters"], ntp, ABS_FLOORS, ks, REL_FLOORS, kr,
                 under, len(ks) - 1), flush=True)
    out["_wall_secs"] = round(time.time() - t0, 1)
    with io.open("platform/supexp-stageA.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    print("\nwrote platform/supexp-stageA.json  wall=%.1fs" % out["_wall_secs"], flush=True)


def stage_b(S):
    import capexp
    with io.open("platform/supexp-stageA.json", encoding="utf-8") as f:
        A = json.load(f)
    first = A["regimes"][0]
    if str(S) in first["abs"]:
        use_rel, key = False, str(S)
    elif str(S) in first["rel"]:
        use_rel, key = True, str(S)
    else:
        raise SystemExit("floor %r is in neither grid: abs=%s rel=%s"
                         % (S, A["abs_floors"], A["rel_floors"]))
    out = {"_note": "Stage B: full pipeline re-run with the cap implied by support floor S "
                    "(passed through the existing n_declared_patterns parameter). Compare "
                    "against capexp-results.json arms 'declared' and 'cap8'.",
           "S": S, "arms": []}
    t0 = time.time()
    for rec in A["regimes"]:
        ent = rec["rel"][key] if use_rel else rec["abs"][key]
        if not ent:
            print("  %s: floor %s admits nothing, skipped" % (rec["rid"], S), flush=True)
            continue
        ndec = ent["ndec"]
        kpred = ent["k_cut"]
        r = capexp.arm(rec["rid"], ndec, "sup%s" % S)
        r["S"] = S
        r["k_cut_predicted"] = kpred
        r["kmax_pat_from_ndec"] = max(2, min(CAP8, ndec + C.K_MAX_PATTERN_HEADROOM))
        out["arms"].append(r)
        ok = "n/a"   # consensus groups != dendrogram cut k; see stage_a fidelity note
        print("[%6.1fs] %s ndec=%d cap=%d n_pat=%s(pred %d %s) n_cells=%d nov=%s ari_p=%s "
              "f1=%s topk=%s G=%s"
              % (time.time() - t0, rec["rid"], ndec, r["kmax_pat"], r["n_pattern_clusters"],
                 kpred, ok, r["n_cells"],
                 ("%.4f" % r["novelty_rate"]) if r["novelty_rate"] is not None else "NA",
                 ("%.4f" % r["ari_pattern_pool"]) if r["ari_pattern_pool"] is not None else "NA",
                 r["f1_pool"], r["topk15_precision"], r["mean_G"]), flush=True)
    out["_wall_secs"] = round(time.time() - t0, 1)
    p = "platform/supexp-stageB-S%s.json" % S
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    print("\nwrote %s  wall=%.1fs" % (p, out["_wall_secs"]), flush=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "A"
    if mode == "A":
        stage_a()
    elif mode == "B":
        stage_b(sys.argv[2] if len(sys.argv) > 2 else "30")
    else:
        raise SystemExit("mode must be A or B")


if __name__ == "__main__":
    main()
