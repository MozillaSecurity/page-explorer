# type: ignore
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# pylint: disable=missing-docstring
from itertools import count, repeat
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
    with PageExplorer("bin", 1234):
        pass
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
    "title_effect, result",
    (
        # connected
        (("foo",), True),
        # not connected
        ((WebDriverException("test"),), False),
    ),
)
def test_page_explorer_is_connected(mocker, title_effect, result):
    """test PageExplorer.is_connected()"""
    driver = mocker.patch("page_explorer.page_explorer.FirefoxDriver", autospec=True)
    type(driver.return_value).title = mocker.PropertyMock(side_effect=title_effect)

    with PageExplorer("bin", 1234) as exp:
        assert exp.is_connected() == result


@mark.parametrize(
    "url_effect, result",
    (
        # connected
        (("foo",), "foo"),
        # not connected
        ((WebDriverException("test"),), None),
    ),
)
def test_page_explorer_current_url(mocker, url_effect, result):
    """test PageExplorer.current_url"""
    driver = mocker.patch("page_explorer.page_explorer.FirefoxDriver", autospec=True)
    type(driver.return_value).current_url = mocker.PropertyMock(side_effect=url_effect)

    with PageExplorer("bin", 1234) as exp:
        assert exp.current_url == result


@mark.parametrize(
    "title_calls, title_effect, script_effect",
    (
        # wait until deadline is exceeded
        (4, repeat("foo"), None),
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
        exp.close_browser(wait=5)
    assert driver.execute_script.call_count == 1
    assert fake_title.call_count == title_calls


@mark.parametrize(
    "get_effect, expected",
    (
        # successfully get a url
        (None, True),
        # get non-existing url
        ((WebDriverException("test"),), False),
        # browser connection error
        ((HTTPError(),), False),
    ),
)
def test_page_explorer_get(mocker, get_effect, expected):
    """test PageExplorer.get()"""
    driver = mocker.patch(
        "page_explorer.page_explorer.FirefoxDriver", autospec=True
    ).return_value

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


@mark.parametrize(
    "title_effect, result",
    (
        # connected
        (("foo",), "foo"),
        # not connected
        ((WebDriverException("test"),), None),
    ),
)
def test_page_explorer_title(mocker, title_effect, result):
    """test PageExplorer.title"""
    driver = mocker.patch("page_explorer.page_explorer.FirefoxDriver", autospec=True)
    type(driver.return_value).title = mocker.PropertyMock(side_effect=title_effect)

    with PageExplorer("bin", 1234) as exp:
        assert exp.title == result
