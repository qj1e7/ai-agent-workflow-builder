"""Explain's rewording of a workflow's In short (ADR 0051): how often the model's smoothing passes
every check, and whether what the person would see keeps to the facts.

Each case is code's In short for a workflow from platform-api's golden n8n documents or its report
tests, with the facts the platform sends beside it. The product's own path runs on the model under
test: one call, the guard, then the verifier. The score reads what the person would see against the
case's facts in its own way, apart from the guard."""

import itertools
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
SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")
WHEN: Final = re.compile(
    r"\b(?:day|daily|week|weekly|month|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday|\d{1,2}:\d{2})\b",
    re.IGNORECASE,
)
ACTIONS: Final = re.compile(
    r"\b(?:reads?|looks?|checks?|posts?|sends?|shares?|creates?|changes?|makes?|writes?|"
    r"deletes?|removes?|closes?|updates?|edits?)\b",
    re.IGNORECASE,
)
YES: Final = re.compile(r"\byes\b", re.IGNORECASE)
NAMED: Final = re.compile(r"([A-Z][\w-]*)\s+(?:“([^”]*)”|\"([^\"]*)\")")


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


def _sentences(text: str) -> list[str]:
    """The text cut into sentences, never inside quotes."""
    masked = QUOTED.sub(lambda m: "_" * len(m.group(0)), text)
    cuts = [0, *(m.end() for m in SENTENCE_END.finditer(masked)), len(text)]
    return [text[a:b].strip() for a, b in itertools.pairwise(cuts) if text[a:b].strip()]


def _outside(sentence: str) -> str:
    return QUOTED.sub(" ", sentence)


def _found(pattern: re.Pattern[str], sentence: str) -> list[str]:
    """The words the pattern finds outside quotes, case and a closing "s" aside, so "changes" and
    "change" are one action."""
    return sorted(m.casefold().removesuffix("s") for m in pattern.findall(_outside(sentence)))


def _untrue(text: str, case: WordingCase) -> list[str]:
    """What the shown text changes in the facts, sentence by sentence against code's wording: a
    sentence merged, split or moved, a quoted value moved, added or dropped, a place on another
    system, a fact's item left out of its sentence, a run time, an action, a yes or a negation
    added, dropped or moved."""
    code, shown = _sentences(case.wording), _sentences(text)
    if len(code) != len(shown):
        return [f"has {len(shown)} sentences, not {len(code)}"]
    found: list[str] = []
    for at, (c, s) in enumerate(zip(code, shown, strict=True), start=1):
        quoted = {a or b for a, b in QUOTED.findall(c)}
        said = {a or b for a, b in QUOTED.findall(s)}
        found += [f"sentence {at} quotes “{value}”" for value in sorted(quoted ^ said)]
        named = {(m[0], m[1] or m[2]) for m in NAMED.findall(s)}
        found += [
            f"sentence {at} has “{value}” off {word}"
            for word, a, b in NAMED.findall(c)
            if (word, value := a or b) not in named
        ]
        held = [f for f in case.facts if all(_item_in(i, c) for i in f.together)]
        found += [
            f"sentence {at} leaves out “{item}”"
            for fact in held
            for item in fact.together
            if not _item_in(item, s)
        ]
        for name, pattern in (("run time", WHEN), ("action", ACTIONS), ("yes", YES)):
            if _found(pattern, c) != _found(pattern, s):
                found.append(f"sentence {at} changes its {name} words")
        if len(NEGATION.findall(_outside(c))) != len(NEGATION.findall(_outside(s))):
            found.append(f"sentence {at} adds or drops a negation")
    return found


def _item_in(item: str, sentence: str) -> bool:
    return item.casefold() in sentence.casefold()


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
