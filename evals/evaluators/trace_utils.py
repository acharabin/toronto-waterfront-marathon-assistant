"""Helpers for extracting evidence from a completed LangSmith trace."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit

from langsmith import Client


SCRAPE_TOOL_NAMES = {"scrape_article_text", "scrape_article_content"}


def field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _run_id(value: Any) -> str | None:
    run_id = field(value, "id")
    return str(run_id) if run_id is not None else None


def completed_trace_runs(root_run: Any) -> list[Any]:
    """Return the root and its children, fetching missing children from LangSmith."""
    found: dict[str, Any] = {}

    def add_tree(run: Any) -> None:
        run_id = _run_id(run)
        key = run_id or f"object-{len(found)}"
        if key in found:
            return
        found[key] = run
        for child in field(run, "child_runs", None) or []:
            add_tree(child)

    add_tree(root_run)

    trace_id = field(root_run, "trace_id") or field(root_run, "id")
    if trace_id:
        try:
            client = Client()
            for child in client.list_runs(trace_id=trace_id, is_root=False):
                child_id = _run_id(child)
                if child_id and child_id not in found:
                    found[child_id] = child
        except Exception:
            # Evaluators still work when the caller already supplied child runs.
            pass

    return list(found.values())


def _content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(text for item in value if (text := _content_text(item)))
    if isinstance(value, dict):
        for key in ("content", "text", "output", "answer", "response"):
            if key in value:
                text = _content_text(value[key])
                if text:
                    return text
        return "\n".join(
            text
            for item in value.values()
            if (text := _content_text(item))
        )
    content = getattr(value, "content", None)
    if content is not None:
        return _content_text(content)
    return str(value)


def _message_content(message: Any) -> str:
    content = field(message, "content")
    if content is None:
        data = field(message, "data", {}) or {}
        content = field(data, "content")
    return _content_text(content).strip()


def question_from_trace(root_run: Any) -> str:
    inputs = field(root_run, "inputs", {}) or {}
    if isinstance(inputs, dict):
        for key in ("question", "query", "user_input", "input"):
            if key in inputs:
                text = _content_text(inputs[key]).strip()
                if text:
                    return text
        messages = inputs.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                role = field(message, "role") or field(message, "type")
                if role in {"user", "human"}:
                    return _message_content(message)
    return ""


def _url_from_inputs(inputs: Any) -> str:
    if isinstance(inputs, dict):
        for key, value in inputs.items():
            if key.casefold() in {"url", "article_url"} and isinstance(value, str):
                return value
        for value in inputs.values():
            found = _url_from_inputs(value)
            if found:
                return found
    elif isinstance(inputs, list):
        for value in inputs:
            found = _url_from_inputs(value)
            if found:
                return found
    return ""


def _link_records(value: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            records.extend(_link_records(item))
    elif isinstance(value, dict):
        url = value.get("url")
        text = value.get("text") or value.get("title") or value.get("name")
        if isinstance(url, str) and isinstance(text, str):
            records.append({"url": url, "text": text})
        else:
            for item in value.values():
                records.extend(_link_records(item))
    return records


def _title_from_text(text: str) -> str:
    match = re.search(r"(?:^|\n)Title:\s*(.+)", text)
    return match.group(1).strip() if match else ""


def scraped_articles(root_run: Any) -> list[dict[str, str]]:
    runs = completed_trace_runs(root_run)
    search_links: list[dict[str, str]] = []
    for run in runs:
        name = str(field(run, "name", "")).casefold()
        if "search_for_articles" in name:
            search_links.extend(_link_records(field(run, "outputs", {})))

    articles = []
    for run in runs:
        name = str(field(run, "name", "")).casefold()
        if name not in SCRAPE_TOOL_NAMES:
            continue
        inputs = field(run, "inputs", {}) or {}
        outputs = field(run, "outputs", {}) or {}
        url = _url_from_inputs(inputs)
        content = _content_text(outputs).strip()
        title = _title_from_text(content)
        if not title and url:
            title = next((link["text"] for link in search_links if link["url"] == url), "")
        if not title and url:
            title = unquote(urlsplit(url).path.rstrip("/").split("/")[-1]).replace("-", " ")
        if content or title or url:
            articles.append({"title": title, "url": url, "content": content})
    return articles


def final_response_from_trace(root_run: Any) -> str:
    outputs = field(root_run, "outputs", {}) or {}
    if isinstance(outputs, dict):
        for key in ("answer", "response", "output"):
            if key in outputs and not isinstance(outputs[key], list):
                text = _content_text(outputs[key]).strip()
                if text:
                    return text
        messages = outputs.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                role = field(message, "role") or field(message, "type")
                if role in {"assistant", "ai"}:
                    text = _message_content(message)
                    if text:
                        return text
    return _content_text(outputs).strip()
