import json
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Callable


ALLOWED_PROFILES = {"cloud-v4", "selfhosted-v4"}
Opener = Callable[..., object]


class DeploymentSmokeError(RuntimeError):
    pass


def _request_json(base_url: str, path: str, timeout: float, opener: Opener) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise DeploymentSmokeError(f"HTTP {error.code} from {url}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DeploymentSmokeError(f"cannot access {url}: {error}") from error
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        raise DeploymentSmokeError(f"non-JSON response from {url}") from error
    if not isinstance(value, dict):
        raise DeploymentSmokeError(f"non-object response from {url}")
    return value


def run_deployment_smoke(
    base_url: str,
    timeout: float = 5.0,
    expected_profile: str | None = None,
    opener: Opener = urllib.request.urlopen,
) -> dict:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if expected_profile is not None and expected_profile not in ALLOWED_PROFILES:
        raise ValueError(f"unsupported profile: {expected_profile}")

    health = _request_json(base_url, "/api/v1/health", timeout, opener)
    if health.get("status") != "ok":
        raise DeploymentSmokeError(f"health status is not ok: {health.get('status')!r}")
    if health.get("version") != "0.1.0":
        raise DeploymentSmokeError(f"unexpected API version: {health.get('version')!r}")

    profile = _request_json(base_url, "/api/v1/config/profile", timeout, opener)
    if profile.get("profile") not in ALLOWED_PROFILES:
        raise DeploymentSmokeError(f"unsupported runtime profile: {profile.get('profile')!r}")
    if expected_profile is not None and profile.get("profile") != expected_profile:
        raise DeploymentSmokeError(
            f"profile mismatch: expected {expected_profile}, got {profile.get('profile')!r}"
        )

    startup = _request_json(base_url, "/api/v1/startup-records/current", timeout, opener)
    if startup.get("profile") != profile.get("profile"):
        raise DeploymentSmokeError(
            f"startup profile mismatch: {startup.get('profile')!r} != {profile.get('profile')!r}"
        )

    tenants = _request_json(base_url, "/api/v1/tenants?limit=1", timeout, opener)
    ontologies = _request_json(base_url, "/api/v1/ontologies?limit=1", timeout, opener)
    if not isinstance(tenants.get("data"), list) or not isinstance(ontologies.get("data"), list):
        raise DeploymentSmokeError("tenant or ontology response is malformed")

    return {
        "status": "passed",
        "base_url": base_url.rstrip("/"),
        "profile": profile.get("profile"),
        "apiVersion": health.get("version"),
        "tenantCountChecked": len(tenants["data"]),
        "ontologyCountChecked": len(ontologies["data"]),
    }


def initialize_database(db_path: str | Path) -> dict:
    from platform.app import store

    path = Path(db_path)
    with closing(store.connect(path, initialize=True)) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    required_tables = {"tenants", "ontologies", "cohort_runs", "schema_migrations"}
    missing = sorted(required_tables - tables)
    if missing:
        raise DeploymentSmokeError(f"database initialization is incomplete: {missing}")
    return {
        "status": "initialized",
        "db_path": str(path.resolve()),
        "schema_version": store.SCHEMA_VERSION,
        "table_count": len(tables),
    }
