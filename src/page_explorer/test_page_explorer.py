# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# pylint: disable=missing-docstring
from itertools import count
from unittest.mock import Mock

from pytest import mark, raises
from selenium.common.exceptions import WebDriverException
from urllib3.exceptions import HTTPError

from .page_explorer import (
    DEFAULT_INSTRUCTIONS,
    Action,
    ExplorerError,
    Instruction,
    PageExplorer,
)


@mark.parametrize("exc", (WebDriverException("test"), HTTPError()))
def test_page_explorer_create(mocker, exc):
    """test creating a PageExplorer object"""
    driver = mocker.patch("page_explorer.page_explorer.FirefoxDriver", autospec=True)

    # create a PageExplorer object
    # raise on call to implicitly_wait() for coverage
    driver.return_value.implicitly_wait.side_effect = (exc,)
    with PageExplorer("bin", 1234):
        assert driver.return_value.implicitly_wait.call_count == 1
    assert driver.return_value.quit.call_count == 1
    driver.reset_mock()

    # attempt create a PageExplorer object but fail to connect
    driver.side_effect = (exc,)
    with (
        raises(ExplorerError, match="Failed to create PageExplorer"),
        PageExplorer("bin", 1234),
    ):
        pass


@mark.parametrize(
    "title_calls, title_effect, script_effect",
    (
        # wait until deadline is exceeded
        (9, None, None),
        # successfully close the browser
        (1, (WebDriverException("test"),), None),
        # failed to send window.close()
        (0, (AssertionError("test failed"),), (WebDriverException("test"),)),
    ),
)
def test_page_explorer_close_browser(mocker, title_calls, title_effect, script_effect):
    """test PageExplorer.close_browser()"""
    mocker.patch("page_explorer.page_explorer.perf_counter", side_effect=count())
    mocker.patch("page_explorer.page_explorer.sleep", autospec=True)
    driver = mocker.patch(
        "page_explorer.page_explorer.FirefoxDriver", autospec=True
    ).return_value

    fake_title = mocker.PropertyMock(side_effect=title_effect)
    type(driver).title = fake_title
    driver.execute_script.side_effect = script_effect
    with PageExplorer("bin", 1234) as exp:
        exp.close_browser(wait=10)
    assert driver.execute_script.call_count == 1
    assert fake_title.call_count == title_calls


@mark.parametrize(
    "fake_title, get_effect, expected",
    (
        # successfully get a url
        ("foo", None, True),
        # get non-existing url
        ("Server Not Found", None, False),
        # get non-existing url
        ("foo", (WebDriverException("test"),), False),
        # browser connection error
        ("foo", (HTTPError(),), False),
    ),
)
def test_page_explorer_get(mocker, fake_title, get_effect, expected):
    """test PageExplorer.get()"""
    driver = mocker.patch(
        "page_explorer.page_explorer.FirefoxDriver", autospec=True
    ).return_value

    driver.title = fake_title
    driver.get.side_effect = get_effect
    with PageExplorer("bin", 1234) as exp:
        result = exp.get("http://foo.com")
    assert driver.get.call_count == 1
    assert result == expected


@mark.parametrize(
    "instructions, found_elements, expected",
    (
        # one instruction, multiple run
        (
            (Instruction(Action.SEND_KEYS, value=("m",), runs=10, delay=0.1),),
            None,
            True,
        ),
        # send multiple instructions
        (
            (
                Instruction(Action.SEND_KEYS, value=("A",)),
                Instruction(Action.SEND_KEYS, value=("B",)),
            ),
            None,
            True,
        ),
        # send key up and down
        (
            (
                Instruction(Action.KEY_DOWN, value="A"),
                Instruction(Action.KEY_UP, value="A"),
            ),
            None,
            True,
        ),
        # execute script
        ((Instruction(Action.EXECUTE_SCRIPT, value="foo()"),), None, True),
        # wait
        ((Instruction(Action.WAIT, value=1.0),), None, True),
        # find elements - no elements
        (
            (
                Instruction(
                    Action.FIND_ELEMENTS, value={"by": "xpath", "value": ".//*"}
                ),
            ),
            ([],),
            True,
        ),
        # find elements, send key to elements and clear elements
        (
            (
                Instruction(
                    Action.FIND_ELEMENTS, value={"by": "xpath", "value": ".//*"}
                ),
                Instruction(Action.SEND_KEYS, value=("a"), delay=0.1),
                Instruction(Action.CLEAR_ELEMENTS),
            ),
            ([Mock()],),
            True,
        ),
        # find elements, browser closed
        (
            (Instruction(Action.FIND_ELEMENTS, value={}),),
            (WebDriverException("test"),),
            False,
        ),
        # browser connection failed
        ((Instruction(Action.FIND_ELEMENTS, value={}),), (HTTPError(),), False),
        # DEFAULT_INSTRUCTIONS
        (DEFAULT_INSTRUCTIONS, ([Mock()],), True),
    ),
)
def test_page_explorer_explore(mocker, instructions, found_elements, expected):
    """test PageExplorer.explore()"""
    mocker.patch("page_explorer.page_explorer.ActionChains", autospec=True)
    driver = mocker.patch(
        "page_explorer.page_explorer.FirefoxDriver", autospec=True
    ).return_value
    driver.find_elements.side_effect = found_elements

    with PageExplorer("bin", 1234) as exp:
        result = exp.explore(instructions=instructions, wait_cb=mocker.MagicMock())
    assert result == expected
