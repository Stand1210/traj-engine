import argparse
import json
import subprocess
import sys
import time
import zipfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform.app import release
from platform.app.deployment_smoke import ALLOWED_PROFILES, _request_json


class ReleaseAcceptanceError(RuntimeError):
    pass


def stage_release(package: str | Path, work_dir: str | Path) -> Path:
    release.verify_release(package)
    destination = Path(work_dir)
    if destination.exists() and any(destination.iterdir()):
        raise ReleaseAcceptanceError(f"work directory is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package, "r") as archive:
        archive.extractall(destination)
    return destination


def _run_command(
    command: list[str],
    cwd: Path,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ReleaseAcceptanceError(f"command timed out: {' '.join(command)}") from error


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_release_acceptance(
    package: str | Path,
    *,
    work_dir: str | Path,
    profile: str = "cloud-v4",
    host: str = "127.0.0.1",
    port: int = 18080,
    timeout: float = 30.0,
    python: str = sys.executable,
    create_venv: bool = False,
) -> dict:
    if profile not in ALLOWED_PROFILES:
        raise ValueError(f"unsupported profile: {profile}")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not 1024 <= port <= 65535:
        raise ValueError("port must be between 1024 and 65535")

    staged = stage_release(package, work_dir)
    python_executable = python

    if create_venv:
        venv_dir = staged / ".venv"
        created = _run_command(
            [python_executable, "-m", "venv", str(venv_dir)],
            staged,
            timeout,
        )
        if created.returncode != 0:
            raise ReleaseAcceptanceError(f"venv creation failed: {created.stderr}")
        python_executable = str(venv_dir / "Scripts" / "python.exe")
        if not Path(python_executable).is_file():
            python_executable = str(venv_dir / "bin" / "python")
        installed = _run_command(
            [python_executable, "-m", "pip", "install", "-r", "requirements.txt"],
            staged,
            timeout,
        )
        if installed.returncode != 0:
            raise ReleaseAcceptanceError(f"dependency installation failed: {installed.stderr}")

    initialized = _run_command(
        [
            python_executable,
            "-m",
            "platform.app.cli",
            "init",
            "--db",
            "platform/var/traj-engine.db",
        ],
        staged,
        timeout,
    )
    if initialized.returncode != 0:
        raise ReleaseAcceptanceError(f"database initialization failed: {initialized.stderr}")

    service = subprocess.Popen(
        [
            python_executable,
            "-m",
            "platform.app.cli",
            "run",
            "--host",
            host,
            "--port",
            str(port),
            "--profile",
            profile,
            "--db",
            "platform/var/traj-engine.db",
        ],
        cwd=staged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = f"http://{host}:{port}"
    try:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if service.poll() is not None:
                output = service.stdout.read() if service.stdout else ""
                errors = service.stderr.read() if service.stderr else ""
                raise ReleaseAcceptanceError(
                    f"service exited before becoming ready: {output} {errors}"
                )
            try:
                health = _request_json(
                    base_url,
                    "/api/v1/health",
                    1.0,
                    urllib.request.urlopen,
                )
                if health.get("status") == "ok":
                    break
            except Exception as error:
                last_error = error
            time.sleep(0.2)
        else:
            raise ReleaseAcceptanceError(f"service did not become ready: {last_error}")

        smoke = _run_command(
            [
                python_executable,
                "-m",
                "platform.app.cli",
                "smoke",
                "--base-url",
                base_url,
                "--expected-profile",
                profile,
            ],
            staged,
            timeout,
        )
        if smoke.returncode != 0:
            raise ReleaseAcceptanceError(f"smoke failed: {smoke.stdout} {smoke.stderr}")
        try:
            smoke_result = json.loads(smoke.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise ReleaseAcceptanceError("smoke did not emit JSON") from error
    finally:
        _stop_process(service)

    return {
        "status": "passed",
        "profile": profile,
        "package": str(Path(package)),
        "workDir": str(staged),
        "venvCreated": create_venv,
        "smoke": smoke_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--profile", choices=sorted(ALLOWED_PROFILES), default="cloud-v4")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--create-venv", action="store_true")
    arguments = parser.parse_args()
    result = run_release_acceptance(
        arguments.package,
        work_dir=arguments.work_dir,
        profile=arguments.profile,
        host=arguments.host,
        port=arguments.port,
        timeout=arguments.timeout,
        python=arguments.python,
        create_venv=arguments.create_venv,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
