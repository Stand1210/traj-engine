"""Evaluation metrics for clustering / detection / ranking / correlation.

HARD RULE: `point_adjust` is banned in this repository. Under the point-adjust convention a
predicted segment that overlaps a ground-truth segment in even a single point credits the
*entire* ground-truth segment, so the degenerate "everything is anomalous" prediction scores
F1 ~ 1.0. Most published time-series anomaly F1 > 0.9 is an artefact of that convention.
Every detector number produced here is either point-wise at an explicit threshold, a top-k
ranking statistic, or an area under a curve - all of which a constant predictor cannot fake.
"""
import math


def point_adjust_f1(*args, **kwargs):
    raise NotImplementedError(
        "point-adjust is banned: a single overlapping point credits the whole ground-truth "
        "segment, so an all-anomaly prediction scores F1~1.0. Use prf / precision_at_k / "
        "roc_auc / pr_auc instead.")


def _comb2(n):
    return n * (n - 1) / 2.0 if n > 1 else 0.0


def contingency(la, lb):
    tab = {}
    for a, b in zip(la, lb):
        tab[(a, b)] = tab.get((a, b), 0) + 1
    return tab


def ari(la, lb):
    n = len(la)
    if n < 2:
        return 0.0
    tab = contingency(la, lb)
    ca = {}
    cb = {}
    for (a, b), v in tab.items():
        ca[a] = ca.get(a, 0) + v
        cb[b] = cb.get(b, 0) + v
    s_ij = sum(_comb2(v) for v in tab.values())
    s_a = sum(_comb2(v) for v in ca.values())
    s_b = sum(_comb2(v) for v in cb.values())
    tot = _comb2(n)
    exp = s_a * s_b / tot if tot else 0.0
    mx = 0.5 * (s_a + s_b)
    den = mx - exp
    if abs(den) < 1e-15:
        return 0.0
    return (s_ij - exp) / den


def _entropy(counts, n):
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / float(n)
            h -= p * math.log(p)
    return h


def nmi(la, lb):
    n = len(la)
    if n == 0:
        return 0.0
    tab = contingency(la, lb)
    ca = {}
    cb = {}
    for (a, b), v in tab.items():
        ca[a] = ca.get(a, 0) + v
        cb[b] = cb.get(b, 0) + v
    ha = _entropy(ca.values(), n)
    hb = _entropy(cb.values(), n)
    if ha == 0 or hb == 0:
        return 0.0
    mi = 0.0
    for (a, b), v in tab.items():
        p_ij = v / float(n)
        mi += p_ij * math.log(p_ij / ((ca[a] / float(n)) * (cb[b] / float(n))))
    return 2.0 * mi / (ha + hb)


def purity(pred, truth):
    """pred/truth are label lists; for each predicted cluster take its majority truth label."""
    if not pred:
        return 0.0
    tab = contingency(pred, truth)
    byp = {}
    for (p, t), v in tab.items():
        e = byp.setdefault(p, [0, {}])
        e[0] += v
        e[1][t] = e[1].get(t, 0) + v
    hit = sum(max(e[1].values()) for e in byp.values())
    return hit / float(len(pred))


def prf(y_true, y_pred):
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if (not t) and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and (not p))
    prec = tp / float(tp + fp) if (tp + fp) else 0.0
    rec = tp / float(tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    tn = len(y_true) - tp - fp - fn
    fpr = fp / float(fp + tn) if (fp + tn) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": prec, "recall": rec,
            "f1": f1, "fpr": fpr, "n_pos": tp + fn, "n_neg": fp + tn}


def _ranks(vals):
    n = len(vals)
    order = sorted(range(n), key=lambda i: vals[i])
    r = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def roc_auc(scores, y):
    """Mann-Whitney U form; ties get average ranks so a constant scorer scores exactly 0.5."""
    pos = sum(1 for v in y if v)
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return None
    r = _ranks(list(scores))
    sp = sum(r[i] for i in range(len(y)) if y[i])
    return (sp - pos * (pos + 1) / 2.0) / float(pos * neg)


def pr_auc(scores, y):
    """Average precision over the descending-score ranking (step interpolation)."""
    pos = sum(1 for v in y if v)
    if pos == 0:
        return None
    order = sorted(range(len(y)), key=lambda i: (-scores[i], i))
    hit = 0
    ap = 0.0
    prev = None
    for k, i in enumerate(order, start=1):
        if y[i]:
            hit += 1
            ap += hit / float(k)
    return ap / float(pos)


def precision_at_k(scores, y, k):
    if k <= 0 or not scores:
        return None
    order = sorted(range(len(y)), key=lambda i: (-scores[i], i))
    kk = min(k, len(order))
    return sum(1 for i in order[:kk] if y[i]) / float(kk)


def recall_at_k(scores, y, k):
    pos = sum(1 for v in y if v)
    if pos == 0 or k <= 0:
        return None
    order = sorted(range(len(y)), key=lambda i: (-scores[i], i))
    kk = min(k, len(order))
    return sum(1 for i in order[:kk] if y[i]) / float(pos)


def pearson(x, y):
    n = len(x)
    if n < 2:
        return None
    mx = sum(x) / float(n)
    my = sum(y) / float(n)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def spearman(x, y):
    if len(x) < 2:
        return None
    return pearson(_ranks(list(x)), _ranks(list(y)))


def kendall_tau_b(x, y, cap=1500):
    n = len(x)
    if n < 2:
        return None
    idx = list(range(n))
    if n > cap:
        step = n / float(cap)
        idx = [int(i * step) for i in range(cap)]
    conc = disc = tx = ty = 0
    for a in range(len(idx)):
        ia = idx[a]
        for b in range(a + 1, len(idx)):
            ib = idx[b]
            dx = x[ia] - x[ib]
            dy = y[ia] - y[ib]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif (dx > 0) == (dy > 0):
                conc += 1
            else:
                disc += 1
    den = math.sqrt(float((conc + disc + tx) * (conc + disc + ty)))
    return (conc - disc) / den if den else None