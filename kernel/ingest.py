"""Span-tree normalization + data-quality flags (contracts/schemas.md section 1)."""
KEY_FIELDS = ("ts_start", "ts_end", "tokens_prompt", "tokens_completion", "cost", "status")


# Conditional availability. A field only counts as missing when the span kind is supposed
# to carry it: tool spans legitimately report no tokens, so counting them would turn
# missing_field_ratio into a measure of the span-kind mix instead of of telemetry loss.
EXPECTED_FIELDS = {
    "llm": ("ts_start", "ts_end", "tokens_prompt", "tokens_completion", "cost", "status",
            "model", "ttft", "prompt_version", "tokens_system_prompt", "tokens_cache_read",
            "tokens_cache_write", "subgoal_text"),
    "agent": ("ts_start", "ts_end", "tokens_prompt", "tokens_completion", "cost", "status",
              "model", "tokens_system_prompt", "tokens_cache_read", "tokens_cache_write"),
    "tool": ("ts_start", "ts_end", "cost", "status", "tool_name", "arg_valid"),
    "retrieval": ("ts_start", "ts_end", "cost", "status", "tool_name", "arg_valid",
                  "output_citations"),
    "guard": ("ts_start", "ts_end", "cost", "status", "verifier"),
}

# `verifier` is expected on every guard span but on no llm span, and `subgoal_text` on every
# llm span but on no tool span. `cost_details` is deliberately absent from both lists: it is a
# decomposition of `cost`, so counting it would double-count the loss of the cost field, and
# normalize() rebuilds it whenever it rebuilds cost.


def expected_fields(kind):
    return EXPECTED_FIELDS.get(kind, KEY_FIELDS)


def normalize(trace, ontology):
    spans = [dict(s) for s in trace["spans"]]
    # missing_field_ratio must be measured on the RAW spans, before anything below repairs
    # them. Measuring after repair made it structurally 0.0 on every trace of every regime
    # (including R5, which injects 45% corrupted telemetry), which turned the
    # `mfr > 0.20` confidence downgrade in kernel/score.py into dead code and left the
    # appendix A.7 requirement ("missingness feeds global confidence") unverified.
    exp_total = sum(len(expected_fields(s.get("kind"))) for s in spans)
    raw_miss = sum(1 for s in spans for k in expected_fields(s.get("kind"))
                   if s.get(k) is None)
    mfr_raw = (raw_miss / float(exp_total)) if exp_total else 0.0
    missing_fields = sorted({k for s in spans for k in expected_fields(s.get("kind"))
                             if s.get(k) is None})
    flags = {"orphan_rebuilt": False, "ts_repaired": False, "usage_estimated": False}
    ids = {s["span_id"] for s in spans}
    roots = [s for s in spans if s.get("parent_id") is None]

    for s in spans:
        pid = s.get("parent_id")
        if pid is not None and pid not in ids:
            host = None
            for c in spans:
                if c["span_id"] != s["span_id"] and c["ts_start"] <= s["ts_start"] \
                        and c["ts_end"] >= s["ts_end"]:
                    if host is None or (c["ts_end"] - c["ts_start"]) < (host["ts_end"] - host["ts_start"]):
                        host = c
            s["parent_id"] = host["span_id"] if host else (roots[0]["span_id"] if roots else None)
            flags["orphan_rebuilt"] = True

    for s in spans:
        if s["ts_end"] < s["ts_start"]:
            s["ts_start"], s["ts_end"] = s["ts_end"], s["ts_start"]
            flags["ts_repaired"] = True
    by_id = {s["span_id"]: s for s in spans}
    for s in spans:
        p = by_id.get(s.get("parent_id"))
        if p is not None and (s["ts_start"] < p["ts_start"] - 1e-9 or s["ts_end"] > p["ts_end"] + 1e-9):
            s["ts_start"] = max(s["ts_start"], p["ts_start"])
            s["ts_end"] = min(s["ts_end"], p["ts_end"]) if p["ts_end"] >= s["ts_start"] else s["ts_end"]
            flags["ts_repaired"] = True

    price = ontology["unit_price"]
    for s in spans:
        if s.get("tokens_prompt") is None or s.get("tokens_completion") is None:
            n_in = max(1, len(s.get("input_text") or "") // 4)
            n_out = max(1, len(s.get("output_text") or "") // 4)
            if s.get("tokens_prompt") is None:
                # An imputed prompt volume has to stay an upper bound of the prompt components
                # the span still reports. `len(input_text)//4` is a prose-length heuristic that
                # knows nothing about the system prompt or the prompt cache, so on its own it
                # produced spans whose tokens_cache_read exceeded their own tokens_prompt (52
                # spans in the 700-trace dev sample) and a trace-level system_prompt_ratio of
                # 2.098. A ratio above 1 is not an estimate, it is a contradiction, and it
                # propagates straight into cache_hit_ratio and context_utilization. Measured
                # after the floor: 0 violations on the same sample, system_prompt_ratio <= 1.
                floor = max(s.get("tokens_system_prompt") or 0,
                            s.get("tokens_cache_read") or 0,
                            s.get("tokens_cache_write") or 0)
                s["tokens_prompt"] = max(n_in, floor)
            if s.get("tokens_completion") is None:
                s["tokens_completion"] = n_out
            flags["usage_estimated"] = True
        if s.get("cost") is None:
            # Rebuild the decomposition together with the total, so that the invariant
            # sum(cost_details.values()) == cost survives the repair. Cache tokens that were
            # themselves lost are treated as absent rather than imputed: an estimate that
            # invented a cache discount would be worse than one that admits it sees none.
            tp = s["tokens_prompt"]
            cr = min(s.get("tokens_cache_read") or 0, tp)
            cw = s.get("tokens_cache_write") or 0
            p_prompt = price["prompt"]
            c_prompt = (tp - cr) * p_prompt
            c_compl = s["tokens_completion"] * price["completion"]
            c_tool = price["tool_call"] if s["kind"] == "tool" else 0.0
            c_cr = cr * price.get("cache_read", p_prompt)
            c_cw = cw * price.get("cache_write", 0.0)
            s["cost"] = c_prompt + c_compl + c_tool + c_cr + c_cw
            s["cost_details"] = {"prompt": c_prompt, "completion": c_compl,
                                 "tool_call": c_tool, "cache_read": c_cr,
                                 "cache_write": c_cw}
            flags["usage_estimated"] = True

    spans.sort(key=lambda s: (s["ts_start"], s["span_id"]))
    total = len(spans) * len(KEY_FIELDS)
    miss = sum(1 for s in spans for k in KEY_FIELDS if s.get(k) is None)
    out = dict(trace)
    out["spans"] = spans
    out["flags"] = flags
    out["missing_field_ratio"] = mfr_raw
    out["missing_field_ratio_post"] = (miss / float(total)) if total else 0.0
    out["missing_fields"] = missing_fields
    return out
