"""
Minimal example: call AproxPay tools directly, optionally run a Crew.

Usage:
  APROXPROXY_PRIVATE_KEY=0x... uv run python examples/crew_proxy_get.py

Optional Crew (needs an LLM key, e.g. OPENAI_API_KEY):
  RUN_CREW=1 APROXPROXY_PRIVATE_KEY=0x... OPENAI_API_KEY=sk-... \\
    uv run python examples/crew_proxy_get.py
"""

from __future__ import annotations

import os
import sys

from crewai_aproxpay import (
    AproxPayClient,
    AproxPayListCountriesTool,
    AproxPayProxyGetTool,
    create_aproxpay_tools,
)


def main() -> None:
    private_key = os.environ.get("APROXPROXY_PRIVATE_KEY")
    if not private_key:
        print("Set APROXPROXY_PRIVATE_KEY (0x… buyer wallet on Base).", file=sys.stderr)
        sys.exit(1)

    client = AproxPayClient(
        private_key=private_key,
        base_url=os.environ.get("APROXPROXY_BASE_URL"),
    )
    try:
        countries = AproxPayListCountriesTool(client=client).run()
        print("countries:", countries)

        result = AproxPayProxyGetTool(client=client).run(
            url="https://api.ipify.org?format=json",
            sticky=True,
        )
        print("proxy_get:", result)

        if os.environ.get("RUN_CREW") == "1":
            from crewai import Agent, Crew, Task

            tools = create_aproxpay_tools(client=client)
            agent = Agent(
                role="Researcher",
                goal="Fetch a public IP via residential proxy",
                backstory="Uses AproxPay for geo-aware HTTP fetches.",
                tools=tools,
                verbose=True,
            )
            task = Task(
                description=(
                    "Use aproxpay_proxy_get to fetch "
                    "https://api.ipify.org?format=json and report the IP."
                ),
                expected_output="The observed public IP address",
                agent=agent,
            )
            Crew(agents=[agent], tasks=[task]).kickoff()
    finally:
        client.close()


if __name__ == "__main__":
    main()
