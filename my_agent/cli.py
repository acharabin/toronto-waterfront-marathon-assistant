"""Interactive command-line interface."""

import asyncio
from uuid import uuid4

from .agent import create_agent

async def ask() -> None:
    agent = create_agent()
    config = {"configurable": {"thread_id": str(uuid4())}}

    while True:
        try:
            user_input = input("User: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if user_input.casefold() in {"exit", "quit"}:
            return
        if not user_input:
            continue

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
        )
        last_message = result["messages"][-1]
        print(f"Agent: {last_message.content}")

def main() -> None:
    asyncio.run(ask())
