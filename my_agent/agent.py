"""Agent construction and project resource loading."""

from __future__ import annotations

import os
from pathlib import Path

from deepagents import create_deep_agent
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_openai.middleware import OpenAIModerationMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from sentence_transformers import SentenceTransformer

from .config import load_project_config, resolve_project_path
from .utils.data import load_runner_stats_with_embeddings
from .utils.middleware import IntegratedSafetyGuardrail
from .utils.tools import create_tools

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

def create_agent(data_path: str | Path | None = None):
    """Load the project resources and construct the Toronto Half Marathon agent."""
    load_dotenv(ENV_FILE, override=False)

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            f"OPENAI_API_KEY is not set. Add it to the shared environment file: {ENV_FILE}"
        )

    project_config = load_project_config()
    runner_data_path = resolve_project_path(
        data_path or project_config["paths"]["runner_results"]
    )
    if not runner_data_path.is_file():
        raise FileNotFoundError(f"Runner data file not found: {runner_data_path}")

    embedding_model = SentenceTransformer(os.getenv("RUNNER_EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    runner_stats = load_runner_stats_with_embeddings(runner_data_path, embedding_model)
    model = init_chat_model(os.getenv("AGENT_MODEL", "openai:gpt-4.1-mini"))
    tools = create_tools(runner_stats, embedding_model, model)
    instructions_path = resolve_project_path(project_config["paths"]["agent_instructions"])
    system_prompt = instructions_path.read_text(encoding="utf-8").replace(
        "{{MAIN_MARATHON_SITE_URL}}",
        project_config["urls"]["main_marathon_site"],
    )

    middleware = [
        OpenAIModerationMiddleware(
            model="omni-moderation-latest",
            check_input=True,
            check_output=True,
            exit_behavior="end",
        ),
        IntegratedSafetyGuardrail(),
    ]

    return create_deep_agent(
        model=model,
        name="toronto_half_marathon_agent",
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=InMemorySaver(),
        middleware=middleware,
    )
