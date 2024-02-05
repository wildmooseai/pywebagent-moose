import datetime
import os
import pyotp
import logging
from typing import Tuple
from playwright.sync_api import Page
from pathlib import Path
from collections import namedtuple
from pywebagent.stateful_agent.agent import StatefulAgent
from pywebagent.agent_common import TASK_STATUS
from pywebagent.agents.datadog.actions import ActionsOverride

logger = logging.getLogger(__name__)

# Main Datadog domain (sans site specialisation)
DATADOG_DOMAIN = "datadoghq.com"

# Directory of the Datadog-specific user scripts.
JS_DIRECTORY = Path(os.path.dirname(os.path.realpath(__file__))) / "js"

# The maximum number of actions during the login flow.
MAX_LOGIN_ACTIONS = 10

DatadogAuth = namedtuple("DatadogAuth", ["user", "password", "totp_uri"])


# An observation source to indicate the current page title.
def extract_dd_page_title(page: Page) -> Tuple[str, str]:

    title_element = page.query_selector("header h2")
    return (
        "Page Title",
        title_element.text_content() if (title_element is not None) else "Unknown",
    )


class DatadogAgent(StatefulAgent):
    def __init__(self, headless: bool, auth: str | DatadogAuth, site: str = "us1"):
        self.site = site
        self.headless = headless
        self.dd_domain = (
            "app.datadoghq.com" if (site == "us1") else f"{site}.{DATADOG_DOMAIN}"
        )

        self._dd_init_scripts = []
        for init_script in (JS_DIRECTORY / "init_scripts").iterdir():
            with open(init_script, "r") as file:
                self._dd_init_scripts.append(file.read())

        with open(JS_DIRECTORY / "override" / "wait_for_load.js", "r") as file:
            self.detect_load_override = file.read()

        with open(JS_DIRECTORY / "override" / "mark_borders_override.js", "r") as file:
            self.mark_borders_override = file.read()

        # `dogweb` provided
        if isinstance(auth, str):
            self.dogweb = auth
        else:
            # Acquire dogweb using credentials
            self.auth = auth
            self.dogweb = self._log_in()

        super().__init__(
            headless=headless,
            initial_url=f"https://{self.dd_domain}",
            actions=ActionsOverride,
            cookies=[
                {
                    "name": "dogweb",
                    "value": self.dogweb,
                    "domain": self.dd_domain,
                    "path": "/",
                    "expires": (
                        datetime.datetime.now() + datetime.timedelta(weeks=1)
                    ).timestamp(),
                    "httpOnly": True,
                    "secure": True,
                }
            ],
            init_scripts=self._dd_init_scripts,
            extra_observation_sources=[extract_dd_page_title],
            detect_load_override=self.detect_load_override,
            mark_borders_override=self.mark_borders_override,
        )

    def _log_in(self) -> str:
        otp = pyotp.parse_uri(self.auth.totp_uri)

        login_agent = StatefulAgent(
            headless=self.headless,
            actions=ActionsOverride,
            initial_url=f"https://{self.dd_domain}/account/login",
            init_scripts=self._dd_init_scripts,
            extra_observation_sources=[extract_dd_page_title],
            detect_load_override=self.detect_load_override,
            mark_borders_override=self.mark_borders_override,
        )
        status, result = login_agent.act(
            task="Log in to DataDog using the given credentials. If you are asked for an OTP, finish with did_succeed=True.",
            args={
                "username": self.auth.user,
                "password": self.auth.password,
                "site": self.site,
            },
        )
        if status != TASK_STATUS.SUCCESS:
            raise Exception("Failed to log in: " + str(result))

        status, result = login_agent.act(
            task="Input the OTP code and log in.",
            args={
                "otp_code": otp.now(),
                "site": self.site,
            },
        )

        if status != TASK_STATUS.SUCCESS:
            raise Exception("Failed to log in: " + str(result))

        browser = login_agent.get_browser()
        browser.page.wait_for_load_state(state="networkidle", timeout=1000)

        dogweb = next(
            filter(
                lambda cookie: cookie["name"] == "dogweb", browser.context.cookies()
            ),
            None,
        )
        try:
            browser.close()
        except Exception as e:
            logger.warning(f"Failed to close browser during log-in flow: {str(e)}")
        return dogweb["value"]
