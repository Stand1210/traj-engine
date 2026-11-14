import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--profile", choices=["cloud-v4", "selfhosted-v4"], default="cloud-v4")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--scheduler", action="store_true")
    args = parser.parse_args()
    os.environ["TRAJ_PROFILE"] = args.profile
    if args.base_url:
        os.environ["LANGFUSE_BASE_URL"] = args.base_url
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
