"""A question about the newest version of one software, as "what's new in node js?", "latest version
of redis" or "any updates for langgraph?". The platform knows a software's newest version only
once the Software watchlist holds it, so the answer is the software card: Watch it for software
the watchlist doesn't hold, and the watched software's own answer for one it holds.

The model names the software, and code finds it in the request's words, as for a watch
(`answers._newest_of`). This module checks the rest of the request's words."""

import re
from typing import Final

from agent_runtime.abilities import RELEASE_ROOTS, other_release_source, other_systems, words
from agent_runtime.monitoring.masking import KEY_SHAPES
from agent_runtime.parts import a_lone_write
from agent_runtime.reading import clauses_of, polite
from agent_runtime.removals import name_key

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
    "would will please pls kindly just tell show know check find see run running use using if "
    "whether"
)
"""The other words such a question may hold beside the software's name: question words, small
words, pronouns, polite asks, and the verbs of a question, as "can you tell me" or "which version
do we run". Any other word, as "news", "email", a number or a second name, asks for more, and
the request is answered the usual way."""
LEADS: Final = words("please pls kindly just now so and can could would will you")
ORDERS: Final = words("update upgrade patch release run use")
"""Words that order a change or a use when they come first, after any of `LEADS`, as "update
node", "can you upgrade redis" or "use the latest node js". Elsewhere they ask, as "any update on
redis" or "which version do we run"."""
ARTICLES: Final = words("the a an")
NOT_NAMES: Final = frozenset(
    name_key(name)
    for name in (
        "Planner",
        "Portal",
        "Home",
        "watchlist",
        "Software watchlist",
        "live activity view",
        "activity view",
        "AI troubleshooter",
        "troubleshooter",
        "approval gate",
        "safety checker",
        "Agent API",
        "AI workflow builder",
        "workflow builder",
        "Needs you",
        "news",
    )
)
"""The platform's own names in GLOSSARY.md, and "news", which a model may read as the name in a
question that is not about software, as "latest news"."""


def asks_for_the_newest(request: str, software: str) -> str | None:
    """The word, as written, that asks for the newest version of `software` in `request`: a release
    word first, as a watch request names it, else the first word of `NEWEST`. None when the request
    asks anything more, in any clause, or orders a change; when it names a system the platform
    doesn't reach or a release source it doesn't read, which keep their can't, or holds a key;
    when the name is one of the platform's own, or a word of `NEWEST` or `ASKS_ONLY`, as "current"
    read from "is the version current?"; or when the name is glued to a sign, as "c" in "c++" or
    "NET" in ".NET", which makes it part of a longer name."""
    if name_key(software) in NOT_NAMES or other_systems(request) or KEY_SHAPES.search(request):
        return None
    if NEWEST.fullmatch(software) or software.casefold() in ASKS_ONLY:
        return None
    if other_release_source(request):
        return None
    if a_lone_write(request):
        return None
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
    if lead and (lead[0] in ORDERS or (lead[0] == "do" and lead[1:2] and lead[1] in ARTICLES)):
        return None
    if not all(_asks_in(request, clause, named.span()) for clause in clauses_of(request)):
        return None
    return next((w for w in found if w.casefold() in RELEASE_ROOTS), found[0])


def _asks_in(request: str, clause: tuple[int, int], name: tuple[int, int]) -> bool:
    """Whether a clause is part of the question: it holds the name or a word of `NEWEST`, or it
    only says please. "check now" after the question asks for more than the card does."""
    said = request[clause[0] : clause[1]]
    return polite(said) or clause[0] <= name[0] < clause[1] or NEWEST.search(said) is not None


def _words(text: str) -> list[str]:
    flat = text.casefold().replace("’", "'")
    return [w for w in (raw.strip("'") for raw in re.findall(r"[\w'-]+", flat)) if w]
