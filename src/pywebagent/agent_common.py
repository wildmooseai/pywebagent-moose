import base64
import json
import logging
from enum import Enum
from pywebagent.env.browser import BrowserEnv
from langchain.schema import HumanMessage, SystemMessage

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


TASK_STATUS = Enum("TASK_STATUS", "IN_PROGRESS SUCCESS FAILED")


class Task:
    def __init__(self, task, args) -> None:
        self.task = task
        self.args = args


def get_llm():
    return ChatOpenAI(
        model_name="gpt-4-vision-preview",
        temperature=0.3,
        request_timeout=120,
        max_tokens=2000,
    )


def generate_user_message(task, observation):
    log_history = "\n".join(
        [f"- {log}" for log in observation.env_state.log_history]
        if observation.env_state.log_history
        else []
    )
    marked_elements_tags = ", ".join(
        [
            f"({str(i)}) - <{tag}> (Text Content: {text})"
            for i, tag, text in map(
                lambda X: (
                    X[0],
                    X[1]["tag"],
                    (
                        X[1]["textContent"][:20] + "..."
                        if len(X[1]["textContent"]) > 20
                        else X[1]["textContent"]
                    ),
                ),
                observation.marked_elements.items(),
            )
        ]
    )
    text_prompt = f"""
        Execution error:
        {observation.error_message}

        URL:
        {observation.url}

        Marked elements tags:
        {marked_elements_tags}

        Task:
        {task.task}

        Log of last actions:
        {log_history}

        Task Arguments:
        {json.dumps(task.args, indent=4)}
    """

    for title, content in observation.additional_observations.items():
        text_prompt += f"""
        {title}:
        {content}

        """

    screenshot_binary = observation.screenshot
    base64_image = base64.b64encode(screenshot_binary).decode("utf-8")
    image_content = {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{base64_image}",
            "detail": "high",  # low, high or auto
            # NOTE: On 'low' detail, the model appears incapable to read marked element digits.
        },
    }
    text_content = {"type": "text", "text": text_prompt}

    return HumanMessage(content=[text_content, image_content])


def generate_system_message():
    system_prompt = """
    You are an AI agent that controls a webpage using python code, in order to achieve a task.
    You are provided a screenshot of the webpage at each timeframe, and you decide on the next python line to execute.
    
    # Actions
    You can use any of the following functions:

    - actions.click(item_id: int, log_message: str) #Click on an element.

    - actions.input_text(item_id: int, text: str, clear_before_input: bool, log_message: str) #Use clear_before_input=True to replace the text instead of appending to it. Never use this method on a combobox.
    
    - actions.upload_files(item_id: int, files: list, log_message: str) # Use this instead of click if clicking is expected to open a file picker. 
    
    - actions.scroll(direction: Literal['up', 'down'], log_message: str) # Scrolls the page, either up or down.

    - actions.combobox_select(item_id: int, option: str, log_message: str) # Select an option from a combobox.
     
    - actions.finish(did_succeed: bool, output: dict, reason: str) # The task is complete with did_succeed=True or False, and a text reason. Output is an optional dictionary of output values if the task succeeded.
     
    Here are a few important guidelines that should always be followed:
    - The `item_id` is always an integer, and is visible as a green label with white number around the TOP-LEFT CORNER OF EACH ELEMENT. Make sure to examine all green highlighted elements before choosing one to interact with.
    - The `log_message` is a short one sentence explanation of what the action does. Make sure to be precise in your description. For instance, if you are opening a dropdown in order to later select an item titled "X", the log should read "Opening dropdown in order to select 'X'", rather than "Selecting 'X'" (that is, only describe the exact action being taken).
    - Do not use keyword arguments, all arguments are positional.
    - Do not forget to _complete_ an action that you have started undertaking. For example, if you had previously opened a drop-down list in order to click on an item, do not forget to click on the item!
    - IMPORTANT: ONLY ONE WEBPAGE FUNCTION CALL IS ALLOWED, EXCEPT FOR FORMS WHERE MULTIPLE CALLS ARE ALLOWED TO FILL MULTIPLE FIELDS! NOTHING IS ALLOWED AFTER THE "```" ENDING THE CODE BLOCK
    - IMPORTANT: LOOK FOR CUES IN THE SCREENSHOTS TO SEE WHAT PARTS OF THE TASK ARE COMPLETED AND WHAT PARTS ARE NOT. FOR EXAMPLE, IF YOU ARE ASKED TO BUY A PRODUCT, LOOK FOR CUES THAT THE PRODUCT IS IN THE CART.
    
    # Response Format

    Reasoning:
    Explanation for the next action, particularly focusing on interpreting the attached screenshot image.

    Code:
    ```python
    # variable definitions and non-webpage function calls are allowed
    ...
    # a single webpage function call.
    actions.func_name(args..)
    ```
    """
    return SystemMessage(content=system_prompt)


def extract_code(text):
    """
    Extracts all text in a string following the pattern "'\nCode:\n".
    """
    pattern = "\nCode:\n```python\n"
    start_index = text.find(pattern)

    # Fallback: the model sometimes omits the prefix.
    if start_index == -1:
        start_index = text.find("```python\n")

    if start_index == -1:
        raise Exception("Code not found")

    # Extract the text following the pattern, without the trailing "```"
    extracted_text = text[start_index + len(pattern) : -3]

    return extracted_text


def calculate_next_action(task, observation):
    llm = get_llm()

    system_message = generate_system_message()
    user_message = generate_user_message(task, observation)

    try:
        logger.debug("Sending request to OpenAI")
        ai_message = llm([system_message, user_message])
    except Exception:
        # This sometimes solves the RPM limit issue
        logger.warning("Failed to get response from OpenAI, trying again")
        ai_message = llm([system_message, user_message])

    logger.debug(f"AI message: {ai_message.content}")

    code_to_execute = extract_code(ai_message.content)

    return code_to_execute


def get_task_status(observation):
    if observation.env_state.has_successfully_completed:
        return TASK_STATUS.SUCCESS
    elif observation.env_state.has_failed:
        return TASK_STATUS.FAILED
    else:
        return TASK_STATUS.IN_PROGRESS


def act(url, task, max_actions=40, **kwargs):
    task = Task(task=task, args=kwargs)

    browser = BrowserEnv(headless=False)
    observation = browser.reset(url)

    for i in range(max_actions):
        action = calculate_next_action(task, observation)
        observation = browser.step(action, observation.marked_elements)
        task_status = get_task_status(observation)
        if task_status in [TASK_STATUS.SUCCESS, TASK_STATUS.FAILED]:
            return task_status, observation.env_state.output

    logger.warning(f"Reached {i} actions without completing the task.")
    return TASK_STATUS.FAILED, observation.env_state.output
