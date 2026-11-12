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

BREAK: Final = re.compile(r"\b(?:and|then|also|but|plus)\b|[,;?!]+|\.(?=\s|$)", re.IGNORECASE)
POLITE_ONLY: Final = re.compile(
    r"^(?:please|thanks?|thank you|cheers|ok(?:ay)?|hi|hello|hey)$", re.IGNORECASE
)
DECIDED: Final = re.compile(
    r"\b(?:did|have) i\b.*\b(?:decid|approv|declin|reject|accept|said (?:yes|no))\w*"
    r"|\bwhat i (?:decided|approved|declined|rejected)\b"
    r"|\b(?:past|recent|earlier|previous|last|old) (?:decisions?|approvals?)\b"
    r"|\bmy decisions?\b",
    re.IGNORECASE,
)
"""A question about the person's own decisions: "What did I decide before?", "did I decline
anything?", "show my past decisions"."""
DECIDE: Final = re.compile(
    r"\b(?:approve|decline|reject|accept|sign off|say (?:yes|no) to)\b", re.IGNORECASE
)
"""An approve or decline, whatever it names. Nobody decides in the chat, so it goes to the
request."""
SKIPPING: Final = re.compile(
    r"\b(?:automatic\w*|always|from now on|skip\w*|without|by itself|pre-?approved|no need)\b",
    re.IGNORECASE,
)
"""Words that ask for a yes to give itself, as "approve it automatically". That is the refusal's,
not a decision to go and make on the request."""
COURTESY: Final = re.compile(
    r"^(?:(?:please|ok(?:ay)?|so|now|hi|hey)\b[,\s]*)*"
    r"(?:(?:can|could|would|will) you\s+(?:please\s+)?)?",
    re.IGNORECASE,
)
QUESTION: Final = re.compile(
    r"^(?:which|what|what's|whats|how|how's|is|are|was|were|do|does|did|when|where|why|who|whose|"
    r"has|have|any|anything|show|list|tell|give|let me (?:see|know))\b",
    re.IGNORECASE,
)
"""A clause that asks to be told something. "Can you show me ..." asks too."""
CHANGE: Final = re.compile(
    r"\b(?:set\s+up|setup|set|make|change|turn|switch|move|rename|pause|resume|stop|start|"
    r"restart|run|retry|delete|remove|cancel|disable|enable|edit|update|upgrade|add|create|"
    r"watch|track|monitor|follow|schedule|reschedule|report|send|post|e-?mail|raise|file|"
    r"assign|close|put|keep)\b",
    re.IGNORECASE,
)
"""A word that asks for something to be set up or changed."""


@dataclass(frozen=True)
class Clause:
    text: str
    ask: Ask


def ask_of(text: str) -> Ask:
    if DECIDED.search(text):
        return "decided"
    if DECIDE.search(text):
        return "decide"
    if QUESTION.match(COURTESY.sub("", text, count=1)):
        return "question"
    return "change" if CHANGE.search(text) else "other"


def clauses_of(text: str) -> list[Clause]:
    """The request's clauses in order, split at "and", "then", commas and full stops, each with
    what it asks. A clause of courtesy alone, such as "thanks", is no part of the request."""
    words = (part.strip() for part in BREAK.split(text))
    return [Clause(w, ask_of(w)) for w in words if w and not POLITE_ONLY.match(w)]


def only_of(clauses: list[Clause]) -> Literal["approve", "decline"] | None:
    """Whether a question about their decisions asks only for declines, or only for approvals."""
    asked = " ".join(c.text for c in clauses if c.ask == "decided")
    if re.search(r"declin|reject|said no", asked, re.IGNORECASE):
        return "decline"
    if re.search(r"approv|accept|said yes", asked, re.IGNORECASE) and not re.search(
        r"decid|decision", asked, re.IGNORECASE
    ):
        return "approve"
    return None
