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
rest"), names a ticket, or holds a search query."""

import re
import unicodedata
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Annotated, Final, Literal, NamedTuple

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from agent_runtime.contract import RowKind

HIDDEN: Final = ("Cc", "Cf", "Cs")
INVISIBLE: Final = frozenset(
    "\u034f\u115f\u1160\u17b4\u17b5\u180b\u180c\u180d\u180f\u2800\u3164\uffa0"
    + "".join(map(chr, range(0xFE00, 0xFE10)))
    + "".join(map(chr, range(0xE0100, 0xE01F0)))
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


type Listed = Annotated[list[str], BeforeValidator(_listed)]


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
    no_update_days: int | None = Field(
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
COUNTS: Final = frozenset(("one", "one each"))
DAYS_LIMIT: Final = 3650
KEY: Final = re.compile(r"[A-Z][A-Z0-9]{1,9}")

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
JQL: Final = frozenset(("AND", "OR", "NOT", "ORDER", "EMPTY", "NULL"))
APOSTROPHES: Final = "'’‘"
WORDS_LIMIT: Final = 12
CHARS_LIMIT: Final = 80
LABEL_CHARS: Final = 40
NAME_WORDS: Final = 3


@dataclass(frozen=True)
class Spot:
    words: int
    chars: int = LABEL_CHARS
    not_after: frozenset[str] = STARTS
    only_after: frozenset[str] | None = None
    before: str | None = None
    tickets_ok: bool = False
    content_only: bool = False


TICKET_TYPE: Final = Spot(3, before=r"\s+tickets?", content_only=True)
PROJECT_NAME: Final = Spot(5, before=r"\s+(project|board)s?")
ASSIGNEE: Final = Spot(4, only_after=frozenset(("to", "by")))
BY: Final = Spot(3, only_after=frozenset(("by", "per", "each")))
EACH_OF: Final = Spot(4, only_after=frozenset(("each", "every")), content_only=True)
SOFTWARE: Final = Spot(4, not_after=TOPIC_STARTS)
TOPIC: Final = Spot(WORDS_LIMIT, CHARS_LIMIT, not_after=TOPIC_STARTS)
SAID: Final = Spot(WORDS_LIMIT, CHARS_LIMIT, tickets_ok=True)


def _plain_chars(value: str) -> bool:
    for at, c in enumerate(value):
        if c.isalnum() or c == " " or c in "-/" or c in APOSTROPHES:
            continue
        inner = 0 < at < len(value) - 1 and value[at - 1].isalnum() and value[at + 1].isalnum()
        if c != "." or not inner:
            return False
    return True


def _instruction(words: list[str], spot: Spot) -> bool:
    low = [w.casefold() for w in words]
    if low[0] in spot.not_after or any(w in JOINERS for w in low):
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


class Place(NamedTuple):
    name: str
    word: str


class Day(NamedTuple):
    ordinal: str
    day: str


@dataclass(frozen=True)
class _Task:
    text: str

    def _out_of_place(self, at: int, spot: Spot) -> bool:
        word = re.search(rf"[\w{APOSTROPHES}-]+$", self.text[:at].rstrip(' "“‘'))
        if word is None:
            return True
        last = word.group(0).casefold()
        if spot.only_after is not None:
            return last not in spot.only_after
        return last in spot.not_after

    def _find(self, value: str, spot: Spot) -> re.Match[str] | None:
        said = visible(value).strip(" " + APOSTROPHES + '"“”')
        words = said.split()
        if not words or len(words) > spot.words or len(said) > spot.chars:
            return None
        if not _plain_chars(said) or _instruction(words, spot):
            return None
        end = spot.before or rf"(?:e?s|[{APOSTROPHES}]s)?"
        found = list(
            re.finditer(
                rf"(?<![\w{APOSTROPHES}-])({_loosely(said)}){end}(?![\w{APOSTROPHES}-])",
                self.text,
                re.IGNORECASE,
            )
        )
        if not found or any(self._out_of_place(m.start(), spot) for m in found):
            return None
        return found[0]

    def quote(self, value: str, spot: Spot) -> str | None:
        found = self._find(value, spot)
        return None if found is None else found.group(1)

    def project_name(self, value: str) -> Place | None:
        name = visible(value)
        found = self._find(name[4:] if name.casefold().startswith("the ") else name, PROJECT_NAME)
        return None if found is None else Place(found.group(1), found.group(2).casefold())

    def name_anywhere(self, value: str) -> str | None:
        said = visible(value)
        if not said or len(said.split()) > NAME_WORDS or not _plain_chars(said):
            return None
        found = re.search(
            rf"(?<![\w{APOSTROPHES}-])({_loosely(said)})(?![\w{APOSTROPHES}-])",
            self.text,
            re.IGNORECASE,
        )
        return None if found is None else found.group(1)

    def has_key(self, key: str) -> bool:
        return re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", self.text) is not None


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


def _every(values: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        word = _word(value)
        word = EVERY_ALSO.get(word, word)
        if word not in EVERY and word.endswith("s") and word[:-1] in EVERY:
            word = word[:-1]
        if word not in EVERY:
            raise _Bad
        out.append(word)
    return tuple(dict.fromkeys(out))


def _at(values: list[str]) -> tuple[str, ...]:
    times = tuple(_word(v).replace(" ", "").replace(".", "") for v in values)
    if len(times) > 4 or not all(TIME.fullmatch(t) for t in times):
        raise _Bad
    return times


def _on(value: str) -> Day:
    found = _ok(ON.fullmatch(_word(value).removeprefix("the ")))
    return Day(found.group(1), found.group(2))


def _key(value: str, task: _Task) -> str:
    key = visible(value)
    if KEY.fullmatch(key) is None or not task.has_key(key):
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


def _checked(row: RowAnswer, task: _Task) -> Parameters | None:
    def quoted(value: str | None, spot: Spot) -> str | None:
        return _maybe(value, lambda v: _ok(task.quote(v, spot)))

    try:
        _maybe(row.source, _jira)
        return Parameters(
            every=_every([v for v in row.every if visible(v)]),
            at=_at([v for v in row.at if visible(v)]),
            on=_maybe(row.on, _on),
            status=_maybe(row.status, lambda v: STATUSES[_one_of(STATUSES, v)]),
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
            software=quoted(row.software, SOFTWARE),
        )
    except _Bad:
        return None


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


def written(row: RowAnswer, task: str, abilities: tuple[Ability, ...] = ABILITIES) -> str | None:
    """The row's text in the platform's own words, or None when the platform can't do it: the
    ability is not in the table or does not fit the row, a parameter does not check out, the row
    carries a value the ability does not take, or a value the ability needs is missing."""
    form = _form(row, abilities)
    if form is None:
        return None
    if any(n not in form.takes and not _unused_ok(n, row) for n in _present(row)):
        return None
    checked = _checked(row, _Task(visible(task)))
    text = None if checked is None else form.write(checked)
    return None if text is None else text[:1].upper() + text[1:]


def said_in(text: str, task: str) -> str | None:
    """The task's own words for a part, when the model's quote of them checks out."""
    return _Task(visible(task)).quote(text, SAID)


def refusal(row: RowAnswer, task: str, abilities: tuple[Ability, ...] = ABILITIES) -> str:
    """The plain note for a part the platform can't do."""
    can = can_only(abilities)
    if row.source is not None and _word(row.source) != "jira":
        source = _Task(visible(task)).name_anywhere(row.source)
        if source is not None:
            return f"I can't read {source} yet. {can}"
    if row.kind == "where":
        return f"I can't put results there yet. {can}"
    return f"I can't do this yet. {can}"
