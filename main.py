"""PyCompiler Studio application entry point."""

from collections.abc import Sequence
import sys

from compiler import main as compiler_main


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the IDE by default, or pass explicit options to the compiler."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    return compiler_main(arguments or ["--ide"])


if __name__ == "__main__":
    raise SystemExit(main())
