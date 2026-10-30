"""Regime specifications for the standard benchmark dataset (contracts/schemas.md 7-8).

A regime is a *distribution shape*, not a business. The point of the matrix is that the
kernel must clear the same gates on bimodal, trimodal, heavily overlapping, extremely
sparse, heavily corrupted, cold-start, drifting and foreign-ontology traffic without any
code change - only the pluggable ontology and the tunable whitelist in adapt/playbook.md
may differ between rows.
"""

ANOMALY_MIX_DEFAULT = {
    "latency_spike": 0.16, "token_bloat": 0.14, "loop": 0.10, "error": 0.12,
    "missing_step": 0.10, "illegal_step": 0.06, "hallucinated_number": 0.12,
    "truncation": 0.10, "unfinished": 0.10,
}

_MIX2 = [(0.70, 2.0, 0.35), (0.30, 60.0, 0.50)]
_MIX3 = [(0.50, 1.5, 0.30), (0.30, 15.0, 0.40), (0.20, 90.0, 0.45)]
_MIX2_OVERLAP = [(0.55, 6.0, 0.70), (0.45, 18.0, 0.70)]
_MIX4 = [(0.45, 2.0, 0.40), (0.30, 12.0, 0.45), (0.17, 45.0, 0.45), (0.08, 150.0, 0.50)]

REGIMES = {
    "R1": {
        "title": "bimodal main path",
        "n": 4000, "mix": _MIX2, "n_intents": 2, "n_patterns_per_intent": 3,
        "overlap": 0.25, "cell_sparsity": 0.0, "defect_rate": 0.05, "drift": None,
        "label_count": 500, "ontology_id": "ontA", "anomaly_rate": 0.08,
        "anomaly_mix": ANOMALY_MIX_DEFAULT, "seed": 101, "hours": 72.0,
        "gates": {"ari_intent": 0.70, "ari_pattern": 0.60, "f1": 0.70, "precision_at_50": 0.80,
                  "fpr": 0.05, "ece": 0.08, "zero_residual": 1e-6, "no_drift": True},
    },
    "R2": {
        "title": "trimodal",
        "n": 4000, "mix": _MIX3, "n_intents": 3, "n_patterns_per_intent": 3,
        "overlap": 0.30, "cell_sparsity": 0.2, "defect_rate": 0.05, "drift": None,
        "label_count": 500, "ontology_id": "ontA", "anomaly_rate": 0.08,
        "anomaly_mix": ANOMALY_MIX_DEFAULT, "seed": 102, "hours": 72.0,
        "gates": {"ari_intent": 0.65, "ari_pattern": 0.55, "f1": 0.65, "precision_at_50": 0.75,
                  "fpr": 0.06, "ece": 0.08, "zero_residual": 1e-6, "no_drift": True},
    },
    "R3": {
        "title": "heavy overlap + intent ambiguity",
        "n": 3000, "mix": _MIX2_OVERLAP, "n_intents": 2, "n_patterns_per_intent": 3,
        # Retuned in bench-gen-v3.1.0: overlap 0.88 -> 0.70 plus the new intent_ambiguity 0.50.
        # The regime's purpose is unchanged - the hardest intent boundary in the matrix, and the
        # only one carrying a novelty floor, because it is the regime that has to produce traffic
        # belonging to no task class the kernel can name. What changed is why v3.0.0 could not
        # get there.
        #
        # v3.0.0 measured ari_intent 0.2513 against a plug-in Bayes ceiling of 0.4824: 52%
        # attainment, where the gate asks for 90%. The cause was not the difficulty level but the
        # *kind* of difficulty. `overlap` inflates sigma_e, and sigma_e-driven hardness separates
        # the oracle from k-means instead of moving them together - measured on a flat,
        # exchangeable geometry (participation ratio ~300 of 384 dims), one kmeans_cent run at
        # the true k tracks the ceiling at 0.997 of it at overlap 0.88, 0.908 at 1.55 and 0.052
        # at 1.90. No geometry constant closes that gap, because the oracle projects onto the
        # true discriminant while k-means has to average noise over all 384 dims.
        #
        # `intent_ambiguity` pulls each trace part way toward the mean of the other intents, so
        # the clusters stay tight while a minority of traces genuinely belong to neither. That
        # moves the oracle and k-means together. Measured through the real cluster_views at
        # n=3000, seed 103 (ari on the assignable pool, ceiling = runner.oracle_ceilings):
        #     ambiguity  overlap   ari_intent  ceiling  attain   novelty   verdict
        #       0.55      0.30       0.6218    0.6208   1.002    0.0063   novelty under floor
        #       0.40      0.88       0.7959    0.8328   0.956    0.0540   ceiling too high
        #       0.45      0.88       0.7176    0.7457   0.962    0.1887   novelty near the cap
        #       0.50      0.70       0.6776    0.6929   0.978    0.0570   <- chosen
        #       0.55      0.55       0.5798    0.5819   0.996    0.0327   novelty 1.09x floor
        # 0.50 / 0.70 is picked for margin on both gates at once. Both ends of the table are
        # rejected for that reason - 0.55/0.55 leaves novelty 9% above its floor, and novelty is
        # a step function of the data rather than a smooth one, because cons = (a - b) / max(a, b)
        # resolves in eighths at R_RUNS = 8 (see kernel/cluster.py:34).
        #
        # THE TABLE ABOVE IS THE SWEEP, NOT THE SHIPPED RESULT, and the difference is large
        # enough that quoting the sweep would be misleading. The sweep ran with the classic
        # (k-biased) silhouette, which answered k = 2 on everything. The shipped pipeline uses the
        # k-neutral statistic; on this continuum its curve is nearly flat over k = 2..6
        # (0.0464 / 0.0439 / 0.0460 / 0.0453 / 0.0482, a 9% spread) while ARI falls
        # 0.5918 -> 0.1827, so the argmax lands on k = 6 against 2 true intents. Shipped,
        # measured on the full bagged pipeline:
        #     ari_intent 0.7512 vs ceiling 0.7521  -> 99.88% attainment, gate 0.55  (comfortable)
        #     novelty_rate 0.2867 on the [0.03, 0.30] band -> 4.4% headroom under the cap (tight)
        #     coverage 0.7133 -> 28.7% of R3 traffic gets no conditional baseline
        # So the ari margin came out far better than the sweep predicted and the novelty margin
        # far worse: 4.4% of headroom, not the 5.3x the sweep row implies. Both gates pass and the
        # numbers are deterministic, but R3 is the tightest regime in the matrix - any retune of
        # the embedding geometry, of R_RUNS, or of the model-order rule has to re-check it. Two
        # fixes for the over-split were measured and REJECTED (an ontology-derived cap, which is
        # inert because both ontologies declare 4 intents and a regime exercises only a subset;
        # and an absolute parsimony band, which pulls novelty below the 0.03 floor here and costs
        # R4 its correct k = 4). Evidence for both is in the silhouette docstring in
        # kernel/cluster.py.
        #
        # REJECTED, a bridge population. Ambiguity on its own leaves the novelty channel nearly
        # silent (0.0063 at ambiguity 0.55): a uniform pull moves every trace together, the
        # centroids move with them, and bagging never disagrees. Parking a thin population
        # exactly on the boundary (t = 0.5 +/- jitter) does fire it, but the rate is not
        # controllable - measured 0.0097 / 0.0200 / 0.3617 / 0.0230 / 0.0170 across bridge
        # 0.04-0.07 with jitter 0.010-0.020, and 0.0717 vs 0.0230 for two RNG streams of the
        # SAME parameters. The jitter also has to be stated in noise units rather than in t
        # units: along the discriminant the two centroids sit 34.9 noise stds apart, so the
        # first attempt's jitter of 0.06 parked "boundary" traces 2.1 stds inside one class,
        # where nothing flags them. A knob whose output moves 40x between identical runs cannot
        # hold a gate band, so the mechanism was removed and sigma_e supplies the instability.
        "overlap": 0.70, "intent_ambiguity": 0.50, "cell_sparsity": 0.0,
        "defect_rate": 0.06, "drift": None,
        "label_count": 300, "ontology_id": "ontA", "anomaly_rate": 0.10,
        "anomaly_mix": ANOMALY_MIX_DEFAULT, "seed": 103, "hours": 72.0,
        "gates": {"ari_intent": 0.55, "ari_pattern": 0.50, "f1": 0.60, "precision_at_50": 0.70,
                  "fpr": 0.08, "ece": 0.10, "zero_residual": 1e-6, "no_drift": True,
                  "novelty_min": 0.03, "novelty_max": 0.30},
    },
    "R4": {
        "title": "extremely sparse cells",
        "n": 1200, "mix": _MIX4, "n_intents": 4, "n_patterns_per_intent": 3,
        "overlap": 0.30, "cell_sparsity": 0.9, "defect_rate": 0.06, "drift": None,
        "label_count": 150, "ontology_id": "ontA", "anomaly_rate": 0.10,
        "anomaly_mix": ANOMALY_MIX_DEFAULT, "seed": 104, "hours": 48.0,
        "gates": {"ari_intent": 0.60, "ari_pattern": 0.50, "f1": 0.50, "precision_at_50": 0.60,
                  "fpr": 0.10, "ece": 0.12, "zero_residual": 1e-6, "fallback_min": 0.50,
                  "no_drift": True},
    },
    "R5": {
        "title": "heavily corrupted telemetry",
        "n": 3000, "mix": _MIX2, "n_intents": 2, "n_patterns_per_intent": 3,
        "overlap": 0.30, "cell_sparsity": 0.1, "defect_rate": 0.45, "drift": None,
        "label_count": 300, "ontology_id": "ontA", "anomaly_rate": 0.10,
        "anomaly_mix": ANOMALY_MIX_DEFAULT, "seed": 105, "hours": 72.0,
        "gates": {"ari_intent": 0.65, "ari_pattern": 0.55, "f1": 0.60, "precision_at_50": 0.70,
                  "fpr": 0.08, "ece": 0.10, "zero_residual": 1e-6, "conf_downgrade": 1.0,
                  "no_drift": True},
    },
    "R6": {
        "title": "cold start",
        "n": 600, "mix": _MIX2, "n_intents": 2, "n_patterns_per_intent": 3,
        "overlap": 0.30, "cell_sparsity": 0.0, "defect_rate": 0.06, "drift": None,
        "label_count": 0, "ontology_id": "ontA", "anomaly_rate": 0.10,
        "anomaly_mix": ANOMALY_MIX_DEFAULT, "seed": 106, "hours": 2.0,
        "gates": {"cold_start": True, "max_alerts": 0, "zero_residual": 1e-6},
    },
    "R7": {
        "title": "mid-stream drift x1.6",
        "n": 4000, "mix": _MIX2, "n_intents": 2, "n_patterns_per_intent": 3,
        "overlap": 0.30, "cell_sparsity": 0.0, "defect_rate": 0.06,
        "drift": {"magnitude": 1.6, "at_frac": 0.5},
        "label_count": 300, "ontology_id": "ontA", "anomaly_rate": 0.08,
        "anomaly_mix": ANOMALY_MIX_DEFAULT, "seed": 107, "hours": 72.0,
        "gates": {"ari_intent": 0.65, "ari_pattern": 0.55, "f1": 0.60, "precision_at_50": 0.70,
                  "fpr": 0.08, "ece": 0.10, "zero_residual": 1e-6,
                  "drift_detected": True, "drift_lag_frac_max": 0.10,
                  "drift_lag_frac_min": -0.05},
    },
    "R8": {
        "title": "foreign ontology",
        "n": 3000, "mix": _MIX3, "n_intents": 3, "n_patterns_per_intent": 3,
        "overlap": 0.30, "cell_sparsity": 0.2, "defect_rate": 0.06, "drift": None,
        "label_count": 300, "ontology_id": "ontB", "anomaly_rate": 0.08,
        "anomaly_mix": ANOMALY_MIX_DEFAULT, "seed": 108, "hours": 72.0,
        "gates": {"ari_intent": 0.65, "ari_pattern": 0.55, "f1": 0.65, "precision_at_50": 0.75,
                  "fpr": 0.06, "ece": 0.10, "zero_residual": 1e-6, "no_drift": True,
                  "no_hardcoded_actions": True},
    },
}

COLD_START_MIN_TRACES = 1000
# Operator-facing alert budget. The FDR-controlled triage set is an audit/review queue and is
# allowed to be larger; what reaches a human unsolicited is its top-k by a_raw at this rate.
ALERT_BUDGET_PER_DAY = 5
# The budgeted stream is the only thing that pages an operator, and each entry costs a bounded
# few minutes of a scarce human, so its precision is gated directly rather than inferred from
# the FDR of the much larger triage set.
OPS_STREAM_PRECISION_MIN = 0.80


def get(name):
    r = dict(REGIMES[name])
    r["id"] = name
    return r


def names():
    return sorted(REGIMES)