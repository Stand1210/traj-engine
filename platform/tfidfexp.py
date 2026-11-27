"""tfidfexp -- A/B: current pattern-view profile distance vs methodology 5.3 route A.

EMBEDDING_REMEDIATION_PLAN.md phase E3 upgrades the execution (pattern) view to route A:
stable span_key tokens (agent::operation::tool), 1/2/3-gram sublinear TF-IDF, L2 norm,
cosine distance, average linkage, top n-gram explanations, structural fingerprint. The
shipped kernel has a close relative (saliency-weighted 1/2-gram count profile -> cosine ->
UPGMA, kernel/cluster.py:159-201) whose saliency weighting must PROVE its value in an A/B
before it may stay (plan section 2.2). This script is that A/B; it touches nothing in
kernel/ or bench/, so code_hash and the committed reports stay valid.

Arms (all share ONE intent view, captured from the `current` run; only the pattern view
differs). The three tfidf variants isolate WHERE the route-A delta comes from:
  current       shipped kernel path: action tokens, saliency profile distance
  tfidf-act      action tokens, 1/2/3-gram sublinear TF-IDF, no saliency
  tfidf-act+sal  action tokens, TF-IDF + saliency multiplier on tf'
  tfidf-kind     kind::action tokens, TF-IDF, no saliency
  tfidf-kind+sal kind::action tokens, TF-IDF + saliency
  tfidf-full     kind::action::tool tokens (full span_key), TF-IDF, no saliency
  tfidf-full+sal full span_key tokens, TF-IDF + saliency

Full factorial: token recipe {action, kind::action, kind::action::tool} x saliency
{off, on}, against the shipped profile baseline.

First-run finding that motivated the variable isolation (R6): tfidf-full shattered 3
declared workflows into 17 clusters (ARI 0.35). Root cause: the bench generator samples
tool_name i.i.d. per span from tool_catalog, so two traces of the same workflow share
almost no span_key n-grams, cosine distances saturate near 1.0 above the cut grid (max
0.85), and the k-closest-to-2 fallback fires. Whether the tool component, the weighting,
or the 3-grams are to blame is what the arm matrix answers.

Per regime and arm: cluster counts, cut height/silhouette, novelty, ARI vs ground truth
(assignable pool, as runner.evaluate), downstream F1/FPR/top-k precision/mean G, wall time.

RNG note: tfidf arms draw pattern jitter from Random("<seed>:<mode>"), so consensus
frequencies are not bit-identical to a fused kernel build; the difference is jitter noise
only and both sides face it equally.

Run:  python -u platform/tfidfexp.py            (all 8 regimes)
      python -u platform/tfidfexp.py R3,R8      (subset; results merge into the same file)
Results merge into platform/tfidfexp-results.json after every regime (resumable).
"""
import hashlib
import io
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.getcwd())
from kernel import ingest, features as FEAT, cluster, baseline as BL, binding as BD
from kernel import detect as DET, score, drift, meta
import bench.regime as RG
import bench.runner as RUN
from ontology.base import get_ontology

RIDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
TOPK = 15
RESULTS = os.path.join("platform", "tfidfexp-results.json")
NGRAM_MAX = 3
SIG_WEIGHT = cluster.SIG_WEIGHT


# ---- route A vectorizer (candidate kernel implementation, measured here first) ----------

def span_key(span):
    """`agent::operation::tool` with explicit degradation, never fabrication.

    `agent`/`operation` are optional contract fields; without them the span's structural
    role (`kind`) and ontology action token stand in. A missing tool identity is the
    literal "-", so absence stays visible in the vocabulary instead of being invented.
    """
    agent = span.get("agent") or span.get("kind") or "?"
    operation = span.get("operation") or span.get("action") or "?"
    tool = span.get("tool_name") or "-"
    return "%s::%s::%s" % (agent, operation, tool)


def span_key_seq(feat):
    return [span_key(s) for s in feat["spans"] if s.get("action")]


def _ngrams(seq, nmax=NGRAM_MAX):
    length = len(seq)
    for n in range(1, nmax + 1):
        for i in range(length - n + 1):
            yield ">".join(seq[i:i + n])


def fit_idf(docs, nmax=NGRAM_MAX, min_df=1):
    df = {}
    for doc in docs:
        for gram in set(_ngrams(doc, nmax)):
            df[gram] = df.get(gram, 0) + 1
    total = len(docs)
    return {gram: math.log((1.0 + total) / (1.0 + count)) + 1.0
            for gram, count in df.items() if count >= min_df}


def tfidf_vec(seq, idf, salient=None, nmax=NGRAM_MAX):
    tf = {}
    for gram in _ngrams(seq, nmax):
        tf[gram] = tf.get(gram, 0) + 1
    vec = {}
    for gram, count in tf.items():
        weight = (1.0 + math.log(count)) * idf.get(gram, 0.0)
        if salient:
            toks = gram.split(">")
            boost = 1.0
            for tok in toks:
                boost *= SIG_WEIGHT if tok in salient else 1.0
            weight *= boost ** (1.0 / len(toks))
        if weight:
            vec[gram] = weight
    norm = math.sqrt(sum(x * x for x in vec.values()))
    if norm:
        vec = {gram: x / norm for gram, x in vec.items()}
    return vec


def cos_dist(a, b):
    if len(a) > len(b):
        a, b = b, a
    dot = sum(x * b.get(gram, 0.0) for gram, x in a.items())
    return max(0.0, min(1.0, 1.0 - dot))


def structural_fingerprint(token_mode, saliency, min_df=1):
    config = {
        "span_key_recipe": {
            "action": "action:v1(action)",
            "kindact": "span_key:v1-no-tool(agent|kind::operation|action)",
            "full": "span_key:v1(agent|kind::operation|action::tool_name|-)",
        }[token_mode],
        "ngram_max": NGRAM_MAX,
        "tf": "sublinear:1+ln(tf)",
        "idf": "smoothed:ln((1+N)/(1+df))+1",
        "min_df": min_df,
        "norm": "l2",
        "distance": "cosine",
        "saliency_weight": SIG_WEIGHT if saliency else None,
        "saliency_min_prev": cluster.SIG_MIN_PREV if saliency else None,
        "clustering": "upgma",
        "cut_selection": "silhouette_sweep",
    }
    blob = json.dumps(config, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


# ---- pattern view with a pluggable distance (extracted shape of kernel cluster_views) ---

def kindact_key(span):
    return "%s::%s" % (span.get("agent") or span.get("kind") or "?",
                       span.get("operation") or span.get("action") or "?")


def skeleton_of(feat, mode):
    if mode.startswith("tfidf-act"):
        return cluster.collapse(feat["action_seq"])
    if mode.startswith("tfidf-kind"):
        return cluster.collapse([kindact_key(s) for s in feat["spans"] if s.get("action")])
    return cluster.collapse(span_key_seq(feat))


def token_mode_of(mode):
    if mode.startswith("tfidf-act"):
        return "action"
    if mode.startswith("tfidf-kind"):
        return "kindact"
    return "full"


def pattern_view(feats, eval_idx, seed, threshold, r_runs, n_declared, mode):
    rng = random.Random("%s:%s" % (seed, mode))
    skels = [skeleton_of(feats[i], mode) for i in eval_idx]
    sig, _nseq = cluster.action_saliency(skels)
    sig_tok = tuple(sorted(sig))
    uniq, urep = [], {}
    for sq in skels:
        key = tuple(sq)
        if key not in urep:
            urep[key] = len(uniq)
            uniq.append(key)
    u = len(uniq)

    salient = sig if "+sal" in mode else None
    min_df = 2 if "+df2" in mode else 1
    if mode == "current":
        dist = lambda a, b: cluster.seq_dist(list(uniq[a]), list(uniq[b]), sig, sig_tok)
    else:
        idf = fit_idf([list(s) for s in uniq], min_df=min_df)
        vecs = [tfidf_vec(list(s), idf, salient) for s in uniq]
        dist = lambda a, b: cos_dist(vecs[a], vecs[b])

    udm = [[0.0] * u for _ in range(u)]
    flat = []
    for a in range(u):
        for b in range(a + 1, u):
            v = dist(a, b)
            udm[a][b] = udm[b][a] = v
            flat.append(v)
    flat.sort()
    dm_stats = {
        "dm_max": round(flat[-1], 4) if flat else None,
        "dm_p95": round(flat[int(0.95 * (len(flat) - 1))], 4) if flat else None,
        "dm_frac_above_grid": round(
            sum(1 for v in flat if v > max(cluster.HEIGHT_GRID)) / float(len(flat)), 4)
        if flat else None,
    }
    uw = [0] * u
    for sq in skels:
        uw[urep[tuple(sq)]] += 1
    n_dec = n_declared or cluster.K_MAX_PATTERN_ABS
    kmax_pat = max(2, min(cluster.K_MAX_PATTERN_ABS,
                          n_dec + cluster.K_MAX_PATTERN_HEADROOM))
    h_pat, sil_pat, curve = cluster.select_cut_height(udm, u, k_max=kmax_pat, weights=uw)
    runs_p = []
    for _ in range(r_runs):
        jdm = [[0.0] * u for _ in range(u)]
        for a in range(u):
            for b in range(a + 1, u):
                v = udm[a][b] + rng.gauss(0.0, cluster.JITTER_SEQ)
                v = 0.0 if v < 0.0 else v
                jdm[a][b] = jdm[b][a] = v
        lab_u = cluster.avg_link_cut(jdm, u, h_pat)
        runs_p.append([lab_u.get(urep[tuple(sq)], 0) for sq in skels])
    m = len(eval_idx)
    cid_p, cons_p, groups_p = cluster._consensus(runs_p, m, threshold)

    def pair_dist(sx, sy):
        if mode == "current":
            return cluster.seq_dist(sx, sy, sig, sig_tok)
        return cos_dist(tfidf_vec(sx, idf, salient), tfidf_vec(sy, idf, salient))

    med_p = {}
    for c, mem in groups_p.items():
        best, bx = None, None
        for x in mem:
            tot = sum(pair_dist(skels[x], skels[y]) for y in mem) / float(len(mem))
            if best is None or tot < best:
                best, bx = tot, x
        med_p[c] = skels[bx]
    single_p = {c for c, mem in groups_p.items() if len(mem) == 1}
    memcons_p = {c: sum(cons_p[x] for x in mem) / float(len(mem))
                 for c, mem in groups_p.items()}

    top_ngrams = {}
    if mode != "current":
        for c, mem in groups_p.items():
            acc = {}
            for x in mem:
                for gram, w in tfidf_vec(skels[x], idf, salient).items():
                    acc[gram] = acc.get(gram, 0.0) + w
            ranked = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            top_ngrams[c] = [gram.replace(">", "->") for gram, _w in ranked]

    result = {
        "groups_p": groups_p, "cons_p": cons_p, "med_p": med_p, "single_p": single_p,
        "memcons_p": memcons_p, "h_pat": h_pat, "sil_pat": sil_pat, "curve": curve,
        "n_unique_seq": u, "n_salient": len(sig), "skels": skels,
        "top_ngrams": top_ngrams, "dm_stats": dm_stats,
        "fingerprint": None if mode == "current"
        else structural_fingerprint(token_mode_of(mode), salient is not None, min_df),
    }
    if mode != "current":
        result["_idf"] = idf
        result["_salient"] = salient
    return result


def capture_intent(feats, seed, n_declared):
    """One full cluster_views call -> (assigns_current, cinfo_current, intent_ctx)."""
    captured = {}

    def capture_return(frame, event, arg):
        if event == "return":
            captured.update(frame.f_locals)
        return capture_return

    def capture_call(frame, event, arg):
        if (event == "call" and frame.f_code.co_name == "cluster_views"
                and frame.f_code.co_filename.replace("\\", "/").endswith("kernel/cluster.py")):
            return capture_return
        return None

    cluster.reset_cache()
    sys.settrace(capture_call)
    try:
        assigns, cinfo = cluster.cluster_views(
            feats, threshold=cluster.CONSENSUS_THRESHOLD, seed=seed,
            n_declared_patterns=n_declared)
    finally:
        sys.settrace(None)
    ctx = {key: captured[key] for key in (
        "cents_i", "cons_i", "single_i", "memcons_i", "cl", "cent_list",
        "sigma2", "geo_cut", "eval_idx", "flag_rate")}
    return assigns, cinfo, ctx


def combine_assigns(feats, intent_ctx, pat, threshold, mode):
    """Rebuild the cluster_views output rows with the intent ctx and a new pattern view."""
    eval_idx = intent_ctx["eval_idx"]
    pos_of = {t: p for p, t in enumerate(eval_idx)}
    cons_i, memcons_i = intent_ctx["cons_i"], intent_ctx["memcons_i"]
    cents_i, cl = intent_ctx["cents_i"], intent_ctx["cl"]
    single_i = intent_ctx["single_i"]
    cent_list, sigma2, geo_cut = (intent_ctx["cent_list"], intent_ctx["sigma2"],
                                  intent_ctx["geo_cut"])
    cons_p, memcons_p = pat["cons_p"], pat["memcons_p"]
    med_p, pl = pat["med_p"], sorted(pat["med_p"])
    skel_by_idx = dict(zip(eval_idx, pat["skels"]))
    sig_cache = {}

    def pat_dist(sx, sy):
        if mode == "current":
            return cluster.seq_dist(sx, sy)
        key = id(sx)
        # medoids and skeletons are plain lists; recompute through the arm's own distance
        # via pattern_view's closure is unavailable here, so cache vectors per object id.
        return _pat_dist_cached(sx, sy, pat, sig_cache)

    out = []
    for i in range(len(feats)):
        e = feats[i]["embedding"]
        ci = min(cl, key=lambda c: cluster.euclid(e, cents_i[c])) if cl else -1
        sk = skel_by_idx.get(i)
        if sk is None:
            sk = skeleton_of(feats[i], mode)
        cp = min(pl, key=lambda c: pat_dist(sk, med_p[c])) if pl else -1
        p = pos_of.get(i)
        vi = cons_i[p] if p is not None else memcons_i.get(ci, 0.0)
        vp = cons_p[p] if p is not None else memcons_p.get(cp, 0.0)
        geo = cluster.post_margin(e, cent_list, sigma2)
        nov = ((ci in single_i) or (cp in pat["single_p"]) or (vi < threshold)
               or (vp < threshold) or (geo_cut is not None and geo <= geo_cut))
        out.append({
            "trace_id": feats[i]["trace_id"],
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


def _pat_dist_cached(sx, sy, pat, cache):
    idf = pat["_idf"]
    salient = pat["_salient"]
    for s in (sx, sy):
        key = tuple(s)
        if key not in cache:
            cache[key] = tfidf_vec(list(s), idf, salient)
    return cos_dist(cache[tuple(sx)], cache[tuple(sy)])


# ---- downstream evaluation (same shape as capexp.arm) ------------------------------------

def downstream(feats, assigns, ont, rid, tag):
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
    return score.score_all(feats, assigns, stage, art, ont,
                           cold_start=len(feats) < RG.COLD_START_MIN_TRACES,
                           drift_map=dict((x, True) for x in set(dr.get("suspects") or [])),
                           anchor_version="anchor-%s-%s" % (rid, tag), model_version=tag)


def evaluate_arm(rid, tag, feats, assigns, cinfo, gt, secs_cluster, secs_down, extra=None):
    tids = [f["trace_id"] for f in feats]
    AS = dict((a["trace_id"], a) for a in assigns)
    pool = [t for t in tids if not AS[t]["novelty"]]
    ari_p = meta.ari([AS[t]["pattern_cluster"] for t in pool],
                     [gt[t]["pattern_id"] for t in pool]) if pool else None
    ari_i = meta.ari([AS[t]["intent_cluster"] for t in pool],
                     [gt[t]["intent_id"] for t in pool]) if pool else None
    y = dict((t, bool(gt[t]["is_anomaly"])) for t in tids if t in gt)
    R = dict((r["trace_id"], r) for r in
             downstream(feats, assigns, get_ontology(RG.get(rid)["ontology_id"]), rid, tag))
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
    row = {
        "rid": rid, "arm": tag, "n": len(tids),
        "n_intent_clusters": cinfo.get("n_intent_clusters"),
        "n_pattern_clusters": cinfo.get("n_pattern_clusters"),
        "novelty_rate": cinfo.get("novelty_rate"),
        "ari_pattern_pool": ari_p, "ari_intent_pool": ari_i,
        "fpr_pool": round(fp / float(len(nm)), 5) if nm else None,
        "recall_pool": round(rec, 5) if rec is not None else None,
        "f1_pool": round(f1, 5),
        "topk%d_precision" % TOPK: round(tk_prec, 5) if tk_prec is not None else None,
        "mean_G": round(sum(R[t]["G"] for t in tids) / float(len(tids)), 5),
        "secs_cluster": round(secs_cluster, 1),
        "secs_downstream": round(secs_down, 1),
    }
    if extra:
        row.update(extra)
    return row


ALL_ARMS = ["current", "tfidf-act", "tfidf-act+sal", "tfidf-kind", "tfidf-kind+sal",
            "tfidf-full", "tfidf-full+sal", "tfidf-act+sal+df2"]


def run_regime(rid, out, arms):
    spec = RG.get(rid)
    d = os.path.join(RUN.ROOT, "data", "bench_v1", rid)
    traces = RUN.load_jsonl(os.path.join(d, "traces.jsonl"))
    gts = RUN.load_jsonl(os.path.join(d, "gt.jsonl"))
    ont = get_ontology(spec["ontology_id"])
    gt = dict((g["trace_id"], g) for g in gts)
    norms = [ingest.normalize(x, ont) for x in traces]
    feats = [FEAT.extract(x, ont) for x in norms]
    FEAT.annotate_sessions(feats, traces)
    n_dec = len(ont.get("required_steps") or {})
    threshold = cluster.CONSENSUS_THRESHOLD

    t = time.time()
    assigns_cur, cinfo_cur, intent_ctx = capture_intent(feats, spec["seed"], n_dec)
    secs_cluster_cur = time.time() - t
    if "current" in arms:
        t = time.time()
        row = evaluate_arm(rid, "current", feats, assigns_cur, cinfo_cur, gt,
                           secs_cluster_cur, 0.0,
                           extra={"secs_cluster_note": "includes ~10x settrace capture "
                                  "overhead; use secs_pattern_only for distance cost"})
        row["secs_downstream"] = round(time.time() - t, 1)
        out["arms"].append(row)
        print("  %-18s n_pat=%s nov=%s ari_p=%s f1=%s topk=%s clu=%.1fs"
              % ("current", row["n_pattern_clusters"], row["novelty_rate"],
                 ("%.4f" % row["ari_pattern_pool"]) if row["ari_pattern_pool"] is not None else "NA",
                 row["f1_pool"], row["topk%d_precision" % TOPK], row["secs_cluster"]),
              flush=True)

        # pattern-only timing of the shipped distance, caches cleared for honesty
        cluster.reset_cache()
        t = time.time()
        pattern_view(feats, intent_ctx["eval_idx"], spec["seed"], threshold,
                     cluster.R_RUNS, n_dec, "current")
        secs_pat_cur = time.time() - t
        out["arms"][-1]["secs_pattern_only"] = round(secs_pat_cur, 1)
        print("  %-18s pattern-only distance cost %.1fs (caches cleared)"
              % ("current", secs_pat_cur), flush=True)

    for mode in [a for a in arms if a != "current"]:
        t = time.time()
        pat = pattern_view(feats, intent_ctx["eval_idx"], spec["seed"], threshold,
                           cluster.R_RUNS, n_dec, mode)
        assigns = combine_assigns(feats, intent_ctx, pat, threshold, mode)
        nov = sum(1 for a in assigns if a["novelty"]) / float(len(assigns))
        cinfo = dict(cinfo_cur)
        cinfo.update({
            "n_pattern_clusters": len(pat["groups_p"]),
            "novelty_rate": nov,
            "pattern_cut_height": pat["h_pat"],
            "pattern_silhouette": pat["sil_pat"],
        })
        secs_cluster = time.time() - t
        t = time.time()
        row = evaluate_arm(rid, mode, feats, assigns, cinfo, gt, secs_cluster, 0.0,
                           extra={
                               "pattern_cut_height": pat["h_pat"],
                               "pattern_silhouette": pat["sil_pat"],
                               "n_unique_seq": pat["n_unique_seq"],
                               "n_salient": pat["n_salient"],
                               "fingerprint": pat["fingerprint"],
                               "dm_stats": pat["dm_stats"],
                               "top_ngrams": {str(c): v for c, v in
                                              sorted(pat["top_ngrams"].items())},
                           })
        row["secs_downstream"] = round(time.time() - t, 1)
        out["arms"].append(row)
        print("  %-18s n_pat=%s nov=%s ari_p=%s f1=%s topk=%s clu=%.1fs"
              % (mode, row["n_pattern_clusters"], row["novelty_rate"],
                 ("%.4f" % row["ari_pattern_pool"]) if row["ari_pattern_pool"] is not None else "NA",
                 row["f1_pool"], row["topk%d_precision" % TOPK], row["secs_cluster"]),
              flush=True)


def main():
    rids = sys.argv[1].split(",") if len(sys.argv) > 1 else RIDS
    arms = sys.argv[2].split(",") if len(sys.argv) > 2 else ALL_ARMS
    if os.path.exists(RESULTS):
        with io.open(RESULTS, encoding="utf-8") as f:
            out = json.load(f)
    else:
        out = {"_note": "E3 A/B: current saliency-profile pattern view vs route A TF-IDF. "
                        "All arms share one intent view; see tfidfexp.py docstring.",
               "arms": []}
    done = {(a["rid"], a["arm"]) for a in out["arms"]}
    t0 = time.time()
    for rid in rids:
        needed = [a for a in arms if (rid, a) not in done]
        if not needed:
            print("skip %s (already in results)" % rid, flush=True)
            continue
        print("[%6.1fs] %s arms=%s" % (time.time() - t0, rid, ",".join(needed)),
              flush=True)
        out["arms"] = [a for a in out["arms"]
                       if not (a["rid"] == rid and a["arm"] in needed)]
        run_regime(rid, out, needed)
        with io.open(RESULTS, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    out["_wall_secs"] = round(time.time() - t0, 1)
    with io.open(RESULTS, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    print("\nwrote %s  wall=%.1fs" % (RESULTS, out["_wall_secs"]), flush=True)


if __name__ == "__main__":
    main()
