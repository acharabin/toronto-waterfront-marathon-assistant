"""Tools exposed by the Toronto Waterfront Half Marathon agent."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit

import polars as pl
from langchain.tools import tool
from playwright.sync_api import Error as PlaywrightError, sync_playwright
from sentence_transformers import util

from ..config import load_project_config
from .state import RunnerIDType, SearchQueryVariants


_PROJECT_CONFIG = load_project_config()
SEARCH_URL = _PROJECT_CONFIG["urls"]["marathon_search"]
SITE_HOST = urlsplit(SEARCH_URL).hostname


def _search_unavailable(reason: str) -> str:
    return (
        "Article search could not be completed. Ask the user to open the root search URL manually "
        f"and verify that help-center article search is still supported: {SEARCH_URL} "
        "If the root URL has changed, ask them to update urls.marathon_search in config.toml "
        "and restart the application. "
        f"Details: {reason}"
    )


def create_tools(runner_stats: pl.DataFrame, embedding_model: Any, model: Any) -> list[Any]:
    """Bind data/model dependencies and return the tools for ``create_deep_agent``."""

    @tool
    def find_closest_matching_runner_names(names: list[str], top_k: int = 3) -> list[dict[str, Any]] | str:
        """Find likely result-table matches for each supplied runner name."""
        if not names:
            return "Error: provide at least one runner name"
        if len(names) > 100:
            return "Error: only up to 100 runner names are accepted"
        if any(not name.strip() for name in names):
            return "Error: each name must contain a non-space character"

        top_k = max(1, min(top_k, 10))
        corpus_embeddings = runner_stats["name_embedding"].to_torch()
        matches = []
        for name in names:
            query_embedding = embedding_model.encode(name, convert_to_tensor=True)
            hits = util.semantic_search(query_embedding, corpus_embeddings, top_k=top_k)[0]
            candidates = [
                {
                    "name": runner_stats["name"][int(hit["corpus_id"])],
                    "score": float(hit["score"]),
                }
                for hit in hits
            ]
            matches.append({"input_name": name, "candidates": candidates})
        return matches

    @tool
    def find_runner_name_by_id(ids: list[int], runner_id_type: RunnerIDType) -> dict[str, Any] | str:
        """Identify runner based on the bib_number or their place. Up to 100 input IDs supported."""
        if not ids:
            return "Error: provide at least one ID"
        if len(ids) > 100:
            return "Error: only up to 100 IDs are accepted"

        id_column = runner_id_type.value
        found = runner_stats.filter(pl.col(id_column).cast(pl.Int64).is_in(ids))
        found_ids = set(found[id_column].cast(pl.Int64).to_list())
        return {
            "matches": found.select("name", "place", "bib_number").to_dicts(),
            "not_found": [runner_id for runner_id in ids if runner_id not in found_ids],
        }

    @tool
    def get_runner_stats(names: list[str]) -> list[dict[str, Any]] | str:
        """Return result rows for exact runner names confirmed by the user or a prior match."""
        if not names:
            return "Error: provide at least one confirmed runner name"
        if len(names) > 100:
            return "Error: only up to 100 runner names are accepted"
        corpus_names = set(runner_stats["name"].to_list())
        invalid_names = [name for name in names if name not in corpus_names]
        if invalid_names:
            return f"Error: these names are not exact result-table names: {invalid_names}"
        return (
            runner_stats
            .filter(pl.col("name").is_in(names))
            .drop("name_embedding", "corpus_id")
            .to_dicts()
        )

    @tool
    def rewrite_search_queries(query: str, n: int = 4) -> list[str]:
        """Generate distinct search phrases for a Toronto Waterfront Half Marathon question."""
        if not query.strip():
            return []
        n = max(1, min(n, 8))
        prompt = f"""Create exactly {n} distinct, concise search phrases for this question on the Toronto Waterfront Marathon website:
{query}

Keep the intent and any named people, dates, or topics. Vary the wording and useful keywords. Do not add unsupported details."""
        result = model.with_structured_output(SearchQueryVariants).invoke(prompt)
        queries = []
        seen = set()
        for candidate in result.queries:
            candidate = candidate.strip()
            key = candidate.casefold()
            if candidate and key not in seen:
                queries.append(candidate)
                seen.add(key)
            if len(queries) == n:
                break
        return queries

    @tool
    def search_for_articles(search_queries: list[str], max_results: int = 10) -> list[dict[str, Any]] | str:
        """Search the marathon site with query variants and rank unique linked results."""
        queries = [query.strip() for query in search_queries if query.strip()][:8]
        if not queries:
            return []
        max_results = max(1, min(max_results, 20))

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    results_by_url: dict[str, dict[str, Any]] = {}
                    search_path = urlsplit(SEARCH_URL).path.rstrip("/").lower()
                    for query in queries:
                        response = page.goto(
                            SEARCH_URL + quote(query, safe=""),
                            wait_until="domcontentloaded",
                            timeout=60_000,
                        )
                        if response is not None and response.status >= 400:
                            return _search_unavailable(f"the page returned HTTP {response.status}")

                        current_url = urlsplit(page.url)
                        if current_url.hostname != SITE_HOST or not current_url.path.lower().startswith(search_path):
                            return _search_unavailable(f"the search page redirected to {page.url}")

                        page.locator("body").wait_for()
                        page.wait_for_timeout(3_000)
                        links = page.locator("a[href]").evaluate_all(
                            """anchors => anchors
                                .filter(a => a.getClientRects().length > 0)
                                .map(a => ({ text: a.innerText.trim(), url: a.href }))
                                .filter(link => link.text && link.url)"""
                        )
                        for link in links:
                            parsed_url = urlsplit(link["url"])
                            if parsed_url.hostname != SITE_HOST or "/s/global-search/" in parsed_url.path:
                                continue
                            result = results_by_url.setdefault(
                                link["url"],
                                {"text": link["text"], "url": link["url"], "matched_queries": []},
                            )
                            if query not in result["matched_queries"]:
                                result["matched_queries"].append(query)
                    ranked = sorted(
                        results_by_url.values(),
                        key=lambda item: len(item["matched_queries"]),
                        reverse=True,
                    )
                    if not ranked:
                        return _search_unavailable(
                            "the search page loaded but returned no article links for the supplied queries"
                        )
                    return ranked[:max_results]
                finally:
                    browser.close()
        except PlaywrightError as error:
            return _search_unavailable(str(error))

    @tool
    def scrape_article_text(url: str) -> str:
        """Fetch an article from the Toronto Waterfront Marathon site and return its readable text."""
        parsed_url = urlsplit(url)
        if parsed_url.scheme != "https" or parsed_url.hostname != SITE_HOST:
            return f"Error: provide an HTTPS article URL from {SITE_HOST}."

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.locator("body").wait_for()
                # Salesforce Experience pages can render the heading in an
                # <article> while putting the actual body in a separate rich
                # text region. Compare likely content containers instead of
                # returning the first, potentially incomplete, match.
                page.wait_for_timeout(2_000)
                candidate_texts = []
                for selector in (
                    "article",
                    "main",
                    ".slds-rich-text-area__content",
                    ".article-content",
                    ".articleBody",
                    "[class*='article-body']",
                    "[class*='ArticleBody']",
                    "body",
                ):
                    for candidate in page.locator(selector).all_inner_texts():
                        candidate = candidate.strip()
                        if candidate:
                            candidate_texts.append(candidate)
                text = max(candidate_texts, key=len, default="")
                if not text:
                    return f"No readable article text found at {page.url}"
                return f"Title: {page.title()}\nURL: {page.url}\n\n{text}"
            finally:
                browser.close()

    return [
        find_closest_matching_runner_names,
        find_runner_name_by_id,
        get_runner_stats,
        rewrite_search_queries,
        search_for_articles,
        scrape_article_text,
    ]
