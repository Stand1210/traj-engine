import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = ROOT / "platform" / "config"
VAR_ROOT = ROOT / "platform" / "var"


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_profile(profile_name: str, base_url_override: str | None = None) -> dict:
    load_env_file()
    path = CONFIG_ROOT / "profiles" / f"{profile_name}.yaml"
    if not path.exists():
        raise ValueError(f"unknown profile: {profile_name}")
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    profile["baseUrl"] = base_url_override or os.environ.get("LANGFUSE_BASE_URL", profile["baseUrl"])
    return profile


def load_endpoints() -> dict:
    path = CONFIG_ROOT / "endpoints.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resolve_profile_from_args(profile_name: str | None = None) -> dict:
    profile_name = profile_name or os.environ.get("TRAJ_PROFILE", "cloud-v4")
    if profile_name not in {"cloud-v4", "selfhosted-v4"}:
        raise ValueError("first release supports only cloud-v4 and selfhosted-v4")
    return load_profile(profile_name)
