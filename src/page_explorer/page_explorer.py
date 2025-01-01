# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from enum import Enum, auto, unique
from logging import getLogger
from time import perf_counter, sleep
from typing import TYPE_CHECKING, Any, Callable, cast

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


@unique
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


DEFAULT_INSTRUCTIONS = (
    # wait for the page to load more content
    Instruction(Action.WAIT, value=10),
    # Find the end of the page/load more content
    Instruction(Action.SEND_KEYS, value=(Keys.END,), runs=5, delay=0.1),
    Instruction(Action.WAIT, value=1),
    # Attempt to trigger animations
    Instruction(Action.SEND_KEYS, value=(Keys.HOME,)),
    Instruction(Action.SEND_KEYS, value=(Keys.PAGE_DOWN,), runs=10, delay=0.2),
    Instruction(Action.SEND_KEYS, value=(Keys.PAGE_UP,), runs=10, delay=0.2),
    # Select some text
    Instruction(Action.SEND_KEYS, value=(Keys.HOME,)),
    Instruction(Action.KEY_DOWN, value=Keys.SHIFT),
    Instruction(Action.SEND_KEYS, value=(Keys.PAGE_DOWN,)),
    Instruction(Action.KEY_UP, value=Keys.SHIFT),
    Instruction(Action.SEND_KEYS, value=(Keys.HOME,)),
    Instruction(Action.WAIT, value=5),
    # Tab across elements
    Instruction(Action.SEND_KEYS, value=(Keys.TAB,), runs=25),
    Instruction(Action.WAIT, value=1),
    # Find all elements
    Instruction(Action.FIND_ELEMENTS, value={"by": By.XPATH, "value": ".//*"}),
    # Send ESC to some elements
    Instruction(Action.SEND_KEYS, value=(Keys.ESCAPE,), runs=25),
    # clear elements
    Instruction(Action.CLEAR_ELEMENTS),
    # Call GC
    Instruction(
        Action.EXECUTE_SCRIPT,
        value="try { FuzzingFunctions.memoryPressure() } catch(e) { }",
    ),
)


class PageExplorer:
    """PageExplorer enables page interactions via instructions."""

    __slots__ = ("_driver",)

    def __init__(self, binary: Path, port: int, implicitly_wait: float = 30):
        """
        Args:
            binary: Browser binary that is currently running.
            port: Listening browser control port to connect to.
            implicitly_wait: Maximum amount of time for Selenium commands to wait.
        """
        # Setup the options for connecting to an existing Firefox instance
        options = Options()
        options.binary_location = str(binary)
        options.enable_bidi = True
        service = Service(
            service_args=[f"--marionette-port={port}", "--connect-existing"],
        )
        try:
            self._driver = FirefoxDriver(options=options, service=service)
        except HTTPError:
            LOG.debug("suppressing HTTPError")
            raise ExplorerError("Failed to create PageExplorer") from None
        except WebDriverException as exc:
            LOG.error("Failed to create driver: %s", exc.msg)
            raise ExplorerError("Failed to create PageExplorer") from None
        LOG.debug("connected to browser on port: %d", port)
        try:
            self._driver.implicitly_wait(time_to_wait=implicitly_wait)
        except HTTPError:
            LOG.debug("suppressing HTTPError")
        except WebDriverException as exc:
            LOG.debug("no browser connection: %s", exc.msg)

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
        perform_wait = wait > 0
        LOG.debug("executing 'window.close()'")
        try:
            self._driver.execute_script(
                "window.close()"
            )  # type: ignore[no-untyped-call]
        except (HTTPError, WebDriverException):
            perform_wait = False
            LOG.debug("no browser connection")
        if perform_wait:
            deadline = perf_counter() + wait
            while deadline > perf_counter():
                try:
                    self._driver.title
                except (HTTPError, WebDriverException):
                    LOG.debug("connection has closed")
                    break
                sleep(poll)

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
                        instruction.value
                    )  # type: ignore[no-untyped-call]
                elif instruction.action == Action.FIND_ELEMENTS:
                    elements = self._driver.find_elements(
                        **cast(dict[str, str], instruction.value)
                    )
                    if not elements:
                        LOG.debug("no elements found!")
                elif instruction.action == Action.KEY_DOWN:
                    actions.key_down(cast(str, instruction.value)).perform()
                elif instruction.action == Action.KEY_UP:
                    actions.key_up(cast(str, instruction.value)).perform()
                elif instruction.action == Action.SEND_KEYS:
                    if elements is not None:
                        for element in elements:
                            with suppress(
                                ElementNotInteractableException,
                                StaleElementReferenceException,
                            ):
                                element.send_keys(
                                    *cast(tuple[str, ...], instruction.value)
                                )
                            if instruction.delay > 0:
                                wait_cb(instruction.delay)
                    else:
                        for _ in range(instruction.runs):
                            actions.send_keys(
                                *cast(tuple[str, ...], instruction.value)
                            ).perform()
                            if instruction.delay > 0:
                                wait_cb(instruction.delay)
                elif instruction.action == Action.WAIT:
                    wait_cb(cast(float, instruction.value))

            # all instructions complete
            success = True

        except HTTPError:
            LOG.debug("suppressing HTTPError")
        except WebDriverException as exc:
            LOG.debug("failed processing instructions: %s", exc.msg)
        finally:
            LOG.debug("%d/%d instructions", idx + 1, len(instructions))

        return success

    def get(self, url: str) -> bool:
        """Attempt to navigate to a provided URL.

        Args:
            url: URL to load.

        Returns:
            True if URL is successfully loaded otherwise False.
        """
        success = False
        try:
            self._driver.get(url)
            success = self._driver.title != "Server Not Found"
            LOG.debug("page: %r (%r)", self._driver.title, self._driver.current_url)
        except HTTPError:
            LOG.debug("suppressing HTTPError")
        except WebDriverException as exc:
            LOG.debug("no browser connection: %s", exc.msg)
        return success

    def shutdown(self) -> None:
        """Shutdown driver.

        Args:
            None

        Returns:
            None.
        """
        with suppress(HTTPError, WebDriverException):
            self._driver.quit()
