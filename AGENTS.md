# Repository Agent Instructions

This file is the entry point for any coding agent that takes over development of `traj-engine`.

## Project Identity

- Product: agent trajectory clustering, anomaly detection, and deterministic trajectory scoring.
- Repository root: this directory.
- Primary language: Python 3.11 (standard-library kernel plus a small pinned FastAPI platform).
- Frontend: Vite + React + TypeScript under `frontend/`.
- Current release baseline: tag `v0.1.0`; current development continues on `main`.

## Required Reading Order

1. `README.md` — methodology, reproducibility rules, and benchmark conclusions.
2. `platform/INTRANET_HANDOFF.md` — migration and model/tool takeover checklist.
3. `platform/DESIGN.md` — approved architecture decisions and rejected designs.
4. `platform/DEPLOYMENT.md` — dependencies, schema, profiles, and acceptance records.
5. `platform/USAGE_GUIDE.md` — business workflows and capability boundaries.
6. `platform/MODULES.md` and `platform/LIFECYCLE.md` — module and lifecycle semantics.

Do not rely only on conversation history. Docs are the durable source of decisions.

## Hard Product Rules

- Keep the analysis kernel deterministic and auditable. Do not introduce a generative judge.
- Never fabricate missing trace fields; preserve missing data and evidence degradation.
- Never place credentials in Git, ontology YAML, or release packages.
- One project maps to one business ontology. Do not reintroduce mixed-agent detection, `foreign_ratio`, or
  automatic noise isolation.
- Preserve `code_hash`, `structure_version`, and run provenance semantics.
- SQLite is the first-release storage engine; keep DDL PostgreSQL-compatible unless a migration is approved.
- Treat scheduler locks, lifecycle idempotency, and R1/R2 history as regression-sensitive.

## Module Map

- `kernel/` — deterministic business-independent algorithm.
- `bench/` — generation, invariants, scoring, coverage, and reproducibility.
- `contracts/` — frozen data contracts.
- `ontology/` — ontology interfaces and tiers.
- `platform/app/` — FastAPI service, storage, scheduler, Langfuse adapters, alerts, calibration.
- `platform/config/` — profiles and runtime configuration.
- `platform/contracts/` — OpenAPI and SQLite DDL.
- `platform/scripts/` — release, smoke, review, and pilot tooling.
- `frontend/src/` — production console.

## Commands

Run from the repository root:

```powershell
python -m pip install -r requirements.txt
python -m compileall -q platform
python -m unittest discover -s platform/tests -v
npm --prefix frontend install
npm --prefix frontend run build
```

Run focused tests first, then the full platform suite and frontend build.

## Change Discipline

- Make focused root-cause changes; do not silently refactor kernel or benchmark contracts.
- Keep docs synchronized with behavior, dependencies, schema, profiles, and model assets.
- Update `platform/USAGE_GUIDE.md` for user-visible workflow changes.
- Update `platform/DEPLOYMENT.md` for deployment, dependency, schema, or model changes.
- Update `platform/DESIGN.md` for architecture decisions and rejected alternatives.
- Do not commit caches, `.env`, `platform/var/`, databases, or `node_modules/`.
- Do not treat an LLM answer as correctness proof; use code, contracts, tests, or measured benchmarks.

## Intranet Tool / Model Takeover

- Current runtime has **no external LLM dependency and no deployed embedding model**.
- Switching the development assistant or assistant model does not change kernel outputs.
- Before intranet development, verify `platform/INTRANET_HANDOFF.md`.
- Any future model asset must record provider, exact version, dimensions, input truncation, cache policy,
  hash, evaluation, and impact on `code_hash` / `structure_version`.
- A new coding assistant starts with this file, then the handoff document, implementation, and tests.
