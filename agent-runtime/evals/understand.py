import re

from pydantic import BaseModel

from agent_runtime.contract import BelongsOnWatchlist, RowKind, RowState, Understood
from agent_runtime.planner import UNDERSTAND_SYSTEM, UnderstandAnswer, no_tool_for, understood_of
from evals.checks import Check, check, mentions, no_jargon, no_themed_names, ticket_keys
from evals.jobs import Answer, Case, Job

ACCEPTED = ("understood", "changed")
_PROJECT_KEY = re.compile(r"\b(?:[Pp]roject|[Ii]n)\s+([A-Z][A-Z0-9]{1,9})\b")
_NUMBER = re.compile(r"\d+")
_TOOL_OFFER = re.compile(
    r"\btool card\b|\bnew tool\b"
    r"|\b(?:add|build|make|create|draft|request)\w*\b[^.]{0,20}\btools?\b",
    re.IGNORECASE,
)


class UnderstandCase(Case):
    task: str
    watchlist: list[str] = []
    states: dict[RowKind, list[RowState]] = {}
    understood: list[str] = []
    cant_do: list[str] = []
    forbidden: list[str] = []
    reference: UnderstandAnswer


def prompt(case: UnderstandCase) -> str:
    return f"{UNDERSTAND_SYSTEM}\n\nThe task:\n{case.task}"


def schema() -> type[BaseModel]:
    return UnderstandAnswer


def _redirect(case: UnderstandCase, shown: BelongsOnWatchlist) -> list[Check]:
    return [
        check("right_answer", [] if case.watchlist else ["sent a task to the watchlist"]),
        check(
            "names_the_word",
            [] if any(mentions(shown.word, w) for w in case.watchlist) else [shown.word],
        ),
    ]


def _rows(case: UnderstandCase, answer: UnderstandAnswer, shown: Understood) -> list[Check]:
    first = {kind: next(r for r in shown.rows if r.kind == kind) for kind in case.states}
    accepted = " ".join(r.text for r in shown.rows if r.state in ACCEPTED)
    explained = " ".join(f"{r.text} {r.note or ''}" for r in shown.rows if r.state in ACCEPTED)
    refused = [f"{r.text} {r.note or ''}" for r in shown.rows if r.state == "cant_do"]
    words = [w for r in shown.rows for w in (r.text, r.note or "")]
    later = [r.text for r in shown.rows if r.kind != "schedule" and r.state == "understood"]
    notes = [r.note for r in shown.rows if r.state == "cant_do" and r.note]
    task_numbers = set(_NUMBER.findall(case.task))
    task_keys = set(_PROJECT_KEY.findall(case.task)) | ticket_keys(case.task)
    shown_keys = {k for text in words for k in _PROJECT_KEY.findall(text)}
    shown_keys |= {k for text in words for k in ticket_keys(text)}
    return [
        check("right_answer", [] if not case.watchlist else ["read it back instead"]),
        check(
            "right_states",
            [
                f"{kind} is {first[kind].state}, wanted {' or '.join(states)}"
                for kind, states in case.states.items()
                if first[kind].state not in states
            ],
        ),
        check("reads_the_parts", [w for w in case.understood if not mentions(explained, w)]),
        check(
            "marks_cant_do",
            [w for w in case.cant_do if not any(mentions(t, w) for t in refused)]
            + [f"{w} accepted" for w in case.cant_do if mentions(accepted, w)],
        ),
        check("keeps_out", [w for w in case.forbidden if mentions(accepted, w)]),
        check(
            "model_held_to_the_tools",
            [
                r.text
                for r in answer.rows
                if r.state in ACCEPTED and no_tool_for(r.kind, " ".join(r.text.split()))
            ],
        ),
        check("no_invented_keys", sorted(shown_keys - task_keys)),
        check(
            "no_invented_numbers",
            sorted({n for text in later for n in _NUMBER.findall(text)} - task_numbers),
        ),
        check(
            "no_tool_proposed",
            [note for note in notes if _TOOL_OFFER.search(note)],
        ),
    ]


def score(case: UnderstandCase, answer: Answer) -> list[Check]:
    value = answer.value
    if not isinstance(value, UnderstandAnswer):
        return [check("answered", ["no structured answer"])]
    shown = understood_of(value, case.task)
    if shown is None:
        return [check("answered", []), check("right_answer", ["the answer does not hold together"])]
    texts = (
        [shown.word]
        if isinstance(shown, BelongsOnWatchlist)
        else [w for r in shown.rows for w in (r.text, r.note or "")]
    )
    found = (
        _redirect(case, shown)
        if isinstance(shown, BelongsOnWatchlist)
        else _rows(case, value, shown)
    )
    text = " ".join(texts)
    return [check("answered", []), *found, no_jargon(text), no_themed_names(text)]


UNDERSTAND = Job(
    name="understand",
    title="Say what the Planner understood of a task",
    case_type=UnderstandCase,
    prompt=prompt,
    schema=schema,
    score=score,
    judged=False,
)
