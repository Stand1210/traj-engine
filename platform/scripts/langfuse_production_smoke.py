import argparse
import base64
import json
import os
import sys
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app import store
from platform.app.algorithm import load_frozen_state
from platform.app.config import load_endpoints, load_profile
from platform.app.engine import RunEngine
from platform.app.langfuse_source import LangfuseTraceSource


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one production analysis against Langfuse v4")
    parser.add_argument("--profile", default="cloud-v4", choices=["cloud-v4", "selfhosted-v4"])
    parser.add_argument("--project-name", default="development_env")
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--id-offset", type=int, default=None)
    parser.add_argument("--id-count", type=int, default=None)
    parser.add_argument("--write-scores", action="store_true")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    endpoints = load_endpoints()
    keys = {
        "publicKey": os.environ.get("LANGFUSE_PUBLIC_KEY"),
        "secretKey": os.environ.get("LANGFUSE_SECRET_KEY"),
    }
    if not keys["publicKey"] or not keys["secretKey"]:
        raise SystemExit("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")

    project = _find_project(profile, endpoints, keys, args.project_name)
    connection = store.connect(initialize=True)
    try:
        tenant = connection.execute(
            "SELECT * FROM tenants WHERE org_id = ? AND project_id = ?",
            (project["organization"]["id"], project["id"]),
        ).fetchone()
        if tenant is None:
            tenant_id = store.create_tenant(
                connection,
                project["name"],
                project["organization"]["id"],
                project["id"],
                keys["publicKey"],
                keys["secretKey"],
            )
        else:
            tenant_id = tenant["id"]

        ontology = connection.execute(
            "SELECT * FROM ontologies WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if ontology is None:
            ontology_id = store.create_ontology(connection, tenant_id, project["name"], "tier0")
        else:
            ontology_id = ontology["id"]

        end = datetime.now(timezone.utc) + timedelta(minutes=5)
        start = end - timedelta(minutes=args.minutes)
        run_id = store.create_run(
            connection,
            tenant_id,
            ontology_id,
            "langfuse",
            "cloud-v4-smoke",
            "R1",
            start.isoformat(),
            end.isoformat(),
            1.0,
            "langfuse_production_smoke",
            None,
        )
        frozen_state = None
        active_structure = store.get_active_structure(connection, ontology_id)
        if active_structure is not None and active_structure["state_json"]:
            try:
                frozen_state = load_frozen_state(active_structure["state_json"])
                frozen_state["structure_id"] = active_structure["id"]
            except ValueError:
                frozen_state = None
    finally:
        connection.close()

    source = LangfuseTraceSource.from_config(
        profile,
        endpoints,
        keys,
        max_traces=None if args.id_offset is not None else args.limit,
        max_retries=5,
        retry_backoff_seconds=1.0,
    )
    if args.id_offset is not None:
        if args.id_count is None or args.id_count < 1:
            raise SystemExit("--id-offset requires --id-count >= 1")
        source = IdRangeTraceSource(source, args.id_offset, args.id_count)
    engine = RunEngine()
    score_writer = None
    if args.write_scores:
        from platform.app.langfuse_scores import LangfuseScoreWriter
        score_writer = LangfuseScoreWriter.from_config(profile, endpoints, keys)
    try:
        engine.submit(
            run_id,
            "cloud-v4-smoke",
            1.0,
            args.limit,
            trace_source=source,
            window={"start": start.isoformat(), "end": end.isoformat()},
            ontology_id=ontology_id,
            frozen_state=frozen_state,
            score_writer=score_writer,
        )
    finally:
        engine.close()

    with closing(store.connect(initialize=False)) as connection:
        run = store.get_run(connection, run_id)
        steps = connection.execute(
            "SELECT name, status, payload_json FROM run_steps WHERE run_id = ? ORDER BY started_at",
            (run_id,),
        ).fetchall()
        score_count = connection.execute(
            "SELECT COUNT(*) AS n FROM trace_scores WHERE run_id = ?", (run_id,)
        ).fetchone()["n"]
        cells = connection.execute(
            "SELECT COUNT(*) AS n FROM cells WHERE run_id = ?", (run_id,)
        ).fetchone()["n"]

    print(
        {
            "runId": run_id,
            "status": run["status"],
            "error": run["error"],
            "traces": score_count,
            "cells": cells,
            "steps": [
                {"name": step["name"], "status": step["status"], "payload": json.loads(step["payload_json"] or "null")}
                for step in steps
            ],
        }
    )
    return 0 if run["status"] == "succeeded" else 1


def _find_project(profile: dict, endpoints: dict, keys: dict, project_name: str) -> dict:
    path = endpoints["endpoints"]["projects"]["list"]["path"]
    token = base64.b64encode(
        f"{keys['publicKey']}:{keys['secretKey']}".encode("utf-8")
    ).decode("ascii")
    request = urllib.request.Request(
        f"{profile['baseUrl']}{path}",
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    projects = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(projects, list) or not projects:
        raise SystemExit("Langfuse project list is empty")
    for project in projects:
        if project.get("name") == project_name:
            return project
    return projects[0]


class IdRangeTraceSource:
    source_type = "langfuse-id-range"

    def __init__(self, source, id_offset: int, count: int):
        self.source = source
        self.id_offset = id_offset
        self.count = count
        self.traversal = {}

    def list_traces(self, window: dict, sampling: dict):
        traces = [
            trace for trace in self.source.list_traces(window, sampling)
            if self.id_offset <= int(trace["trace_id"], 16) < self.id_offset + self.count
        ]
        self.traversal = {
            **self.source.traversal,
            "id_range_matched": len(traces),
        }
        yield from traces


if __name__ == "__main__":
    raise SystemExit(main())
