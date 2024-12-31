# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# pylint: disable=missing-docstring
from pytest import mark

from .main import init_logging, main


@mark.parametrize(
    "exp_get, exp_explore",
    (
        # navigating to page fails
        (False, False),
        # exploring page fails
        (True, False),
        # success, result found
        (True, True),
    ),
)
def test_main(mocker, exp_get, exp_explore):
    """test main()"""
    exp = mocker.patch(
        "page_explorer.main.PageExplorer", autospec=True
    ).return_value.__enter__.return_value
    exp.get.return_value = exp_get
    exp.explore.return_value = exp_explore
    assert main(["foo.bin", "http://test.url", "1234"]) == 0
    assert exp.get.call_count == 1
    assert exp.explore.call_count == (1 if exp_get else 0)


@mark.parametrize("level", ("DEBUG", "INFO"))
def test_init_logging(level):
    """test init_logging()"""
    init_logging(level=level)
