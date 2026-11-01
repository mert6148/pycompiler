"""Install Python packages into the environment running this script."""

import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install Python packages with the current interpreter's pip."
    )
    parser.add_argument(
        "packages",
        nargs="+",
        metavar="PACKAGE",
        help="package name or requirement, for example requests or flask==3.1.0",
    )
    args = parser.parse_args()

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", *args.packages],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
