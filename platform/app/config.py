import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = ROOT / "platform" / "config"
VAR_ROOT = ROOT / "platform" / "var"


def load_profile(profile_name: str, base_url_override: str | None = None) -> dict:
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
