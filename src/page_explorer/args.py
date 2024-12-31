# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

from argparse import ArgumentParser, Namespace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("page-explorer")
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    __version__ = "unknown"


def parse_args(argv: list[str] | None = None) -> Namespace:
    """Argument parsing"""
    parser = ArgumentParser(
        prog="page-explorer", description="Interact with web content."
    )
    parser.add_argument("binary", type=Path, help="Firefox binary in use.")
    parser.add_argument("url", help="URL to visit.")
    parser.add_argument("port", type=int, help="Browser listening port.")

    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "ERROR", "INFO", "WARNING"),
        default="INFO",
        help="Configure console output (default: %(default)s).",
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show version number.",
    )

    return parser.parse_args(argv)
