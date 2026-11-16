import hashlib
import json
import re
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile


MANIFEST_NAME = "release-manifest.json"
MANIFEST_FORMAT_VERSION = 1
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

RELEASE_DIRECTORIES = (
    "platform/app",
    "platform/scripts",
    "bench",
    "kernel",
    "ontology",
)

RELEASE_FILES = (
    "requirements.txt",
    "README.md",
    "platform/__init__.py",
    "platform/contracts/schema.sql",
    "platform/contracts/openapi.yaml",
    "platform/DEPLOYMENT.md",
    "platform/USAGE_GUIDE.md",
    "platform/config/alerts.yaml",
    "platform/config/calibration.yaml",
    "platform/config/endpoints.yaml",
    "platform/config/performance.yaml",
    "platform/config/scheduler.yaml",
    "platform/config/profiles/cloud-v4.yaml",
    "platform/config/profiles/selfhosted-v4.yaml",
    "platform/config/tenants/example.yaml",
)


class ReleaseError(RuntimeError):
    pass


def collect_release_files(root: str | Path) -> list[Path]:
    base = Path(root)
    if not base.is_dir():
        raise ReleaseError(f"release root does not exist: {base}")

    files: list[Path] = []
    for relative in RELEASE_FILES:
        path = base / relative
        if not path.is_file():
            raise ReleaseError(f"required release file is missing: {relative}")
        files.append(path)

    for relative_directory in RELEASE_DIRECTORIES:
        directory = base / relative_directory
        if not directory.is_dir():
            raise ReleaseError(f"required release directory is missing: {relative_directory}")
        found = [
            path for path in directory.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ]
        if not found:
            raise ReleaseError(f"release directory is empty: {relative_directory}")
        files.extend(found)

    frontend_dist = base / "frontend" / "dist"
    if not (frontend_dist / "index.html").is_file():
        raise ReleaseError("frontend/dist/index.html is missing; run the frontend build first")
    files.extend(path for path in frontend_dist.rglob("*") if path.is_file())

    unique_files = set(files)
    forbidden = {".env", ".git", "node_modules", "platform/var"}
    leaked = [
        path for path in unique_files
        if any(part in forbidden for part in path.parts)
    ]
    if leaked:
        raise ReleaseError(f"release contains forbidden runtime or credential paths: {sorted(leaked)}")

    return sorted(unique_files, key=lambda path: path.relative_to(base).as_posix())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def build_release(
    root: str | Path,
    output: str | Path,
    version: str,
    git_commit: str | None = None,
    kernel_code_hash: str | None = None,
    schema_version: int | None = None,
    created_at: str | None = None,
) -> Path:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version may contain only letters, digits, dot, underscore and hyphen")

    base = Path(root)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = collect_release_files(base)

    if kernel_code_hash is None:
        from bench.runner import code_hash
        kernel_code_hash = code_hash()
    if schema_version is None:
        from platform.app import store
        schema_version = store.SCHEMA_VERSION
    if created_at is None:
        from platform.app import store
        created_at = store.utcnow()

    entries = [
        {
            "path": path.relative_to(base).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in files
    ]
    manifest = {
        "formatVersion": MANIFEST_FORMAT_VERSION,
        "releaseVersion": version,
        "gitCommit": git_commit,
        "schemaVersion": schema_version,
        "kernelCodeHash": kernel_code_hash,
        "createdAt": created_at,
        "fileCount": len(entries),
        "files": entries,
    }

    with NamedTemporaryFile(
        prefix=f"{destination.stem}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                _write_zip_entry(
                    archive,
                    path.relative_to(base).as_posix(),
                    path.read_bytes(),
                )
            _write_zip_entry(
                archive,
                MANIFEST_NAME,
                (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            )
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)

    return destination


def verify_release(
    package: str | Path,
    *,
    expected_kernel_code_hash: str | None = None,
) -> dict:
    path = Path(package)
    if not path.is_file():
        raise ReleaseError(f"release package does not exist: {path}")

    try:
        with zipfile.ZipFile(path, "r") as archive:
            if archive.testzip() is not None:
                raise ReleaseError("release package contains a corrupt entry")
            manifest_bytes = archive.read(MANIFEST_NAME)
    except KeyError as error:
        raise ReleaseError("release manifest is missing") from error
    except zipfile.BadZipFile as error:
        raise ReleaseError("release package is not a valid zip file") from error

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseError("release manifest is not valid UTF-8 JSON") from error

    if not isinstance(manifest, dict):
        raise ReleaseError("release manifest must be a JSON object")
    if manifest.get("formatVersion") != MANIFEST_FORMAT_VERSION:
        raise ReleaseError(f"unsupported manifest format: {manifest.get('formatVersion')!r}")

    entries = manifest.get("files")
    if not isinstance(entries, list) or manifest.get("fileCount") != len(entries):
        raise ReleaseError("release manifest file count is invalid")

    expected_paths = {entry.get("path") for entry in entries}
    if len(expected_paths) != len(entries) or None in expected_paths:
        raise ReleaseError("release manifest contains duplicate or missing paths")
    expected_paths.add(MANIFEST_NAME)

    with zipfile.ZipFile(path, "r") as archive:
        actual_paths = set(archive.namelist())
        if actual_paths != expected_paths:
            missing = sorted(expected_paths - actual_paths)
            extra = sorted(actual_paths - expected_paths)
            raise ReleaseError(f"package contents differ from manifest; missing={missing}, extra={extra}")

        for entry in entries:
            name = entry["path"]
            data = archive.read(name)
            if entry.get("size") != len(data):
                raise ReleaseError(f"size mismatch: {name}")
            if entry.get("sha256") != hashlib.sha256(data).hexdigest():
                raise ReleaseError(f"sha256 mismatch: {name}")

    if expected_kernel_code_hash is not None and manifest.get("kernelCodeHash") != expected_kernel_code_hash:
        raise ReleaseError(
            f"kernel code hash mismatch: expected {expected_kernel_code_hash}, "
            f"got {manifest.get('kernelCodeHash')!r}"
        )

    return {
        "status": "passed",
        "releaseVersion": manifest.get("releaseVersion"),
        "gitCommit": manifest.get("gitCommit"),
        "schemaVersion": manifest.get("schemaVersion"),
        "kernelCodeHash": manifest.get("kernelCodeHash"),
        "fileCount": manifest.get("fileCount"),
    }
