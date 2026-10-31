"""Explorable scoring: 5 dimensions x 4 anchors x hard gates x LMDI zero-residual attribution.

Shape of the score
    S = 100 * G * Q,   Q = exp( sum_d u_d w_d ln(s_d) / sum_d u_d w_d ),   s_d in [EPS, 1]
  s_d : each dimension is mapped from raw metrics through the *cell-conditional* 4-anchor
        piecewise ladder of kernel.baseline (ideal=1.0, good=0.8, warn=0.5, bad=0.0), so the
        same 90s latency scores 1.0 in a deep-analysis cell and 0.0 in a simple-query cell.
  G   : product of triggered hard-gate multipliers (guard block, forbidden action, broken
        result, unfinished, runaway loop, drift suspect, novelty). Gates are business
        vetoes, not statistics, so they multiply instead of subtract.
  u_d : per-dimension confidence. A cost estimated from missing usage tokens (flag
        usage_estimated) must not be allowed to convict a trace, so its vote is downweighted
        instead of being silently trusted.
  EPS : floor of 0.02 keeps the geometric mean defined and bounded when a dimension collapses.

Why geometric mean: it is a *conjunctive* aggregator - one collapsed dimension cannot be
compensated by excellence elsewhere, which is exactly the semantics an SRE wants.

Outcome dimension (slice2): channels are admitted by measured contamination
---------------------------------------------------------------------------------
slice1 scored O from a single v1 proxy, `0.70*traceable_number_ratio + 0.30*(1-error_ratio/
ERR_SAT)` times a truncation multiplier, with a missing ratio substituted by the constant 0.90.
Measured against the generator's own per-dimension truth `dim_dev["O"]` over all 22,800 traces of
bench_v1, that composite ranks *worse than every one of its own ingredients*: mean Spearman
+0.4394 (worst regime +0.2906) against +0.7248 for traceable_number_ratio alone, +0.6575 for
fact_precision, +0.5887 for verifier_pass_rate. Two defects, both structural rather than tuned:
the 0.90 constant tied every answer-without-numbers (13.4% of bench_v1, 32.7% of R8) at exactly
0.93, so a clean trace was indistinguishable from a fabricating one with ten numbers; and O had
no completeness channel at all, so the `unfinished` class (truth 0.55) scored 1.000.

Admission rule. A channel may charge O only if it stays put on every defect class whose outcome
truth is 1.0. Contamination is measured as the trace-weighted |mean(channel | class) -
mean(channel | normal)| summed over those five classes (illegal_step, latency_spike, loop,
missing_step, token_bloat):

    traceable_number_ratio  0.0     fact_precision       0.0     error_ratio  3.2
    verifier_pass_rate     24.5     citation_reachability 27.3    key_fact_recall 65.6

The three contaminated channels are reading defects that belong to another dimension --
key_fact_recall falls to 0.659 on missing_step (a P defect), verifier_pass_rate to 0.813 on
illegal_step (P), citation_reachability to 0.932 / 0.936 on missing_step / token_bloat (P / C).
Wiring them into O would book one defect against two dimensions, which is precisely what the
zero-residual attribution below promises not to do: an auditor asking "which dimension cost how
many points" would get the same defect counted twice. They remain emitted as features and remain
usable by detection; they simply do not vote in O.

`key_fact_recall` was the documented slice2 candidate and is rejected on measurement, not taste:
25.9% availability (it needs `golden_facts`), the highest contamination of the six, and
rank-redundant once the structural completeness channel is present -- mean Spearman is +0.9561
with it and +0.9561 without. `1 - struct.unfinished` says the same thing on 100% of traffic, and
detect.py only reaches 1.0 on *confirmed* non-completion (aborted, or a required step short).
[CORRECTED IN SLICE4] This paragraph used to say the 0.35 "ended on an unusual step" soft case
"is left to P where it is already graded". That was wrong and is measured wrong: grading it in P
put 343 traces at exactly s_p = 0.895, 316 of them with P truth 1.0, which is 96.6% of all of
P's false charges and cost 0.145 mean Spearman. O was right to binarise it; P now does the same.
See "Process dimension (slice4)" below. The
generator's `unfinished` pops trailing spans, so the last action is no longer the cell's dominant
terminal and detect reports 1.0 -- on 135 of the 173 such pool traces; the other 38 land on the
0.35 soft value, for a reason that is a detector boundary and not a scoring choice, given in the
slice4 deferral note. `missing_step` deletes an *interior* required step, the terminal survives
and detect reports 0.0. The discriminator is real, not fitted.

Selection. A 6x6 grid over (GROUND_SAT, completeness weight) was scored by mean Spearman against
`dim_dev["O"]` subject to zero class-order inversions, because Spearman over a whole regime is
blind to ordering *within* the small anomaly classes: each is under 1.1% of traffic, so moving
truncation below hallucinated_number costs nothing measurable while reversing what a triage queue
shows. Mean Spearman turned out to be a plateau (+0.9559..+0.9561) across the entire grid, i.e.
the grid is really choosing the ordering, and this cell has the widest margin. GROUND_SAT = 2.0
saturates the grounding channel at traceable_number_ratio = 0.5, exactly where TR_FLOOR hands over
to the t0_result_broken veto, so the graded channel and the hard gate meet with neither a gap nor
an overlap. The slice1 truncation multiplier is dropped: truncation is already that veto and
already depresses traceable_number_ratio (0.637 on the class), and multiplying on top is what
caused the inversion. sat_g 2.5 ties on margin but saturates at 0.4 and would overlap the veto
band; 1.5 and 1.25 stay inversion-free only at margins of +0.0312 and +0.0044.

Result. Offline over all 22,800 traces with an *oracle* completeness channel
(`gt.process_flags.unfinished`): mean Spearman vs dim_dev["O"] +0.4394 -> +0.9561, worst regime
+0.2906 -> +0.8898; class means hallucinated 0.550 < truncation 0.655 < unfinished 0.740 <
error 0.819 < normal 0.999 against truth 0.15 < 0.35 < 0.55 < 0.75 < 1.00, minimum adjacent
margin +0.0793, zero inversions. Shipped code substitutes detect.l4_contract's `struct.unfinished`
for that oracle and loses little: on R4 the realized `scoring.per_dim.O.spearman` is
0.5089 -> 0.9347. Realized per-regime figures belong in reports/<rid>/metrics.json, not here, so
that this comment need not be re-edited (and the code re-hashed) after every matrix run.

One deliberate trade, measured. R4 `scoring.score_auc` goes 0.8598 -> 0.8525. The slice1 constant
was accidentally discriminating: it charged 0.93 instead of 1.00 to every trace whose answer
carries no numbers (3046 of 22800 = 13.4% of bench_v1, 32.7% of R8), and that set is 1.42x
enriched in anomalies (11.2% vs 7.9%), concentrated in missing_step (3.4x baseline) and
unfinished (1.9x). So O was borrowing a little detection power from a defect it cannot name.
Dropping the constant returns it: mean_S_normal 89.93 -> 90.13, mean_S_anomaly flat at
51.13 -> 51.15. Everything that is supposed to improve does -- spearman_vs_oracle
0.7811 -> 0.7879, kendall_vs_oracle 0.5992 -> 0.6063, grade_separation 38.81 -> 38.98 -- and
per_dim for P/L/C/R plus every gate value stay bit-identical, because O is the only block touched.

Two more channels measured and rejected. `unfaithful_fact_count` is the cleanest channel in the
whole contract -- 100% available, contamination exactly 0.00, and on bench_v1 a perfect
truncation/hallucination discriminator (truncation only ever carries 1, hallucinated_number only
ever 2, all else 0) -- but it is nearly empty: 102 nonzero values in 22,800 traces (0.45%).
Wired in as 1 - min(1, count / FAITH_SAT) it moves mean Spearman by +0.00002 and *costs* the
binding margin, +0.0793 -> +0.0680 / +0.0634 / +0.0595 at weight 0.05 / 0.10 / 0.15 / 0.20,
because it reads 1.0 on unfinished and error and drags both up toward normal. Substituting it for
`fact_precision` is no better (+0.95611 either way). A channel that buys nothing on rank fidelity
while shrinking the margin the entire ordering rests on is a net loss; it stays a detection
feature and does not vote in O. `verifier_pass_rate` and `citation_reachability` fail earlier,
on contamination.

Process dimension (slice4): five exact-zero channels behind two attribution gates
---------------------------------------------------------------------------------
After slice3 the dimensions ranked, by realized mean Spearman against the generator's own
`dim_dev`, R +0.9987 > O +0.9332 > C +0.9201 > P +0.7859 > L +0.7359, so P was next. P's
pathology is *not* R's. The incumbent's class ordering was already correct -- zero inversions,
illegal 0.5220 < unfinished 0.6529 < loop 0.8156 < missing 0.9362 < ok 0.9984 against truth
0.05 < 0.20 < 0.50 < 0.80 < 1.00 -- so the damage is ties, false charges and misses, and the
selection criterion has to be different. P truth has five levels and is 1.0 on 20,919 of the
21,541 bound traces (96.9%), so again almost the whole coefficient is "can the 622 low-truth
traces be separated without touching the 20,919".

  level          truth   n     source in bench/generate.py
  illegal_step   0.05    120   a forbidden action inside the executed sequence
  unfinished     0.20    173   confirmed non-completion
  loop           0.50    170   a repeated action group
  missing_step   0.80    111   one of three declared required steps deleted
  missing_step   0.85     48   one of four deleted; truth = 1 - 0.6/len(required)
  everything else 1.00 20,919   normal + latency_spike + token_bloat + error + err_recov
                                + truncation + hallucinated_number

Three structural defects in the incumbent, in descending damage:

  1. The `unfinished == 0.35` soft branch, charged at weight 0.30. detect.l4_contract reports
     1.0 only on *confirmed* non-completion and 0.35 when the last action merely is not the
     cell's terminal. Grading that suspicion puts 343 traces at exactly s_p = 1 - 0.30*0.35 =
     0.895, and 316 of them have P truth 1.0: 295 normal, 15 latency_spike, 4
     hallucinated_number, 2 token_bloat. That is 96.6% of the incumbent's 327 false charges.
     (Those three numbers are over all 22,800 traces; the bound pool that every reported
     coefficient is computed on carries 316 / 289 / 300.)
     They are genuine rank errors, not harmless ties, because 0.895 sits *below* missing_step's
     realized 0.9362 -- an ordinary trace is queued behind a confirmed workflow violation.
  2. A coverage gap that scoring cannot close on its own. `missing = [a for a in required if a
     not in set(seq)]` means a deleted required action that also occurs elsewhere in the
     sequence is invisible, so `missing_frac > 0` fires on only 66.67% of missing_step (106 of
     159 on the bound pool). The remaining 53 (76 over all 22,800) are the incumbent's entire
     miss count, and no reweighting inside score.py can reach them.
  3. Constant-filling, the slice1 O defect again: `struct.get("missing_frac", 0.0) or 0.0`
     turned "no contract layer" into "nothing missing", i.e. full credit for missing data.

Admission rule, as in O and R: a channel may charge P only if it stays put on every defect
class whose P truth is 1.0 (latency_spike, token_bloat, error, err_recov, truncation,
hallucinated_number). Contamination is the trace-weighted |mean(ch | class) - mean(ch | normal)|
summed over those six, and `nz@ok` is the share of the 20,919 truth-1.0 traces where it is
nonzero at all:

    channel                     contam  nz@ok    verdict
    struct.missing_frac          0.000  0.00%    admitted, graded
    struct.illegal_actions       0.000  0.00%    admitted, binarised
    unfinished >= 1.0            0.000  0.05%    admitted, binarised, gated
    feats.loop_count / LOOP_SAT  0.000  0.00%    admitted
    feats.goal_drift_max         0.001  0.13%    admitted only behind the gate below
    struct.loop_rule             0.000  0.00%    rejected, rank-redundant with loop_count
    feats.loop_group_count       0.000  0.00%    rejected, see the over-fit note
    feats.path_convergence       0.000  0.00%    rejected, 13.3 on loop and nothing else
    feats.longest_repeated_subseq 0.000 0.03%    rejected, loop-redundant (3.99 on loop)
    unfinished raw (0/0.35/1)    0.000  1.43%    rejected, defect 1 above
    struct.dev                   0.024  3.90%    rejected, folds in err_dev/truncated/
                                                traceable_viol, i.e. R and O defects
    feats.plan_revision_count    0.000  6.05%    rejected, zero signal (solo Spearman +0.0006)
    feats.goal_drift_slope       0.000  0.13%    rejected, zero signal (+0.0184)
    feats.self_correction_count  -0.008   -      rejected, solo Spearman -0.0077
    tool_success_rate / tool_arg_valid_rate / effective_info_ratio / cost_per_step_of_progress
    / query_complexity / n_turns_in_session                     nz@ok 99-100%, rejected
    tool_repeat_rate 13.9% / warn_level_ratio 21.8% / missing_field_ratio 15.1% /
    reformulation_signal 14.1% / kind_ratio_guard 49% / error_level_ratio 1.08%   rejected
    max_width / depth / n_spans / branch_factor  contam .001-.003 but nz@ok 100%, rejected
    n_unique_tools 94.5% availability, subgoal_count solo Spearman -0.1429, rejected

THE ATTRIBUTION GATE, which is this slice's actual contribution. `goal_drift_max` is the only
admitted channel with broad coverage -- it fires on 55.8% of illegal_step, 40.3% of
missing_step, 38.2% of unfinished, 29.4% of loop and 0.00% of normal -- so it is the only thing
in scoring-only scope that can reach defect 2's missing 53. But it is not exact: it also fires
on 20.8% of the `error` class (26 traces), whose P truth is 1.0, which gives contamination
0.001 and fails admission. The admission rule as written would reject it, and with it the only
fix for the coverage gap.

The resolution is that those 26 traces are exactly the ones where *another dimension has
already claimed the same evidence*. Measured: low-P traces with `error_ratio > 0` number 0, so
gating `goal_drift_max` on `error_ratio == 0` costs nothing at all on the low-P side, while
removing precisely the 26 contaminating traces. Contamination goes 0.001 -> 0.000 exactly, the
channel becomes admissible under the locked rule, and rank fidelity *improves* rather than
merely qualifying: +0.9327 ungated -> +0.9520 error-gated at the shipped weights, false charges
37 -> 11. So the gate is not a waiver. It generalises the admission rule from "measured
contamination happens to be zero" to "structural non-overlap": a channel may vote on a dimension
only where no other dimension has already booked the same evidence, implemented as a conditional
drop-and-renormalise on a cross-dimension indicator.

The same trick clears the last 11 false charges, and they partition exactly. Of the 11 truth-1.0
traces where `unfinished >= 1.0` fires, 6 are `normal` with `error_ratio > 0` and no truncation
(error already charges O and R) and 5 are `truncation` with a `finish_reason == "length"` span
(truncation already fires the t0_result_broken veto). Gating `unfinished` on
`error_ratio > 0 or truncated > 0` removes all 11. Cost on the low-P side, measured directly:
**0 traces** -- no low-P trace carries an errored or truncated step. Both gates are free.

The two changes are separable and must not be conflated, so here is the whole ledger on the
bound pool -- 622 low-P traces and 20,919 truth-1.0 traces, where a "miss" is a low-P trace
scored exactly 1.0 and a "false charge" is a truth-1.0 trace scored below 1.0:

    variant                                        misses    false charges
    incumbent additive form                           53          300
    5 channels, soft 0.35 kept, no gate               29          326
    5 channels, soft 0.35 kept, gated                 29          289
    5 channels, hard unfinished only, no gate         49           37
    5 channels, hard unfinished + gates  (slice4)     49            0
    + slice5 detect-side `absent` fix    (SHIPPED)    29            0

Read the last two rows as a column: the attribution gate removes all 37 remaining false charges
and moves the miss count by exactly zero. Read the middle two as a row: dropping the soft branch
is what costs misses, +20, and it buys 252 fewer false charges. The soft branch touches 368 pool
traces of which 289 have truth 1.0; of the 79 genuinely low-P ones, 59 are still caught by
another channel once it is gone and only 20 are not, so its *marginal* precision as a P signal is
20/368 = 5.4% against a false-charge rate of 78.5%.

Result: all five channels are exactly zero on all 20,919 truth-1.0 traces, the ok group's mean
s_p is 1.000000 with a single distinct value over 20,919 traces, and P joins R as a dimension
whose clean-trace score is exact rather than approximate. The truncation half of the gate is
load-bearing for `unfinished` (5 of the 11) and *inert* for `goal_drift_max` (no drift-firing
trace is truncated: adding it there leaves every number bit-identical). One shared predicate is
kept for both because that is the mechanism being stated, and the inertness is recorded here
rather than papered over by two different predicates.

Selection. A 3,876-cell simplex at step 0.05 over the five weights, scored by mean Spearman
against `dim_dev["P"]` subject to zero class-order inversions. Mean Spearman is a plateau here
too, and a much flatter one than R's: all 736 zero-inversion cells land in +0.960992..+0.961134,
a range of 1.4e-4. The grid is therefore choosing the *ordering and the magnitudes*, not the rank
fidelity. Two facts forced an explicit, stated rule rather than a bare argmax:

  - Margin (the minimum adjacent group-mean gap) and Pearson disagree across the plateau. The
    max-margin cell (0.30/0.25/0.15/0.05/0.25, margin +0.0986) has mean Pearson +0.8999, which
    is *below the incumbent's* +0.9343, because it gives `missing_frac` -- the direct, exact,
    truth-shaped channel -- the smallest weight of the five and gives the indirect binary drift
    proxy twice as much. Pearson spans +0.686..+0.955 over the same plateau, so this is a real
    trade, not noise.
  - Magnitude is not cosmetic downstream. s_p enters S through a geometric mean and S is read
    against the locked absolute grade bands A90/B75/C60, so a dimension that is systematically
    too lenient moves grade_abs, not just a correlation.

Rule as shipped: among zero-inversion cells with every weight >= 0.10 (no knife-edge channel)
and margin >= the incumbent's +0.0622, take those within 1e-3 of the best mean Pearson, then
maximise margin. 22 cells are eligible; the Pearson band leaves exactly two, (0.35/0.25/0.15/
0.15/0.10) at +0.94640 / margin +0.0643 and (0.30/0.20/0.15/0.25/0.10) at +0.94628 / margin
+0.0803. The Pearson gap between them is 1.2e-4, i.e. noise, while the margin gap is 25%, so
margin decides: **W_P_ILL 0.30, W_P_UNF 0.20, W_P_LOOP 0.15, W_P_MISS 0.25, W_P_DRIFT 0.10**.
The ordering is also the semantically defensible one -- a forbidden action costs most, then the
fraction of the declared workflow that was skipped, then confirmed non-completion, then looping,
then the indirect drift proxy.

Result, offline over the 21,541 bound traces, harness reproduced against the shipped
`reports/<rid>/metrics.json` to the last digit on all 8 regimes for both coefficients:

    mean Spearman   +0.785920 -> +0.961115    worst regime +0.687707 -> +0.903748   (8/8 up)
    mean Pearson    +0.934334 -> +0.946277    worst regime +0.893057 -> +0.891651  (-0.0014)
    min adj margin  +0.062165 -> +0.080300    inversions 0 -> 0
    false charges on truth-1.0 traces  300 -> 0        misses  53 -> 49 (all missing_step)
    group means  illegal 0.6442 < unfinished 0.7480 < loop 0.8365 < missing 0.9197 < ok 1.0000

Worst-regime Pearson is the one number that does not improve, by 0.0014 on R3; no cell in the
plateau reaches the incumbent's worst-regime Pearson at all (best available +0.8917 against
+0.8931), so this is recorded as the deliberate cost of removing 300 false charges, in the same
style as slice2's `score_auc` trade.

Every channel is load-bearing, measured two ways. At the shipped weights, dropping one and
renormalising the rest *inverts the class order* for three of the five: dropping `illegal`
scores illegal_step 0.9202 above unfinished 0.6390 (margin -0.2813, Spearman +0.9070), dropping
`unfinished` scores unfinished 0.8815 above loop 0.7956 (-0.0859, +0.9610), dropping `loop`
scores loop 0.9654 above everything (+0.8630, misses 49 -> 169). Dropping `missing_frac` keeps
the order but misses go 49 -> 120 (+0.9065) and dropping `goal_drift_max` takes them 49 -> 80
(+0.9322), which is the coverage-gap number from defect 2. Re-searched instead of held fixed,
`drop loop` has *no* zero-inversion cell at all out of 969, `drop illegal` has 4 and `drop
missing_frac` 225, so the conclusion does not depend on the operating point.

Variants rejected on measurement, at the shipped weights:
  - `missing_frac` binarised instead of graded: mean Spearman is indistinguishable (+0.961032
    against +0.961115) but it produces **two** class-order inversions (unfinished 0.5922 below
    illegal 0.6442, missing 0.7922 below loop 0.8365) and mean Pearson falls to +0.8999. Graded
    is also the only defensible semantics for a business -- the deduction should be proportional
    to the fraction of the declared workflow that was skipped -- and it matches the generator's
    own truth shape, 1 - 0.6/len(required).
  - keeping the 0.35 soft branch: +0.816144 mean Spearman, 289 false charges. Decisive.
  - `loop <- struct.loop_rule`: +0.960480, margin +0.0609 against +0.0803. Worse on both.
  - `loop <- feats.loop_group_count`: +0.961117 and Pearson +0.948250, both nominally better.
    Rejected anyway, on two grounds. It is bit-identical to the generator's own `orc_loop_true`
    on 21,541 of 21,541 traces, so any advantage is a benchmark artifact rather than a property
    of the feature; and it is not in the v1-frozen `METRICS`, so wiring it would widen the
    contract for a gain that will not exist on real traffic. `loop_count` is already there.
  - `DRIFT_FLOOR` and any `DRIFT_SAT` are both inert on bench_v1: `goal_drift_max` takes 273
    nonzero values and every one is exactly 1.0. The floor is kept and documented because a
    business whose drift is a continuous cosine distance would otherwise charge P for numerical
    noise; no saturation divisor is added because the feature is already a maximum.

Resolved in slice5, by two changes that only work as one. The 343 soft-branch traces were
charged *twice*, and the second charge dwarfed the first: `if unfinished > 0` fired the
categorical `t1_unfinished` veto at 0.25, so all of them landed in grade D with median S 22.93
against a dataset median of 91.79, and 313 carried no other gate at all. detect.l4_contract's own
`hard` predicate uses `unfinished >= 1.0`, so the gate trigger was plainly inconsistent with the
detector's definition of a categorical breach -- a graded suspicion fed into an all-or-nothing veto.

Narrowing the trigger on its own was implemented and run on R4 during slice4. It is a net loss and
was reverted: `t1_unfinished` 37 -> 10 hits, 15 normal traces lifted of which 12 correctly leave
grade D (mean S 21.53 -> 86.12), but `score_auc` 0.85693 -> 0.83700, `grade_separation`
39.188 -> 35.969 and `mean_S_anomaly` 51.215 -> 55.357, bought against only +0.0096 / +0.0072 on
the two oracle rank correlations. `per_dim` and every detection leaf are bit-identical either way,
so the loss was real rather than a measurement artifact.

Why it lost is what made slice5: the veto was accidentally compensating for a detector gap.
`l4_contract` reached `unfinished = 1.0` only when the trace aborted/errored or came up short
against the *required set*, while `term` is *learned* per cell by `baseline._profile` as the
dominant final action. When that learned terminal is not itself a member of `required` -- and an
`optional_steps` entry such as `verify` / `api_call` / `peer_review` can be exactly that -- a
popped terminal leaves every required step present, so detect could only report 0.35 and nothing
downstream could tell it apart from an ordinary unusual ending. Narrowing the veto without closing
that gap just let the genuine non-completions escape along with the suspicions. Two of R4's 11
`unfinished` traces were in exactly that state and they were two of the four wrong promotions
(S 24.56 -> 98.22, D -> A; the other two a token_bloat and a latency_spike).

So slice5 lands the detector fix first and the gate narrowing with it, in one commit.
detect.l4_contract now escalates on a third predicate, `absent = term not in present`: a cell only
earns a learned terminal at >= TERMINAL_PREVALENCE support, so a terminal appearing *nowhere* in
the sequence is confirmed non-completion and belongs with `aborted` and `short`, while an
attested-but-unusual ending stays graded. Measured over all 22,800 bench_v1 traces, `absent`
escalates exactly 38, and those 38 are exactly the 38 `unfinished`-class traces sitting at 0.35 --
intersection 38/38, flip-only 0, unf-only 0, zero false positives -- all carrying truth dimP=0.20
and dimO=0.55 while the slice4 scorer was giving them dims.P mean 0.9484 (max 1.0000) and dims.O
exactly 1.0000. The 361 that stay at 0.35 have absent=False without exception (295 normal,
35 illegal_step, 15 latency_spike, 10 loop, 4 hallucinated_number, 2 token_bloat). The rejected
alternative is measured in detect.py: escalating on *zero terminal support* instead -- the observed
final action never terminating any baseline trace in the cell -- is a different signal and does not
work, because "attested but unusual ending" and "closing step never performed" are different
questions and only the second is a breach.

Both halves then pay, on different surfaces:

  detection  `unfinished >= 1.0` fires on 146 -> 184 pool traces while its truth-1.0 firing count
             stays at exactly 11 (6 `normal` with error_ratio > 0, 5 `truncation`), so the
             attribution-gate ledger above is unchanged and still removes 11 -> 0. Of the 38, 27
             were not otherwise hard, so the alert stream gains 27 alerts of which 27/27 are true
             anomalies: pool F1 0.7184 -> 0.7296, precision 0.8631 -> 0.8635, recall
             0.6170 -> 0.6327, FPR unchanged at 0.000768, auc_a_raw 0.9319 -> 0.9396, pr_auc
             0.8394 -> 0.8524, and no regime moves down (R3 F1 0.7962 -> 0.8333, R5
             0.7556 -> 0.7802, R7 0.8226 -> 0.8340, R4 0.7867 -> 0.8026, R1/R2/R6/R8 unchanged).
  scoring    P misses 49 -> 29 at false charges still exactly 0, and O misses 102 -> 64, also at
             0 false charges. The 20 recovered P misses are precisely the ones slice4's
             de-contamination had to leave behind; the 38 recovered O misses are the whole
             `unfinished` class. per_dim.P.spearman +0.961115 -> +0.977482 (worst regime
             +0.903748 -> +0.945051), per_dim.P.pearson +0.946277 -> +0.975907,
             per_dim.O.spearman +0.933179 -> +0.956381, per_dim.O.pearson +0.874728 -> +0.887000.
             L, C and R are bit-identical, and so is mean_S_normal under the detector fix alone.

The gate narrowing is what turns that into a rank gain rather than only a magnitude gain:
`t1_unfinished` 578 -> 217 hits, grade_abs A 13,685 -> 13,911 and D 2,729 -> 2,435, and against
the oracle spearman_vs_oracle +0.798645 -> +0.813194, kendall_vs_oracle +0.615147 -> +0.625498,
score_auc 0.875834 -> 0.878849 -- those three measured A -> B, i.e. with the detector fix already
in on both sides, so they are the gate's own contribution. 269 normal traces whose *only* gate was
`t1_unfinished` stop being vetoed to grade D on a signal whose precision for the `unfinished` class
was 38/399 = 9.5%.

The cost is stated rather than hidden: `grade_separation` 39.904704 -> 39.359789 and
`mean_S_anomaly` 50.224994 -> 51.627154, because 21 non-normal traces (14 latency_spike, 4 loop,
2 token_bloat, 1 hallucinated_number) also stop carrying a veto that never described them. They
stay charged where they actually belong -- L and C for the latency and token classes, their own
`loop_runaway` / `t0_result_broken` gates for the rest -- and all three rank statistics move the
other way, which is the reading that matters: `grade_separation` is a difference of two means and
is dominated by tails, while score_auc and the two oracle correlations are rank statistics. A veto
asserting "the task did not finish" firing on a trace that finished and was merely slow is a
category error, and this is the slice that stops charging it.

Deliberately not re-run: the five-channel weight search of the section above. `x_unf` now fires on
184 pool traces instead of 146, so the plateau could in principle have moved, and it was left
alone on purpose -- re-tuning in the same commit as a root-cause fix would make the two
unattributable. That the shipped (0.30, 0.20, 0.15, 0.25, 0.10) improves P's rank fidelity from
+0.961115 to +0.977482 with no re-tuning at all is itself the robustness evidence.

Robustness dimension (slice3): three exact-zero channels replace two proxies
----------------------------------------------------------------------------
slice2 left R the worst dimension by a wide margin. Realized mean Spearman against the
generator's own `dim_dev["R"]` was +0.3260 (worst regime +0.2665), while R's best single
ingredient, `error_ratio`, reaches +0.7504 alone -- the composite ranked below its own parts,
the same pathology slice2 removed from O. Three structural defects, in descending damage:

  1. `retry_count` (weight 0.30, anchored, constant-filled to 1.0 when no anchor exists).
     Retrying is ordinary traffic, not a robustness defect: it is nonzero on 16% of *clean*
     traces, mean 0.1714 there against 0.2045 / 1.1404 / 0.9908 on the error / loop /
     error-recovered classes. That is an effect size of d = 1.596 of spread *inside* the group
     carrying 98.2% of the traffic whose R truth is a flat 1.0, i.e. pure dilution.
  2. `guard_hits` (weight 0.30). Contaminated, trace-weighted deviation 0.28 against the defect
     classes whose R truth is 1.0, worst `illegal_step` at 64.0, because the generator inserts a
     `guard_block` span for that class. It also double-booked the `guard_violation` veto below,
     so a single guard hit was charged twice in one score.
  3. Constant-filling a missing channel -- exactly the slice1 O defect, still present here.

R truth has four levels and is 1.0 on 22,381 of 22,800 traces (98.2%), so R's Spearman is almost
entirely "can the 419 low-truth traces be separated cleanly". Any channel that varies inside the
ok group is noise by construction, which makes *exactness* the selection criterion rather than
effect size.

Admission rule, as in O: a channel may charge R only if it stays put on every defect class whose
R truth is 1.0 (illegal_step, latency_spike, missing_step, token_bloat, truncation,
hallucinated_number, unfinished). Contamination is the trace-weighted |mean(ch | class) -
mean(ch | normal)| summed over those seven:

    error_ratio 0.00   unrecovered_errors 0.00   loop_rule 0.00   self_correction_count 0.00
    retry_count 0.34   guard_hits 0.28   n_guard 0.57   n_spans 3.44

`error_ratio`, `len(unrecovered_errors)` and `loop_rule` are not merely low-contamination, they
are *exactly zero* on all 22,381 ok traces (nonzero count 0). A clean trace therefore gets
s_r = 1.0 exactly and adds nothing to within-group tie noise. Four more channels pass admission
but are rank-redundant with these three and were dropped: `self_correction_count` (0.9817 on
error-recovered, 0 elsewhere), `loop_run_max` / `loop_count` (3.13 / 3.01 on loop, 0 elsewhere),
`path_convergence` (66% nonzero on loop). `warn_level_ratio`, `plan_revision_count`,
`kind_ratio_guard` and `guard_time_ratio` carry no signal at all (effect size <= 0.27, solo
Spearman ~ 0).

Selection: a 153-cell simplex at step 0.05 over the three weights, scored by mean Spearman
against `dim_dev["R"]` subject to zero class-order inversions, then by widest minimum adjacent
margin. Mean Spearman is a plateau here too (range 6e-5 over all 153 cells), so the grid selects
the *ordering*, not the rank fidelity. Chosen 0.20 / 0.50 / 0.30.

Result, offline over all 22,800 traces: mean Spearman +0.3260 -> +0.9987, worst regime +0.2665 ->
+0.9896, zero inversions, minimum adjacent margin +0.1121. Class means error 0.6154 < loop
0.7750 < error-recovered 0.8879 < ok 1.0000 against truth 0.35 < 0.55 < 0.60 < 1.00.

Recovery needs no term of its own. The generator writes R truth 0.60 for an error that was
recovered and 0.35 for one that was not, and the two error channels already diverge exactly
there: `error_ratio` counts the errored step either way, `unrecovered_errors` only counts what
survived. Recovery is therefore encoded as the *gap* between x_fail and x_unrec, which is
detect.l4_contract's own semantics ("a recovered error is a blemish, not an incident"). Adding
`self_correction_count` -- the obvious explicit recovery term -- was measured both ways and
rejected both ways: as a fourth penalty it inverts error-recovered below loop (0.6915 vs 0.8125,
margin -0.1210); as a credit it leaves mean Spearman at +0.998693, identical to five decimals,
while shrinking the margin the whole ordering rests on, +0.1121 -> +0.0793.

Every admitted channel is load-bearing. Dropping `unrecovered_errors` inverts error above loop
(0.7347 vs 0.5500); dropping `loop_rule` scores the loop class 1.0000 and falls to +0.7504;
`unrecovered_errors` alone gives +0.5719 with two inversions. The rejected additions are
quantitatively catastrophic rather than merely unhelpful: `retry_count` at weight 0.25 drags mean
Spearman to +0.3506, `guard_hits` at 0.25 to +0.9107, and the slice2 form reproduces offline at
+0.3274 against the +0.3260 it realized, so the harness is faithful.

Two deliberate non-changes. `ERR_SAT` is *shared* with O instead of getting its own `ERR_SAT_R`:
a separate 0.25 reaches margin +0.1231, but mean Spearman is identical to five decimals
(+0.998691 vs +0.998693, the shared value marginally higher) and the zero-inversion feasible
region is narrower, 42 of 153 cells against 47. One physical quantity -- the fraction of steps
that errored -- gets one saturation point; two knobs would silently couple O and R in the adapt
playbook. And `error_ratio` voting in both O and R does not break zero-residual attribution,
because the *generator* double-books it: the error-injection branch sets `dim["O"]` and
`dim["R"]` for the same injected error. The admission rule forbids a channel whose target
dimension's truth does not move; `error_ratio` has contamination 0.00 against both O's and R's
truth-1.0 class sets, so it is admissible in both.

L was measured and left alone; see the slice3 note in README for the oracle ceiling table.

Zero-residual attribution (LMDI)
    S_base = 100*G            L = (S - S_base) / (ln S - ln S_base)
    contrib_d = L * (u_d w_d / sum u w) * ln(s_d)
    => sum_d contrib_d == S - S_base   exactly (logarithmic-mean identity, no residual).
  Gate losses are reported separately in `gates` rather than being smeared across
  dimensions, so the audit trail answers "which dimension cost how many points" and
  "which veto cost how many points" without a leftover bucket.
"""
import math

from kernel import baseline as bl

EPS = 0.02
WEIGHTS = {"O": 0.40, "P": 0.20, "L": 0.15, "C": 0.15, "R": 0.10}
GATES = {"guard_violation": 0.15, "t0_result_broken": 0.25, "t1_unfinished": 0.25,
         "forbidden_action": 0.30, "loop_runaway": 0.35, "drift_suspect": 0.50,
         "t2_untraceable_number": 0.60, "novelty": 0.80}
GRADE_ABS = (("A", 90.0), ("B", 75.0), ("C", 60.0))
ERR_SAT = 0.30
LOOP_SAT = 3.0
TR_FLOOR = 0.5
# Saturating gain on the *untraceable* fraction of the answer's numbers. 2.0 exhausts the
# grounding channel at traceable_number_ratio = 0.5, which is TR_FLOOR: below that the
# t0_result_broken veto governs, so the graded channel and the hard gate meet exactly.
GROUND_SAT = 2.0
# Outcome channels. Absent channels are dropped and these renormalised -- never replaced by a
# constant, which is the defect that cost slice1 half its rank fidelity. See the docstring.
W_O_NUM = 0.70      # traceable_number_ratio, saturated by GROUND_SAT   contamination 0.0
W_O_PREC = 0.15     # fact_precision (needs golden_facts, 25.9% of traffic)  contamination 0.0
W_O_EXEC = 0.30     # 1 - error_ratio / ERR_SAT                            contamination 3.2
W_O_COMP = 0.25     # structural completeness, 1 - confirmed unfinished
# Saturating gain on the count of errored steps the agent never retried successfully. LOCKED at
# 2.0 because it mirrors detect.l4_contract's own err_dev = min(1.0, len(unrecovered) / 2.0);
# diverging here would decouple the scorer from the detector's definition of the same quantity.
UNREC_SAT = 2.0
# Robustness channels, same drop-and-renormalise rule as O. `retry_count` and `guard_hits` were
# dropped in slice3 on measurement and GUARD_SAT was deleted with them: see the docstring.
W_R_FAIL = 0.20     # 1 - error_ratio / ERR_SAT (shared with O)             contamination 0.00
W_R_UNREC = 0.50    # 1 - len(unrecovered_errors) / UNREC_SAT               contamination 0.00
W_R_LOOP = 0.30     # 1 - loop_rule                                         contamination 0.00
# Process channels (slice4), same drop-and-renormalise rule as O and R. `unfinished` and
# `goal_drift_max` additionally sit behind the attribution gate: they are dropped, and the rest
# renormalised, on any trace whose errored or truncated step another dimension already charges.
W_P_ILL = 0.30      # a forbidden action in the executed sequence           contamination 0.00
W_P_UNF = 0.20      # detect's *confirmed* non-completion only (>= 1.0)     contamination 0.00
W_P_LOOP = 0.15     # 1 - loop_count / LOOP_SAT                             contamination 0.00
W_P_MISS = 0.25     # 1 - missing_frac, graded -- binary inverts twice      contamination 0.00
W_P_DRIFT = 0.10    # goal_drift_max > DRIFT_FLOOR, gated                   contamination 0.00
# Binarisation floor for goal_drift_max, not a saturation divisor: the feature is already a
# maximum, so there is nothing to saturate and no DRIFT_SAT exists. INERT on bench_v1, where the
# feature takes 273 nonzero values and every one is exactly 1.0, so any floor in (0, 1) selects
# the same traces. It is named and tunable because a business whose drift is a continuous cosine
# distance would otherwise charge P for numerical noise.
DRIFT_FLOOR = 0.50
MODEL_VERSION = "kernel-v0.5.0"


def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _anch(art, cell, metric, x):
    if x is None:
        return None, None
    ent = art["cell"].get(cell) if cell else None
    a = (ent or {}).get("anchors", {}).get(metric)
    if a is None:
        g = art["global"].get(metric, {})
        med = g.get("median")
        if med is None:
            return None, None
        a = {"ideal": med, "good": med, "warn": med, "bad": med}
    return bl.anchor_score(a, x, bl.DIRECTION[metric]), a


def _truncated(feats):
    for s in feats.get("spans") or []:
        if s.get("finish_reason") == "length":
            return True
    return False


def score_one(feats, assign, det, art, ontology, cold_start=False, drift_suspect=False,
              anchor_version="anchor-v1", model_version=MODEL_VERSION):
    cell = assign.get("cell")
    nov = bool(assign.get("novelty"))
    struct = (det or {}).get("struct") or {}
    flags = feats.get("flags") or {}
    mfr = feats.get("missing_field_ratio", 0.0) or 0.0

    u = {"O": 1.0, "P": 1.0, "L": 1.0, "C": 1.0, "R": 1.0}

    tr = feats.get("traceable_number_ratio")
    err = feats.get("error_ratio") or 0.0
    err_r = _clamp01(err / ERR_SAT)
    trunc = 1.0 if _truncated(feats) else 0.0
    g_num = None if tr is None else _clamp01(1.0 - GROUND_SAT * (1.0 - tr))
    f_prec = feats.get("fact_precision")
    unf = struct.get("unfinished") if struct else None
    x_comp = None if unf is None else (0.0 if unf >= 1.0 else 1.0)
    o_num = o_den = 0.0
    for wgt, val in ((W_O_NUM, g_num), (W_O_PREC, f_prec),
                     (W_O_EXEC, 1.0 - err_r), (W_O_COMP, x_comp)):
        if val is None:
            continue
        o_num += wgt * val
        o_den += wgt
    s_o = _clamp01((o_num / o_den) if o_den else 1.0)
    if g_num is None:
        u["O"] *= 0.90
        if f_prec is None:
            u["O"] *= 0.85
    if x_comp is None:
        u["O"] *= 0.80

    ill_raw = struct.get("illegal_actions") if struct else None
    unf_raw = struct.get("unfinished") if struct else None
    miss_raw = struct.get("missing_frac") if struct else None
    drift_max = feats.get("goal_drift_max")
    illegal = 1.0 if ill_raw else 0.0
    unfinished = unf_raw or 0.0
    loop = feats.get("loop_count") or 0
    # Attribution gate. An errored step is already charged by error_ratio in O and in R, and a
    # truncated step already fires the t0_result_broken veto, so P stays silent on exactly those
    # traces instead of booking the same evidence a third time. Measured cost on the low-P side:
    # zero traces. See "Process dimension (slice4)" in the module docstring.
    claimed = (err > 0.0) or (trunc > 0.0)
    x_ill = None if ill_raw is None else 1.0 - illegal
    x_unf = None if (unf_raw is None or claimed) else (0.0 if unf_raw >= 1.0 else 1.0)
    x_loop = 1.0 - _clamp01(loop / float(LOOP_SAT))
    x_miss = None if miss_raw is None else 1.0 - _clamp01(miss_raw)
    x_drift = None if (drift_max is None or claimed) else (0.0 if drift_max > DRIFT_FLOOR else 1.0)
    p_num = p_den = 0.0
    for wgt, val in ((W_P_ILL, x_ill), (W_P_UNF, x_unf), (W_P_LOOP, x_loop),
                     (W_P_MISS, x_miss), (W_P_DRIFT, x_drift)):
        if val is None:
            continue
        p_num += wgt * val
        p_den += wgt
    s_p = _clamp01((p_num / p_den) if p_den else 1.0)
    if x_unf is None and not claimed:
        u["P"] *= 0.85
    if drift_max is None:
        u["P"] *= 0.90
    if not struct.get("required"):
        u["P"] *= 0.70

    s_l_val, _ = _anch(art, cell, "latency_total", feats.get("latency_total"))
    s_l = 1.0 if s_l_val is None else s_l_val
    if s_l_val is None:
        u["L"] *= 0.6
    if flags.get("ts_repaired"):
        u["L"] *= 0.70

    s_cost, _ = _anch(art, cell, "cost_total", feats.get("cost_total"))
    s_tok, _ = _anch(art, cell, "tokens_total", feats.get("tokens_total"))
    parts, wts = [], []
    if s_cost is not None:
        parts.append(s_cost)
        wts.append(0.6)
    if s_tok is not None:
        parts.append(s_tok)
        wts.append(0.4)
    s_c = (sum(p * w for p, w in zip(parts, wts)) / sum(wts)) if wts else 1.0
    if not wts:
        u["C"] *= 0.6
    if flags.get("usage_estimated"):
        u["C"] *= 0.60

    guard = feats.get("guard_hits") or 0      # read for the guard_violation veto, not for s_r
    unrec = struct.get("unrecovered_errors") if struct else None
    lr = struct.get("loop_rule") if struct else None
    x_unrec = None if unrec is None else 1.0 - _clamp01(len(unrec) / UNREC_SAT)
    x_loop = None if lr is None else 1.0 - _clamp01(lr)
    r_num = r_den = 0.0
    for wgt, val in ((W_R_FAIL, 1.0 - err_r), (W_R_UNREC, x_unrec), (W_R_LOOP, x_loop)):
        if val is None:
            continue
        r_num += wgt * val
        r_den += wgt
    s_r = _clamp01((r_num / r_den) if r_den else 1.0)
    if x_unrec is None:
        u["R"] *= 0.75
    if x_loop is None:
        u["R"] *= 0.85

    if mfr > 0.20:
        for d in u:
            u[d] *= 0.80
    if nov:
        u["L"] *= 0.50
        u["C"] *= 0.50
        u["R"] *= 0.70

    dims = {"O": s_o, "P": s_p, "L": s_l, "C": s_c, "R": s_r}

    gates = {}
    if guard > 0:
        gates["guard_violation"] = GATES["guard_violation"]
    if illegal > 0:
        gates["forbidden_action"] = GATES["forbidden_action"]
    if (tr is not None and tr < TR_FLOOR) or trunc > 0:
        gates["t0_result_broken"] = GATES["t0_result_broken"]
    elif struct.get("traceable_viol"):
        # the ontology validator is breached but the answer is still mostly grounded:
        # a veto would be disproportionate, a graded multiplier is not.
        gates["t2_untraceable_number"] = GATES["t2_untraceable_number"]
    # Narrowed from `unfinished > 0` to `>= 1.0` in slice5, and only because detect.l4_contract
    # learned to escalate on `absent` in the same commit. A 0.35 is a graded suspicion -- an
    # unusual ending from a trace that still performed its cell's closing step -- and feeding it
    # into an all-or-nothing veto put 269 normal traces in grade D on a signal whose precision
    # for the `unfinished` class was 38/399 = 9.5%. Narrowing it *alone* was tried in slice4 and
    # reverted; the full ledger, the A -> B attribution and the grade_separation cost are in
    # "Resolved in slice5" in the module docstring.
    if unfinished >= 1.0:
        gates["t1_unfinished"] = GATES["t1_unfinished"]
    if loop >= LOOP_SAT:
        gates["loop_runaway"] = GATES["loop_runaway"]
    if drift_suspect:
        gates["drift_suspect"] = GATES["drift_suspect"]
    if nov:
        gates["novelty"] = GATES["novelty"]
    g = 1.0
    for v in gates.values():
        g *= v

    num = 0.0
    den = 0.0
    for d, w in WEIGHTS.items():
        sd = max(dims[d], EPS)
        num += u[d] * w * math.log(sd)
        den += u[d] * w
    q = math.exp(num / den) if den > 0 else EPS
    s_base = 100.0 * g
    s = s_base * q

    contrib = {}
    if den > 0 and abs(s - s_base) > 1e-12 and s > 0 and s_base > 0:
        lmean = (s - s_base) / (math.log(s) - math.log(s_base))
        for d, w in WEIGHTS.items():
            contrib[d] = lmean * (u[d] * w / den) * math.log(max(dims[d], EPS))
    else:
        contrib = dict((d, 0.0) for d in WEIGHTS)

    conf = (det or {}).get("conf", 1.0)
    hw = 3.0 + 12.0 * (1.0 - conf)
    grade = "D"
    for name, cut in GRADE_ABS:
        if s >= cut:
            grade = name
            break
    return {
        "trace_id": feats["trace_id"],
        "cell": cell,
        "dims": dims,
        "dim_conf": u,
        "gates": gates,
        "G": g,
        "Q": q,
        "S": s,
        "S_base": s_base,
        "grade_abs": grade,
        "grade_rel": grade,
        "contrib": contrib,
        "ci": [max(0.0, s - hw), min(100.0, s + hw)],
        "conf": conf,
        "cold_start": bool(cold_start),
        "model_version": model_version,
        "anchor_version": anchor_version,
        "alert": bool((det or {}).get("alert")),
        "alert_stat": bool((det or {}).get("alert_stat")),
        "alert_rule": bool((det or {}).get("alert_rule")),
        "a_raw": (det or {}).get("a_raw", 0.0),
        "tier": int((det or {}).get("tier", 0)),
        "graded": float((det or {}).get("graded", 0.0)),
        "evidence": (det or {}).get("evidence", []),
        "novelty": nov,
    }


def score_all(features, assigns, stage, art, ontology, cold_start=False, drift_map=None,
              anchor_version="anchor-v1", model_version=MODEL_VERSION):
    amap = dict((a["trace_id"], a) for a in assigns)
    dmap = drift_map or {}
    out = []
    for f in features:
        tid = f["trace_id"]
        out.append(score_one(f, amap.get(tid, {}), stage.get(tid), art, ontology,
                             cold_start=cold_start, drift_suspect=bool(dmap.get(tid)),
                             anchor_version=anchor_version, model_version=model_version))
    assign_relative_grades(out)
    return out


def assign_relative_grades(recs, min_cell=8):
    """Within-cell relative grade: top 25% A / next 35% B / next 25% C / bottom 15% D."""
    by = {}
    for r in recs:
        by.setdefault(r["cell"], []).append(r)
    for cell, rs in by.items():
        if len(rs) < min_cell:
            for r in rs:
                r["grade_rel"] = r["grade_abs"]
            continue
        rs.sort(key=lambda r: (-r["S"], r["trace_id"]))
        n = len(rs)
        for i, r in enumerate(rs):
            f = i / float(n)
            r["grade_rel"] = "A" if f < 0.25 else ("B" if f < 0.60 else ("C" if f < 0.85 else "D"))
    return recs