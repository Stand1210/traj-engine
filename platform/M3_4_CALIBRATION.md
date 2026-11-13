# M3.4 Human-Review Calibration

## Scope

M3.4 turns completed human reviews into a controlled calibration layer. It
does not modify the algorithm kernel or historical alert decisions.

## Review aggregation

- Reviews are grouped by `trace_score_id`.
- Multiple reviewers are reduced by majority vote.
- An exact tie becomes `uncertain`.
- `uncertain` labels are excluded from precision and reliability metrics.

## Metrics

- `alertPrecision`: agreement rate on reviewed formal alerts.
- `alertCoverage`: reviewed formal alerts divided by all formal alerts.
- `reviewCoverage`: reviewed traces divided by all run traces.
- `ece`: binned difference between normalized total score and human agreement.
- `brier`: mean squared error between normalized total score and agreement.
- `causeStats`: per-cause sample count and agreement rate.

## Safety gate

The default production gate is:

- at least 20 review labels;
- at least 5 reviewed formal alerts. This matches the default alert budget of
  5. Cause calibration additionally uses reviewed candidates and suppressed
  duplicates to collect enough per-cause samples.

If either threshold is not met, trigger returns HTTP 400 with
`calibration_insufficient_labels` and no version is created.

## Version and activation

Each trigger creates an immutable `review_calibrations` row containing:

- source run and tenant;
- label and verdict counts;
- alert precision, ECE, and Brier;
- full metrics and parameter JSON;
- kernel code hash, creator, and timestamps.

Activation is explicit. One active version is retained per tenant. The active
version supplies `causeSeverityAdjustments` to later alert ranking. Historical
`alert_decisions` rows are never rewritten.

## REST API

- `POST /api/v1/runs/{runId}/calibration/trigger`
- `GET /api/v1/calibrations`
- `GET /api/v1/calibrations/{calibrationId}`
- `POST /api/v1/calibrations/{calibrationId}/activate`

## Frontend

Route: `#/runs/{runId}/calibration`

The workbench shows review coverage, calibration versions, metrics, and the
activate action.

## Validation

Before synthetic validation, real Cloud run `run-35339336f1e24ab4` had no
imported review labels. Triggering calibration returned HTTP 400 with
`calibration_insufficient_labels`, required counts of 20 labels and 5
reviewed formal alerts, actual counts of 0, and created no calibration
version.

### Synthetic development validation

The development-only script
`platform/scripts/validate_synthetic_calibration.py` creates 20 deterministic
labels with reviewer `synthetic-benchmark`: all 5 formal alerts are `agree`
and 15 candidates/suppressed duplicates are `disagree`.

Validated result:

- calibration version created;
- version activated;
- alert precision 1.0;
- ECE 0.122373;
- Brier 0.199428;
- `rule:untraceable_answer_number` and `rule:unfinished`
  adjustments both 0.5;
- its top priority changed from 80.089 to 73.089.

Synthetic labels are for engineering validation only and must not be treated
as real business review evidence.
