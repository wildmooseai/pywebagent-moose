from pywebagent.env.actions import Actions, EnvState


class ActionsOverride(Actions):
    def __init__(self, page, marked_elements: list, env_state: EnvState) -> None:
        super().__init__(
            page=page, marked_elements=marked_elements, env_state=env_state
        )

    def click(self, item_id: int, log_message: str, force=False) -> None:

        element_info = self.marked_elements[item_id]

        # Playwright fails to interactively interact with some DataDog form buttons.
        # For instance, the "Error", "Warn" and "Info" buttons under "Status" in Logs.
        # In such cases we invoke "click()" rather than interact via Playwright.
        if (
            element_info["class"].startswith("druids_form_action")
            and element_info["tag"].lower() == "button"
        ):
            self.page.evaluate(
                f"document.evaluate('{element_info['xpath']}', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue.click()"
            )
            return
        return super().click(item_id=item_id, log_message=log_message, force=force)
