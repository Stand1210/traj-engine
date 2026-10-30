# -*- coding: utf-8 -*-
"""Regenerate the README scorecard from `reports/R*/metrics.json`, and check it for drift.

Why this module exists
----------------------
The scorecard in `README.md` is *derived data*: every cell is a deterministic function of the
runner's `metrics.json`. It used to be hand-written, and hand-written derived tables go stale
silently -- nothing in the gate chain looks at them. This is the same failure class as the
`meta.json` staleness that `bench.coverage.dataset_provenance()` was added to catch: after the
v3.1.0 regeneration the runner reported 8/8 ALL-PASS and coverage reported 0 blockers while
7 of 8 `meta.json` still carried a key the generator no longer has. Green gates do not imply
fresh documentation.

The fix is to *derive* rather than to assert. `python -m bench.scorecard` rewrites the five
generated regions in place; `python -m bench.scorecard --check` rewrites nothing and exits 1 on
either of two disagreements:

  * README vs `reports/*/metrics.json`  -- the scorecard drifted from the runs;
  * `reports/*/metrics.json` vs `data/bench_v1/*/meta.json` on `spec_hash` -- the *reports*
    drifted from the dataset, i.e. the data was regenerated and the runner was not re-run.

The second one matters because deriving the README from stale reports would otherwise produce a
scorecard that is perfectly self-consistent and describes data that no longer exists on disk.
`bench.coverage.dataset_provenance()` already re-derives `spec_hash` for the dataset against the
live generator; `reports_provenance()` below is the same idea one hop downstream.

Generated regions are delimited by `<!-- scorecard:<name>:begin/end -->` markers, which are
invisible in rendered Markdown. On a README that does not have the markers yet the region is
located by its first line (an `ANCHORS` prefix) and the markers are inserted -- so the first
run bootstraps and every later run is a pure splice.

Deliberately NOT asserted: the per-regime wall clock. It is generated into the table because it
is informative, but it depends on machine load (the same code and data measured 95.6s and 100.7s
for R1 on two consecutive solo runs of the same box), so `--check` tolerates any value there.
Everything else in the four regions is compared exactly.
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPORTS = os.path.join(ROOT, "reports")
DATA = os.path.join(ROOT, "data", "bench_v1")
README = os.path.join(ROOT, "README.md")
REGIMES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
WALL_COL = u"\u5899\u949f"

BEGIN = "<!-- scorecard:%s:begin -->"
END = "<!-- scorecard:%s:end -->"
ANCHORS = {
    "header": u"## \u5f53\u524d\u8dd1\u5206\uff08\u6d41\u6c34\u7ebf",
    "main": u"| regime | \u5206\u5e03\u5f62\u6001 |",
    "notes": u"- F1 \u53d6 `detection",
    "scoring": u"| regime | \u6b63\u5e38\u5747\u5206 |",
    "channels": u"\u4e09\u901a\u9053\u53e3\u5f84\uff08",
}


def load(regimes=None):
    """{rid: metrics} for every regime that has been run; missing ones are absent, not None."""
    out = {}
    for rid in (regimes or REGIMES):
        p = os.path.join(REPORTS, rid, "metrics.json")
        if os.path.exists(p):
            out[rid] = json.load(io.open(p, encoding="utf-8"))
    return out


def reports_provenance(M, regimes=None):
    """Reconcile each report against BOTH things it claims to describe.

    Two hops, and both are needed:
      * `spec_hash` vs `data/bench_v1/<rid>/meta.json` -- was this score run against the dataset
        that is on disk now? Catches "the data was regenerated and the runner was not re-run".
      * `code_hash` vs the live `bench.runner.code_hash()` -- was it run against the kernel that
        is on disk now? Catches "the kernel was edited and the runner was not re-run", which the
        spec_hash hop cannot see at all because the dataset is untouched.

    `bench.coverage.dataset_provenance()` covers the hop above these (dataset vs the live
    generator). Together the three close the chain
    **live generator -> data -> reports -> README**, so no downstream "all green" can outlive an
    upstream change.

    Returns (rows, stale); each row is a dict with rid / spec_got / spec_want / code_got /
    code_want / ok / why.
    """
    from bench.runner import code_hash as live_code_hash
    live = live_code_hash()
    rows, stale = [], []
    for rid in (regimes or REGIMES):
        if rid not in M:
            continue
        m = M[rid]
        meta_p = os.path.join(DATA, rid, "meta.json")
        spec_got, code_got = m.get("spec_hash"), m.get("code_hash")
        spec_want = (json.load(io.open(meta_p, encoding="utf-8")).get("spec_hash")
                     if os.path.exists(meta_p) else None)
        why = []
        if spec_want is None:
            why.append("dataset meta.json missing")
        elif spec_got != spec_want:
            why.append("spec_hash mismatch")
        if code_got is None:
            why.append("report predates the code_hash field")
        elif code_got != live:
            why.append("code_hash mismatch")
        ok = not why
        rows.append({"rid": rid, "spec_got": spec_got, "spec_want": spec_want,
                     "code_got": code_got, "code_want": live, "ok": ok, "why": why})
        if not ok:
            stale.append(rid)
    return rows, stale


def _g(m, path, default=None):
    cur = m
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def _gate(m, name, key):
    return _g(m, "gates.%s.%s" % (name, key))


def _drift_text(m):
    """One-cell summary of the drift channel, in the shape the scorecard has always used."""
    d = m.get("drift") or {}
    if m.get("cold_start"):
        return u"\u51b7\u542f\u52a8\u6291\u5236"
    if d.get("detected"):
        return (u"\u68c0\u51fa idx %s / \u771f\u503c %s\uff0clag %+d\uff08%.1f vs \u03bb %.1f\uff09"
                % (d.get("index"), d.get("true_index"), d.get("lag") or 0,
                   d.get("statistic") or 0.0, d.get("lambda") or 0.0))
    if d.get("statistic") is None:
        return u"\u5f03\u6743"
    return u"\u65e0\u6f02\u79fb\uff0c%.1f vs \u03bb %.1f" % (d["statistic"], d.get("lambda") or 0.0)


def header(M):
    npass = sum(1 for m in M.values() if m.get("all_pass"))
    total = sum(m.get("wall_s") or 0.0 for m in M.values())
    ver = sorted(set(m.get("pipeline_version") or "?" for m in M.values()))
    return (u"## \u5f53\u524d\u8dd1\u5206\uff08\u6d41\u6c34\u7ebf `%s`\uff0c%d/%d regime "
            u"\u5168\u95e8\u69db\u901a\u8fc7\uff0c\u5168\u77e9\u9635\u7ea6 %.0fs\uff09"
            % ("/".join(ver), npass, len(M), total))


MAIN_HEAD = (u"| regime | \u5206\u5e03\u5f62\u6001 | n | \u53ef\u5f52\u7c07 | novelty "
             u"| ARI_intent\uff08\u4e0a\u754c\uff09 | ARI_pattern\uff08\u4e0a\u754c / "
             u"\u5f03\u6743\u524d\uff09 | novelty \u7eaf\u5ea6 | F1 | P@50 | FPR | AUC | ECE "
             u"| \u6f02\u79fb | " + WALL_COL + u" |")


def main_table(M):
    rows = [MAIN_HEAD, "|---" * 15 + "|"]
    for rid in REGIMES:
        if rid not in M:
            continue
        m, c = M[rid], M[rid]["clustering"]
        rows.append(u"| %s | %s | %d | %d | %.4f | %.4f (%.4f) | %.4f (%.4f / %.4f) | %.4f "
                    u"| %.3f | %.3f | %.4f | %.3f | %.4f | %s | %.1fs |" % (
                        rid, m.get("title", ""), m["n"], m["n_pool"], c["novelty_rate"],
                        c["ari_intent"], c["ari_intent_ceiling"],
                        c["ari_pattern"], c["ari_pattern_ceiling"], c["ari_pattern_all"],
                        c["novelty_purity_pattern"],
                        _g(m, "detection.pool.f1", 0.0),
                        _g(m, "detection.precision_at_50", 0.0),
                        _g(m, "detection.pool.fpr", 0.0),
                        _g(m, "detection.auc_a_raw", 0.0),
                        _g(m, "calibration.ece_oof", 0.0),
                        _drift_text(m), m.get("wall_s") or 0.0))
    return "\n".join(rows)


def _ari_gate(m):
    """(table_value, oracle_ceiling, effective_gate, got) parsed out of the gate's own `want`."""
    want = _gate(m, "ari_intent", "want") or ""
    t = re.search(r"table ([\d.]+)", want)
    c = re.search(r"oracle ceiling ([\d.]+)", want)
    g = re.search(r">=([\d.]+)", want)
    return (float(t.group(1)) if t else None,
            float(c.group(1)) if c else None,
            float(g.group(1)) if g else None,
            float(_gate(m, "ari_intent", "got") or 0.0))


NOTES = u"""- F1 \u53d6 `detection["pool"]["f1"]`\uff08\u95e8\u63a7\u540e\u3001\u53ef\u5f52\u7c07\u6c60\u4e0a\uff09\uff0c\u4e0d\u662f `detection["all"]["f1"]`\u3002
- R6 \u7684 F1 = @@R6F1@@ \u662f**\u8981\u6c42\u7684\u884c\u4e3a**\uff1a\u51b7\u542f\u52a8\u53ea\u51fa\u5206\u4e0d\u544a\u8b66\uff0c\u5176\u95e8\u69db\u662f `cold_start=true \u4e14\u544a\u8b66\u6570=0`\u3002
- R3 \u7684 `ari_intent` \u95e8\u69db\u8868\u503c @@R3TABLE@@\u3001oracle \u4e0a\u754c @@R3CEIL@@\uff1b`0.9 x @@R3CEIL@@ = @@R3EFF@@ @@R3CMP@@ @@R3TABLE@@`\uff0c
  \u6240\u4ee5\u5c01\u9876@@R3EFFTXT@@\uff0c\u6709\u6548\u95e8\u69db\u5c31\u662f @@R3GATE@@\uff1b\u5b9e\u6d4b **@@R3GOT@@\uff0c\u5373\u4e0a\u754c\u7684 @@R3PCT@@ \u767e\u5206\u4f4d**\uff0c\u4e0d\u662f\u538b\u7ebf\u901a\u8fc7\u3002
- R7 \u6f02\u79fb\u68c0\u51fa\u6ede\u540e **@@R7LAG@@**\uff08\u68c0\u51fa idx @@R7IDX@@ / \u771f\u503c @@R7TRUE@@\uff0c\u7edf\u8ba1\u91cf @@R7STAT@@ \u5bf9 \u03bb @@R7LAM@@\uff09\uff1b
  \u95e8\u69db\u8981\u6c42 `lag_frac \u2208 [@@R7LO@@, @@R7HI@@]`\uff0c\u5b9e\u6d4b @@R7LF@@\u3002
- \u5f03\u6743\u8ba1\u4ef7\uff1aR1 `ari_pattern` \u5f03\u6743\u524d @@R1ALL@@ \u2192 \u6c60\u4e0a @@R1POOL@@\uff08\u51c0\u4e70 @@R1DELTA@@\uff09\uff0c\u7f13\u51b2\u533a\u7eaf\u5ea6 @@R1PUR@@\uff1b
  R8 \u5f03\u6743\u524d @@R8ALL@@ \u2192 \u6c60\u4e0a @@R8POOL@@\uff0c\u51e0\u4e4e\u6ca1\u5dee\uff0c\u5f03\u6743\u6ca1\u6709\u4e70\u5206\uff1b\u800c\u5176\u4e0a\u754c\u662f @@R8CEIL@@\uff0c
  \u5dee\u7684 @@R8GAP@@ \u4e2a\u767e\u5206\u70b9\u662f\u5f02\u672c\u4f53\u4e0b**\u771f\u5b9e\u7684\u805a\u7c7b\u96be\u5ea6**\u3002"""


def notes(M):
    r3, r7 = M.get("R3"), M.get("R7")
    r1, r6, r8 = M.get("R1"), M.get("R6"), M.get("R8")
    sub = {"R6F1": "%.3f" % _g(r6, "detection.pool.f1", 0.0)}
    if r3 is not None:
        tbl, ceil, gate, got = _ari_gate(r3)
        eff = 0.9 * ceil
        binds = eff < tbl
        sub.update({
            "R3TABLE": "%g" % tbl,
            "R3CEIL": "%.4f" % ceil,
            "R3EFF": "%.3f" % eff,
            "R3CMP": "<" if binds else ">",
            "R3EFFTXT": (u"\u751f\u6548\uff0c\u628a\u95e8\u69db\u62ac\u5230" if binds
                         else u"\u6ca1\u6709\u751f\u6548"),
            "R3GATE": "%g" % gate,
            "R3GOT": "%.4f" % got,
            "R3PCT": "%.2f" % (100.0 * got / ceil),
        })
    if r7 is not None:
        d = r7["drift"]
        want = _gate(r7, "drift", "want") or ""
        band = re.search(r"lag_frac in \[([-\d.]+),([-\d.]+)\]", want)
        sub.update({
            "R7LAG": "%+d" % (d.get("lag") or 0),
            "R7IDX": "%s" % d.get("index"),
            "R7TRUE": "%s" % d.get("true_index"),
            "R7STAT": "%.1f" % (d.get("statistic") or 0.0),
            "R7LAM": "%.1f" % (d.get("lambda") or 0.0),
            "R7LO": band.group(1) if band else "-0.05",
            "R7HI": band.group(2) if band else "0.10",
            "R7LF": "%.4f" % (d.get("lag_frac") or 0.0),
        })
    for tag, m in (("R1", r1), ("R8", r8)):
        if m is None:
            continue
        c = m["clustering"]
        sub[tag + "ALL"] = "%.4f" % c["ari_pattern_all"]
        sub[tag + "POOL"] = "%.4f" % c["ari_pattern"]
        sub[tag + "CEIL"] = "%.4f" % c["ari_pattern_ceiling"]
    if r1 is not None:
        c = r1["clustering"]
        sub["R1DELTA"] = "%+.3f" % (c["ari_pattern"] - c["ari_pattern_all"])
        sub["R1PUR"] = "%.4f" % c["novelty_purity_pattern"]
    if r8 is not None:
        c = r8["clustering"]
        sub["R8GAP"] = "%.1f" % (100.0 * (c["ari_pattern_ceiling"] - c["ari_pattern"]))
    out = NOTES
    for k, v in sorted(sub.items()):
        out = out.replace("@@" + k + "@@", v)
    left = re.findall(r"@@[A-Z0-9]+@@", out)
    if left:
        raise AssertionError("unsubstituted placeholders: %s" % sorted(set(left)))
    return out


SCORING_HEAD = (u"| regime | \u6b63\u5e38\u5747\u5206 | \u5f02\u5e38\u5747\u5206 | \u5206\u79bb\u5ea6 "
                u"| Spearman(vs oracle) | \u96f6\u6b8b\u5dee\u6700\u5927\u504f\u5dee |")


def scoring_table(M):
    rows = [SCORING_HEAD, "|---" * 6 + "|"]
    for rid in REGIMES:
        if rid not in M:
            continue
        s = M[rid]["scoring"]
        rows.append(u"| %s | %.1f | %.1f | %.1f | %.3f | %.1e |" % (
            rid, s["mean_S_normal"], s["mean_S_anomaly"], s["grade_separation"],
            s["spearman_vs_oracle"], s["zero_residual_max"]))
    return "\n".join(rows)


CHANNELS = u"""\u4e09\u901a\u9053\u53e3\u5f84\uff08R1\uff0c@@HOURS@@h \u7a97\u53e3\uff09\uff1a**\u544a\u8b66\u6d41** k=@@K@@\u3001Precision @@PREC@@\uff08\u552f\u4e00\u4f1a\u4e3b\u52a8\u6253\u6270\u4eba\u7684\u901a\u9053\uff09\uff5c
**\u5ba1\u8ba1\u6d41** @@NRULE@@ \u6761\u786e\u5b9a\u6027\u8fdd\u89c4 = @@PERDAY@@ \u6761/\u65e5\uff08\u843d\u5e93\u5f85\u67e5\u4e0d\u547c\u53eb\uff09\uff5c**\u590d\u6838\u961f\u5217** @@NALERT@@ \u6761
\uff08\u7edf\u8ba1 @@NSTAT@@ + \u786c\u89c4\u5219 @@NRULE@@\uff0cBH-FDR \u03b1=@@ALPHA@@\uff09\uff0c\u5254\u9664 tier2 \u540e Precision@50 = @@P50BR@@
\uff08\u8be5\u5b50\u6c60\u5f02\u5e38\u57fa\u7387 @@BASE@@\uff0c\u63d0\u5347 @@LIFT@@ \u500d\uff09\u3002"""


def channels(M):
    m = M.get("R1")
    if m is None:
        return None
    d = m["detection"]
    sub = {
        "HOURS": "%.0f" % (24.0 * (d.get("days") or 0.0)),
        "K": "%d" % d["budget_k"],
        "PREC": "%.3f" % d["precision_at_budget"],
        "NRULE": "%d" % d["n_alert_rule"],
        "PERDAY": "%.1f" % d["rule_findings_per_day"],
        "NALERT": "%d" % d["n_alert"],
        "NSTAT": "%d" % d["n_alert_stat"],
        "ALPHA": "%.2f" % d["bh_alpha"],
        "P50BR": "%.3f" % d["precision_at_50_below_rule"],
        "BASE": "%.4f" % d["below_rule_base_rate"],
        "LIFT": "%.1f" % d["below_rule_lift"],
    }
    out = CHANNELS
    for k, v in sorted(sub.items()):
        out = out.replace("@@" + k + "@@", v)
    left = re.findall(r"@@[A-Z0-9]+@@", out)
    if left:
        raise AssertionError("unsubstituted placeholders: %s" % sorted(set(left)))
    return out


RENDER = {"header": header, "main": main_table, "notes": notes,
          "scoring": scoring_table, "channels": channels}


def render(M):
    out = {}
    for name, fn in RENDER.items():
        txt = fn(M)
        if txt is not None:
            out[name] = txt
    return out


def _region(lines, name):
    """(i, j) half-open span of region `name`, markers included if already present."""
    b, e = BEGIN % name, END % name
    if b in lines:
        i = lines.index(b)
        return i, lines.index(e, i) + 1
    a = ANCHORS[name]
    i = next(k for k, x in enumerate(lines) if x.startswith(a))
    j = i + 1
    if name in ("main", "scoring"):
        while j < len(lines) and lines[j].startswith("|"):
            j += 1
    else:
        while j < len(lines) and lines[j].strip():
            j += 1
    return i, j


def splice(text, blocks):
    """Replace each generated region with markers + fresh content. Idempotent."""
    lines = text.replace("\r\n", "\n").split("\n")
    for name in ("channels", "scoring", "notes", "main", "header"):
        if name not in blocks:
            continue
        i, j = _region(lines, name)
        body = blocks[name].split("\n")
        lines[i:j] = [BEGIN % name] + body + [END % name]
    return "\n".join(lines)


def _strip_markers(text):
    return "\n".join(x for x in text.replace("\r\n", "\n").split("\n")
                     if not re.match(r"^<!-- scorecard:[a-z]+:(begin|end) -->$", x))


def _mask_wall(text):
    """Wall clock is machine-load dependent, so it is excluded from the drift comparison."""
    out = []
    for x in text.split("\n"):
        cells = x.split("|")
        # main-table rows only: 15 columns, last one `<n>s`. The scoring table also starts with
        # `| R1 |`, so the column count is what keeps the mask off it.
        if x.startswith("| R") and len(cells) == 17 and x.rstrip().endswith("s |"):
            cells[-2] = " @@WALL@@ "
            x = "|".join(cells)
        out.append(x)
    return "\n".join(out)


def check(path=README, regimes=None):
    """(ok, missing, diffs). ok=True means README agrees with the reports on every cell except
    the per-regime wall clock, AND every report agrees with the dataset it was run against."""
    M = load(regimes)
    if not M:
        return True, REGIMES, []
    if not os.path.exists(path):
        return False, [], ["README.md not found at %s" % path]
    prows, pstale = reports_provenance(M, regimes)
    pdiffs = ["report %s: %s (spec_hash report=%s dataset=%s; code_hash report=%s live=%s) "
              "-- re-run `python -m bench.runner --regimes %s`"
              % (r["rid"], ", ".join(r["why"]), r["spec_got"], r["spec_want"],
                 r["code_got"], r["code_want"], r["rid"])
              for r in prows if not r["ok"]]
    cur = _strip_markers(io.open(path, encoding="utf-8-sig").read())
    want = _strip_markers(splice(cur, render(M)))
    missing = [r for r in REGIMES if r not in M]
    if pdiffs:
        return False, missing, pdiffs
    if _mask_wall(cur) == _mask_wall(want):
        return True, missing, []
    a, b = _mask_wall(cur).split("\n"), _mask_wall(want).split("\n")
    diffs = []
    for k in range(max(len(a), len(b))):
        x = a[k] if k < len(a) else "<absent>"
        y = b[k] if k < len(b) else "<absent>"
        if x != y:
            diffs.append("line %d\n    README : %s\n    reports: %s" % (k + 1, x, y))
    return False, missing, diffs


def main(argv):
    M = load()
    if not M:
        print("no reports/R*/metrics.json -- run `python -m bench.runner` first")
        return 2
    if "--check" in argv:
        prows, pstale = reports_provenance(M)
        for r in prows:
            print("  [%s] %-3s spec_hash report=%s dataset=%s | code_hash report=%s live=%s%s"
                  % ("PASS" if r["ok"] else "FAIL", r["rid"], r["spec_got"], r["spec_want"],
                     r["code_got"], r["code_want"],
                     "" if r["ok"] else "   <- " + ", ".join(r["why"])))
        ok, missing, diffs = check()
        for d in diffs[:40]:
            print("  [DIFF] %s" % d)
        if missing:
            print("  note: %s not run, their rows are absent from the scorecard"
                  % ", ".join(missing))
        print("scorecard: %s (%d regimes reconciled against the dataset and the live code; "
              "README compared cell by cell, wall clock excluded)"
              % ("IN SYNC" if ok else "STALE", len(M)))
        return 0 if ok else 1
    blocks = render(M)
    old = io.open(README, encoding="utf-8-sig").read()
    new = splice(old, blocks)
    if new != old:
        io.open(README, "w", encoding="utf-8", newline="\n").write(new)
        print("rewrote %s: %d -> %d chars, regions %s"
              % (README, len(old), len(new), ", ".join(sorted(blocks))))
    else:
        print("README already in sync with reports/ (%d regions checked)" % len(blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
