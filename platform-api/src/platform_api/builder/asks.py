"""What each clause of a request asks, for someone who can't change workflows (ADR 0043, spec 5.3).

The agent runtime reads the request. These word rules only sort the request's clauses into what
builder answers for an Approver: their own decisions, an approve or decline that goes to the
request, a question, or a change only an Operator makes. A clause they can't place is "other".
They fail closed: a clause that asks for a change is never answered as a question.
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

type Ask = Literal["decided", "decide", "question", "change", "other"]

BREAK: Final = re.compile(
    r"\b(?:and|then|also|but|plus|while)\b|[,;?!&]+|\.(?=\s|$)", re.IGNORECASE
)
POLITE_ONLY: Final = re.compile(
    r"^(?:please|thanks?|thank you|cheers|ok(?:ay)?|hi|hello|hey)$", re.IGNORECASE
)
DECIDED: Final = re.compile(
    r"\bdid i\b.*\b(?:decide|approve|decline|reject|accept|say (?:yes|no))\b"
    r"|\bhave i\b.*\b(?:decided|approved|declined|rejected|accepted|said (?:yes|no))\b"
    r"|\bi (?:decided|approved|declined|rejected|accepted|said (?:yes|no))\b"
    r"|\b(?:past|recent|earlier|previous|last|old) (?:decisions?|approvals?)\b"
    r"|\bmy decisions?\b",
    re.IGNORECASE,
)
"""A question about the person's own decisions, in the past: "What did I decide before?", "did
I say no to anything?", "show my past decisions". "Have I got anything to approve?" is not one."""
DECIDE: Final = re.compile(
    r"\b(?:approve|decline|reject|accept|sign off|say (?:yes|no) to)\b", re.IGNORECASE
)
"""An approve or decline, whatever it names. Nobody decides in the chat, so it goes to the
request."""
TO_BEFORE: Final = re.compile(r"\bto\s+$", re.IGNORECASE)
COURTESY: Final = re.compile(
    r"^(?:(?:please|ok(?:ay)?|so|now|hi|hey)\b[,\s]*)*"
    r"(?:(?:can|could|would|will) you\s+(?:please\s+)?)?",
    re.IGNORECASE,
)
QUESTION: Final = re.compile(
    r"^(?:which|what|what's|whats|how|how's|is|are|was|were|do|does|did|when|where|why|who|"
    r"whose|has|have|any|anything|show|list|tell|give|see|view|find|look|let me (?:see|know)|"
    r"check (?:on|my|how|whether|if|what|which))\b",
    re.IGNORECASE,
)
"""A clause that asks to be told something. "Can you show me ..." asks too."""
CHANGE: Final = re.compile(
    r"\b(?:set\s+up|setup|set|make|change|turn|switch|move|rename|pause|resume|stop|start|"
    r"restart|run|retry|delete|remove|cancel|disable|enable|edit|update|upgrade|add|create|"
    r"watch|unwatch|track|monitor|follow|schedule|reschedule|report|send|post|e-?mail|raise|"
    r"file|assign|close|put|keep|notify|remind|alert|ping|inform|kill|shut|terminate|abort|"
    r"halt|archive|mute|drop|replace|install|deploy|trigger|launch|execute|submit|publish|"
    r"merge|push|write)\b",
    re.IGNORECASE,
)
"""A word that asks for something to be set up or changed."""
NAMES_A_THING: Final = re.compile(
    r"\b(?:the|a|an|this|that|these|those|my|our|your|its|their|his|her|any|every|each|no)\s+$",
    re.IGNORECASE,
)
"""A change word right after one of these names a thing, as "the upgrade" in "approve the
upgrade", and asks for nothing."""


@dataclass(frozen=True)
class Clause:
    text: str
    ask: Ask


def _asks_to_be_told(text: str) -> bool:
    return QUESTION.match(COURTESY.sub("", text, count=1)) is not None


def _changes(text: str) -> bool:
    return any(not NAMES_A_THING.search(text[: m.start()]) for m in CHANGE.finditer(text))


def _decides(text: str) -> bool:
    """An approve or decline asked for. In a question, "anything to approve" asks what waits."""
    told = _asks_to_be_told(text)
    return any(not (told and TO_BEFORE.search(text[: m.start()])) for m in DECIDE.finditer(text))


def ask_of(text: str) -> Ask:
    """What a clause asks. A change wins over an approve or decline and over a question about
    past decisions in the same clause, so it is never ticked with them."""
    decided = DECIDED.search(text) is not None
    decides = not decided and _decides(text)
    if (decided or decides) and _changes(text):
        return "change"
    if decided:
        return "decided"
    if decides:
        return "decide"
    if _asks_to_be_told(text):
        return "question"
    return "change" if _changes(text) else "other"


def clauses_of(text: str) -> list[Clause]:
    """The request's clauses in order, split at "and", "then", "while", "&", commas and full
    stops, each with what it asks. A clause of courtesy alone, such as "thanks", is no part of
    the request."""
    words = (part.strip() for part in BREAK.split(text))
    return [Clause(w, ask_of(w)) for w in words if w and not POLITE_ONLY.match(w)]


def only_of(clauses: list[Clause]) -> Literal["approve", "decline"] | None:
    """Whether a question about their decisions asks only for declines, or only for approvals."""
    asked = " ".join(c.text for c in clauses if c.ask == "decided")
    if re.search(r"declin|reject|sa(?:id|y) no", asked, re.IGNORECASE):
        return "decline"
    if re.search(r"approv|accept|sa(?:id|y) yes", asked, re.IGNORECASE) and not re.search(
        r"decid|decision", asked, re.IGNORECASE
    ):
        return "approve"
    return None
