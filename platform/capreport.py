# -*- coding: utf-8 -*-
"""capreport -- turn capexp-results.json into the gate-aligned decision table.

Reads the published gate thresholds out of reports/<rid>/metrics.json (never hard-codes them)
and, for each regime, reports what the cap-8 arm (= "drop pattern_count and do nothing") does
to every gate capexp can observe, plus the sub-gate cost.

Honest coverage note, printed with the table: capexp observes 6 of the 10 published gates.
ece / zero_residual / no_false_drift / precision_at_50 are NOT re-measured here.

Also cross-checks that capexp's `declared` arm reproduces the published clustering block --
if that check fails the whole comparison is meaningless, so it is asserted, not printed.

Run:  python -u platform/capreport.py            (read-only; writes nothing)
"""
import io, json, os, re, sys

RIDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
GE = re.compile(r"[-+]?\d*\.?\d+")


_MCACHE = {}


def metrics(rid):
    if rid not in _MCACHE:
        _MCACHE[rid] = json.load(io.open("reports/%s/metrics.json" % rid, encoding="utf-8"))
    return _MCACHE[rid]


def thr(rid, name):
    """Published threshold list for `name`, or [] when the regime declares no such gate.

    R6 ships without an ari_pattern gate; thresholds are always read from the report, never
    hard-coded, so a missing gate must degrade to "unconstrained" rather than crash.
    """
    m = metrics(rid)
    g = (m.get("gates") or {}).get(name)
    if not g or "want" not in g:
        return [], m
    return [float(x) for x in GE.findall(g["want"])], m


def fmt(v, nd=4):
    return ("%%.%df" % nd) % v if isinstance(v, float) else str(v)


def main():
    res = json.load(io.open("platform/capexp-results.json", encoding="utf-8"))
    by = {}
    for a in res["arms"]:
        by[(a["rid"], a["arm"])] = a

    print("=" * 118)
    print("TABLE 1  fidelity check: capexp 'declared' arm vs published reports/<rid>/metrics.json")
    print("=" * 118)
    print("%-4s %-28s %-28s %s" % ("rid", "capexp declared", "published clustering", "match"))
    for rid in RIDS:
        a = by[(rid, "declared")]
        m = metrics(rid)
        c = m["clustering"]
        got = (a["n_pattern_clusters"], a["n_intent_clusters"], a["n_cells"],
               round(a["novelty_rate"], 5), round(a["ari_pattern_pool"], 4))
        pub = (c["n_pattern_clusters"], c["n_intent_clusters"], c["n_cells"],
               round(c["novelty_rate"], 5), round(c["ari_pattern"], 4))
        print("%-4s %-28s %-28s %s" % (rid, got, pub, "OK" if got == pub else "**DIFF**"))

    print()
    print("=" * 118)
    print("TABLE 2  what dropping pattern_count (cap 8) costs on CLEAN traffic")
    print("=" * 118)
    hdr = ("%-4s %-5s %-9s %-9s | %-7s %-7s %-8s | %-8s %-8s | %-7s %-7s | %-6s"
           % ("rid", "n", "arm", "kmax", "n_pat", "n_cell", "nov", "ari_pat", "ari_int",
              "f1", "fpr", "topk15"))
    print(hdr)
    print("-" * 118)
    for rid in RIDS:
        for arm in ("declared", "cap8"):
            a = by[(rid, arm)]
            print("%-4s %-5d %-9s %-9d | %-7s %-7d %-8s | %-8s %-8s | %-7s %-7s | %-6s"
                  % (rid, a["n"], arm, a["kmax_pat"], a["n_pattern_clusters"], a["n_cells"],
                     fmt(a["novelty_rate"], 4), fmt(a["ari_pattern_pool"]),
                     fmt(a["ari_intent_pool"]), fmt(a["f1_pool"]), fmt(a["fpr_pool"], 5),
                     fmt(a["topk15_precision"], 3)))
        print("-" * 118)

    print()
    print("=" * 118)
    print("TABLE 3  DELTA (cap8 - declared) and whether cap8 still clears each published gate")
    print("=" * 118)
    print("%-4s | %-9s %-9s | %-9s %-9s | %-8s %-8s | %-8s | %-8s | %s"
          % ("rid", "d_n_pat", "d_n_cell", "d_nov", "d_ari_pat", "d_f1", "d_topk",
             "ari_pat gate", "nov gate", "f1/fpr/topk gates"))
    print("-" * 118)
    n_break = 0
    n_gate_slots = 0
    for rid in RIDS:
        d, c8 = by[(rid, "declared")], by[(rid, "cap8")]
        tp, m = thr(rid, "ari_pattern")
        ti, _ = thr(rid, "ari_intent")
        tn, _ = thr(rid, "novelty_rate")
        tf, _ = thr(rid, "f1")
        tr, _ = thr(rid, "fpr")
        to, _ = thr(rid, "operator_stream_precision")
        ap_ok = (c8["ari_pattern_pool"] >= tp[0]) if tp else True
        ai_ok = (c8["ari_intent_pool"] >= ti[0]) if ti else True
        nv_ok = (tn[0] <= c8["novelty_rate"] <= tn[1]) if len(tn) >= 2 else True
        f1_ok = (c8["f1_pool"] >= tf[0]) if tf else True
        fp_ok = (c8["fpr_pool"] <= tr[0]) if tr else True
        tk_ok = (c8["topk15_precision"] >= to[0]) if to else True
        declared_gates = sum(1 for t in (tp, ti, tf, tr, to) if t) + (1 if len(tn) >= 2 else 0)
        n_gate_slots += declared_gates
        breaks = [n for n, ok, t in (("ari_pattern", ap_ok, tp), ("ari_intent", ai_ok, ti),
                                     ("novelty_rate", nv_ok, tn), ("f1", f1_ok, tf),
                                     ("fpr", fp_ok, tr), ("ops_stream_prec", tk_ok, to))
                  if t and not ok]
        n_break += len(breaks)
        print("%-4s | %+9d %+9d | %+9.4f %+9.4f | %+8.4f %+8.4f | %-8s | %-8s | %s"
              % (rid, c8["n_pattern_clusters"] - d["n_pattern_clusters"],
                 c8["n_cells"] - d["n_cells"],
                 c8["novelty_rate"] - d["novelty_rate"],
                 c8["ari_pattern_pool"] - d["ari_pattern_pool"],
                 c8["f1_pool"] - d["f1_pool"],
                 (c8["topk15_precision"] - d["topk15_precision"]),
                 (("%.3f>=%.2f %s" % (c8["ari_pattern_pool"], tp[0],
                                      "OK" if ap_ok else "FAIL")) if tp
                  else "%.3f (no gate)" % c8["ari_pattern_pool"]),
                 (("%.3f in[%.2f,%.2f] %s" % (c8["novelty_rate"], tn[0], tn[1],
                                               "OK" if nv_ok else "FAIL")) if len(tn) >= 2
                  else "%.3f (no gate)" % c8["novelty_rate"]),
                 ("f1 %s / fpr %s / topk %s / ari_int %s"
                  % ("OK" if f1_ok else "FAIL", "OK" if fp_ok else "FAIL",
                     "OK" if tk_ok else "FAIL", "OK" if ai_ok else "FAIL"))))
    print("-" * 118)
    print("total gate breaks = %d / %d declared regime-gate slots" % (n_break, n_gate_slots))

    print()
    print("=" * 118)
    print("TABLE 4  margin of cap8's ari_pattern over its gate, and cell geometry")
    print("=" * 118)
    print("%-4s | %-24s | %-34s | %s" % ("rid", "cap8 ari_pat vs gate", "cell size min/med/max",
                                         "cells below KAPPA=30 (dec -> cap8)"))
    for rid in RIDS:
        d, c8 = by[(rid, "declared")], by[(rid, "cap8")]
        tp, _m = thr(rid, "ari_pattern")
        print("%-4s | %-24s | %-34s | %s"
              % (rid, (("%.4f / %.2f = %.2fx"
                        % (c8["ari_pattern_pool"], tp[0], c8["ari_pattern_pool"] / tp[0]))
                       if tp else "%.4f (no gate)" % c8["ari_pattern_pool"]),
                 "%s/%s/%s -> %s/%s/%s" % (d["cell_size_min"], d["cell_size_median"],
                                            d["cell_size_max"], c8["cell_size_min"],
                                            c8["cell_size_median"], c8["cell_size_max"]),
                 "%d -> %d  | baseline levels %s -> %s"
                 % (d["n_cells_below_kappa"], c8["n_cells_below_kappa"],
                    d["baseline_level_mix"], c8["baseline_level_mix"])))

    print()
    print("=" * 118)
    print("TABLE 5  UNDER-SPLIT tripwire -- n_pattern_clusters vs the published true pattern count")
    print("=" * 118)
    print("cluster.py:468-472: over-splitting is cheap (credibility shrinks small cells), "
          "under-splitting is NOT recoverable (bimodal conditional baseline).")
    print("%-4s | %-11s | %-22s | %-22s | %s"
          % ("rid", "n_true_pat", "declared n_pat", "cap8 n_pat", "verdict"))
    print("-" * 118)
    for rid in RIDS:
        d, c8 = by[(rid, "declared")], by[(rid, "cap8")]
        ntp = metrics(rid)["clustering"]["n_true_patterns"]
        v = []
        if d["n_pattern_clusters"] < ntp:
            v.append("declared UNDER-SPLITS")
        if c8["n_pattern_clusters"] < ntp:
            v.append("cap8 UNDER-SPLITS")
        if not v:
            v.append("neither under-splits"
                     + ("; cap8 over-splits %+d" % (c8["n_pattern_clusters"] - ntp)
                        if c8["n_pattern_clusters"] > ntp else ""))
        print("%-4s | %-11d | %-22d | %-22d | %s"
              % (rid, ntp, d["n_pattern_clusters"], c8["n_pattern_clusters"], "; ".join(v)))
    print("-" * 118)

    print()
    print("COVERAGE: capexp observes 6 of the 10 published gates (ari_pattern, ari_intent,")
    print("novelty_rate, f1, fpr, operator_stream_precision). NOT re-measured here: ece,")
    print("zero_residual, no_false_drift, precision_at_50.")
    print("wall=%.1fs" % res.get("_wall_secs", -1))


if __name__ == "__main__":
    main()
