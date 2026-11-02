"""Run the authentication API with Uvicorn."""

from __future__ import annotations

import argparse
import os
from typing import Sequence


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
        description="Run the PyCompiler authentication API."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=8001,
        help="HTTP port to use (default: 8001)",
    )
    arguments = parser.parse_args(argv)

    secret = os.environ.get("AUTH_SECRET", "")
    if len(secret) < 32:
        parser.error(
            "AUTH_SECRET must contain at least 32 characters; "
            "generate one with a cryptographically secure random generator"
        )

    try:
        import uvicorn
    except ImportError:
        parser.error(
            "authentication dependencies are missing; install them with "
            "'python -m pip install -r auth/requirements.txt'"
        )

    uvicorn.run(
        "auth.authserver_pro:app",
        host=arguments.host,
        port=arguments.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
