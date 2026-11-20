"""A request to explain a workflow the person has (ADR 0051, section 6, the registry's
workflows.explain).

Code reads it from the whole message: "explain" and the words that name the workflow, and nothing
else, so a request that asks for more keeps the lanes it had. The words are matched against the
person's workflows as an edit matches them (`name_runs`), else they are the words after
"explain" with the filler around them taken off. "explain why it stopped" and "explain what
happened" stay the why-stopped answer. "what does my workflow do?" asks for the same thing, and
is read only when the words between "what does" and "do" are my, our, this, that or the workflow,
or a workflow's whole name, and the person has a workflow. Explaining changes nothing, so both
roles may ask."""

import re
from typing import Final

from agent_runtime.abilities import words
from agent_runtime.contract import ExplainAnswer, PlannerFacts
from agent_runtime.edits import name_runs
from agent_runtime.reading import trim

type Span = tuple[int, int]

WORDS_LIMIT: Final = 80
LEAD: Final = re.compile(
    r"^\W*(?:(?:hi|hello|hey|ok|okay)\b\W*)?"
    r"(?:(?:please|pls|kindly|can|could|would|will|you|u|just)\s+)*explain\b",
    re.IGNORECASE,
)
"""The request opens with "explain", as "please explain" or "can you explain"."""
ABOUT_A_RUN: Final = re.compile(
    r"\b(?:why|what|how|when|where|whether|stop\w*|fail\w*|broke\w*|wrong|errors?|happen\w*|"
    r"crash\w*)\b",
    re.IGNORECASE,
)
"""Words that ask about a run, as "explain why it stopped", which the why-stopped answer takes."""
EDGE: Final = words(
    "the my our your this that these those a an me us to for please pls kindly workflow "
    "workflows one ones again now thanks thank you cheers"
)
"""Words around a workflow's name that name no workflow, as "to me", "the" or "workflow"."""
POINTING: Final = words("it them")
"""Words that name the workflow in focus, as "explain it"."""
JOINED: Final = re.compile(r"[,;:!?]|\.(?:\s|$)|\b(?:and|then|also|plus|but|or)\b", re.IGNORECASE)
"""A second request beside the explanation, as "and pause it"."""
TOKEN: Final = re.compile(r"[^\W_]+(?:['’.-][^\W_]+)*")
WHAT_IT_DOES: Final = re.compile(
    r"^\W*(?:(?:hi|hello|hey|ok|okay|so)\b\W*)?what\s+(?:does|do)\s+(?P<ref>.+?)\s+"
    r"(?:(?:actually|exactly|really)\s+)?do(?:\s+(?:actually|exactly|again))?\W*$",
    re.IGNORECASE,
)
"""A question about what a workflow does, as "what does my workflow do?"."""
ONE_OF_THEIRS: Final = re.compile(r"(?:my|our|this|that|the)\s+workflow", re.IGNORECASE)
"""The words that point at one of the person's workflows, never "a workflow" or "workflows"."""
LEADING: Final = re.compile(r"^(?:my|our|this|that|the)\s+", re.IGNORECASE)


def explain_of(text: str, facts: PlannerFacts | None) -> ExplainAnswer | None:
    """The explanation the whole request asks for, or None when it asks for anything else."""
    lead = LEAD.match(text)
    if lead is None:
        return _what_it_does(text, facts)
    start, end = trim(text, lead.end(), len(text))
    named = _named(text, (start, end), facts)
    unnamed = text[start:end] if named is None else text[start : named[0]] + text[named[1] : end]
    if ABOUT_A_RUN.search(unnamed):
        return None
    if named is not None and not _content(unnamed):
        return ExplainAnswer(workflow_words=text[named[0] : named[1]])
    said = _edges_off(text[start:end])
    if all(t.casefold() in POINTING for t in TOKEN.findall(said)):
        return ExplainAnswer(workflow_words=None)
    if JOINED.search(said) or len(said) > WORDS_LIMIT:
        return None
    return ExplainAnswer(workflow_words=said)


def _what_it_does(text: str, facts: PlannerFacts | None) -> ExplainAnswer | None:
    """A question as "what does my workflow do?" names no workflow, so the platform picks the
    one they mean. A workflow's whole name, as "what does the FastAPI release check do?", is
    kept. Anything else in the middle, as "it", "a workflow", part of a name or a software's
    name, is no explanation, and nor is anything asked by someone with no workflow to explain."""
    asked = WHAT_IT_DOES.match(text)
    if asked is None or facts is None or facts.workflows_in_all() == 0:
        return None
    start, end = asked.span("ref")
    if ONE_OF_THEIRS.fullmatch(" ".join(text[start:end].split())):
        return ExplainAnswer(workflow_words=None)
    named = LEADING.sub("", text[start:end], count=1)
    names = {_plain(name) for name in facts.workflow_names()}
    return ExplainAnswer(workflow_words=named) if _plain(named) in names else None


def _plain(name: str) -> str:
    return " ".join(name.casefold().split())


def _named(text: str, within: Span, facts: PlannerFacts | None) -> Span | None:
    """The longest stretch of the request that names one of the person's workflows."""
    names = facts.workflow_names() if facts is not None else []
    runs = [
        r
        for name in names
        for r in name_runs(text, name)
        if within[0] <= r[0] and r[1] <= within[1]
    ]
    return max(runs, key=lambda r: (r[1] - r[0], -r[0]), default=None)


def _content(said: str) -> list[str]:
    return [t for t in TOKEN.findall(said) if t.casefold() not in EDGE]


def _edges_off(said: str) -> str:
    """The words with the filler at either end taken off, as "the" or "to me"."""
    kept = [m for m in TOKEN.finditer(said) if m.group(0).casefold() not in EDGE]
    return said[kept[0].start() : kept[-1].end()] if kept else ""
