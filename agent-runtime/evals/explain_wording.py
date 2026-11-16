"""Explain's rewording of a workflow's In short (ADR 0051): how often the model's smoothing passes
every check, and whether what the person would see keeps to the facts.

Each case is code's In short for a workflow from platform-api's golden n8n documents or its report
tests, with the facts the platform sends beside it. The product's own path runs on the model under
test: one call, the guard, then the verifier. The score reads what the person would see against the
case's facts in its own way, apart from the guard."""

import re
from typing import Final

from langchain_core.language_models import BaseChatModel

from agent_runtime.contract import (
    ExplainFact,
    ExplainKept,
    ExplainReworded,
    ExplainWordingRequest,
    ModelAccess,
)
from agent_runtime.explain_wording import EXPLAIN_TIMEOUT_SECONDS, reword
from evals.anything import Replies, usage_of
from evals.checks import Check, check
from evals.jobs import Answer, Case, Job

ACCESS: Final = ModelAccess(
    style="openai", base_url="http://eval.invalid", model="eval", api_key="-"
)
QUOTED: Final = re.compile(r"“([^”]*)”|\"([^\"]*)\"")
NEGATION: Final = re.compile(
    r"\b(?:not|no|never|nothing|none|nor|cannot|without)\b|n['’]t\b", re.IGNORECASE
)


class WordingCase(Case):
    wording: str
    facts: list[ExplainFact]
    can_reword: bool
    """False when no smoothing can pass ADR 0047's checks, as one that names Slack, so code's
    wording kept is the right answer."""


def request_of(case: WordingCase) -> ExplainWordingRequest:
    return ExplainWordingRequest(model=ACCESS, wording=case.wording, facts=case.facts)


def ask(model: BaseChatModel, case: WordingCase) -> Answer:
    """The product's own path for a case, every model call it makes counted."""
    replies = Replies()
    watched = model.model_copy(update={"callbacks": [replies]})
    shown = reword(request_of(case), lambda _timeout: watched)
    return Answer(shown, shown.model_dump_json(), usage_of(replies.messages))


def _untrue(text: str, case: WordingCase) -> list[str]:
    """What the shown text changes in the facts: a quoted value added or dropped, an item of a fact
    left out, or a negation added or dropped."""
    quoted = {a or b for a, b in QUOTED.findall(case.wording)}
    shown = {a or b for a, b in QUOTED.findall(text)}
    found = [f"quotes “{value}”" for value in sorted(quoted ^ shown)]
    low = text.casefold()
    found += [
        f"leaves out “{item}”"
        for fact in case.facts
        for item in fact.together
        if item.casefold() not in low
    ]
    if len(NEGATION.findall(text)) != len(NEGATION.findall(case.wording)):
        found.append("adds or drops a negation")
    return found


def score(case: WordingCase, answer: Answer) -> list[Check]:
    shown = answer.value
    if not isinstance(shown, ExplainReworded | ExplainKept):
        return [check("answered", ["no answer"])]
    if isinstance(shown, ExplainKept):
        missed = [f"kept: {shown.why}"] if case.can_reword else []
        return [check("answered", []), check("reworded", missed)]
    passed = [] if case.can_reword else ["no smoothing should pass"]
    return [
        check("answered", []),
        check("reworded", passed),
        check("true_to_the_facts", _untrue(shown.text, case)),
    ]


EXPLAIN_WORDING = Job(
    name="explain_wording",
    title="Reword a workflow's In short, true to its facts",
    case_type=WordingCase,
    prompt=lambda case: case.wording,
    schema=None,
    score=score,
    judged=False,
    time_limit_s=EXPLAIN_TIMEOUT_SECONDS,
    product_call=ask,
    most_calls=2,
)
