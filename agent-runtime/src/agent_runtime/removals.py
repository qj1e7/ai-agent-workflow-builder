"""A request to take software off the Software watchlist (the registry's watchlist.remove).

Code reads it from the words, clause by clause: an order to remove a name from the watchlist, to
stop watching it, or a statement that the team no longer uses software the watchlist holds. Words
that name no watchlist count only for a name the watchlist holds, so "delete the old tickets" is
never one. A no, as "don't remove React", and a time, as "stop watching React until next month",
make none: those keep the lanes they had. The platform matches the name to the watchlist and shows
the Software page's own Remove, with its Undo. Nothing outside the platform is written, so no
Approver is asked."""

import re
from dataclasses import dataclass
from typing import Final

from agent_runtime.abilities import TICKETS, words
from agent_runtime.contract import SOFTWARE_NAME_LIMIT, PlannerFacts
from agent_runtime.edits import asks
from agent_runtime.follow_ups import plausible_name
from agent_runtime.reading import FILLER, SCHEDULE_WORDS, TIME_OF_DAY, clauses_of, negated, trim

type Span = tuple[int, int]

LIST: Final = (
    r"(?:(?:the|my|our|your)\s+)?(?:software\s+)?"
    r"(?:watch\s*-?list|software\s+list|list\s+of\s+software)(?!\w)(?!\s+schedules?\b)"
)
"""The watchlist by name. "the watchlist schedule" is its schedule, which the edit lane reads."""


@dataclass(frozen=True)
class _Way:
    pattern: re.Pattern[str]
    held_only: bool
    """True when the words name no watchlist, so only a name the watchlist holds counts."""
    bounded: bool = False
    """True when the list after the name ends it, so the name is never cut shorter."""


WAYS: Final = (
    _Way(
        re.compile(
            r"\b(?:remove|delete|drop|take|get|cut)\s+(?P<name>.+?)\s+"
            rf"(?:off|out\s+of|from)\s+{LIST}",
            re.IGNORECASE,
        ),
        held_only=False,
        bounded=True,
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
    _Way(
        re.compile(rf"^(?P<name>.+?)\s+(?:off|out\s+of|from)\s+{LIST}$", re.IGNORECASE),
        held_only=True,
        bounded=True,
    ),
)
"""Each way to ask, first match wins in a clause. The last is a name and its list alone, as
"LangGraph from the watchlist" left over from "remove React and LangGraph from the watchlist",
which Ask about this sends on its own."""

AFTER_A_NAME: Final = (
    r"(?:[\s,]+(?:any\s*more|now|please|for\s+(?:me|us|now|good)|too|as\s+well|"
    r"from\s+now\s+on|(?:for\s+)?(?:new\s+)?(?:releases?|versions?|updates?)|"
    rf"(?:on|in|from|off)\s+{LIST}))"
)
"""Words after the name that belong to the request to stop watching it."""
TAIL: Final = re.compile(rf"{AFTER_A_NAME}*", re.IGNORECASE)
NAME_TAIL: Final = re.compile(rf"{AFTER_A_NAME}+$", re.IGNORECASE)
TIMED: Final = re.compile(
    r"\b(?:until|till|for\s+(?:a|an|one|two|three|\d+)\s+(?:days?|weeks?|months?|years?)|"
    r"next\s+(?:week|month|year)|tomorrow|today|tonight|temporarily|weekends?)\b",
    re.IGNORECASE,
)
"""A time that makes it a pause or a schedule, as "until next month", not a removal."""
NOT_SOFTWARE: Final = TICKETS | words(
    "check checks workflow workflows summary summaries report reports run runs list lists "
    "software watchlist"
)
"""Words that make a name one of the person's workflows or tickets, never a software."""
QUOTES: Final = " .,'\"“”‘’"
NO_APOSTROPHE: Final = re.compile(
    r"\b(?:dont|doesnt|didnt|wont|wouldnt|shouldnt|cant|cannot)\b", re.IGNORECASE
)
"""A no typed without its apostrophe, which `negated` misses."""
SAYS_NOTHING: Final = FILLER | words("i me my mine i'd id like kindly pls plz")
"""Words around the request that ask for nothing more, as "help me" or "for me"."""
POINTS_BACK: Final = re.compile(
    r"(?:(?:please|so|and|then|just)\s+)*(?:(?:remove|delete|drop|unwatch|take)\s+"
    r"|stop\s+(?:watching|tracking|monitoring|checking)\s+)(?:it|them|that|this(?:\s+one)?)"
    rf"(?:\s+(?:off|out\s+of|from)\s+{LIST})?(?:\s+please)?",
    re.IGNORECASE,
)
"""A clause that asks again for the removal beside it, as "remove it"."""


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


def points_back(clause: str) -> bool:
    return POINTS_BACK.fullmatch(clause.strip(QUOTES + "!?")) is not None


def _in_clause(text: str, clause: Span, facts: PlannerFacts | None) -> Removal | None:
    if asks(text, clause):
        return None
    said = text[clause[0] : clause[1]]
    names = [w.name for w in facts.watchlist or []] if facts is not None else []
    held = {name_key(n) for n in names}
    workflows = {name_key(n) for n in facts.workflow_names()} if facts is not None else set[str]()
    for way in WAYS:
        found = way.pattern.search(said)
        if found is None or _says_no(said[: found.start()]):
            continue
        raw = found.group("name")
        cut = None if way.bounded else NAME_TAIL.search(raw)
        name = plausible_name((raw[: cut.start()] if cut else raw).strip(QUOTES))
        if name is None or len(name) > SOFTWARE_NAME_LIMIT:
            continue
        if set(name.casefold().split()) & NOT_SOFTWARE:
            continue
        if (way.held_only or name_key(name) in workflows) and name_key(name) not in held:
            continue
        start = said.index(name, found.start("name"))
        tail = TAIL.match(said, found.end() if way.bounded else start + len(name))
        asked = (found.start(), tail.end() if tail else found.end())
        if _timed(said.replace(name, " ") if name_key(name) in held else said):
            return None
        watched_as = tuple(n for n in names if name_key(n) == name_key(name))
        at = (clause[0] + asked[0], clause[0] + asked[1])
        return Removal(name, watched_as, clause, at, _unread(text, clause, at))
    return None


def _says_no(before: str) -> bool:
    """Whether the words before the order say no to it, as "don't" or "no need to"."""
    plain = before.replace("’", "'")
    return negated(plain) or NO_APOSTROPHE.search(plain) is not None


def _timed(words_: str) -> bool:
    low = re.findall(r"[\w'’]+", words_.casefold())
    return bool(TIMED.search(words_) or TIME_OF_DAY.search(words_) or set(low) & SCHEDULE_WORDS)


def _unread(text: str, clause: Span, asked: Span) -> tuple[Span, ...]:
    """The stretches of the clause outside the request to stop watching that ask for more."""
    pieces = [trim(text, clause[0], asked[0]), trim(text, asked[1], clause[1])]
    return tuple(
        (a, b)
        for a, b in pieces
        if a < b
        and any(w not in SAYS_NOTHING for w in re.findall(r"[\w'’]+", text[a:b].casefold()))
    )
