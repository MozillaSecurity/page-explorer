# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from enum import Enum, auto
from logging import getLogger
from os import environ
from string import ascii_lowercase, ascii_uppercase
from time import perf_counter, sleep
from typing import TYPE_CHECKING, Any, Callable

from selenium.common.exceptions import (
    ElementNotInteractableException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver import Firefox as FirefoxDriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from urllib3.exceptions import HTTPError

if TYPE_CHECKING:
    from pathlib import Path

LOG = getLogger(__name__)
PAGE_LOAD_STRATEGIES = (
    # some content may still be loading (document.readyState="interactive")
    "eager",
    # does not block
    "none",
    # waits for all resources to download (document.readyState="complete")
    "normal",
)


class Action(Enum):
    """Supported actions that can be performed."""

    CLEAR_ELEMENTS = auto()
    EXECUTE_SCRIPT = auto()
    FIND_ELEMENTS = auto()
    KEY_DOWN = auto()
    KEY_UP = auto()
    SEND_KEYS = auto()
    WAIT = auto()


class ExplorerError(Exception):
    """Base exception used by this module."""


@dataclass(frozen=True, eq=False)
class Instruction:
    """Instruction to be executed."""

    action: Action
    delay: float = 0
    runs: int = 1
    value: Any = None


class PageLoad(Enum):
    """Page load result."""

    FAILURE = auto()
    SUCCESS = auto()
    TIMEOUT = auto()


DEFAULT_INSTRUCTIONS = (
    # Attempt to dismiss any potential overlay content
    Instruction(Action.SEND_KEYS, value=(Keys.ESCAPE,)),
    # Find the end of the page/load more content
    Instruction(Action.SEND_KEYS, value=(Keys.END,), runs=5, delay=0.1),
    Instruction(Action.WAIT, value=1),
    # Attempt to trigger animations
    Instruction(Action.SEND_KEYS, value=(Keys.HOME,)),
    Instruction(Action.SEND_KEYS, value=(Keys.PAGE_DOWN,), runs=10, delay=0.2),
    Instruction(Action.SEND_KEYS, value=(Keys.PAGE_UP,), runs=10, delay=0.1),
    Instruction(Action.WAIT, value=1),
    # Select some text
    Instruction(Action.SEND_KEYS, value=(Keys.HOME,)),
    Instruction(Action.KEY_DOWN, value=Keys.SHIFT),
    Instruction(Action.SEND_KEYS, value=(Keys.PAGE_DOWN,)),
    Instruction(Action.KEY_UP, value=Keys.SHIFT),
    Instruction(Action.SEND_KEYS, value=(Keys.HOME,)),
    Instruction(Action.WAIT, value=1),
    # Tab across elements
    Instruction(Action.SEND_KEYS, value=(Keys.TAB,), runs=25, delay=0.1),
    Instruction(Action.WAIT, value=1),
    # Zoom in/out
    Instruction(Action.SEND_KEYS, value=(Keys.HOME,)),
    Instruction(
        Action.EXECUTE_SCRIPT,
        value="try { document.body.style.zoom='150%' } catch(e) { }",
    ),
    Instruction(Action.WAIT, value=1),
    Instruction(
        Action.EXECUTE_SCRIPT,
        value="try { document.body.style.zoom='33%' } catch(e) { }",
    ),
    Instruction(Action.WAIT, value=1),
    Instruction(
        Action.EXECUTE_SCRIPT,
        value="try { document.body.style.zoom='100%' } catch(e) { }",
    ),
    # Call GC (requires fuzzing builds)
    Instruction(
        Action.EXECUTE_SCRIPT,
        value="try { FuzzingFunctions.memoryPressure() } catch(e) { }",
    ),
    Instruction(Action.WAIT, value=1),
)


class PageExplorer:
    """PageExplorer enables page interactions via instructions."""

    __slots__ = ("_driver",)

    def __init__(
        self, binary: Path, port: int, page_load_strategy: str = "normal"
    ) -> None:
        """
        Args:
            binary: Browser binary that is currently running.
            port: Listening browser control port to connect to.
            page_load_strategy: Wait for certain 'document.readyState' when loading.
        """
        assert page_load_strategy in PAGE_LOAD_STRATEGIES
        # disable data collection
        # https://www.selenium.dev/documentation/selenium_manager/#data-collection
        environ["SE_AVOID_STATS"] = "true"
        # Setup the options for connecting to an existing Firefox instance
        options = Options()
        options.binary_location = str(binary)
        options.page_load_strategy = page_load_strategy
        service = Service(
            service_args=[f"--marionette-port={port}", "--connect-existing"],
        )
        try:
            self._driver = FirefoxDriver(options=options, service=service)
        except HTTPError as exc:
            LOG.debug("suppressing HTTPError: %s", exc)
            raise ExplorerError("Failed to create PageExplorer") from None
        except WebDriverException as exc:
            LOG.error("Failed to create WebDriver: %s", exc.msg)
            raise ExplorerError("Failed to create PageExplorer") from None
        LOG.debug("connected to browser on port: %d", port)

    def __enter__(self) -> PageExplorer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def close_browser(self, wait: int = 0, poll: float = 0.5) -> None:
        """Attempt to execute 'window.close()' on the browser.

        Args:
            wait: Total amount of time to wait for browser to close.
            poll: Polling interval.

        Returns:
            None.
        """
        assert wait >= 0
        LOG.debug("executing 'window.close()'")
        try:
            self._driver.execute_script(
                "try { window.close() } catch(e) { }"  # type: ignore[no-untyped-call]
            )
        except (HTTPError, WebDriverException):
            LOG.debug("no browser connection")
        else:
            deadline = perf_counter() + wait
            while deadline > perf_counter() and self.is_connected():
                sleep(poll)

    @property
    def current_url(self) -> str | None:
        """Get the URL of the current page.

        Args:
            None

        Returns:
            The URL if it is available otherwise None.
        """
        with suppress(HTTPError, WebDriverException):
            return self._driver.current_url
        return None

    # pylint: disable=too-many-branches
    def explore(
        self,
        instructions: tuple[Instruction, ...] = DEFAULT_INSTRUCTIONS,
        wait_cb: Callable[[float], None] = sleep,
    ) -> bool:
        """Interact with active page by executing provided instructions.

        Args:
            instructions: Instructions to perform.
            wait_cb: Function used to delay execution.

        Returns:
            True if all instructions were successfully executed otherwise False.
        """
        idx = -1
        success = False
        elements = None

        LOG.debug("explore (instructions: %d)", len(instructions))
        # pylint: disable=too-many-nested-blocks
        try:
            actions = ActionChains(self._driver)
            for instruction in instructions:
                idx += 1
                if instruction.action == Action.CLEAR_ELEMENTS:
                    elements = None
                elif instruction.action == Action.EXECUTE_SCRIPT:
                    self._driver.execute_script(
                        instruction.value  # type: ignore[no-untyped-call]
                    )
                elif instruction.action == Action.FIND_ELEMENTS:
                    elements = self._driver.find_elements(**instruction.value)
                    if not elements:
                        LOG.debug("no elements found!")
                elif instruction.action == Action.KEY_DOWN:
                    actions.key_down(instruction.value).perform()
                elif instruction.action == Action.KEY_UP:
                    actions.key_up(instruction.value).perform()
                elif instruction.action == Action.SEND_KEYS:
                    if elements is not None:
                        for element in elements:
                            with suppress(
                                ElementNotInteractableException,
                                StaleElementReferenceException,
                            ):
                                element.send_keys(*instruction.value)
                            if instruction.delay > 0:
                                wait_cb(instruction.delay)
                    else:
                        for _ in range(instruction.runs):
                            actions.send_keys(*instruction.value).perform()
                            if instruction.delay > 0:
                                wait_cb(instruction.delay)
                elif instruction.action == Action.WAIT:
                    wait_cb(instruction.value)
            # all instructions complete
            success = True
        except HTTPError as exc:
            LOG.debug("explore - HTTPError: %s", exc)
        except WebDriverException as exc:
            LOG.debug("explore - WebDriverException: %s", exc.msg)
        finally:
            LOG.debug("%d/%d instructions executed", idx + 1, len(instructions))
        return success

    def get(self, url: str, wait: int = 90) -> PageLoad:
        """Attempt to navigate to a provided URL.
        NOTE: When the browser is very busy an HTTPError is raised after 120 seconds.

        Args:
            url: URL to load.

        Returns:
            True if URL is successfully loaded otherwise False.
        """
        try:
            if wait > 0:
                self._driver.set_page_load_timeout(wait)
            self._driver.get(url)
        except HTTPError as exc:
            LOG.debug("get - HTTPError: %s", exc)
            if "timed out" in str(exc):
                return PageLoad.TIMEOUT
        except WebDriverException as exc:
            if wait > 0 and "Navigation timed out after" in str(exc):
                return PageLoad.TIMEOUT
            LOG.debug("get - WebDriverException: %s", exc.msg)
        else:
            LOG.debug("load event received")
            return PageLoad.SUCCESS
        return PageLoad.FAILURE

    def is_connected(self) -> bool:
        """Check if a page is open and connection is active.

        Args:
            None

        Returns:
            True if a page is open and connection is active otherwise False.
        """
        with suppress(HTTPError, WebDriverException):
            return isinstance(self._driver.title, str)
        return False

    def shutdown(self) -> None:
        """Shutdown driver.

        Args:
            None

        Returns:
            None.
        """
        with suppress(HTTPError, WebDriverException):
            self._driver.quit()

    def skip_to_content(self) -> None:
        """Attempt to find and activate a "Skip to Content" link.
        This can dismiss some dialogs and scroll the page to the main content.

        https://webaim.org/ can be used to test the feature.

        Args:
            None

        Returns:
            None.
        """
        try:
            elements = self._driver.find_elements(
                by=By.XPATH,
                value=(
                    "//a[starts-with("
                    f"translate(text(), '{ascii_uppercase}', '{ascii_lowercase}'), "
                    "'skip to '"
                    ")]"
                ),
            )
            if not elements:
                LOG.debug("'skip to content' link not found")
                return
            actions = ActionChains(self._driver)
            # this can fail in some cases but seems to be required
            with suppress(WebDriverException):
                actions.scroll_to_element(elements[0]).perform()
                actions.move_to_element(elements[0]).perform()
                actions.click(elements[0])
            actions.send_keys(Keys.ENTER).perform()
        except HTTPError as exc:
            LOG.debug("skip_to_content - HTTPError: %s", exc)
        except WebDriverException as exc:
            LOG.debug("skip_to_content - WebDriverException: %s", exc.msg)

    @property
    def title(self) -> str | None:
        """Get the title of the current page.

        Args:
            None

        Returns:
            The page title if it is available otherwise None.
        """
        with suppress(HTTPError, WebDriverException):
            return self._driver.title
        return None
