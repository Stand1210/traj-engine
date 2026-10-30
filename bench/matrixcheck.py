"""Compare a candidate `reports/` tree against the committed one, output by output.

Why this module exists
----------------------
`bench.runner` exits 0 when every regime clears its gates. `bench.scorecard --check` exits 0 when
the README agrees with the committed `reports/`. `bench.reprocheck` exits 0 when the committed
dataset is what the committed generator produces. None of them compares *two runs of the
pipeline*.

That leaves a hole exactly the shape of this project's central claim. A change that keeps every
metric inside its gate band while moving its value -- a silhouette tie broken the other way, a
dict iteration order leaking into consensus voting, a platform-dependent float path -- passes all
three of those gates and silently invalidates every number published in the README, the patent
disclosure and the methodology document. Gate bands are wide by design (F1 >= 0.70, ARI >= 0.55);
the published figures are quoted to four decimals.

So: run the matrix into a scratch `--out` directory and compare it against the committed run.

    python -m bench.runner --regimes R1,R2,R3,R4,R5,R6,R7,R8 --out /tmp/reports-ci
    python -m bench.matrixcheck --candidate /tmp/reports-ci

Three layers, strongest first
----------------------------
1. `scores.jsonl` -- sha256 of the whole file. This is the per-trace pipeline output (S, the five
   dimensions, gate multipliers, LMDI contributions, tier, alert flags, evidence). It carries no
   timing field of any kind, so byte-identity is a meaningful claim and it subsumes every metric
   below it: if all 4,000 traces score identically, the aggregates cannot differ.
2. `metrics.json` -- leaf by leaf, with lists expanded by index so that a reordered list counts as
   a difference instead of slipping through. Measured over the committed run: 379-437 leaves per
   regime (R1 has 423), of which exactly 6 are machine-dependent and excluded, leaving 373-431
   compared values per regime and 3,334 across the full matrix.
3. `report.md` -- full text, with the machine-dependent lines masked. Measured by diffing a real
   second run of the pipeline, not by reading `render_md()`: exactly two lines move, the header's
   wall clock (`\u5899\u949f 73.7s`, emitted at `bench/runner.py:747`) and the per-stage timing
   line (`- \u8ba1\u65f6 {...}`, emitted at `bench/runner.py:892`).

   The second one was found the hard way and is recorded here so it does not get "simplified"
   away. The first draft of this module masked only the wall clock, on the strength of a grep for
   the literal string `timings` -- which does not appear anywhere in the rendered Markdown,
   because the label there is Chinese. Copy-based tests could not catch the error either, since
   they compare a committed file against a copy of itself. Only an end-to-end second run
   (`bench.runner --regimes R4 --out <scratch>`, 95.5s) exposed it, at line 114 of the report.

Excluding the wall clock is not a convenience, it is forced by measurement. Three solo runs of the
full matrix on the same idle dev box totalled 782s / 743s / 747s (max spread 5.2%), and R1 alone
measured 95.6s and 100.7s on two consecutive runs -- while every non-timing leaf of every regime
was identical to the last bit across all three. That is the same rationale as
`bench.scorecard._mask_wall()`, applied one level down.

Float comparison
----------------
Exact equality by default, because the claim being tested is bit-reproducibility and a tolerance
would quietly defeat it. The one special case is NaN, which is not equal to itself.

`--rel-tol REL` relaxes floats and *bare decimal-literal strings*, and exists for one measured
reason. The committed baseline was produced on Windows/MSVC. IEEE-754 does not require `exp`,
`log`, `erf`, `erfc` or `pow` to be correctly rounded, and this codebase calls `math.log` 17
times, `math.exp` 7 times, `math.erfc` once and uses `**` 107 times -- including
`bench/generate.py:765`'s `lat = math.exp(math.log(med) + sig * z_l)` and `kernel/baseline.py:543`'s
erfc-based normal CDF. glibc and the MSVC CRT are different implementations, so a run on Linux may
differ in the last bit.

MEASURED, not assumed. Run 40995616332 of `.github/workflows/matrix.yml` re-ran the whole
8-regime pipeline on ubuntu-24.04 (Python 3.11.17 / GCC 13.3.0) and diffed it against this
Windows-produced baseline: 3334 metric leaves, of which 58 differ, in 5 of 8 regimes.

  * The *dataset* is bit-identical. `bench.reprocheck --numeric-tol 1e-12` on the same runner
    reported a worst deviation of `0.000e+00`, so glibc's exp/log agree with the MSVC CRT to the
    last bit for every value `bench/generate.py` feeds them. The tolerance was never used.
  * The *pipeline* is not, and the divergence is confined to one leaf: every one of the 58 is
    `a_cal`, the isotonic-calibrated anomaly probability, worst deviation `4.441e-16` = 2 ulp.
    The causal chain is fully identified -- `math.erfc` at `kernel/baseline.py:543` is the only
    transcendental the pipeline calls that the generator does not (the generator uses `math.erf`,
    `generate.py:553`), it perturbs the *unrounded* `a_raw` held in `stage`, and
    `IsotonicCalibrator._one` at `kernel/calib.py:93` interpolates linearly between knots, so a
    trace landing strictly between two knots inherits the wobble while one landing on a knot
    returns it bit-exact. That is why only 4-18 traces per regime move.
  * Nothing cascaded. F1 / P@50 / FPR / AUC / ARI, all five dimension scores, the grade bands and
    every LMDI contribution are bit-identical, and all 8 regimes still report `gates=ALL-PASS`.
    The 1-ulp comparison flip feared below did not occur, because the emitted `a_raw` is rounded
    to 5 decimals (`bench/runner.py:723`) and every gate band is 4 decimals wide.

Why strings are included. `metrics.json` stores each gate reading as a *pre-rendered* string --
66 such leaves across the matrix, in 11 `gates.*.got` paths -- so the data and `report.md` cannot
drift apart. Ten of the eleven render to 3-4 decimals, which a 2-ulp wobble cannot reach; the
eleventh is `gates.zero_residual.got`, printed as `%.3e` of a quantity that *is* pure rounding
error. Linux produced `'9.415e-14'` against the committed `'9.370e-14'` -- three significant
digits of noise, an absolute difference of 4.5e-16 on a 0-100 score scale -- and a type-blind
comparison failed the whole leg on it. Recognising a bare decimal literal (`NUMSTR_FULL`) fixes
that without weakening anything: regime ids, PASS/FAIL verdicts and version strings do not parse,
so they stay byte-exact, and a leaf that *changes type* from float to string still fails because
`same_value` compares types first.

No `--abs-tol` knob was added; that was considered and rejected. `within()` floors its
denominator at 1.0, so for any leaf below magnitude 1 the relative test already *is* an absolute
one. A second tolerance would only create a way for the two to disagree.

Two consequences are worth stating plainly. First, `--rel-tol 1e-12` is still eight orders of
magnitude tighter than the smallest change an algorithmic edit can produce: the gate bands are
four decimals wide and the published figures move by >= 1e-4 when anything real changes, so a
tolerance at that level cannot hide a regression. Second, a last-bit difference can in principle
flip a float *comparison* and cascade -- a novelty score one ulp either side of its threshold
changes pool membership, which changes `n_pool`, which changes every aggregate downstream. That is
not noise to be tolerated away; if it happens, the leaf-level diff names the exact metric where it
started, which is the useful outcome.

The worst relative deviation actually observed is printed, so a run on a new platform measures its
own portability instead of assuming it. A deviation of 0.0 means the platform is bit-reproducible
and the tolerance was never used.

Run:
    python -m bench.matrixcheck --candidate DIR            # all 8 regimes required, exact
    python -m bench.matrixcheck --candidate DIR --regimes R1,R4
    python -m bench.matrixcheck --candidate DIR --rel-tol 1e-12   # portable mode (CI on Linux)
    python -m bench.matrixcheck --candidate DIR --allow-missing   # partial local runs

Exit 0 when every layer of every requested regime agrees, 1 on any difference or a missing regime
(unless --allow-missing), 2 on a bad invocation. Console output is ASCII only.
"""
import argparse
import hashlib
import io
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COMMITTED = os.path.join(ROOT, "reports")
REGIMES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]

# Machine-dependent leaves of metrics.json. Measured, not assumed: a full leaf dump of all 8
# regimes gives 379-437 leaves each, and these 6 are the only ones that move between runs of
# identical code on an identical dataset on the same box. Everything else -- including the 84-88
# list elements per regime, which flatten() expands by index -- is reproducible to the last bit.
MACHINE_LEAVES = frozenset(["wall_s"])
MACHINE_PREFIXES = ("timings.",)

# The two machine-dependent lines rendered into report.md. Two, not one -- the timing line is
# easy to miss because its label is Chinese; see the docstring for how that nearly shipped.
WALL_MASK = re.compile(u"\u5899\u949f [0-9.]+s")
WALL_REPL = u"\u5899\u949f <WALL>s"
TIMINGS_MASK = re.compile(u"^- \u8ba1\u65f6 \\{.*\\}$", re.M)
TIMINGS_REPL = u"- \u8ba1\u65f6 <TIMINGS>"

# A *bare decimal literal* and nothing else. Admits '9.370e-14', '-0.5', '1.0000'.
# Rejects '', ' 1.5', 'nan', 'inf', '0x10', '1_000', 'R1', 'PASS',
# 'bench-gen-v3.1.0' -- i.e. every regime id, verdict and version string in metrics.json
# stays byte-exact under any tolerance. NUMSTR_TOKEN is the same grammar unanchored, for
# pulling the numbers back out of a rendered report.md line.
NUMSTR_FULL = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
NUMSTR_TOKEN = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")

CHUNK = 1 << 20


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def flatten(obj, pre=""):
    """Dict/list -> {"a.b.0": leaf}. Lists are indexed so a reordered list is a difference."""
    out = {}
    if isinstance(obj, dict):
        for key in obj:
            out.update(flatten(obj[key], pre + str(key) + "."))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            out.update(flatten(item, pre + str(i) + "."))
    else:
        out[pre.rstrip(".")] = obj
    return out


def is_machine(path):
    return path in MACHINE_LEAVES or path.startswith(MACHINE_PREFIXES)


def numstr(v):
    """The float a bare-decimal-literal string denotes, else None. See NUMSTR_FULL."""
    if not isinstance(v, str) or not NUMSTR_FULL.match(v):
        return None
    return float(v)


def within(a, b, rel_tol):
    """The one tolerance test in this module: |a-b| <= rel_tol * max(1, |a|).

    The 1.0 floor in the denominator is what makes a separate --abs-tol unnecessary.
    For a leaf whose magnitude is below 1 the test is already absolute, so the
    zero-residual noise floor (9.370e-14 vs 9.415e-14 -> 4.5e-16) is absorbed, while a
    real move in the same field (>= 1e-4) is not.
    """
    return abs(a - b) <= rel_tol * max(1.0, abs(a))


def numeric_pair(a, b, rel_tol):
    """(comparable_as_floats, deviation). Strings qualify only when a tolerance is set,
    so in exact mode this module behaves as it always did."""
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True, 0.0
        return True, rel_dev(a, b)
    if rel_tol > 0.0:
        fa, fb = numstr(a), numstr(b)
        if fa is not None and fb is not None:
            return True, rel_dev(fa, fb)
    return False, 0.0


def same_value(a, b, rel_tol=0.0):
    """Exact by default; rel_tol > 0 relaxes floats and decimal-float string literals.

    Types are compared first on purpose: a leaf that changes from float to string is a
    schema change, not rounding, and must fail even when the numbers agree.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
        if a == b:
            return True
        return rel_tol > 0.0 and within(a, b, rel_tol)
    if rel_tol > 0.0 and isinstance(a, str):
        fa, fb = numstr(a), numstr(b)
        if fa is not None and fb is not None:
            return within(fa, fb, rel_tol)
    return a == b


def rel_dev(a, b):
    """Relative deviation, floored at 1.0 in the denominator so 0.0 vs 1e-300 is not infinite."""
    return abs(a - b) / max(1.0, abs(a))


def compare_numeric(path_a, path_b, rel_tol):
    """Structural comparison of two JSONL (or JSON) files; the fallback after sha256 disagrees.

    Line counts, keys and every non-float value must match exactly; floats must match within
    rel_tol relative. Reports the worst deviation observed so the caller can publish a measurement
    instead of an assumption. Still catches tampering that a tolerance might seem to excuse: a
    deleted record changes the line count, a CRLF flip or a BOM makes the line fail to parse, an
    edited string or int differs exactly.

    Shared with bench.reprocheck on purpose -- one definition of "leaf" and one definition of
    "close enough", so the two checkers cannot drift apart in what they count as a difference.
    """
    out = {"ok": False, "note": "", "n_leaves": 0, "n_floatdiff": 0,
           "worst_rel": 0.0, "worst_at": None}
    jsonl = path_a.endswith(".jsonl")
    raw_a = open(path_a, "rb").read()
    raw_b = open(path_b, "rb").read()

    # Reject CR outright instead of letting text mode hide it. Measured, and the measurement is
    # the whole reason this block exists: io.open(..., encoding="utf-8") applies universal-newline
    # translation, str.splitlines() also splits on \r\n, and json.loads() accepts a trailing \r
    # as JSON whitespace. Those three normalisations compose, so a full LF -> CRLF conversion of
    # all 240 MB -- exactly the damage a global core.autocrlf=true does to a checkout that missed
    # .gitattributes -- compared clean under this fallback. The dataset contract is LF-only: every
    # writer passes newline="\n" and .gitattributes marks *.jsonl binary so no checkout can
    # rewrite it, so a CR byte anywhere is contract damage and never something to tolerate.
    cr_a, cr_b = raw_a.count(b"\r"), raw_b.count(b"\r")
    if cr_a or cr_b:
        out["note"] = ("carriage return present (%d in the committed-side file, %d in the "
                       "candidate-side file) -- the dataset contract is LF-only, see "
                       ".gitattributes" % (cr_a, cr_b))
        return out

    try:
        if jsonl:
            la = raw_a.decode("utf-8").split("\n")
            lb = raw_b.decode("utf-8").split("\n")
        else:
            la = [raw_a.decode("utf-8")]
            lb = [raw_b.decode("utf-8")]
    except (UnicodeDecodeError, ValueError) as exc:
        out["note"] = "unreadable as UTF-8 text (%s: %s) -- BOM or encoding damage" % (
            type(exc).__name__, exc)
        return out
    if len(la) != len(lb):
        out["note"] = "record count differs: %s=%d %s=%d" % (
            os.path.basename(path_a), len(la), os.path.basename(path_b), len(lb))
        return out
    for lineno, (xa, xb) in enumerate(zip(la, lb), 1):
        if not xa.strip() and not xb.strip():
            continue
        try:
            fa = flatten(json.loads(xa))
            fb = flatten(json.loads(xb))
        except ValueError as exc:
            out["note"] = "line %d does not parse (%s) -- CRLF/BOM/truncation damage" % (
                lineno, exc)
            return out
        for k in sorted(set(fa) | set(fb)):
            out["n_leaves"] += 1
            if k not in fa or k not in fb:
                out["note"] = "line %d leaf %s present on only one side" % (lineno, k)
                return out
            va, vb = fa[k], fb[k]
            if isinstance(va, float) and isinstance(vb, float):
                if va == vb:
                    continue
                dev = rel_dev(va, vb)
                out["n_floatdiff"] += 1
                if dev > out["worst_rel"]:
                    out["worst_rel"] = dev
                    out["worst_at"] = "line %d leaf %s: %r vs %r" % (lineno, k, va, vb)
                if dev > rel_tol:
                    out["note"] = ("line %d leaf %s exceeds tolerance: %r vs %r "
                                   "(rel dev %.3e > %.0e)" % (lineno, k, va, vb, dev, rel_tol))
                    return out
            elif not same_value(va, vb):
                out["note"] = "line %d leaf %s differs exactly: %r vs %r" % (lineno, k, va, vb)
                return out
    out["ok"] = True
    out["note"] = ("%d float leaves differ within %.0e (worst %.3e at %s)"
                   % (out["n_floatdiff"], rel_tol, out["worst_rel"], out["worst_at"])
                   ) if out["n_floatdiff"] else "structurally identical, no float deviation"
    return out


def mask_report(text):
    """Strip the machine-dependent lines. Returns (masked_text, n_tokens_masked)."""
    n = len(WALL_MASK.findall(text)) + len(TIMINGS_MASK.findall(text))
    return TIMINGS_MASK.sub(TIMINGS_REPL, WALL_MASK.sub(WALL_REPL, text)), n


def compare_scores(rid, cand_dir, comm_dir, rel_tol=0.0):
    a = os.path.join(comm_dir, rid, "scores.jsonl")
    b = os.path.join(cand_dir, rid, "scores.jsonl")
    for p, tag in ((a, "committed"), (b, "candidate")):
        if not os.path.exists(p):
            return {"ok": False, "note": "%s scores.jsonl absent: %s" % (tag, p),
                    "worst_rel": 0.0, "bytes": "-"}
    sa, sb = sha256(a), sha256(b)
    out = {"sha_committed": sa[:16], "sha_candidate": sb[:16],
           "bytes": os.path.getsize(a), "worst_rel": 0.0}
    if sa == sb:
        out["ok"] = True
        out["note"] = ""
        return out
    if rel_tol <= 0.0:
        out["ok"] = False
        out["note"] = "sha256 differs"
        return out
    num = compare_numeric(a, b, rel_tol)
    out["ok"] = num["ok"]
    out["note"] = num["note"]
    out["worst_rel"] = num.get("worst_rel", 0.0)
    return out


def compare_metrics(rid, cand_dir, comm_dir, max_diffs, rel_tol=0.0):
    a = os.path.join(comm_dir, rid, "metrics.json")
    b = os.path.join(cand_dir, rid, "metrics.json")
    for p, tag in ((a, "committed"), (b, "candidate")):
        if not os.path.exists(p):
            return {"ok": False, "note": "%s metrics.json absent" % tag, "diffs": [], "n": 0,
                    "excluded": 0, "worst_rel": 0.0}
    fa = flatten(json.load(io.open(a, encoding="utf-8")))
    fb = flatten(json.load(io.open(b, encoding="utf-8")))
    excluded = len([k for k in fa if is_machine(k)]) + len(
        [k for k in fb if is_machine(k) and k not in fa])
    keys = sorted(set(fa) | set(fb))
    diffs = []
    worst = 0.0
    n_tol = 0
    for k in keys:
        if is_machine(k):
            continue
        isn, dev = numeric_pair(fa.get(k), fb.get(k), rel_tol) if (k in fa and k in fb) else (False, 0.0)
        if k not in fa:
            diffs.append("%s: only in candidate (%r)" % (k, fb[k]))
        elif k not in fb:
            diffs.append("%s: only in committed (%r)" % (k, fa[k]))
        elif not same_value(fa[k], fb[k], rel_tol):
            if isn:
                worst = max(worst, dev)
            diffs.append("%s: committed=%r candidate=%r" % (k, fa[k], fb[k]))
        elif isn and dev > 0.0:
            # inside tolerance, but record it: this is the measured portability signal
            worst = max(worst, dev)
            n_tol += 1
    return {"ok": not diffs, "diffs": diffs[:max_diffs], "n": len(keys) - excluded,
            "excluded": excluded, "worst_rel": worst, "n_diff": len(diffs), "n_tol": n_tol,
            "note": ("" if n_tol == 0 else
                     "%d metric leaf/leaves differ, all inside the tolerance" % n_tol)}


def line_same_modulo_numbers(x, y, rel_tol):
    """True iff two report.md lines differ only in their numeric tokens.

    Two clauses, and the first is what keeps this from being a hole. Strip every numeric
    token and the residue must still be byte-identical, so '- F1 0.838' vs '- F2 0.838'
    fails: the numbers agree, the words do not. Only then are the tokens paired up in
    order and held to the same `within()` test used for float leaves.
    """
    tx, ty = NUMSTR_TOKEN.findall(x), NUMSTR_TOKEN.findall(y)
    if len(tx) != len(ty):
        return False
    if NUMSTR_TOKEN.sub("\x00", x) != NUMSTR_TOKEN.sub("\x00", y):
        return False
    return all(within(float(a), float(b), rel_tol) for a, b in zip(tx, ty))


def compare_report(rid, cand_dir, comm_dir, rel_tol=0.0):
    a = os.path.join(comm_dir, rid, "report.md")
    b = os.path.join(cand_dir, rid, "report.md")
    for p, tag in ((a, "committed"), (b, "candidate")):
        if not os.path.exists(p):
            return {"ok": False, "note": "%s report.md absent" % tag, "line": None, "masked": 0}
    ta = io.open(a, encoding="utf-8").read()
    tb = io.open(b, encoding="utf-8").read()
    ma, na = mask_report(ta)
    mb, nb = mask_report(tb)
    if na != nb:
        return {"ok": False, "note": "mask count differs: committed=%d candidate=%d "
                                     "(a machine-dependent line was added or removed)"
                % (na, nb), "line": None, "masked": na}
    if ma == mb:
        return {"ok": True, "note": "", "line": None, "masked": na, "tolerated": 0}
    la, lb = ma.splitlines(), mb.splitlines()
    if len(la) != len(lb):
        return {"ok": False, "note": "report.md differs after masking wall clock + timings",
                "line": "line count: committed=%d candidate=%d" % (len(la), len(lb)),
                "masked": na, "tolerated": 0}
    first = None
    ntol = 0
    for i in range(len(la)):
        x, y = la[i], lb[i]
        if x == y:
            continue
        if rel_tol > 0.0 and line_same_modulo_numbers(x, y, rel_tol):
            ntol += 1
            continue
        first = "line %d: committed=%r candidate=%r" % (i + 1, x[:90], y[:90])
        break
    if first is None:
        return {"ok": True, "masked": na, "tolerated": ntol, "line": None,
                "note": "%d report.md line(s) differ only in their numeric tokens"
                        % ntol}
    return {"ok": False, "note": "report.md differs after masking wall clock + timings",
            "line": first, "masked": na, "tolerated": ntol}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--candidate", required=True,
                    help="directory holding the new run's R*/{scores.jsonl,metrics.json,report.md}")
    ap.add_argument("--committed", default=COMMITTED, help="default: <repo>/reports")
    ap.add_argument("--regimes", default=",".join(REGIMES))
    ap.add_argument("--rel-tol", type=float, default=0.0, metavar="REL",
                    help="accept this relative deviation on floats (default 0 = exact). "
                         "Portable mode for a different libc; ints/strings/lists stay exact.")
    ap.add_argument("--allow-missing", action="store_true",
                    help="skip regimes absent from the candidate instead of failing")
    ap.add_argument("--max-diffs", type=int, default=12)
    args = ap.parse_args(argv)

    ids = [x.strip() for x in args.regimes.split(",") if x.strip()]
    unknown = [r for r in ids if r not in REGIMES]
    if unknown:
        print("unknown regimes: %s (known: %s)" % (", ".join(unknown), ", ".join(REGIMES)))
        return 2
    if not 0.0 <= args.rel_tol < 1.0:
        print("--rel-tol must be in [0, 1); got %r" % args.rel_tol)
        return 2
    for d, tag in ((args.candidate, "candidate"), (args.committed, "committed")):
        if not os.path.isdir(d):
            print("%s dir does not exist: %s" % (tag, d))
            return 2

    print("=== matrixcheck: candidate vs committed ===")
    print("candidate: %s" % args.candidate)
    print("committed: %s" % args.committed)
    print("floats:    %s" % ("exact equality" if args.rel_tol <= 0.0
                              else "relative tolerance %.0e" % args.rel_tol))
    print("excluded as machine-dependent: %s + %s*"
          % (", ".join(sorted(MACHINE_LEAVES)),
             "/".join(p.rstrip(".") for p in MACHINE_PREFIXES)))
    print("")

    allok = True
    checked = 0
    npass = 0
    nident = 0
    nleaves = 0
    ntol_all = 0
    worst_all = 0.0
    skipped = []
    for rid in ids:
        cdir = os.path.join(args.candidate, rid)
        if not os.path.isdir(cdir):
            if args.allow_missing:
                skipped.append(rid)
                print("  [SKIP] %-3s not present in candidate" % rid)
                continue
            print("  [FAIL] %-3s candidate dir absent: %s" % (rid, cdir))
            allok = False
            continue
        sc = compare_scores(rid, args.candidate, args.committed, args.rel_tol)
        me = compare_metrics(rid, args.candidate, args.committed, args.max_diffs, args.rel_tol)
        rp = compare_report(rid, args.candidate, args.committed, args.rel_tol)
        ok = sc["ok"] and me["ok"] and rp["ok"]
        allok = allok and ok
        checked += 1
        npass += 1 if ok else 0
        nleaves += me.get("n", 0)
        ntol = me.get("n_tol", 0) + rp.get("tolerated", 0)
        ntol_all += ntol
        # byte-identical is a strictly stronger claim than PASS-under-tolerance, and the
        # two are reported separately: "0/8 identical" used to be printed whenever any
        # single regime failed, which sent the reader hunting for a total collapse when
        # the truth was 7/8 passing and 3/8 bit-for-bit.
        if ok and ntol == 0 and sc.get("sha_committed") == sc.get("sha_candidate"):
            nident += 1
        worst_all = max(worst_all, sc.get("worst_rel", 0.0), me.get("worst_rel", 0.0))
        print("  [%s] %-3s scores.jsonl %s B sha=%s|%s | metrics %d leaves (%d excluded) | "
              "report.md %s (%d lines masked)"
              % ("PASS" if ok else "FAIL", rid, sc.get("bytes", "-"),
                 sc.get("sha_committed", "-"), sc.get("sha_candidate", "-"),
                 me.get("n", 0), me.get("excluded", 0),
                 ("DIFFERS" if not rp["ok"] else
                  "identical" if rp.get("tolerated", 0) == 0 else
                  "same modulo %.0e" % args.rel_tol),
                 rp.get("masked", 0)))
        for note in (sc.get("note"), me.get("note"), rp.get("note"), rp.get("line")):
            if note:
                print("         <- %s" % note)
        for d in me.get("diffs", []):
            print("         <- %s" % d)
        if me.get("n_diff", 0) > args.max_diffs:
            print("         <- (%d differing leaves, truncated at --max-diffs %d)"
                  % (me["n_diff"], args.max_diffs))

    print("")
    print("matrixcheck: %d/%d regimes PASS, %d/%d byte-identical "
          "(%d metric leaves compared, %d differences absorbed by the tolerance)%s"
          % (npass, checked, nident, checked, nleaves, ntol_all,
             ("; skipped %s" % ", ".join(skipped)) if skipped else ""))
    if args.rel_tol > 0.0:
        print("  worst relative float deviation observed: %.3e (tolerance %.0e)"
              % (worst_all, args.rel_tol))
        if worst_all == 0.0:
            print("  -> zero deviation: this platform reproduces the run bit-for-bit, "
                  "the tolerance was never used.")
        elif allok:
            print("  -> non-zero but inside tolerance: last-bit libm differences only. "
                  "No leaf moved by more than the tolerance, so no published figure moved.")
    if not allok:
        print("  the pipeline is NOT reproducible against the committed run.")
        print("  investigate before republishing any figure from reports/ or README.md.")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())