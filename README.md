# Toronto Waterfront Marathon Assistant

## Intro

This project is a locally run conversational assistant for the 2026 Toronto Waterfront Half Marathon. It brings two common tasks into one place: looking up runner results and answering Half Marathon questions using the event help center.

The assistant is designed for interactive use on a developer's computer, rather than as a continuously running hosted service. Runner results are prepared locally from the Sportstats leaderboard. Event information is searched on the Toronto Waterfront Marathon help site when a question is asked.

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

## Runner data workflow

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

## Key decisions and tradeoffs

### Shared moderation and safety screening

The agent uses `OpenAIModerationMiddleware` to check model input and output. A separate safety judge screens help-center search and scrape tool results before those results enter graph chat history. If the judge flags a result or fails, the tool message is replaced with a safe notice. The agent is also instructed to treat web content as untrusted evidence, never as instructions.

This adds an LLM call and some latency to each help-center search and scrape. A classifier cannot guarantee detection, and external tracing systems may retain raw tool output separately from graph chat history.

### Runner results

**Tradeoffs made**

- Scrape, clean, and stage results before the agent starts. This reduces per-question latency and makes cross-page runner lookups practical, since the live leaderboard does not provide a simple query interface for searching all pages at once.
- Use semantic similarity to find candidate names across the local dataset. This keeps matching logic in code and is cost-effective for a dataset of roughly ten thousand records, while still allowing the agent to ask the user to resolve ambiguous matches.
- Provide a separate exact lookup by bib number or finishing place. Both name-based and ID-based paths lead to the same result data, which keeps result retrieval predictable.
- Keep lookup tools stateless. Each tool receives its names or IDs directly, avoiding state synchronization across a short lookup flow.

**Risks and mitigation**

- Results can change retroactively, for example after a disqualification. Re-run the scrape and processing scripts before starting the agent to refresh its local data. A continuously hosted deployment would need a scheduled refresh job.
- The lookup flow assumes places, bib numbers, and names uniquely identify the intended runner. Processing now checks duplicate IDs and names and compares raw and processed record counts; it prints warnings if these assumptions or the record counts do not hold. Duplicate names can be legitimate namesakes, so those warnings need review.

### Race information

**Tradeoffs made**

- Use the help center's existing keyword search rather than maintaining a local copy of every article. A local copy would need discovery, parsing, chunking, and regular refresh logic; if the online article structure changes, that copy could drift.
- Rewrite each question into several search variants to improve recall, then use the candidate links and their match frequency to help select a relevant article.
- Scrape the selected article on demand and answer from its content. This avoids asking the user to search repeatedly and scan a list of possible articles.

**Risks and mitigation**

- The search flow depends on the help-center URL and page structure. When navigation fails, redirects, or yields no article links, the tool returns a diagnostic asking the user to manually check the root search URL and update `urls.marathon_search` in `config.toml` if needed.
- Web results can contain unsafe content or prompt-injection attempts. The safety judge checks search and scrape outputs before they enter chat history and fails closed if it cannot assess them. The agent is instructed to treat page text as data. These measures reduce risk but do not guarantee detection; tracing retention is configured separately.
