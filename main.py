"""Serve the PyCompiler Studio frontend and its local package APIs."""

from __future__ import annotations

import argparse
import functools
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence
from urllib.parse import parse_qs, urlsplit

import github_repository
import program_store


PROJECT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_DIR / "app" / "frontend"
VENV_DIR = PROJECT_DIR / "venv"
LOGGER = logging.getLogger("pycompiler.server")
PACKAGE_SPEC_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?==[0-9]+(?:\.[0-9]+)*$"
)
PACKAGE_INSTALL_TIMEOUT = 300
PACKAGE_MANIFEST_PATH = PROJECT_DIR / "packages.yaml"
PACKAGE_MANIFEST_MAX_SIZE = 16 * 1024
PACKAGE_MANIFEST_MAX_PACKAGES = 50
PROGRAM_API_BODY_MAX_SIZE = 12_500_000
REPOSITORY_API_BODY_MAX_SIZE = 12_000_000
PROGRAM_ID_PATH = re.compile(r"^/api/programs/([1-9][0-9]*)(/history)?$")


def _venv_python() -> Path:
    """Return the Python executable inside the project virtual environment."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def validate_package_spec(requirement: str) -> str:
    """Accept only a PyPI project name with an exact numeric version."""
    if len(requirement) > 220 or not PACKAGE_SPEC_PATTERN.fullmatch(requirement):
        raise ValueError(
            "PyPI paket adını tam sayısal sürümle sabitleyin; "
            "örnek: requests==2.32.4."
        )
    return requirement


def _install_packages(requirements: Sequence[str]) -> tuple[bool, str]:
    """Install pinned PyPI packages as wheels into the project virtualenv."""
    python = _venv_python()
    if not python.is_file():
        raise FileNotFoundError(
            f"Proje sanal ortamı {VENV_DIR} konumunda bulunamadı. "
            "Şu komutla oluşturun: python -m venv venv"
        )

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PIP_")
    }
    environment["PIP_CONFIG_FILE"] = os.devnull
    completed = subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--isolated",
            "--disable-pip-version-check",
            "--index-url",
            "https://pypi.org/simple",
            "--no-input",
            "--only-binary=:all:",
            *requirements,
        ],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        env=environment,
        timeout=PACKAGE_INSTALL_TIMEOUT,
        check=False,
    )
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if completed.returncode:
        return False, output or f"pip exited with status {completed.returncode}."
    return True, output or f"Installed {', '.join(requirements)}."


def _install_package(requirement: str) -> tuple[bool, str]:
    """Install one pinned PyPI package into the project virtualenv."""
    return _install_packages([requirement])


def load_package_manifest(
    manifest_path: Path = PACKAGE_MANIFEST_PATH,
) -> list[dict[str, str]]:
    """Load and validate the pinned package list from a YAML manifest."""
    try:
        import yaml
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "YAML desteği için PyYAML gereklidir. "
            "python -m pip install -r requirements.txt komutunu çalıştırın."
        ) from error

    with manifest_path.open("rb") as manifest_file:
        content = manifest_file.read(PACKAGE_MANIFEST_MAX_SIZE + 1)
    if len(content) > PACKAGE_MANIFEST_MAX_SIZE:
        raise ValueError("Paket YAML dosyası 16 KiB sınırını aşamaz.")
    try:
        configuration = yaml.safe_load(content.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ValueError("Paket YAML dosyası UTF-8 kodlamalı olmalıdır.") from error
    except yaml.YAMLError as error:
        raise ValueError(f"Paket YAML dosyası geçersiz: {error}") from error

    if not isinstance(configuration, dict) or set(configuration) != {"packages"}:
        raise ValueError("YAML kökünde yalnızca 'packages' listesi bulunmalıdır.")
    packages = configuration["packages"]
    if not isinstance(packages, list):
        raise ValueError("'packages' bir liste olmalıdır.")
    if len(packages) > PACKAGE_MANIFEST_MAX_PACKAGES:
        raise ValueError(
            f"En fazla {PACKAGE_MANIFEST_MAX_PACKAGES} paket tanımlanabilir."
        )

    validated_packages = []
    seen_names = set()
    for index, package in enumerate(packages, start=1):
        if not isinstance(package, dict) or set(package) != {"name", "version"}:
            raise ValueError(
                f"'packages' öğesi {index}, yalnızca 'name' ve 'version' içermelidir."
            )
        name = package["name"]
        version = package["version"]
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError(f"'packages' öğesi {index}: ad ve sürüm metin olmalıdır.")
        requirement = validate_package_spec(f"{name}=={version}")
        normalized_name = name.lower().replace("_", "-").replace(".", "-")
        if normalized_name in seen_names:
            raise ValueError(f"'{name}' paketi manifestte birden fazla kez tanımlanmış.")
        seen_names.add(normalized_name)
        validated_packages.append(
            {"name": name, "version": version, "requirement": requirement}
        )
    return validated_packages


def _is_loopback_host(host: str) -> bool:
    """Return whether every address resolved for a host is loopback."""
    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError):
        return False
    return bool(addresses) and all(address.is_loopback for address in addresses)


def _request_handler(
    *,
    package_install_enabled: bool,
    install_token: str,
    package_manifest_path: Path = PACKAGE_MANIFEST_PATH,
    local_api_enabled: bool | None = None,
) -> type[SimpleHTTPRequestHandler]:
    """Create the static-file handler with local package, database, and GitHub APIs."""
    if local_api_enabled is None:
        local_api_enabled = package_install_enabled

    class RequestHandler(SimpleHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _is_local_request(self) -> bool:
            if not local_api_enabled:
                return False
            try:
                address = ipaddress.ip_address(self.client_address[0])
                host = urlsplit("//" + self.headers.get("Host", "")).hostname
                host_address = ipaddress.ip_address(host) if host else None
            except ValueError:
                return False
            if address.version == 6 and address.ipv4_mapped:
                address = address.ipv4_mapped
            valid_host = host == "localhost" or (
                host_address is not None and host_address.is_loopback
            )
            return address.is_loopback and valid_host

        def _authorize_local_api(self) -> bool:
            if not self._is_local_request():
                self._send_json(
                    403,
                    {"ok": False, "message": "Bu API yalnızca localhost üzerinden kullanılabilir."},
                )
                return False

            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if origin and not hmac.compare_digest(origin, f"http://{host}"):
                self._send_json(
                    403,
                    {"ok": False, "message": "Farklı kaynaktan gelen istek reddedildi."},
                )
                return False
            if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
                self._send_json(
                    403,
                    {"ok": False, "message": "Siteler arası istek reddedildi."},
                )
                return False
            if not hmac.compare_digest(
                self.headers.get("X-PyCompiler-Local-Token", ""),
                install_token,
            ):
                self._send_json(
                    403,
                    {"ok": False, "message": "Yerel API doğrulama anahtarı geçersiz."},
                )
                return False
            return True

        def _read_json(self, maximum: int) -> dict[str, object] | None:
            if self.headers.get_content_type() != "application/json":
                self._send_json(415, {"ok": False, "message": "JSON biçiminde istek gerekli."})
                return None
            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send_json(400, {"ok": False, "message": "İstek boyutu başlığı geçersiz."})
                return None
            if not 0 < content_length <= maximum:
                self._send_json(
                    413,
                    {"ok": False, "message": f"İstek gövdesi 1-{maximum} bayt olmalıdır."},
                )
                return None
            try:
                payload = json.loads(self.rfile.read(content_length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "message": "İstek gövdesi geçerli JSON değil."})
                return None
            if not isinstance(payload, dict):
                self._send_json(400, {"ok": False, "message": "JSON nesnesi gerekli."})
                return None
            return payload

        def _send_store_error(self, error: Exception) -> None:
            if isinstance(error, program_store.ProgramValidationError):
                self._send_json(400, {"ok": False, "message": str(error)})
            elif isinstance(error, program_store.ProgramNotFound):
                self._send_json(404, {"ok": False, "message": str(error)})
            elif isinstance(error, program_store.ProgramStoreError):
                LOGGER.warning("Program storage request failed: %s", error)
                self._send_json(503, {"ok": False, "message": str(error)})
            else:
                LOGGER.exception("Unexpected program storage error")
                self._send_json(500, {"ok": False, "message": "Program veritabanı isteği tamamlanamadı."})

        def _program_id(self, endpoint: str) -> tuple[int, bool] | None:
            match = PROGRAM_ID_PATH.fullmatch(endpoint)
            if not match:
                return None
            return int(match.group(1)), bool(match.group(2))

        def _local_status(self) -> None:
            enabled = self._is_local_request()
            self._send_json(
                200,
                {
                    "enabled": enabled,
                    "token": install_token if enabled else "",
                    "database": {
                        "configured": enabled and program_store.is_configured(),
                        "engine": "mysql",
                    },
                    "repository": github_repository.configuration() if enabled else None,
                },
            )

        def _authorize_package_request(self) -> bool:
            if not package_install_enabled:
                self._send_json(
                    403,
                    {"ok": False, "message": "Bu sunucu adresinde paket kurulumu devre dışıdır."},
                )
                return False

            origin = self.headers.get("Origin")
            if origin:
                expected_origin = f"http://{self.headers.get('Host', '')}"
                if not hmac.compare_digest(origin, expected_origin):
                    self._send_json(
                        403,
                        {"ok": False, "message": "Farklı kaynaktan gelen istek reddedildi."},
                    )
                    return False

            if not hmac.compare_digest(
                self.headers.get("X-PyCompiler-Install-Token", ""),
                install_token,
            ):
                self._send_json(
                    403,
                    {"ok": False, "message": "Kurulum doğrulama anahtarı geçersiz."},
                )
                return False
            return True

        def do_GET(self) -> None:
            parsed_path = urlsplit(self.path)
            endpoint = parsed_path.path
            if endpoint == "/api/local/status":
                self._local_status()
                return
            if endpoint == "/api/programs":
                if not self._authorize_local_api():
                    return
                query = parse_qs(parsed_path.query, strict_parsing=False)
                try:
                    limit = int(query.get("limit", ["50"])[0])
                    offset = int(query.get("offset", ["0"])[0])
                    programs = program_store.list_programs(limit=limit, offset=offset)
                except ValueError as error:
                    self._send_json(400, {"ok": False, "message": "limit ve offset sayı olmalıdır."})
                    return
                except Exception as error:
                    self._send_store_error(error)
                    return
                self._send_json(200, {"ok": True, "programs": programs})
                return
            program_route = self._program_id(endpoint)
            if program_route:
                if not self._authorize_local_api():
                    return
                program_id, history = program_route
                try:
                    if history:
                        result = program_store.list_history(program_id)
                    else:
                        result = program_store.get_program(program_id)
                except Exception as error:
                    self._send_store_error(error)
                    return
                self._send_json(
                    200,
                    {"ok": True, "history": result} if history else {"ok": True, "program": result},
                )
                return
            if endpoint == "/api/packages/status":
                python = _venv_python()
                enabled = package_install_enabled and python.is_file()
                try:
                    python_display_path = python.relative_to(PROJECT_DIR)
                except ValueError:
                    python_display_path = python
                message = ""
                if not package_install_enabled:
                    message = "Uzak ağ arayüzlerinde paket kurulumu devre dışıdır."
                elif not python.is_file():
                    message = (
                        f"Proje sanal ortamı {VENV_DIR} konumunda bulunamadı. "
                        "Şu komutla oluşturun: python -m venv venv"
                    )
                self._send_json(
                    200,
                    {
                        "enabled": enabled,
                        "message": message,
                        "python": str(python_display_path),
                        "token": install_token if enabled else "",
                    },
                )
                return
            if endpoint == "/api/packages/config":
                if not self._authorize_package_request():
                    return
                try:
                    packages = load_package_manifest(package_manifest_path)
                except FileNotFoundError as error:
                    self._send_json(404, {"ok": False, "message": str(error)})
                    return
                except RuntimeError as error:
                    self._send_json(503, {"ok": False, "message": str(error)})
                    return
                except ValueError as error:
                    self._send_json(400, {"ok": False, "message": str(error)})
                    return
                except OSError as error:
                    self._send_json(
                        500,
                        {"ok": False, "message": f"YAML dosyası okunamadı: {error}"},
                    )
                    return
                self._send_json(200, {"ok": True, "packages": packages})
                return
            super().do_GET()

        def do_POST(self) -> None:
            endpoint = urlsplit(self.path).path
            if endpoint == "/api/programs":
                if not self._authorize_local_api():
                    return
                payload = self._read_json(PROGRAM_API_BODY_MAX_SIZE)
                if payload is None:
                    return
                try:
                    program = program_store.create_program(payload)
                except Exception as error:
                    self._send_store_error(error)
                    return
                self._send_json(201, {"ok": True, "program": program})
                return
            if endpoint == "/api/repository/upload":
                if not self._authorize_local_api():
                    return
                payload = self._read_json(REPOSITORY_API_BODY_MAX_SIZE)
                if payload is None:
                    return
                try:
                    message, files = github_repository.validate_upload(payload)
                    result = github_repository.upload_files(message, files)
                except github_repository.UploadValidationError as error:
                    self._send_json(400, {"ok": False, "message": str(error)})
                    return
                except github_repository.RepositoryNotConfigured as error:
                    self._send_json(503, {"ok": False, "message": str(error)})
                    return
                except github_repository.RepositoryUploadError as error:
                    LOGGER.warning("GitHub upload request failed: %s", error)
                    status = 409 if "HTTP 409" in str(error) else 502
                    self._send_json(status, {"ok": False, "message": str(error)})
                    return
                self._send_json(201, {"ok": True, **result})
                return
            if endpoint not in ("/api/packages/install", "/api/packages/install-config"):
                self.send_error(404, "Not found")
                return
            if not self._authorize_package_request():
                return

            if endpoint == "/api/packages/install-config":
                try:
                    packages = load_package_manifest(package_manifest_path)
                    if not packages:
                        raise ValueError("'packages' listesi boş; kurulacak paket yok.")
                except FileNotFoundError as error:
                    self._send_json(404, {"ok": False, "message": str(error)})
                    return
                except RuntimeError as error:
                    self._send_json(503, {"ok": False, "message": str(error)})
                    return
                except ValueError as error:
                    self._send_json(400, {"ok": False, "message": str(error)})
                    return
                except OSError as error:
                    self._send_json(
                        500,
                        {"ok": False, "message": f"YAML dosyası okunamadı: {error}"},
                    )
                    return

                try:
                    success, output = _install_packages(
                        [package["requirement"] for package in packages]
                    )
                except FileNotFoundError as error:
                    self._send_json(503, {"ok": False, "message": str(error)})
                    return
                except subprocess.TimeoutExpired:
                    self._send_json(
                        504,
                        {
                            "ok": False,
                            "message": f"Paket kurulumu {PACKAGE_INSTALL_TIMEOUT} saniyede tamamlanamadı.",
                        },
                    )
                    return
                except OSError as error:
                    self._send_json(500, {"ok": False, "message": f"pip başlatılamadı: {error}"})
                    return

                self._send_json(
                    200 if success else 500,
                    {
                        "ok": success,
                        "packages": packages,
                        "message": output[-12000:],
                    },
                )
                return

            if self.headers.get_content_type() != "application/json":
                self._send_json(415, {"ok": False, "message": "JSON biçiminde istek gerekli."})
                return

            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send_json(400, {"ok": False, "message": "İstek boyutu başlığı geçersiz."})
                return
            if not 0 < content_length <= 2048:
                self._send_json(413, {"ok": False, "message": "İstek gövdesi boş veya çok büyük."})
                return

            try:
                payload = json.loads(self.rfile.read(content_length))
                if not isinstance(payload, dict) or set(payload) != {"requirement"}:
                    raise ValueError("İstekte yalnızca 'requirement' alanı bulunmalı.")
                requirement = payload["requirement"]
                if not isinstance(requirement, str):
                    raise ValueError("Paket isteği metin olmalı.")
                validate_package_spec(requirement)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                self._send_json(400, {"ok": False, "message": str(error)})
                return

            try:
                success, output = _install_package(requirement)
            except FileNotFoundError as error:
                self._send_json(503, {"ok": False, "message": str(error)})
                return
            except subprocess.TimeoutExpired:
                self._send_json(
                    504,
                    {
                        "ok": False,
                        "message": f"Paket kurulumu {PACKAGE_INSTALL_TIMEOUT} saniyede tamamlanamadı.",
                    },
                )
                return
            except OSError as error:
                self._send_json(500, {"ok": False, "message": f"pip başlatılamadı: {error}"})
                return

            self._send_json(
                200 if success else 500,
                {"ok": success, "message": output[-12000:]},
            )

        def do_PUT(self) -> None:
            endpoint = urlsplit(self.path).path
            route = self._program_id(endpoint)
            if route is None or route[1]:
                self.send_error(404, "Not found")
                return
            if not self._authorize_local_api():
                return
            payload = self._read_json(PROGRAM_API_BODY_MAX_SIZE)
            if payload is None:
                return
            try:
                program = program_store.update_program(route[0], payload)
            except Exception as error:
                self._send_store_error(error)
                return
            self._send_json(200, {"ok": True, "program": program})

        def do_DELETE(self) -> None:
            endpoint = urlsplit(self.path).path
            route = self._program_id(endpoint)
            if route is None or route[1]:
                self.send_error(404, "Not found")
                return
            if not self._authorize_local_api():
                return
            try:
                program_store.delete_program(route[0])
            except Exception as error:
                self._send_store_error(error)
                return
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

    return RequestHandler


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve the PyCompiler Studio frontend on your local machine."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=8000,
        help="HTTP port to use (default: 8000)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="open the local page in your default browser",
    )
    arguments = parser.parse_args(argv)

    if not FRONTEND_DIR.is_dir():
        parser.error(f"frontend directory not found: {FRONTEND_DIR}")

    install_token = secrets.token_urlsafe(32)
    handler = functools.partial(
        _request_handler(
            package_install_enabled=_is_loopback_host(arguments.host),
            install_token=install_token,
        ),
        directory=str(FRONTEND_DIR),
    )
    try:
        with ThreadingHTTPServer((arguments.host, arguments.port), handler) as server:
            url = f"http://{arguments.host}:{arguments.port}/"
            print(f"PyCompiler Studio is running at {url} (press Ctrl+C to stop)")
            if arguments.open_browser:
                webbrowser.open(url)
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nPyCompiler Studio stopped.")
    except OSError as error:
        parser.error(f"could not start server: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())