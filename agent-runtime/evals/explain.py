from typing import Literal

from pydantic import BaseModel, Field

from evals.checks import (
    Check,
    check,
    length_cap,
    no_invented,
    no_jargon,
    no_themed_names,
    no_write_claim,
)
from evals.jobs import Answer, Case, Job

MAX_EXPLANATION_LENGTH = 500


class Explanation(BaseModel):
    explanation: str = Field(
        description="What happened and what to do next, in at most three short plain sentences "
        "for a non-technical support person."
    )
    retry_safe: bool = Field(
        description="True if the person can safely retry this same run as it is. False if "
        "someone must change something first, or a person decided against the work."
    )


class ExplainCase(Case):
    outcome: Literal["failed", "declined"]
    stage: str
    reason: str | None
    message: str
    events: list[str]
    retry_safe: bool
    must_mention: list[list[str]]
    reference: Explanation


def ending(case: ExplainCase) -> str:
    if case.outcome == "declined":
        return f"The run ended at the approval stage. Detail: {case.message}"
    return (
        f"The run failed while it was {case.stage}. Reason: {case.reason}. Detail: {case.message}"
    )


def prompt(case: ExplainCase) -> str:
    log = "\n".join(f"- {line}" for line in case.events)
    return (
        "You are the AI troubleshooter in a workflow platform. A non-technical support person "
        "started a run and it did not finish. Explain in at most three short sentences what "
        "happened and what they should do next. Use plain words. Then say whether retrying "
        f"the same run is safe.\n\nActivity log:\n{log}\n\nHow it ended: {ending(case)}"
    )


def score(case: ExplainCase, answer: Answer) -> list[Check]:
    if not isinstance(answer.value, Explanation):
        return [check("answered", ["no structured answer"])]
    text = answer.value.explanation
    source = "\n".join([*case.events, case.message, "workflow engine"])
    lowered = text.lower()
    return [
        check("answered", [] if text.strip() else ["empty explanation"]),
        check(
            "retry_safe_matches",
            []
            if answer.value.retry_safe == case.retry_safe
            else [f"said {answer.value.retry_safe}, truth {case.retry_safe}"],
        ),
        check(
            "required_facts",
            [
                " or ".join(group)
                for group in case.must_mention
                if not any(term.lower() in lowered for term in group)
            ],
        ),
        length_cap(text, MAX_EXPLANATION_LENGTH),
        no_jargon(text),
        no_themed_names(text),
        *no_invented(text, source),
        no_write_claim(text, source),
    ]


EXPLAIN = Job(
    name="explain",
    title="Explain a failure in plain words",
    case_type=ExplainCase,
    prompt=prompt,
    schema=lambda: Explanation,
    score=score,
    judged=True,
)
