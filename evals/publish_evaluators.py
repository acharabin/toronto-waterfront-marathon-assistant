"""Publish native LangSmith LLM-as-a-judge evaluators and their prompts."""

import asyncio
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
import httpx
from langsmith import Client

# When run as ``python evals/publish_evaluators.py``, Python places the evals
# folder (rather than the project root) on sys.path. Add the root so the
# package imports work in both direct-file and ``python -m`` invocation modes.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evals.evaluators import (
    RESPONSE_GROUNDEDNESS_PROMPT_HANDLE,
    RESPONSE_GROUNDEDNESS_VARIABLE_MAPPING,
    RETRIEVAL_RELEVANCE_PROMPT_HANDLE,
    RETRIEVAL_RELEVANCE_VARIABLE_MAPPING,
    make_response_groundedness_prompt,
    make_retrieval_relevance_prompt,
)
from my_agent.config import load_project_config


load_dotenv(PROJECT_ROOT / ".env", override=False)
PROJECT_CONFIG = load_project_config()


async def publish_judges():
    """Push prompts, create/reuse native judges, and attach them to the project."""
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    tenant_id = (os.getenv("LANGSMITH_TENANT_ID") or os.getenv("LANGSMITH_WORKSPACE_ID") or "").strip()
    if not api_key and not tenant_id:
        raise RuntimeError(
            "LangSmith authentication is missing. Add LANGSMITH_API_KEY to the "
            "project .env file (and, if required by your workspace, set "
            "LANGSMITH_TENANT_ID or LANGSMITH_WORKSPACE_ID)."
        )

    project_name = (os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "").strip()
    if not project_name:
        raise RuntimeError(
            "The LangSmith tracing project is not configured. Set LANGSMITH_PROJECT "
            "in the project .env file to the project that should receive these evaluators."
        )

    client = Client(api_key=api_key or None, workspace_id=tenant_id or None)
    project = client.read_project(project_name=project_name)
    playground_settings_id = os.getenv("LANGSMITH_EVALUATOR_PLAYGROUND_SETTINGS_ID", "").strip()
    endpoint = (
        os.getenv("LANGSMITH_ENDPOINT")
        or os.getenv("LANGCHAIN_ENDPOINT")
        or PROJECT_CONFIG["urls"]["langsmith_api"]
    ).rstrip("/")
    evaluator_specs = [
        {
            "name": "Production Response Groundedness",
            "prompt_handle": RESPONSE_GROUNDEDNESS_PROMPT_HANDLE,
            "prompt": make_response_groundedness_prompt(),
            "variable_mapping": RESPONSE_GROUNDEDNESS_VARIABLE_MAPPING,
        },
        {
            "name": "Production Retrieval Relevance",
            "prompt_handle": RETRIEVAL_RELEVANCE_PROMPT_HANDLE,
            "prompt": make_retrieval_relevance_prompt(),
            "variable_mapping": RETRIEVAL_RELEVANCE_VARIABLE_MAPPING,
        },
    ]

    for spec in evaluator_specs:
        try:
            try:
                client.push_prompt(
                    spec["prompt_handle"],
                    object=spec["prompt"],
                    description=f"Structured judge prompt for {spec['name']}.",
                    commit_description="Managed by evals/publish_evaluators.py",
                )
            except Exception as error:
                if "nothing to commit" not in str(error).casefold():
                    raise
                print(f"Prompt '{spec['prompt_handle']}' is unchanged; continuing.")

            llm_evaluator = {
                "prompt_repo_handle": spec["prompt_handle"],
                "commit_hash_or_tag": "latest",
                "variable_mapping": spec["variable_mapping"],
            }
            if playground_settings_id:
                llm_evaluator["playground_settings_id"] = playground_settings_id

            evaluator = await _get_or_create_evaluator(client, spec["name"], llm_evaluator)
            await _attach_evaluator(
                client=client,
                evaluator=evaluator,
                evaluator_name=spec["name"],
                project=project,
                project_name=project_name,
                endpoint=endpoint,
                api_key=api_key,
                tenant_id=tenant_id,
            )
            print(f"Published and attached native LLM evaluator '{evaluator.name}'.")
            print(f"   -> Evaluator ID: {evaluator.id}")
            print(f"   -> Prompt handle: {spec['prompt_handle']}\n")
        except Exception as error:
            print(f"Failed to publish {spec['name']}: {error}")


async def _find_evaluators(client, name):
    matches = []
    async for evaluator in client.evaluators.list(name_contains=name, limit=100):
        if evaluator.name == name:
            matches.append(evaluator)
    return matches


async def _get_or_create_evaluator(client, name, llm_evaluator):
    """Reuse an existing native evaluator by name or create one."""
    matches = await _find_evaluators(client, name)
    native = next((item for item in matches if item.type == "llm"), None)
    if native is not None:
        updated = await client.evaluators.update(
            native.id,
            llm_evaluator=llm_evaluator,
        )
        return updated.evaluator

    # Evaluator type is immutable. If an older code evaluator has this name,
    # publish the native version with a clear suffix instead of colliding.
    target_name = f"{name} (Native LLM)" if matches else name
    native_matches = await _find_evaluators(client, target_name) if matches else []
    native = next((item for item in native_matches if item.type == "llm"), None)
    if native is not None:
        updated = await client.evaluators.update(
            native.id,
            llm_evaluator=llm_evaluator,
        )
        return updated.evaluator

    created = await client.evaluators.create(
        name=target_name,
        type="llm",
        llm_evaluator=llm_evaluator,
    )
    return created.evaluator


async def _attach_evaluator(
    *, client, evaluator, evaluator_name, project, project_name, endpoint, api_key, tenant_id
):
    """Create a 100% sampled project run rule unless it already exists."""
    async for current in client.evaluators.list(resource_id=[str(evaluator.id)], limit=100):
        for rule in current.run_rules or []:
            if str(rule.session_id) == str(project.id):
                print(f"   -> Already attached to project '{project_name}'.")
                return

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    if tenant_id:
        headers["x-tenant-id"] = tenant_id
    response = httpx.post(
        f"{endpoint}/api/v1/runs/rules",
        headers=headers,
        json={
            "display_name": f"{evaluator_name} - {project_name}",
            "session_id": str(project.id),
            "sampling_rate": 1.0,
            "evaluator_id": str(evaluator.id),
            "is_enabled": True,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    rule_id = response.json().get("id", "unknown")
    print(f"   -> Attached to project '{project_name}' (rule {rule_id}).")


if __name__ == "__main__":
    asyncio.run(publish_judges())
