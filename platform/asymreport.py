# -*- coding: utf-8 -*-
"""asymreport -- assemble the complete cap curve {2,3,4,5,6,8} and settle the asymmetry claim.

Inputs (all produced by harnesses under platform/, all read-only):
    capexp-results.json         arms 'declared' (cap 5) and 'cap8'
    asymexp-cap{2,3,4,6}.json   the four missing points
    reports/<rid>/metrics.json  the published gate thresholds and n_true_patterns
    supexp-stageA.json          the rejected support-floor alternative (if present)

kernel/cluster.py:468-472 asserts an asymmetry ("over-splitting a workflow is cheap ...
under-splitting is not recoverable anywhere downstream"). That assertion has never been
measured. This report measures it, per metric, and says plainly where it holds and where it
does not -- including where it is WRONG.

Run:  python -u platform/asymreport.py
"""
import io, json, os, re, sys

RIDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
CAPS = [2, 3, 4, 5, 6, 8]
GE = re.compile(r"[-+]?\d*\.?\d+")
OBS = (("ari_pattern", "ari_pattern_pool", "ge"), ("ari_intent", "ari_intent_pool", "ge"),
       ("novelty_rate", "novelty_rate", "band"), ("f1", "f1_pool", "ge"),
       ("fpr", "fpr_pool", "le"), ("operator_stream_precision", "topk15_precision", "ge"))

_MC = {}


def metrics(rid):
    if rid not in _MC:
        _MC[rid] = json.load(io.open("reports/%s/metrics.json" % rid, encoding="utf-8"))
    return _MC[rid]


def thr(rid, name):
    g = (metrics(rid).get("gates") or {}).get(name)
    return [float(x) for x in GE.findall(g["want"])] if g and "want" in g else []


def load():
    arms = {}
    cap = json.load(io.open("platform/capexp-results.json", encoding="utf-8"))
    for a in cap["arms"]:
        arms[(a["rid"], 5 if a["arm"] == "declared" else 8)] = a
    for c in (2, 3, 4, 6):
        p = "platform/asymexp-cap%d.json" % c
        if not os.path.exists(p):
            continue
        for a in json.load(io.open(p, encoding="utf-8"))["arms"]:
            arms[(a["rid"], c)] = a
    return arms


def gate_check(rid, a):
    bad = []
    for gname, key, kind in OBS:
        t = thr(rid, gname)
        v = a.get(key)
        if not t or v is None:
            continue
        ok = (v >= t[0]) if kind == "ge" else ((v <= t[0]) if kind == "le"
                                               else (t[0] <= v <= t[1]))
        if not ok:
            bad.append("%s=%.4g%s%s" % (gname, v, ">=" if kind == "ge"
                                        else ("<=" if kind == "le" else " in"),
                                        ("%.3g" % t[0]) if kind != "band"
                                        else "[%.3g,%.3g]" % (t[0], t[1])))
    return bad


def main():
    arms = load()
    have = sorted(set(c for (_r, c) in arms))
    print("caps present: %s" % have)
    missing = [c for c in CAPS if c not in have]
    if missing:
        print("!! still missing caps %s -- table below is partial" % missing)

    for key, label, nd in (("n_pattern_clusters", "n_pattern_clusters (true = 3 on all regimes)", 0),
                           ("ari_pattern_pool", "ari_pattern_pool", 4),
                           ("f1_pool", "f1_pool", 5),
                           ("novelty_rate", "novelty_rate", 4),
                           ("n_cells", "n_cells", 0),
                           ("topk15_precision", "topk15_precision", 3),
                           ("mean_G", "mean_G", 5)):
        print()
        print("=" * 96)
        print("%s   [cap ->]" % label)
        print("=" * 96)
        print("%-4s %s" % ("rid", "".join("%13d" % c for c in have)))
        for rid in RIDS:
            row = []
            for c in have:
                a = arms.get((rid, c))
                v = a.get(key) if a else None
                row.append("%13s" % (("-" if v is None else
                                      (("%d" % v) if nd == 0 else ("%%.%df" % nd) % v))))
            ntp = metrics(rid)["clustering"]["n_true_patterns"]
            tag = ""
            if key == "n_pattern_clusters":
                tag = "   (true %d)" % ntp
            print("%-4s %s%s" % (rid, "".join(row), tag))
        # per-cap mean / break count
        vals = [[arms[(rid, c)][key] for rid in RIDS if (rid, c) in arms
                 and arms[(rid, c)].get(key) is not None] for c in have]
        print("%-4s %s" % ("mean", "".join("%13s" % (("%.5f" % (sum(v) / len(v))) if v else "-")
                                           for v in vals)))

    print()
    print("=" * 96)
    print("GATE BREAKS per cap (6 observable gates x 8 regimes = 48 slots max)")
    print("=" * 96)
    print("%-6s %-14s %-14s %s" % ("cap", "breaks/slots", "mean f1", "detail"))
    for c in have:
        nb, ns, det = 0, 0, []
        for rid in RIDS:
            a = arms.get((rid, c))
            if not a:
                continue
            bad = gate_check(rid, a)
            ns += sum(1 for g, _k, _o in OBS if thr(rid, g))
            nb += len(bad)
            if bad:
                det.append("%s: %s" % (rid, ", ".join(bad)))
        f1s = [arms[(rid, c)]["f1_pool"] for rid in RIDS if (rid, c) in arms]
        print("%-6d %-14s %-14s %s" % (c, "%d / %d" % (nb, ns),
                                       ("%.5f" % (sum(f1s) / len(f1s))) if f1s else "-",
                                       " | ".join(det) if det else "none"))

    print()
    print("=" * 96)
    print("UNDER-SPLIT vs OVER-SPLIT census (true pattern count = 3 on every regime)")
    print("=" * 96)
    print("%-6s %-26s %-26s %s" % ("cap", "n_pat census", "mean ari_pattern", "mean f1"))
    for c in have:
        cen = {}
        ap, f1 = [], []
        for rid in RIDS:
            a = arms.get((rid, c))
            if not a:
                continue
            ntp = metrics(rid)["clustering"]["n_true_patterns"]
            v = "UNDER" if a["n_pattern_clusters"] < ntp else (
                "EXACT" if a["n_pattern_clusters"] == ntp else "OVER")
            cen[v] = cen.get(v, 0) + 1
            if a["ari_pattern_pool"] is not None:
                ap.append(a["ari_pattern_pool"])
            f1.append(a["f1_pool"])
        print("%-6d %-26s %-26s %s"
              % (c, " ".join("%s=%d" % kv for kv in sorted(cen.items())),
                 "%.4f" % (sum(ap) / len(ap)) if ap else "-",
                 "%.5f" % (sum(f1) / len(f1)) if f1 else "-"))

    p = "platform/supexp-stageA.json"
    if os.path.exists(p):
        S = json.load(io.open(p, encoding="utf-8"))
        print()
        print("=" * 96)
        print("REJECTED ALTERNATIVE: data-driven support floor on pattern-cluster mass")
        print("=" * 96)
        print("%-4s %-6s %-8s | %-34s | %s"
              % ("rid", "u", "k_cut@0", "k_cut by ABS floor %s" % S["abs_floors"],
                 "k_cut by REL floor %s" % S["rel_floors"]))
        for rec in S["regimes"]:
            ks = [rec["abs"][str(x)]["k_cut"] if rec["abs"][str(x)] else None
                  for x in S["abs_floors"]]
            kr = [rec["rel"][str(x)]["k_cut"] if rec["rel"][str(x)] else None
                  for x in S["rel_floors"]]
            print("%-4s %-6d %-8d | %-34s | %s"
                  % (rec["rid"], rec["u"], rec["k_cut_base"], ks, kr))
        print("true pattern count is 3 on every regime, so any entry < 3 is UNDER-SPLITTING,")
        print("the direction cluster.py:468-472 calls unrecoverable.")


if __name__ == "__main__":
    main()
