"""Regeneration identity check: is the committed dataset what the committed generator produces?

Why this module exists
----------------------
`bench.coverage.dataset_provenance()` re-derives each regime's `spec_hash` with the live
generator and compares it against `data/bench_v1/<rid>/meta.json`. That catches a *stale*
dataset -- data left behind by an older generator -- and it is the check that caught the v3.1.0
regeneration leaving 7 of 8 `meta.json` carrying a key the generator no longer emitted.

It cannot catch a dataset altered *after* generation, because `spec_hash` is a hash of the regime
spec, not of the emitted bytes. A `traces.jsonl` with every LF flipped to CRLF, with one trace
deleted, or re-encoded with a BOM, still carries a valid `spec_hash` and still passes provenance.
On this dev box that is not hypothetical: `core.autocrlf=true` is set globally, so any copy that
reaches git without the `.gitattributes` rules rewrites all 240 MB of JSONL to CRLF and every sha
published in the README silently stops describing the bytes on disk.

This module closes the gap by re-running `bench.generate.build()` into a scratch directory and
comparing the result against the committed files.

Two comparison modes, and why both exist
---------------------------------------
Default (`--numeric-tol` absent) is **byte-identity**: sha256 of every emitted file. Measured on
the Windows dev box (Python 3.11, `core.autocrlf=true`, pure-LF data): regenerating R6 reproduces
`traces.jsonl` 5,672,294 B (sha256 4813fd982d4f1932...), `gt.jsonl` 695,942 B and `meta.json`
3,673 B exactly, in 1.0s; all 8 regimes plus all 8 SAMPLE.md are byte-identical in 53.0s.
`meta.json` carries no timestamp, hostname, pid or absolute-path field, which is what makes the
comparison possible at all.

Byte-identity is *not portable across C libraries*, and this is a property of the generator rather
than of the check. Measured emission precision in `bench/generate.py`:

    ts_start / ts_end   full double precision, e.g. 1767225604.0650926   <- libm-exposed
    cost                full double precision                            <- libm-exposed
    embedding           round(v, 5)      (line 1269)
    ttft                round(., 6)      (line 1031)
    latency_true        round(., 4)      (line 1326)

The full-precision fields descend directly from `lat = math.exp(math.log(med) + sig * z_l)`
(line 765). IEEE-754 does not require `exp`, `log`, `erf` or `pow` to be correctly rounded, and
the kernel plus generator use `math.log` 17 times, `math.exp` 7 times, `math.erfc` once and `**`
107 times. glibc and the MSVC CRT are different implementations, so a last-bit difference on
another platform would legitimately change the emitted bytes while every rounded field stayed put.

MEASURED, and for the dataset it did not happen. On ubuntu-24.04 (Python 3.11.17 / GCC 13.3.0) all
8 regimes and all 8 SAMPLE.md reproduced byte-identically and the run reported a worst relative
deviation of `0.000e+00`: glibc's exp/log agree with the MSVC CRT to the last bit for every value
this generator feeds them, so the tolerance was never used. The fallback stays as insurance rather
than because it is needed, and it is *not* dead weight one level up -- the pipeline does diverge on
that same runner (58 `a_cal` leaves at 2 ulp, traced to the `math.erfc` in `kernel/baseline.py:543`
that the generator never calls); `bench.matrixcheck` documents that chain in full. What the zero
here buys is a tripwire: a generator edit that starts exercising a transcendental the dataset did
not previously touch would move this measurement off 0.000e+00, which is exactly why the number is
printed instead of assumed.

`--numeric-tol REL` therefore adds a structural fallback: sha256 is still tried first (so a
platform that does reproduce bit-for-bit pays nothing and says so), and only on a byte mismatch
are both sides parsed and compared leaf by leaf -- line counts exactly, keys and non-float values
exactly, floats within `REL` relative. It prints the worst deviation actually observed, so the
first run on a new platform *measures* the portability instead of assuming it. Tampering is still
caught in this mode, and each kind is caught by a different mechanism rather than by one lucky
side effect:
a deleted record changes the line count; a CRLF flip is rejected outright on a raw CR byte count
*before* any parsing, because text-mode universal-newline translation plus `str.splitlines()` plus
`json.loads()` tolerating a trailing `\r` would otherwise normalise a whole-file LF -> CRLF
conversion away entirely; a BOM makes the first line fail to parse; an edited string or int
differs exactly; an edited float exceeds the tolerance.

SAMPLE.md is derived by `bench.show.write_sample()`, whose output path is hard-coded to
`DATA/<rid>/SAMPLE.md` and cannot be redirected, so it is checked by idempotence: sha256 before,
regenerate, sha256 after. On mismatch the bytes the check *read* are written back -- never its own
output -- because a verification tool that silently repairs the file it is verifying destroys the
evidence the operator needs. Measured: R1's SAMPLE.md is 80-93 KB and regenerates to sha256
c4b085e6f25a01f7... unchanged.

Under `--numeric-tol` a SAMPLE.md difference is a WARN, not a failure, and the reason is measured:
`bench/show.py:185` renders `ts_start=%.3f`, and at 1.767e9 one double ulp is 2.4e-7, so a
last-bit libm difference flips the printed third decimal with probability ~2.4e-4 per rendered
timestamp. With ~40 rendered timestamps per file that is ~1% per regime of a purely cosmetic
wobble. Failing a build on that would be worse than reporting it. In strict mode SAMPLE.md must
still be byte-identical.

Scratch cost: the directory is removed per regime, so peak extra disk is one regime (~45 MB), not
the whole 240 MB. Regenerating all 8 regimes takes ~35s; with `--sample`, 53s.

Run:
    python -m bench.reprocheck                       # strict, all 8 regimes
    python -m bench.reprocheck --sample              # + all 8 SAMPLE.md
    python -m bench.reprocheck --sample --numeric-tol 1e-12   # portable mode (CI on Linux)
    python -m bench.reprocheck --regimes R6 --keep

Exit 0 when every regime passes, 1 on any mismatch, 2 on a bad invocation.
Console output is ASCII only.
"""
import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time

from bench.generate import build
from bench import show as SH
# One definition of "leaf" and one definition of "close enough", shared with bench.matrixcheck on
# purpose: if the two checkers each carried their own flattener or their own comparator they could
# disagree about what is being compared, and a value one treats as a scalar and the other as a
# list would silently escape both.
from bench.matrixcheck import compare_numeric, flatten, sha256

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "bench_v1")
REGIMES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
# exactly the files bench.generate.build() writes; SAMPLE.md is derived separately by bench.show
EMITTED = ["traces.jsonl", "gt.jsonl", "meta.json"]
def check_regime(rid, scratch_root, keep=False, rel_tol=None):
    """Regenerate one regime into a private scratch dir and compare against the committed bytes."""
    rows = []
    committed_dir = os.path.join(DATA, rid)
    if not os.path.isdir(committed_dir):
        return [{"file": "-", "ok": False, "warn": False,
                 "note": "committed dir missing: %s" % committed_dir}], False, 0.0
    scratch = os.path.join(scratch_root, rid)
    if os.path.exists(scratch):
        shutil.rmtree(scratch)
    os.makedirs(scratch)
    t0 = time.time()
    try:
        build(rid, scratch_root)
    except Exception as exc:
        return [{"file": "-", "ok": False, "warn": False,
                 "note": "build(%s) raised %s: %s" % (rid, type(exc).__name__, exc)}], False, 0.0
    elapsed = time.time() - t0
    ok = True
    worst = 0.0
    for fn in EMITTED:
        a = os.path.join(committed_dir, fn)
        b = os.path.join(scratch, fn)
        row = {"file": fn, "ok": False, "warn": False, "note": ""}
        if not os.path.exists(a):
            row["note"] = "committed file absent"
        elif not os.path.exists(b):
            row["note"] = "generator did not emit it"
        else:
            sa, sb = sha256(a), sha256(b)
            row["bytes_committed"] = os.path.getsize(a)
            row["bytes_regen"] = os.path.getsize(b)
            row["sha"] = sa[:16]
            if sa == sb:
                row["ok"] = True
                row["note"] = "byte-identical"
            elif rel_tol is None:
                row["note"] = "sha256 differs"
            else:
                num = compare_numeric(a, b, rel_tol)
                row["ok"] = num["ok"]
                row["note"] = num["note"]
                worst = max(worst, num.get("worst_rel", 0.0))
        ok = ok and row["ok"]
        rows.append(row)
    rows.append({"file": "(regenerate)", "ok": True, "warn": False, "note": "%.1fs" % elapsed})
    if not keep and os.path.exists(scratch):
        shutil.rmtree(scratch)
    return rows, ok, worst


def check_sample(rid, rel_tol=None):
    """Idempotence check for SAMPLE.md: regenerate in place, compare, restore what we read."""
    path = os.path.join(DATA, rid, "SAMPLE.md")
    row = {"file": "SAMPLE.md", "ok": False, "warn": False, "note": ""}
    if not os.path.exists(path):
        row["note"] = "absent"
        return row, False
    before = open(path, "rb").read()
    sha_before = hashlib.sha256(before).hexdigest()
    try:
        SH.write_sample(rid)
    except Exception as exc:
        row["note"] = "write_sample raised %s: %s" % (type(exc).__name__, exc)
        return row, False
    after = open(path, "rb").read()
    sha_after = hashlib.sha256(after).hexdigest()
    row["bytes_committed"] = len(before)
    row["bytes_regen"] = len(after)
    row["sha"] = sha_before[:16]
    same = sha_before == sha_after
    if not same:
        # restore the bytes we read, never our own output -- see the docstring
        with open(path, "wb") as fh:
            fh.write(before)
        if rel_tol is None:
            row["note"] = "regeneration differs; input restored"
        else:
            row["ok"] = True
            row["warn"] = True
            row["note"] = ("WARN regeneration differs under --numeric-tol; input restored. "
                           "Expected: show.py renders ts_start at %%.3f where 1 ulp is 2.4e-7")
    else:
        row["ok"] = True
        row["note"] = "byte-identical"
    return row, row["ok"]


def _print_row(tag, rid, r):
    print("  [%s] %-3s %-14s committed=%s regen=%s sha=%s%s"
          % (tag, rid, r["file"], r.get("bytes_committed", "-"), r.get("bytes_regen", "-"),
             r.get("sha", "-"), ("  <- " + r["note"]) if r.get("note") else ""))


def _gen_version():
    try:
        from bench.generate import GEN_VERSION
        return GEN_VERSION
    except Exception:
        return "?"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--regimes", default=",".join(REGIMES))
    ap.add_argument("--sample", action="store_true",
                    help="also verify SAMPLE.md regenerates identically")
    ap.add_argument("--numeric-tol", type=float, default=None, metavar="REL",
                    help="on a sha256 mismatch, fall back to a structural comparison accepting "
                         "this relative deviation on floats (portable mode for a different libc)")
    ap.add_argument("--scratch", default=None, help="scratch dir (default: a temp dir)")
    ap.add_argument("--keep", action="store_true", help="keep regenerated files for inspection")
    args = ap.parse_args(argv)
    ids = [x.strip() for x in args.regimes.split(",") if x.strip()]
    unknown = [r for r in ids if r not in REGIMES]
    if unknown:
        print("unknown regimes: %s (known: %s)" % (", ".join(unknown), ", ".join(REGIMES)))
        return 2
    if args.numeric_tol is not None and not (0.0 < args.numeric_tol < 1.0):
        print("--numeric-tol must be in (0, 1); got %r" % args.numeric_tol)
        return 2

    scratch_root = args.scratch or os.path.join(tempfile.gettempdir(), "bench-reprocheck")
    if not os.path.exists(scratch_root):
        os.makedirs(scratch_root)
    mode = ("numeric-tol %.0e (sha256 tried first)" % args.numeric_tol) if args.numeric_tol \
        is not None else "strict byte-identity"
    print("=== regeneration identity (generator %s) ===" % _gen_version())
    print("mode:    %s" % mode)
    print("scratch: %s" % scratch_root)
    allok = True
    nwarn = 0
    worst_all = 0.0
    t_all = time.time()
    for rid in ids:
        rows, ok, worst = check_regime(rid, scratch_root, keep=args.keep,
                                       rel_tol=args.numeric_tol)
        allok = allok and ok
        worst_all = max(worst_all, worst)
        timing = None
        for r in rows:
            if r["file"] == "(regenerate)":
                timing = r["note"]
                continue
            nwarn += 1 if r.get("warn") else 0
            _print_row("WARN" if r.get("warn") else ("PASS" if r["ok"] else "FAIL"), rid, r)
        if timing:
            print("        %-3s regenerated in %s" % (rid, timing))
        if args.sample:
            srow, sok = check_sample(rid, rel_tol=args.numeric_tol)
            allok = allok and sok
            nwarn += 1 if srow.get("warn") else 0
            _print_row("WARN" if srow.get("warn") else ("PASS" if srow["ok"] else "FAIL"),
                       rid, srow)
    if not args.keep and not args.scratch and os.path.exists(scratch_root):
        try:
            shutil.rmtree(scratch_root)
        except OSError:
            pass
    print("")
    print("reprocheck: %d/%d regimes reproduced (%.1fs) | mode=%s | warnings=%d%s"
          % (len(ids) if allok else 0, len(ids), time.time() - t_all,
             ("numeric-tol %.0e" % args.numeric_tol) if args.numeric_tol is not None else "strict",
             nwarn, " incl. SAMPLE.md" if args.sample else ""))
    if args.numeric_tol is not None:
        print("  worst relative float deviation observed: %.3e (tolerance %.0e)"
              % (worst_all, args.numeric_tol))
        if worst_all == 0.0:
            print("  -> zero deviation: this platform reproduces the dataset bit-for-bit.")
    if not allok:
        print("  the committed dataset is NOT the output of the committed generator.")
        print("  regenerate with: python -m bench.generate --regimes %s" % ",".join(ids))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())