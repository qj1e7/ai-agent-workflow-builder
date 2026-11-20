"""The words that ask to watch software (ADR 0042): the verbs that start a watch request, and words
that ask only to watch "it" or "them"."""

import re
from typing import Final

from agent_runtime.planner import visible_words

WATCH_VERBS: Final = (
    "add",
    "watch",
    "track",
    "monitor",
    "follow",
    "check",
    "keep an eye on",
    "keep track of",
    "keep tabs on",
)
"""Verbs that start a watch request. The model's reading of one is taken only when the request
says it and names the software."""
_VERB_PATTERN: Final = "|".join(r"\s+".join(v.split()) for v in WATCH_VERBS)
_IT: Final = r"it|this(?:\s+one)?|that(?:\s+one)?"
_FEW: Final = r"two|three|four|five"
_THEM: Final = (
    r"them(?:\s+(?:all|both))?|['’]?em|"
    rf"(?:those|these)(?:\s+(?:ones|{_FEW}))?|both(?:\s+of\s+them)?|"
    rf"all(?:\s+(?:of\s+)?(?:them|those|these|{_FEW}))?|each(?:\s+(?:one|of\s+them))?|"
    rf"the\s+(?:{_FEW})(?:\s+of\s+them)?"
)
"""Words that point at more than one thing, so they can't mean one software."""
_POLITE_TAIL: Final = r"(?:\s+(?:please|pls|for\s+me|for\s+us|too|as\s+well|also|now))*"


def _only_watching(pronoun: str, verbs: str) -> re.Pattern[str]:
    return re.compile(
        r"^\W*(?:(?:and|then|also|so|please|pls|now|(?:can|could|would)\s+you|help\s+me)\s+)*"
        rf"(?P<verb>{verbs})\s+(?:{pronoun}){_POLITE_TAIL}\W*$",
        re.IGNORECASE,
    )


_WATCHES_IT: Final = _only_watching(_IT, _VERB_PATTERN)
_WATCHES_THEM: Final = _only_watching(_THEM, rf"{_VERB_PATTERN}|keep")
A_WATCH_OF_IT: Final = re.compile(
    rf"\b(?:{_VERB_PATTERN})\s+(?:{_IT})\b{_POLITE_TAIL}", re.IGNORECASE
)
"""A watch of "it" anywhere in the words, as "keep track of it please"."""


def watches_it(words: str) -> str | None:
    """The watch verb, as written, of words that ask only to watch "it", as "keep track of it" or
    "please monitor this one": a watch of the one software named beside them, or in the turn
    before. A word more, as a time or another verb, and they ask for more. "them" is not "it"
    (`watches_them`)."""
    found = _WATCHES_IT.match(visible_words(words))
    return None if found is None else found.group("verb")


def watches_them(words: str) -> str | None:
    """The watch verb, as written, of words that ask only to watch more than one thing, as "track
    them", "follow both" or "keep all of them". A plural can't mean one software, so they never
    take the software named beside them or in the turn before."""
    found = _WATCHES_THEM.match(visible_words(words))
    return None if found is None else found.group("verb")


ONLY_WATCH_VERBS: Final = (
    "watch",
    "track",
    "monitor",
    "keep an eye on",
    "keep track of",
    "keep tabs on",
)
"""The watch verbs that ask for nothing but a watch. "add", "check", "follow" and a bare "keep"
ask for other things too, as "check them all" or "keep the two"."""
_ONLY_WATCH_PATTERN: Final = "|".join(r"\s+".join(v.split()) for v in ONLY_WATCH_VERBS)


def surely_watches_them(words: str) -> bool:
    """Whether the words only ask to watch more than one thing (`watches_them`), with a verb that
    asks for nothing but a watch."""
    verb = watches_them(words)
    return verb is not None and " ".join(verb.casefold().split()) in ONLY_WATCH_VERBS


def asks_to_watch(words: str) -> bool:
    """Whether the words hold a verb that asks for nothing but a watch (`ONLY_WATCH_VERBS`)."""
    return re.search(rf"(?<!\w)(?:{_ONLY_WATCH_PATTERN})(?!\w)", words, re.IGNORECASE) is not None


def watch_verb_in(words: str) -> str | None:
    """The first of `WATCH_VERBS` the words write, as written."""
    found = re.search(rf"(?<!\w)(?:{_VERB_PATTERN})(?!\w)", words, re.IGNORECASE)
    return None if found is None else found.group(0)
