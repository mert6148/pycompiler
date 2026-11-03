"""Upload explicitly selected text files as one GitHub repository commit."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


MAX_FILES = 50
MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 5_000_000
MAX_COMMIT_MESSAGE = 200
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_BLOCKED_SEGMENTS = {
    ".git",
    ".vs",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".aws",
    ".ssh",
    "id_rsa",
    "id_ed25519",
    ".git-credentials",
    ".npmrc",
    ".netrc",
    ".pypirc",
    "credentials.json",
    "service-account.json",
}
_BLOCKED_SUFFIXES = {".db", ".key", ".pem", ".p12", ".pfx", ".sqlite", ".sqlite3"}


class RepositoryNotConfigured(Exception):
    """Raised when the server-side GitHub credentials are missing."""


class RepositoryUploadError(Exception):
    """Raised when GitHub rejects or cannot process the requested commit."""


class UploadValidationError(ValueError):
    """Raised when an upload payload contains unsafe or invalid files."""


def _utf8_size(value: str, message: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise UploadValidationError(message) from error


def configuration(environ: dict[str, str] | None = None) -> dict[str, str] | None:
    environment = os.environ if environ is None else environ
    repository = environment.get("GITHUB_REPOSITORY", "").strip()
    owner, separator, name = repository.partition("/")
    token = environment.get("GITHUB_TOKEN", "").strip()
    branch = environment.get("GITHUB_BRANCH", "main").strip()
    if (
        not token
        or not separator
        or not _OWNER_RE.fullmatch(owner)
        or not _REPO_RE.fullmatch(name)
        or not _valid_branch(branch)
    ):
        return None
    return {"owner": owner, "repo": name, "branch": branch}


def _valid_branch(branch: str) -> bool:
    forbidden = set(" ~^:?*[\\")
    return bool(
        branch
        and len(branch) <= 200
        and not branch.startswith("/")
        and not branch.endswith("/")
        and "//" not in branch
        and ".." not in branch
        and "@{" not in branch
        and not any(ord(character) < 32 or character in forbidden for character in branch)
        and not branch.endswith(".")
        and not any(part.startswith(".") or part.endswith(".lock") for part in branch.split("/"))
    )


def validate_upload(payload: Any) -> tuple[str, list[dict[str, str]]]:
    if not isinstance(payload, dict) or set(payload) != {"commit_message", "files"}:
        raise UploadValidationError("İstekte yalnızca commit_message ve files alanları bulunmalıdır.")
    message = payload["commit_message"]
    files = payload["files"]
    if (
        not isinstance(message, str)
        or not 1 <= len(message.strip()) <= MAX_COMMIT_MESSAGE
    ):
        raise UploadValidationError("Commit mesajı 1-200 karakter olmalıdır.")
    _utf8_size(message, "Commit mesajı geçerli UTF-8 metin olmalıdır.")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise UploadValidationError(f"1-{MAX_FILES} arası dosya seçin.")

    validated: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    total_bytes = 0
    for index, file in enumerate(files, start=1):
        if not isinstance(file, dict) or set(file) != {"path", "content"}:
            raise UploadValidationError(f"{index}. dosyada yalnızca path ve content alanları bulunmalıdır.")
        path, content = file["path"], file["content"]
        if not isinstance(path, str) or not isinstance(content, str):
            raise UploadValidationError(f"{index}. dosyanın yolu ve içeriği metin olmalıdır.")
        if (
            not path
            or len(path) > 240
            or path.startswith("/")
            or "\\" in path
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
        ):
            raise UploadValidationError(f"{index}. dosyanın depo yolu geçersiz.")
        _utf8_size(path, f"{index}. dosyanın yolu geçerli UTF-8 metin olmalıdır.")
        segments = path.split("/")
        if any(segment in {"", ".", ".."} for segment in segments):
            raise UploadValidationError(f"{index}. dosya yolu depo dışına çıkamaz.")
        if any(
            segment.lower() in _BLOCKED_SEGMENTS
            or segment.lower().startswith(".env")
            or segment.lower().endswith(tuple(_BLOCKED_SUFFIXES))
            for segment in segments
        ):
            raise UploadValidationError(f"Güvenlik nedeniyle '{path}' yolu depoya yüklenemez.")
        normalized_path = path.casefold()
        if normalized_path in seen_paths:
            raise UploadValidationError(f"'{path}' yolu birden fazla seçilmiş.")
        seen_paths.add(normalized_path)

        encoded_content_size = _utf8_size(content, f"'{path}' geçerli UTF-8 metin olmalıdır.")
        if any(
            (ord(character) < 32 and character not in "\t\n\r")
            or ord(character) == 127
            for character in content
        ):
            raise UploadValidationError(f"'{path}' ikili içerik gibi görünüyor; yalnızca metin dosyaları yüklenebilir.")
        if encoded_content_size > MAX_FILE_BYTES:
            raise UploadValidationError(f"'{path}' dosyası 1 MB sınırını aşıyor.")
        total_bytes += encoded_content_size
        if total_bytes > MAX_TOTAL_BYTES:
            raise UploadValidationError("Toplam dosya boyutu 5 MB sınırını aşıyor.")
        validated.append({"path": path, "content": content})

    return message.strip(), validated


def _api_request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}/{path.lstrip('/')}",
        data=body,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "PyCompiler",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )
    try:
        with opener(request, timeout=15) as response:
            return json.loads(response.read())
    except HTTPError as error:
        try:
            response_body = json.loads(error.read(4096))
        except (json.JSONDecodeError, UnicodeDecodeError):
            response_body = {}
        detail = (
            response_body.get("message", "GitHub API isteği başarısız.")
            if isinstance(response_body, dict)
            else "GitHub API isteği başarısız."
        )
        raise RepositoryUploadError(f"GitHub HTTP {error.code}: {str(detail)[:300]}") from error
    except URLError as error:
        raise RepositoryUploadError("GitHub API'ye bağlanılamadı.") from error
    except (TimeoutError, OSError) as error:
        raise RepositoryUploadError("GitHub API'ye bağlanılamadı veya zaman aşımına uğradı.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RepositoryUploadError("GitHub API geçersiz JSON yanıtı verdi.") from error


def upload_files(
    commit_message: str,
    files: list[dict[str, str]],
    *,
    environ: dict[str, str] | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    settings = configuration(environ)
    if settings is None:
        raise RepositoryNotConfigured(
            "GITHUB_TOKEN ve geçerli GITHUB_REPOSITORY=owner/repo ayarlarını sunucu ortamında tanımlayın."
        )
    message, validated_files = validate_upload(
        {"commit_message": commit_message, "files": files}
    )
    environment = os.environ if environ is None else environ
    token = environment.get("GITHUB_TOKEN", "").strip()
    owner = quote(settings["owner"], safe="")
    repository = quote(settings["repo"], safe="")
    branch = quote(settings["branch"], safe="")
    base_url = f"https://api.github.com/repos/{owner}/{repository}"
    ref = _api_request(
        base_url,
        token,
        "GET",
        f"git/ref/heads/{branch}",
        opener=opener,
    )
    parent_sha = ref.get("object", {}).get("sha")
    if not isinstance(parent_sha, str):
        raise RepositoryUploadError("GitHub dalı için geçerli commit bulunamadı.")
    parent_commit = _api_request(
        base_url,
        token,
        "GET",
        f"git/commits/{quote(parent_sha, safe='')}",
        opener=opener,
    )
    base_tree = parent_commit.get("tree", {}).get("sha")
    if not isinstance(base_tree, str):
        raise RepositoryUploadError("GitHub dalının ağaç bilgisi alınamadı.")

    tree_entries = []
    for file in validated_files:
        blob = _api_request(
            base_url,
            token,
            "POST",
            "git/blobs",
            {
                "content": base64.b64encode(file["content"].encode("utf-8")).decode("ascii"),
                "encoding": "base64",
            },
            opener=opener,
        )
        blob_sha = blob.get("sha")
        if not isinstance(blob_sha, str):
            raise RepositoryUploadError(f"'{file['path']}' dosyası için GitHub blob oluşturamadı.")
        tree_entries.append(
            {"path": file["path"], "mode": "100644", "type": "blob", "sha": blob_sha}
        )

    tree = _api_request(
        base_url,
        token,
        "POST",
        "git/trees",
        {"base_tree": base_tree, "tree": tree_entries},
        opener=opener,
    )
    tree_sha = tree.get("sha")
    if not isinstance(tree_sha, str):
        raise RepositoryUploadError("GitHub dosya ağacı oluşturulamadı.")
    commit = _api_request(
        base_url,
        token,
        "POST",
        "git/commits",
        {"message": message, "tree": tree_sha, "parents": [parent_sha]},
        opener=opener,
    )
    commit_sha = commit.get("sha")
    if not isinstance(commit_sha, str):
        raise RepositoryUploadError("GitHub commit oluşturulamadı.")
    updated_ref = _api_request(
        base_url,
        token,
        "PATCH",
        f"git/refs/heads/{branch}",
        {"sha": commit_sha, "force": False},
        opener=opener,
    )
    return {
        "commit_sha": commit_sha,
        "commit_url": commit.get("html_url", ""),
        "branch": settings["branch"],
        "files": [file["path"] for file in validated_files],
        "updated_ref": updated_ref.get("ref", ""),
    }
