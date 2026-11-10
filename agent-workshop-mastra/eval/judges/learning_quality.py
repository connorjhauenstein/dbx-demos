"""learning_quality — custom LLM judge: is the response helpful, accurate, and
well-scoped for a learner? Returns a 1-5 score."""
from mlflow.genai.judges import make_judge


def build(model: str):
    return make_judge(
        name="learning_quality",
        instructions=(
            "Grade the response in {{ outputs }} to {{ inputs }} on a 1-5 scale for a learner: "
            "1 = unhelpful or incorrect, 3 = adequate, 5 = accurate, actionable, and well-scoped."
        ),
        feedback_value_type=float,
        model=model,
    )
