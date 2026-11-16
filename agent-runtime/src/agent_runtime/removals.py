"""A request to take software off the Software watchlist (the registry's watchlist.remove).

Code reads it from the words, clause by clause: an order to remove a name from the watchlist, to
stop watching it, or a statement that the team no longer uses software the watchlist holds. Words
that name no watchlist count only for a name the watchlist holds, so "delete the old tickets" is
never one. The platform matches the name to the watchlist and shows the Software page's own
Remove, with its Undo. Nothing outside the platform is written, so no Approver is asked."""

import re
from dataclasses import dataclass
from typing import Final

from agent_runtime.abilities import TICKETS, words
from agent_runtime.contract import PlannerFacts
from agent_runtime.edits import asks
from agent_runtime.follow_ups import plausible_name
from agent_runtime.reading import FILLER, clauses_of, trim

type Span = tuple[int, int]

LIST: Final = (
    r"(?:(?:the|my|our|your)\s+)?(?:software\s+)?"
    r"(?:watch\s*-?list|software\s+list|list\s+of\s+software)"
)


@dataclass(frozen=True)
class _Way:
    pattern: re.Pattern[str]
    held_only: bool
    """True when the words name no watchlist, so only a name the watchlist holds counts."""


WAYS: Final = (
    _Way(
        re.compile(
            r"\b(?:remove|delete|drop|take|get|cut)\s+(?P<name>.+?)\s+"
            rf"(?:off|out\s+of|from)\s+{LIST}(?!\w)",
            re.IGNORECASE,
        ),
        held_only=False,
    ),
    _Way(re.compile(r"\bunwatch\s+(?P<name>.+)", re.IGNORECASE), held_only=False),
    _Way(
        re.compile(
            r"\b(?:stop|quit)\s+(?:watching|tracking|monitoring|following|checking)\s+(?P<name>.+)",
            re.IGNORECASE,
        ),
        held_only=False,
    ),
    _Way(
        re.compile(
            r"\b(?:we|i)\s+(?:(?:don['’]?t|do\s+not|no\s+longer)\s+(?:use|run|need)|"
            r"(?:have\s+)?stopped\s+using|(?:aren['’]?t|are\s+not)\s+using)\s+(?P<name>.+)",
            re.IGNORECASE,
        ),
        held_only=True,
    ),
    _Way(re.compile(r"\b(?:remove|delete|drop)\s+(?P<name>.+)", re.IGNORECASE), held_only=True),
)
"""Each way to ask, first match wins in a clause."""

ENDS_A_NAME: Final = re.compile(
    r"(?:^|\s+)(?:on|in|at|for|from|to|with|by|every|each|after|before|until|since|because|so|as|off|"
    r"out|any\s*more|now|please|too|releases?|versions?|updates?)\b.*$",
    re.IGNORECASE,
)
"""Where a name ends and the words after it begin, as "Kubernetes" in "Kubernetes releases"."""
AFTER_A_NAME: Final = re.compile(
    rf"(?:[\s,]+(?:any\s*more|now|please|for\s+(?:me|us|now|good)|too|as\s+well|"
    rf"from\s+now\s+on|(?:for\s+)?(?:new\s+)?(?:releases?|versions?|updates?)|"
    rf"(?:on|in|from|off)\s+{LIST}))*",
    re.IGNORECASE,
)
"""Words after the name that belong to the request to stop watching it."""
NOT_SOFTWARE: Final = TICKETS | words(
    "check checks workflow workflows summary summaries report reports run runs list lists "
    "software watchlist"
)
"""Words that make a name one of the person's workflows or tickets, never a software."""
QUOTES: Final = " .,'\"“”‘’"
SAYS_NOTHING: Final = FILLER | words("i me my mine i'd id like kindly pls plz")
"""Words around the request that ask for nothing more, as "help me" or "for me"."""


def name_key(name: str) -> str:
    """The name with case, spaces, dots and hyphens aside, so "node js" is "Node.js"."""
    return re.sub(r"[\s.\-]+", "", name.casefold())


@dataclass(frozen=True)
class Removal:
    software: str
    """The name as the request wrote it."""
    watched_as: tuple[str, ...]
    """The watchlist's names for it, from the facts."""
    clause: Span
    asked: Span
    """The words that ask for it: the order, the name and the list it names."""
    unread: tuple[Span, ...]
    """Other words in the clause that ask for something else, which no part of it reads."""


def removal_of(text: str, facts: PlannerFacts | None) -> Removal | None:
    """The first clause of the request that asks to take software off the watchlist, or None."""
    for clause in clauses_of(text):
        found = _in_clause(text, clause, facts)
        if found is not None:
            return found
    return None


def _in_clause(text: str, clause: Span, facts: PlannerFacts | None) -> Removal | None:
    if asks(text, clause):
        return None
    names = [w.name for w in facts.watchlist or []] if facts is not None else []
    held = {name_key(n) for n in names}
    workflows = {name_key(n) for n in facts.workflow_names()} if facts is not None else set[str]()
    for way in WAYS:
        found = way.pattern.search(text, clause[0], clause[1])
        if found is None:
            continue
        raw = found.group("name")
        cut = ENDS_A_NAME.search(raw)
        whole = plausible_name(raw.strip(QUOTES))
        if whole is not None and name_key(whole) in held:
            cut = None
        name = plausible_name((raw[: cut.start()] if cut else raw).strip(QUOTES))
        if name is None or set(name.casefold().split()) & NOT_SOFTWARE:
            continue
        if (way.held_only or name_key(name) in workflows) and name_key(name) not in held:
            continue
        start = text.index(name, found.start("name"))
        end = found.end() if cut is None else start + len(name)
        tail = AFTER_A_NAME.match(text, end, clause[1])
        asked = (found.start(), tail.end() if tail else end)
        watched_as = tuple(n for n in names if name_key(n) == name_key(name))
        return Removal(name, watched_as, clause, asked, _unread(text, clause, asked))
    return None


def _unread(text: str, clause: Span, asked: Span) -> tuple[Span, ...]:
    """The stretches of the clause outside the request to stop watching that ask for more."""
    pieces = [trim(text, clause[0], asked[0]), trim(text, asked[1], clause[1])]
    return tuple(
        (a, b)
        for a, b in pieces
        if a < b
        and any(w not in SAYS_NOTHING for w in re.findall(r"[\w'’]+", text[a:b].casefold()))
    )
