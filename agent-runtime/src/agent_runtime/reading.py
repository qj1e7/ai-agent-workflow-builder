"""What the model fills in when it reads a request typed on Home, and what code makes of it.

The model fills closed structures: the ticket search the platform will run, the ticket it will
create, the Jira project the result goes in, the schedule, and whose yes the request asks to
skip. Code renders every row a person sees from those structures, so a card claims only what
code will run, never the model's paraphrase. Code then checks every content word of the request
against the words those structures explain: whatever is left is quoted back as a part the
platform can't do, in the person's own words, never dropped. A filter the model fills with a
value the request never gave is dropped, and the request's words for it come back the same way.
"""

import re
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.abilities import (
    change_verbs_in,
    phrase_in,
    words,
)
from agent_runtime.contract import RowKind, UnderstoodRow
from agent_runtime.planner import (
    TEXT_LIMIT,
    missing_row,
    plain,
    said_in,
    visible_words,
)

type StatusRead = Literal["open", "done"]
type DayHow = Literal["within", "before", "since_last_run"]
type Detail = Literal["owner", "type", "status", "created", "updated", "done"]
type Says = Literal["list", "count", "summary"]
type SkipWhose = Literal["nobody", "only_me", "an_approver_or_anyone_else"]
type AsksAbout = Literal["none", "my_workflows", "why_stopped", "needs_me", "abilities"]

FILLED_IN: Final = "I filled this in. Your words didn't say it, so please check it."
FILLED_IN_FROM: Final = 'I filled some of this in from your words "{}". Please check it.'
READ_FROM: Final = 'Read from your words "{}".'
NO_TIME_SAID: Final = "Your words didn't say a time. Please choose one."
NO_TIME_BUT: Final = 'Your words said "{}" but not a time. Please choose one.'
SAID_LIMIT: Final = 200


class DaysRead(BaseModel):
    """A filter on when a ticket was created, updated or done, as the search runs it: within
    the last N days, more than N days ago, or since the last run."""

    model_config = ConfigDict(extra="ignore")

    how: DayHow = Field(
        description="within for the last N days, before for more than N days ago, as in no "
        "update for N days, or since_last_run for tickets new since the task last ran."
    )
    days: int | None = Field(
        default=None,
        ge=0,
        le=3660,
        description="The number of days the request gives. 0 for today. Null for "
        "since_last_run, or when the request gives no number: then say the words in said and "
        "the platform asks.",
    )


class SearchRead(BaseModel):
    """The ticket search the agents will run. Only the filters jira.search takes, and the
    details the agents read off each ticket it returns."""

    model_config = ConfigDict(extra="ignore")

    project: str | None = Field(
        default=None, description="The Jira project key the request names, such as MOCK."
    )
    issue_types: list[str] = Field(
        default_factory=list[str],
        description="The kinds of ticket the request names: bug, task, story, epic, sub-task, "
        "incident, improvement or defect. Empty for any kind.",
    )
    status: StatusRead | None = Field(
        default=None,
        description="open for open, to do, unresolved or not done; done for done, closed, "
        "resolved or finished. Null for any status. No other status can be searched for.",
    )
    assignee: str | None = Field(
        default=None,
        description="Who the tickets are assigned to: a name as the request writes it, me "
        "for the staff member's own, or nobody for unassigned. Null for anyone.",
    )
    created: DaysRead | None = Field(default=None, description="When the tickets were created.")
    updated: DaysRead | None = Field(
        default=None, description="When the tickets were last updated."
    )
    done: DaysRead | None = Field(default=None, description="When the tickets were done.")
    words: str | None = Field(
        default=None,
        description="Words to look for in a ticket's title or body, only when the request "
        'names a topic or area, such as login for "the login area". Never a priority, '
        "status, resolution or any other field.",
    )
    said: str = Field(
        default="",
        description="The request's words this search covers, copied exactly.",
    )


class TicketRead(BaseModel):
    """What happens with what was found: the agents list, count or sum up the tickets, and
    put the result in one new Jira ticket after an Approver says yes."""

    model_config = ConfigDict(extra="ignore")

    creates: bool = Field(
        description="True when the result goes in one new Jira ticket. False when the request "
        "only asks to see the result."
    )
    says: Says = Field(
        description="What the result is: a list of the tickets found, their count, or a "
        "summary of them."
    )
    shows: list[Detail] = Field(
        default_factory=list[Detail],
        description="The details of each ticket the result includes, when the request asks "
        "for them: owner, type, status, created, updated, done.",
    )
    said: str = Field(default="", description="The request's words this covers, copied exactly.")


class PlaceRead(BaseModel):
    """The Jira project the new ticket goes in."""

    model_config = ConfigDict(extra="ignore")

    project: str | None = Field(
        default=None, description="The Jira project key the request names for it, such as MOCK."
    )
    said: str = Field(default="", description="The request's words this covers, copied exactly.")


class SkipRead(BaseModel):
    """The model's answer to one question about the whole request: whose yes or attention does
    it ask to skip? Code refuses a skip of an Approver's yes or of anyone else's. The staff
    member's own attention is theirs to skip, because the Operator is never the Approver, and
    code accepts that only when the quoted words name the staff member and nobody else."""

    model_config = ConfigDict(extra="ignore")

    whose: SkipWhose = Field(
        description="nobody when the request skips no one's yes or attention, including a "
        "request that only reads or reports on approvals. only_me when it asks only that the "
        "staff member themselves is not asked, told or kept in the loop. "
        "an_approver_or_anyone_else when it asks for a change to go ahead without an Approver's "
        "yes, to bypass, pre-approve or self-approve it, or to leave any other person or any "
        "person at all out."
    )
    said: str | None = Field(
        default=None,
        description="The request's words that ask so, copied exactly. Null when whose is nobody.",
    )


class TaskRead(BaseModel):
    """What the model fills in when it reads a request typed on Home. The model reads; code
    decides from what it read, and shows the person only what code will run."""

    model_config = ConfigDict(extra="ignore")

    skips_the_yes: SkipRead = Field(
        description="Whether the request asks to skip, bypass, pre-approve or self-approve the "
        "Approver's yes, with the request's words that say so."
    )
    asks_about: AsksAbout = Field(
        default="none",
        description="What the request is: a task or software to set up (none), a question "
        "about the person's workflows, or what you can do.",
    )
    workflow_words: str | None = Field(
        default=None,
        description="For my_workflows and why_stopped: the words of the request that name one "
        "workflow, copied exactly. Null when it asks about all of them.",
    )
    belongs_on_watchlist: bool = Field(
        default=False,
        description="True when the request is about software versions, releases, upgrades or "
        "patches, and asks for no known vulnerabilities.",
    )
    watchlist_word: str | None = Field(
        default=None, description="The word from the request that made you think so."
    )
    software: str | None = Field(
        default=None, description="The software the request names, as it writes it."
    )
    name: str | None = Field(
        default=None, description="For a task: 2 to 5 plain words that say what it does."
    )
    schedule: str | None = Field(
        default=None,
        description="When the task runs, in the request's own words, such as \"Every weekday "
        'at 3pm". Null when the request does not say. Never add a day or a time.',
    )
    search: SearchRead | None = Field(
        default=None, description="The ticket search the task runs. Null when it searches none."
    )
    ticket: TicketRead | None = Field(
        default=None,
        description="What happens with what was found. Null when the request does not say.",
    )
    place: PlaceRead | None = Field(
        default=None, description="Where the new ticket goes. Null when the request does not say."
    )


# The words each structure explains. Every list here can only make the platform claim less:
# a word missing from one comes back to the person as a part the platform can't do, never as a
# claim. A word in one explains a request word only when that structure is filled.
FILLER: Final = words(
    "a an the this that these those each every all any some no none i i'd i'm i'll i've me my "
    "mine myself we us our ours you your yours it its it's they them their theirs there here one "
    "ones who whom whose which what where when how why in on at to of for with without from by "
    "into onto over under about as per via through after before since until during between "
    "among against and or nor but so then than if whether while once yet still also just only "
    "please too very rather really even ever already always again now right soon "
    "quickly simply up down out off back away is are was were be been being am do does did has "
    "have had having can could will would shall should may might must need needs needed want "
    "wants wanted like not never don't doesn't didn't won't can't cannot isn't aren't wasn't "
    "weren't shouldn't wouldn't couldn't haven't hasn't get gets got getting go goes going gone "
    "let keep keeps something anything everything nothing thanks thank hi hello hey etc able "
    "sure make makes making help t s d m ll ve re"
)
"""Words that name no part of a task on their own. "make" is here for "make sure"; a ticket
made is "create" or "make" in the ticket's own words, which the ticket vocabulary explains."""
SCHEDULE_WORDS: Final = words(
    "monday tuesday wednesday thursday friday saturday sunday weekday weekdays daily weekly "
    "monthly hourly quarterly yearly annually fortnightly biweekly day days week weeks month "
    "months hour hours quarter quarters year years fortnight morning afternoon evening night "
    "noon midday midnight"
)
SCHEDULE_VOCAB: Final = SCHEDULE_WORDS | words(
    "every each on at in the and to from by before after first last other twice once per a an "
    "am pm o'clock start end of beginning eod"
)
TIME_OF_DAY: Final = re.compile(
    r"\b(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b(?:at\s+)?\d{1,2}:\d{2}\b|\bat\s+\d{1,2}\b|"
    r"\bat\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b|"
    r"\b(?:noon|midday|midnight|morning|afternoon|evening|night)\b",
    re.IGNORECASE,
)
CLOCK_TOKEN: Final = re.compile(r"^\d{1,2}(?::\d{2})?(?:am|pm)$|^\d{1,2}(?:st|nd|rd|th)$")
SEARCH_VOCAB: Final = words(
    "ticket tickets issue issues item items entry entries find finds finding found list lists "
    "listing listed show shows showing get gather gathers gathering collect collects "
    "collecting fetch look looks looking search searches searching pull pulls see view display "
    "identify spot check checks checking review reviews pick select filter jira project "
    "projects board backlog queue all any"
)
"""What a ticket search explains on its own. A kind of ticket, such as bugs, is explained only
by the search's issue_types, so a kind the model left out comes back to the person."""
PROJECT_KEY: Final = re.compile(r"[A-Z][A-Z0-9]{1,9}")
STATUS_VOCAB: Final[dict[StatusRead, frozenset[str]]] = {
    "open": words(
        "open unresolved outstanding active unfinished incomplete pending todo to-do ongoing "
        "live current unclosed"
    ),
    "done": words("done closed resolved finished completed complete fixed shipped solved"),
}
NEGATIONS: Final = words("not never no isn't aren't wasn't weren't hasn't haven't un without")
ISSUE_TYPES: Final[dict[str, tuple[str, ...]]] = {
    "Bug": ("bug", "bugs"),
    "Task": ("task", "tasks"),
    "Story": ("story", "stories"),
    "Epic": ("epic", "epics"),
    "Sub-task": ("sub-task", "sub-tasks", "subtask", "subtasks"),
    "Incident": ("incident", "incidents"),
    "Improvement": ("improvement", "improvements"),
    "Defect": ("defect", "defects"),
}
"""Jira's own issue types, the closed set a search can name. A word the request uses for a kind
of ticket that is not one of these, such as Major, is not a type."""
TYPE_BY_FORM: Final = {form: name for name, forms in ISSUE_TYPES.items() for form in forms}
ASSIGNEE_VOCAB: Final = words(
    "assigned assignee assignees assign owned owner owners owns own belonging belongs belong "
    "held holds unassigned nobody no-one none"
)
ME_WORDS: Final = words("me my mine myself i")
NOBODY_WORDS: Final = words("nobody no-one unassigned none")
NAME: Final = re.compile(r"^[A-Z][a-z]+(?: [A-Z][a-z]+)?$")
DAYS_VOCAB: Final = words(
    "since last past within in the days day week weeks month months year years this today "
    "yesterday ago older newer than more over less under fewer no without for from recent "
    "recently latest earlier later back run quarter fortnight hours hour"
)
WHEN_VOCAB: Final[dict[str, frozenset[str]]] = {
    "created": words("created raised filed logged submitted new newly added opened arrived"),
    "updated": words(
        "updated update updates touched changed modified edited activity active stale idle "
        "dormant quiet untouched"
    ),
    "done": STATUS_VOCAB["done"] | words("closing closure"),
}
TOPIC_VOCAB: Final = words(
    "about mentioning mention mentions titled called named regarding concerning containing "
    "contain contains saying say says related area topic subject feature module page title "
    "summary description body name text word words"
)
TOPIC_LEADS: Final = (
    r"about|mentioning|mentions?|titled|called|named|regarding|concerning|containing|contains?|"
    r"saying|says?|discussing|covering|on\s+the\s+subject\s+of|related\s+to|to\s+do\s+with"
)
TOPIC_PLACES: Final = r"title|summary|description|body|name|text|subject"
CREATE_VOCAB: Final = words(
    "create creates creating make makes making raise raises raising file files filing log logs "
    "logging propose proposes draft drafts write writes submit submits add adds generate "
    "generates put puts one single new another jira that which ticket tickets issue issues "
    "follow-up follow-ups followup followups summary"
)
OPEN_AS_CREATE_AFTER: Final = words("a an one single new another the up")
SAYS_VOCAB: Final[dict[Says, frozenset[str]]] = {
    "list": words(
        "list lists listing listed show shows showing include includes including each all "
        "together them it everything"
    ),
    "count": words("count counts counted counting number numbers many total tally how"),
    "summary": words(
        "sum sums summing up summary summaries summarise summarize summarised summarized recap "
        "digest overview roundup round-up write-up writeup report reports brief rundown breakdown"
    ),
}
SHOWS_VOCAB: Final[dict[Detail, frozenset[str]]] = {
    "owner": words("owner owners owns assignee assignees who whom assigned responsible holder"),
    "type": words("type types kind kinds"),
    "status": words("status statuses state states"),
    "created": words("created date dates age when"),
    "updated": words("updated update touched when"),
    "done": words("finished completion when"),
}
PLACE_VOCAB: Final = words("jira project projects board in into to put puts goes go file")
A_YES: Final = re.compile(
    r"\b(?:approv\w*|sign[- ]?offs?|signs?|signed|signing|yes|okay|ok|go-ahead|permission|"
    r"consent|confirmation|confirms?|confirmed|authori[sz]\w*|reviewed|reviewers?|reviewing|"
    r"rubber-?stamp\w*|decision|decides?|decided|green\s+light|agreed|agrees)\b",
    re.IGNORECASE,
)
"""Words that name a yes. None is in any vocabulary above, so none is ever explained by a
structure: a request that carries one either quotes it as the staff member's own attention,
which code checks, or sees it come back."""
SOMEONE: Final = re.compile(
    r"\b(?:anyone|anybody|someone|somebody|nobody|no\s+one|no-one|everyone|everybody|humans?|"
    r"persons?|people|the\s+team|managers?|the\s+boss|supervisors?|he|she|him|her|his|hers)\b",
    re.IGNORECASE,
)
"""Words that name a person who could give a yes. With a "no", "not" or "without" beside them,
or as "nobody", they skip that person; alone, as in "remove anyone who has left", they do not."""
NOBODY: Final = re.compile(r"\b(?:nobody|no\s+one|no-one)\b", re.IGNORECASE)
FROM_ME: Final = re.compile(
    r"\b(?:approval|approvals|confirmation|permission|sign[- ]?off|okay|ok|yes|go-ahead|consent)\s+"
    r"(?:from|of|by)\s+(?:me|myself)\b",
    re.IGNORECASE,
)
"""A yes the staff member gives, as "confirmation from me": theirs to skip, because the Operator
is never the Approver. The word rule makes the same exception."""
NEGATED: Final = re.compile(
    r"\b(?:no|not|without|neither|nor|never|don't|doesn't|shouldn't|needn't|spare|skip\w*|"
    r"bypass\w*)\b|n't\b",
    re.IGNORECASE,
)
SPEAKS_OF_SELF: Final = re.compile(r"\b(?:i|i'd|i'm|i'll|i've|me|my|mine|myself)\b", re.IGNORECASE)
CLAUSE_END: Final = re.compile(r"[,;:.!?]+(?=\s|$)|[()]")
LEAD_IN: Final = re.compile(
    r"\b(?:without|no|not|neither|nor|never|don't)(?:\s+(?:a|an|the|any|my|their))?\s*$",
    re.IGNORECASE,
)
TOKEN: Final = re.compile(r"[^\W_][\w'’-]*")


type Said = dict[RowKind, tuple[int, int] | None]


@dataclass(frozen=True)
class Span:
    """A run of the request's words that no structure explains."""

    text: str
    start: int
    end: int
    kind: RowKind
    names_a_yes: bool


@dataclass(frozen=True)
class Rendered:
    """A row code wrote from a structure, with the request words that structure explains, and
    the request span it came from."""

    row: UnderstoodRow
    explained: frozenset[str]
    said: tuple[int, int] | None


def _low(token: str) -> str:
    return token.casefold().replace("’", "'").removesuffix("'s").removesuffix("'")


def _request_tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in TOKEN.finditer(text)]


def _find(text: str, phrase: str | None) -> tuple[int, int] | None:
    """Where the request writes the model's quote, or None when it does not."""
    found = phrase_in(text, phrase or "")
    if found is None:
        return None
    at = text.casefold().find(found.casefold())
    return None if at < 0 else (at, at + len(found))


def _quote(text: str, said: tuple[int, int] | None) -> str | None:
    return None if said is None else plain(text[said[0] : said[1]], SAID_LIMIT)


def _note(text: str, said: tuple[int, int] | None, sourced: bool) -> str | None:
    quote = _quote(text, said)
    if sourced:
        return None if quote is None else READ_FROM.format(quote)
    return FILLED_IN if quote is None else FILLED_IN_FROM.format(quote)


def _forms_in(text: str, forms: frozenset[str]) -> bool:
    low = {_low(t) for t, _, _ in _request_tokens(text)}
    return bool(low & forms)


def _project_in(text: str, key: str | None) -> str | None:
    """The key as the request writes it, or None: a key the request never said is never shown."""
    if not key:
        return None
    key = key.strip().upper()
    return key if PROJECT_KEY.fullmatch(key) and said_in(key, text) else None


def _days_text(when: str, read: DaysRead) -> str | None:
    """The filter in plain words, or None when it needs a number the model left out."""
    verb = {"created": "created", "updated": "updated", "done": "finished"}[when]
    match read.how:
        case "since_last_run":
            return f"{verb} since the last run"
        case "within":
            if read.days is None:
                return None
            return f"{verb} today" if read.days == 0 else f"{verb} in the last {read.days} days"
        case "before":
            if read.days is None:
                return None
            if when == "updated":
                return f"with no update for {read.days} days"
            return f"{verb} more than {read.days} days ago"


def _assignee(text: str, said: str | None) -> tuple[str, frozenset[str]] | None:
    """The assignee filter as the request frames it, with the words it explains, or None when
    the request frames no such filter: a name alone is not an assignee."""
    if not said:
        return None
    value = said.strip()
    low = _low(value)
    if low in ME_WORDS:
        framed = re.search(
            r"\b(?:my|mine)\b|\b(?:assigned|belonging|belongs?)\s+to\s+me\b|\bowned\s+by\s+me\b|"
            r"\bi\s+own\b",
            text,
            re.IGNORECASE,
        )
        return None if framed is None else ("assigned to you", ASSIGNEE_VOCAB | ME_WORDS)
    if low in NOBODY_WORDS or low in ("no one", "not assigned"):
        framed = re.search(
            r"\bunassigned\b|\b(?:nobody|no\s+one|no-one|no\s+owner|no\s+assignee)\b|"
            r"\bwithout\s+(?:an\s+)?(?:owner|assignee)\b|\bnot\s+assigned\b",
            text,
            re.IGNORECASE,
        )
        return None if framed is None else ("with no assignee", ASSIGNEE_VOCAB | NOBODY_WORDS)
    if NAME.fullmatch(value) is None:
        return None
    name = re.escape(value)
    framed = re.search(
        rf"\b(?:assigned|belonging|belongs|belong|given|handed)\s+to\s+{name}\b|"
        rf"\b(?:owned|held)\s+by\s+{name}\b|\b{name}['’]s\b|"
        rf"\b{name}\s+(?:owns|holds|is\s+(?:the\s+)?(?:owner|assignee))\b|"
        rf"\b(?:owner|assignee)\s*(?:is|=|:)\s*{name}\b",
        text,
        re.IGNORECASE,
    )
    if framed is None:
        return None
    return f"assigned to {value}", ASSIGNEE_VOCAB | frozenset(_low(w) for w in value.split())


def _topic(text: str, said: str | None) -> tuple[str, frozenset[str]] | None:
    """The word search as the request frames it, with the words it explains, or None when the
    request does not frame those words as a topic: a value such as P1 is not a topic."""
    if not said:
        return None
    found = phrase_in(text, said)
    if found is None:
        return None
    w = re.escape(found)
    framed = re.search(
        rf"\b(?:{TOPIC_LEADS})\s+(?:the\s+|a\s+|an\s+)?{w}\b|"
        rf"\b{w}\s+(?:area|topic|subject|feature|module|page|screen)\b|"
        rf"\b{w}\s+in\s+(?:the|their|its|a)\s+(?:{TOPIC_PLACES})\b|"
        rf"\bwords?\s+{w}\b",
        text,
        re.IGNORECASE,
    )
    if framed is None:
        return None
    return found, TOPIC_VOCAB | frozenset(_low(t) for t, _, _ in _request_tokens(found))


def _negated_done(text: str) -> frozenset[str]:
    """Done words that a negation turns into open, as "not done" or "aren't finished"."""
    tokens = [_low(t) for t, _, _ in _request_tokens(text)]
    found: set[str] = set()
    for at, token in enumerate(tokens):
        if token in STATUS_VOCAB["done"] and any(
            t in NEGATIONS or t.endswith("n't") for t in tokens[max(0, at - 2) : at]
        ):
            found.add(token)
    return frozenset(found)


def render_search(read: SearchRead, text: str) -> Rendered:
    """The look-for row, written from the search. A filter the request never framed is dropped,
    so its words come back to the person instead of a claim."""
    explained: set[str] = set(SEARCH_VOCAB)
    sourced = True
    types = list(
        dict.fromkeys(t for t in (TYPE_BY_FORM.get(_low(x)) for x in read.issue_types) if t)
    )
    kept_types = [t for t in types if _forms_in(text, frozenset(ISSUE_TYPES[t]))]
    for name in kept_types:
        explained.update(ISSUE_TYPES[name])
    subject = " and ".join(kept_types[:3]).lower() + " tickets" if kept_types else "tickets"
    status = ""
    if read.status is not None:
        vocab = STATUS_VOCAB[read.status]
        negated = _negated_done(text) if read.status == "open" else frozenset[str]()
        if _forms_in(text, vocab) or negated:
            explained.update(vocab | negated)
        else:
            sourced = False
        status = f"{read.status} "
    parts = [f"{status}{subject}"]
    project = _project_in(text, read.project)
    if project is not None:
        parts.append(f"in {project}")
        explained.add(project.casefold())
    assignee = _assignee(text, read.assignee)
    if assignee is not None:
        parts.append(assignee[0])
        explained.update(assignee[1])
    tail: list[str] = []
    for when, filter_ in (
        ("created", read.created),
        ("updated", read.updated),
        ("done", read.done),
    ):
        if filter_ is None:
            continue
        shown = _days_text(when, filter_)
        if shown is None:
            continue
        tail.append(shown)
        explained.update(WHEN_VOCAB[when] | DAYS_VOCAB)
        if filter_.days is not None:
            if said_in(str(filter_.days), text) or (filter_.days == 0 and said_in("today", text)):
                explained.add(str(filter_.days))
            else:
                sourced = False
        if not _forms_in(text, WHEN_VOCAB[when]):
            sourced = False
    topic = _topic(text, read.words)
    if topic is not None:
        tail.append(f'with "{topic[0]}" in the title or body')
        explained.update(topic[1])
    shown = " ".join(parts) + (", " + ", ".join(tail) if tail else "")
    shown = shown[:1].upper() + shown[1:]
    said = _find(text, read.said)
    row = UnderstoodRow(
        kind="look_for",
        text=plain(shown, TEXT_LIMIT),
        state="understood" if sourced else "changed",
        note=_note(text, said, sourced),
    )
    return Rendered(row, frozenset(explained), said)


def _open_as_create(text: str) -> frozenset[str]:
    """ "open" explains a request word only as the verb that opens a ticket, as in "open one
    ticket", never as the state of the tickets looked for."""
    tokens = [_low(t) for t, _, _ in _request_tokens(text)]
    for at, token in enumerate(tokens[:-1]):
        if token in ("open", "opens", "opening") and tokens[at + 1] in OPEN_AS_CREATE_AFTER:
            return frozenset({token})
    return frozenset()


def render_ticket(read: TicketRead, text: str) -> Rendered:
    """The do row, written from what happens with what was found."""
    explained: set[str] = set(SAYS_VOCAB[read.says])
    what = {"list": "lists them", "count": "counts them", "summary": "sums them up"}[read.says]
    details: list[str] = []
    for detail in dict.fromkeys(read.shows):
        explained.update(SHOWS_VOCAB[detail])
        details.append(
            {
                "owner": "who owns each one",
                "type": "each one's type",
                "status": "whether each one is open or done",
                "created": "when each one was created",
                "updated": "when each one was last updated",
                "done": "when each one was finished",
            }[detail]
        )
    with_details = f", with {' and '.join(details)}" if details else ""
    if read.creates:
        explained.update(CREATE_VOCAB | _open_as_create(text))
        shown = f"Create one ticket that {what}{with_details}"
    else:
        shown = {"list": "List them", "count": "Count them", "summary": "Sum them up"}[read.says]
        shown += with_details
    said = _find(text, read.said)
    row = UnderstoodRow(
        kind="do", text=plain(shown, TEXT_LIMIT), state="understood", note=_note(text, said, True)
    )
    return Rendered(row, frozenset(explained), said)


def render_place(read: PlaceRead, text: str) -> Rendered:
    project = _project_in(text, read.project)
    said = _find(text, read.said)
    if project is None:
        return Rendered(missing_row("where"), frozenset(), said)
    row = UnderstoodRow(
        kind="where",
        text=f"Jira project {project}",
        state="understood",
        note=_note(text, said, True),
    )
    return Rendered(row, PLACE_VOCAB | frozenset({project.casefold()}), said)


def _schedule_token(token: str) -> bool:
    low = _low(token)
    return low in SCHEDULE_VOCAB or CLOCK_TOKEN.match(low) is not None or low.isdigit()


def _a_schedule_word(token: str) -> bool:
    """A word only a schedule uses, which the schedule row carries or asks for, so it is never
    a part the platform can't do. "first" or "last" can be a filter, so they are not here."""
    low = _low(token)
    return low in SCHEDULE_WORDS | words("every each am pm o'clock") or bool(CLOCK_TOKEN.match(low))


def _no_time_said(schedule: str, text: str) -> str:
    """The note on a schedule asked for because its time was a guess, keeping the words that
    were the person's own, such as "Every Friday", and never a day the model guessed."""
    unsaid = [t for t in TIME_OF_DAY.findall(schedule) if not said_in(t.strip(), text)]
    day = schedule
    for time in unsaid:
        day = day.replace(time, " ")
    day = " ".join(day.split()).strip(" ,").removesuffix(" at").removesuffix(" in the")
    words_of_day = re.findall(r"\w+", day)
    theirs = any(w.casefold() in SCHEDULE_WORDS or TIME_OF_DAY.search(w) for w in words_of_day)
    if not theirs or not all(said_in(w, text) for w in words_of_day):
        return NO_TIME_SAID
    return NO_TIME_BUT.format(day)


def render_schedule(schedule: str | None, text: str) -> Rendered:
    """The schedule row: the model's words kept to schedule words only, with a time the request
    never said asked for, not filled in, and a day it never said shown as a guess."""
    kept = [t for t in (visible_words(schedule) or "").split() if _schedule_token(t.strip(",."))]
    shown = " ".join(kept).strip(" ,")
    if not any(_low(t) in SCHEDULE_WORDS or CLOCK_TOKEN.match(_low(t)) for t in kept):
        return Rendered(missing_row("schedule"), frozenset(), None)
    if any(not said_in(time.strip(), text) for time in TIME_OF_DAY.findall(shown)):
        return Rendered(missing_row("schedule", _no_time_said(shown, text)), frozenset(), None)
    explained = frozenset(_low(t) for t in kept)
    guessed = [w for w in re.findall(r"\w+", shown) if w.casefold() in SCHEDULE_WORDS]
    sourced = all(said_in(w, text) for w in guessed)
    row = UnderstoodRow(
        kind="schedule",
        text=plain(shown[:1].upper() + shown[1:], TEXT_LIMIT),
        state="understood" if sourced else "changed",
        note=None if sourced else FILLED_IN,
    )
    return Rendered(row, explained, None)


def _clauses(text: str) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    at = 0
    for mark in CLAUSE_END.finditer(text):
        if mark.start() > at:
            found.append((at, mark.start()))
        at = mark.end()
    if at < len(text):
        found.append((at, len(text)))
    return found


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and not text[start].isalnum():
        start += 1
    while end > start and not text[end - 1].isalnum():
        end -= 1
    return start, end


def _kind_of(text: str, start: int, end: int, said: Said) -> RowKind:
    """The part the words belong to: words inside what the model said the search covers are
    what to look for; a change asked for is the do part; otherwise the part whose words the
    model said they were in; otherwise what to look for."""
    look = said.get("look_for")
    if look is not None and look[0] <= start and end <= look[1]:
        return "look_for"
    if change_verbs_in(text[start:end]):
        return "do"
    for kind in ("where", "do", "look_for"):
        span = said.get(kind)
        if span is not None and start < span[1] and end > span[0]:
            return kind
    return "look_for"


def negated(text: str) -> bool:
    """Whether the words say no to something, as "don't ping me" or "run it without me"."""
    return NEGATED.search(text) is not None


def names_a_yes(text: str) -> bool:
    """Whether the words name a yes, or a person left out of one."""
    text = FROM_ME.sub(" ", text)
    if A_YES.search(text) is not None or NOBODY.search(text) is not None:
        return True
    return SOMEONE.search(text) is not None and NEGATED.search(text) is not None


def leftovers(
    text: str,
    explained: frozenset[str],
    covered: list[tuple[int, int]],
    said: Said,
    writes: bool = False,
) -> list[Span]:
    """The request's words that nothing explains, clause by clause. A clause whose first content
    word is unexplained comes back from that word to its end, because the whole part is unread;
    otherwise the run from the first unexplained word to the last. A "without", "no" or "not"
    right before the run comes with it, so "without approval" keeps its "without". A word that
    names a yes or a person is content whatever list it is in, and in a request that writes
    its whole clause comes back, so the refusal reads as the person wrote it. Schedule words
    are never content: the schedule row carries or asks for them."""
    spans: list[Span] = []
    for c_start, c_end in _clauses(text):
        clause = text[c_start:c_end]
        tokens = _request_tokens(clause)
        theirs = [(c_start + m.start(), c_start + m.end()) for m in FROM_ME.finditer(clause)]
        content: list[tuple[int, int]] = []
        unread: list[tuple[int, int]] = []
        before = ""
        for at, (raw, start, end) in enumerate(tokens):
            low = _low(raw)
            start, end = c_start + start, c_start + end
            names = (
                A_YES.fullmatch(raw) is not None
                or SOMEONE.fullmatch(raw) is not None
                or (low == "one" and before == "no")
                or (low in ("team", "boss") and before == "the")
            ) and not any(a <= start and end <= b for a, b in theirs)
            filler = (low in FILLER and not (raw[:1].isupper() and at)) or _a_schedule_word(raw)
            filler = filler and not names
            before = low
            if filler:
                continue
            content.append((start, end))
            known = low in explained or any(a <= start and end <= b for a, b in covered)
            if not known or names:
                unread.append((start, end))
        if not unread:
            continue
        start = unread[0][0]
        end = c_end if unread[0] == content[0] else unread[-1][1]
        lead = LEAD_IN.search(text[c_start:start])
        if lead is not None:
            start = c_start + lead.start()
        names = names_a_yes(text[start:end])
        if names and writes:
            start, end = content[0][0], c_end
        start, end = _trim(text, start, end)
        spans.append(Span(text[start:end], start, end, _kind_of(text, start, end, said), names))
    return spans


def task_shaped(read: TaskRead, text: str) -> bool:
    """Whether the reading, or the request, describes a task: a structure is filled, or the
    request asks for a change in its own words."""
    return any((read.search, read.ticket, read.place, read.schedule)) or bool(change_verbs_in(text))


def speaks_only_of_self(quote: str) -> bool:
    """Whether a quote the model called the staff member's own really names them and nobody
    else: the words say I, me, my, mine or myself, and no yes or other person."""
    named = any(re.fullmatch(r"[A-Z][a-z]+", w) for w in re.findall(r"\w+", quote)[1:])
    quote = FROM_ME.sub(" me ", quote)
    return (
        SPEAKS_OF_SELF.search(quote) is not None
        and A_YES.search(quote) is None
        and SOMEONE.search(quote) is None
        and not named
    )
