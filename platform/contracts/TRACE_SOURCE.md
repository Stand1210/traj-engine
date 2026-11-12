# TraceSource Contract

## 1. Interface

```python
from typing import Iterator, Protocol

class TimeWindow(Protocol):
    start: str
    end: str

class SamplingPolicy(Protocol):
    rate: float
    seed: int
    strategy: str

class TraceSource(Protocol):
    source_type: str

    def list_traces(
        self,
        window: TimeWindow,
        sampling: SamplingPolicy,
    ) -> Iterator[dict]:
        ...
```

## 2. Output Contract

Every yielded record is one `RawTrace` and must conform to `contracts/schemas.md`.

- Trace object has the required 19 keys.
- Each span object has the required 29 keys.
- Fields unavailable in the source must be `None`; they must not be omitted, guessed, or silently defaulted.
- The source must preserve trace/span tree relationships before yielding.
- The source must not modify algorithm inputs or ontology.

## 3. Implementations

| Implementation | Stage | Input | Notes |
|---|---|---|---|
| `JsonlTraceSource` | M1 | `data/bench_v1/*/traces.jsonl` | Registered as an internal platform tenant |
| `LangfuseTraceSource` | M2 | Observations API v2 | Fixture-tested implementation; real project first-run pending |

## 4. Pagination and Failure Rules

- Cursor pagination continues until the response cursor is absent.
- A page with zero rows and a present cursor is not the end.
- Network failures may be retried with bounded exponential backoff.
- HTTP `404` from a supported v4 profile is a configuration error, not a data-empty result.
- Partial ingestion must fail the run; it must not be silently scored.

## 5. Reproducibility Rules

- The source must record `source_type`, `window`, `sampling`, profile name, and startup record id.
- For `JsonlTraceSource`, dataset `spec_hash` must be recorded.
- For `LangfuseTraceSource`, profile hash and cursor traversal metadata must be recorded.
- A run is reproducible only if its input identity, ontology version, code hash, and structure version are all recorded.

