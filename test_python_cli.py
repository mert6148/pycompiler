import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compiler
import main


class CompilerCliTests(unittest.TestCase):
    def test_invalid_utf8_source_has_a_clear_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "invalid.pc"
            source_path.write_bytes(b"print('\xff')")
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                result = compiler.main([str(source_path)])

        self.assertEqual(result, 1)
        self.assertIn("source file is not valid UTF-8 (byte 7)", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


class FrontendServerTests(unittest.TestCase):
    def test_open_browser_failure_is_reported_and_server_still_runs(self) -> None:
        server = unittest.mock.MagicMock()
        server.__enter__.return_value = server
        server_class = unittest.mock.MagicMock(return_value=server)
        output = io.StringIO()

        with (
            patch.object(main, "ThreadingHTTPServer", server_class),
            patch.object(main.webbrowser, "open", return_value=False),
            contextlib.redirect_stdout(output),
        ):
            result = main.main(["--port", "8123", "--open"])

        self.assertEqual(result, 0)
        server.serve_forever.assert_called_once_with()
        self.assertIn(
            "Could not open a browser. Visit http://127.0.0.1:8123/ manually.",
            output.getvalue(),
        )

    def test_browser_error_is_reported_and_server_still_runs(self) -> None:
        server = unittest.mock.MagicMock()
        server.__enter__.return_value = server
        server_class = unittest.mock.MagicMock(return_value=server)
        output = io.StringIO()

        with (
            patch.object(main, "ThreadingHTTPServer", server_class),
            patch.object(
                main.webbrowser,
                "open",
                side_effect=main.webbrowser.Error("unavailable"),
            ),
            contextlib.redirect_stdout(output),
        ):
            result = main.main(["--port", "8123", "--open"])

        self.assertEqual(result, 0)
        server.serve_forever.assert_called_once_with()
        self.assertIn("Could not open a browser: unavailable.", output.getvalue())

    def test_browser_os_error_is_reported_and_server_still_runs(self) -> None:
        server = unittest.mock.MagicMock()
        server.__enter__.return_value = server
        server_class = unittest.mock.MagicMock(return_value=server)
        output = io.StringIO()

        with (
            patch.object(main, "ThreadingHTTPServer", server_class),
            patch.object(main.webbrowser, "open", side_effect=OSError("launch failed")),
            contextlib.redirect_stdout(output),
        ):
            result = main.main(["--port", "8123", "--open"])

        self.assertEqual(result, 0)
        server.serve_forever.assert_called_once_with()
        self.assertIn("Could not open a browser: launch failed.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
