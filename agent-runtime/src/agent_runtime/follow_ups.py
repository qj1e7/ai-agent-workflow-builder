"""Safe follow-ups (ADR 0042): "and Redis?" after an answer about the watchlist.

The follow-up reads only what the person typed now. The previous turn is client input, so it
decides whether a follow-up applies and nothing more: it never supplies request text. The first
reading always runs first. A name on the watchlist sends the typed words to the read-only question
lane. Any other plausible name becomes the offer to watch it, which the person must tap, only when
the first reading names it as software. Everything else keeps the first answer."""

import re
from dataclasses import dataclass
from typing import Final

from agent_runtime.abilities import change_verbs_in, commands_a_change
from agent_runtime.contract import AnswerRequest, PlannerAnswer, WatchlistAnswer
from agent_runtime.planner import visible_words

FOLLOWS: Final = frozenset({"question", "watchlist"})
FOLLOW_UP: Final = re.compile(
    r"^\s*(?:and|what\s+about|how\s+about)\s+(?P<name>[^?]{1,60}?)\s*\??\s*$", re.IGNORECASE
)
NAME_WORD: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_#-]*$")
NOT_A_NAME: Final = frozenset(
    {
        *("it", "its", "that", "this", "them", "they", "those", "these", "there", "here", "the"),
        *("same", "one", "ones", "all", "any", "anything", "everything", "something", "nothing"),
        *("none", "else", "more", "other", "another", "also", "too", "again", "now", "then"),
        *("instead", "without", "with", "but", "or", "and", "not", "no", "yes", "if", "please"),
        *("why", "how", "when", "what", "which", "who", "whom", "where", "whose"),
        *("me", "my", "we", "our", "us", "you", "your", "i"),
    }
)
VERSION: Final = "version"


@dataclass(frozen=True)
class FollowUp:
    """The name a follow-up asks about, and whether the watchlist holds it, spelled as it does."""

    name: str
    watched: str | None


def plausible_name(said: str) -> str | None:
    """The name when it is one to three plain words, none a pronoun or question word, with no verb
    that asks for a change. A leading "the" is dropped."""
    row = said.split()
    if row and row[0].casefold() == "the":
        row = row[1:]
    if not 1 <= len(row) <= 3 or any(not NAME_WORD.match(w) for w in row):
        return None
    if any(w.casefold().strip(".") in NOT_A_NAME for w in row):
        return None
    name = " ".join(row)
    if change_verbs_in(name) or commands_a_change(name):
        return None
    return name


def follow_up_of(request: AnswerRequest) -> FollowUp | None:
    """The follow-up the typed words make, or None for the normal path. It needs a previous answer
    of kind question or watchlist, and a watchlist in the facts to tell watched from unwatched."""
    earlier = request.previous
    facts = request.facts
    if earlier is None or earlier.kind not in FOLLOWS or facts is None or facts.watchlist is None:
        return None
    text = visible_words(request.task)
    found = FOLLOW_UP.match(text)
    if found is None or change_verbs_in(text) or commands_a_change(text):
        return None
    name = plausible_name(found.group("name"))
    if name is None:
        return None
    held = {w.name.strip().casefold(): w.name.strip() for w in facts.watchlist}
    return FollowUp(name=name, watched=held.get(name.casefold()))


def watch_offer_of(
    found: FollowUp, read_software: str | None, answer: PlannerAnswer
) -> WatchlistAnswer | None:
    """The offer to watch X, for a follow-up about software the watchlist does not hold. It needs
    the first reading to name X as software, or the first answer to be a watchlist answer for X."""
    wanted = found.name.strip().casefold()
    said = (read_software or "").strip().casefold()
    asked = answer.software if isinstance(answer, WatchlistAnswer) else None
    if wanted not in (said, (asked or "").strip().casefold()):
        return None
    return WatchlistAnswer(word=VERSION, software=found.name)
