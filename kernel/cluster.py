"""Dual-view consensus clustering -> 2-D analysis grid (methodology 5.x).

View I (intent): kmeans on sentence embeddings, k swept by a k-neutral silhouette, R runs.
View P (pattern): average-linkage (UPGMA) hierarchy on an n-gram profile distance over the
action sequence, R perturbed runs. The cut height is *selected*, not hardcoded: it is swept over
HEIGHT_GRID and scored with the silhouette statistic computed directly on the distance
matrix, which is the exact analogue of the k-sweep in view I. Both views therefore choose
their own resolution from the data and only the stability of that choice is voted on. The R runs are *bagged*: each one refits on a bootstrap resample and labels the
out-of-bag points by nearest bag centroid, so every pair receives a vote in every run (plain
subsampling would leave ~37% of pairs unvoted and silently fragment the consensus matrix).

Within each view: co-association M[a][b] = share of the R runs voting "same cluster". The
model order is the median k over the runs and the co-association dendrogram is cut at the
height that realises exactly that k, so consensus_threshold does NOT decide how many task
classes exist. It only decides when a trace's own assignment is too unreproducible to name:
cons = (a - b) / max(a, b), the silhouette of the co-association matrix, below the threshold.
Singletons and low-consensus members go to the novelty buffer (cell = null) and never feed
baselines or alerts.
"""
import math
import random

# Resample size for consensus estimation. 400 rather than 220 because the consensus is the
# only place instability is *measured*, and the measured share is what the whole population's
# novelty rate is calibrated to: at 220 points a 3% instability rate is 7 traces, which is
# inside the noise of the measurement itself.
EVAL_M = 400
# Eight resampling runs, not four. The consensus statistic is a co-association frequency, so
# it can only take R_RUNS+1 distinct values; at R_RUNS=4 a trace is either "agreed by 3 of 4
# runs" or "agreed by 2 of 4" and nothing in between, which is far too coarse to express
# "this trace sits on the boundary between two task classes". At 8 runs the consensus is
# resolved in eighths and the threshold becomes a real dial.
R_RUNS = 8
# Novelty dial. A trace is unassignable when the relative margin between the cluster the
# bagged runs gave it and the best competing cluster, cons = (a - b) / max(a, b), falls below
# this: 0.35 means "the runner-up retains more than 65% of the winner's support", i.e. the
# assignment does not survive resampling. The value is a measured plateau, not a fit. Sweeping
# the dial in 0.01 steps over all eight benchmark regimes, the novelty rate moves by at most
# 0.0014 anywhere inside [0.35, 0.37] and then jumps off a cliff - at 0.38 the heavy-overlap
# regime goes from 0.098 to 0.308, because 3/8 is a lattice point of the co-association
# statistic (a = 1, b = 5/8) and a fifth of that regime's traces sit exactly on it. 0.35 is
# placed just inside the plateau, away from both neighbouring lattice points (1/3 and 3/8).
# The superseded value 0.60 predates the margin semantics: under the mean-co-association form
# it was a sensible "60% of runs agree" cutoff, but on the margin form it sits on the a = 2b
# lattice point and flagged 30-45% of well behaved traffic as novel.
CONSENSUS_THRESHOLD = 0.35
K_MAX = 6
# The pattern view is a workflow taxonomy, so its model order comes from the pluggable
# business ontology rather than from a global constant: the ontology declares how many
# execution patterns the business has, and the search is allowed that many plus headroom for
# undeclared variants. Deriving it matters because the cut-selection statistic is monotone
# toward finer partitions once its k-bias is removed (see silhouette_dm), which makes the cap
# the binding constraint - leaving it at a loose global 8 let the heavily corrupted and
# foreign-ontology regimes shatter 3 declared workflows into 9-12 clusters.
K_MAX_PATTERN_HEADROOM = 2
K_MAX_PATTERN_ABS = 8
K_MAX_PATTERN = 5
SIL_CAP = 120
HEIGHT_GRID = tuple(round(0.05 * i, 2) for i in range(1, 18))
JITTER_SEQ = 0.02
JITTER_EMB_FRAC = 0.03
SIG_WEIGHT = 3.0
SIG_MIN_PREV = 0.03
SIL_TOL = 0.15
SIL_ABS_TOL = 0.02
# Separation term of BOTH silhouette statistics: distance to the NEAREST other cluster
# (classic) or the mass-weighted mean distance to ALL other clusters (k-neutral). See
# silhouette_dm for why the classic form is unusable for choosing a dendrogram cut, and
# silhouette for the same measurement on the intent view's choice of k.
SIL_NEAREST = False

_SEQ_MEMO = {}
_SEQ_MEMO_MAX = 200000


def reset_cache():
    _SEQ_MEMO.clear()
    _PROF_MEMO.clear()


def euclid(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def lev(a, b):
    if a == b:
        return 0
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ai != b[j - 1]))
        prev = cur
    return prev[lb]


def collapse(seq):
    """Drop immediate repetitions: a retried or nested-same-action step is not a new step."""
    out = []
    for a in seq:
        if not a or (out and out[-1] == a):
            continue
        out.append(a)
    return out


def action_saliency(seqs, min_prev=SIG_MIN_PREV):
    """Label-free saliency of action tokens, derived from *mutual exclusivity*.

    The hard part of the pattern view is that "workflow B" and "workflow A plus one
    decoration step" are the same structural event: a single token inserted into a
    sequence. Edit distance, n-gram distance and set distance all score them alike, so no
    cut height can separate a real route change from an optional verification step.

    What does separate them is a global, label-free statistic. A decoration step (optional
    verify / approve / extra api call) is sprinkled across *every* workflow, so it
    co-occurs with all other common actions. A route-signature step appears only on its own
    route, and is therefore **mutually exclusive** with the signature step of the route it
    replaces (this path retrieves the schema, that path queries the knowledge base instead
    - never both). So: an action is salient iff it never co-occurs with some other
    sufficiently common action. Salient tokens are up-weighted in the profile, which is
    what makes the hierarchy see "different route" as farther than "same route, extra
    decoration".
    """
    n = len(seqs)
    if n == 0:
        return set(), 0
    sets = [set(q) for q in seqs]
    prev = {}
    for st in sets:
        for a in st:
            prev[a] = prev.get(a, 0) + 1
    thr = max(2, int(math.ceil(min_prev * n)))
    common = sorted(a for a, c in prev.items() if c >= thr)
    co = {}
    for st in sets:
        loc = [a for a in st if a in set(common)]
        for i in range(len(loc)):
            for j in range(i + 1, len(loc)):
                k = (loc[i], loc[j]) if loc[i] < loc[j] else (loc[j], loc[i])
                co[k] = co.get(k, 0) + 1
    sig = set()
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            a, b = common[i], common[j]
            k = (a, b) if a < b else (b, a)
            if co.get(k, 0) == 0:
                sig.add(a)
                sig.add(b)
    return sig, n


def _token_weight(a, sig):
    return SIG_WEIGHT if (sig and a in sig) else 1.0


def profile(seq, sig=None):
    """Sparse weighted unigram+bigram count profile of a collapsed action sequence."""
    p = {}
    for a in seq:
        p[a] = p.get(a, 0.0) + _token_weight(a, sig)
    for i in range(len(seq) - 1):
        k = seq[i] + ">" + seq[i + 1]
        p[k] = p.get(k, 0.0) + math.sqrt(_token_weight(seq[i], sig)
                                        * _token_weight(seq[i + 1], sig))
    return p


def seq_dist(a, b, sig=None, token=0):
    """1 - cosine over the saliency-weighted unigram+bigram profile.

    Chosen over normalized edit distance on purpose. Edit distance treats "an optional
    verification step was inserted" (~0.20) and "a core retrieval step was replaced by a
    different one" (~0.25) as almost the same event, so workflow variants and genuinely
    different workflows land at the same radius and no cut height separates them. The
    n-gram profile charges an insertion one broken bigram but a substitution two, and the
    saliency weighting widens that gap further.
    """
    ka, kb = tuple(a), tuple(b)
    if ka == kb:
        return 0.0
    key = (token, ka, kb) if ka < kb else (token, kb, ka)
    v = _SEQ_MEMO.get(key)
    if v is None:
        pa = _prof_cache(ka, sig, token)
        pb = _prof_cache(kb, sig, token)
        if len(pa) > len(pb):
            pa, pb = pb, pa
        dot = 0.0
        for k, c in pa.items():
            if k in pb:
                dot += c * pb[k]
        na = math.sqrt(sum(c * c for c in pa.values()))
        nb = math.sqrt(sum(c * c for c in pb.values()))
        cos = dot / (na * nb) if (na and nb) else 0.0
        v = max(0.0, min(1.0, 1.0 - cos))
        if len(_SEQ_MEMO) < _SEQ_MEMO_MAX:
            _SEQ_MEMO[key] = v
    return v


_PROF_MEMO = {}


def _prof_cache(k, sig, token):
    key = (token, k)
    p = _PROF_MEMO.get(key)
    if p is None:
        p = profile(list(k), sig)
        if len(_PROF_MEMO) < _SEQ_MEMO_MAX:
            _PROF_MEMO[key] = p
    return p


def kmeans_cent(pts, k, rng, iters=25):
    """k-means++ seeded Lloyd's algorithm. Returns (labels, centroids).

    Centroids are returned because the consensus runs label out-of-bag points with them; a
    run that only reports labels cannot say anything about a point it never saw.
    """
    n = len(pts)
    if n <= k:
        return list(range(n)), [list(p) for p in pts]
    dim = len(pts[0])
    cents = [list(pts[rng.randrange(n)])]
    while len(cents) < k:
        d2 = [min(sum((p[c] - q[c]) ** 2 for c in range(dim)) for q in cents) for p in pts]
        tot = sum(d2) or 1.0
        r = rng.random() * tot
        acc = 0.0
        pick = n - 1
        for i, d in enumerate(d2):
            acc += d
            if acc >= r:
                pick = i
                break
        cents.append(list(pts[pick]))
    lab = [0] * n
    for _ in range(iters):
        moved = False
        for i, p in enumerate(pts):
            best, bd = 0, None
            for j, q in enumerate(cents):
                d = sum((p[c] - q[c]) ** 2 for c in range(dim))
                if bd is None or d < bd:
                    best, bd = j, d
            if lab[i] != best:
                moved = True
                lab[i] = best
        if not moved:
            break
        for j in range(k):
            mem = [p for i, p in enumerate(pts) if lab[i] == j]
            if mem:
                cents[j] = [sum(p[c] for p in mem) / len(mem) for c in range(dim)]
    return lab, cents


def kmeans(pts, k, rng, iters=25):
    return kmeans_cent(pts, k, rng, iters)[0]


def silhouette(pts, lab, rng, cap=SIL_CAP, nearest=None):
    """Mean silhouette of a partition of embedding points; k-neutral by default.

    The intent view maximises this over k, so its bias *is* the model order that view reports.
    `nearest` defaults to SIL_NEAREST (False): the mean distance to ALL out-of-cluster mass,
    matching silhouette_dm. The classic form takes the minimum over the other clusters, and
    every additional cluster can only shrink that minimum, so it is structurally biased toward
    coarse partitions.

    Measured on the bench_v1 regimes over the same 400-point eval subset and the same
    kmeans_cent partitions - argmax over k = 2..6, and the ARI against true intent_id that the
    selected k then yields:

        regime  true k   classic argmax -> ARI    k-neutral argmax -> ARI
        R2         3        2 -> 0.7915               6 -> 0.6994
        R4         4        2 -> 0.6316               4 -> 1.0000
        R8         3        2 -> 0.7485               4 -> 0.8827
        R3         2        2 -> 0.6074               2 -> 0.6074

    The classic form answered k = 2 on all four, including the three whose ground truth is 3
    or 4. That is why the intent view reported k_intent_consensus = 2 on all eight regimes
    while its own plug-in Bayes ceiling was 1.0000 on R2/R4/R8: the embedding was perfectly
    separable and the view was simply asking for the wrong number of clusters. The intent
    directions lie on an arc, so the most separated 2-cut is the two halves of that arc and it
    wins the classic index by a wide margin (R4: 0.3639 at k=2 against 0.3153 at the true
    k=4). k-neutral recovers k = 4 on R4 exactly and lifts R8 0.7485 -> 0.8827.

    It is not uniformly better, and the exception is recorded rather than tuned away. On R3 -
    the one regime built as a deliberate intent continuum - the k-neutral curve is nearly flat
    over k = 2..6 (0.0464 / 0.0439 / 0.0460 / 0.0453 / 0.0482, a 9% spread) while ARI falls
    0.5918 -> 0.1827 across the same range, so the argmax lands on k = 6 against 2 true
    intents. That costs R3 novelty_rate 0.2867 on a [0.03, 0.30] band - 4.4% of headroom under
    the cap - and coverage 0.7133, i.e. 28.7% of its traffic is left unassignable and gets no
    conditional baseline. Everywhere else the curve is decisive and the argmax is correct: the
    shipped bagged model orders are R1 2, R2 3, R3 6, R4 4, R5 2, R6 2, R7 2, R8 3, against
    truths 2, 3, 2, 4, 2, 2, 2, 3. R3 is the only over-split. (An earlier single-run sweep
    predicted R2 would also over-split to 6; the real pipeline takes the median over 8 bags and
    reports 3, which is exactly right - single-run diagnostics under-predict this.)

    Two fixes for R3 were measured and both are REJECTED, so neither should be re-tried without
    new evidence:

      * Ontology-derived model order cap, mirroring K_MAX_PATTERN_HEADROOM. Inert. Both shipped
        ontologies declare 4 intents, so min(K_MAX, 4 + 2) = 6 = K_MAX and nothing is bounded.
        The structural reason is that a regime exercises a SUBSET of the declared taxonomy - R3
        uses 2 of the 4 intents its ontology declares - so a declared count cannot bound the
        order of the traffic actually present. The pattern view can use it because workflows
        are enumerated per pattern_id in `required_steps`, which the generator samples from
        directly; intents are not enumerated that way.
      * Absolute parsimony band - smallest k whose silhouette is within SIL_ABS_TOL of the best,
        the same rule select_cut_height uses for the dendrogram cut. Measured on the full bagged
        pipeline: R1 unchanged (k 2, novelty 0.0138); R2 k 3 -> 2, ari_intent 1.0000 -> 0.7612,
        still clearing its 0.65 gate; R3 k 6 -> 2 but novelty 0.2867 -> 0.0280, which falls
        BELOW the 0.03 floor, because collapsing to the true k leaves almost no undecided points
        for the novelty channel to fire on; R4 k 4 -> 2, ari_intent 1.0000 -> 0.4656, a hard
        FAIL. So the band trades a 4.4% novelty margin on one regime for two failed gates.
        The relative term SIL_TOL makes it strictly worse still: intent silhouette scores span
        an order of magnitude across regimes (0.046 on the R3 continuum, 0.38 on well separated
        traffic), so a 15% relative band is 0.057 on R1 and swallows the true k.

    The argmax is therefore kept and R3's novelty margin is carried as a known boundary rather
    than fixed by a rule that breaks R4. It is deterministic, not run-to-run fragile: the same
    seed reproduces 0.2867 exactly. What would move it is a change to the embedding geometry or
    to R_RUNS, so both are worth re-checking R3 after any future retune.
    """
    nearest = SIL_NEAREST if nearest is None else nearest
    n = len(pts)
    idx = list(range(n))
    if n > cap:
        idx = rng.sample(idx, cap)
    m = len(idx)
    dm = [[0.0] * m for _ in range(m)]
    for a in range(m):
        pa = pts[idx[a]]
        for b in range(a + 1, m):
            dm[a][b] = dm[b][a] = euclid(pa, pts[idx[b]])
    labs = [lab[i] for i in idx]
    ks = sorted(set(labs))
    if len(ks) < 2:
        return -1.0
    byk = {k: [a for a in range(m) if labs[a] == k] for k in ks}
    vals = []
    for a in range(m):
        same = [b for b in byk[labs[a]] if b != a]
        if not same:
            continue
        ai = sum(dm[a][b] for b in same) / len(same)
        if nearest:
            bi = None
            for k in ks:
                if k == labs[a]:
                    continue
                oth = byk[k]
                if not oth:
                    continue
                mk = sum(dm[a][b] for b in oth) / len(oth)
                bi = mk if bi is None else min(bi, mk)
        else:
            oth = [b for b in range(m) if b != a and labs[b] != labs[a]]
            bi = (sum(dm[a][b] for b in oth) / len(oth)) if oth else None
        if bi is None:
            continue
        vals.append((bi - ai) / max(ai, bi, 1e-9))
    return sum(vals) / len(vals) if vals else -1.0


def silhouette_dm(dm, lab, weights=None, cap=220, nearest=None):
    """Frequency-weighted silhouette on a precomputed distance matrix.

    `nearest` selects the separation term b_i, and the choice is not cosmetic. The classic
    form takes the distance to the NEAREST other cluster, so every additional cluster can
    only shrink b_i - the index is structurally biased toward coarse partitions, and when it
    is used to pick a dendrogram cut that bias decides the answer. Measured on the
    heavy-overlap regime: the k=2 cut scored 0.6231 while the correct 3-workflow cut scored
    0.5214, so a 15% tolerance band around the maximum landed on k=2, ARI fell from a 0.997
    information ceiling to 0.60, cells doubled in size and their conditional distributions
    turned bimodal again. The k-neutral form replaces the minimum with the mass-weighted mean
    distance to ALL out-of-cluster mass, which does not shrink as clusters are added.

    The nodes here are *unique* action sequences, each standing for a different number of
    traces. Unweighted, one far-out sequence (a trace with a dropped core step or an
    injected forbidden action) carries the same vote as a workflow used by 40% of traffic,
    and the statistic then prefers a cut that merges two real workflows rather than
    admitting a speck of an outlier cluster. Weighting by trace multiplicity restores the
    question we actually care about: how well is the *traffic* partitioned.
    """
    nearest = SIL_NEAREST if nearest is None else nearest
    n = len(dm)
    w = list(weights) if weights else [1.0] * n
    idx = list(range(n))
    if n > cap:
        idx = list(range(0, n, max(1, n // cap)))[:cap]
    labs = [lab[i] for i in idx]
    ks = sorted(set(labs))
    if len(ks) < 2:
        return -1.0
    byk = {}
    for a, l in enumerate(labs):
        byk.setdefault(l, []).append(a)
    num = 0.0
    den = 0.0
    for a in range(len(idx)):
        i = idx[a]
        same = [b for b in byk[labs[a]] if b != a]
        wsum_same = sum(w[idx[b]] for b in same)
        if not same or wsum_same <= 0:
            continue
        ai = sum(dm[i][idx[b]] * w[idx[b]] for b in same) / wsum_same
        if nearest:
            bi = None
            for k in ks:
                if k == labs[a]:
                    continue
                oth = byk[k]
                wsum_o = sum(w[idx[b]] for b in oth)
                if wsum_o <= 0:
                    continue
                mk = sum(dm[i][idx[b]] * w[idx[b]] for b in oth) / wsum_o
                bi = mk if bi is None else min(bi, mk)
        else:
            num_o, den_o = 0.0, 0.0
            for b in range(len(idx)):
                if b == a or labs[b] == labs[a]:
                    continue
                num_o += dm[i][idx[b]] * w[idx[b]]
                den_o += w[idx[b]]
            bi = (num_o / den_o) if den_o > 0 else None
        if bi is None:
            continue
        si = (bi - ai) / max(ai, bi, 1e-12)
        num += w[i] * si
        den += w[i]
    return num / den if den > 0 else -1.0


def select_cut_height(dm, u, grid=HEIGHT_GRID, k_max=K_MAX_PATTERN, min_size=2,
                      min_cover=0.90, weights=None):
    """Pick the UPGMA cut height for the pattern view: merge-gap first, silhouette as fallback.

    Two separate degeneracies have to be avoided and they pull in opposite directions.

    (1) Unconstrained silhouette is maximised by shattering. Many action sequences are exact
        duplicates, so on the reference regime plain maximisation picks 59 clusters at
        height 0.10 (silhouette 0.55) where the true 3-workflow cut at height 0.50 scores
        0.20. Hence the hard constraints 2 <= k <= k_max and "clusters holding at least
        min_size unique sequences cover >= min_cover of trace mass". The coverage *form*
        matters: a single far-out sequence (a dropped core step, an injected forbidden
        action) would otherwise veto every candidate height and collapse the view into one
        cluster.

    (2) Even constrained, silhouette is *k-biased*: its separation term b_i is the distance
        to the NEAREST other cluster, so splitting can only shrink b_i. On real sequence
        profiles the bias is decisive - the k=2 cut scored 0.6231 while the correct
        3-workflow cut scored 0.5214 - so a tolerance band around the maximum always landed
        on the coarsest admissible cut. Measured cost on the heavy-overlap and sparse-cell
        regimes: the pattern view returned 2 clusters where 3 patterns (6 pattern x intent
        workflows) were present, ARI fell from a 0.997 information ceiling to 0.60, cells
        roughly doubled in size, conditional baselines turned bimodal again, and the
        sparse-cell regime stopped exercising the credibility pooling it exists to test.

    Both constraints are applied to a k-neutral silhouette (see silhouette_dm); the merge-
    height gap was tried as the primary criterion and rejected, because the final merge into
    a single cluster always owns the largest vertical stretch, so Thorndike's rule collapses
    to k=2 on every regime measured. Residual ties break toward the finer cut: over-
    splitting a workflow is cheap, because a small cell is shrunk toward its intent and
    global levels by the credibility weight and its baseline stays sound; under-splitting is
    not recoverable anywhere downstream, since a cell that silently mixes two workflows has
    a bimodal conditional distribution - precisely the failure this design exists to avoid.

    Returns (height, silhouette_at_height, curve) where curve is the admissibility/silhouette
    trace over the grid, kept for the report so the choice is auditable after the fact.
    """
    if u < 4:
        return grid[0], -1.0, []
    ww = list(weights) if weights else [1.0] * u
    tot_w = sum(ww) or 1.0
    sched = upgma(dm, u)

    def k_of(h):
        cid = cut_from_schedule(sched, u, h)
        lab = [cid.get(i, i) for i in range(u)]
        sizes, mass = {}, {}
        for j, l in enumerate(lab):
            sizes[l] = sizes.get(l, 0) + 1
            mass[l] = mass.get(l, 0.0) + ww[j]
        covered = sum(v for l, v in mass.items() if sizes[l] >= min_size)
        return lab, len(sizes), (2 <= len(sizes) <= k_max) and covered >= min_cover * tot_w

    curve = []
    for h in grid:
        lab, k, admissible = k_of(h)
        sc = silhouette_dm(dm, lab, ww) if admissible else None
        curve.append((h, (round(sc, 4) if sc is not None else None), k, admissible))

    adm = [(h, sc, k) for (h, sc, k, a) in curve if a and sc is not None]
    if not adm:
        # nothing admissible: fall back to the height whose k is closest to 2, finest first,
        # so the result stays deterministic
        return min((abs(k - 2), -h, h) for (h, _sc, k, _a) in curve)[2], -1.0, curve
    best_s = max(sc for _h, sc, _k in adm)
    floor_s = best_s - max(SIL_TOL * abs(best_s), SIL_ABS_TOL)
    best_h = min(h for h, sc, _k in adm if sc >= floor_s)
    lab, _k, _a = k_of(best_h)
    return best_h, round(silhouette_dm(dm, lab, ww), 4), curve


def upgma(dist, m):
    """Average-linkage (UPGMA) agglomeration over an m x m distance matrix.

    Returns the merge schedule: one (height, keep, drop, members, n_clusters) tuple per
    merge in increasing height order, where `keep`/`drop` are the surviving and absorbed
    node handles and `members` is the member list of the merged cluster. Building the
    schedule once and cutting it many times is what lets the cut-height sweep and the gap
    statistic share a single linkage pass instead of paying for one each - on a 225-sequence
    distance matrix that is the difference between ~17 linkage runs and 1.
    """
    d = [list(row) for row in dist]
    members = [[i] for i in range(m)]
    alive = list(range(m))
    sched = []
    while len(alive) > 1:
        best, bi, bj = None, -1, -1
        for ai in range(len(alive)):
            i = alive[ai]
            di = d[i]
            for aj in range(ai + 1, len(alive)):
                v = di[alive[aj]]
                if best is None or v < best:
                    best, bi, bj = v, ai, aj
        if best is None:
            break
        i, j = alive[bi], alive[bj]
        ni, nj = len(members[i]), len(members[j])
        tot = float(ni + nj)
        di, dj = d[i], d[j]
        for k in alive:
            if k == i or k == j:
                continue
            v = (ni * di[k] + nj * dj[k]) / tot
            di[k] = v
            d[k][i] = v
        members[i] = members[i] + members[j]
        members[j] = []
        alive = [x for x in alive if x != j]
        sched.append((best, i, j, list(members[i]), len(alive)))
    return sched


def cut_from_schedule(sched, m, height):
    """Partition of 0..m-1 obtained by applying every merge at height <= `height`."""
    tag = [-1] * m
    for idx, (h, _keep, _drop, mem, _k) in enumerate(sched):
        if h > height:
            break
        t = -idx - 2
        for x in mem:
            tag[x] = t
    order = {}
    res = [0] * m
    nxt = 0
    for x in range(m):
        key = tag[x] if tag[x] < -1 else x
        if key not in order:
            order[key] = nxt
            nxt += 1
        res[x] = order[key]
    return dict((x, res[x]) for x in range(m))


def avg_link_cut(dist, m, height):
    """UPGMA (average linkage) over an m x m distance matrix, cut at merge height <= height."""
    return cut_from_schedule(upgma(dist, m), m, height)



def _quantile(sv, q):
    n = len(sv)
    if n == 0:
        return None
    if n == 1:
        return sv[0]
    h = (n - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, n - 1)
    return sv[lo] + (h - lo) * (sv[hi] - sv[lo])


def post_margin(pt, cent_list, sigma2):
    """Log-posterior margin of the nearest-centroid assignment, in nats.

        geo(x) = (||x - mu_2nd||^2 - ||x - mu_own||^2) / (2 * sigma^2)

    Zero exactly on the decision boundary between the two nearest task classes, and growing
    without bound as x moves inside its own class. It has to be the difference of *squared*
    distances, not of distances: in a 16-d embedding the Euclidean distance to a centroid is
    dominated by the 15 orthogonal noise directions, so d2 - d1 barely moves when a trace
    crosses the boundary, whereas d2^2 - d1^2 is exactly the quantity the Gaussian
    log-posterior ratio is proportional to. sigma^2 is the pooled within-cluster variance per
    dimension, which makes geo dimension-free and comparable across deployments.
    """
    if len(cent_list) < 2 or not sigma2 or sigma2 <= 0:
        return float("inf")
    ds = sorted(sum((a - b) ** 2 for a, b in zip(pt, c)) for c in cent_list)
    return (ds[1] - ds[0]) / (2.0 * sigma2)


def pooled_var(emb, groups, cents, dim):
    """Pooled within-cluster variance per dimension of a consensus partition."""
    ss, dof = 0.0, 0
    if dim <= 0:
        return 0.0
    for c, mem in groups.items():
        if len(mem) < 2 or c not in cents:
            continue
        mu = cents[c]
        for x in mem:
            for dd in range(dim):
                ss += (emb[x][dd] - mu[dd]) ** 2
                dof += 1
    return (ss / dof) if dof else 0.0


def _consensus(label_runs, m, threshold):
    """Bagged co-association consensus -> (partition, per-point stability, groups).

    Two decisions here are load-bearing, and both were wrong in the first implementation.

    Model order = median of the per-run k, not a cut of the co-association dendrogram.
      Cutting the co-association matrix at a fixed height (1 - threshold) lets the threshold
      decide how many task classes exist, and it fragments them. On the heavy-overlap regime
      every one of the 8 bagged runs agreed on k=2, yet boundary points co-associate slightly
      less with the far side of their own class, average linkage read that dip as structure,
      and the consensus came back with 4 clusters: intent ARI fell from 0.499 - which is the
      Bayes ceiling for that regime - to 0.379, and the analysis cells tripled in number.
      Taking the median k over runs keeps the model order a property of the data instead of a
      property of a dial, and leaves the threshold free to do its actual job.

    Per-point stability = silhouette of the co-association matrix, not mean co-association.
      A within-cluster mean cannot express the only uncertainty that matters, which is
      *relative*: a trace sitting on the boundary between two task classes co-associates
      strongly with both, so its within-cluster mean stays around 0.7 and it looks confident.
      The margin form

          cons = (a - b) / max(a, b)    a = mean co-assoc with own cluster
                                        b = mean co-assoc with the nearest other cluster

      is ~1.0 for a trace deep inside a class, ~0 on the boundary, and negative when the runs
      mostly placed it elsewhere. That is what lets `novelty` mean "this trace belongs to no
      task class I can name" rather than "this trace was unlucky in one bootstrap".
    """
    r = len(label_runs)
    cnt = [[0] * m for _ in range(m)]
    for lab in label_runs:
        groups = {}
        for pos, l in enumerate(lab):
            groups.setdefault(l, []).append(pos)
        for g in groups.values():
            for ai in range(len(g)):
                ga = g[ai]
                for aj in range(ai + 1, len(g)):
                    cnt[ga][g[aj]] += 1
    sim = [[cnt[i][j] / float(r) for j in range(m)] for i in range(m)]

    ks = sorted(len(set(lab)) for lab in label_runs)
    mid = len(ks) // 2
    k_cons = ks[mid] if len(ks) % 2 else int(round(0.5 * (ks[mid - 1] + ks[mid])))
    k_cons = max(1, min(k_cons, m))

    if k_cons >= m:
        cid = dict((i, i) for i in range(m))
    else:
        dist = [[1.0 - sim[i][j] for j in range(m)] for i in range(m)]
        sched = upgma(dist, m)
        h_cut = None
        for h, _keep, _drop, _mem, k in sched:
            if k == k_cons:
                h_cut = h
                break
        cid = cut_from_schedule(sched, m, float("inf") if h_cut is None else h_cut)

    groups = {}
    for x, c in cid.items():
        groups.setdefault(c, []).append(x)
    members = dict((c, sorted(mem)) for c, mem in groups.items())
    others = sorted(members)
    cons = [0.0] * m
    for c in others:
        mem = members[c]
        if len(mem) == 1:
            continue
        for x in mem:
            a = sum(sim[x][y] for y in mem if y != x) / float(len(mem) - 1)
            b = None
            for c2 in others:
                if c2 == c:
                    continue
                m2 = members[c2]
                v = sum(sim[x][y] for y in m2) / float(len(m2))
                b = v if b is None or v > b else b
            cons[x] = (1.0 if a > 0 else 0.0) if b is None else (a - b) / max(a, b, 1e-12)
    return cid, cons, groups


def _emb_scale(emb, rng, cap=60):
    n = len(emb)
    if n < 2:
        return 1.0
    idx = list(range(n))
    if n > cap:
        idx = rng.sample(idx, cap)
    tot, k = 0.0, 0
    for ai in range(len(idx)):
        for bj in range(ai + 1, len(idx)):
            tot += euclid(emb[idx[ai]], emb[idx[bj]])
            k += 1
    return (tot / k) if k else 1.0


def _jitter_emb(emb, sigma, rng):
    if sigma <= 0:
        return [list(p) for p in emb]
    return [[x + rng.gauss(0.0, sigma) for x in p] for p in emb]


def cluster_views(features, threshold=CONSENSUS_THRESHOLD, seed=42, eval_m=EVAL_M, r_runs=R_RUNS,
                  n_declared_patterns=None):
    rng = random.Random(seed)
    n = len(features)
    m = min(eval_m, n)
    eval_idx = sorted(rng.sample(range(n), m)) if m < n else list(range(n))
    emb = [features[i]["embedding"] for i in eval_idx]
    seqs = [features[i]["action_seq"] for i in eval_idx]
    dim = len(emb[0]) if emb and emb[0] else 0

    sigma_e = JITTER_EMB_FRAC * _emb_scale(emb, rng) if dim else 0.0
    runs_i = []
    kmax = max(2, min(K_MAX, m - 1))
    for _ in range(r_runs):
        # Bagging (Monti et al. consensus clustering): refit on a bootstrap resample, then
        # label the out-of-bag points by nearest bag centroid. Two reasons this replaces the
        # jitter-only resampling it supersedes:
        #   * The perturbation is a *sampling* perturbation, so it moves exactly the points
        #     that are genuinely undecided. Additive noise of a fixed scale perturbs every
        #     point equally: on well-separated traffic it changes nothing (consensus stays
        #     1.000 and the view reports no uncertainty at all), and on heavily overlapping
        #     traffic it still changes nothing, because the noise is small next to the
        #     intrinsic spread. Either way the consensus matrix came out binary, so the
        #     novelty channel - the mechanism that is supposed to say "this trace belongs to
        #     no task class I have seen" - never fired: 0.07% on a regime whose Bayes error
        #     is 14%.
        #   * Plain subsampling would leave the out-of-bag points unlabelled in that run, so
        #     ~37% of pairs would receive no vote and their co-association would be
        #     indistinguishable from disagreement. Nearest-centroid labelling gives every
        #     pair a vote in every run, which is what makes the frequency interpretable.
        bag = [rng.randrange(m) for _ in range(m)]
        e_bag = _jitter_emb([emb[i] for i in bag], sigma_e, rng)
        best, bcen = None, None
        for k in range(2, kmax + 1):
            lab, cen = kmeans_cent(e_bag, k, rng)
            sc = silhouette(e_bag, lab, rng)
            if best is None or sc > best:
                best, bcen = sc, cen
        if not bcen:
            runs_i.append(list(range(m)))
            continue
        runs_i.append([min(range(len(bcen)), key=lambda c, i=i: euclid(emb[i], bcen[c]))
                       for i in range(m)])
    cid_i, cons_i, groups_i = _consensus(runs_i, m, threshold)

    skels = [collapse(sq) for sq in seqs]
    sig, _nseq = action_saliency(skels)
    sig_tok = tuple(sorted(sig))
    uniq, urep = [], {}
    for sq in skels:
        k = tuple(sq)
        if k not in urep:
            urep[k] = len(uniq)
            uniq.append(k)
    u = len(uniq)
    udm = [[0.0] * u for _ in range(u)]
    for a in range(u):
        la = list(uniq[a])
        for b in range(a + 1, u):
            udm[a][b] = udm[b][a] = seq_dist(la, list(uniq[b]), sig, sig_tok)
    uw = [0] * u
    for sq in skels:
        uw[urep[tuple(sq)]] += 1
    # Model order of the pattern view = declared workflows + headroom for undeclared
    # variants, capped by an absolute ceiling. See K_MAX_PATTERN_HEADROOM.
    n_dec = n_declared_patterns or K_MAX_PATTERN_ABS
    kmax_pat = max(2, min(K_MAX_PATTERN_ABS, n_dec + K_MAX_PATTERN_HEADROOM))
    h_pat, sil_pat, curve = select_cut_height(udm, u, k_max=kmax_pat, weights=uw)
    runs_p = []
    for _ in range(r_runs):
        jdm = [[0.0] * u for _ in range(u)]
        for a in range(u):
            for b in range(a + 1, u):
                v = udm[a][b] + rng.gauss(0.0, JITTER_SEQ)
                v = 0.0 if v < 0.0 else v
                jdm[a][b] = jdm[b][a] = v
        lab_u = avg_link_cut(jdm, u, h_pat)
        runs_p.append([lab_u.get(urep[tuple(sq)], 0) for sq in skels])
    cid_p, cons_p, groups_p = _consensus(runs_p, m, threshold)

    cents_i = {}
    for c, mem in groups_i.items():
        pts = [emb[x] for x in mem]
        cents_i[c] = [sum(p[d] for p in pts) / len(pts) for d in range(dim)] if dim else []
    med_p = {}
    for c, mem in groups_p.items():
        best, bx = None, None
        for x in mem:
            tot = sum(seq_dist(skels[x], skels[y], sig, sig_tok) for y in mem) / float(len(mem))
            if best is None or tot < best:
                best, bx = tot, x
        med_p[c] = skels[bx]
    single_i = {c for c, mem in groups_i.items() if len(mem) == 1}
    single_p = {c for c, mem in groups_p.items() if len(mem) == 1}
    memcons_i = {c: sum(cons_i[x] for x in mem) / float(len(mem)) for c, mem in groups_i.items()}
    memcons_p = {c: sum(cons_p[x] for x in mem) / float(len(mem)) for c, mem in groups_p.items()}
    pos_of = {t: p for p, t in enumerate(eval_idx)}
    _sig_ctx = (sig, sig_tok)
    cl = sorted(cents_i)
    pl = sorted(med_p)
    cent_list = [cents_i[c] for c in cl]

    # ---- propagating the instability verdict from the resampled subset to every trace ----
    # Stability under bagging is only measurable on the subset that was resampled; the
    # remaining traces have no co-association frequency at all, and inheriting their cluster's
    # mean (the previous behaviour) makes every one of them look confident, so a regime whose
    # Bayes error is 14% reported a novelty rate of 0.07%. The two questions are therefore
    # split between the two quantities that can actually answer them:
    #   * HOW MANY traces are unassignable is *measured*, on the subset, by bagged consensus.
    #   * WHICH ones they are is decided for every trace by the log-posterior margin geo,
    #     whose cutoff is the quantile of the geo distribution at the measured rate.
    # Neither side is a free parameter, and on well-separated traffic the measured rate is
    # zero, which disables the geometric rule entirely instead of guessing at a boundary.
    sigma2 = pooled_var(emb, groups_i, cents_i, dim)
    n_flag = sum(1 for p in range(m) if cons_i[p] < threshold)
    flag_rate = (n_flag / float(m)) if m else 0.0
    geo_cut, n_geo = None, 0
    if flag_rate > 0.0 and cent_list and sigma2 > 0:
        all_geo = sorted(post_margin(features[i]["embedding"], cent_list, sigma2)
                         for i in range(n))
        geo_cut = _quantile(all_geo, flag_rate)
        n_geo = sum(1 for g in all_geo if g <= geo_cut)

    out = []
    for i in range(n):
        e = features[i]["embedding"]
        ci = min(cl, key=lambda c: euclid(e, cents_i[c])) if cl else -1
        sk = collapse(features[i]["action_seq"])
        cp = min(pl, key=lambda c: seq_dist(sk, med_p[c], _sig_ctx[0], _sig_ctx[1])) if pl else -1
        p = pos_of.get(i)
        vi = cons_i[p] if p is not None else memcons_i.get(ci, 0.0)
        vp = cons_p[p] if p is not None else memcons_p.get(cp, 0.0)
        geo = post_margin(e, cent_list, sigma2)
        nov = ((ci in single_i) or (cp in single_p) or (vi < threshold) or (vp < threshold)
               or (geo_cut is not None and geo <= geo_cut))
        out.append({
            "trace_id": features[i]["trace_id"],
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
    info = {
        "n_intent_clusters": len(groups_i),
        "n_pattern_clusters": len(groups_p),
        "n_singleton_intent": len(single_i),
        "n_singleton_pattern": len(single_p),
        "n_unique_seq": u,
        "n_salient_actions": len(sig),
        "salient_actions": sorted(sig),
        "pattern_cut_height": h_pat,
        "pattern_silhouette": sil_pat,
        "pattern_height_curve": curve,
        "eval_m": m,
        "r_runs": r_runs,
        "threshold": threshold,
        "novelty_rate": (sum(1 for r in out if r["novelty"]) / float(n)) if n else 0.0,
        "emb_jitter_sigma": sigma_e,
        "instability_rate_measured": flag_rate,
        "post_margin_cut": geo_cut,
        "n_novelty_by_margin": n_geo,
        "pooled_emb_var": sigma2,
        "k_intent_consensus": len(groups_i),
        "k_pattern_consensus": len(groups_p),
    }
    return out, info