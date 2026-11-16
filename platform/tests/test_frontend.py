import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from platform.app import frontend


class FrontendTest(unittest.TestCase):
    def test_serves_index_assets_and_spa_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            (dist / "assets").mkdir()
            (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
            asset = dist / "assets" / "app.js"
            asset.write_text("console.log(1)", encoding="utf-8")

            with patch.object(frontend, "FRONTEND_DIST", dist):
                index_response = frontend.serve_frontend_index()
                asset_response = frontend.serve_frontend_asset("assets/app.js")
                fallback_response = frontend.serve_frontend_asset("runs/detail")

            self.assertTrue((dist / "index.html").samefile(index_response.path))
            self.assertEqual("text/html", index_response.media_type)
            self.assertTrue(asset.samefile(asset_response.path))
            self.assertTrue((dist / "index.html").samefile(fallback_response.path))

    def test_rejects_frontend_when_build_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(frontend, "FRONTEND_DIST", Path(directory)):
                with self.assertRaisesRegex(HTTPException, "frontend build is not available"):
                    frontend.serve_frontend_index()

    def test_unknown_api_path_is_not_masked_by_spa_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")

            with patch.object(frontend, "FRONTEND_DIST", dist):
                with self.assertRaisesRegex(HTTPException, "not found"):
                    frontend.serve_frontend_asset("api/v1/unknown")


if __name__ == "__main__":
    unittest.main()
