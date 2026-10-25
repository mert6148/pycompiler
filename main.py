"""Serve the PyCompiler Studio frontend using only the Python standard library."""

from __future__ import annotations

import argparse
import functools
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


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

    handler = functools.partial(
        SimpleHTTPRequestHandler,
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