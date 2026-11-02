import os
import subprocess
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AuthPackageTests(unittest.TestCase):
    def run_auth(self, *arguments: str, secret: str | None = None) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.pop("AUTH_SECRET", None)
        if secret is not None:
            environment["AUTH_SECRET"] = secret
        return subprocess.run(
            [sys.executable, "-m", "auth", *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_package_import_does_not_load_server_dependencies(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import auth"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help_does_not_require_a_secret_or_optional_dependencies(self) -> None:
        result = self.run_auth("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--host", result.stdout)
        self.assertIn("--port", result.stdout)

    def test_missing_secret_has_an_actionable_error(self) -> None:
        result = self.run_auth()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AUTH_SECRET must contain at least 32 characters", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_port_is_rejected_before_server_startup(self) -> None:
        result = self.run_auth("--port", "70000")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("port must be between 1 and 65535", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
