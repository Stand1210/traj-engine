"""Concept-drift watch on the cell-normalized metric stream (Page-Hinkley CUSUM).

The detector never looks at raw latency. It looks at the robust z of log-latency *within the
trace's own analysis cell*, measured against a reference window taken before any drift, and
recentred on that window's own mean. That normalization is what makes the test usable on
heterogeneous agent traffic at all: a raw latency stream that interleaves 2s lookups with 60s
analyses has no stable mean, so a CUSUM on it accumulates positive drift from the mixture alone
and raises a changepoint alarm on a perfectly stationary system (measured: 1065 false drift
flags on 4000 stationary traces).

One-sided (upward) because slower-and-costlier is the operationally dangerous direction;
negate the input to watch the other side.

Why the increments are winsorized
  One latency_spike trace carries a cell-normalized z of 12, which on its own exceeds any
  sane decision constant and raises a changepoint alarm on a perfectly stationary system.
  That was measured: every non-drifting benchmark regime was flagged as drifting and 88-242
  innocent traces per regime were gated down by the drift_suspect multiplier. So z is the
  genuine modified z 0.6745*(y-med)/MAD (the previous form cancelled the 0.6745 and ran at
  variance 2.2) and is winsorized at +-Z_CLIP = +-3.5, the Iglewicz-Hoaglin trigger the
  magnitude layer already uses.

Why lambda is calibrated and the window is length-restricted
  Winsorizing was necessary but not sufficient: 3 of the 7 stationary regimes still alarmed.
  Measured on the monitored tails, the increments have variance 0.97-1.76 and kurtosis
  3.5-4.4, so the unit-variance Gaussian assumption behind Page-Hinkley's exp(-2*delta*lambda)
  ~ 2.5e-3 bound simply does not hold, and the fixed lambda = 6 turned out to sit *inside*
  the null distribution of the statistic it was thresholding - the seven stationary regimes
  scored 5.06, 5.15, 5.70, 5.97, 7.72, 8.54 and 10.38. Three of seven false alarms.
  Inspecting the triggering windows says what was really happening: they were 13-23
  observations long with a mean z of 0.87-1.09, i.e. a burst of individual anomalies, not a
  displacement of the population. The genuine x1.6 drift on the benchmark produces a
  1999-observation window with mean z 0.762 - same height, three orders of magnitude more
  length. Two corrections follow, and neither is a fitted constant:
    1. MINIMUM SEGMENT LENGTH. Drift is a claim about a population, so it has to be supported
       by a population-sized window: >= max(50, 5% of the monitored stream). A burst of 18
       anomalies can no longer be reported as a change point at all.
    2. RIGHT-ANCHORED WINDOW. Concept drift means the population moved *and stayed moved*, so
       the alternative hypothesis is a segment running to the end of the stream and the change
       point is where that segment starts. Letting the window end anywhere still admits
       transient excursions: on the heavy-overlap regime, where impure cells leave the
       normalized stream a little residual bias, the unrestricted statistic found a
       368-observation window in the middle of a stationary stream and reported its start as a
       change point (59.8% of that window above the reference median, against 77.5% for the
       genuine x1.6 drift). Anchoring to the last observation makes that impossible - a
       transient bump is now averaged against the stationary traffic that follows it.
    3. BOOTSTRAP-CALIBRATED LAMBDA. The threshold is the (1 - DRIFT_ALPHA) quantile of the
       same right-anchored, length-restricted statistic evaluated on circular block bootstrap
       replicates of the reference window, resampled to the monitored length (Kunsch 1989). The
       reference window is drift-free by construction and carries the same anomaly bursts, the
       same variance and the same short-range dependence as the monitored stream, so the null
       is estimated rather than assumed. lambda is therefore expressed in the units of the data
       instead of in the units of a Gaussian that the data is not.
  Individual extremes remain the anomaly detector's job. This separation of concerns is the
  point: drift answers "did the population move", detection answers "is this trace wrong",
  and letting one trace answer both is how drift alarms get muted by the first on-call
  rotation.

Why the increments are signs and not magnitudes
  delta is an indifference zone, and that reading only holds if the in-control mean of the
  increment is zero. For a magnitude CUSUM on modified z it never is: the modified z of a
  skewed log-scale variable has a mean of -0.01 to -0.22 depending on the regime, and the mean
  of the monitored tail differs from the mean of the reference window by +0.04 to +0.13 on
  stationary traffic purely through that skew. Centring on the reference mean removes the
  level but not the sensitivity - the statistic is still a sum of magnitudes, so a 0.05 sigma
  wobble in the mean of a skewed variable accumulates over thousands of observations and
  crosses a threshold that was calibrated on a slightly different wobble. Measured: two of the
  seven stationary regimes still alarmed, and both by a margin of 1-2 units against a
  threshold of -24, i.e. decided by noise.
  So the CUSUM runs on the SIGN of (z - reference median) instead. Under the null the median
  of z in the reference window is zero by construction, the sign is +1 or -1 with probability
  1/2 each, and the increment mean is exactly zero whatever the skew of the underlying
  variable does. delta becomes directly readable as an operational statement - 0.10 means the
  share of traffic above the pre-drift median has moved from 50% to 55% and stayed there -
  and the bootstrap threshold is calibrated on a bounded, symmetric, unit-variance series
  instead of on a skewed one whose variance differs by a factor of 1.8 between regimes.
  The cost is explicit and accepted: a shift that severely affects a small sub-population
  moves the median little and will not be reported as drift. That is the separation of
  concerns again - individual extremes are the anomaly detector's job, drift is a statement
  about where the bulk of the traffic now sits. The magnitude z is still computed and still
  used, for the suspect list and for the reported effect size.

Why the reference lookup is a ladder that ends in abstention
  See cell_normalized_z. Two measured failures drove the current shape.
  (1) A cell-only lookup left cells whose reference window held a single observation, MAD
      degenerated to its 1e-9 floor, and every later trace in that cell scored |z| = 3.5 no
      matter what it did - 4.4% of the monitored stream was artifact, and a run of clipped +3.5
      is exactly what a CUSUM reads as a change point. Hence the parent-intent level.
  (2) The global level at the bottom of the ladder is worse than no level at all. On the
      sparse-cell benchmark the slowest intent (92 of 1200 traces) had too few reference
      observations at both cell and parent level and fell through to global, which mixes a 1.5s
      lookup population with a 120s analysis population and hands every slow trace a
      permanently positive z. Ordinary sampling noise in the *intent mix* then reads as a
      sustained positive sign run: statistic 45.1 against a bootstrapped lambda of 12.2, a
      false change point at index 681, on data whose per-intent medians are flat to within
      noise across the whole stream (1.53/1.46/1.64/1.51/1.70/1.59 for the fast intent).
      Detecting a population-mix shift and calling it drift is the same category error the
      whole method exists to avoid - a global yardstick over a multimodal population - so the
      ladder now abstains instead. An abstained trace is excluded from the monitored series;
      if too many abstain, drift is reported as unmeasurable, not as absent.
"""
import math
import random

# Indifference zone of the sign-CUSUM, in the only units a sign score can express: a sustained
# mean sign of +0.10 is the share of traffic above the pre-drift reference median moving from
# 50% to 55% and staying there. Declared, not fitted. The benchmark's x1.6 latency drift moves
# it to ~0.38 (69% above the old median), three and a half times the indifference zone.
DEFAULT_DELTA = 0.10
# Fallback decision constant, used only when the reference window is too short to bootstrap.
DEFAULT_LAMBDA = 6.0
Z_SUSPECT = 2.0
Z_CLIP = 3.5
# Minimum reference observations before a level of the ladder is trusted with a median AND a
# MAD. 30 is the same n at which baseline.credibility(n) = n/(n+KAPPA) reaches half weight, so
# the two modules hand over to their parent level at the same point.
MIN_CELL_REF = 30
MIN_PARENT_REF = 30
DRIFT_MIN_SEG_ABS = 50
DRIFT_MIN_SEG_FRAC = 0.05
# Above this share of the stream abstaining, the monitored remainder no longer represents the
# traffic and drift is reported as unmeasurable rather than as "no drift".
MAX_ABSTAIN_SHARE = 0.50
DRIFT_ALPHA = 0.01
DRIFT_BLOCK = 64
DRIFT_BOOTSTRAP_REPS = 200
DRIFT_BOOTSTRAP_SEED = 20240501


def _moments(sorted_vals):
    n = len(sorted_vals)
    if n == 0:
        return (0.0, 1e-9)
    med = sorted_vals[n // 2] if n % 2 else 0.5 * (sorted_vals[n // 2 - 1] + sorted_vals[n // 2])
    dev = sorted(abs(x - med) for x in sorted_vals)
    mad = dev[n // 2] if n % 2 else 0.5 * (dev[n // 2 - 1] + dev[n // 2])
    return (med, mad if mad > 1e-9 else 1e-9)


def max_suffix(vals, delta=DEFAULT_DELTA, min_len=1):
    """Largest sum of (x - delta) over windows that END at the last observation.

    Returns (value, start, end = len(vals) - 1).

    Page-Hinkley restricted to the alternative hypothesis concept drift actually asserts: the
    process shifted somewhere and stayed shifted. Writing it as a suffix-sum maximum instead of
    stopping at the first crossing has two payoffs - `start` is the change-point estimate, and
    the length restriction that keeps anomaly bursts out is expressible at all.
    """
    n = len(vals)
    if n < min_len or min_len < 1:
        return (float("-inf"), 0, -1)
    best, bstart, acc = float("-inf"), 0, 0.0
    for i in range(n - 1, -1, -1):
        acc += vals[i] - delta
        if (n - i) >= min_len and acc > best:
            best, bstart = acc, i
    return (best, bstart, n - 1)


def _quantile(sv, q):
    if not sv:
        return None
    if q <= 0.0:
        return sv[0]
    if q >= 1.0:
        return sv[-1]
    pos = q * (len(sv) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sv) - 1)
    return sv[lo] + (sv[hi] - sv[lo]) * (pos - lo)


def _median(vals):
    if not vals:
        return 0.0
    sv = sorted(vals)
    n = len(sv)
    return sv[n // 2] if n % 2 else 0.5 * (sv[n // 2 - 1] + sv[n // 2])


def sign_score(vals, centre=0.0):
    """+1 above the reference median, -1 below, 0 on it. Bounded, symmetric, mean 0 in control."""
    return [1.0 if v > centre else (-1.0 if v < centre else 0.0) for v in vals]


def calibrate_lambda(ref_z, n_monitored, delta=DEFAULT_DELTA, min_len=1,
                     alpha=DRIFT_ALPHA, block=DRIFT_BLOCK, reps=DRIFT_BOOTSTRAP_REPS,
                     seed=DRIFT_BOOTSTRAP_SEED):
    """(1-alpha) quantile of the right-anchored CUSUM statistic under the reference null.

    Takes the reference *z values*, not their signs, and draws TWO circular block bootstrap
    resamples per replicate:

      resample A, length = reference length, supplies the centre `median(A)`;
      resample B, length = n_monitored, is scored against that centre.

    Re-estimating the centre inside every replicate is what makes the null honest. The live
    detector scores the monitored window against a centre estimated from the first 20% of the
    stream only, and that estimate carries error. On the sparse-cell benchmark the reference
    window holds 112 / 67 / 30 observations for the three supported cells, and a median from
    30 log-normal samples is off by enough to push an entire cell's tail to 69% above the
    pooled centre. A bootstrap over a series whose centre is already exactly its own median
    cannot reproduce that error, so it returns a threshold far too small - measured on R4
    before this change: lambda 10.6 against a statistic of 44.6, a false change point at index
    406, on data whose per-intent medians are flat to within sampling noise. Splitting the
    reference into "the part that fixes the centre" and "the part that gets scored" injects
    exactly the estimation noise the live detector is exposed to.

    Circular blocks keep the marginal distribution AND the short-range dependence of the
    reference window (iid resampling would destroy the latter and understate the threshold),
    and resampling B to the monitored length matters because the statistic grows with the
    number of candidate change points it gets to choose from - a threshold calibrated at the
    reference length would be far too small at four times that length.
    """
    m = len(ref_z)
    if m < max(2 * block, min_len) or n_monitored < min_len:
        return None
    rng = random.Random(seed)

    def blocks(target):
        out = []
        while len(out) < target:
            start = rng.randrange(m)
            take = min(block, target - len(out))
            for t in range(take):
                out.append(ref_z[(start + t) % m])
        return out

    stats = []
    for _ in range(reps):
        centre = _median(blocks(m))
        stats.append(max_suffix(sign_score(blocks(n_monitored), centre), delta, min_len)[0])
    stats.sort()
    return _quantile(stats, 1.0 - alpha)


def cell_normalized_z(stream, ref_frac=0.2, min_ref=30, min_cell_ref=MIN_CELL_REF,
                      min_parent_ref=MIN_PARENT_REF):
    """stream: [(trace_id, cell, parent, value)] in time order.

    Returns (z list with None for abstained points, reference window size, per-level counts).

    The reference moments come from a two-level ladder - the trace's own analysis cell, then
    the cell's parent intent - and a level is only used when it holds enough reference
    observations to estimate both a median and a MAD. The parent intent is still a coherent
    task class, and on the sparse benchmark it has 24-100 reference observations where some of
    its cells have one; this is the same L3 -> L2 ladder the baseline module pools anchors
    through. Below that the point abstains (z = None) rather than being normalised against the
    global mixture, because a global reference turns intent-mix sampling noise into a
    sustained positive sign run. See the module docstring for the measured false change point
    that this rule removes.
    """
    kref = min(len(stream), max(min_ref, int(len(stream) * ref_frac)))
    ref = stream[:kref]
    per_cell, per_par = {}, {}
    for _t, c, par, v in ref:
        lv = math.log(max(v, 1e-9))
        per_cell.setdefault(c, []).append(lv)
        per_par.setdefault(par, []).append(lv)
    cstats = dict((c, _moments(sorted(v))) for c, v in per_cell.items()
                  if len(v) >= min_cell_ref)
    pstats = dict((p, _moments(sorted(v))) for p, v in per_par.items()
                  if len(v) >= min_parent_ref)
    zs, levels = [], {"cell": 0, "parent": 0, "abstain": 0}
    for _t, c, par, v in stream:
        if c in cstats:
            med, mad, lvl = cstats[c][0], cstats[c][1], "cell"
        elif par in pstats:
            med, mad, lvl = pstats[par][0], pstats[par][1], "parent"
        else:
            levels["abstain"] += 1
            zs.append(None)
            continue
        levels[lvl] += 1
        z = 0.6745 * (math.log(max(v, 1e-9)) - med) / mad
        zs.append(max(-Z_CLIP, min(Z_CLIP, z)))
    return zs, kref, levels


def detect_drift(stream, delta=DEFAULT_DELTA, lam=None, ref_frac=0.2,
                 min_ref=30, z_suspect=Z_SUSPECT, min_seg_abs=DRIFT_MIN_SEG_ABS,
                 min_seg_frac=DRIFT_MIN_SEG_FRAC, alpha=DRIFT_ALPHA):
    """stream: [(trace_id, cell, parent, value)] in time order -> report + suspect trace ids.

    `lam` is normally None, meaning "calibrate it from the reference window"; passing a number
    overrides the calibration and is only there for experiments.
    """
    if len(stream) < 40:
        return {"drift": False, "reason": "stream_too_short", "n": len(stream),
                "index": None, "lag_frac": None, "suspects": [], "z_mean": None}
    zs_all, kref, z_levels = cell_normalized_z(stream, ref_frac, min_ref)
    n_abstain = z_levels.get("abstain", 0)
    abstain_share = n_abstain / float(len(stream))
    base = {"n": len(stream), "ref_window": kref, "z_levels": z_levels,
            "n_abstain": n_abstain, "abstain_share": abstain_share}
    if abstain_share > MAX_ABSTAIN_SHARE:
        # Not "no drift": the monitored remainder would no longer represent the traffic.
        out = dict(base, drift=False, reason="insufficient_support", index=None,
                   lag_frac=None, suspects=[], n_monitored=len(stream) - n_abstain)
        return out
    # The CUSUM needs a contiguous series, so abstained points are dropped and every index
    # reported back to the caller is mapped to its position in the original stream.
    kept = [i for i, z in enumerate(zs_all) if z is not None]
    zs = [zs_all[i] for i in kept]
    kref_c = sum(1 for i in kept if i < kref)
    ref_z, tail_z = zs[:kref_c], zs[kref_c:]
    centre = _median(ref_z)
    sg = sign_score(zs, centre)
    ref_s, tail_s = sg[:kref_c], sg[kref_c:]
    n_mon = len(tail_s)
    min_len = max(min_seg_abs, int(round(min_seg_frac * n_mon)))
    stat, bstart, bend = max_suffix(tail_s, delta, min_len)
    lam_cal = calibrate_lambda(ref_z, n_mon, delta, min_len, alpha=alpha)
    lam_use = lam if lam is not None else (lam_cal if lam_cal is not None else DEFAULT_LAMBDA)
    hit = bool(n_mon >= min_len and stat > lam_use)
    det_c = (kref_c + bstart) if hit else None
    det = kept[det_c] if det_c is not None else None
    win = sg[det_c:(kref_c + bend + 1)] if hit else []
    suspects = []
    if det_c is not None:
        suspects = [stream[kept[j]][0] for j in range(det_c, len(zs)) if zs[j] > z_suspect]
    out = dict(base, drift=hit, index=det, n_monitored=len(zs),
            ref_window_monitored=kref_c, delta=delta, **{"lambda": lam_use})
    out.update({
            "lambda_calibrated": lam_cal,
            "lambda_source": ("override" if lam is not None else
                              ("bootstrap" if lam_cal is not None else "fallback")),
            "statistic": (stat if stat != float("-inf") else None),
            "min_seg_len": min_len,
            "window": (None if not hit else [kref + bstart, kref + bend]),
            "alpha": alpha, "z_suspect": z_suspect,
            "z_median_ref": centre,
            "z_median_tail": _median(tail_z),
            "z_mean_ref": (sum(ref_z) / float(kref_c)) if kref_c else None,
            "z_mean_tail": (sum(tail_z) / float(n_mon)) if n_mon else None,
            "sign_mean_ref": (sum(ref_s) / float(kref)) if kref else None,
            "sign_mean_tail": (sum(tail_s) / float(n_mon)) if n_mon else None,
            # The effect size an operator can read without knowing what a CUSUM is: what share
            # of the traffic inside the detected window now sits above the pre-drift median.
            "share_above_ref_median": (sum(1.0 for v in win if v > 0) / len(win)) if win else None,
            "window_len": len(win) if hit else None,
            "min_cell_ref": MIN_CELL_REF, "min_parent_ref": MIN_PARENT_REF,
            "lag_frac": (det - kref) / float(len(stream)) if det is not None else None,
            "suspects": suspects})
    return out
