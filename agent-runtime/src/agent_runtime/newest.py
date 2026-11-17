"""A question about the newest version of one software, as "what's new in node js?", "latest version
of redis" or "any updates for langgraph?". The platform knows a software's newest version only
once the Software watchlist holds it, so the answer is the software card: Watch it for software
the watchlist doesn't hold, and the watched software's own answer for one it holds.

The reading names the software, and code finds it in the request's words, as for a watch
(`answers._software_of`). This module reads the rest of the request, so the question is code's
reading, whatever the model made of it."""

import re
from typing import Final

from agent_runtime.abilities import RELEASE_ROOTS, words

NEWEST: Final = re.compile(
    r"(?<![\w'’-])(?:up[\s-]+to[\s-]+date|out[\s-]+of[\s-]+date|outdated|behind|newest|newer|new|"
    r"latest|recent|current|updates?|"
    + "|".join(sorted(RELEASE_ROOTS, key=len, reverse=True))
    + r")(?![\w'’-])",
    re.IGNORECASE,
)
"""Words that ask what is newest, the release words of a watch request among them."""
ASKS_ONLY: Final = words(
    "what what's whats which is isn't are aren't was has hasn't have had does do did any "
    "anything there there's theres been out available yet now lately recently currently most "
    "the a an of in on for with to at about from s we we're our us i my me you your can could "
    "would will please pls kindly just tell show know check find see run running use using"
)
"""The other words such a question may hold beside the software's name: question words, small
words and polite asks, as "can you tell me". Any other word, as "news", "email", a number or a
second name, asks for more, and the request is answered the usual way."""
LEADS: Final = words("please pls kindly just now so and can could would will you")
ORDERS: Final = words("update upgrade patch release")
"""Words that ask what is newest as nouns but order a change as verbs. First, after a polite
lead-in, they order it, as "update node" or "can you upgrade redis"."""


def asks_for_the_newest(request: str, software: str) -> str | None:
    """The word, as written, that asks for the newest version of `software` in `request`: a release
    word first, as a watch request names it, else the first word of `NEWEST`. None when the request
    asks anything more, orders a change, or glues the name to a sign, as "c" in "c++" or "NET" in
    ".NET", which makes it part of a longer name."""
    named = re.search(
        rf"(?<![\w.+#@/]){re.escape(software)}(?![\w+#@/]|\.\w)", request, re.IGNORECASE
    )
    if named is None:
        return None
    rest = f"{request[: named.start()]} {request[named.end() :]}"
    found = [m.group(0) for m in NEWEST.finditer(rest)]
    if not found or any(w not in ASKS_ONLY for w in _words(NEWEST.sub(" ", rest))):
        return None
    lead = [w for w in _words(rest) if w not in LEADS]
    if lead and lead[0] in ORDERS:
        return None
    return next((w for w in found if w.casefold() in RELEASE_ROOTS), found[0])


def _words(text: str) -> list[str]:
    flat = text.casefold().replace("’", "'")
    return [w for w in (raw.strip("'") for raw in re.findall(r"[\w'-]+", flat)) if w]
