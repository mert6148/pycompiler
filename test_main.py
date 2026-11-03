import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import main


class PackageRequirementTests(unittest.TestCase):
    def test_accepts_exact_numeric_versions(self):
        for requirement in ("requests==2.32.4", "A-package_2==1", "demo==1.2.3"):
            with self.subTest(requirement=requirement):
                self.assertEqual(main.validate_package_spec(requirement), requirement)

    def test_rejects_unpinned_or_non_pypi_requirements(self):
        for requirement in (
            "requests",
            "requests>=2.0",
            "requests==1.2rc1",
            "git+https://example.test/project.git",
            "--index-url=https://example.test",
            "package @ https://example.test/package.whl",
        ):
            with self.subTest(requirement=requirement):
                with self.assertRaises(ValueError):
                    main.validate_package_spec(requirement)

    def test_package_install_is_enabled_only_for_loopback_hosts(self):
        self.assertTrue(main._is_loopback_host("127.0.0.1"))
        self.assertTrue(main._is_loopback_host("localhost"))
        self.assertFalse(main._is_loopback_host("0.0.0.0"))

    def test_install_uses_project_virtualenv_and_wheels_only(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="installed", stderr="")
        with (
            mock.patch.object(main, "_venv_python", return_value=Path(sys.executable)),
            mock.patch.object(main.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(main._install_package("demo==1.2"), (True, "installed"))

        command = run.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertIn("--only-binary=:all:", command)
        self.assertIn("https://pypi.org/simple", command)
        self.assertEqual(command[-1], "demo==1.2")
        self.assertNotIn("shell", run.call_args.kwargs)
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["PIP_CONFIG_FILE"], os.devnull)
        self.assertFalse(
            any(
                key.upper().startswith("PIP_")
                for key in environment
                if key != "PIP_CONFIG_FILE"
            )
        )


class PackageManifestTests(unittest.TestCase):
    def test_loads_and_validates_pinned_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "packages.yaml"
            manifest.write_text(
                "packages:\n"
                "  - name: requests\n"
                "    version: \"2.32.4\"\n",
                encoding="utf-8",
            )

            self.assertEqual(
                main.load_package_manifest(manifest),
                [
                    {
                        "name": "requests",
                        "version": "2.32.4",
                        "requirement": "requests==2.32.4",
                    }
                ],
            )

    def test_rejects_unpinned_or_duplicate_manifest_packages(self):
        for content in (
            "packages:\n  - name: requests\n    version: latest\n",
            "packages:\n  - name: requests\n    version: \"2.32\"\n"
            "  - name: REQUESTS\n    version: \"2.31\"\n",
            "packages: [requests==2.32.4]\n",
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                manifest = Path(directory) / "packages.yaml"
                manifest.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    main.load_package_manifest(manifest)


class PackageInstallApiTests(unittest.TestCase):
    def setUp(self):
        self.manifest_directory = tempfile.TemporaryDirectory()
        self.manifest_path = Path(self.manifest_directory.name) / "packages.yaml"
        self.manifest_path.write_text(
            "packages:\n"
            "  - name: demo\n"
            "    version: \"1.2\"\n",
            encoding="utf-8",
        )
        handler = main._request_handler(
            package_install_enabled=True,
            install_token="test-token",
            package_manifest_path=self.manifest_path,
        )
        self.server = main.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.manifest_directory.cleanup()

    def test_status_returns_token_for_local_install_ui(self):
        with mock.patch.object(main, "_venv_python", return_value=Path(sys.executable)):
            with urlopen(f"{self.url}/api/packages/status") as response:
                status = json.load(response)

        self.assertTrue(status["enabled"])
        self.assertEqual(status["token"], "test-token")

    def test_install_requires_token_before_calling_pip(self):
        request = Request(
            f"{self.url}/api/packages/install",
            data=json.dumps({"requirement": "demo==1.2"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(main, "_install_package") as install:
            with self.assertRaises(HTTPError) as error:
                urlopen(request)

        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        install.assert_not_called()

    def test_install_rejects_cross_origin_and_invalid_package(self):
        for headers, requirement, expected_status in (
            (
                {
                    "Content-Type": "application/json",
                    "X-PyCompiler-Install-Token": "test-token",
                    "Origin": "http://attacker.example",
                },
                "demo==1.2",
                403,
            ),
            (
                {
                    "Content-Type": "application/json",
                    "X-PyCompiler-Install-Token": "test-token",
                },
                "demo",
                400,
            ),
        ):
            request = Request(
                f"{self.url}/api/packages/install",
                data=json.dumps({"requirement": requirement}).encode(),
                headers=headers,
                method="POST",
            )
            with self.subTest(requirement=requirement), mock.patch.object(
                main, "_install_package"
            ) as install:
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, expected_status)
                error.exception.close()
                install.assert_not_called()

    def test_install_calls_package_installer_for_valid_request(self):
        request = Request(
            f"{self.url}/api/packages/install",
            data=json.dumps({"requirement": "demo==1.2"}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-PyCompiler-Install-Token": "test-token",
                "Origin": self.url,
            },
            method="POST",
        )
        with mock.patch.object(
            main, "_install_package", return_value=(True, "Successfully installed demo")
        ) as install:
            with urlopen(request) as response:
                result = json.load(response)

        self.assertTrue(result["ok"])
        install.assert_called_once_with("demo==1.2")

    def test_config_endpoint_requires_token_and_returns_manifest(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.url}/api/packages/config")
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

        request = Request(
            f"{self.url}/api/packages/config",
            headers={"X-PyCompiler-Install-Token": "test-token"},
        )
        with urlopen(request) as response:
            result = json.load(response)

        self.assertTrue(result["ok"])
        self.assertEqual(result["packages"][0]["requirement"], "demo==1.2")

    def test_install_config_installs_all_manifest_packages(self):
        request = Request(
            f"{self.url}/api/packages/install-config",
            headers={
                "X-PyCompiler-Install-Token": "test-token",
                "Origin": self.url,
            },
            method="POST",
        )
        with mock.patch.object(
            main, "_install_packages", return_value=(True, "Successfully installed demo")
        ) as install:
            with urlopen(request) as response:
                result = json.load(response)

        self.assertTrue(result["ok"])
        self.assertEqual(result["packages"][0]["requirement"], "demo==1.2")
        install.assert_called_once_with(["demo==1.2"])

    def test_install_config_rejects_invalid_manifest_without_pip(self):
        self.manifest_path.write_text(
            "packages:\n  - name: demo\n    version: latest\n",
            encoding="utf-8",
        )
        request = Request(
            f"{self.url}/api/packages/install-config",
            headers={"X-PyCompiler-Install-Token": "test-token"},
            method="POST",
        )
        with mock.patch.object(main, "_install_packages") as install:
            with self.assertRaises(HTTPError) as error:
                urlopen(request)

        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        install.assert_not_called()

    def test_local_status_does_not_disclose_configuration_to_nonlocal_host(self):
        request = Request(f"{self.url}/api/local/status", headers={"Host": "attacker.example"})
        with (
            mock.patch.object(main.program_store, "is_configured", return_value=True),
            mock.patch.object(
                main.github_repository,
                "configuration",
                return_value={"owner": "example", "repo": "private", "branch": "main"},
            ),
            urlopen(request) as response,
        ):
            status = json.load(response)

        self.assertFalse(status["enabled"])
        self.assertEqual(status["token"], "")
        self.assertFalse(status["database"]["configured"])
        self.assertIsNone(status["repository"])

    def test_program_api_requires_local_token(self):
        request = Request(
            f"{self.url}/api/programs",
            data=json.dumps(
                {
                    "name": "Demo",
                    "source_type": "pycompiler",
                    "source_code": "print(1)",
                    "target_language": "python",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(main.program_store, "create_program") as create:
            with self.assertRaises(HTTPError) as error:
                urlopen(request)

        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        create.assert_not_called()

    def test_program_api_creates_valid_program(self):
        payload = {
            "name": "Demo",
            "source_type": "pycompiler",
            "source_code": "print(1)",
            "target_language": "python",
            "generated_code": "print(1)",
        }
        stored_program = {"id": 7, **payload}
        request = Request(
            f"{self.url}/api/programs",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "X-PyCompiler-Local-Token": "test-token",
                "Origin": self.url,
            },
            method="POST",
        )
        with mock.patch.object(
            main.program_store, "create_program", return_value=stored_program
        ) as create:
            with urlopen(request) as response:
                result = json.load(response)
                self.assertEqual(response.status, 201)

        self.assertEqual(result["program"], stored_program)
        create.assert_called_once_with(payload)

    def test_program_api_reads_history_updates_and_deletes(self):
        stored_program = {
            "id": 8,
            "name": "Demo",
            "source_type": "pycompiler",
            "source_code": "print(2)",
            "target_language": "python",
            "generated_code": "print(2)",
        }
        headers = {"X-PyCompiler-Local-Token": "test-token"}
        with (
            mock.patch.object(
                main.program_store, "get_program", return_value=stored_program
            ) as get_program,
            urlopen(Request(f"{self.url}/api/programs/8", headers=headers)) as response,
        ):
            self.assertEqual(json.load(response)["program"], stored_program)
        get_program.assert_called_once_with(8)

        with (
            mock.patch.object(
                main.program_store, "list_history", return_value=[{"id": 3}]
            ) as list_history,
            urlopen(Request(f"{self.url}/api/programs/8/history", headers=headers)) as response,
        ):
            self.assertEqual(json.load(response)["history"], [{"id": 3}])
        list_history.assert_called_once_with(8)

        update_payload = {
            "name": "Updated",
            "source_type": "pycompiler",
            "source_code": "print(3)",
            "target_language": "python",
        }
        update_request = Request(
            f"{self.url}/api/programs/8",
            data=json.dumps(update_payload).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="PUT",
        )
        with mock.patch.object(
            main.program_store, "update_program", return_value=stored_program
        ) as update_program:
            with urlopen(update_request) as response:
                self.assertEqual(json.load(response)["program"], stored_program)
        update_program.assert_called_once_with(8, update_payload)

        delete_request = Request(
            f"{self.url}/api/programs/8",
            headers=headers,
            method="DELETE",
        )
        with mock.patch.object(main.program_store, "delete_program") as delete_program:
            with urlopen(delete_request) as response:
                self.assertEqual(response.status, 204)
        delete_program.assert_called_once_with(8)

    def test_repository_upload_uses_validated_files_and_local_token(self):
        payload = {
            "commit_message": "Add example",
            "files": [{"path": "examples/demo.pc", "content": "print(1)"}],
        }
        uploaded = {
            "commit_sha": "abc123",
            "commit_url": "https://github.com/example/repo/commit/abc123",
            "branch": "main",
            "files": ["examples/demo.pc"],
        }
        request = Request(
            f"{self.url}/api/repository/upload",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "X-PyCompiler-Local-Token": "test-token",
                "Origin": self.url,
            },
            method="POST",
        )
        with mock.patch.object(
            main.github_repository, "upload_files", return_value=uploaded
        ) as upload:
            with urlopen(request) as response:
                result = json.load(response)
                self.assertEqual(response.status, 201)

        self.assertEqual(result, {"ok": True, **uploaded})
        upload.assert_called_once_with("Add example", payload["files"])


if __name__ == "__main__":
    unittest.main()
