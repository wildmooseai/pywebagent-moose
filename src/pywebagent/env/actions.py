import time
import logging
from attr import dataclass
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


logger = logging.getLogger(__name__)


@dataclass
class EnvState:
    has_successfully_completed: bool = False
    has_failed: bool = False
    output: dict = {}
    timeframe: int = 0
    log_history: list[str] = []


class Actions:
    def __init__(self, page, marked_elements: list, env_state: EnvState) -> None:
        self.env_state = env_state
        self.page = page
        self.marked_elements = marked_elements

    def finish(self, did_succeed, output: dict, reason: str) -> None:
        self.env_state.has_successfully_completed = did_succeed
        self.env_state.has_failed = not did_succeed
        self.env_state.output = output

    def set_page(self, page):
        self.page = page

    def _visualized_interact(self, item_id: int, func: str, *args, **kwargs) -> None:
        """Mark element border with red and executes the given function."""
        if item_id not in self.marked_elements:
            raise Exception(f"Element with id {item_id} is not marked in the webpage.")
        element_info = self.marked_elements[item_id]
        xpath = element_info["xpath"]
        iframe = element_info["iframe"]
        element = iframe.evaluate_handle(
            f"document.evaluate('{xpath}', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue"
        )

        border = iframe.evaluate_handle(
            f"document.getElementById('item_id_border__{item_id}')"
        )
        label = iframe.evaluate_handle(
            f"document.getElementById('item_id_label__{item_id}')"
        )
        border.evaluate("(element) => element.style.borderColor = 'red'")
        label.evaluate("(element) => element.style.backgroundColor = 'red'")

        time.sleep(1)  # Wait a bit for the color change to be visible

        # Editable `div` with the `textbox` role (e.g., the Datadog Logs Search input)
        # can only by `type`-ed into, not `fill`-ed.
        if func == "fill" and element_info["tag"].lower() == "div":
            func = "type"

        element_func = getattr(element, func)
        assert element_func, f"Element with id {id} does not have a function {func}."
        element_func(*args, **kwargs)

        border.evaluate("(element) => element.style.borderColor = 'green'")
        label.evaluate("(element) => element.style.backgroundColor = 'green'")

        element.dispose()

    def click(self, item_id: int, log_message: str, force=False) -> None:
        """
        Attempts to click an element identified by `item_id`.
        Checks if a file chooser dialog opens as a result of the click, which is unexpected behavior.
        If the element is not clickable and `force` is False, retries with force click.
        """
        if log_message:
            self.env_state.log_history.append(log_message)
        try:
            inner_exception_raised = False
            with self.page.expect_file_chooser(timeout=1200):
                try:
                    self._visualized_interact(
                        item_id, "click", timeout=5000, force=force, no_wait_after=True
                    )
                except Exception as e_click:
                    inner_exception_raised = True
                    inner_exception = e_click

        except PlaywrightTimeoutError:
            if not inner_exception_raised:
                return  # Expected scenario: file chooser did not open.

            # Handle click-related exceptions.
            if inner_exception_raised:
                if self._is_unstable_element_exception(inner_exception) and not force:
                    return self.click(item_id, log_message="", force=True)
                elif self._is_context_destroyed_exception(inner_exception):
                    # The page likely navigated -- ignore that and move along.
                    self.page.reload()
                    return
                else:
                    raise inner_exception
        except Exception as e:
            assert (
                False
            ), f"Unexpected exception raised: {e}"  # Unexpected exception outside the file chooser context.

        raise Exception(
            "filechooser event was triggered unexpectedly. Consider using upload_files() instead of click() for this element."
        )

    def scroll(self, direction: str, log_message: str) -> None:
        self.env_state.log_history.append(log_message)
        if direction not in ["up", "down"]:
            raise Exception("direction must be either 'up' or 'down'")

        # Scroll by the height of the viewport for page down/up
        scroll_height = "window.innerHeight"  # Gets the height of the viewport

        if direction == "up":
            self.page.evaluate(f"window.scrollBy(0, -{scroll_height})")
        else:
            self.page.evaluate(f"window.scrollBy(0, {scroll_height})")

    def combobox_select(self, item_id: int, option: str, log_message: str) -> None:
        self.env_state.log_history.append(log_message)
        try:
            self._visualized_interact(item_id, "select_option", option)
        except Exception:
            # In many cases, stylised divs that resemble comboboxes can fool
            # the model into attempting to interact with them via `combobox_select`.
            # As a workaround, we attempt to `click` on such elements, in case the
            # prior attempt at `combobox_select` failed.
            self._visualized_interact(item_id, "click", timeout=1000, force=True)

    def input_text(
        self, item_id: int, text: str, clear_before_input: bool, log_message: str
    ):
        self.env_state.log_history.append(log_message)
        if clear_before_input:
            self._visualized_interact(item_id, "fill", text)
        else:
            self._visualized_interact(item_id, "type", text)

    def upload_files(self, item_id: int, files: list, log_message: str) -> None:
        self.env_state.log_history.append(log_message)
        try:
            with self.page.expect_file_chooser(timeout=2000) as file_chooser_info:
                successfully_clicked = False
                click_exception = None
                try:
                    self._visualized_interact(
                        item_id, "click", timeout=1000, force=False
                    )
                    successfully_clicked = True
                except Exception as e_click:
                    click_exception = e_click
                    if self._is_unstable_element_exception(e_click):
                        try:
                            self._visualized_interact(
                                item_id, "click", timeout=1000, force=True
                            )
                            successfully_clicked = True
                        except Exception as e_click_force:
                            click_exception = e_click_force
                            raise e_click_force
                    else:
                        raise e_click

                file_chooser = file_chooser_info.value
            file_chooser.set_files(files)
        except PlaywrightTimeoutError as e:
            if not successfully_clicked:
                raise click_exception
            else:
                raise e

    @staticmethod
    def _is_context_destroyed_exception(e):
        return "Execution context was destroyed" in str(e)

    @staticmethod
    def _is_unstable_element_exception(e):
        e_lines = str(e).split("\n")

        return (
            isinstance(e, PlaywrightTimeoutError)
            and ("element is not stable - waiting..." in e_lines[-2])
            and "==============" in e_lines[-1]
        )
