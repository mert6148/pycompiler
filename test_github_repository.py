import base64
import json
import unittest

import github_repository


class RepositoryValidationTests(unittest.TestCase):
    def test_rejects_unsafe_paths_and_duplicate_files(self):
        for path in (
            "../outside.txt",
            ".env",
            "venv/app.py",
            "private.key",
            "a\\b.txt",
            ".ssh/id_ed25519",
            "bad-\ud800.txt",
        ):
            with self.subTest(path=path), self.assertRaises(
                github_repository.UploadValidationError
            ):
                github_repository.validate_upload(
                    {"commit_message": "Add files", "files": [{"path": path, "content": "x"}]}
                )

        duplicate_files = [
            {"path": "src/App.py", "content": "a"},
            {"path": "src/app.py", "content": "b"},
        ]
        with self.assertRaises(github_repository.UploadValidationError):
            github_repository.validate_upload(
                {"commit_message": "Add files", "files": duplicate_files}
            )

    def test_enforces_file_count_and_payload_size_limits(self):
        too_many = [
            {"path": f"file-{index}.txt", "content": ""}
            for index in range(github_repository.MAX_FILES + 1)
        ]
        too_large = [{"path": "large.txt", "content": "x" * (github_repository.MAX_FILE_BYTES + 1)}]
        for files in (too_many, too_large):
            with self.subTest(count=len(files)), self.assertRaises(
                github_repository.UploadValidationError
            ):
                github_repository.validate_upload({"commit_message": "Add files", "files": files})

    def test_rejects_binary_content(self):
        with self.assertRaises(github_repository.UploadValidationError):
            github_repository.validate_upload(
                {
                    "commit_message": "Add files",
                    "files": [{"path": "image.bin", "content": "header\x00data"}],
                }
            )

    def test_rejects_invalid_unicode_content_and_commit_message(self):
        for payload in (
            {"commit_message": "\ud800", "files": [{"path": "ok.txt", "content": "text"}]},
            {"commit_message": "Add file", "files": [{"path": "ok.txt", "content": "\ud800"}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(
                github_repository.UploadValidationError
            ):
                github_repository.validate_upload(payload)


class RepositoryCommitTests(unittest.TestCase):
    def test_uploads_selected_files_as_one_non_force_commit(self):
        responses = [
            {"object": {"sha": "parent"}},
            {"tree": {"sha": "base-tree"}},
            {"sha": "blob-sha"},
            {"sha": "new-tree"},
            {"sha": "new-commit", "html_url": "https://github.com/acme/demo/commit/new-commit"},
            {"ref": "refs/heads/main"},
        ]
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return _FakeResponse(responses.pop(0))

        result = github_repository.upload_files(
            "Add selected file",
            [{"path": "examples/demo.txt", "content": "hello"}],
            environ={
                "GITHUB_TOKEN": "secret-token",
                "GITHUB_REPOSITORY": "acme/demo",
                "GITHUB_BRANCH": "main",
            },
            opener=opener,
        )

        self.assertEqual(result["commit_sha"], "new-commit")
        self.assertEqual(result["files"], ["examples/demo.txt"])
        self.assertEqual([request.method for request, _ in requests], [
            "GET", "GET", "POST", "POST", "POST", "PATCH"
        ])
        self.assertEqual([timeout for _, timeout in requests], [15] * 6)
        patch_payload = json.loads(requests[-1][0].data)
        self.assertFalse(patch_payload["force"])
        blob_payload = json.loads(requests[2][0].data)
        self.assertEqual(
            base64.b64decode(blob_payload["content"]).decode("utf-8"),
            "hello",
        )
        auth_headers = dict(requests[0][0].header_items())
        self.assertEqual(auth_headers["Authorization"], "Bearer secret-token")


class _FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self.body


if __name__ == "__main__":
    unittest.main()
