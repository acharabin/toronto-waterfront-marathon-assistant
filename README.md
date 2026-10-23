# Toronto Waterfront Marathon Assistant

## Intro

This project is a conversational assistant for the 2026 Toronto Waterfront Half Marathon. It brings two common tasks into one place: looking up runner results and answering questions from the event help center.

The assistant is designed for interactive use on a developer's computer, rather than as a continuously running hosted service. Runner results are prepared from the Sportstats leaderboard. Event information is searched on the Toronto Waterfront Marathon help site when a question is asked.

## Architecture

The agent routes each question through one of two workflows:

- **Runner results:** Names use semantic similarity to find candidate runners. The agent asks for clarification when a match is uncertain, then retrieves the selected runner's result. Bib numbers and finishing places use exact ID lookups.
- **Race information:** The agent rewrites the question into several search variants, searches the event help center, ranks the linked candidates, and scrapes the best matching article before answering from its text.

The workflow diagram, including safety screening before search and scrape results enter chat history, is in [diagrams/architecture.md](diagrams/architecture.md).

## Project layout

```text
main.py                         CLI entry point
my_agent/                       Agent package
  agent.py                      Agent construction and resource loading
  cli.py                        Interactive terminal loop
  config.py                     Shared TOML configuration loader
  utils/
    data.py                     Runner results and embeddings
    state.py                    Shared types for tools
    tools.py                    Runner and article search tools
    middleware.py               Moderation and tool-result safety screening
    instructions.md             Agent instructions
evals/evaluators/               LangSmith LLM evaluator definitions
assets/                         Processed and raw runner data
scripts/                        Scraping, processing, and data-quality scripts
diagrams/                       Architecture diagram
config.toml                     Shared paths, URLs, and scraper settings
.env                            Local credentials and tracing configuration
```

## Setup

1. Install dependencies with `uv sync`.
2. Copy `.env.example` to `.env` in the project root and add your OpenAI and LangSmith credentials.
3. Install Playwright's Chromium browser with `uv run playwright install chromium`.
4. Start the CLI with `uv run main.py` or `uv run python -m my_agent`.

File paths, service URLs, and scraper options are configured in `config.toml`. Relative paths resolve from the project root. Keep credentials in `.env`.

## Runner results data workflow

Scrape and process the leaderboard before starting the agent when you want to refresh the local results:

```powershell
uv run python scripts/scrape_half_marathon_results.py
uv run python scripts/process_raw_stats.py
```

The scraper settings `apply_truncate_file` and `num_skipped_pages` are in the `[scraper]` section of `config.toml`. Processing writes the Parquet dataset and then reports malformed raw records, raw-to-processed record-count mismatches, and duplicate places, bib numbers, names, ID pairs, or identical rows. It exits with status `1` if it reports a warning.

To run the duplicate checks against the already processed dataset without scraping or reprocessing, use:

```powershell
uv run python scripts/evaluate_processed_stats.py
```

## Examples

- “Who finished first in the Half Marathon?”
- “What was Ross Smith's finish time?”
- “Who had bib number 1234?”
- “What are the Half Marathon bag-check hours?”

## LangSmith evaluators

To publish and attach the native LangSmith LLM judges, set `LANGSMITH_PROJECT` in the project `.env` to the tracing project name, then run:

```powershell
uv run python -m evals.publish_evaluators
```

The publisher creates or reuses the evaluators and attaches them to the project at a 100% sampling rate. If your workspace requires explicit tenant routing, set `LANGSMITH_TENANT_ID`. To select a saved judge model configuration, set `LANGSMITH_EVALUATOR_PLAYGROUND_SETTINGS_ID`.

The project has two boolean LLM-as-a-judge metrics:

- **Retrieval relevance:** Passes when at least one article was scraped and every scraped article directly addresses the user's question. It fails when no article was scraped or any selected article is unrelated or only broadly related.
- **Response groundedness:** Passes when at least one article was scraped and every material factual claim in the assistant's final answer is supported by the scraped text. It fails when source text is missing or a material claim is unsupported or contradicted.

After publication, enabled run rules attach both evaluators to the configured LangSmith project at 100% sampling. New traces that land in that project are automatically scored by both evaluators. These metrics target race-information traces: runner-result-only traces contain no scraped article and will receive failing scores under the current evaluator definitions. Scores are LLM judgments, with a brief reasoning field for review.

## Key decisions and tradeoffs

### Shared moderation and safety screening

**Tradeoffs made**

- **Model input and output checks:** The agent uses `OpenAIModerationMiddleware` to check model input and output.

### Runner results

**Tradeoffs made**

- **Precomputed results:** Scrape, clean, and stage results before the agent starts. This reduces per-question latency and makes cross-page runner lookups practical, since the live leaderboard does not provide a simple query interface for searching all pages at once.
- **Semantic name matching:** Use semantic similarity to find candidate names across the local dataset. This keeps matching logic in code and is cost-effective for a dataset of roughly ten thousand records, while still allowing the agent to ask the user to resolve ambiguous matches.
- **Exact ID lookups:** Provide a separate exact lookup by bib number or finishing place. Both name-based and ID-based paths lead to the same result data, which keeps result retrieval predictable.
- **Stateless tools:** Keep lookup tools stateless. Each tool receives its names or IDs directly, avoiding state synchronization across a short lookup flow.

**Risks and mitigation**

- **Retroactive result changes:** Results can change retroactively, for example after a disqualification. Re-run the scrape and processing scripts before starting the agent to refresh its local data. A continuously hosted deployment would need a scheduled refresh job.
- **Runner identity collisions:** The lookup flow assumes places, bib numbers, and names uniquely identify the intended runner. Processing now checks duplicate IDs and names and compares raw and processed record counts; it prints warnings if these assumptions or the record counts do not hold. Duplicate names can be legitimate namesakes, so those warnings need review.

### Race information

**Tradeoffs made**

- **Live help center search:** Use the help center's existing keyword search rather than maintaining a local copy of every article. A local copy would need discovery, parsing, chunking, and regular refresh logic; if the online article structure changes, that copy could drift.
- **Query expansion:** Rewrite each question into several search variants to improve recall, then use the candidate links and their match frequency to help select a relevant article.
- **On-demand article retrieval:** Scrape the selected article on demand and answer from its content. This avoids asking the user to search repeatedly and scan a list of possible articles.

**Risks and mitigation**

- **Help-center availability and structure:** The search flow depends on the help-center URL and page structure. When navigation fails, redirects, or yields no article links, the tool returns a diagnostic asking the user to manually check the root search URL and update `urls.marathon_search` in `config.toml` if needed.
- **Tool result screening:** A separate safety judge screens help-center search and scrape results before they enter graph chat history, replacing a result with a safe notice if it is flagged or the judge fails. This adds an LLM call and some latency to each search and scrape. The classifier cannot guarantee detection, and external tracing systems may retain raw tool output separately from graph chat history.
- **Prompt injection mitigation:** Help-center pages may contain prompt injection attempts. The agent is instructed to treat page text as untrusted evidence, never as instructions. The safety judge screens retrieved content before it enters graph chat history, reducing—but not eliminating—the risk.
