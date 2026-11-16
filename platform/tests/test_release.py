import tempfile
import unittest
import zipfile
from pathlib import Path

from platform.app import release


def create_release_tree(root: Path) -> None:
    for relative in release.RELEASE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n", encoding="utf-8")

    for relative_directory in release.RELEASE_DIRECTORIES:
        directory = root / relative_directory
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "module.py").write_text("value = 1\n", encoding="utf-8")
        cache = directory / "__pycache__"
        cache.mkdir()
        (cache / "module.pyc").write_bytes(b"cache")

    frontend_dist = root / "frontend" / "dist"
    (frontend_dist / "assets").mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (frontend_dist / "assets" / "app.js").write_text("console.log(1)\n", encoding="utf-8")

    forbidden = root / "platform" / "var"
    forbidden.mkdir(parents=True)
    (forbidden / "runtime.db").write_text("runtime", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")


class ReleaseTest(unittest.TestCase):
    def test_builds_and_verifies_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_release_tree(root)
            output = root / "out" / "traj-engine-0.1.0.zip"

            package = release.build_release(
                root,
                output,
                "0.1.0",
                git_commit="abc123",
                kernel_code_hash="kernel-hash",
                schema_version=7,
                created_at="2026-01-01T00:00:00Z",
            )
            result = release.verify_release(
                package, expected_kernel_code_hash="kernel-hash"
            )

            self.assertEqual(output, package)
            self.assertEqual("passed", result["status"])
            self.assertEqual("0.1.0", result["releaseVersion"])
            self.assertEqual("abc123", result["gitCommit"])
            self.assertEqual(7, result["schemaVersion"])
            self.assertEqual("kernel-hash", result["kernelCodeHash"])

            with zipfile.ZipFile(package) as archive:
                names = archive.namelist()
                self.assertIn("release-manifest.json", names)
                self.assertIn("frontend/dist/index.html", names)
                self.assertIn("platform/app/module.py", names)
                self.assertNotIn("platform/app/__pycache__/module.pyc", names)
                self.assertNotIn("platform/var/runtime.db", names)
                self.assertNotIn(".env", names)

    def test_requires_frontend_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_release_tree(root)
            (root / "frontend" / "dist" / "index.html").unlink()

            with self.assertRaisesRegex(release.ReleaseError, "frontend/dist/index.html"):
                release.build_release(
                    root,
                    root / "release.zip",
                    "0.1.0",
                    kernel_code_hash="kernel-hash",
                    schema_version=7,
                    created_at="2026-01-01T00:00:00Z",
                )

    def test_rejects_tampered_package_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_release_tree(root)
            package = release.build_release(
                root,
                root / "release.zip",
                "0.1.0",
                kernel_code_hash="kernel-hash",
                schema_version=7,
                created_at="2026-01-01T00:00:00Z",
            )

            with zipfile.ZipFile(package) as archive:
                contents = {
                    name: archive.read(name)
                    for name in archive.namelist()
                }
            original = contents["README.md"]
            contents["README.md"] = b"X" + original[1:]
            tampered = root / "tampered.zip"
            with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in contents.items():
                    archive.writestr(name, data)

            with self.assertRaisesRegex(release.ReleaseError, "sha256 mismatch: README.md"):
                release.verify_release(tampered)


if __name__ == "__main__":
    unittest.main()
