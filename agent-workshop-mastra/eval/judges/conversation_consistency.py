"""conversation_consistency — multi-turn LLM judge. Reads the rolling conversation
from the TRACE ({{ trace }}) so it works per-turn in production monitoring: each
turn is scored against the conversation so far, so the metric evolves through the
thread. 1-5."""
from mlflow.genai.judges import make_judge


def build(model: str):
    return make_judge(
        name="conversation_consistency",
        instructions=(
            "Inspect the multi-turn conversation captured in {{ trace }} — the sequence of user and "
            "assistant messages so far. Judge whether the assistant's MOST RECENT reply is consistent "
            "with earlier turns (no contradiction), uses the prior context, and advances the user's goal. "
            "If this is the first turn (no prior context), score based on whether it sets up the "
            "conversation well. Grade 1-5."
        ),
        feedback_value_type=float,
        model=model,  # required for {{ trace }} (agentic) judges
    )
