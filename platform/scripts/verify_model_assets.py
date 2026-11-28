"""Verify an offline model package against the pinned asset registry.

Intended for intranet operations *before* service startup: checks every
declared weight file exists and matches its SHA-256, then prints the asset
fingerprint that runs will record as provenance. Exit code 0 means the
package at ``--root`` exactly matches ``platform/config/model_assets.json``.

Usage:
    python -m platform.scripts.verify_model_assets [--model bge-m3] \
        [--root platform/var/models/bge-m3] [--registry platform/config/model_assets.json]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app.encoder import EncoderContractError
from platform.app.intent_encoder import load_asset_registry, model_asset_from_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an offline model package against the asset registry")
    parser.add_argument("--model", default="bge-m3", help="registry entry name (default: bge-m3)")
    parser.add_argument("--root", default=None, help="model package directory (default: registry cache_dir)")
    parser.add_argument("--registry", default=None, help="asset registry path (default: platform/config/model_assets.json)")
    args = parser.parse_args()

    try:
        registry = load_asset_registry(args.registry)
        asset = model_asset_from_registry(args.model, registry)
    except EncoderContractError as error:
        print(f"REGISTRY ERROR: {error}")
        return 2

    root = Path(args.root) if args.root else ROOT / str(asset.cache_dir)
    print(f"model: {asset.model_name} @ {asset.revision}")
    print(f"root:  {root}")

    failures = []
    total_bytes = 0
    for relative, expected in sorted(asset.weights.items()):
        path = root / relative
        if not path.exists():
            failures.append(f"MISSING {relative}")
            print(f"  MISSING {relative}")
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        total_bytes += path.stat().st_size
        if actual != expected:
            failures.append(f"HASH MISMATCH {relative}")
            print(f"  FAIL    {relative} expected={expected[:16]}... actual={actual[:16]}...")
        else:
            print(f"  OK      {relative}")

    if failures:
        print(
            f"FAILED: {len(failures)} file(s) do not match the registry; "
            "re-install the approved offline model package "
            "(see DEPLOYMENT.md model asset section)"
        )
        return 1
    print(f"fingerprint: {asset.fingerprint()}")
    print(f"files: {len(asset.weights)} OK, {total_bytes / (1024 ** 3):.2f} GiB total")
    print("PASSED: offline model package matches the pinned asset registry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
