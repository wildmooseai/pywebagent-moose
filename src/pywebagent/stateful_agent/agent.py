import logging
from typing import List, Callable, Tuple
from playwright.sync_api import Page
from pywebagent.env.browser import BrowserEnv
from pywebagent.agent_common import (
    Task,
    TASK_STATUS,
    calculate_next_action,
    get_task_status,
)

logger = logging.getLogger(__name__)


class StatefulAgent(object):
    def __init__(
        self,
        headless,
        initial_url,
        actions,
        cookies=[],
        init_scripts=[],
        extra_observation_sources: List[Callable[[Page], Tuple[str, str]]] = [],
        detect_load_override: str = None,
        mark_borders_override: str = None,
    ):
        self.browser = BrowserEnv(
            headless=headless,
            actions=actions,
            extra_observation_sources=extra_observation_sources,
            detect_load_override=detect_load_override,
            mark_borders_override=mark_borders_override,
        )
        self.observation = self.browser.reset(
            initial_url, cookies=cookies, init_scripts=init_scripts
        )

    def act(self, task, max_actions=40, **kwargs):
        task = Task(task=task, args=kwargs)

        for i in range(max_actions):
            action = calculate_next_action(task, self.observation)
            self.observation = self.browser.step(
                action, self.observation.marked_elements
            )
            task_status = get_task_status(self.observation)
            if task_status in [TASK_STATUS.SUCCESS, TASK_STATUS.FAILED]:
                return task_status, self.observation.env_state.output

        logger.warning(f"Reached {i} actions without completing the task.")
        return TASK_STATUS.FAILED, self.observation.env_state.output

    def get_browser(self):
        return self.browser
