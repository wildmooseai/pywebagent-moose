import os
import logging
import argparse
from dotenv import load_dotenv
from pywebagent.agents.datadog.agent import DatadogAgent, DatadogAuth


def main():
    logging.basicConfig(level=logging.INFO)
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        description="Runs a simple DataDog agent with the given task."
    )

    parser.add_argument(
        "--mode",
        required=True,
        choices=["credentials", "cookie"],
        help='Mode can be "credentials" or "cookie"',
    )
    parser.add_argument(
        "--task",
        required=True,
        type=str,
        help="The task to perform",
    )

    args = parser.parse_args()

    if args.mode == "cookie":
        # Option 1: Use a pre-existing dogweb cookie.
        agent = DatadogAgent(headless=False, auth=os.getenv("DOGWEB"), site="us1")
    elif args.mode == "credentials":
        # Option 2: Perform the login-flow (for a 2FA enabled acount) to acquire a dogweb.
        agent = DatadogAgent(
            headless=False,
            auth=DatadogAuth(
                user=os.getenv("DD_USERNAME"),
                password=os.getenv("DD_PASSWORD"),
                totp_uri=os.getenv("DD_TOTP_URI"),
            ),
            site="us5",
        )

    status, result = agent.act(args.task)
    print(status, result)


if __name__ == "__main__":
    main()
