"""helpful_on_topic — built-in Guidelines judge (reference-free): pass/fail on
addressing the question concisely without inventing facts."""
from mlflow.genai.scorers import Guidelines


def build(model: str):
    return Guidelines(
        name="helpful_on_topic",
        guidelines="The response must directly address the question, be concise, and not invent facts.",
        model=model,
    )
