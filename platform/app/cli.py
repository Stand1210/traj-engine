import argparse
import json
import os
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="create or initialize the SQLite database")
    init_parser.add_argument("--db", default=None)
    upgrade_parser = subparsers.add_parser("upgrade", help="apply schema migrations")
    upgrade_parser.add_argument("--db", default=None)

    run_parser = subparsers.add_parser("run", help="start the backend service")
    run_parser.add_argument("--host", default="127.0.0.1")
    run_parser.add_argument("--port", type=int, default=8000)
    run_parser.add_argument("--profile", choices=["cloud-v4", "selfhosted-v4"], default="cloud-v4")
    run_parser.add_argument("--base-url", default=None)
    run_parser.add_argument("--db", default=None)
    run_parser.add_argument("--scheduler", action="store_true")

    smoke_parser = subparsers.add_parser("smoke", help="verify a running deployment")
    smoke_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    smoke_parser.add_argument("--timeout", type=float, default=5.0)
    smoke_parser.add_argument("--expected-profile", choices=["cloud-v4", "selfhosted-v4"], default=None)

    release_parser = subparsers.add_parser("release", help="build a verifiable release package")
    release_parser.add_argument("--version", default="0.1.0")
    release_parser.add_argument("--output", default=None)
    release_parser.add_argument("--git-commit", default=None)

    release_verify_parser = subparsers.add_parser("release-verify", help="verify a release package")
    release_verify_parser.add_argument("--package", required=True)
    release_verify_parser.add_argument("--expected-kernel-code-hash", default=None)

    arguments = sys.argv[1:] or ["run"]
    commands = {"init", "upgrade", "run", "smoke", "release", "release-verify"}
    if arguments[0] not in commands and arguments[0] != "--help":
        arguments = ["run"] + arguments
    args = parser.parse_args(arguments)

    if args.command in {"init", "upgrade"}:
        from platform.app import store
        from platform.app.deployment_smoke import initialize_database

        db_path = Path(args.db or store.resolve_db_path())
        print(json.dumps(initialize_database(db_path), ensure_ascii=False))
        return

    if args.command == "smoke":
        from platform.app.deployment_smoke import run_deployment_smoke

        print(json.dumps(
            run_deployment_smoke(args.base_url, args.timeout, args.expected_profile),
            ensure_ascii=False,
        ))
        return

    if args.command == "release":
        import subprocess
        from platform.app import release

        root = Path(__file__).resolve().parents[2]
        output = Path(args.output) if args.output else (
            root / "platform" / "var" / "releases" / f"traj-engine-{args.version}.zip"
        )
        git_commit = args.git_commit
        if git_commit is None:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
        package = release.build_release(root, output, args.version, git_commit)
        print(json.dumps({
            "status": "built",
            "package": str(package),
            "version": args.version,
            "gitCommit": git_commit,
        }, ensure_ascii=False))
        return

    if args.command == "release-verify":
        from platform.app import release

        print(json.dumps(
            release.verify_release(
                args.package,
                expected_kernel_code_hash=args.expected_kernel_code_hash,
            ),
            ensure_ascii=False,
        ))
        return

    os.environ["TRAJ_PROFILE"] = args.profile
    if args.base_url:
        os.environ["LANGFUSE_BASE_URL"] = args.base_url
    if args.db:
        os.environ["TRAJ_DB_PATH"] = args.db
    if args.scheduler:
        os.environ["TRAJ_SCHEDULER"] = "1"
    uvicorn.run(
        "platform.app.service:app",
        host=args.host,
        port=args.port,
        env_file=None,
    )


if __name__ == "__main__":
    main()
