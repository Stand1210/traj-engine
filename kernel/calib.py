"""Probability calibration + label-fused anomaly scoring (discriminative, never generative).

Three pieces, all deterministic and reproducible:
  IsotonicCalibrator : PAVA pool-adjacent-violators. Monotone *by construction*, so
                       calibrating can never reorder the alert queue - a hard requirement
                       when the same score has to be reproducible bit-for-bit in an audit.
  platt / LogReg     : parametric fallbacks when labels are scarce (isotonic overfits
                       below a few hundred labels).
  ece                : expected calibration error over equal-width bins, the gate metric.

`P(y=1 | a)` monotone and matching observed frequency is what makes an alert budget
meaningful: "top 5 per day" only equals "5% false discovery" if the score is calibrated.
"""
import math


def _sigmoid(x):
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


class IsotonicCalibrator(object):
    """PAVA isotonic regression, increasing. fit(scores, labels) -> predict(scores)."""

    def __init__(self):
        self.xs = []
        self.ys = []
        self.version = "isotonic-v0"

    def fit(self, scores, labels, weights=None):
        n = len(scores)
        w = weights or [1.0] * n
        order = sorted(range(n), key=lambda i: (scores[i], i))
        vals = []
        wts = []
        xs = []
        for i in order:
            vals.append(float(labels[i]))
            wts.append(float(w[i]))
            xs.append(float(scores[i]))
        blocks = [[vals[k], wts[k], k, k] for k in range(n)]
        merged = []
        for b in blocks:
            merged.append(b)
            while len(merged) > 1:
                a = merged[-2]
                c = merged[-1]
                va = a[0] / a[1]
                vc = c[0] / c[1]
                if va <= vc + 1e-15:
                    break
                merged.pop()
                merged.pop()
                merged.append([a[0] + c[0], a[1] + c[1], a[2], c[2]])
        self.xs = []
        self.ys = []
        for b in merged:
            x_lo = xs[b[2]]
            x_hi = xs[b[3]]
            y = b[0] / b[1] if b[1] else 0.0
            self.xs.append(x_lo)
            self.ys.append(y)
            if x_hi > x_lo:
                self.xs.append(x_hi)
                self.ys.append(y)
        return self

    def predict(self, scores):
        if not self.xs:
            return [0.5] * len(scores)
        out = []
        for s in scores:
            out.append(self._one(float(s)))
        return out

    def _one(self, s):
        xs, ys = self.xs, self.ys
        if s <= xs[0]:
            return ys[0]
        if s >= xs[-1]:
            return ys[-1]
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= s:
                lo = mid
            else:
                hi = mid
        if xs[hi] == xs[lo]:
            return ys[lo]
        t = (s - xs[lo]) / (xs[hi] - xs[lo])
        return ys[lo] + t * (ys[hi] - ys[lo])


def platt(scores, labels, iters=400, lr=0.1, l2=1e-4):
    """Platt scaling: P = sigmoid(a*s + b) fitted by gradient ascent on the log-likelihood."""
    n = len(scores)
    if n == 0:
        return (0.0, 0.0)
    mu = sum(scores) / float(n)
    sd = math.sqrt(sum((s - mu) ** 2 for s in scores) / float(n)) or 1.0
    z = [(s - mu) / sd for s in scores]
    hi = (n + 1.0) / (n + 2.0)
    lo = 1.0 / (n + 2.0)
    t = [hi if y else lo for y in labels]
    a, b = 0.0, math.log((sum(labels) + 1.0) / (n - sum(labels) + 1.0))
    for _ in range(iters):
        ga = gb = 0.0
        for i in range(n):
            p = _sigmoid(a * z[i] + b)
            e = t[i] - p
            ga += e * z[i]
            gb += e
        a += lr * (ga / n - l2 * a)
        b += lr * (gb / n)
        if abs(ga) / n < 1e-9 and abs(gb) / n < 1e-9:
            break
    return (a / sd, b - a * mu / sd)


def platt_predict(ab, scores):
    a, b = ab
    return [_sigmoid(a * s + b) for s in scores]


class LogReg(object):
    """Plain L2 logistic regression by batch gradient descent. Pure python, seeded, no deps."""

    def __init__(self, iters=400, lr=0.3, l2=1e-3):
        self.iters = iters
        self.lr = lr
        self.l2 = l2
        self.w = None
        self.mu = None
        self.sd = None
        self.version = "logreg-v0"

    def fit(self, rows, labels):
        n = len(rows)
        d = len(rows[0])
        self.mu = [sum(r[j] for r in rows) / float(n) for j in range(d)]
        sd = []
        for j in range(d):
            v = sum((r[j] - self.mu[j]) ** 2 for r in rows) / float(n)
            sd.append(math.sqrt(v) or 1.0)
        self.sd = sd
        z = [[1.0] + [(r[j] - self.mu[j]) / sd[j] for j in range(d)] for r in rows]
        w = [0.0] * (d + 1)
        for _ in range(self.iters):
            g = [0.0] * (d + 1)
            for i in range(n):
                p = _sigmoid(sum(w[k] * z[i][k] for k in range(d + 1)))
                e = labels[i] - p
                for k in range(d + 1):
                    g[k] += e * z[i][k]
            step = 0.0
            for k in range(d + 1):
                reg = 0.0 if k == 0 else self.l2 * w[k]
                w[k] += self.lr * (g[k] / n - reg)
                step = max(step, abs(self.lr * (g[k] / n - reg)))
            if step < 1e-9:
                break
        self.w = w
        return self

    def predict(self, rows):
        d = len(self.mu)
        out = []
        for r in rows:
            z = [1.0] + [(r[j] - self.mu[j]) / self.sd[j] for j in range(d)]
            out.append(_sigmoid(sum(self.w[k] * z[k] for k in range(d + 1))))
        return out


def ece(probs, labels, bins=10):
    n = len(probs)
    if n == 0:
        return 0.0
    buck = [[] for _ in range(bins)]
    for p, y in zip(probs, labels):
        k = min(bins - 1, max(0, int(p * bins)))
        buck[k].append((p, y))
    tot = 0.0
    for b in buck:
        if not b:
            continue
        conf = sum(p for p, _ in b) / float(len(b))
        acc = sum(1 for _, y in b if y) / float(len(b))
        tot += (len(b) / float(n)) * abs(acc - conf)
    return tot


def reliability(probs, labels, bins=10):
    buck = [[] for _ in range(bins)]
    for p, y in zip(probs, labels):
        buck[min(bins - 1, max(0, int(p * bins)))].append((p, y))
    out = []
    for i, b in enumerate(buck):
        if not b:
            continue
        out.append({"bin": i, "n": len(b),
                    "conf": sum(p for p, _ in b) / float(len(b)),
                    "acc": sum(1 for _, y in b if y) / float(len(b))})
    return out