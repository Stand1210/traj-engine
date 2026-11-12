# Frontend Routes and Data Dependencies

## M1 Pages

| Route | Page | Primary API |
|---|---|---|
| `/` | Dashboard | `GET /runs?limit=20` |
| `/runs` | Run list | `GET /runs` |
| `/runs/new` | Create run | `GET /tenants`, `GET /ontologies`, `POST /runs` |
| `/runs/:runId` | Run overview | `GET /runs/{runId}`, `GET /runs/{runId}/steps` |
| `/runs/:runId/cells` | Cluster view | `GET /runs/{runId}/cells` |
| `/runs/:runId/traces` | Trace list | `GET /runs/{runId}/traces` |
| `/runs/:runId/traces/:traceId` | Trace drilldown | `GET /runs/{runId}/traces/{traceId}` |
| `/runs/:runId/alerts` | Alert workbench | `GET /runs/{runId}/alerts` |
| `/settings` | Effective profile | `GET /config/profile`, `GET /startup-records/current` |

## M2+ Pages

| Route | Page | Primary API |
|---|---|---|
| `/onboarding` | Tenant and ontology onboarding | `POST /tenants`, `POST /ontologies` |
| `/ontologies/:ontologyId/prechecks` | Adapter precheck | `POST /ontologies/{id}/prechecks` |
| `/reviews` | Human review queue | `GET /reviews`, `POST /runs/{runId}/reviews` |
| `/runs/:runId/lineage` | Structure lineage | `GET /runs/{runId}/lineage` |

## UI State Rules

- Running runs poll `GET /runs/{runId}` and `GET /runs/{runId}/steps`.
- Scores are immutable; reruns create a new run, never overwrite an old run.
- Cross-version trend charts draw a version boundary, not a continuous line.
- The frontend never calls Langfuse directly.
