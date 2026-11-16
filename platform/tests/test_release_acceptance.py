import tempfile
import shutil
import unittest
import socket
from pathlib import Path

from platform.app import release
from platform.scripts import release_acceptance


ROOT = Path(__file__).resolve().parents[2]


def build_test_release(directory: Path) -> Path:
    source = directory / "source"
    source.mkdir()

    for relative in release.RELEASE_FILES:
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)

    for relative_directory in release.RELEASE_DIRECTORIES:
        shutil.copytree(
            ROOT / relative_directory,
            source / relative_directory,
            ignore=shutil.ignore_patterns("__pycache__"),
        )

    frontend_dist = source / "frontend" / "dist"
    frontend_dist.mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<html></html>\n", encoding="utf-8")

    return release.build_release(
        source,
        directory / "release.zip",
        "0.1.0",
        git_commit="test",
        kernel_code_hash="kernel-hash",
        schema_version=7,
        created_at="2026-01-01T00:00:00Z",
    )


class ReleaseAcceptanceTest(unittest.TestCase):
    def test_package_starts_and_passes_smoke_in_clean_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            package = build_test_release(Path(directory))
            work_dir = Path(directory) / "accepted"

            result = release_acceptance.run_release_acceptance(
                package,
                work_dir=work_dir,
                port=self._free_port(),
                timeout=15.0,
            )

            self.assertEqual("passed", result["status"])
            self.assertEqual("cloud-v4", result["profile"])
            self.assertEqual("passed", result["smoke"]["status"])
            self.assertTrue((work_dir / "platform" / "var" / "traj-engine.db").is_file())
            self.assertTrue((work_dir / "frontend" / "dist" / "index.html").is_file())

    def test_stage_release_rejects_non_empty_work_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            package = build_test_release(Path(directory))
            work_dir = Path(directory) / "work"
            work_dir.mkdir()
            (work_dir / "existing.txt").write_text("blocked", encoding="utf-8")

            with self.assertRaisesRegex(
                release_acceptance.ReleaseAcceptanceError,
                "work directory is not empty",
            ):
                release_acceptance.stage_release(package, work_dir)

    def _free_port(self) -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


if __name__ == "__main__":
    unittest.main()
