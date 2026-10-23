"""Prompt definition for LangSmith's native retrieval relevance judge."""

PROMPT_REPO_HANDLE = "toronto-half-marathon-retrieval-relevance"
VARIABLE_MAPPING = {
    "input_messages": "inputs.messages",
    "output_messages": "outputs.messages",
}


def make_prompt():
    """Build a structured prompt that scores retrieved article titles."""
    from langchain_core.prompts.structured import StructuredPrompt

    return StructuredPrompt(
        messages=[
            (
                "system",
                "You are an evaluator for retrieval relevance. Inspect the user's "
                "question in the input messages and identify every article returned "
                "by a scrape_article_text or scrape_article_content tool in the "
                "output messages. Article text starts with 'Title:' when available. "
                "Judge each selected article by its title and URL against the user's "
                "question. Every selected article must directly address the requested "
                "topic. Return is_relevant=true only if at least one article was "
                "scraped and every scraped article is directly relevant. Return false "
                "if an article is unrelated, only broadly related, or about another "
                "race or topic. Do not treat a missing scrape as a passing result. "
                "Return the boolean judgment in 'score' and a brief explanation in "
                "'reasoning'.",
            ),
            (
                "human",
                "Input messages (contains the user question):\n{input_messages}\n\n"
                "Output messages (contains tool calls, scraped article text, and the "
                "assistant response):\n{output_messages}",
            ),
        ],
        schema_={
            "title": "RetrievalRelevanceJudgment",
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "score": {"type": "boolean"},
            },
            "required": ["reasoning", "score"],
            "additionalProperties": False,
        },
    )
