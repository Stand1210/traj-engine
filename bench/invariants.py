"""Business-agnostic invariants. These must hold for *any* ontology, regime or tuning.

They are the reason the kernel can be called a standard engineering artefact rather than a
fit to one business: each one is a mathematical property of the scoring / clustering /
calibration machinery, asserted on synthetic inputs, with no ground truth and no labels.

Run: python -m bench.invariants
"""
import glob
import io
import math
import os
import random
import sys

from kernel import baseline as bl
from kernel import calib
from kernel import cluster
from kernel import detect
from kernel import meta
from kernel import score
from ontology.base import get_ontology, ONTOLOGY_IDS

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    return ok


def i_zero_residual():
    rng = random.Random(7)
    worst = 0.0
    art = {"cell": {}, "global": {}, "intent": {}, "global_profile": {"required": [], "terminal": None},
           "global_markov": {"trans": {}, "vocab": [], "n_seq": 0}}
    for _ in range(400):
        feats = {"trace_id": "t", "latency_total": rng.uniform(0.5, 200.0),
                 "tokens_total": rng.randint(100, 90000), "cost_total": rng.uniform(0.001, 2.0),
                 "retry_count": rng.randint(0, 4), "error_ratio": rng.random() * 0.4,
                 "loop_count": rng.randint(0, 5), "guard_hits": rng.randint(0, 2),
                 "traceable_number_ratio": rng.random(), "missing_field_ratio": rng.random(),
                 "n_spans": 8, "action_seq": ["a", "b"], "spans": [], "flags": {}}
        assign = {"cell": None, "novelty": rng.random() < 0.3}
        det = {"struct": {"missing_frac": rng.random(), "illegal_actions": (["x"] if rng.random() < 0.2 else []),
                          "unfinished": rng.choice([0.0, 0.35, 1.0]), "required": ["a"]},
               "conf": rng.uniform(0.4, 1.0)}
        r = score.score_one(feats, assign, det, art, get_ontology("ontA"))
        resid = abs(sum(r["contrib"].values()) - (r["S"] - 100.0 * r["G"]))
        worst = max(worst, resid)
    check("score.lmdi_zero_residual", worst < 1e-9, "max_residual=%.3e" % worst)


def i_perfect_score():
    art = {"cell": {}, "global": {}, "intent": {}, "global_profile": {"required": [], "terminal": None},
           "global_markov": {"trans": {}, "vocab": [], "n_seq": 0}}
    feats = {"trace_id": "t", "latency_total": 1.0, "tokens_total": 100, "cost_total": 0.001,
             "retry_count": 0, "error_ratio": 0.0, "loop_count": 0, "guard_hits": 0,
             "traceable_number_ratio": 1.0, "missing_field_ratio": 0.0, "n_spans": 4,
             "action_seq": ["a"], "spans": [], "flags": {}}
    r = score.score_one(feats, {"cell": None, "novelty": False},
                        {"struct": {"missing_frac": 0.0, "illegal_actions": [], "unfinished": 0.0,
                                    "required": ["a"]}, "conf": 1.0},
                        art, get_ontology("ontA"))
    check("score.perfect_is_100", abs(r["S"] - 100.0) < 1e-9 and r["grade_abs"] == "A",
          "S=%.6f G=%.3f" % (r["S"], r["G"]))


def i_single_dim_collapse():
    art = {"cell": {}, "global": {}, "intent": {}, "global_profile": {"required": [], "terminal": None},
           "global_markov": {"trans": {}, "vocab": [], "n_seq": 0}}
    base = {"trace_id": "t", "latency_total": 1.0, "tokens_total": 100, "cost_total": 0.001,
            "retry_count": 0, "error_ratio": 0.0, "loop_count": 0, "guard_hits": 0,
            "traceable_number_ratio": 1.0, "missing_field_ratio": 0.0, "n_spans": 4,
            "action_seq": ["a"], "spans": [], "flags": {}}
    det = {"struct": {"missing_frac": 0.0, "illegal_actions": [], "unfinished": 0.0,
                      "required": ["a"]}, "conf": 1.0}
    good = score.score_one(dict(base), {"cell": None, "novelty": False}, det, art, get_ontology("ontA"))
    bad = dict(base)
    bad["traceable_number_ratio"] = 0.0
    coll = score.score_one(bad, {"cell": None, "novelty": False}, det, art, get_ontology("ontA"))
    drop = 1.0 - coll["S"] / good["S"]
    # arithmetic averaging over the same weights would lose only 0.40*0.8 = 32%;
    # the conjunctive geometric aggregator must lose strictly more.
    check("score.single_dim_collapse_is_punitive", drop > 0.40,
          "drop=%.3f (arithmetic would be <=0.32)" % drop)


def i_gates_multiply():
    art = {"cell": {}, "global": {}, "intent": {}, "global_profile": {"required": [], "terminal": None},
           "global_markov": {"trans": {}, "vocab": [], "n_seq": 0}}
    feats = {"trace_id": "t", "latency_total": 1.0, "tokens_total": 100, "cost_total": 0.001,
             "retry_count": 0, "error_ratio": 0.0, "loop_count": 5, "guard_hits": 1,
             "traceable_number_ratio": 0.1, "missing_field_ratio": 0.0, "n_spans": 4,
             "action_seq": ["a"], "spans": [{"finish_reason": "length"}], "flags": {}}
    r = score.score_one(feats, {"cell": None, "novelty": True},
                        {"struct": {"missing_frac": 0.0, "illegal_actions": ["force_delete"],
                                    "unfinished": 1.0, "required": ["a"]}, "conf": 0.5},
                        art, get_ontology("ontA"))
    exp = 1.0
    for v in r["gates"].values():
        exp *= v
    check("score.gates_are_multiplicative", abs(r["G"] - exp) < 1e-12 and r["S"] < 5.0,
          "G=%.6f gates=%s S=%.3f" % (r["G"], sorted(r["gates"]), r["S"]))


def i_anchor_monotone():
    anch = {"ideal": 2.0, "good": 10.0, "warn": 60.0, "bad": 200.0}
    xs = [i * 0.5 for i in range(0, 801)]
    ys = [bl.anchor_score(anch, x, "higher_worse") for x in xs]
    ok = all(ys[i] >= ys[i + 1] - 1e-12 for i in range(len(ys) - 1))
    anch2 = {"ideal": 0.98, "good": 0.90, "warn": 0.60, "bad": 0.30}
    ys2 = [bl.anchor_score(anch2, i / 100.0, "lower_worse") for i in range(0, 101)]
    ok2 = all(ys2[i] <= ys2[i + 1] + 1e-12 for i in range(len(ys2) - 1))
    ends = (ys2[0], ys2[-1])
    check("baseline.anchor_score_monotone", ok and ok2 and ends == (0.0, 1.0),
          "higher_worse non-increasing=%s ; lower_worse non-decreasing=%s ends=%s"
          % (ok, ok2, ends))


def i_pooling_limits():
    ont = get_ontology("ontA")
    big = [{"cell": "cA", "intent": 0,
            "feats": {"latency_total": 10.0 + (i % 5), "tokens_total": 1000, "cost_total": 0.01,
                      "retry_count": 0, "error_ratio": 0.0, "loop_count": 0, "guard_hits": 0,
                      "traceable_number_ratio": 1.0, "missing_field_ratio": 0.0,
                      "n_spans": 5, "depth": 2, "branch_factor": 4.0,
                      "action_seq": ["a", "b", "c"]}} for i in range(4000)]
    small = [{"cell": "cB", "intent": 1,
              "feats": {"latency_total": 500.0, "tokens_total": 90000, "cost_total": 0.9,
                        "retry_count": 3, "error_ratio": 0.2, "loop_count": 2, "guard_hits": 1,
                        "traceable_number_ratio": 0.5, "missing_field_ratio": 0.3,
                        "n_spans": 5, "depth": 2, "branch_factor": 4.0,
                        "action_seq": ["a", "b", "c"]}}]
    art = bl.build(big + small, ont, "test")
    a_big = art["cell"]["cA"]["anchors"]["latency_total"]
    a_small = art["cell"]["cB"]["anchors"]["latency_total"]
    a_glob = None
    gvals = sorted([r["feats"]["latency_total"] for r in big + small])
    a_glob = {"ideal": bl.quantile(gvals, 0.10), "good": bl.quantile(gvals, 0.50),
              "warn": bl.quantile(gvals, 0.90), "bad": bl.quantile(gvals, 0.99)}
    own = sorted(r["feats"]["latency_total"] for r in big)
    own_anch = bl._separate(bl._anchors_from(own, "higher_worse"), "latency_total",
                            bl._moments(own)["mad"], "higher_worse")
    ok_big = all(abs(a_big[k] - own_anch[k]) < 0.15 for k in ("ideal", "good", "warn", "bad"))
    # n -> 0: the cell's own sample carries B -> 0 weight, so the first three anchors must
    # converge to the leave-one-out global reference. The far tail (bad) is still allowed
    # to be stretched by the cell's own single observation - documented behaviour.
    ok_small = all(abs(a_small[k] - a_glob[k]) < 0.35 for k in ("ideal", "good", "warn"))
    ok_mono = a_small["bad"] >= a_small["warn"] >= a_small["good"] >= a_small["ideal"]
    ok_cred = (abs(bl.credibility(0) - 0.0) < 1e-12 and abs(bl.credibility(30) - 0.5) < 1e-12
               and bl.credibility(10 ** 9) > 0.999999)
    check("baseline.pooling_limits", ok_big and ok_small and ok_mono and ok_cred,
          "B(n=0)=%.4f B(n=30)=%.4f B(n=1e9)=%.6f | cA(n=4000,B=%.4f) own-quantile dev<0.15=%s "
          "| cB(n=1,B=%.4f) anchors=%s vs LOO-global=%s head-converged=%s monotone=%s"
          % (bl.credibility(0), bl.credibility(30), bl.credibility(10 ** 9),
             art["cell"]["cA"]["B_cell"], ok_big, art["cell"]["cB"]["B_cell"],
             {k: round(v, 2) for k, v in a_small.items()},
             {k: round(v, 2) for k, v in a_glob.items()}, ok_small, ok_mono))
    assert ok_cred


def i_consensus_threshold_semantics():
    """The consensus dial must move novelty and nothing else.

    Two properties, and the superseded implementation violated both. (a) The partition is
    invariant: the model order is the median k over the bagged runs and the cut height is
    derived from it, so how many task classes exist cannot depend on a deployment dial - the
    old fixed-height cut let the threshold split 2 agreed classes into 4 and pushed intent ARI
    below the Bayes ceiling of the heavy-overlap regime. (b) The novelty rate is monotone
    non-decreasing in the threshold and responsive to it, which is what makes it a dial rather
    than a decoration. The fixture is two blobs plus a ramp of points placed at 0.20..0.80 of
    the way between them, so the bagged co-association margins span the swept range instead of
    all landing at 0 or 1 (three tight well separated blobs gave a flat 0.04 everywhere and
    the assertion passed vacuously).
    """
    rng = random.Random(11)
    dim, sep, sigma = 4, 2.0, 0.8
    ca = [0.0] * dim
    cb = [sep] * dim
    feats = []
    for i in range(40):
        feats.append({"trace_id": "A%d" % i, "action_seq": ["a", "b"],
                      "embedding": [v + rng.gauss(0, sigma) for v in ca]})
    for i in range(40):
        feats.append({"trace_id": "B%d" % i, "action_seq": ["a", "b", "c", "d"],
                      "embedding": [v + rng.gauss(0, sigma) for v in cb]})
    for j in range(60):
        t = 0.20 + 0.60 * (j % 9) / 8.0
        mid = [ca[d] * (1.0 - t) + cb[d] * t for d in range(dim)]
        feats.append({"trace_id": "b%d" % j, "action_seq": ["a", "b"],
                      "embedding": [v + rng.gauss(0, sigma) for v in mid]})
    ths = (0.05, 0.20, cluster.CONSENSUS_THRESHOLD, 0.55, 0.85)
    parts, novs, ks = [], [], []
    for th in ths:
        cluster.reset_cache()
        a, info = cluster.cluster_views(feats, threshold=th, seed=5, eval_m=len(feats),
                                        r_runs=5)
        parts.append(tuple(x["near_intent"] for x in a))
        novs.append(info["novelty_rate"])
        ks.append(info["n_intent_clusters"])
    ok_same = all(x == parts[0] for x in parts)
    ok_k = len(set(ks)) == 1
    ok_mono = all(novs[i] <= novs[i + 1] + 1e-12 for i in range(len(novs) - 1))
    ok_bite = novs[-1] > novs[0] + 1e-9
    ok_mid = 0.0 < novs[2] < 0.5
    check("cluster.consensus_threshold_semantics",
          ok_same and ok_k and ok_mono and ok_bite and ok_mid,
          "thresholds %s -> k=%s partition-identical=%s novelty=%s monotone=%s responsive=%s "
          "default-in-range=%s" % (list(ths), ks, ok_same, [round(v, 4) for v in novs],
                                   ok_mono, ok_bite, ok_mid))


def i_cluster_determinism():
    rng = random.Random(3)
    feats = [{"trace_id": "t%d" % i,
              "embedding": [rng.gauss(0, 1) + (3.0 if i % 2 else 0.0) for _ in range(6)],
              "action_seq": ["a", "b"] if i % 3 else ["a", "c", "d"]} for i in range(60)]
    cluster.reset_cache()
    a1, i1 = cluster.cluster_views(feats, seed=99, eval_m=60, r_runs=3)
    cluster.reset_cache()
    a2, i2 = cluster.cluster_views(feats, seed=99, eval_m=60, r_runs=3)
    same = all(x == y for x, y in zip(a1, a2)) and i1 == i2
    check("cluster.deterministic_same_seed", same, "identical=%s" % same)


def i_calibration_monotone():
    rng = random.Random(5)
    xs = [rng.random() for _ in range(600)]
    ys = [1 if rng.random() < (0.05 + 0.9 * x) else 0 for x in xs]
    ic = calib.IsotonicCalibrator().fit(xs, ys)
    grid = [i / 200.0 for i in range(201)]
    ps = ic.predict(grid)
    ok = all(ps[i] <= ps[i + 1] + 1e-12 for i in range(len(ps) - 1))
    e_in = calib.ece(ic.predict(xs), ys, bins=10)
    e_raw = calib.ece(xs, ys, bins=10)
    check("calib.isotonic_monotone_and_reduces_ece", ok and e_in <= e_raw + 1e-9,
          "monotone=%s ece_raw=%.4f ece_isotonic=%.4f" % (ok, e_raw, e_in))


def i_bh_fdr_under_null():
    rng = random.Random(13)
    rates = []
    for _ in range(30):
        m = 400
        keys = list(range(m))
        ps = [rng.random() for _ in range(m)]
        rej = detect.bh_fdr(keys, ps, alpha=0.05)
        rates.append(len(rej) / float(m))
    worst = max(rates)
    check("detect.bh_controls_false_discovery_under_null", worst <= 0.10,
          "max rejection rate on 30x400 uniform p-values = %.4f (alpha=0.05)" % worst)


def i_point_adjust_banned():
    try:
        meta.point_adjust_f1([0, 1], [0, 1])
        ok = False
        msg = "did not raise"
    except NotImplementedError:
        ok = True
        msg = "raises NotImplementedError"
    check("meta.point_adjust_is_banned", ok, msg)


def i_no_hardcoded_actions():
    names = set()
    for oid in ONTOLOGY_IDS:
        o = get_ontology(oid)
        names.update(o["actions"])
        names.update(o["forbidden_actions"])
        names.update(o.get("optional_steps") or [])
        for v in o["required_steps"].values():
            names.update(v)
    names.discard("")
    hits = []
    for path in sorted(glob.glob(os.path.join(ROOT, "kernel", "*.py"))):
        src = io.open(path, encoding="utf-8").read()
        for a in sorted(names):
            if len(a) < 4:
                continue
            if ('"%s"' % a) in src or ("'%s'" % a) in src:
                hits.append("%s:%s" % (os.path.basename(path), a))
    check("kernel.no_hardcoded_ontology_actions", not hits, "hits=%s" % (hits or "none"))


def main():
    for fn in (i_zero_residual, i_perfect_score, i_single_dim_collapse, i_gates_multiply,
               i_anchor_monotone, i_pooling_limits, i_consensus_threshold_semantics,
               i_cluster_determinism, i_calibration_monotone, i_bh_fdr_under_null,
               i_point_adjust_banned, i_no_hardcoded_actions):
        try:
            fn()
        except Exception as exc:
            check(fn.__name__, False, "EXCEPTION %s: %s" % (type(exc).__name__, exc))
    bad = [r for r in RESULTS if not r["ok"]]
    for r in RESULTS:
        print("[%s] %s :: %s" % ("PASS" if r["ok"] else "FAIL", r["name"], r["detail"]))
    print("invariants: %d/%d passed" % (len(RESULTS) - len(bad), len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())