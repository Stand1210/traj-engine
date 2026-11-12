import importlib
import unittest


class PlatformCompatibilityTest(unittest.TestCase):
    def test_stdlib_platform_api_remains_available_behind_repo_package(self):
        import platform

        self.assertTrue(callable(platform.system))
        self.assertIsInstance(platform.system(), str)
        self.assertTrue(callable(platform.python_version))

        app = importlib.import_module("platform.app")
        self.assertTrue(app.__name__.startswith("platform.app"))


if __name__ == "__main__":
    unittest.main()
