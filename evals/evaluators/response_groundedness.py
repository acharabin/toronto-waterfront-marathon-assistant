"""Prompt definition for LangSmith's native response groundedness judge."""

PROMPT_REPO_HANDLE = "toronto-half-marathon-response-groundedness"
VARIABLE_MAPPING = {
    "input_messages": "inputs.messages",
    "output_messages": "outputs.messages",
}


def make_prompt():
    """Build a structured prompt comparing the final answer to scraped text."""
    from langchain_core.prompts.structured import StructuredPrompt

    return StructuredPrompt(
        messages=[
            (
                "system",
                "You are an evaluator for answer groundedness. From the output "
                "messages, identify the content returned by scrape_article_text or "
                "scrape_article_content tools and the assistant's final response. "
                "Judge whether the response's material factual claims are supported "
                "by the scraped article text. Do not count a claim as supported just "
                "because it is plausible or generally true. Return is_grounded=true "
                "only when at least one article was scraped and all material factual "
                "claims in the final response are supported by those sources. Return "
                "false if no article was scraped, source text is missing, or any "
                "material claim is unsupported or contradicted. Return the boolean "
                "judgment in 'score' and a brief explanation in 'reasoning'.",
            ),
            (
                "human",
                "Input messages:\n{input_messages}\n\n"
                "Output messages (tool results and final assistant response):\n"
                "{output_messages}",
            ),
        ],
        schema_={
            "title": "ResponseGroundednessJudgment",
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "score": {"type": "boolean"},
            },
            "required": ["reasoning", "score"],
            "additionalProperties": False,
        },
    )
