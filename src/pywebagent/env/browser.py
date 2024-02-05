import os
import traceback
import logging
import time
import numpy as np
import io
from urllib.parse import urlparse, urlunparse
from pathlib import Path
from PIL import Image
from dataclasses import dataclass
from typing import Any, Tuple, Dict, List, Callable
from playwright.sync_api import sync_playwright, Page
from pywebagent.env.actions import Actions, EnvState

logger = logging.getLogger(__name__)

JS_DIRECTORY = Path(os.path.dirname(os.path.realpath(__file__))) / "../js"

# Hueristic: The number of seconds we wait after any action has been performed
# in a given page. TODO: Figure out if there's a deterministic way to discover
# whether the given action (which is _not necessarily a navigation_) has already
# taken effect, rather than using a fixed 'delay'.
ACTION_EFFECT_DURATION = 1.5


class WebpageEmptyException(Exception):
    pass


@dataclass
class WebpageObservation:
    url: str
    error_message: str
    screenshot: bytes
    marked_elements: Dict[str, Any]
    additional_observations: Dict[str, str]
    env_state: EnvState = None


def _is_screenshot_empty(screenshot: bytes) -> bool:
    img = Image.open(io.BytesIO(screenshot))
    img = img.convert("RGBA")
    img_array = np.array(img)
    return np.min(img_array[:, :, :3]) == 255


class BrowserEnv:
    def __init__(
        self,
        headless: bool = True,
        actions: Actions = Actions,
        extra_observation_sources: List[Callable[[Page], Tuple[str, str]]] = [],
        detect_load_override: str = None,
        mark_borders_override: str = None,
    ):
        # headless = 'new' if headless else False TODO make this work
        self.actions = actions
        self.extra_observation_sources = extra_observation_sources
        self.detect_load_override = detect_load_override
        self.context_manager = sync_playwright()
        self.playwright = self.context_manager.__enter__()
        self.browser = self.playwright.chromium.launch(
            channel="chrome",
            headless=headless,
        )
        self.current_url = None

        with open(JS_DIRECTORY / "mark_borders.js", "r") as file:
            self._mark_elements_js_script = file.read()
        if mark_borders_override is not None:
            self._mark_elements_js_script = self._mark_elements_js_script.replace(
                "function isMarkableElementOverride(element) { return null; }",
                mark_borders_override,
            )
        with open(JS_DIRECTORY / "remove_mark_borders.js", "r") as file:
            self.remove_elements_marks_js_script = file.read()
        with open(JS_DIRECTORY / "override_file_chooser.js", "r") as file:
            self.override_file_chooser_js_script = file.read()

    def step(self, code: str, marked_elements: list = []) -> WebpageObservation:
        actions = self.actions(self.page, marked_elements, self.env_state)
        context = {"actions": actions}
        try:
            error_message = None
            logger.info(f"Executing code: {code}")
            exec(
                code, context, context
            )  # TODO: SCARY CODE-EXECUTION! PORT TO CAGED-MOOSE / OTHER SANDBOX.
        except Exception as e:
            # Extract exception line number and rethrow
            _, _, exc_tb = traceback.sys.exc_info()
            line_of_code = "N/A"
            while exc_tb is not None:
                frame = exc_tb.tb_frame
                lineno = exc_tb.tb_lineno
                if (
                    frame.f_code.co_name == "<module>"
                    and frame.f_code.co_filename == "<string>"
                ):
                    line_of_code = code.split("\n")[lineno - 1].lstrip()
                    break
                exc_tb = exc_tb.tb_next

            error_message = (
                f'Error in execution of script. At line: "{line_of_code}". Error: "{e}"'
            )
            logger.warning(error_message)
        finally:
            self._remove_elements_marks()

        time.sleep(ACTION_EFFECT_DURATION)

        # In case the action caused a navigation, wait (perhaps longer) for completion
        # Currently we detect a navigation by checking if the URL (sans query string) had changed.
        if urlunparse(urlparse(self.page.url)._replace(query="")) != urlunparse(
            urlparse(self.current_url)._replace(query="")
        ):
            self._wait_for_load()
            self.current_url = self.page.url

        self.env_state.timeframe += 1
        obs = self.get_observation()

        # If a new page was opened, switch to it
        if len(self.context.pages) > 1:
            self.page.close()
            self.page = self.context.pages[-1]
            self._wait_for_load()
            obs = self.get_observation()

        obs.error_message = error_message
        return obs

    def _wait_for_load(self):
        try:
            if self.detect_load_override is None:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            else:
                self.page.evaluate(self.detect_load_override)
        except Exception as e:
            logger.warning(f"Exception while waiting for load state: {e}")

    def _mark_elements(self):
        def run_script_in_frame(frame, counter, iframe_name=None):
            # Modify the script to start with the specific counter
            modified_script = self._mark_elements_js_script.replace(
                "let counter = 0;", f"let counter = {counter};"
            )

            try:
                elements = frame.evaluate(modified_script)
            except Exception as e:
                # log exception
                logger.warning(
                    f"Exception while running script in frame {iframe_name}: {e}"
                )
                elements = []

            # Add iframe origin information to each element
            for element in elements:
                element["iframe"] = frame
                element["iframe_name"] = iframe_name

            return elements

        counter = 0
        marked_elements = []
        for frame in self.page.frames:
            iframe_name = (
                frame.name or frame.url
            )  # Use the frame's name or URL as an identifier
            marked_elements_iframe = run_script_in_frame(
                frame, counter, iframe_name=iframe_name
            )
            marked_elements.extend(marked_elements_iframe)
            counter += len(marked_elements_iframe)

        marked_elements = {element["id"]: element for element in marked_elements}
        return marked_elements

    def _remove_elements_marks(self):
        for frame in self.page.frames:
            try:
                frame.evaluate(self.remove_elements_marks_js_script)
            except Exception as e:
                logger.warning(
                    f"Exception while running removal script in frame {frame.name}: {e}"
                )
                if "Target closed" in str(e):
                    return

    def get_observation(self) -> WebpageObservation:
        marked_elements = self._mark_elements()
        screenshot = self.page.screenshot()
        if len(screenshot) == 0 or _is_screenshot_empty(screenshot):
            raise WebpageEmptyException(
                "Screenshot is empty! Likely the webpage did not fully load."
            )

        return WebpageObservation(
            url=self.page.url,
            error_message=None,
            screenshot=screenshot,
            marked_elements=marked_elements,
            additional_observations=dict(
                [f(self.page) for f in self.extra_observation_sources]
            ),
            env_state=self.env_state,
        )

    def reset(
        self, url, cookies=[], init_scripts=[]
    ) -> Tuple[WebpageObservation, Dict[str, Any]]:
        geolocation = {"longitude": -122.417168, "latitude": 37.785834}  # USA
        self.context = self.browser.new_context(
            viewport={"width": 1600, "height": 900},
            storage_state=None,
            geolocation=geolocation,
            device_scale_factor=1,
        )
        self.context.add_cookies(cookies)
        self.page = self.context.new_page()

        #  Overrides the standard file picker function in the browser with a custom implementation
        # for file selection. This allows filechooser events to be triggered from the python code.
        self.page.add_init_script(self.override_file_chooser_js_script)

        # Registering auxiliary init scripts
        for script in init_scripts:
            self.page.add_init_script(script)

        # Navigating
        self.page.goto(url)
        logger.info("Waiting for page to load...")
        self._wait_for_load()
        logger.info("Page loaded")

        self.current_url = url
        self.env_state = EnvState()
        return self.get_observation()

    def close(self):
        self.context_manager.__exit__()
        self.browser.close()
