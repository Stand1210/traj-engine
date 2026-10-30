"""Human-readable inspector for the benchmark dataset and pipeline output.

The dataset is JSONL (one compressed record per line, ~54 MB across R1..R8), which is the
right storage format for a deterministic benchmark and the wrong format for a human. This
module closes that gap: it renders one trace as an indented span tree with timings, tokens
and text, then shows the ground truth next to what the pipeline actually produced, so the
input -> truth -> output loop can be read end to end.

Run:
    python -m bench.show R1 R1-00176          # one or more traces to stdout (ASCII only)
    python -m bench.show R1 --sample          # write data/bench_v1/R1/SAMPLE.md (zh)
    python -m bench.show R1 --list latency_spike   # trace ids carrying an anomaly type

Console output is deliberately ASCII, and since bench-gen-v3 that has to be *enforced* rather
than assumed: the records themselves now carry real Chinese in intent_text, goal_text,
subgoal_text, the answer and the golden answer. `_text(..., ascii_only=True)` maps every
non-ASCII run to a length placeholder, so the console keeps its column layout and can never
raise UnicodeEncodeError partway through a report. SAMPLE.md is UTF-8 and keeps the real text.
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "bench_v1")
REPORTS = os.path.join(ROOT, "reports")
DIMS = ("O", "P", "L", "C", "R")
DIM_NAME = {"O": "outcome", "P": "process", "L": "latency", "C": "cost", "R": "robustness"}


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with io.open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _index(path, key="trace_id"):
    return dict((rec[key], rec) for rec in _read_jsonl(path))


def load(regime):
    base = os.path.join(DATA, regime)
    return {
        "traces": _index(os.path.join(base, "traces.jsonl")),
        "gt": _index(os.path.join(base, "gt.jsonl")),
        "scores": _index(os.path.join(REPORTS, regime, "scores.jsonl")),
        "meta": (json.load(io.open(os.path.join(base, "meta.json"), encoding="utf-8"))
                 if os.path.exists(os.path.join(base, "meta.json")) else {}),
    }


def _kids(spans):
    by_parent = {}
    for span in spans:
        by_parent.setdefault(span.get("parent_id"), []).append(span)
    for group in by_parent.values():
        group.sort(key=lambda s: (s["ts_start"], s["span_id"]))
    return by_parent


def _order(spans):
    """Depth-first order; orphaned spans (corrupted parent_id) are appended, not dropped."""
    by_parent = _kids(spans)
    seen = set()
    ordered = []

    def walk(span, depth):
        if span["span_id"] in seen:
            return
        seen.add(span["span_id"])
        ordered.append((depth, span))
        for child in by_parent.get(span["span_id"], []):
            walk(child, depth + 1)

    for span in by_parent.get(None, []):
        walk(span, 0)
    for span in sorted(spans, key=lambda s: (s["ts_start"], s["span_id"])):
        if span["span_id"] not in seen:
            ordered.append((0, span))
            seen.add(span["span_id"])
    return ordered


def _bar(seconds, total, width=22):
    if total <= 0:
        return ""
    n = int(round(width * seconds / total))
    return "#" * max(1, n) if seconds > 0 else ""


def _num(value, nd=2):
    return "n/a" if value is None else ("%." + str(nd) + "f") % value


# span fields added by bench-gen-v2 that carry the cost / tool-identity / data-quality
# signal. Rendered as one compact line per span, None values dropped, so a tool span does
# not advertise a model it never called and an llm span does not advertise a tool.
META_FIELDS = ("model", "tool_name", "level", "ttft", "prompt_version", "status_message")


def _span_meta(span):
    bits = []
    for key in META_FIELDS:
        val = span.get(key)
        if val in (None, "", "DEFAULT"):
            continue
        bits.append("%s=%s" % ({"tool_name": "tool", "prompt_version": "pv",
                                "status_message": "msg", "ttft": "ttft"}.get(key, key),
                               _num(val, 4) if key == "ttft" else val))
    params = span.get("tool_params")
    if params:
        bits.append("params={%s}" % ",".join("%s:%s" % (k, params[k]) for k in sorted(params)))
    facts = span.get("output_facts")
    if facts:
        bits.append("facts=[%s]" % " ".join(str(f) for f in facts))
    return "  ".join(bits)


def _text(value, ascii_only=False, limit=None):
    """Record text, made safe for the channel it is about to be written to."""
    if value is None:
        return ""
    s = value if isinstance(value, str) else str(value)
    if limit:
        s = s[:limit]
    if not ascii_only:
        return s
    out, run = [], 0
    for ch in s:
        if ord(ch) < 128:
            if run:
                out.append("<cjk%d>" % run)
                run = 0
            out.append(ch)
        else:
            run += 1
    if run:
        out.append("<cjk%d>" % run)
    return "".join(out)


# Span fields added by bench-gen-v3: the system-prompt / prompt-cache token decomposition, the
# exact cost attribution, the *measured* argument-schema verdict, the validator outcome, the
# sub-goal text and the retrieved citation set. They go on their own line because every one of
# them is conditional on the span kind, and folding them into META_FIELDS would make a tool span
# advertise a verifier it never ran.
def _span_meta_v3(span, ascii_only=False):
    bits = []
    for key, short in (("tokens_system_prompt", "sys"), ("tokens_cache_read", "cache_r"),
                       ("tokens_cache_write", "cache_w")):
        if span.get(key):
            bits.append("%s=%s" % (short, span[key]))
    nz = dict((k, v) for k, v in (span.get("cost_details") or {}).items() if v)
    if nz:
        bits.append("cost_det={%s}" % ",".join("%s:%.3g" % (k, nz[k]) for k in sorted(nz)))
    if span.get("arg_valid") is not None:
        bits.append("arg_valid=%s" % span["arg_valid"])
    ver = span.get("verifier")
    if ver:
        bits.append("verifier=%s:%s%s"
                    % (ver.get("id"), "PASS" if ver.get("passed") else "FAIL",
                       "" if not ver.get("detail") else "(%s)" % ver["detail"]))
    if span.get("subgoal_text"):
        bits.append("subgoal=%s" % _text(span["subgoal_text"], ascii_only, 60))
    if span.get("output_citations"):
        bits.append("retrieved=[%s]" % " ".join(span["output_citations"]))
    return "  ".join(bits)


def render_trace(regime, trace_id, bundle=None, show_text=True, ascii_only=False):
    bundle = bundle or load(regime)
    trace = bundle["traces"].get(trace_id)
    if trace is None:
        return ["trace %s not found in %s" % (trace_id, regime)]
    gt = bundle["gt"].get(trace_id, {})
    sc = bundle["scores"].get(trace_id, {})
    spans = trace["spans"]
    wall = max(s["ts_end"] for s in spans) - min(s["ts_start"] for s in spans)
    out = []
    out.append("=" * 78)
    out.append("TRACE %s   [%s]" % (trace_id, _text(trace["intent_text"], ascii_only)))
    out.append("  ontology=%s  session=%s  turn=%s/%s  spans=%d  wall=%.3fs  ts_start=%.3f"
               % (trace["ontology_id"], trace["session_id"], trace.get("turn_index"),
                  trace.get("session_turn_count"), len(spans), wall, trace["ts_start"]))
    fb = trace.get("user_feedback") or {}
    out.append("  user_feedback: %s" % ("none captured" if not fb else " ".join(
        "%s=%s" % (k, fb[k]) for k in sorted(fb))))
    out.append("  answer_numbers=%s" % (trace.get("answer_numbers"),))
    out.append("  answer_facts  =%s" % (trace.get("answer_facts"),))
    out.append("  golden_answer =%s" % _text(trace.get("golden_answer"), ascii_only))
    out.append("  golden_facts  =%s" % (trace.get("golden_facts"),))
    out.append("  goal_text     =%s   query_lang=%s"
               % (_text(trace.get("goal_text"), ascii_only), trace.get("query_lang")))
    out.append("  answer_citations  =%s" % (trace.get("answer_citations") or [],))
    out.append("  contradicted_facts=%s" % (trace.get("contradicted_facts") or [],))
    flags = trace.get("raw_flags", {})
    out.append("  raw_flags(as ingested): %s" % " ".join(
        "%s=%s" % (k, flags.get(k)) for k in sorted(flags)))
    out.append("  embedding[0:4]=%s ... (%d dims, intent view input)"
               % ([round(x, 4) for x in trace["embedding"][:4]], len(trace["embedding"])))

    out.append("")
    out.append("  SPAN TREE (execution process)")
    out.append("  %-2s %-13s %-11s %-16s %8s %-9s %-9s %-9s %8s %-5s %s"
               % ("", "span", "kind", "action", "dur(s)", "share", "tok_in", "tok_out",
                  "cost($)", "stat", "finish"))
    ordered = _order(spans)
    for depth, span in ordered:
        dur = span["ts_end"] - span["ts_start"]
        mark = "- " if depth == 0 else ("  " * (depth - 1) + "`-")
        pad = "  " + "  " * depth
        out.append("  %-2s %-13s %-11s %-16s %8.3f %-9s %-9s %-9s %8s %-5s %s"
                   % (mark, span["span_id"].split("-", 2)[-1], span["kind"], span["action"],
                      dur, _bar(dur, wall, 9),
                      span["tokens_prompt"] if span["tokens_prompt"] is not None else "None",
                      span["tokens_completion"] if span["tokens_completion"] is not None else "None",
                      _num(span["cost"], 5), span["status"], span["finish_reason"] or "-"))
        if show_text:
            out.append("  %s   in : %s" % (pad, _text(span.get("input_text"), ascii_only, 72)))
            out.append("  %s   out: %s"
                       % (pad, _text(span.get("output_text"), ascii_only, 72)))
            meta = _span_meta(span)
            if meta:
                out.append("  %s   meta: %s" % (pad, meta[:150]))
            meta3 = _span_meta_v3(span, ascii_only)
            if meta3:
                out.append("  %s   v3  : %s" % (pad, meta3[:230]))

    out.append("")
    out.append("  GROUND TRUTH (what the generator knows; the pipeline never sees this)")
    out.append("    is_anomaly=%s  anomaly_types=%s" % (gt.get("is_anomaly"), gt.get("anomaly_types")))
    out.append("    intent=%s  pattern=%s  cell=%s" % (gt.get("intent_id"), gt.get("pattern_id"),
                                                       gt.get("cell_id")))
    dev = gt.get("dim_dev") or {}
    out.append("    oracle dim_dev : %s" % "  ".join("%s=%s" % (d, _num(dev.get(d), 2)) for d in DIMS))
    out.append("    latency_true=%.3fs  gen_quantiles=%s" % (gt.get("latency_true") or 0.0,
                                                             gt.get("gen_quantiles")))
    out.append("    process_flags=%s" % (gt.get("process_flags"),))
    out.append("    defect_flags(after normalize)=%s" % (gt.get("defect_flags"),))
    out.append("    responsible_span_ids=%s  human_label=%s  drift_segment=%s"
               % (gt.get("responsible_span_ids"), gt.get("human_label"), gt.get("drift_segment")))
    # v2 truth: the outcome-fidelity, loop, telemetry-loss and model-mix signals the kernel
    # is supposed to recover from raw fields alone. Printed next to the label so a mismatch
    # between "what the label says" and "what the data contains" is visible by eye - that is
    # exactly the class of bug bench/coverage.truth_agreement() now fails the build on.
    out.append("    loop_true=%s  mfr_true=%s  model_mix_true=%s  feedback_available=%s"
               % (gt.get("loop_true"), _num(gt.get("mfr_true"), 4), gt.get("model_mix_true"),
                  gt.get("feedback_available")))
    out.append("    has_golden=%s  key_fact_recall_true=%s  fact_precision_true=%s"
               % (gt.get("has_golden"), _num(gt.get("key_fact_recall_true"), 4),
                  _num(gt.get("fact_precision_true"), 4)))
    out.append("    hallucinated_facts=%s" % (gt.get("hallucinated_facts"),))
    # v3 truth. Printed for the same reason as the v2 block: coverage.truth_agreement() asserts a
    # two-sided equivalence between each of these and the matching kernel feature over every trace
    # of every regime, so a mismatch visible here is a build failure rather than a curiosity.
    out.append("    query_lang_true=%s  session_turn_count_true=%s  subgoal_count=%s"
               % (gt.get("query_lang_true"), gt.get("session_turn_count_true"),
                  gt.get("subgoal_count")))
    out.append("    plan_revision_true=%s  goal_drift_true=%s  arg_valid_true=%s  "
               "verifier_pass_true=%s"
               % (gt.get("plan_revision_true"), gt.get("goal_drift_true"),
                  _num(gt.get("arg_valid_true"), 4), _num(gt.get("verifier_pass_true"), 4)))
    out.append("    citation_reachable_true=%s  contradiction_true=%s  contradicted_count=%s  "
               "fabricated_citation_count=%s"
               % (_num(gt.get("citation_reachable_true"), 4),
                  _num(gt.get("contradiction_true"), 4), gt.get("contradicted_count"),
                  gt.get("fabricated_citation_count")))
    out.append("    cache_read_true=%s  cache_write_true=%s  system_prompt_ratio_true=%s  "
               "cost_details_reconciled_true=%s"
               % (gt.get("cache_read_true"), gt.get("cache_write_true"),
                  _num(gt.get("system_prompt_ratio_true"), 4),
                  gt.get("cost_details_reconciled_true")))

    out.append("")
    out.append("  PIPELINE OUTPUT (%s)" % sc.get("model_version", "not run"))
    if not sc:
        out.append("    (no score row; run `python -m bench.runner --regimes %s` first)" % regime)
        return out
    dims = sc.get("dims") or {}
    contrib = sc.get("contrib") or {}
    total = sum(v for v in contrib.values() if v is not None)
    s_val, g_val = sc.get("S"), sc.get("G")
    out.append("    S=%s  G=%s  grade_abs=%s  grade_rel=%s  tier=%s  novelty=%s"
               % (_num(s_val, 4), _num(g_val, 2), sc.get("grade_abs"), sc.get("grade_rel"),
                  sc.get("tier"), sc.get("novelty")))
    out.append("    alert=%s (rule=%s stat=%s)  cold_start=%s  cell=%s"
               % (sc.get("alert"), sc.get("alert_rule"), sc.get("alert_stat"),
                  sc.get("cold_start"), sc.get("cell")))
    out.append("    dims    : %s" % "  ".join("%s=%.3f" % (d, dims.get(d, 0.0)) for d in DIMS))
    out.append("    contrib : %s   sum=%s" % ("  ".join(
        "%s=%+.3f" % (d, contrib.get(d) or 0.0) for d in DIMS), _num(total, 4)))
    # scores.jsonl stores S with 4dp and contrib with 6dp, so a residual read back from
    # disk bottoms out around 1e-4. The exact identity (|diff| <= 1e-13) is asserted
    # in-memory by bench/runner.py; here we only check the rounded rows still balance.
    if s_val is None or g_val is None:
        out.append("    zero-residual: n/a (no S/G on this row)")
    else:
        resid = abs(total - (s_val - 100.0 * g_val))
        out.append("    zero-residual: S-100G=%.4f  |diff|=%.2e  %s  (rounded JSONL rows;"
                   % (s_val - 100.0 * g_val, resid, "OK" if resid <= 1e-3 else "BAD"))
        out.append("                   exact identity asserted in bench/runner.py)")
    out.append("    a_raw=%s  a_cal=%s  conf=%s  anchor=%s"
               % (_num(sc.get("a_raw"), 4), _num(sc.get("a_cal"), 4), _num(sc.get("conf"), 4),
                  sc.get("anchor_version")))
    gates = sc.get("gates") or {}
    if gates:
        out.append("    gates: %s" % json.dumps(gates, sort_keys=True)[:180])
    ev = sc.get("evidence") or []
    out.append("    evidence (%d items, drill-down order):" % len(ev))
    for item in ev[:6]:
        if item.get("kind") == "metric":
            out.append("      - [trace] %-24s span=%-14s value=%-11s cell_median=%-11s z=%+7.2f dev=%s"
                       % (item.get("metric"), item.get("span_id") or "-",
                          _num(item.get("value"), 4), _num(item.get("cell_median"), 4),
                          item.get("z") or 0.0, _num(item.get("dev"), 4)))
        elif item.get("kind") == "span":
            out.append("      - [span ] %-24s span=%-14s value=%-11s peer_median=%-11s z=%+7.2f dev=%s"
                       " (%s/%s action=%s)"
                       % (item.get("metric"), item.get("span_id") or "-",
                          _num(item.get("value"), 4), _num(item.get("peer_median"), 4),
                          item.get("z") or 0.0, _num(item.get("dev"), 4),
                          item.get("layer"), item.get("baseline_level"), item.get("action")))
        else:
            out.append("      - %s" % json.dumps(item, sort_keys=True)[:150])
    return out


def _by_type(bundle, atype, limit, need_golden=False):
    """Trace ids carrying an anomaly type, in file order.

    `need_golden` restricts to traces that also carry a golden answer. Sample sets want that
    for the fidelity anomalies: without a golden the recall / precision truth fields are
    None, and the whole point of showing a `hallucinated_number` next to a `truncation` is
    that the first drops precision while recall stays 1.0 and the second does the opposite.
    """
    hits = []
    for tid, gt in bundle["gt"].items():
        if atype not in (gt.get("anomaly_types") or []):
            continue
        if need_golden and not gt.get("has_golden"):
            continue
        hits.append(tid)
        if len(hits) >= limit:
            break
    return hits


def _by_pred(bundle, pred, limit=1):
    """Trace ids whose ground truth satisfies `pred`, in file order.

    Kept apart from `_by_type` because the v3 signals are co-defects rather than anomaly types:
    they only ever fire on an already-anomalous trace, so no value of `anomaly_types` selects
    them.
    """
    hits = []
    for tid, gt in bundle["gt"].items():
        if pred(gt):
            hits.append(tid)
        if len(hits) >= limit:
            break
    return hits


def _first_normal(bundle, min_spans=5, limit=1):
    hits = []
    for tid, trace in bundle["traces"].items():
        gt = bundle["gt"].get(tid, {})
        if not gt.get("is_anomaly") and len(trace["spans"]) >= min_spans:
            hits.append(tid)
        if len(hits) >= limit:
            break
    return hits


NARRATIVE = u"""# %(regime)s \u6837\u672c\u9605\u8bfb\u624b\u518c

\u8fd9\u4e2a\u6587\u4ef6\u7531 `python -m bench.show %(regime)s --sample` \u751f\u6210\uff0c\u5185\u5bb9\u662f\u771f\u5b9e\u6570\u636e\uff0c\u4e0d\u662f\u793a\u610f\u56fe\u3002

## \u4e00\u3001\u8fd9\u5957\u4e1c\u897f\u662f\u4ec0\u4e48

\u5b83\u662f\u4e00\u4e2a**\u79bb\u7ebf\u57fa\u51c6\uff08benchmark\uff09+ \u7b97\u6cd5\u5de5\u7a0b harness**\uff0c\u4e0d\u662f\u751f\u4ea7\u670d\u52a1\u3002\u56e0\u4e3a\u8981\u9a8c\u8bc1\u7684\u662f\u201c\u805a\u7c7b \u2192 \u5f02\u5e38\u8bc6\u522b \u2192 \u6253\u5206\u201d\u4e09\u4e2a\u7b97\u6cd5\u6a21\u5757\u672c\u8eab\u662f\u5426\u6210\u7acb\uff0c
\u5c31\u5fc5\u987b\u6709\u4e00\u4efd**\u5e26\u771f\u503c\u6807\u7b7e**\u7684\u8f68\u8ff9\u6570\u636e\uff1a\u771f\u5b9e Langfuse \u6570\u636e\u6ca1\u6709\u4eba\u5de5\u6807\u6ce8\u7684\u201c\u8fd9\u6761\u5f02\u5e38/\u8fd9\u6761\u6b63\u5e38\u201d\uff0c\u65e0\u6cd5\u7b97 F1 / ARI / AUC\u3002

\u56e0\u6b64\u6d41\u7a0b\u662f\uff1a

```
bench/generate.py   \u9020\u6570\u636e\uff1a\u6a21\u62df\u667a\u80fd\u4f53\u6267\u884c\u8fc7\u7a0b \u2192 traces.jsonl\uff08\u8f93\u5165\uff09+ gt.jsonl\uff08\u771f\u503c\uff09
        \u2193
kernel/*            \u7b97\u6cd5\u5de5\u7a0b\uff1aingest \u2192 features \u2192 cluster \u2192 baseline \u2192 detect \u2192 drift \u2192 score \u2192 calib
        \u2193
bench/runner.py     \u8dd1\u5168\u94fe\u8def \u2192 reports/<regime>/scores.jsonl\uff08\u6bcf\u6761\u8f68\u8ff9\u7684\u5206\u6570+\u8bc1\u636e\uff09
        \u2193
bench/runner.py     \u62ff gt.jsonl \u5bf9\u81ea\u5df1\u6253\u5206\uff0c\u8fc7 contracts/schemas.md \u91cc\u7684\u95e8\u69db\u8868 \u2192 report.md
```

## \u4e8c\u3001trace \u8bb0\u5f55\u5728\u54ea\u91cc

| \u6587\u4ef6 | \u5185\u5bb9 | \u884c\u6570 |
|---|---|---|
| `data/bench_v1/%(regime)s/traces.jsonl` | \u6a21\u62df\u51fa\u6765\u7684\u8f68\u8ff9\uff08\u4e00\u884c\u4e00\u6761\uff0c\u542b\u5b8c\u6574 Span \u6811\uff09 | %(n_traces)d |
| `data/bench_v1/%(regime)s/gt.jsonl` | \u771f\u503c\uff1a\u662f\u5426\u5f02\u5e38\u3001\u5f02\u5e38\u7c7b\u578b\u3001\u771f\u5b9e\u610f\u56fe/\u6a21\u5f0f\u3001\u8d23\u4efb Span | %(n_traces)d |
| `reports/%(regime)s/scores.jsonl` | \u7b97\u6cd5\u8f93\u51fa\uff1aS \u5206\u3001\u4e94\u7ef4\u3001\u6263\u5206\u5f52\u56e0\u3001\u8bc1\u636e\u3001\u544a\u8b66 | %(n_scores)d |

JSONL = \u6bcf\u884c\u4e00\u4e2a\u538b\u7f29 JSON\uff0c\u76f4\u63a5\u6253\u5f00\u4f1a\u770b\u5230\u4e00\u5806\u6ca1\u6cd5\u8bfb\u7684\u957f\u884c\u3002\u7528\u4e0b\u9762\u7684\u547d\u4ee4\u770b\uff1a

```
python -m bench.show %(regime)s %(regime)s-00001        # \u770b\u5355\u6761\u8f68\u8ff9\uff08\u8f93\u5165+\u771f\u503c+\u7b97\u6cd5\u8f93\u51fa\uff09
python -m bench.show %(regime)s --list latency_spike    # \u5217\u51fa\u67d0\u7c7b\u5f02\u5e38\u7684 trace_id
python -m bench.show %(regime)s --stats                 # \u6570\u636e\u96c6\u4fa7\u5199
```

## \u4e09\u3001\u4e00\u6761 trace \u957f\u4ec0\u4e48\u6837

\u6bcf\u6761 trace = \u4e00\u68f5 Span \u6811\u3002\u6839\u8282\u70b9\u662f\u6574\u6b21 agent \u6267\u884c\uff0c\u5b50\u8282\u70b9\u662f\u5177\u4f53\u6b65\u9aa4\uff08\u5927\u6a21\u578b\u8c03\u7528 / \u5de5\u5177\u8c03\u7528 / \u77e5\u8bc6\u68c0\u7d22 / \u62a4\u680f\u6821\u9a8c\uff09\uff0c
\u6bcf\u4e2a\u8282\u70b9\u5e26\u5f00\u59cb\u7ed3\u675f\u65f6\u95f4\u3001token\u3001\u6210\u672c\u3001\u72b6\u6001\u3001\u8f93\u5165\u8f93\u51fa\u6587\u672c\u3002\u4e0b\u9762\u662f\u771f\u5b9e\u6837\u672c\u3002

"""

STATS_HDR = u"## \u56db\u3001\u6570\u636e\u96c6\u4fa7\u5199\n\n"


def _stats_lines(bundle, regime):
    traces = bundle["traces"]
    gts = bundle["gt"]
    n_span = sum(len(t["spans"]) for t in traces.values())
    n_anom = sum(1 for g in gts.values() if g.get("is_anomaly"))
    counts = {}
    for gt in gts.values():
        for atype in gt.get("anomaly_types") or []:
            counts[atype] = counts.get(atype, 0) + 1
    intents = {}
    for gt in gts.values():
        intents[gt.get("intent_id")] = intents.get(gt.get("intent_id"), 0) + 1
    cells = set(gt.get("cell_id") for gt in gts.values())
    lines = []
    lines.append(u"- \u8f68\u8ff9\u6570 **%d**\uff0cSpan \u6570 **%d**\uff0c\u5e73\u5747 %.1f Span/\u8f68\u8ff9"
                 % (len(traces), n_span, n_span / max(1, len(traces))))
    lines.append(u"- \u5f02\u5e38\u8f68\u8ff9 **%d** \u6761\uff08\u57fa\u7387 %.2f%%\uff09\uff0c\u6b63\u5e38 **%d** \u6761"
                 % (n_anom, 100.0 * n_anom / max(1, len(traces)), len(traces) - n_anom))
    lines.append(u"- \u610f\u56fe\u5206\u5e03\uff1a%s" % u"\uff0c".join(
        u"%s=%d" % (k, intents[k]) for k in sorted(intents)))
    lines.append(u"- \u771f\u5b9e\u5355\u5143\u683c\uff08\u610f\u56fe\u00d7\u6a21\u5f0f\uff09**%d** \u4e2a" % len(cells))
    lines.append(u"- \u5f02\u5e38\u7c7b\u578b\u5206\u5e03\uff1a%s" % u"\uff0c".join(
        u"%s=%d" % (k, counts[k]) for k in sorted(counts, key=lambda x: -counts[x])))
    meta = bundle.get("meta") or {}
    if meta:
        # meta.json has always stored this under `generator_version`; the old `gen_version` key
        # never existed, so SAMPLE.md printed `gen_version=None` for every regime.
        lines.append(u"- `spec_hash=%s`  `gen_version=%s`"
                     % (meta.get("spec_hash"), meta.get("generator_version")))
        v3 = meta.get("v3_counts") or {}
        if v3:
            lines.append(STATS_V3 % u"\uff0c".join(
                u"%s=%d" % (k, v3[k]) for k in sorted(v3)))
        langs = meta.get("lang_counts") or {}
        if langs:
            lines.append(STATS_LANG % (u"\uff0c".join(
                u"%s=%d" % (k, langs[k]) for k in sorted(langs)),
                meta.get("session_count"), meta.get("session_turn_counts")))
    return lines


SAMPLE_TITLE = {
    "normal": u"### \u6837\u672c A\uff1a\u4e00\u6761\u6b63\u5e38\u8f68\u8ff9\uff08\u5e94\u8be5\u5f97\u9ad8\u5206\u3001\u4e0d\u544a\u8b66\uff09",
    "anomaly": u"### \u6837\u672c %(i)s\uff1a%(atype)s \u2014\u2014 %(tid)s",
}

ANOM_NOTE = {
    "latency_spike": u"\u67d0\u4e00\u6b65\u8017\u65f6\u88ab\u653e\u5927 5~20 \u500d\u3002\u770b SPAN TREE \u91cc\u7684 dur(s) \u5217\u548c share \u6761\uff1a\u5176\u4e2d\u4e00\u4e2a\u5b50\u6b65\u9aa4\u5403\u6389\u4e86\u51e0\u4e4e\u5168\u90e8\u58c1\u949f\u65f6\u95f4\u3002\u771f\u503c\u628a L \u7ef4\u6253\u5230 0.10\uff0c\u7b97\u6cd5\u5e94\u8be5\u5728 L \u4e0a\u6263\u5206\u5e76\u628a\u8d23\u4efb\u6307\u5411\u90a3\u4e2a Span\u3002",
    "hallucinated_number": u"\u6700\u7ec8\u7b54\u6848\u91cc\u51fa\u73b0\u4e86\u68c0\u7d22\u8bc1\u636e\u4e2d\u4e0d\u5b58\u5728\u7684\u6570\u5b57\u3002\u5bf9\u6bd4\u5b50 Span \u7684 `out: evidence: ...` \u4e0e\u6839 Span \u7684 `out: answer: ...`\uff1a\u540e\u8005\u591a\u51fa\u4e86\u4e24\u4e2a 5 \u4f4d\u6570\u3002\u8fd9\u662f\u552f\u4e00\u4e00\u4e2a\u9760\u6587\u672c\u5185\u5bb9\u5224\u5b9a\u7684\u5f02\u5e38\uff08`traceable_number_ratio` \u7279\u5f81\uff09\u3002",
    "loop": u"\u540c\u4e00\u6b65\u9aa4\u88ab\u91cd\u590d\u63d2\u5165 3~5 \u6b21\u3002SPAN TREE \u91cc\u4f1a\u770b\u5230\u8fde\u7eed\u591a\u884c\u76f8\u540c action\uff0c\u65f6\u95f4\u6233\u4e5f\u76f8\u540c\uff08\u751f\u6210\u5668\u76f4\u63a5\u590d\u5236\u4e86 Span\uff09\u3002",
    "token_bloat": u"\u67d0\u4e2a LLM \u6b65\u9aa4\u7684 token \u88ab\u653e\u5927 4~10 \u500d\uff0c\u8017\u65f6\u4e0d\u53d8\u3002\u53ea\u6709\u6210\u672c\u7ef4\uff08C\uff09\u4f1a\u5d29\uff0c\u65f6\u5ef6\u7ef4\u4e0d\u5d29\u2014\u2014\u7528\u6765\u9a8c\u8bc1\u4e94\u7ef4\u4e0d\u4f1a\u4e92\u76f8\u6c61\u67d3\u3002",
    "illegal_step": u"\u63d2\u5165\u4e86\u672c\u4f53\u7981\u6b62\u7684\u52a8\u4f5c\uff08\u5982 `force_delete` / `skip_approval_execute`\uff09\u3002\u8fd9\u662f\u786e\u5b9a\u6027\u8fdd\u89c4\uff0c\u8d70\u89c4\u5219\u95f8\u95e8\uff08alert_rule=True\uff09\u800c\u4e0d\u662f\u7edf\u8ba1\u5f02\u5e38\u3002",
    "missing_step": u"\u672c\u4f53\u8981\u6c42\u7684\u5fc5\u987b\u6b65\u9aa4\u88ab\u5220\u6389\u4e00\u4e2a\uff0c\u8fc7\u7a0b\u7ef4\uff08P\uff09\u6263\u5206\u3002",
    "unfinished": u"\u672b\u5c3e 1~2 \u4e2a\u6b65\u9aa4\u88ab\u622a\u65ad\uff0c\u4efb\u52a1\u6ca1\u8d70\u5b8c\u3002",
    "truncation": u"\u6839 Span \u7684 `finish_reason=length`\uff0c\u7b54\u6848\u88ab\u622a\u65ad\uff0c\u7ed3\u679c\u7ef4\uff08O\uff09\u91cd\u7f5a\u3002",
    "error": u"\u5b50 Span `status=error`\u3002\u6ce8\u610f\uff1a\u751f\u6210\u5668\u6709 40%% \u6982\u7387\u628a\u5b83\u53d8\u6210\u201c\u62a5\u9519\u540e\u91cd\u8bd5\u6210\u529f\u201d\u5e76\u6807\u4e3a**\u6b63\u5e38**\uff0c\u4e13\u95e8\u7528\u6765\u60e9\u7f5a\u201c\u89c1\u5230 error \u5c31\u544a\u8b66\u201d\u7684\u5e7c\u7a1a\u89c4\u5219\u3002",
}


# (anomaly type, require a golden answer) - the two golden-bearing samples are what make the
# "incomplete is not the same as unfaithful" separation in bench/generate.py visible.
SAMPLE_SPEC = (("latency_spike", False), ("hallucinated_number", True), ("loop", False),
               ("token_bloat", False), ("illegal_step", False), ("truncation", True),
               ("missing_step", False))


GOLDEN_NOTE = {
    "hallucinated_number": u"\u8fd9\u6761\u5e26 golden\u3002\u770b GROUND TRUTH \u91cc\u7684 "
                           u"`fact_precision_true` \u4e0e `key_fact_recall_true`\uff1a\u7f16\u9020\u6570\u5b57"
                           u"\u53ea\u538b precision\uff0crecall \u4ecd\u4e3a 1.00\u2014\u2014\u7b54\u6848"
                           u"\u91cc\u7684\u4e8b\u5b9e\u90fd\u5728\uff0c\u53ea\u662f\u591a\u4e86\u4e0d\u8be5"
                           u"\u6709\u7684\u3002`hallucinated_facts` \u76f4\u63a5\u5217\u51fa\u591a\u51fa\u6765"
                           u"\u7684\u90a3\u51e0\u4e2a\u3002",
    "truncation": u"\u8fd9\u6761\u5e26 golden\u3002\u4e0e\u4e0a\u4e00\u4e2a\u6837\u672c\u5bf9\u7740\u770b"
                  u"\uff1a\u622a\u65ad\u53ea\u538b `key_fact_recall_true`\uff0cprecision \u4ecd\u4e3a 1.00"
                  u"\u2014\u2014\u8bf4\u51fa\u6765\u7684\u90fd\u5bf9\uff0c\u53ea\u662f\u6ca1\u8bf4\u5b8c\u3002"
                  u"\u751f\u6210\u5668\u6545\u610f\u628a\u201c\u4e0d\u5b8c\u6574\u201d\u4e0e\u201c\u4e0d"
                  u"\u5fe0\u5b9e\u201d\u505a\u6210\u53ef\u5206\u79bb\u7684\u4e24\u7c7b\uff0c\u5426\u5219"
                  u"O \u7ef4\u4f1a\u628a\u4e24\u79cd\u5b8c\u5168\u4e0d\u540c\u7684\u5931\u8d25\u6253\u6210"
                  u"\u540c\u4e00\u4e2a\u5206\u3002",
    "*": u"\u8fd9\u6761\u5e26 golden\uff0c\u5bf9\u6bd4 `answer_facts` \u4e0e `golden_facts` \u53ef\u770b\u5230"
         u"\u5dee\u5728\u54ea\u91cc\u3002",
}


V3_HDR = u"""## \u516d\u3001v3 \u5171\u751f\u7f3a\u9677\u6837\u672c\uff08\u9644\u5f55 A \u65b0\u589e\u7279\u5f81\u7684\u539f\u59cb\u8bc1\u636e\uff09

\u4e0b\u9762\u8fd9\u4e9b**\u4e0d\u662f**\u72ec\u7acb\u7684\u5f02\u5e38\u7c7b\u578b\uff0c\u800c\u662f\u53e0\u52a0\u5728\u5df2\u5f02\u5e38\u8f68\u8ff9\u4e0a\u7684\u5171\u751f\u7f3a\u9677\u3002\u6bcf\u4e00\u4e2a\u90fd\u7531
`bench/coverage.truth_agreement()` \u5728\u5168\u90e8\u8f68\u8ff9\u4e0a\u505a\u53cc\u5411\u7b49\u4ef7\u6821\u9a8c\uff08\u5185\u6838\u7279\u5f81 \u27fa \u751f\u6210\u5668\u771f\u503c\uff09\uff0c
\u4efb\u4f55\u4e00\u6761\u5bf9\u4e0d\u4e0a\u90fd\u4f1a\u8ba9\u6784\u5efa\u76f4\u63a5\u5931\u8d25\uff0c\u800c\u4e0d\u662f\u53ea\u5728\u62a5\u544a\u91cc\u7559\u4e00\u884c\u8b66\u544a\u3002

"""

V3_ITEM = u"### v3 \u6837\u672c %(i)s\uff1a%(name)s \u2014\u2014 %(tid)s"

V3_SPEC = (
    ("plan_revision", lambda g: bool(g.get("plan_revision_true")),
     u"\u5165\u53e3\u6b65\u9aa4\uff08ontA \u7684 `plan`\u3001ontB \u7684 `intent_parse`\uff09\u51fa\u73b0\u4e86\u4e24\u6b21\uff0c\u7b2c\u4e8c\u6b21\u7684\u65f6\u95f4\u533a\u95f4**\u5d4c\u5957\u5728**\u7b2c\u4e00\u6b21\u4e4b\u5185"
     u"\u2014\u2014\u667a\u80fd\u4f53\u5728\u4e00\u6b65\u8fd8\u6ca1\u8d70\u5b8c\u65f6\u5c31\u91cd\u5f00\u4e86\u8ba1\u5212\u3002`kernel/cluster.collapse()` \u4f1a\u6298\u53e0\u76f8\u90bb\u91cd\u590d\uff0c\u6240\u4ee5\u6a21\u5f0f\u89c6\u56fe\u770b\u5230\u7684"
     u"\u9aa8\u67b6\u5b8c\u5168\u4e0d\u53d8\uff0c\u53ea\u6709 `plan_revision_count` \u80fd\u770b\u89c1\u5b83\u3002\u8fd9\u4e5f\u662f\u8be5\u7279\u5f81\u88ab\u5b9a\u4e49\u6210\u201c\u65f6\u95f4\u5305\u542b\u201d\u800c\u4e0d\u662f\u201c\u8ba1\u6570\u51cf\u4e00\u201d\u7684\u539f\u56e0\uff1a"
     u"\u5faa\u73af\u6ce8\u5165\u5668\u540c\u6837\u53ef\u80fd\u9009\u4e2d\u5165\u53e3\u6b65\u9aa4\uff0c\u8ba1\u6570\u51cf\u4e00\u4f1a\u628a\u4e00\u6b21\u5faa\u73af\u8bfb\u6210\u4e24\u6b21\u8ba1\u5212\u4fee\u8ba2\u3002"),
    ("goal_drift", lambda g: bool(g.get("goal_drift_true")),
     u"\u67d0\u4e2a `subgoal_text` \u4e0e\u672c\u6761\u8f68\u8ff9\u7684 `goal_text` **\u6ca1\u6709\u4efb\u4f55\u5185\u5bb9\u8bcd\u91cd\u53e0**\u2014\u2014\u667a\u80fd\u4f53\u5728\u8fd9\u4e00\u6b65\u8dd1\u504f\u4e86\u3002\u7279\u5f81\u4fa7\u7528\u8bcd\u5143"
     u"\u5305\u542b\u7387 `1 - |G \u2229 S| / |G|` \u5ea6\u91cf\uff1a\u8dd1\u504f\u65f6\u6070\u597d\u4e3a 1.0\uff0c\u5728\u8f68\u65f6\u6070\u597d\u4e3a 0.0\uff0c\u6240\u4ee5 `goal_drift_max >= 0.5` \u4e0e\u771f\u503c"
     u"\u6784\u6210\u4e25\u683c\u7684\u53cc\u5411\u7b49\u4ef7\u3002\u751f\u6210\u5668\u4e3a\u6b64\u4e13\u95e8\u8fc7\u6ee4\u6389\u4efb\u4f55\u4e0e\u76ee\u6807\u5171\u4eab\u8bcd\u5143\u7684\u7ed5\u8def\u6a21\u677f\uff0c\u5426\u5219\u771f\u503c\u4f1a\u58f0\u79f0\u6f02\u79fb\u800c\u6570\u636e\u91cc\u91cf\u4e0d\u51fa\u6765\u3002"),
    ("invalid_tool_arg", lambda g: (g.get("arg_valid_true") is not None
                                    and g["arg_valid_true"] < 1.0),
     u"\u5de5\u5177\u5165\u53c2\u8fdd\u53cd\u4e86\u672c\u4f53\u7684 `param_schema`\uff08\u679a\u4e3e\u8d8a\u754c / \u524d\u7f00\u4e0d\u7b26\uff09\u3002`arg_valid` \u662f**\u6d4b\u91cf**\u51fa\u6765\u7684\u800c\u4e0d\u662f\u65ad\u8a00\u7684\uff1a"
     u"\u751f\u6210\u5668\u6784\u9020\u5b8c\u8fdd\u89c4\u53c2\u6570\u540e\u4f1a\u518d\u8dd1\u4e00\u6b21\u540c\u4e00\u4e2a\u6821\u9a8c\u51fd\u6570\uff0c\u53ea\u6709\u786e\u5b9e\u5224\u4e3a\u8fdd\u89c4\u624d\u843d\u5e93\u3002\u5faa\u73af\u4e0e\u91cd\u8bd5\u7684\u526f\u672c\u5171\u4eab\u540c\u4e00\u4efd\u53c2\u6570\uff0c"
     u"\u6240\u4ee5\u4e00\u4e2a\u8fdd\u89c4\u7ec4\u91cc\u7684\u6bcf\u4e2a\u526f\u672c\u90fd\u540c\u6837\u8fdd\u89c4\u2014\u2014\u8fd9\u662f\u523b\u610f\u7684\uff0c\u5426\u5219 `(parent, action, \u53c2\u6570\u54c8\u5e0c)` \u5206\u7ec4\u4f1a\u88ab\u62c6\u5f00\uff0c"
     u"\u4e00\u4e2a\u771f\u5faa\u73af\u5c31\u6084\u6084\u53d8\u6210\u4e86\u975e\u5faa\u73af\u3002"),
    ("verifier_fail", lambda g: (g.get("verifier_pass_true") is not None
                                 and g["verifier_pass_true"] < 1.0),
     u"\u786e\u5b9a\u6027\u6821\u9a8c\u5668\u7ed9\u51fa FAIL\u3002\u4e09\u4e2a\u6821\u9a8c\u5668\u5168\u90e8\u662f\u4ee3\u7801\u5224\u5b9a\uff0c\u6ca1\u6709\u4efb\u4f55\u751f\u6210\u5f0f\u5224\u5b98\u53c2\u4e0e\uff1a`v_numbers_traceable`"
     u"\uff08\u7b54\u6848\u91cc\u7684\u6570\u5b57\u5fc5\u987b\u80fd\u5728\u8bc1\u636e\u6c60\u4e2d\u627e\u5230\uff09\u3001`v_no_forbidden_action`\uff08\u7981\u7528\u52a8\u4f5c\u4e0d\u5f97\u88ab\u542f\u52a8\uff09\u3001"
     u"`v_answer_nonempty`\uff08\u7b54\u6848\u975e\u7a7a\uff09\u3002\u5b83\u4eec\u7684\u7ed3\u679c\u662f\u4ece\u843d\u5e93\u8bb0\u5f55\u672c\u8eab\u53cd\u63a8\u51fa\u6765\u7684\uff0c\u800c\u4e0d\u662f\u751f\u6210\u5668\u7684\u610f\u56fe\u3002"),
    ("fabricated_citation", lambda g: bool(g.get("fabricated_citation_count")),
     u"\u7b54\u6848\u5f15\u7528\u4e86\u4e00\u4e2a**\u683c\u5f0f\u5b8c\u5168\u5408\u6cd5**\u7684\u5b9a\u4f4d\u7b26\uff0c\u4f46\u5b83\u4e0d\u5728\u672c\u6b21\u68c0\u7d22\u5230\u7684\u7ed3\u679c\u96c6\u91cc\u3002\u771f\u5b9e\u667a\u80fd\u4f53\u7684\u7f16\u9020\u51e0\u4e4e\u4ece\u4e0d\u662f\u51ed\u7a7a\u9020\u4e00\u4e2a"
     u"URL\uff0c\u800c\u662f\u628a\u7247\u6bb5\u53f7\u5199\u9519\u2014\u2014\u6240\u4ee5 `citation_reachability` \u5fc5\u987b\u5bf9\u7740\u68c0\u7d22\u7ed3\u679c\u96c6\u7b97\uff0c\u800c\u4e0d\u662f\u5bf9\u7740 URL \u767d\u540d\u5355\u6216\u683c\u5f0f"
     u"\u6821\u9a8c\u7b97\u3002\u751f\u6210\u5668\u6b63\u662f\u8fd9\u6837\u4f2a\u9020\u7684\uff1a\u53d6\u4e00\u4e2a\u771f\u5b9e\u5b9a\u4f4d\u7b26\uff0c\u628a `#L` \u7247\u6bb5\u6539\u5230 1001~1900 \u533a\u95f4\u3002"),
    ("contradicted_evidence", lambda g: bool(g.get("contradicted_count")),
     u"\u7b54\u6848\u9648\u8ff0\u4e86\u4e0e\u8bc1\u636e\u76f8\u53cd\u7684\u5173\u7cfb\u3002\u6ce8\u610f\u5b83\u4e0e\u5e7b\u89c9\u7684\u533a\u522b\uff1a\u77db\u76fe\u6d89\u53ca\u7684\u4e8b\u5b9e**\u5728**\u8bc1\u636e\u6c60\u91cc\uff0c\u53ea\u662f\u5173\u7cfb\u88ab\u8bf4\u53cd\u4e86\u3002\u751f\u6210\u5668\u53ea\u4ece"
     u"`golden_facts \u2229 answer_facts` \u91cc\u91c7\u6837\uff0c\u4ece\u7ed3\u6784\u4e0a\u4fdd\u8bc1\u4e86\u8fd9\u4e00\u70b9\u3002\u7279\u5f81\u4fa7\u7684 `contradiction_rate` \u4ecd\u6807\u8bb0\u4e3a"
     u"`needs_model`\u2014\u2014\u6570\u636e\u96c6\u8d1f\u8d23\u63d0\u4f9b\u8f93\u5165\u4e0e\u771f\u503c\uff0c\u6570\u503c\u672c\u8eab\u8981\u7b49\u771f\u5b9e NLI \u6a21\u578b\u63a5\u4e0a\u624d\u6709\u610f\u4e49\u3002"),
)

STATS_V3 = u"- v3 \u4fe1\u53f7\uff1a%s"
STATS_LANG = u"- \u8bed\u79cd\u5206\u5e03\uff1a%s\uff1b\u4f1a\u8bdd\u6570 **%s**\uff0c\u6bcf\u4f1a\u8bdd\u8f6e\u6b21 %s"


def write_sample(regime, bundle=None, atypes=None):
    bundle = bundle or load(regime)
    path = os.path.join(DATA, regime, "SAMPLE.md")
    parts = [NARRATIVE % {"regime": regime, "n_traces": len(bundle["traces"]),
                          "n_scores": len(bundle["scores"])}]
    parts.append(STATS_HDR)
    parts.extend(u"%s" % line for line in _stats_lines(bundle, regime))
    parts.append(u"")
    parts.append(u"---")
    parts.append(u"")
    parts.append(u"## \u4e94\u3001\u5b8c\u6574\u6837\u672c\uff1a\u8f93\u5165 \u2192 \u771f\u503c \u2192 \u7b97\u6cd5\u8f93\u51fa")
    parts.append(u"")
    normals = _first_normal(bundle, limit=1)
    if normals:
        parts.append(SAMPLE_TITLE["normal"])
        parts.append(u"")
        parts.append(u"```text")
        parts.extend(render_trace(regime, normals[0], bundle))
        parts.append(u"```")
        parts.append(u"")
    idx = 0
    for atype, need_golden in (atypes or SAMPLE_SPEC):
        hits = _by_type(bundle, atype, 1, need_golden=need_golden)
        if not hits:
            continue
        idx += 1
        label = atype + (u"\uff08\u5e26 golden\uff09" if need_golden else u"")
        parts.append(SAMPLE_TITLE["anomaly"] % {"i": "BCDEFGHI"[idx - 1] if idx > 1 else "B",
                                                "atype": label, "tid": hits[0]})
        parts.append(u"")
        note = ANOM_NOTE.get(atype)
        if note:
            parts.append(note)
            parts.append(u"")
        if need_golden:
            parts.append(GOLDEN_NOTE.get(atype, GOLDEN_NOTE["*"]))
            parts.append(u"")
        parts.append(u"```text")
        parts.extend(render_trace(regime, hits[0], bundle))
        parts.append(u"```")
        parts.append(u"")
    parts.append(V3_HDR)
    vi = 0
    for name, pred, note in V3_SPEC:
        hits = _by_pred(bundle, pred, 1)
        if not hits:
            continue
        vi += 1
        parts.append(V3_ITEM % {"i": "ABCDEFG"[vi - 1], "name": name, "tid": hits[0]})
        parts.append(u"")
        parts.append(note)
        parts.append(u"")
        parts.append(u"```text")
        parts.extend(render_trace(regime, hits[0], bundle))
        parts.append(u"```")
        parts.append(u"")
    if not vi:
        parts.append(u"- (none)")
        parts.append(u"")
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(u"\n".join(parts))
    return path


def _side(bundle, regime):
    counts = {}
    for gt in bundle["gt"].values():
        for atype in gt.get("anomaly_types") or []:
            counts[atype] = counts.get(atype, 0) + 1
    n_anom = sum(1 for g in bundle["gt"].values() if g.get("is_anomaly"))
    print("regime %s" % regime)
    print("  traces=%d spans=%d anomalies=%d (%.2f%%) scored=%d"
          % (len(bundle["traces"]), sum(len(t["spans"]) for t in bundle["traces"].values()),
             n_anom, 100.0 * n_anom / max(1, len(bundle["traces"])), len(bundle["scores"])))
    print("  anomaly types: %s" % ", ".join("%s=%d" % (k, counts[k])
                                            for k in sorted(counts, key=lambda x: -counts[x])))
    print("  files: data/bench_v1/%s/{traces.jsonl,gt.jsonl,meta.json}" % regime)
    print("         reports/%s/{scores.jsonl,metrics.json,report.md}" % regime)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    regime = argv[1]
    rest = argv[2:]
    bundle = load(regime)
    if not bundle["traces"]:
        print("no traces for regime %s; run `python -m bench.generate --regimes %s`" % (regime, regime))
        return 2
    if not rest:
        _side(bundle, regime)
        return 0
    if rest[0] == "--sample":
        print("wrote %s" % write_sample(regime, bundle))
        return 0
    if rest[0] == "--stats":
        _side(bundle, regime)
        return 0
    if rest[0] == "--list":
        atype = rest[1] if len(rest) > 1 else None
        limit = int(rest[2]) if len(rest) > 2 and rest[2].isdigit() else 20
        if atype in (None, "all"):
            ids = [tid for tid, g in bundle["gt"].items() if g.get("is_anomaly")][:limit]
        else:
            ids = _by_type(bundle, atype, limit, need_golden=("--golden" in rest))
        print("%d trace ids (%s):" % (len(ids), atype or "any-anomaly"))
        for tid in ids:
            print("  %s  %s" % (tid, ",".join(bundle["gt"][tid].get("anomaly_types") or [])))
        return 0
    if rest[0] == "--random":
        limit = int(rest[1]) if len(rest) > 1 else 3
        ids = sorted(bundle["traces"])
        step = max(1, len(ids) // limit)
        rest = ids[::step][:limit]
    for tid in rest:
        for line in render_trace(regime, tid, bundle, ascii_only=True):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))