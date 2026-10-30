"""What the platform can do, and how a part the Planner read back is held to it.

The model never writes a row the platform trusts. For each part of a task it names one ability
from `ABILITIES` and fills in that ability's parameters. The platform checks each parameter and
writes the row itself, in its own words. A part that names no ability in the table, an ability
that does not fit the part, or a parameter that does not check out is can't do. A new tool that
takes the parameters already here is one more entry.

Every parameter is a short, checked value. An enum is one of its words, a Jira key is a key the
task wrote, and a number is in bounds. Anything taken from the task's words (a kind of ticket, a
name, a topic) must be plain text that the task holds where such a value sits, and must carry no
instruction: it never starts a clause, joins one on, points back at what was found ("them", "the
rest"), names a ticket, holds a search query, holds a write word in any form, or names another
system outside the words about Jira tickets. A row is understood only when each fixed value it
shows (a day, a time, a number of days, a period, how to sum up, and that a new ticket lists what
was found) is the task's own, and its Jira project is one the platform can see. Otherwise it is
changed, and the Operator is asked to check it."""

import re
import unicodedata
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from typing import Annotated, Final, Literal, NamedTuple, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from agent_runtime.contract import RowKind

HIDDEN: Final = ("Cc", "Cf", "Cs")
INVISIBLE: Final = frozenset(
    "͏ᅟᅠ឴឵᠋᠌᠍᠏⠀ㅤﾠ" + "".join(map(chr, range(0xFE00, 0xFE10))) + "".join(map(chr, range(0xE0100, 0xE01F0)))
)


def visible(text: str | None) -> str:
    """The text as NFKC, without hidden characters, its spaces collapsed. Words in any script are
    kept whole."""
    folded = unicodedata.normalize("NFKC", text or "")
    kept = (
        c
        for c in folded
        if c.isspace() or (unicodedata.category(c) not in HIDDEN and c not in INVISIBLE)
    )
    return " ".join("".join(kept).split())


def _listed(value: object) -> object:
    return [value] if isinstance(value, str) else value


def _not_a_flag(value: object) -> object:
    return 0 if isinstance(value, bool) else value


type Listed = Annotated[list[str], BeforeValidator(_listed)]
type Days = Annotated[int | None, BeforeValidator(_not_a_flag)]


class RowAnswer(BaseModel):
    """One part of the task as the model reads it: the ability it names and its parameters."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["schedule", "look_for", "do", "where"]
    state: Literal["understood", "changed", "missing", "cant_do"]
    said: str = Field(
        default="", description="The task's own words for this part, copied as written."
    )
    ability: str | None = Field(
        default=None, description="The id of one ability from the list. Null when none fits."
    )
    every: Listed = Field(
        default_factory=list[str],
        description="run_on_a_schedule: day, weekday, weekend, week, month, quarter, year, "
        "morning, evening, or days of the week such as monday.",
    )
    at: Listed = Field(
        default_factory=list[str],
        description="run_on_a_schedule: the times, such as 3pm or 15:00.",
    )
    on: str | None = Field(
        default=None,
        description="run_on_a_schedule: which day of the period, such as first monday.",
    )
    status: str | None = Field(default=None, description="read_jira_tickets: open or closed.")
    ticket_type: str | None = Field(
        default=None,
        description="The task's words for the kind of ticket, just before the word ticket, such "
        "as bug.",
    )
    project: str | None = Field(
        default=None, description="A Jira project key the task wrote, such as MOCK."
    )
    project_name: str | None = Field(
        default=None,
        description="A Jira project or board the task names by name, such as Access Review.",
    )
    assigned_to: str | None = Field(
        default=None, description="read_jira_tickets: who the tickets are assigned to."
    )
    about: str | None = Field(
        default=None,
        description="What the tickets are about, or what the new ticket is about or lists, in "
        "the task's words.",
    )
    closed_in: str | None = Field(
        default=None,
        description="read_jira_tickets: when they were closed: today, yesterday, this week, last "
        "week, this month, last month, this quarter, last quarter, this year or last year.",
    )
    created_in: str | None = Field(
        default=None, description="read_jira_tickets: when they were created, in the same words."
    )
    no_update_days: Days = Field(
        default=None, description="read_jira_tickets: no update for this many days."
    )
    source: str | None = Field(
        default=None,
        description="read_jira_tickets: the system the tickets are in. Jira, or the other system "
        "the task names.",
    )
    how: str | None = Field(default=None, description="sum_up: summary, list, count or group.")
    by: str | None = Field(default=None, description="sum_up: what to list or group by.")
    count: str | None = Field(
        default=None, description="create_jira_ticket: one, or one_each for one per thing found."
    )
    each_of: str | None = Field(
        default=None, description="create_jira_ticket: one ticket for each of what, such as server."
    )
    lists_found: bool = Field(
        default=False, description="create_jira_ticket: true when the ticket lists what was found."
    )
    software: str | None = Field(default=None, description="check_releases: the software.")


STRING_PARAMETERS: Final = (
    "every",
    "at",
    "on",
    "status",
    "ticket_type",
    "project",
    "project_name",
    "assigned_to",
    "about",
    "closed_in",
    "created_in",
    "source",
    "how",
    "by",
    "count",
    "each_of",
    "software",
)
TASK_WORDS: Final = (
    "ticket_type",
    "about",
    "each_of",
    "by",
    "assigned_to",
    "project_name",
    "software",
    "source",
)
HARMLESS: Final = frozenset(
    ("project", "status", "closed_in", "created_in", "no_update_days", "count", "how")
)

WEEKDAYS: Final = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
EVERY: Final = frozenset(
    ("day", "weekday", "weekend", "week", "month", "quarter", "year", "morning", "evening")
    + WEEKDAYS
)
EVERY_ALSO: Final = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "quarterly": "quarter",
    "yearly": "year",
}
ORDINALS: Final = ("first", "second", "third", "fourth", "last")
ON: Final = re.compile(rf"({'|'.join(ORDINALS)}) ({'|'.join(WEEKDAYS)}|day|weekday)")
TIME: Final = re.compile(
    r"(?:1[0-2]|0?[1-9])(?::[0-5][0-9])?(?:am|pm)|(?:[01]?[0-9]|2[0-3]):[0-5][0-9]|noon|midnight"
)
TASK_TIME: Final = re.compile(
    r"(?<![\w:])(?:\d{1,2}(?::\d{2})?\s*(?:a\.?\s?m\.?|p\.?\s?m\.?)|\d{1,2}:\d{2}|noon|midnight)"
    r"(?![\w:])",
    re.IGNORECASE,
)
STATUSES: Final = {"open": "open", "closed": "closed", "done": "closed"}
PERIODS: Final = frozenset(
    f"{when} {span}" for when in ("this", "last") for span in ("week", "month", "quarter", "year")
) | {"today", "yesterday"}
HOW: Final = {
    "summary": "Sum them up",
    "list": "List them",
    "count": "Count them",
    "group": "Group them",
}
HOW_WORDS: Final = {
    "summary": r"\b(?:sum|summar)",
    "list": r"\blist",
    "count": r"\bcount",
    "group": r"\bgroup",
}
LISTS: Final = r"\b(?:list|sum|summar)"
COUNTS: Final = frozenset(("one", "one each"))
DAYS_LIMIT: Final = 3650
KEY: Final = re.compile(r"[A-Z][A-Z0-9]{1,9}")
RELEASE: Final = r"(?:releases?|versions?|upgrades?|updates?|patch(?:es)?|vulnerabilit(?:y|ies))"
SOFTWARE_AFTER: Final = re.compile(
    rf"(?:\s*['’]s)?\s+(?:(?:for|has|have|gets?|got|with)\s+)?"
    rf"(?:(?:a|an|any|new|the|latest|next|newest)\s+){{0,2}}{RELEASE}\b",
    re.IGNORECASE,
)
SOFTWARE_BEFORE: Final = re.compile(rf"\b{RELEASE}\s+(?:of|for|to|in)\s+(?:the\s+)?$", re.I)
NOT_SOFTWARE: Final = frozenset(
    ("latest", "new", "newest", "next", "current", "old", "older", "previous", "last", "our")
)

STARTS: Final = frozenset(
    [
        "and",
        "or",
        "nor",
        "then",
        "also",
        "plus",
        "but",
        "so",
        "please",
        "finally",
        "afterwards",
        "afterward",
    ]
)
TOPIC_STARTS: Final = STARTS | {"that", "which", "who", "to"}
JOINERS: Final = frozenset(
    ["then", "also", "plus", "but", "please", "finally", "afterwards", "afterward"]
)
CONJUNCTIONS: Final = frozenset(("and", "or", "nor"))
DETERMINERS: Final = frozenset(
    [
        "the",
        "a",
        "an",
        "its",
        "their",
        "his",
        "her",
        "our",
        "my",
        "your",
        "each",
        "every",
        "any",
        "some",
        "this",
        "that",
        "these",
        "those",
        "no",
        "other",
        "another",
        "all",
    ]
)
BACK: Final = frozenset(("them", "they", "it", "rest", "everything", "everyone", "everybody"))
PREPOSITIONS: Final = frozenset(
    [
        "to",
        "in",
        "on",
        "at",
        "for",
        "of",
        "with",
        "from",
        "by",
        "about",
        "into",
        "onto",
        "over",
        "under",
        "via",
        "per",
        "after",
        "before",
        "without",
        "within",
        "across",
        "against",
        "between",
        "through",
        "during",
        "like",
        "than",
        "as",
    ]
)
FUNCTION_WORDS: Final = DETERMINERS | PREPOSITIONS | CONJUNCTIONS | BACK | {"one"}
TICKET_WORDS: Final = frozenset(("ticket", "tickets"))
READS: Final = frozenset(
    [
        "find",
        "get",
        "list",
        "show",
        "count",
        "check",
        "review",
        "search",
        "look",
        "see",
        "fetch",
        "read",
        "pull",
        "gather",
        "collect",
    ]
)
TICKET_LEAD: Final = (
    DETERMINERS | READS | frozenset(STATUSES) | {"one", "new", "single", "me", "us", "for", "of"}
)
TOPIC_MARKERS: Final = frozenset(
    [
        "about",
        "regarding",
        "concerning",
        "for",
        "mention",
        "mentions",
        "mentioning",
        "listing",
        "lists",
        "where",
        "find",
        "involving",
        "covering",
    ]
)
QUESTION_WORDS: Final = frozenset(
    ("who", "what", "which", "when", "where", "why", "how", "whom", "whose")
)
QUOTES: Final = "\"“”‘’'«»"
JQL: Final = frozenset(("AND", "OR", "NOT", "ORDER", "EMPTY", "NULL"))
APOSTROPHES: Final = "'’‘"
WORDS_LIMIT: Final = 12
CHARS_LIMIT: Final = 80
LABEL_CHARS: Final = 40
NAME_WORDS: Final = 3

type Systems = Literal["never", "about_tickets", "with_tickets", "always"]


def _single(*words: str) -> frozenset[tuple[str, ...]]:
    return frozenset((word,) for word in words)


@dataclass(frozen=True)
class Spot:
    words: int
    chars: int = LABEL_CHARS
    clause_starts: frozenset[str] = STARTS
    after: frozenset[tuple[str, ...]] | None = None
    before: str | None = None
    tickets_ok: bool = False
    content_only: bool = False
    systems: Systems = "never"


TICKET_TYPE: Final = Spot(
    3, before=r"\s+tickets?", after=_single(*TICKET_LEAD), content_only=True, systems="always"
)
PROJECT_NAME: Final = Spot(5, before=r"\s+(project|board)s?", systems="always")
ASSIGNEE: Final = Spot(4, after=frozenset({("assigned", "to")}))
BY: Final = Spot(3, after=frozenset({("by",), ("per",), ("for", "each"), ("for", "every")}))
EACH_OF: Final = Spot(
    4, after=frozenset({("for", "each"), ("for", "every"), ("per",)}), content_only=True
)
SOFTWARE: Final = Spot(4, clause_starts=TOPIC_STARTS)
TOPIC: Final = Spot(
    WORDS_LIMIT,
    CHARS_LIMIT,
    clause_starts=TOPIC_STARTS,
    after=_single(*TOPIC_MARKERS),
    systems="about_tickets",
)
SAID: Final = Spot(WORDS_LIMIT, CHARS_LIMIT, tickets_ok=True, systems="with_tickets")


def _letter(c: str) -> bool:
    return c.isalnum() or unicodedata.category(c)[0] == "M"


def _in_a_word(c: str) -> bool:
    return _letter(c) or c == "-"


def _inner_joiner(text: str, at: int) -> bool:
    return (
        text[at] in f"-{APOSTROPHES}"
        and 0 < at < len(text) - 1
        and _letter(text[at - 1])
        and _letter(text[at + 1])
    )


def _tokens(text: str) -> Iterator[tuple[int, str]]:
    start, word = 0, ""
    for at, c in enumerate(text):
        if _letter(c) or (word and _inner_joiner(text, at)):
            if not word:
                start = at
            word += c
            continue
        if word:
            yield start, word
            word = ""
        if not c.isspace():
            yield at, c
    if word:
        yield start, word


def _is_word(token: str) -> bool:
    return _letter(token[0])


def _plain_chars(value: str) -> bool:
    for at, c in enumerate(value):
        if c.isalnum() or c == " " or c in "-/" or c in APOSTROPHES:
            continue
        if unicodedata.category(c)[0] == "M" and at > 0 and value[at - 1] != " ":
            continue
        inner = 0 < at < len(value) - 1 and value[at - 1].isalnum() and value[at + 1].isalnum()
        if c != "." or not inner:
            return False
    return True


def _instruction(words: list[str], spot: Spot) -> bool:
    low = [w.casefold() for w in words]
    if low[0] in spot.clause_starts or any(w in JOINERS for w in low):
        return True
    for at, word in enumerate(low):
        if word not in CONJUNCTIONS:
            continue
        after = words[at + 1] if at + 1 < len(words) else ""
        if not after or not (
            low[at + 1] in DETERMINERS or after[0].isdigit() or after[0].isupper()
        ):
            return True
    if any(
        w in BACK and not (raw.isupper() and len(raw) > 1)
        for w, raw in zip(low, words, strict=True)
    ):
        return True
    if not spot.tickets_ok and any(w in TICKET_WORDS for w in low):
        return True
    if spot.content_only and any(w in FUNCTION_WORDS for w in low):
        return True
    return any(w in JQL for w in words)


def _loosely(value: str) -> str:
    apostrophe = f"[{APOSTROPHES}]"
    return r"\s+".join(
        "".join(apostrophe if c in APOSTROPHES else re.escape(c) for c in word)
        for word in value.split()
    )


def _bounded(text: str, start: int, end: int) -> bool:
    return (start == 0 or not _in_a_word(text[start - 1])) and (
        end == len(text) or not _in_a_word(text[end])
    )


LOOK_ALIKES: Final = str.maketrans(
    dict(
        zip(
            "аеорсухіјѕԁԛԝАВЕКМНОРСТХІЈЅαβεικνορτυχΑΒΕΖΗΙΚΜΝΟΡΤΥΧ",
            "aeopcyxijsdqwABEKMHOPCTXIJSabeikvoptuxABEZHIKMNOPTYX",
            strict=True,
        )
    )
)


def _skeleton(text: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", visible(text))
    bare = "".join(c for c in decomposed if unicodedata.category(c)[0] != "M")
    return unicodedata.normalize("NFKC", bare).translate(LOOK_ALIKES)


SPACED_LETTERS: Final = re.compile(r"(?<!\w)(?:\w ){2,}\w(?!\w)")


def _parts_and_whole(word: str) -> set[str]:
    parts = [p for p in re.split(rf"[-{APOSTROPHES}]", word) if p]
    return {*parts, "".join(parts)}


def _spaced_letters_joined(text: str) -> set[str]:
    return {spaced.replace(" ", "") for spaced in SPACED_LETTERS.findall(text)}


def _words_in(text: str | None) -> set[str]:
    folded = _skeleton(text).casefold()
    words = {w for _, token in _tokens(folded) if _is_word(token) for w in _parts_and_whole(token)}
    return words | _spaced_letters_joined(folded)


class VerbForms(NamedTuple):
    orders: set[str]
    past: set[str]


def _forms(verb: str) -> VerbForms:
    stem = verb[:-1] if verb.endswith("e") else verb
    forms = VerbForms(
        orders={verb, f"{verb}s", f"{verb}es", f"{stem}ing", f"{verb}ing"},
        past={f"{stem}ed", f"{verb}d"},
    )
    if verb.endswith("y") and verb[-2:-1] not in ("a", "e", "o", "u"):
        forms.orders.add(f"{verb[:-1]}ies")
        forms.past.add(f"{verb[:-1]}ied")
    if re.fullmatch(r".*[^aeiou][aeiou][bdgklmnprt]", verb):
        forms.orders.add(f"{verb}{verb[-1]}ing")
        forms.past.add(f"{verb}{verb[-1]}ed")
    return forms


def _systems_in(text: str) -> str | None:
    skeleton = _skeleton(text)
    found = SYSTEMS_FOUND.search(skeleton.casefold()) or NAMED_FOUND.search(skeleton)
    return None if found is None else found.group(0)


def _gives_an_order(text: str) -> bool:
    return not _words_in(text).isdisjoint(ORDER_FORMS)


def _writes(text: str) -> bool:
    return not _words_in(text).isdisjoint(BARRED_FORMS)


def _places(text: str) -> bool:
    return not _words_in(text).isdisjoint(PLACES) or _systems_in(text) is not None


class Place(NamedTuple):
    name: str
    word: str


class Day(NamedTuple):
    ordinal: str
    day: str


@dataclass(frozen=True)
class _Task:
    text: str
    part: tuple[int, int] | None = None

    @classmethod
    def of(cls, task: str, said: str | None = None) -> Self:
        seen = cls(visible(task))
        found = seen.copy_of(said)
        return seen if found is None else cls(seen.text, (found.start(1), found.end(1)))

    def copies(self, value: str, end: str = "") -> list[re.Match[str]]:
        return [
            m
            for m in re.finditer(rf"({_loosely(value)}){end}", self.text, re.IGNORECASE)
            if _bounded(self.text, m.start(), m.end())
        ]

    def copy_of(self, value: str | None) -> re.Match[str] | None:
        whole = visible(value)
        for wanted in dict.fromkeys((whole, whole.strip(" " + QUOTES))):
            found = self.copies(wanted) if wanted else []
            if found:
                return found[0]
        return None

    def _words_before(self, at: int, count: int) -> list[str]:
        words: list[str] = []
        for _, token in reversed(list(_tokens(self.text[:at]))):
            if token in QUOTES and not words:
                continue
            if not _is_word(token) or len(words) == count:
                break
            words.insert(0, token.casefold())
        return words

    def _clause(self, at: int) -> tuple[list[str], list[str]]:
        tokens = list(_tokens(self.text))
        here = next((i for i, (start, _) in enumerate(tokens) if start >= at), len(tokens))

        def walk(indexes: Iterator[int]) -> list[str]:
            words: list[str] = []
            for i in indexes:
                token = tokens[i][1]
                if token in QUOTES:
                    continue
                if not _is_word(token) or token.casefold() in STARTS:
                    break
                words.append(token.casefold())
            return words

        return walk(iter(range(here - 1, -1, -1))), walk(iter(range(here, len(tokens))))

    def about_tickets(self, at: int) -> bool:
        before, _ = self._clause(at)
        return not TICKET_WORDS.isdisjoint(before)

    def _in_place(self, found: re.Match[str], words: list[str], spot: Spot) -> bool:
        before = self._words_before(found.start(1), 2)
        if not before or before[-1] in spot.clause_starts:
            return False
        if spot.after is None:
            return True
        if not any(tuple(before[-len(lead) :]) == lead for lead in spot.after):
            return False
        return not (before[-1] == "find" and words[0].casefold() in QUESTION_WORDS)

    def _systems_ok(self, value: str, found: re.Match[str], spot: Spot) -> bool:
        if _systems_in(value) is None:
            return True
        match spot.systems:
            case "always":
                return True
            case "about_tickets":
                return self.about_tickets(found.start(1))
            case "with_tickets":
                return not TICKET_WORDS.isdisjoint(w.casefold() for w in value.split())
            case "never":
                return False

    def find(self, value: str, spot: Spot) -> re.Match[str] | None:
        said = visible(value).strip(" " + QUOTES)
        words = said.split()
        if not words or len(words) > spot.words or len(said) > spot.chars:
            return None
        if not _plain_chars(said) or _instruction(words, spot) or _writes(said):
            return None
        found = self.copies(said, spot.before or rf"(?:e?s|[{APOSTROPHES}]s)?")
        part = self.part
        inside = [m for m in found if part and part[0] <= m.start(1) and m.end(1) <= part[1]]
        placed = (
            m
            for m in inside or found
            if self._in_place(m, words, spot) and self._systems_ok(said, m, spot)
        )
        return next(placed, None)

    def quote(self, value: str, spot: Spot) -> str | None:
        found = self.find(value, spot)
        return None if found is None else found.group(1)

    def software(self, value: str) -> str | None:
        found = self.find(value, SOFTWARE)
        if found is None or found.group(1).split()[0].casefold() in NOT_SOFTWARE | FUNCTION_WORDS:
            return None
        named = SOFTWARE_AFTER.match(self.text, found.end(1)) or SOFTWARE_BEFORE.search(
            self.text[: found.start(1)]
        )
        return None if named is None else found.group(1)

    def project_name(self, value: str) -> Place | None:
        name = visible(value)
        name = name[4:] if name.casefold().startswith("the ") else name
        found = self.find(name, PROJECT_NAME)
        if found is None or found.group(1).split()[0].casefold() in FUNCTION_WORDS:
            return None
        system = _systems_in(found.group(1))
        if system is not None and system.casefold() == _skeleton(found.group(1)).casefold():
            return None
        return Place(found.group(1), found.group(2).casefold())

    def status(self, value: str) -> str:
        wanted = STATUSES[_one_of(STATUSES, value)]
        words = [word for word, status in STATUSES.items() if status == wanted]
        for found in re.finditer(rf"(?<![\w-])(?:{'|'.join(words)})(?![\w-])", self.text, re.I):
            before, after = self._clause(found.start())
            if not TICKET_WORDS.isdisjoint(before + after):
                return wanted
        raise _Bad

    def name_anywhere(self, value: str) -> str | None:
        said = visible(value)
        if not said or len(said.split()) > NAME_WORDS or not _plain_chars(said):
            return None
        found = self.copies(said)
        return None if not found else found[0].group(1)

    def has_key(self, key: str) -> bool:
        return re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", self.text) is not None

    def own(self, pattern: str) -> bool:
        return re.search(pattern, self.text, re.IGNORECASE) is not None


def _word(value: str | None) -> str:
    return " ".join(visible(value).casefold().replace("_", " ").replace("-", " ").split())


@dataclass(frozen=True)
class Parameters:
    """A row's parameters after every check, in the forms the platform writes."""

    every: tuple[str, ...] = ()
    at: tuple[str, ...] = ()
    on: Day | None = None
    status: str | None = None
    ticket_type: str | None = None
    project: str | None = None
    project_name: Place | None = None
    assigned_to: str | None = None
    about: str | None = None
    closed_in: str | None = None
    created_in: str | None = None
    no_update_days: int | None = None
    how: str | None = None
    by: str | None = None
    count: str | None = None
    each_of: str | None = None
    lists_found: bool = False
    software: str | None = None


class _Bad(Exception):
    pass


def _ok[T](value: T | None) -> T:
    if value is None:
        raise _Bad
    return value


def _given(value: str | list[str] | int | bool | None) -> bool:
    if isinstance(value, list):
        return any(visible(v) for v in value)
    if isinstance(value, str):
        return bool(visible(value))
    return value is not None and value is not False


def _maybe[T](value: str | None, check: Callable[[str], T]) -> T | None:
    return check(value) if value is not None and visible(value) else None


def _every_word(value: str) -> str:
    word = _word(value)
    word = EVERY_ALSO.get(word, word)
    return word[:-1] if word not in EVERY and word.endswith("s") and word[:-1] in EVERY else word


def _every(values: list[str]) -> tuple[str, ...]:
    out = [_every_word(value) for value in values]
    if not all(word in EVERY for word in out):
        raise _Bad
    return tuple(dict.fromkeys(out))


def _time(value: str) -> str:
    return _word(value).replace(" ", "").replace(".", "")


def _at(values: list[str]) -> tuple[str, ...]:
    times = tuple(_time(v) for v in values)
    if len(times) > 4 or not all(TIME.fullmatch(t) for t in times):
        raise _Bad
    return times


def _on(value: str) -> Day:
    found = _ok(ON.fullmatch(_word(value).removeprefix("the ")))
    return Day(found.group(1), found.group(2))


def _key(value: str, task: _Task) -> str:
    key = visible(value)
    if KEY.fullmatch(key) is None or not task.has_key(key) or _systems_in(key):
        raise _Bad
    return key


def _days(value: int | None) -> int | None:
    if value is not None and not 1 <= value <= DAYS_LIMIT:
        raise _Bad
    return value


def _jira(value: str) -> None:
    if _word(value) != "jira":
        raise _Bad


def _one_of(words: Collection[str], value: str) -> str:
    word = _word(value)
    if word not in words:
        raise _Bad
    return word


def _present(row: RowAnswer) -> list[str]:
    named = [name for name in STRING_PARAMETERS if _given(getattr(row, name))]
    if row.no_update_days is not None:
        named.append("no_update_days")
    if row.lists_found:
        named.append("lists_found")
    return named


def _checked(row: RowAnswer, task: _Task, takes: Collection[str]) -> Parameters | None:
    def quoted(value: str | None, spot: Spot) -> str | None:
        return _maybe(value, lambda v: _ok(task.quote(v, spot)))

    def status(value: str) -> str:
        return task.status(value) if "status" in takes else STATUSES[_one_of(STATUSES, value)]

    try:
        _maybe(row.source, _jira)
        return Parameters(
            every=_every([v for v in row.every if visible(v)]),
            at=_at([v for v in row.at if visible(v)]),
            on=_maybe(row.on, _on),
            status=_maybe(row.status, status),
            ticket_type=quoted(row.ticket_type, TICKET_TYPE),
            project=_maybe(row.project, lambda v: _key(v, task)),
            project_name=_maybe(row.project_name, lambda v: _ok(task.project_name(v))),
            assigned_to=quoted(row.assigned_to, ASSIGNEE),
            about=quoted(row.about, TOPIC),
            closed_in=_maybe(row.closed_in, lambda v: _one_of(PERIODS, v)),
            created_in=_maybe(row.created_in, lambda v: _one_of(PERIODS, v)),
            no_update_days=_days(row.no_update_days),
            how=_maybe(row.how, lambda v: _one_of(HOW, v)),
            by=quoted(row.by, BY),
            count=_maybe(row.count, lambda v: _one_of(COUNTS, v)),
            each_of=quoted(row.each_of, EACH_OF),
            lists_found=row.lists_found,
            software=_maybe(row.software, lambda v: _ok(task.software(v))),
        )
    except _Bad:
        return None


def _every_in(word: str, task: _Task) -> bool:
    return any(_every_word(w) == word for w in re.findall(r"[^\W\d_]+", task.text))


def _fixed_values_in_task(p: Parameters, takes: Collection[str], task: _Task) -> bool:
    times = {_time(t) for t in TASK_TIME.findall(task.text)}
    days = p.no_update_days
    in_task = {
        "every": all(_every_in(word, task) for word in p.every),
        "at": all(time in times for time in p.at),
        "on": p.on is None or task.own(rf"\b{p.on.ordinal}\s+{p.on.day}s?\b"),
        "no_update_days": days is None or task.own(rf"(?<!\d){days}(?!\d)"),
        "closed_in": p.closed_in is None or task.own(rf"\b{p.closed_in}\b"),
        "created_in": p.created_in is None or task.own(rf"\b{p.created_in}\b"),
        "how": p.how is None or task.own(HOW_WORDS[p.how]),
        "lists_found": not p.lists_found or task.own(LISTS),
    }
    return all(held for name, held in in_task.items() if name in takes)


def _unseen(p: Parameters, takes: Collection[str], projects: Collection[str] | None) -> list[str]:
    unseen: list[str] = []
    if p.project is not None and "project" in takes:
        if projects is None:
            unseen.append(f"I can't check that {p.project} is a Jira project.")
        elif p.project not in projects:
            unseen.append(f"I can't find a Jira project {p.project}.")
    if p.project_name is not None:
        unseen.append(
            f"I can't check that the {p.project_name.name} {p.project_name.word} is in Jira."
        )
    return unseen


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _day(word: str) -> str:
    return word.capitalize() if word in WEEKDAYS else word


def _schedule(p: Parameters) -> str | None:
    if not p.every:
        return None
    text = f"Every {_and([_day(w) for w in p.every])}"
    if p.on is not None:
        text += f", on the {p.on.ordinal} {_day(p.on.day)}"
    if p.at:
        text += f" at {_and(list(p.at))}"
    return text


def _in(p: Parameters) -> str:
    if p.project is not None:
        return f" in {p.project}"
    if p.project_name is not None:
        return f" in the {p.project_name.name} {p.project_name.word}"
    return ""


def _search(p: Parameters) -> str:
    status = p.status if p.status and not (p.status == "closed" and p.closed_in) else None
    lead = " ".join(w for w in (status, p.ticket_type) if w)
    text = f"{lead} tickets" if lead else "Tickets"
    text += _in(p)
    if p.assigned_to:
        text += f" assigned to {p.assigned_to}"
    if p.about:
        text += f" about “{p.about}”"
    if p.closed_in:
        text += f" closed {p.closed_in}"
    if p.created_in:
        text += f" created {p.created_in}"
    if p.no_update_days is not None:
        days = "day" if p.no_update_days == 1 else "days"
        text += f" with no update for {p.no_update_days} {days}"
    return text


def _sum_up(p: Parameters) -> str:
    text = HOW[p.how or "summary"]
    return f"{text} by {p.by}" if p.by else text


def _releases(p: Parameters) -> str | None:
    return None if p.software is None else f"Check {p.software} for new releases"


def _new_ticket(p: Parameters) -> str:
    text = f"Create one {p.ticket_type} ticket" if p.ticket_type else "Create one ticket"
    if p.each_of:
        text += f" for each {p.each_of}"
    elif p.count == "one each":
        text += " for each one found"
    text += _in(p)
    if p.lists_found:
        text += " that lists them"
    if p.about:
        text += f" about “{p.about}”"
    return text


def _ticket_place(p: Parameters) -> str:
    if p.project is not None:
        return f"Jira project {p.project}"
    if p.project_name is not None:
        return f"The {p.project_name.name} {p.project_name.word} in Jira"
    return "A new Jira ticket"


@dataclass(frozen=True)
class Form:
    """How an ability fits one kind of row: what it is, the parameters it takes, and the row's
    text from them, or None when a parameter it needs is missing."""

    what: str
    takes: tuple[str, ...]
    write: Callable[[Parameters], str | None]


@dataclass(frozen=True)
class Ability:
    id: str
    plain: str | None
    forms: Mapping[RowKind, Form]


SEARCH: Final = (
    "status",
    "ticket_type",
    "project",
    "project_name",
    "assigned_to",
    "about",
    "closed_in",
    "created_in",
    "no_update_days",
    "source",
)
NEW_TICKET: Final = (
    "count",
    "ticket_type",
    "each_of",
    "project",
    "project_name",
    "lists_found",
    "about",
)
ABILITIES: Final = (
    Ability(
        "run_on_a_schedule",
        None,
        {"schedule": Form("when the task runs.", ("every", "at", "on"), _schedule)},
    ),
    Ability(
        "read_jira_tickets",
        "read Jira tickets",
        {"look_for": Form("a search of Jira tickets.", SEARCH, _search)},
    ),
    Ability(
        "sum_up",
        "sum up what I find",
        {
            "do": Form("sum up what was found, in the run's report.", ("how", "by"), _sum_up),
            "where": Form("the run's report.", (), lambda _: "The run's report"),
        },
    ),
    Ability(
        "check_releases",
        "check software for new releases",
        {"do": Form("check software for new releases.", ("software",), _releases)},
    ),
    Ability(
        "create_jira_ticket",
        "create a Jira ticket after a yes",
        {
            "do": Form(
                "propose one new Jira ticket, or one for each thing found. An Approver must say "
                "yes before it is made.",
                NEW_TICKET,
                _new_ticket,
            ),
            "where": Form(
                "the Jira project the new ticket goes in.",
                ("project", "project_name"),
                _ticket_place,
            ),
        },
    ),
)

BARRED_AS_ORDERS: Final = (
    "close",
    "delete",
    "remove",
    "erase",
    "purge",
    "wipe",
    "clear",
    "nuke",
    "destroy",
    "discard",
    "trash",
    "kill",
    "cancel",
    "archive",
    "approve",
    "reject",
    "decline",
    "deny",
    "revoke",
    "resolve",
    "reopen",
    "reassign",
    "unassign",
    "merge",
    "deploy",
    "restart",
    "reboot",
    "shut",
    "shutdown",
    "uninstall",
    "revert",
    "rollback",
    "escalate",
    "edit",
    "modify",
    "rename",
    "rid",
)
BARRED_ONLY_IN_VALUES: Final = (
    "open",
    "post",
    "put",
    "send",
    "publish",
    "upload",
    "add",
    "attach",
    "append",
    "insert",
    "forward",
    "invite",
    "ask",
    "tell",
    "nudge",
    "remind",
    "notify",
    "give",
    "assign",
    "apply",
    "install",
    "fix",
    "trigger",
    "execute",
    "drop",
)
IRREGULAR_PAST: Final = ("sent", "gave", "given", "told")
SYSTEMS: Final = (
    "slack",
    "confluence",
    "github",
    "gitlab",
    "entra",
    "basecamp",
    r"monday\.com",
    "whatsapp",
    "sharepoint",
    "gmail",
    "servicenow",
    "trello",
    "asana",
    "bitbucket",
    "jenkins",
    "telegram",
    "discord",
    "webex",
    "yammer",
    "onedrive",
    "dropbox",
    "google sheets?",
    "google docs?",
    "google drive",
    "intranet",
    "spreadsheets?",
)
NAMED_SYSTEMS: Final = ("Teams", "Linear", "Notion", "Outlook", "Zoom", "Excel")
PLACES: Final = frozenset(
    [
        "channel",
        "chat",
        "room",
        "page",
        "sheet",
        "wiki",
        "inbox",
        "email",
        "mail",
        "site",
        "group",
        "folder",
        "drive",
        "document",
        "doc",
        "dm",
        "thread",
        "sms",
        "text",
    ]
)

ORDER_FORMS: Final = frozenset(form for verb in BARRED_AS_ORDERS for form in _forms(verb).orders)
BARRED_FORMS: Final = frozenset(
    form
    for forms in map(_forms, BARRED_AS_ORDERS + BARRED_ONLY_IN_VALUES)
    for form in forms.orders | forms.past
) | frozenset(IRREGULAR_PAST)
SYSTEMS_FOUND: Final = re.compile(rf"(?<![\w.-])(?:{'|'.join(SYSTEMS)})(?![\w-])")
NAMED_FOUND: Final = re.compile(
    rf"(?<![\w-])(?:{'|'.join(NAMED_SYSTEMS + tuple(n.upper() for n in NAMED_SYSTEMS))})(?![\w-])"
)


def can_only(abilities: tuple[Ability, ...] = ABILITIES) -> str:
    plain = [a.plain for a in abilities if a.plain]
    listed = plain[0] if len(plain) == 1 else f"{', '.join(plain[:-1])}, and {plain[-1]}"
    return f"I can only {listed}."


CAN: Final = can_only()


def abilities_text(abilities: tuple[Ability, ...] = ABILITIES) -> str:
    lines: list[str] = []
    for ability in abilities:
        for kind, form in ability.forms.items():
            takes = f" Parameters: {', '.join(form.takes)}." if form.takes else ""
            lines.append(f"- {ability.id}, for a {kind} row: {form.what}{takes}")
    return "\n".join(lines)


def _form(row: RowAnswer, abilities: tuple[Ability, ...]) -> Form | None:
    named = _word(row.ability).replace(" ", "_")
    ability = next((a for a in abilities if a.id == named), None)
    return None if ability is None else ability.forms.get(row.kind)


def _unused_ok(name: str, row: RowAnswer) -> bool:
    return name in HARMLESS or (name == "source" and _word(row.source) == "jira")


def _holds_more(part: str, kind: RowKind) -> bool:
    if _gives_an_order(part):
        return True
    if kind == "where":
        return _places(part)
    return _systems_in(part) is not None and TICKET_WORDS.isdisjoint(_words_in(part))


class Reading(NamedTuple):
    """A row the platform can do, in its own words. `fixed_values_in_task` is false when a day,
    time, number of days, period, way of summing up, or "lists them" that the row shows is not in
    the task, and `unseen` says what the platform could not check in Jira."""

    text: str
    fixed_values_in_task: bool
    unseen: tuple[str, ...]


def reading(
    row: RowAnswer,
    task: str,
    abilities: tuple[Ability, ...] = ABILITIES,
    *,
    projects: Collection[str] | None = None,
) -> Reading | None:
    """The row in the platform's own words, or None when the platform can't do it: the ability
    is not in the table or does not fit the row, a parameter does not check out, the row carries
    a value the ability does not take, a value the ability needs is missing, or the task's own
    words for the part say more than the ability does."""
    form = _form(row, abilities)
    if form is None:
        return None
    if any(n not in form.takes and not _unused_ok(n, row) for n in _present(row)):
        return None
    seen = _Task.of(task, row.said)
    if seen.part is not None and _holds_more(seen.text[seen.part[0] : seen.part[1]], row.kind):
        return None
    checked = _checked(row, seen, form.takes)
    if checked is None:
        return None
    text = form.write(checked)
    if text is None:
        return None
    return Reading(
        text[:1].upper() + text[1:],
        _fixed_values_in_task(checked, form.takes, seen),
        tuple(_unseen(checked, form.takes, projects)),
    )


def written(
    row: RowAnswer,
    task: str,
    abilities: tuple[Ability, ...] = ABILITIES,
    *,
    projects: Collection[str] | None = None,
) -> str | None:
    """The row's text in the platform's own words, or None when the platform can't do it."""
    found = reading(row, task, abilities, projects=projects)
    return None if found is None else found.text


def said_in(text: str, task: str) -> str | None:
    """The task's own words for a part, when the model's quote of them checks out and holds no
    write. It may name another system only when it also says tickets."""
    return _Task(visible(task)).quote(text, SAID)


def own_words(row: RowAnswer, task: str) -> str | None:
    """The task's own words for a part the platform can't do: the model's copy of them when the
    task holds it, or else the longest value of the row that the task holds."""
    seen = _Task(visible(task))
    values = [v for name in TASK_WORDS if isinstance(v := getattr(row, name), str)]
    for value in (row.said, *sorted(values, key=len, reverse=True)):
        found = seen.copy_of(value)
        if found is not None:
            return found.group(1)
    return None


def refusal(row: RowAnswer, task: str, abilities: tuple[Ability, ...] = ABILITIES) -> str:
    """The plain note for a part the platform can't do."""
    can = can_only(abilities)
    seen = _Task(visible(task))
    if row.source is not None and _word(row.source) != "jira":
        source = seen.name_anywhere(row.source)
        if source is not None:
            return f"I can't read {source} yet. {can}"
    if row.kind == "look_for":
        named = (own_words(row, task), row.project, row.project_name)
        system = next((s for v in named if v and (s := _systems_in(v))), None)
        shown = None if system is None else seen.name_anywhere(system)
        if shown is not None:
            return f"I can't read {shown} yet. {can}"
    if row.kind == "where":
        return f"I can't put results there yet. {can}"
    return f"I can't do this yet. {can}"
