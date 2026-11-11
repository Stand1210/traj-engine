# -*- coding: utf-8 -*-
"""asymexp -- measure the OVER/UNDER-split asymmetry instead of quoting a code comment.

Why
---
The user asked: "so should the business write pattern_count too HIGH rather than too LOW?"
Every answer given so far rests on a *comment* in kernel/cluster.py:468-472 ("over-splitting a
workflow is cheap ... under-splitting is not recoverable anywhere downstream"). A comment is not
evidence, and capexp just showed the "cheap" half is only approximately true: cap 8 (more
over-splitting) costs a mean -0.024 f1 over the 8 clean regimes, +42% cells, and breaks R3's
novelty_rate gate. So the asymmetry needs measuring on BOTH sides.

capexp-results.json already supplies cap 5 and cap 8. This script fills in the missing points,
giving a complete curve at cap in {2, 3, 4, 5, 6, 8} against a true pattern count of 3 on all
eight regimes (reports/<rid>/metrics.json -> clustering.n_true_patterns).

    cap < 3  -> UNDER-split  (the direction the comment calls unrecoverable)
    cap = 3  -> exactly at truth, zero headroom
    cap >= 5 -> OVER-split   (the direction the comment calls cheap)

How the cap is set with zero kernel change
------------------------------------------
cluster.py:794-795   n_dec = n_declared_patterns or K_MAX_PATTERN_ABS
                     kmax_pat = max(2, min(K_MAX_PATTERN_ABS, n_dec + K_MAX_PATTERN_HEADROOM))
so n_declared_patterns = cap - 2 selects the cap. n_dec must be TRUTHY or it falls back to 8,
which is why cap 2 is reached with n_declared_patterns = -1 (min(8, 1) = 1 -> max(2, 1) = 2)
rather than 0. Ugly, but it is the existing formal parameter and touches no kernel line; the
platform would never pass a negative value -- cap 2 exists here only to measure the cliff.

Run (one process per cap; they are independent, 8 cores available):
    python -u platform/asymexp.py 2
    python -u platform/asymexp.py 3
Writes platform/asymexp-cap<CAP>.json
"""
import io, json, os, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "platform"))
from kernel import cluster as C
import bench.regime as RG

RIDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]


def ndec_for(cap):
    """n_declared_patterns value that yields kmax_pat == cap, or None if unreachable."""
    for nd in range(-4, 12):
        n_dec = nd or C.K_MAX_PATTERN_ABS
        if max(2, min(C.K_MAX_PATTERN_ABS, n_dec + C.K_MAX_PATTERN_HEADROOM)) == cap:
            return nd
    return None


def main():
    cap = int(sys.argv[1])
    nd = ndec_for(cap)
    if nd is None:
        raise SystemExit("cap %d unreachable through n_declared_patterns" % cap)
    import capexp
    out = {"cap": cap, "n_declared_patterns": nd,
           "_note": "asymexp arm cap=%d (n_declared_patterns=%d). Compare against "
                    "capexp-results.json arms 'declared' (cap 5) and 'cap8'." % (cap, nd),
           "arms": []}
    t0 = time.time()
    for rid in RIDS:
        t = time.time()
        r = capexp.arm(rid, nd, "cap%d" % cap)
        r["cap"] = cap
        r["n_true_patterns"] = json.load(io.open(
            "reports/%s/metrics.json" % rid, encoding="utf-8"))["clustering"]["n_true_patterns"]
        r["split_verdict"] = ("UNDER" if r["n_pattern_clusters"] < r["n_true_patterns"]
                              else ("EXACT" if r["n_pattern_clusters"] == r["n_true_patterns"]
                                    else "OVER+%d" % (r["n_pattern_clusters"]
                                                      - r["n_true_patterns"])))
        out["arms"].append(r)
        print("[%6.1fs] cap=%d %s ndec=%-3d n_pat=%s/%d %-7s n_cells=%-3d nov=%-8s "
              "ari_p=%-7s f1=%-8s topk=%-6s G=%s"
              % (time.time() - t0, cap, rid, nd, r["n_pattern_clusters"], r["n_true_patterns"],
                 r["split_verdict"], r["n_cells"], ("%.4f" % r["novelty_rate"]),
                 ("%.4f" % r["ari_pattern_pool"]) if r["n_pattern_clusters"] else "NA",
                 r["f1_pool"], r["topk15_precision"], r["mean_G"]), flush=True)
    out["_wall_secs"] = round(time.time() - t0, 1)
    p = "platform/asymexp-cap%d.json" % cap
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    print("\nwrote %s  wall=%.1fs" % (p, out["_wall_secs"]), flush=True)


if __name__ == "__main__":
    main()
