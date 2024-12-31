# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

from logging import DEBUG, ERROR, INFO, WARNING, basicConfig, getLogger
from time import perf_counter

from .args import parse_args
from .page_explorer import PageExplorer

LOG = getLogger(__name__)
getLogger("selenium").setLevel(WARNING)
getLogger("urllib3").setLevel(ERROR)


def init_logging(level: str) -> None:
    """Initialize logging.

    Arguments:
        level: logging verbosity level

    Returns:
        None
    """
    mapping = {"DEBUG": DEBUG, "ERROR": ERROR, "INFO": INFO, "WARNING": WARNING}
    assert level in mapping
    if level == "DEBUG":
        log_fmt = "%(asctime)s.%(msecs)03d %(levelname).1s %(name)s | %(message)s"
    else:
        log_fmt = "[%(asctime)s] %(message)s"
    basicConfig(format=log_fmt, datefmt="%H:%M:%S", level=mapping[level])


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)
    init_logging(args.log_level)

    try:
        LOG.info("Starting Page Explorer...")
        with PageExplorer(args.binary.resolve(), port=args.port) as explorer:
            LOG.info("Loading %r...", args.url)
            start = perf_counter()
            success = explorer.get(args.url)
            LOG.info("Done. (%0.1fs)", perf_counter() - start)
            if not success:
                LOG.info("Load failed!")
            else:
                LOG.info("Exploring...")
                start = perf_counter()
                success = explorer.explore()
                LOG.info("Done. (%0.1fs)", perf_counter() - start)
                if not success:
                    LOG.info("Could not complete exploration!")
                else:
                    explorer.close_browser(wait=5)

    except KeyboardInterrupt:  # pragma: no cover
        LOG.warning("Aborting...")

    finally:
        LOG.warning("Shutting down...")

    return 0
