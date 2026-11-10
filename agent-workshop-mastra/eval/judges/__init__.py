"""Judge definitions — one module per judge.

Registerable LLM judges (appear in the experiment's Judges tab):
  - learning_quality          (custom make_judge, 1-5)
  - conversation_consistency  (custom multi-turn make_judge, 1-5)
  - helpful_on_topic          (built-in Guidelines, pass/fail)
"""
from . import learning_quality, conversation_consistency, helpful_on_topic


def llm_judges(model: str):
    """The registerable LLM judges, instantiated against the given judge model."""
    return [
        learning_quality.build(model),
        conversation_consistency.build(model),
        helpful_on_topic.build(model),
    ]
