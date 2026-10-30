"""Parameterized, seeded, pure-python generator for the standard benchmark dataset.

Design intent
  The generator emits a *distribution regime*, not a business. Every knob the kernel is
  supposed to be robust to is an explicit axis (contracts/schemas.md 7): modality of the
  latency mixture, intent separability, cell sparsity, telemetry corruption rate, drift,
  cold start, foreign ontology, anomaly rate and anomaly type mix. Ground truth is emitted
  alongside the data so the runner can score clustering / detection / ranking / calibration
  without any human or LLM in the loop.

  Ground truth is *generative*, not empirical: the oracle per-dimension score of a normal
  trace is derived from the latent quantile that produced its latency and token draw
  (q = Phi(z) of the gaussian that was exponentiated), so the scoring gate is a real test
  and not a restatement of the kernel's own percentile arithmetic.

  human_label = oracle XOR 5% noise, on a fixed label budget, to exercise the calibration
  and label-fused slices without pretending synthetic labels are business truth.

v3 (bench-gen-v3.0.0)
  Closes the last 11 dataset blockers of the appendix-A 77-feature contract and both of its
  fidelity failures. Each addition and the reason it is shaped this way:

  * 384-dim anisotropic embeddings on a topic continuum (was 16-dim isotropic). A 16-dim
    Gaussian blob satisfies the *type* of `query_embedding` and validates nothing: real
    sentence embeddings share a dominant direction (so every pair of traces has a large
    cosine), have a heavy-tailed per-dim scale (so the dims are not exchangeable and
    unwhitened Euclidean is dominated by a handful of them) and place neighbouring intents on
    an arc instead of at orthogonal poles. See `_emb_basis`.
  * Bilingual queries, >= 8 wordings per intent. With one fixed phrase per intent,
    `query_complexity` is constant inside a cell and can explain nothing, and `query_lang` is
    decoration. Language also scales the token volume (`lang_token_factor`), which turns it
    into a genuine nuisance axis that a cost baseline has to be stratified on.
  * Prompt-cache / system-prompt / cost_details accounting, argument schemas with injected
    violations, per-span verifier outcomes, retrieval citations with fabricated answer
    citations, and subgoal text with injected off-goal detours.
  * Plan revision: a nested repeat of the workflow entry action, placed inside the first
    span's interval and only when the next sibling does not overlap it. `cluster.collapse`
    therefore still folds it away, so the collapsed skeleton - the input of the pattern view
    and of the `n_true_patterns` binding - is unchanged, while `plan_revision_count` becomes
    computable.

  Co-defect rule. Contradiction, fabricated citation and goal drift are injected *only on
  traces that are already anomalous for another reason*. A standalone `contradiction` class
  is not detectable by this kernel (every number is still traceable; only its relation to the
  evidence is wrong), so adding it as a tenth anomaly type would price a capability the
  pipeline does not have and push F1 below the gates for a reason unrelated to clustering or
  scoring. The dataset carries the ground truth so a future NLI-backed detector can be
  validated; the class itself is deferred, and the deferral is recorded in
  contracts/schemas.md.

v3.1 (bench-gen-v3.1.0)
  Embedding-geometry retune, and the only change is to the `embedding` field plus the regime
  field that drives it. v3.0.0 moved to 384 dims without re-deriving the difficulty knobs,
  and the ari_intent gate then became unmeetable: R3 scored 0.2513 against a plug-in Bayes
  ceiling of 0.4824 (52% attainment) and R4 0.4651 against 0.9803 (47%), against a gate rule
  that asks for 90% of the ceiling. Two independent defects, both measured:

  * The per-dim scale contrast was 22x, which drops the participation ratio
    (sum s^2)^2 / (sum s^4) to 23-32 dims out of 384. A whitened oracle recovered the intent
    at ARI 0.9967 where the isotropic one reached 0.4574, so the information was present and
    unwhitened Euclidean could not read it. Contrast is now 3.5x, PR ~106-140.
  * `spec["overlap"]` inflates sigma_e, and sigma_e-driven hardness is a kind an unsupervised
    view cannot be scored on: even on an exactly flat geometry (PR ~300) k-means tracks the
    oracle at 0.997 of it at overlap 0.88 and 0.052 of it at overlap 1.90. Difficulty now
    comes from `spec["intent_ambiguity"]` - genuine between-intent traces - which lowers the
    oracle and k-means together, so the ceiling stays an honest bound.

  Full measurements, and the two retunes that were tried and rejected, are in the geometry
  constant block below. `EMB_TOPIC_AMP` 7.0 -> 10.0 is required separately by the 4-intent
  regimes, whose separation-to-noise-radius ratio is dimension-limited.

  RNG discipline. Four streams, and the split is load-bearing:
    rng   random.Random(spec["seed"]) - every draw that existed in v1, in the same order.
    raux  "%s#%d"          - the v2 telemetry fields (model, prompt_version, level, ...).
    r3    "%s|v3#%d"       - everything added in v3.
    remb  "%s|emb#%d|%d"   - the embedding, on its own stream *on purpose*: changing EMB_DIM
                             must never perturb a quantity draw again.
  Adding a v3 field therefore cannot reshuffle the v1 draws of the trace it lands on.

Usage
  python -m bench.generate --regimes R1,R4,R6 [--out data/bench_v1]
"""
import argparse
import hashlib
import json
import math
import os
import random

from bench import regime as RG
from kernel.ingest import expected_fields
from ontology.base import get_ontology

GEN_VERSION = "bench-gen-v3.1.0"
T0 = 1767225600.0
ANOMALY_TYPES = ("latency_spike", "token_bloat", "loop", "error", "missing_step",
                 "illegal_step", "hallucinated_number", "truncation", "unfinished")

# ---- embedding geometry (appendix A.4 #37: d = 384 / 768 / 1024) -------------------------
EMB_DIM = 384
EMB_SIG_DIMS = 16          # topic-bearing dims; the rest carry a heavier background scale
EMB_ARC_STEP = 0.75        # radians between adjacent intent directions (the topic continuum)
EMB_DOMINANT = 2.0         # shared-direction amplitude -> narrow cone, high pairwise cosine
EMB_NORM_SIGMA = 0.06      # per-trace length variation along it (sentence length, not topic)
# EMB_DOMINANT * EMB_NORM_SIGMA = 0.12 stays fixed: that product is the only way the cone
# enters a Euclidean distance, so the cosine level moves without moving a ceiling.
#
# Retuned in bench-gen-v3.1.0 (AMP, BG_MU, BG_SIGMA together, plus the new per-regime
# spec["intent_ambiguity"]). Three numbers moved because one measurement showed the v3.0.0
# geometry made the ari_intent gate unmeetable, and the cause was not the one the failing
# number suggests. All figures below come from the same harness: 1200 traces of a regime
# shape, reporting ari_iso (the gate ceiling - true class means, true priors, one pooled
# isotropic variance), ari_wht (the same oracle with a pooled per-dim variance, i.e. the
# rule that is genuinely Bayes-optimal under non-exchangeable dims) and ari_km (one plain
# kmeans_cent run at the true k, which is what the consensus view is built out of).
#
# BEFORE, v3.0.0 (AMP 7.0, BG_MU -2.5, BG_SIGMA 1.0):
#     2 intents, overlap 0.88   ari_iso 0.4574   ari_wht 0.9967   ari_km 0.0974
#     4 intents, overlap 0.30   ari_iso 1.0000   ari_wht 1.0000   ari_km 0.6970
# ari_wht 0.9967 against ari_iso 0.4574 says the intent signal was essentially all there and
# the isotropic reader could not reach it. The mechanism is the participation ratio
# PR = (sum s^2)^2 / (sum s^4) of the per-dim scale vector - the number of dims that can
# actually carry a Euclidean distance - because the isotropic discriminant's SNR is
#     (AMP / sigma_e) * ||delta|| * sqrt(PR / EMB_DIM)
# and PR measured 23-32 out of 384. A 22x contrast between the signal dims (scale ~1.08) and
# the background median (exp(-2.5) = 0.082) puts almost all of sum s^4 into 16 dims, so
# unwhitened k-means was solving a ~30-dim problem wearing a 384-dim costume. The v3.0.0 R3
# run measured exactly that: ari_intent 0.2513 against a ceiling of 0.4824, 52% attainment,
# and R4 0.4651 against 0.9803, 47%.
#
# REJECTED, lower BG_SIGMA - the obvious knob, and it does not work. PR is bounded by the 16
# signal dims themselves: PR ~ (f^2 S + (d-S))^2 / (f^4 S + (d-S)) in the contrast
# f = signal scale / background scale gives 20.6 at f = 13 for any BG_SIGMA. Measured,
# BG_SIGMA 1.0 -> 0.45 alone moved ari_km 0.0974 -> 0.2313 and left km/iso at 0.705. The
# contrast is the lever; the tail is not.
#
# REJECTED, keep the contrast and re-harden R3 by raising overlap. Raising PR alone is not
# enough either. On an exactly flat, exchangeable geometry (BG_SIGMA 0.05, PR 296-301) km/iso
# still collapses as sigma_e grows - 0.997 / 0.986 / 0.908 / 0.052 / 0.034 at overlap
# 0.88 / 1.20 / 1.55 / 1.90 / 2.40 - and stacking the two mechanisms is worse than either
# (overlap 0.88 with ambiguity 0.55 gives km/iso 0.065). sigma_e-driven hardness is a kind
# of hardness an unsupervised view structurally cannot read: the oracle projects onto the
# true discriminant, while k-means must average noise over all 384 dims and below a
# separation threshold it splits noise instead of classes. No geometry closes that gap, so
# difficulty has to be injected as genuine label ambiguity instead.
#
# AFTER (AMP 10.0, BG_MU -0.90, BG_SIGMA 0.45; contrast 3.5x, PR ~106-140):
#     4 intents, overlap 0.30, ambiguity 0.12   ari_iso 1.0000   ari_km 1.0000   km/iso 1.000
#     3 intents, overlap 0.30, ambiguity 0.12   ari_iso 1.0000   ari_km 1.0000   km/iso 1.000
#     2 intents, overlap 0.30, ambiguity 0.55   ari_iso 0.6159   ari_wht 0.6397
#                                               ari_km  0.6081   km/iso  0.987
# AMP 10.0 is the smallest value that lifts the 4-intent case off 0.6970. What limits it is
# the separation-to-noise-radius ratio AMP * ||delta|| / (sigma_e * sqrt(dim)), which is
# 1.25 at AMP 7 and 1.78 at AMP 10; k=4 needs the higher one and k=2 does not. AMP is not
# raised further because at AMP 14 overlap goes inert (ari_iso 1.0000 at overlap 0.88), and
# a spec field that cannot move a metric is not a knob.
# ari_wht 0.6397 against ari_iso 0.6159 is the property that matters most: the residual
# hardness is now genuine ambiguity, which whitening cannot undo, so the reported ceiling is
# an honest information bound rather than an artifact of the isotropic assumption.
EMB_TOPIC_AMP = 10.0       # topic amplitude; calibration and rejected alternatives above
EMB_BG_MU = -0.90          # background per-dim scale exp(N(mu, sigma)). The dims are still
EMB_BG_SIGMA = 0.45        # not exchangeable - background median 0.41 against signal dims
                           # at ~1.41, with a ~2.4x spread inside the background itself - but
                           # the contrast is 3.5x rather than 22x, which is what keeps PR
                           # high enough for unwhitened Euclidean to aggregate over ~120 dims.
EMB_CONTINUUM = 0.12       # default max pull of a trace toward the mean of the other intents.
                           # Per-regime override: spec["intent_ambiguity"], and that field,
                           # not spec["overlap"], is how a regime makes an intent boundary
                           # hard while staying scoreable by an unsupervised view.

# ---- conditional availability -------------------------------------------------------------
# In production a golden answer exists only for the curated evaluation subset and only a
# minority of operators click thumbs, so both are emitted on a fraction of traces. The kernel
# must treat them as *absent* (None), never as "perfect".
GOLDEN_RATE = 0.30
FEEDBACK_RATE = 0.25

# Rates of the v3 co-defects. Every one of them fires only on an already-anomalous trace.
PLAN_REVISION_RATE = 0.08
DRIFT_RATE_BY_TYPE = {"illegal_step": 0.60, "missing_step": 0.45, "unfinished": 0.45,
                      "loop": 0.35, "error": 0.20}
CONTRADICTION_TYPES = ("hallucinated_number", "truncation", "error")
CONTRADICTION_RATE = 0.50
FABRICATED_CITATION_TYPES = ("hallucinated_number", "truncation")
FABRICATED_CITATION_RATE = 0.60
# Argument-schema violations. The baseline rate is the ordinary sloppiness of a real agent;
# the per-type boosts make the feature informative about the failures that matter instead of
# being pure noise.
ARG_INVALID_BASE = 0.012
ARG_INVALID_BY_TYPE = {"illegal_step": 0.85, "error": 0.45, "loop": 0.20}
# Prompt cache: a miss writes the system prompt, a hit reads it back at a discount. The first
# LLM call of a session misses; a later turn hits even on its first call.
CACHE_MISS_RATE = 0.10
SESSION_MIN, SESSION_MAX = 2, 7

NE_HEX = "0123456789ABCDEF"

# Which fields each span kind can lose. Deliberately excludes tokens_prompt/completion and
# cost, so that the field-loss pass moves missing_field_ratio without also perturbing the cost
# dimension the gates are measured on.
LOSSABLE = {"llm": ("model", "ttft", "prompt_version", "tokens_system_prompt",
                    "tokens_cache_read", "tokens_cache_write", "subgoal_text"),
            "agent": ("model", "tokens_system_prompt", "tokens_cache_read",
                      "tokens_cache_write"),
            "tool": ("tool_name", "tool_params", "arg_valid"),
            "retrieval": ("tool_name", "arg_valid", "output_citations"),
            "guard": ("verifier",)}


def _param_groups(all_spans):
    """(action, normalized param hash) -> count, over the spans the loop truth may use.

    The `-n1` nested sub-call is excluded because it is a duplicate of its own parent by
    construction, so counting it would report a loop on a trace that merely nests one tool call.
    `loop_true` and the field-loss guard in build() both go through this function, so the loop
    definition cannot drift between the label and the guard that protects it.
    """
    grp = {}
    for x in all_spans:
        if x["span_id"].endswith("-n1"):
            continue
        key = (x["action"], _param_hash(x.get("tool_params")))
        grp[key] = grp.get(key, 0) + 1
    return grp


def _aux_rng(spec_id, idx):
    """Independent RNG stream for the v2 telemetry fields.

    Kept separate from the primary `rng` on purpose. Every draw that existed in v1 must stay
    bit-identical, so that a field addition is an *additive* dataset change and the earlier
    gate numbers stay attributable instead of being reshuffled by an unrelated draw.
    """
    return random.Random("%s#%d" % (spec_id, idx))


def _v3_rng(spec_id, idx):
    """Independent RNG stream for every field added in v3. Same reason as `_aux_rng`."""
    return random.Random("%s|v3#%d" % (spec_id, idx))


def _emb_rng(spec_id, idx, dim):
    """Dedicated stream for the embedding draw.

    In v2 the embedding came off the primary `rng`, so raising EMB_DIM from 16 to 384 would
    have consumed 368 extra primary draws per trace and silently re-rolled every latency,
    token and anomaly decision in the dataset. Its own stream makes the dimensionality
    upgrade what it should be: a change to exactly one field.
    """
    return random.Random("%s|emb#%d|%d" % (spec_id, idx, dim))


def _session_rng(spec_id):
    return random.Random("%s|sess" % spec_id)


def _ne_id(raux):
    return "NE-" + "".join(NE_HEX[raux.randrange(16)] for _ in range(4)) + \
           "-%02d" % raux.randrange(1, 60)


def _fmt(tmpl, ctx):
    if not tmpl:
        return None
    try:
        return tmpl.format(**ctx)
    except (KeyError, IndexError):
        return None


def _tool_name(ont, action, raux):
    cat = (ont.get("tool_catalog") or {}).get(action)
    return raux.choice(cat) if cat else None


_PARAM_CHOICE = {"top_k": [3, 5, 10], "depth": [1, 2, 3], "severity": ["critical", "major", "minor"],
                 "table": ["current_alarms", "alarm_history", "kpi_15min"],
                 "kpi": ["cpu_usage", "packet_loss", "latency_ms"],
                 "region": ["east", "north", "south"], "scope": ["ne", "subnetwork"],
                 "rollback": ["auto", "manual"], "granularity": ["1m", "5m", "15m"]}

# Out-of-schema values, one per constraint kind. An invalid argument is *constructed* and then
# re-validated by the same code path that validates the good ones, so `arg_valid` is a measured
# verdict rather than an asserted label.
_BAD_VALUE = {"prefix": "legacy-id-9931", "enum_str": "not-in-enum", "enum_num": -7}


def _tool_params(ont, action, ne, win, raux):
    keys = (ont.get("param_keys") or {}).get(action)
    if not keys:
        return None
    out = {}
    for k in keys:
        if k in ("ne_id", "change_id", "query"):
            out[k] = ("CHG-%05d" % raux.randrange(1, 99999)) if k == "change_id" else ne
        elif k == "time_window":
            out[k] = win
        elif k in _PARAM_CHOICE:
            out[k] = raux.choice(_PARAM_CHOICE[k])
        else:
            out[k] = raux.randrange(1, 50)
    return out


def _validate_args(schema, action, params):
    """Validate one tool call against the ontology's param_schema.

    Returns (ok, reason). Unknown keys and a missing schema are *not* violations: a schema
    that does not cover an argument cannot say anything about it, and treating silence as
    failure would turn tool_arg_valid_rate into a measure of ontology completeness.
    """
    if params is None:
        return True, None
    rules = (schema or {}).get(action) or {}
    for key in sorted(params):
        val = params[key]
        rule = rules.get(key)
        if not rule:
            continue
        if "enum" in rule and val not in rule["enum"]:
            return False, "%s=%r not in enum" % (key, val)
        if rule.get("prefix") and (not isinstance(val, str)
                                   or not val.startswith(rule["prefix"])):
            return False, "%s=%r violates prefix %s" % (key, val, rule["prefix"])
        if rule.get("type") == "string" and not isinstance(val, str):
            return False, "%s=%r is not a string" % (key, val)
    return True, None


def _corrupt_args(schema, action, params, r3):
    """Turn a valid argument vector into an invalid one, if the schema allows it."""
    if not params:
        return params, False
    rules = (schema or {}).get(action) or {}
    cands = sorted(k for k in params if rules.get(k))
    if not cands:
        return params, False
    key = r3.choice(cands)
    rule = rules[key]
    out = dict(params)
    if "enum" in rule:
        out[key] = (_BAD_VALUE["enum_num"] if isinstance(rule["enum"][0], int)
                    else _BAD_VALUE["enum_str"])
    elif rule.get("prefix"):
        out[key] = _BAD_VALUE["prefix"]
    else:
        out[key] = 12345
    ok, _why = _validate_args(schema, action, out)
    return (out, True) if not ok else (params, False)


def _param_hash(params):
    """Byte-identical to kernel/features._param_hash on purpose: the generator's loop truth
    and the kernel's loop feature must group by the same key or the two silently disagree."""
    return json.dumps(params, sort_keys=True) if params is not None else "null"


def _tool_identity(ont, action, ne, win, trace_id, cache, schema=None, p_bad=0.0):
    """Deterministic tool name + params for a (trace, action) pair.

    A pure function of the pair, seeded independently of both the primary and the aux stream.
    That is what makes a loop or a retry carry byte-identical parameters: with params drawn
    from an advancing stream the duplicates differ, the (parent, action, param-hash) group
    never reaches the loop threshold, and `gt.loop_true` contradicts `anomaly_types`.
    """
    key = (trace_id, action)
    if key in cache:
        return cache[key]
    rid = random.Random("%s|%s" % (trace_id, action))
    tname = _tool_name(ont, action, rid)
    params = _tool_params(ont, action, ne, win, rid)
    # The violation is drawn from the SAME seeded stream, so every copy of a looped or retried
    # call carries byte-identical (and identically invalid) arguments. Deciding it per span
    # instead would split the (parent, action, param-hash) group and silently turn a true loop
    # into a non-loop, which is the bug truth_agreement was written to catch.
    if p_bad > 0.0 and rid.random() < p_bad:
        params, _changed = _corrupt_args(schema, action, params, rid)
    ident = (tname, params)
    cache[key] = ident
    return ident

# ---- language-aware content tokens --------------------------------------------------------
# A deliberate second implementation of kernel/features._content_tokens. The generator uses it
# to *guarantee* that an off-goal detour shares no token with the goal of the trace it lands
# on; if the two tokenizers disagreed, coverage.truth_agreement would report it as a
# goal_drift feature/truth mismatch instead of the drift silently never firing.
_EN_STOP = frozenset("""a all also an and any are as at be by can could do does down each every
for from give here his how i if in into is it its just me my need not of off on only or our out
over please show some than that the their them then there these they this to together up want we
what when where which who why with whether your""".split())
_CJK = None


def _content_tokens(text, lang):
    import re as _re
    text = text or ""
    if lang == "zh":
        return set(_re.findall(u"[\u4e00-\u9fff]", text))
    return set(w for w in _re.split(r"[^a-z0-9]+", text.lower())
               if w and w not in _EN_STOP)


def _subgoal(ont, lang, action, goal, ne, win, r3):
    frames = (ont.get("subgoal_frames") or {}).get(lang) or []
    core = ((ont.get("subgoal_core") or {}).get(lang) or {}).get(action)
    if not frames or not core:
        return None
    return _fmt(r3.choice(frames), {"goal": goal, "core": core, "ne": ne, "win": win})


def _detours_for(ont, lang, goal):
    """Detour templates that provably share no content token with this trace's goal.

    Returns an empty list rather than falling back to an unfiltered bank: a detour that
    happens to contain a goal token would read as on-goal, and the trace would then carry
    `goal_drift_true` without carrying any measurable drift.
    """
    bank = (ont.get("subgoal_detour") or {}).get(lang) or []
    g = _content_tokens(goal, lang)
    return [d for d in bank if g and not (_content_tokens(d, lang) & g)]


def _fabricate_citation(sources, r3):
    """A citation that looks like a real locator and resolves to nothing.

    Fabrication by a real agent is almost never an invented URL; it is a plausible locator
    with the wrong fragment. That is exactly why `citation_reachability` must be measured
    against the retrieved set rather than against a URL whitelist or a format check.
    """
    src = r3.choice(sorted(sources))
    for _ in range(20):
        head = src.split("#L", 1)[0]
        cand = "%s#L%d" % (head, 1000 + r3.randint(1, 900))
        if cand not in sources:
            return cand
    return src + "#unreachable"


# ---- embedding geometry -------------------------------------------------------------------
def _unit(v):
    nrm = math.sqrt(sum(x * x for x in v))
    return [x / nrm for x in v] if nrm > 1e-12 else list(v)


def _orth_unit(v, us):
    for u in us:
        d = sum(a * b for a, b in zip(v, u))
        v = [a - d * b for a, b in zip(v, u)]
    return _unit(v)


def _participation(scale):
    """(sum s^2)^2 / (sum s^4): dims able to carry a Euclidean distance.

    Reported in meta.json rather than left as a comment because it is the quantity the whole
    geometry block is calibrated against, and a future retune should be able to check the
    value the shipped dataset actually has instead of trusting the number quoted here.
    """
    s2 = sum(x * x for x in scale)
    s4 = sum(x ** 4 for x in scale)
    return (s2 * s2 / s4) if s4 else 0.0


def _emb_basis(n_int, dim, rng):
    """The shared geometry of one regime's embedding space.

    Three properties of real sentence encoders are reproduced on purpose, because each of them
    breaks something an isotropic 16-dim blob would let pass unnoticed:

      dominant direction  every trace carries a large common component, so all pairwise
                          cosines sit near 0.9 and a cosine threshold tuned on synthetic noise
                          is meaningless. It cancels out of Euclidean distances except through
                          the per-trace length below, which is precisely the real failure mode.
      non-exchangeable    the 384 dims do not carry equal weight: the 16 topic dims sit at
        scale             scale ~1.41 against a background median of 0.41, and the background
                          itself spans ~2.4x. Unwhitened Euclidean is therefore dominated by
                          the heavier dims and "distance concentration" is a property of the
                          data, not a bug. The contrast is deliberately only 3.5x. At the 22x
                          of bench-gen-v3.0.0 the participation ratio (sum s^2)^2 / (sum s^4)
                          collapsed to 23-32 dims out of 384, so a view reading raw Euclidean
                          was solving a ~30-dim problem while the ceiling it was graded
                          against was computed over all 384 - measured, the intent signal was
                          recoverable at ARI 0.9967 by a whitened oracle and 0.4574 by the
                          isotropic one. The geometry block above carries the full sweep.
      topic arc           adjacent intents are near-duplicates (cos = 0.73 at the 0.75 rad
                          step), so the class boundary is a continuum. `spec["intent_ambiguity"]`
                          moves individual traces along it; the arc is what makes even
                          ambiguity = 0 a non-trivial problem.
    """
    u0 = _unit([rng.gauss(0.0, 1.0) for _ in range(dim)])
    scale = [math.exp(rng.gauss(EMB_BG_MU, EMB_BG_SIGMA)) for _ in range(dim)]
    sig = sorted(rng.sample(range(dim), min(EMB_SIG_DIMS, dim)))
    for d in sig:
        scale[d] += 1.0
    e1 = _orth_unit([rng.gauss(0.0, 1.0) for _ in range(dim)], [u0])
    e2 = _orth_unit([rng.gauss(0.0, 1.0) for _ in range(dim)], [u0, e1])
    off = (n_int - 1) / 2.0
    cents = []
    for i in range(n_int):
        th = EMB_ARC_STEP * (i - off)
        c, s = math.cos(th), math.sin(th)
        cents.append([c * e1[d] + s * e2[d] for d in range(dim)])
    # mean of the *other* intent directions, per intent: the point a trace drifts toward when
    # it is only partly about its own intent. Precomputed because it is a regime constant.
    pull = []
    for i in range(n_int):
        others = [cents[j] for j in range(n_int) if j != i]
        pull.append([sum(o[d] for o in others) / len(others) for d in range(dim)]
                    if others else list(cents[i]))
    dom = [EMB_DOMINANT * x for x in u0]
    return {"dom": dom, "scale": scale, "cents": cents, "pull": pull, "sig": sig}


def _embed(basis, intent_i, sigma_e, cont, remb):
    dim = len(basis["dom"])
    c = basis["cents"][intent_i]
    p = basis["pull"][intent_i]
    # Beta(2,6) has mean 0.25, so the expected pull is `cont` and the worst case is 2 * `cont`:
    # a minority of traces really are between two intents, and on the regime that sets it high
    # that minority is what makes the intent boundary hard. `cont` is a regime field rather than
    # a module constant because it is the only difficulty mechanism an unsupervised view can
    # still be scored against - the geometry block above measures the one that cannot, and
    # bench/regime.py R3 carries the sweep that picked the shipped value.
    t = cont * 2.0 * remb.betavariate(2.0, 6.0)
    r = math.exp(remb.gauss(0.0, EMB_NORM_SIGMA))
    scale, dom = basis["scale"], basis["dom"]
    out = [0.0] * dim
    for d in range(dim):
        topic = EMB_TOPIC_AMP * ((1.0 - t) * c[d] + t * p[d])
        out[d] = r * dom[d] + scale[d] * (topic + remb.gauss(0.0, sigma_e))
    return out


def _session_plan(spec_id, n):
    """Variable-length sessions.

    v2 used a fixed `idx // 5`, which makes every session exactly five turns and turns
    `n_turns_in_session` into a constant - a feature that is constant on every regime cannot
    validate anything built on it.
    """
    r = _session_rng(spec_id)
    out, k = [], 0
    while len(out) < n:
        length = min(r.randint(SESSION_MIN, SESSION_MAX), n - len(out))
        sid = "sess-%05d" % k
        k += 1
        for j in range(length):
            out.append((sid, j + 1, length))
    return out


def phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _weighted(rng, items, weights):
    tot = sum(weights)
    r = rng.random() * tot
    acc = 0.0
    for it, w in zip(items, weights):
        acc += w
        if r <= acc:
            return it
    return items[-1]


def _plan_steps(ont, pattern, rng):
    steps = list(ont["required_steps"][pattern])
    for j, a in enumerate(ont.get("optional_steps") or []):
        pr = 0.35 if j == 0 else 0.20
        if a not in ont["kind_map"] or a in steps or rng.random() >= pr:
            continue
        # never after the last required step, so the terminal action stays identifiable
        steps.insert(rng.randrange(1, len(steps)), a)
    return steps


def _kind_dur_weight(kind):
    return {"llm": 1.0, "retrieval": 0.5, "tool": 0.7, "guard": 0.3}.get(kind, 0.6)


def _tokens(kind, dur_share, rng):
    if kind == "llm":
        tp = int(max(120, rng.gauss(900, 250) * (0.7 + 0.6 * dur_share)))
        tc = int(max(40, rng.gauss(320, 110) * (0.7 + 0.6 * dur_share)))
    elif kind == "retrieval":
        tp = int(max(60, rng.gauss(420, 120)))
        tc = 0
    elif kind == "guard":
        tp = int(max(40, rng.gauss(260, 80)))
        tc = int(max(8, rng.gauss(60, 25)))
    else:
        tp = 0
        tc = 0
    return tp, tc


def _cost_and_details(kind, tp, tc, cache_read, cache_write, price):
    """Cost plus an exact additive decomposition of it.

    `sum(cost_details.values()) == cost` is an invariant, not a convention: an attribution that
    does not reconcile with the total is how a cost dashboard ends up arguing with the bill.
    The cache read is a discount and the cache write a surcharge, both quoted per token in the
    ontology, so the decomposition is derivable from data the platform already has.
    """
    p_prompt = price["prompt"]
    c_prompt = max(0, tp - cache_read) * p_prompt
    c_compl = tc * price["completion"]
    c_tool = price["tool_call"] if kind == "tool" else 0.0
    c_cr = cache_read * price.get("cache_read", p_prompt)
    c_cw = cache_write * price.get("cache_write", 0.0)
    return (c_prompt + c_compl + c_tool + c_cr + c_cw,
            {"prompt": c_prompt, "completion": c_compl, "tool_call": c_tool,
             "cache_read": c_cr, "cache_write": c_cw})


def _sample_anomaly(rng, rate, mix):
    if rng.random() >= rate:
        return None
    keys = sorted(mix)
    ws = [mix[k] for k in keys]
    return _weighted(rng, keys, ws)


def _quant(sv, q):
    if not sv:
        return None
    h = (len(sv) - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, len(sv) - 1)
    return sv[lo] + (h - lo) * (sv[hi] - sv[lo])


def _summary(vals):
    sv = sorted(v for v in vals if v is not None)
    if not sv:
        return {}
    return {"n": len(sv), "p50": _quant(sv, 0.50), "p90": _quant(sv, 0.90),
            "p99": _quant(sv, 0.99), "min": sv[0], "max": sv[-1]}


def _count(it):
    c = {}
    for x in it:
        c[x] = c.get(x, 0) + 1
    return c

def _citations_for(ont, trace_id, action, cache):
    """Deterministic retrieval-result locators for a (trace, action) pair.

    Seeded the same way as `_tool_identity` so that a loop or a retry re-retrieves the *same*
    documents. If the copies cited different sources, `citation_reachability` would measure
    the RNG instead of the agent.
    """
    if action in cache:
        return cache[action]
    srcs = sorted(ont.get("kb_sources") or [])
    if not srcs:
        cache[action] = []
        return []
    r = random.Random("%s|cit|%s" % (trace_id, action))
    out = sorted(r.sample(srcs, min(len(srcs), r.randint(1, 3))))
    cache[action] = out
    return out


def _validator_id(ont, kind):
    for v in ont.get("validators") or []:
        if v.get("kind") == kind:
            return v.get("id")
    return None


def build(regime_id, out_root=None):
    spec = RG.get(regime_id)
    rng = random.Random(spec["seed"])
    ont = get_ontology(spec["ontology_id"])
    price = ont["unit_price"]
    kmap = ont["kind_map"]
    root_action = ont.get("root_action", "agent_run")
    patterns = sorted(ont["required_steps"])
    n_pat = min(spec["n_patterns_per_intent"], len(patterns))
    n_int = spec["n_intents"]
    mix = spec["mix"]
    assert len(mix) == n_int, "mix length must equal n_intents for %s" % regime_id
    emb_dim = int(spec.get("emb_dim", EMB_DIM))
    basis = _emb_basis(n_int, emb_dim,
                       random.Random("%s|emb_basis|%d" % (spec["id"], emb_dim)))
    sigma_e = spec["overlap"] * 0.70
    cont = float(spec.get("intent_ambiguity", EMB_CONTINUUM))
    int_w = [m[0] for m in mix]
    sp = spec["cell_sparsity"]
    pw_base = [(k + 1) ** (-1.0 - 3.0 * sp) for k in range(n_pat)]

    # Workflow entry actions = the declared first step of every required workflow. The kernel
    # must not hardcode "plan", so plan_revision_count is defined against this set.
    entry_actions = sorted({v[0] for v in ont["required_steps"].values() if v})
    forbidden = set(ont.get("forbidden_actions") or [])
    qlangs = ont.get("query_langs") or [("en", 1.0)]
    langs, lang_w = [x[0] for x in qlangs], [x[1] for x in qlangs]
    intents = ont.get("intents") or []
    windows = ont.get("time_windows") or ["15m"]
    schema = ont.get("param_schema") or {}
    ctx_win = ont.get("context_window") or {}
    sys_map = ont.get("system_prompt_tokens") or {}
    sys_default = sys_map.get("default", 160)
    frames = ont.get("out_frames") or ["{core}"]
    v_forbid = _validator_id(ont, "forbidden_actions")
    v_nums = _validator_id(ont, "number_traceable")
    v_nonempty = _validator_id(ont, "nonempty_answer")

    drift = spec.get("drift")
    n = spec["n"]
    hours = spec.get("hours", 72.0)
    step_s = hours * 3600.0 / max(1, n)
    labels_left = spec["label_count"]
    label_idx = set(rng.sample(range(n), min(labels_left, n))) if labels_left else set()
    sessions = _session_plan(spec["id"], n)

    traces, gts = [], []
    lat_all, tok_all, cost_all = [], [], []
    type_counts = dict((t, 0) for t in ANOMALY_TYPES)
    defect_counts = {"ts_repaired": 0, "usage_estimated": 0, "orphan_rebuilt": 0}
    v3_counts = {"plan_revision": 0, "goal_drift": 0, "contradiction": 0,
                 "fabricated_citation": 0, "arg_invalid_spans": 0, "verifier_fail": 0,
                 "cache_hit_spans": 0, "llm_spans": 0}
    lang_counts = {}

    for idx in range(n):
        intent_i = _weighted(rng, list(range(n_int)), int_w)
        pw = pw_base[intent_i % n_pat:] + pw_base[:intent_i % n_pat]
        pat_j = _weighted(rng, list(range(n_pat)), pw)
        pattern = patterns[pat_j]
        intent_id = "i%d" % intent_i
        cell_id = "%s|%s" % (intent_id, pattern)

        # v2 context, drawn from the independent stream so v1 draws stay bit-identical
        raux = _aux_rng(spec["id"], idx)
        r3 = _v3_rng(spec["id"], idx)
        remb = _emb_rng(spec["id"], idx, emb_dim)
        ne = _ne_id(raux)
        win = raux.choice(windows)
        models = ont.get("models") or [("default-model", 1.0, 1.0)]
        pvers = ont.get("prompt_versions") or [("pv-default", 1.0)]
        pver = _weighted(raux, [m[0] for m in pvers], [m[1] for m in pvers])
        act_text = ont.get("action_text") or {}

        # v3: language then wording. The goal phrase is substituted into every wording, so the
        # goal vocabulary is literally present in the query - without that, "how much of the
        # goal survived into step k" has no denominator.
        lang = _weighted(r3, langs, lang_w)
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        slot = intents[intent_i % len(intents)] if intents else None
        goal = slot["goal"][lang] if slot else intent_id
        query = (_fmt(r3.choice(slot["ask"][lang]), {"goal": goal, "ne": ne, "win": win})
                 if slot else None) or ("%s for %s" % (goal, ne))
        intent_phrase = query
        lf = (ont.get("lang_token_factor") or {}).get(lang, 1.0)
        trace_id = "%s-%05d" % (spec["id"], idx)
        sess_id, turn_index, turn_count = sessions[idx]
        tool_cache, cit_cache = {}, {}

        _, med, sig = mix[intent_i]
        z_l = rng.gauss(0.0, 1.0)
        lat = math.exp(math.log(med) + sig * z_l)
        drift_seg = None
        if drift and idx >= int(drift["at_frac"] * n):
            lat *= drift["magnitude"]
            drift_seg = 1
        elif drift:
            drift_seg = 0
        q_l = phi(z_l)

        z_u = rng.gauss(0.0, 1.0)
        tok_scale = math.exp(0.45 * z_u)
        q_u = phi(z_u)

        atype = _sample_anomaly(rng, spec["anomaly_rate"], spec["anomaly_mix"])

        steps = _plan_steps(ont, pattern, rng)
        t_start = T0 + idx * step_s + rng.uniform(-0.2 * step_s, 0.2 * step_s)
        want_rev = bool(entry_actions) and r3.random() < PLAN_REVISION_RATE

        # ---- child spans -------------------------------------------------
        kinds = [kmap.get(a, "tool") for a in steps]
        raw_w = [max(0.05, rng.gammavariate(2.0, 1.0)) * _kind_dur_weight(k)
                 for k in kinds]
        sw = sum(raw_w) or 1.0
        inner = max(0.05, lat * 0.92)
        gap = lat - inner
        spans = []
        pool = []
        citations = []
        cur = t_start + gap * 0.3
        respans = []
        # Emulating a parallel branch means emitting step k+1 *early*, not emitting it twice.
        # A for-loop cannot skip its own next iteration, so the previous zero-and-continue
        # version appended step k+1 a second time as a degenerate 4 ms span; that phantom
        # duplicate inflated n_spans and fed false signal into retry_count and loop_count.
        skipped = False
        for k, a in enumerate(steps):
            parallel = (k + 1 < len(steps)) and rng.random() < 0.22
            if skipped:
                skipped = False
                continue
            dur = max(0.004, inner * raw_w[k] / sw)
            kind = kinds[k]
            s0, s1 = cur, cur + dur
            if parallel:
                nxt = max(0.004, inner * raw_w[k + 1] / sw)
                half = dur * 0.5
                spans.append({"action": a, "kind": kind, "ts_start": s0,
                              "ts_end": s0 + half, "dur_share": dur / max(lat, 1e-9)})
                spans.append({"action": steps[k + 1], "kind": kinds[k + 1], "ts_start": s0,
                              "ts_end": s0 + half, "dur_share": nxt / max(lat, 1e-9)})
                cur = s0 + half + gap * 0.7 / max(1, len(steps))
                skipped = True
                continue
            spans.append({"action": a, "kind": kind, "ts_start": s0, "ts_end": s1,
                          "dur_share": dur / max(lat, 1e-9)})
            cur = s1 + gap * 0.7 / max(1, len(steps))
        # ---- anomaly injection -------------------------------------------
        proc = {"missing_step": False, "illegal_step": False, "unfinished": False}
        dim = {"O": 1.0, "P": 1.0, "L": 1.0 - 0.5 * q_l, "C": 1.0 - 0.5 * q_u, "R": 1.0}
        resp_ids = []
        idxs = list(range(len(spans)))

        if atype == "latency_spike" and spans:
            j = rng.randrange(len(spans))
            f = rng.uniform(5.0, 20.0)
            spans[j]["ts_end"] = spans[j]["ts_start"] + (spans[j]["ts_end"] - spans[j]["ts_start"]) * f
            respans.append(j)
            dim["L"] = 0.10
        elif atype == "token_bloat" and spans:
            cand = [k for k, s in enumerate(spans) if s["kind"] == "llm"] or idxs
            j = rng.choice(cand)
            spans[j]["tok_mul"] = rng.uniform(4.0, 10.0)
            respans.append(j)
            dim["C"] = 0.12
        elif atype == "loop" and len(spans) >= 3:
            j = rng.randrange(1, len(spans) - 1)
            rep = rng.randint(3, 5)
            base = spans[j]
            for r in range(rep):
                spans.insert(j + 1 + r, dict(base))
            respans = [j] + [j + 1 + r for r in range(rep)]
            dim["P"] = 0.50
            dim["R"] = 0.55
        elif atype == "error" and spans:
            j = rng.randrange(len(spans))
            spans[j]["status"] = "error"
            respans.append(j)
            if rng.random() < 0.40:
                # errored then recovered: a blemish, not an incident. The benchmark keeps
                # these as *normals* so that a naive "any error span is an anomaly" rule
                # is measured as the false-alarm machine it would be in production.
                rt = dict(spans[j])
                d0 = max(1e-4, spans[j]["ts_end"] - spans[j]["ts_start"])
                rt["status"] = "ok"
                rt["ts_start"] = spans[j]["ts_end"]
                rt["ts_end"] = spans[j]["ts_end"] + d0
                spans.insert(j + 1, rt)
                atype = None
                respans = []
                dim["R"] = 0.60
                dim["O"] = 0.95
            else:
                dim["R"] = 0.35
                dim["O"] = 0.75
        elif atype == "missing_step":
            req = ont["required_steps"][pattern]
            cand = [k for k, s in enumerate(spans)
                    if s["action"] in req and k != len(spans) - 1]
            if cand:
                j = rng.choice(cand)
                del spans[j]
                respans = []
                proc["missing_step"] = True
                dim["P"] = max(0.2, 1.0 - 0.6 / max(1, len(req)))
        elif atype == "illegal_step" and spans:
            fa = sorted(ont.get("forbidden_actions") or [])
            if fa:
                act = rng.choice(fa)
                j = rng.randrange(len(spans))
                s0 = spans[j]["ts_end"]
                spans.insert(j + 1, {"action": act, "kind": kmap.get(act, "tool"),
                                     "ts_start": s0, "ts_end": s0 + lat * 0.02,
                                     "dur_share": 0.02})
                respans = [j + 1]
                proc["illegal_step"] = True
                dim["P"] = 0.05
                if rng.random() < 0.5:
                    spans.insert(j + 2, {"action": (ont.get("optional_steps") or ["verify"])[0],
                                         "kind": "guard", "ts_start": s0, "ts_end": s0 + lat * 0.01,
                                         "dur_share": 0.01, "guard_block": True})
        elif atype == "unfinished" and len(spans) >= 2:
            drop = 1 if len(spans) < 3 else rng.randint(1, 2)
            respans = [len(spans) - 1]
            for _ in range(drop):
                if spans:
                    spans.pop()
            proc["unfinished"] = True
            dim["P"] = 0.20
            dim["O"] = 0.55
        elif atype == "truncation":
            dim["O"] = 0.35
        elif atype == "hallucinated_number":
            dim["O"] = 0.15

        # ---- v3: plan revision ------------------------------------------------
        # Nested inside the entry span rather than appended after it, and only when the next
        # sibling does not already overlap the entry span (a parallel branch starts at the same
        # ts_start, so an appended revision would sort *after* it and stop being adjacent).
        # Adjacency is the whole point: cluster.collapse folds immediate repeats away, so the
        # collapsed skeleton the pattern view clusters on is unchanged, while the raw span list
        # gains the second plan that plan_revision_count needs.
        plan_rev = 0
        if want_rev and len(spans) >= 2 and spans[0]["action"] in entry_actions \
                and spans[1]["ts_start"] >= spans[0]["ts_end"] - 1e-9:
            b = spans[0]
            d0 = max(1e-4, b["ts_end"] - b["ts_start"])
            rev = dict(b)
            rev["ts_start"] = b["ts_start"] + 0.55 * d0
            rev["ts_end"] = b["ts_start"] + 0.95 * d0
            rev["dur_share"] = b.get("dur_share", 0.05) * 0.40
            rev["plan_revision"] = True
            spans.insert(1, rev)
            respans = [j + 1 if j >= 1 else j for j in respans]
            plan_rev = 1

        # ---- v3: goal drift (co-defect only) ----------------------------------
        detours = _detours_for(ont, lang, goal) if atype else []
        want_drift = bool(detours) and atype in DRIFT_RATE_BY_TYPE \
            and r3.random() < DRIFT_RATE_BY_TYPE[atype]
        n_llm = sum(1 for s in spans if s["kind"] == "llm")
        drift_pos = r3.randrange(n_llm) if (want_drift and n_llm) else -1
        drift_text = r3.choice(detours) if want_drift else None

        # ---- materialize spans --------------------------------------------
        t_first = min(s["ts_start"] for s in spans) if spans else t_start
        t_last = max(s["ts_end"] for s in spans) if spans else t_start + lat
        out_spans = []
        real_lat = max(1e-6, t_last - t_first)
        p_bad = ARG_INVALID_BY_TYPE.get(atype, ARG_INVALID_BASE)
        llm_seen = 0
        llm_counter = 0
        for k, s in enumerate(spans):
            sid = "%s-s%02d" % (spec["id"] + "-" + str(idx).zfill(5), k + 1)
            kind = s["kind"]
            action = s["action"]
            tp, tc = _tokens(kind, s.get("dur_share", 0.1), rng)
            # tok_scale is the latent usage level of this trace; q_u = Phi(z_u) is the
            # generative quantile the oracle cost score is derived from, so the two must
            # actually drive the emitted token volume or the cost dimension is untestable.
            # `lf` is the language token factor: a pure nuisance axis the oracle deliberately
            # does not know about, because a Chinese request costing 15% more prompt tokens is
            # not a worse execution.
            mul = s.get("tok_mul", 1.0) * tok_scale
            tp = int(tp * mul * lf)
            tc = int(tc * mul)
            if kind in ("tool", "retrieval"):
                nums = [rng.randint(1000, 9999) for _ in range(rng.randint(2, 4))]
                pool.extend(str(x) for x in nums)
                facts = [str(x) for x in nums]
            else:
                nums = []
                facts = []
            if kind in ("tool", "retrieval"):
                tname, tparams = _tool_identity(ont, action, ne, win, trace_id, tool_cache,
                                                schema=schema, p_bad=p_bad)
                arg_valid = _validate_args(schema, action, tparams)[0] \
                    if tparams is not None else None
            else:
                tname, tparams, arg_valid = None, None, None
            if kind == "retrieval":
                ocit = _citations_for(ont, trace_id, action, cit_cache)
                citations.append(list(ocit))
            else:
                ocit = None
            s_dur = max(s["ts_end"], s["ts_start"] + 1e-4) - s["ts_start"]
            ctx = {"intent": intent_phrase, "goal": goal, "ne": ne, "win": win,
                   "tool": tname or "", "ver": pver,
                   "nums": " ".join(str(x) for x in nums) if nums else " ".join(pool[-6:])}
            t_in = (act_text.get(action) or {}).get("in") or [None]
            t_out = (act_text.get(action) or {}).get("out") or [None]
            status = s.get("status", "ok")
            if status == "error":
                level, smsg = "ERROR", raux.choice(ont.get("error_messages") or ["error"])
            elif raux.random() < 0.06:
                level, smsg = "WARNING", raux.choice(ont.get("warn_messages") or ["warning"])
            else:
                level, smsg = "DEFAULT", None
            if kind == "guard":
                # features.extract counts a guard hit by the substring "block"; keep it
                ctx["verdict"] = "block - policy violation" if s.get("guard_block") else "pass"
                out = _fmt(raux.choice(t_out), ctx) or ("guard verdict: %s for %s"
                                                        % (ctx["verdict"], ne))
            else:
                core = _fmt(raux.choice(t_out), ctx) or ("result of %s" % action)
                out = _fmt(raux.choice(frames), dict(ctx, core=core)) or core
            model = _weighted(raux, [m[0] for m in models], [m[1] for m in models]) \
                if kind in ("llm", "agent") else None
            if kind in ("llm", "agent"):
                sys_base = sys_map.get(model, sys_default)
                sys_tok = min(tp, max(0, int(sys_base * (0.90 + 0.20 * r3.random()))))
                hit_ok = (turn_index > 1) or (llm_seen > 0)
                hit = hit_ok and r3.random() >= CACHE_MISS_RATE
                cache_read = sys_tok if hit else 0
                cache_write = 0 if hit else sys_tok
                llm_seen += 1
            else:
                sys_tok, cache_read, cache_write = None, 0, 0
            cost, cost_details = _cost_and_details(kind, tp, tc, cache_read, cache_write, price)
            if kind == "llm":
                subgoal = (drift_text if llm_counter == drift_pos
                           else _subgoal(ont, lang, action, goal, ne, win, r3))
                llm_counter += 1
            else:
                subgoal = None
            sp = {"span_id": sid, "parent_id": None, "kind": kind, "action": action,
                  "ts_start": s["ts_start"], "ts_end": max(s["ts_end"], s["ts_start"] + 1e-4),
                  "tokens_prompt": tp, "tokens_completion": tc,
                  "tokens_system_prompt": sys_tok,
                  "tokens_cache_read": cache_read if kind in ("llm", "agent") else None,
                  "tokens_cache_write": cache_write if kind in ("llm", "agent") else None,
                  "cost": cost, "cost_details": cost_details,
                  "status": status, "finish_reason": None,
                  "input_text": _fmt(raux.choice(t_in), ctx) or ("context for %s" % action),
                  "output_text": out,
                  "model": model,
                  "ttft": round(s_dur * raux.uniform(0.03, 0.30), 6) if kind == "llm" else None,
                  "tool_name": tname, "tool_params": tparams, "arg_valid": arg_valid,
                  "prompt_version": pver if kind == "llm" else None,
                  "subgoal_text": subgoal,
                  "output_citations": ocit,
                  "verifier": None,
                  "output_facts": facts, "level": level, "status_message": smsg}
            if kind == "llm":
                sp["finish_reason"] = "stop"
                sp["_vslot"] = "answer"
                v3_counts["llm_spans"] += 1
                if cache_read:
                    v3_counts["cache_hit_spans"] += 1
            if kind == "guard":
                sp["_vslot"] = "process"
            out_spans.append(sp)
            if k in respans:
                resp_ids.append(sid)
        # Only the last llm span can vouch for the answer; the earlier ones have not seen it.
        _aslots = sorted((_x["ts_start"], _i) for _i, _x in enumerate(out_spans)
                         if _x.get("_vslot") == "answer")
        for _t, _i in _aslots[:-1]:
            out_spans[_i]["_vslot"] = None

        for sp in out_spans:
            sp["parent_id"] = "%s-s00" % (spec["id"] + "-" + str(idx).zfill(5))
        if len(out_spans) >= 4 and rng.random() < 0.25:
            cand = [sp for sp in out_spans if sp["kind"] == "tool"]
            if cand:
                child = rng.choice(cand)
                sub = dict(child)
                sub["span_id"] = child["span_id"] + "-n1"
                sub["parent_id"] = child["span_id"]
                sub["ts_start"] = child["ts_start"] + (child["ts_end"] - child["ts_start"]) * 0.2
                sub["ts_end"] = child["ts_start"] + (child["ts_end"] - child["ts_start"]) * 0.8
                sub["input_text"] = "nested %s call for %s" % (child["action"], ne)
                sub["ttft"] = None
                sub["_vslot"] = None
                out_spans.append(sub)
        # ---- answer / golden facts / citations / feedback --------------------
        numeric = rng.random() > 0.10
        ans_nums, golden_nums = [], []
        if numeric and pool:
            k_pick = min(len(pool), rng.randint(1, 3))
            picked = rng.sample(pool, k_pick)
            ans_nums = list(picked)
            golden_nums = list(picked)
            if atype == "hallucinated_number":
                fake = [str(rng.randint(20000, 99999)) for _ in range(2)]
                ans_nums = ans_nums + fake
            if atype == "truncation":
                ans_nums = ans_nums + [str(rng.randint(10, 99))]
        else:
            numeric = False
        # The golden set is what a *complete* answer should have cited. Cut-short and
        # step-skipping traces therefore lose recall even though every number they did cite
        # is traceable, which keeps "incomplete" separable from "unfaithful".
        if numeric and atype in ("truncation", "unfinished", "missing_step"):
            for _ in range(raux.randint(1, 2)):
                extra = str(raux.randint(1000, 9999))
                if extra not in golden_nums:
                    golden_nums.append(extra)
        a_ctx = {"intent": intent_phrase, "ne": ne, "win": win, "nums": ", ".join(ans_nums)}
        ans_tmpl = ont.get("answer_templates") or ["{intent} for {ne}: {nums}"]
        ans_empty = ont.get("answer_empty_templates") or ["completed '{intent}' on {ne}"]
        if numeric and ans_nums:
            ans = _fmt(raux.choice(ans_tmpl), a_ctx)
        else:
            ans = _fmt(raux.choice(ans_empty), a_ctx)
        answer_facts = ([ne] + ans_nums) if numeric else []
        # golden answers exist only for a curated subset, exactly as in production
        has_golden = bool(golden_nums) and raux.random() < spec.get("golden_rate", GOLDEN_RATE)
        golden_facts = ([ne] + golden_nums) if has_golden else None
        golden_answer = (_fmt(ont.get("golden_template") or "expected: {nums}",
                              {"intent": intent_phrase, "ne": ne, "win": win,
                               "nums": ", ".join(golden_nums)})
                         if has_golden else None)

        # v3: citations. The reachable set is what retrieval actually returned; a fabricated
        # citation is a plausible locator that is not in it. Co-defect only, see module header.
        retrieved = sorted({c for cs in citations for c in cs})
        if retrieved:
            ans_cit = sorted(r3.sample(retrieved, r3.randint(1, min(3, len(retrieved)))))
        else:
            ans_cit = []
        fabricated = []
        if atype in FABRICATED_CITATION_TYPES and r3.random() < FABRICATED_CITATION_RATE:
            srcs = ont.get("kb_sources") or []
            if srcs:
                fabricated = [_fabricate_citation(srcs, r3) for _ in range(r3.randint(1, 2))]
                v3_counts["fabricated_citation"] += 1
        answer_citations = sorted(set(ans_cit) | set(fabricated))

        # v3: contradiction. Sampled from numbers the evidence *does* contain, so this is
        # "the answer states a relation the evidence denies", not "the answer invented a
        # number" - the second failure is already hallucinated_number.
        contradicted = []
        if atype in CONTRADICTION_TYPES and ans_nums and r3.random() < CONTRADICTION_RATE:
            base = sorted(set(golden_nums) & set(ans_nums)) or sorted(set(ans_nums))
            contradicted = sorted(r3.sample(base, r3.randint(1, min(2, len(base)))))
            v3_counts["contradiction"] += 1

        latent_bad = atype is not None
        feedback = None
        if raux.random() < spec.get("feedback_rate", FEEDBACK_RATE):
            if latent_bad:
                thumbs = _weighted(raux, ["up", "none", "down"], [0.10, 0.35, 0.55])
                p_retry, p_abandon, p_takeover = 0.45, 0.30, 0.35
            else:
                thumbs = _weighted(raux, ["up", "none", "down"], [0.60, 0.35, 0.05])
                p_retry, p_abandon, p_takeover = 0.08, 0.04, 0.05
            feedback = {"thumbs": None if thumbs == "none" else (1 if thumbs == "up" else -1),
                        "retry": raux.random() < p_retry,
                        "abandoned": raux.random() < p_abandon,
                        "human_takeover": raux.random() < p_takeover}

        rid = "%s-s00" % (spec["id"] + "-" + str(idx).zfill(5))
        rt_p = max(40, int(300 * tok_scale * lf))
        rt_c = max(16, int(120 * tok_scale))
        r_model = _weighted(raux, [m[0] for m in models], [m[1] for m in models])
        r_sys = min(rt_p, max(0, int(sys_map.get(r_model, sys_default)
                                     * (0.90 + 0.20 * r3.random()))))
        r_hit = turn_index > 1 and r3.random() >= CACHE_MISS_RATE
        r_cr = r_sys if r_hit else 0
        r_cw = 0 if r_hit else r_sys
        r_cost, r_details = _cost_and_details("llm", rt_p, rt_c, r_cr, r_cw, price)
        root = {"span_id": rid, "parent_id": None, "kind": kmap.get(root_action, "agent"),
                "action": root_action, "ts_start": t_first - 0.001,
                "ts_end": t_last + 0.002, "tokens_prompt": rt_p,
                "tokens_completion": rt_c,
                "tokens_system_prompt": r_sys,
                "tokens_cache_read": r_cr, "tokens_cache_write": r_cw,
                "cost": r_cost, "cost_details": r_details,
                "status": "ok", "finish_reason": "length" if atype == "truncation" else "stop",
                "input_text": query,
                "output_text": ans,
                "model": r_model,
                "ttft": None, "tool_name": None, "tool_params": None, "arg_valid": None,
                "prompt_version": None, "subgoal_text": None, "output_citations": None,
                "verifier": None, "_vslot": "nonempty",
                "output_facts": list(ans_nums),
                "level": "DEFAULT", "status_message": None}
        all_spans = [root] + out_spans
        all_spans.sort(key=lambda s: (s["ts_start"], s["span_id"]))

        # ---- v3 verifier outcomes ---------------------------------------------
        # Computed from the record itself, never asserted: the process verifier fails exactly
        # when a forbidden action had already started before the gate ran, and the answer
        # verifier fails exactly when an answer number is not in the evidence pool. A verifier
        # field that could disagree with the data it sits on would be a second source of truth.
        traceable_all = (not ans_nums) or all(x in pool for x in ans_nums)
        for s in all_spans:
            slot = s.pop("_vslot", None)
            if slot == "process":
                bad = sorted({x["action"] for x in all_spans
                              if x["action"] in forbidden and x["ts_start"] <= s["ts_start"]})
                s["verifier"] = {"id": v_forbid, "passed": not bad,
                                 "detail": ("forbidden action before gate: %s" % ",".join(bad)
                                            if bad else None)}
            elif slot == "answer":
                s["verifier"] = {"id": v_nums, "passed": bool(traceable_all),
                                 "detail": None if traceable_all
                                 else "answer number absent from the evidence pool"}
            elif slot == "nonempty":
                ok = len(ans or "") >= 8
                s["verifier"] = {"id": v_nonempty, "passed": ok,
                                 "detail": None if ok else "answer shorter than min_chars"}
            if s["verifier"] and not s["verifier"]["passed"]:
                v3_counts["verifier_fail"] += 1

        # ---- telemetry corruption ------------------------------------------
        raw_flags = {"usage_estimated": False, "ts_missing": False, "orphan": False}
        if rng.random() < spec["defect_rate"]:
            mode = _weighted(rng, ["usage", "ts", "orphan", "multi"], [0.45, 0.25, 0.15, 0.15])
            kids = [s for s in all_spans if s["parent_id"] is not None] or all_spans
            if mode in ("usage", "multi"):
                for s in rng.sample(kids, min(len(kids), rng.randint(1, 3))):
                    if rng.random() < 0.5:
                        s["tokens_prompt"] = None
                    else:
                        s["cost"] = None
                raw_flags["usage_estimated"] = True
            if mode in ("ts", "multi") and kids:
                s = rng.choice(kids)
                s["ts_start"], s["ts_end"] = s["ts_end"], s["ts_start"]
                raw_flags["ts_missing"] = True
            if mode in ("orphan", "multi") and kids:
                s = rng.choice(kids)
                s["parent_id"] = "lost-parent-%d" % rng.randint(1, 999)
                raw_flags["orphan"] = True

        # v2 field loss, on the independent stream: it moves missing_field_ratio without
        # perturbing the usage/cost corruption above, so the cost dimension stays comparable.
        # `tool_params` is the identity key of the loop/retry detector, so losing it can both
        # destroy a real loop (two of four copies lose their params and no group of three
        # remains) and fabricate one (three unrelated same-action spans all lose theirs and
        # become parameter-identical). Neither is telemetry loss the benchmark should ask the
        # kernel to see through: a label has to be observable in the record it is applied to.
        # Measured on the 22,800-trace v3 dataset the destructive direction fired on exactly one
        # trace (R1-01338, labelled `loop` with loop_true False) and the fabricating direction on
        # none -- which is why the guard below is written symmetrically rather than as a loop
        # special case: the rare direction is rare only at this sample size.
        params_before = dict((id(x), x.get("tool_params")) for x in all_spans)
        groups_before = _param_groups(all_spans)
        field_loss = 0
        if raux.random() < spec["defect_rate"]:
            lossy = [x for x in all_spans if x.get("parent_id") is not None] or all_spans
            for x in raux.sample(lossy, min(len(lossy), raux.randint(1, 3))):
                for key in LOSSABLE.get(x["kind"], ()):
                    if x.get(key) is not None and raux.random() < 0.55:
                        x[key] = None
                        field_loss += 1
        if _param_groups(all_spans) != groups_before:
            for x in all_spans:
                if x.get("tool_params") is None and params_before[id(x)] is not None:
                    x["tool_params"] = params_before[id(x)]
                    field_loss -= 1
        raw_flags["field_loss"] = field_loss
        exp_total = sum(len(expected_fields(x["kind"])) for x in all_spans)
        mfr_true = (sum(1 for x in all_spans for k in expected_fields(x["kind"])
                        if x.get(k) is None) / float(exp_total)) if exp_total else 0.0
        tok_by_model = {}
        for x in all_spans:
            if x.get("model"):
                tok_by_model[x["model"]] = tok_by_model.get(x["model"], 0) \
                    + (x.get("tokens_prompt") or 0) + (x.get("tokens_completion") or 0)
        tok_sum = sum(tok_by_model.values()) or 1
        model_mix = dict((k, round(v / float(tok_sum), 4))
                         for k, v in sorted(tok_by_model.items()))
        loop_true = any(v >= 3 for v in _param_groups(all_spans).values())

        emb = _embed(basis, intent_i % len(basis["cents"]), sigma_e, cont, remb)
        trace = {"trace_id": trace_id,
                 "session_id": sess_id,
                 "ts_start": t_first,
                 "intent_text": "intent%d: %s" % (intent_i, query),
                 "goal_text": goal,
                 "query_lang": lang,
                 "embedding": [round(v, 5) for v in emb],
                 "ontology_id": spec["ontology_id"], "spans": all_spans,
                 "raw_flags": raw_flags,
                 "turn_index": turn_index,
                 "session_turn_count": turn_count,
                 "answer_facts": answer_facts, "answer_numbers": list(ans_nums),
                 "answer_citations": answer_citations,
                 "contradicted_facts": contradicted,
                 "golden_facts": golden_facts, "golden_answer": golden_answer,
                 "user_feedback": feedback}
        traces.append(trace)
        # ---- v3 truth, computed from the EMITTED record ------------------------
        # Computed after corruption and field loss on purpose. A truth that describes the
        # record the generator *intended* rather than the one it *emitted* is exactly how a
        # benchmark ends up asking the kernel to read a field that is not there.
        av = [x.get("arg_valid") for x in all_spans if x.get("arg_valid") is not None]
        vf = [x["verifier"]["passed"] for x in all_spans if x.get("verifier")]
        retr = {c for x in all_spans for c in (x.get("output_citations") or [])}
        cit_true = (round(len([c for c in set(answer_citations) if c in retr])
                          / float(len(set(answer_citations))), 6)
                    if answer_citations else None)
        sys_sum = sum(x.get("tokens_system_prompt") or 0 for x in all_spans)
        prompt_sum = sum(x.get("tokens_prompt") or 0 for x in all_spans)
        cr_sum = sum(x.get("tokens_cache_read") or 0 for x in all_spans)
        cw_sum = sum(x.get("tokens_cache_write") or 0 for x in all_spans)
        reconciled = all(abs(sum((x["cost_details"] or {}).values()) - x["cost"])
                         <= 1e-12 + 1e-9 * abs(x["cost"])
                         for x in all_spans
                         if x.get("cost_details") and x.get("cost") is not None)
        arg_valid_true = round(sum(1 for v in av if v) / float(len(av)), 6) if av else None
        verifier_pass_true = round(sum(1 for v in vf if v) / float(len(vf)), 6) if vf else None
        subgoal_spans = [x for x in all_spans if x.get("subgoal_text")]
        drift_present = bool(drift_text) and any(x.get("subgoal_text") == drift_text
                                                 for x in all_spans)
        v3_counts["arg_invalid_spans"] += sum(1 for v in av if not v)
        if plan_rev:
            v3_counts["plan_revision"] += 1
        if drift_present:
            v3_counts["goal_drift"] += 1

        is_anom = atype is not None
        if atype:
            type_counts[atype] = type_counts.get(atype, 0) + 1
        atypes = [atype] if atype else []
        dflags = {"ts_repaired": raw_flags["ts_missing"],
                  "usage_estimated": raw_flags["usage_estimated"],
                  "orphan_rebuilt": raw_flags["orphan"]}
        for k, v in dflags.items():
            if v:
                defect_counts[k] += 1
        gt = {"trace_id": trace["trace_id"], "intent_id": intent_id, "pattern_id": pattern,
              "cell_id": cell_id, "is_anomaly": is_anom, "anomaly_types": atypes,
              "dim_dev": dict((k, round(max(0.0, min(1.0, v)), 4)) for k, v in dim.items()),
              "responsible_span_ids": list(resp_ids),
              "process_flags": proc, "defect_flags": dflags,
              "drift_segment": drift_seg,
              "gen_quantiles": {"L": round(q_l, 4), "C": round(q_u, 4)},
              "latency_true": round(real_lat, 4),
              "human_label": None,
              # --- v2 truth for the dimensions those fields unlock ---------------
              "has_golden": has_golden,
              "key_fact_recall_true": (round(len(set(answer_facts) & set(golden_facts))
                                              / float(len(set(golden_facts))), 4)
                                       if golden_facts else None),
              "fact_precision_true": (round(len(set(answer_facts) & set(golden_facts))
                                            / float(len(set(answer_facts))), 4)
                                      if (golden_facts and answer_facts) else None),
              "hallucinated_facts": (sorted(set(answer_facts) - set(golden_facts))
                                     if golden_facts else []),
              "loop_true": loop_true,
              "mfr_true": round(mfr_true, 4),
              "model_mix_true": model_mix,
              "feedback_available": feedback is not None,
              # --- v3 truth ------------------------------------------------------
              "query_lang_true": lang,
              "plan_revision_true": plan_rev,
              "goal_drift_true": bool(drift_present),
              "subgoal_count": len(subgoal_spans),
              "arg_valid_true": arg_valid_true,
              "verifier_pass_true": verifier_pass_true,
              "citation_reachable_true": cit_true,
              "contradiction_true": (round(len(set(contradicted) & set(answer_facts))
                                           / float(len(set(answer_facts))), 6)
                                     if answer_facts else None),
              "contradicted_count": len(contradicted),
              "fabricated_citation_count": len(fabricated),
              "cache_read_true": cr_sum,
              "cache_write_true": cw_sum,
              "system_prompt_ratio_true": (round(sys_sum / float(prompt_sum), 6)
                                           if prompt_sum else None),
              "session_turn_count_true": turn_count,
              "cost_details_reconciled_true": bool(reconciled)}
        if idx in label_idx:
            gt["human_label"] = bool(is_anom) ^ (rng.random() < 0.05)
        gts.append(gt)
        lat_all.append(real_lat)
        tok_all.append(sum((s.get("tokens_prompt") or 0) + (s.get("tokens_completion") or 0)
                           for s in all_spans))
        cost_all.append(sum((s.get("cost") or 0.0) for s in all_spans))

    out_root = out_root or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "data", "bench_v1")
    d = os.path.join(out_root, spec["id"])
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(os.path.join(d, "traces.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(d, "gt.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for g in gts:
            f.write(json.dumps(g, ensure_ascii=False, sort_keys=True) + "\n")

    # The generator version is part of the hashed identity: two datasets produced from the
    # same regime spec by different generator code are different datasets, and spec_hash feeds
    # anchor_version, so leaving the version out would let an anchor set silently survive a
    # change in the data it was fitted on.
    spec_txt = json.dumps({"generator_version": GEN_VERSION,
                           "emb_dim": emb_dim,
                           "spec": {k: v for k, v in spec.items() if k != "gates"}},
                          sort_keys=True, ensure_ascii=False)
    meta = {
        "regime_id": spec["id"], "title": spec["title"], "generator_version": GEN_VERSION,
        "seed": spec["seed"], "spec": {k: v for k, v in spec.items() if k != "gates"},
        "spec_hash": hashlib.sha256(spec_txt.encode("utf-8")).hexdigest()[:16],
        "n_traces": len(traces),
        "n_spans": sum(len(t["spans"]) for t in traces),
        "n_cells_true": len(set(g["cell_id"] for g in gts)),
        "cell_sizes": dict(sorted(((k, v) for k, v in
                                   _count(g["cell_id"] for g in gts).items()), key=lambda kv: -kv[1])),
        "anomaly_rate_true": sum(1 for g in gts if g["is_anomaly"]) / float(len(gts)),
        "anomaly_type_counts": type_counts,
        "defect_counts": defect_counts,
        "labels": sum(1 for g in gts if g["human_label"] is not None),
        "golden_count": sum(1 for g in gts if g["has_golden"]),
        "feedback_count": sum(1 for g in gts if g["feedback_available"]),
        "loop_true_count": sum(1 for g in gts if g["loop_true"]),
        "field_loss_total": sum(t["raw_flags"].get("field_loss", 0) for t in traces),
        "mfr_true": _summary([g["mfr_true"] for g in gts]),
        "recall_true": _summary([g["key_fact_recall_true"] for g in gts
                                 if g["key_fact_recall_true"] is not None]),
        "latency": _summary(lat_all), "tokens": _summary(tok_all), "cost": _summary(cost_all),
        # --- v3 side of the dataset --------------------------------------------
        "emb_dim": emb_dim,
        "emb_geometry": {"sig_dims": EMB_SIG_DIMS, "arc_step": EMB_ARC_STEP,
                         "dominant": EMB_DOMINANT, "norm_sigma": EMB_NORM_SIGMA,
                         "topic_amp": EMB_TOPIC_AMP, "continuum": cont,
                         "bg_mu": EMB_BG_MU, "bg_sigma": EMB_BG_SIGMA,
                         "bg_scale": "exp(N(%s,%s))" % (EMB_BG_MU, EMB_BG_SIGMA),
                         "sigma_e": round(sigma_e, 6),
                         "participation_ratio": round(_participation(basis["scale"]), 2)},
        "lang_counts": dict(sorted(lang_counts.items())),
        "session_count": len(set(t["session_id"] for t in traces)),
        "session_turn_counts": _summary([t["session_turn_count"] for t in traces]),
        "query_variety": len(set(t["intent_text"].split(":", 1)[1].strip()
                                 for t in traces if ":" in t["intent_text"])),
        "goal_drift_count": sum(1 for g in gts if g["goal_drift_true"]),
        "plan_revision_count": sum(g["plan_revision_true"] for g in gts),
        "contradiction_count": sum(1 for g in gts if g["contradicted_count"]),
        "fabricated_citation_count": sum(1 for g in gts if g["fabricated_citation_count"]),
        "arg_valid_true": _summary([g["arg_valid_true"] for g in gts
                                    if g["arg_valid_true"] is not None]),
        "verifier_pass_true": _summary([g["verifier_pass_true"] for g in gts
                                        if g["verifier_pass_true"] is not None]),
        "citation_reachable_true": _summary([g["citation_reachable_true"] for g in gts
                                             if g["citation_reachable_true"] is not None]),
        "cost_details_reconciled": (sum(1 for g in gts if g["cost_details_reconciled_true"])
                                    == len(gts)),
        "v3_counts": v3_counts,
        "gates": spec["gates"],
    }
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regimes", default="R1")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    ids = [x.strip() for x in args.regimes.split(",") if x.strip()]
    for rid in ids:
        meta = build(rid, args.out)
        print("[gen] %s n=%d spans=%d cells=%d anom=%.3f labels=%d dim=%d hash=%s"
              % (rid, meta["n_traces"], meta["n_spans"], meta["n_cells_true"],
                 meta["anomaly_rate_true"], meta["labels"], meta["emb_dim"],
                 meta["spec_hash"]))


if __name__ == "__main__":
    main()