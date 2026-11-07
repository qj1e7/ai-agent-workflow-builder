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
    SYSTEMS,
    TICKETS,
    change_verbs_in,
    commands_a_change,
    phrase_in,
    starts_with_a_verb,
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
# claim. A word in one explains a request word only when that structure is filled, and only
# inside that structure's own stretch of the request (`leftovers`).
FILLER: Final = words(
    "a an the this that these those each every all any some no none we us our ours you your "
    "yours it its it's they them their theirs there here one ones who whom whose which what "
    "where when how why in on at to of for with without from into onto over about as per via "
    "through after before since until during between among against and or nor but so then "
    "than if whether while once yet also just only please too very rather really even ever "
    "already always again now right soon quickly simply up down out off back away is are was "
    "were be been being am do does did has have had having can could will would shall should "
    "may might must need needs needed want wants wanted like not never don't doesn't didn't "
    "won't can't cannot isn't aren't wasn't weren't shouldn't wouldn't couldn't haven't hasn't "
    "get gets got getting go goes going gone let keep keeps something anything everything "
    "nothing thanks thank hi hello hey etc able sure make makes making help t s d m ll ve re"
)
"""Words that name no part of a task on their own. "make" is here for "make sure"; a ticket
made is "create" or "make" in the ticket's own words, which the ticket vocabulary explains.
"I", "me" and "my", "by", "under" and "still" are not here: each can carry a filter ("opened by
me", "still under review"), so a structure must explain it where it stands, or it comes back."""
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
    "identify spot check checks checking pick select filter jira project projects board "
    "backlog queue all any"
)
"""What a ticket search explains on its own. A kind of ticket, such as bugs, is explained only
by the search's issue_types, so a kind the model left out comes back to the person. "review" is
the search's verb only at the front of its clause ("Review the open bugs"); after "under" or
"in" it is a status the search can't filter by, so it is not here."""
REVIEW: Final = words("review reviews")
STILL: Final = words("still")
"""A status filter explains "still" ("still open", "still under review") but is never read
from it: "still" alone does not say open or done."""
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
    "held holds unassigned nobody no-one none by"
)
ME_WORDS: Final = words("me my mine myself i i'd i'm i'll i've")
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
    "done": words("completion completed when"),
}
"""The details a ticket can show, each explained only where the ticket's own words stand.
"finished" is not a detail word: "finished by this Friday" is a due date, which no structure
holds, so it must come back."""
PLACE_VOCAB: Final = words("jira project projects board in into to put puts goes go file")
CREATE_PHRASE: Final = re.compile(
    r"\b(?:(?:create|creates|make|makes|raise|raises|file|files|log|logs|open|opens|draft|"
    r"drafts|propose|proposes|submit|submits|add|adds|generate|generates|write|writes|put|"
    r"puts)\s+)?(?:a|an|one|single|new|another)\s+(?:(?:new|single|follow-?up|summary|jira|"
    r"(?-i:[A-Z][A-Z0-9]{1,9}))\s+)*(?:ticket|issue)s?\b",
    re.IGNORECASE,
)
"""The request's own words for the new ticket, such as "create one ticket", "one SVC ticket"
or "in one new ticket": a second place the ticket structure stands in the request, because the
model's quote for the ticket is sometimes only "list them"."""
A_YES: Final = re.compile(
    r"\b(?:approv\w*|sign[- ]?offs?|signs?|signed|signing|countersign\w*|yes|okay|okayed|"
    r"okays|ok|ok'd|go-ahead|permission|consent|confirmation|confirms?|confirmed|"
    r"authori[sz]\w*|reviewed|reviewers?|reviewing|rubber-?stamp\w*|decision|decides?|decided|"
    r"green\s+light|greenlit|greenlight\w*|agreed|agrees|vouch\w*|the\s+nod|blessing|"
    r"pre-?cleared|sanction\w*|endors\w*|ratif\w*|waived?|once-over|"
    r"(?:second|another)\s+pair\s+of\s+eyes)\b",
    re.IGNORECASE,
)
"""Words that name a yes. None is in any vocabulary above, so none is ever explained by a
structure: a request that carries one either quotes it as the staff member's own attention,
which code checks, or sees it come back."""
SOMEONE: Final = re.compile(
    r"\b(?:anyone|anybody|someone|somebody|nobody|no\s+one|no-one|everyone|everybody|humans?|"
    r"persons?|people|whoever|the\s+team|teammates?|colleagues?|stakeholders?|managers?|"
    r"the\s+boss|supervisors?|directors?|leads?|gatekeepers?|committee|"
    r"(?:change|review|approval|advisory|steering)\s+board|cab|he|she|him|her|his|hers)\b",
    re.IGNORECASE,
)
"""Words that name a person, a role or a group who could give a yes. With a "no", "not" or
"without" beside them, or as "nobody", they skip that person. In a request that writes, words
no structure explains that name one are refused whatever stands beside them ("the change board
can catch up on it at their next meeting"); in one that reads they are a visible can't."""
CAPITALISED: Final = r"[A-Z][a-z]+"
NAMED_BEFORE: Final = (
    r"(?:get|getting|got|ask|asking|tell|telling|let|have|having|cc|ping|pinging|notify|"
    r"notifying|bother|bothering|consult|consulting|email|emailing|message|remind|involve|"
    r"involving|wait\s+for|waiting\s+for|wait\s+on|waiting\s+on|check\s+with|checking\s+with|"
    r"run\s+it\s+(?:by|past)|clear\s+it\s+with|hear\s+from|without|unless|"
    r"(?:me|myself|i|{name})\s+(?:or|and|nor))"
)
NAMED_AFTER: Final = (
    r"(?:'s|’s|'ll|’ll|'d|’d|can|could|will|would|shall|should|may|might|must|has|had|have|"
    r"is|was|does|did|said|says|told|tells|mentioned|mentions|gave|gives|okayed|okays|ok'd|"
    r"agreed|agrees|signed|signs|normally|usually|already|also|wants|needs|prefers|likes|"
    r"asked|wanted|knows|isn't|hasn't|doesn't|won't|to|or\s+me|and\s+me)"
)
WHO: Final = rf"(?:(?i:{SOMEONE.pattern[2:-2]})|{CAPITALISED})"
NAMED_ACTOR: Final = re.compile(
    rf"\b(?i:{NAMED_BEFORE.format(name=CAPITALISED)})\s+(?i:the\s+)?(?P<before>{WHO})\b|"
    rf"\b(?P<after>{WHO})(?:\s+{CAPITALISED})?\s*(?i:{NAMED_AFTER})\b"
)
"""A person, a role, a group or a capitalised word framed as someone who acts: asked, waited
for, or the subject of a verb ("get Ravi to", "Joanne normally okays", "the change board
can", "the duty lead doesn't", "Wei Ling's inbox", "me or Bob"). A value such as "flagged
Highest" or "the Checkout component" is never framed so, and stays a can't; nor is a person
the change acts on, as "remove anyone who has left the team", which is a can't for GitLab."""
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
    """A run of the request's words that no structure explains, with the part of a task they
    are: None when they ask for no change and stand beside no part."""

    text: str
    start: int
    end: int
    kind: RowKind | None
    names_a_yes: bool
    names_a_person: bool = False


@dataclass(frozen=True)
class Rendered:
    """A row code wrote from a structure, with the request words that structure explains, and
    the stretches of the request the structure stands in: the model's quote for it as the
    request writes it, and, for the ticket, the request's own words for the new ticket. The
    structure explains its words only there and in the run of its own words around there."""

    row: UnderstoodRow
    explained: frozenset[str]
    said: tuple[int, int] | None
    also: tuple[int, int] | None = None


def _low(token: str) -> str:
    return token.casefold().replace("’", "'").removesuffix("'s").removesuffix("'")


def _request_tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in TOKEN.finditer(text)]


def _find(text: str, phrase: str | None, last: bool = False) -> tuple[int, int] | None:
    """Where the request writes the model's quote, or None when it does not."""
    found = phrase_in(text, phrase or "")
    if found is None:
        return None
    at = (text.casefold().rfind if last else text.casefold().find)(found.casefold())
    return None if at < 0 else (at, at + len(found))


def _locate(text: str, phrase: str | None) -> tuple[int, int] | None:
    """Where the request writes the model's quote: as written, else from the first of its
    content words to the last, each found in order after the one before ("list them, create
    one ticket that lists them" for "list the bugs, create one ticket that lists them"). None
    when the request lacks it."""
    found = _find(text, phrase)
    if found is not None:
        return found
    content = [t for t, _, _ in _request_tokens(phrase or "") if _low(t) not in FILLER]
    if not content:
        return None
    at = 0
    start: int | None = None
    for word in content:
        match = re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text[at:], re.IGNORECASE)
        if match is None:
            return None
        if start is None:
            start = at + match.start()
        at += match.end()
    return None if start is None else (start, at)


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


PERSONS_ACTION: Final = re.compile(
    r"\b(?:i|we|you|i've|we've|i'd|we'd)\s+(?:have\s+|had\s+)?(?P<before>{when})\b|"
    r"\b(?P<after>{when})\s+by\s+(?:me|us|you|myself|[A-Z][a-z]+)\b"
)
"""A day word framed as what a person did ("the bugs I raised", "opened by me", "filed by
Bob") names the reporter, which the search can't filter by, so the day filter does not explain
that word: it comes back with the person."""


def _persons_action(span: str, when: str) -> frozenset[str]:
    forms = "|".join(re.escape(w) for w in WHEN_VOCAB[when])
    pattern = re.compile(PERSONS_ACTION.pattern.format(when=forms), re.IGNORECASE)
    return frozenset(_low(m.group("before") or m.group("after")) for m in pattern.finditer(span))


def _leads_its_clause(text: str, span: tuple[int, int] | None, forms: frozenset[str]) -> bool:
    """Whether the clause holding `span` opens with one of `forms`, after filler only."""
    start = max([0] + [m.end() for m in CLAUSE_END.finditer(text[: span[0]])]) if span else 0
    for raw, _, _ in _request_tokens(text[start : span[1] if span else len(text)]):
        if _low(raw) in forms:
            return True
        if _low(raw) not in FILLER | ME_WORDS:
            return False
    return False


def _own_run(text: str, explained: frozenset[str]) -> tuple[int, int] | None:
    """The longest run of the request's words a structure explains, with filler between, when
    it holds at least two such words: where the structure stands when the model quoted
    nothing for it ("the open DESK bugs"). None when no run is that long."""
    best: tuple[int, int] | None = None
    best_count = 0
    run: list[tuple[int, int]] = []
    count = 0
    for raw, start, end in _request_tokens(text) + [("", len(text), len(text))]:
        low = _low(raw)
        if raw and low in explained:
            run.append((start, end))
            count += 1
        elif raw and low in FILLER and run:
            run.append((start, end))
        else:
            if count >= 2 and count > best_count:
                first = next(a for a, b in run if _low(text[a:b]) in explained)
                last = next(b for a, b in reversed(run) if _low(text[a:b]) in explained)
                best, best_count = (first, last), count
            run, count = [], 0
    return best


def render_search(read: SearchRead, text: str) -> Rendered:
    """The look-for row, written from the search. A filter the request never framed is dropped,
    so its words come back to the person instead of a claim. With no quote from the model, the
    search stands on the longest run of its own words in the request."""
    said = _locate(text, read.said)
    explained: set[str] = set(SEARCH_VOCAB)
    if _leads_its_clause(text, said, REVIEW):
        explained.update(REVIEW)
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
        explained.update(STILL)
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
        # A day filter on a date the request never names, as "the last comment is older than 5
        # days" read as no update, is dropped like an assignee or a topic it never framed.
        if filter_ is None or not _forms_in(text, WHEN_VOCAB[when]):
            continue
        shown = _days_text(when, filter_)
        if shown is None:
            continue
        tail.append(shown)
        quoted = text[said[0] : said[1]] if said is not None else ""
        explained.update((WHEN_VOCAB[when] - _persons_action(quoted, when)) | DAYS_VOCAB)
        if filter_.days is not None:
            if said_in(str(filter_.days), text) or (filter_.days == 0 and said_in("today", text)):
                explained.add(str(filter_.days))
            else:
                sourced = False
    topic = _topic(text, read.words)
    if topic is not None:
        tail.append(f'with "{topic[0]}" in the title or body')
        explained.update(topic[1])
    shown = " ".join(parts) + (", " + ", ".join(tail) if tail else "")
    shown = shown[:1].upper() + shown[1:]
    row = UnderstoodRow(
        kind="look_for",
        text=plain(shown, TEXT_LIMIT),
        state="understood" if sourced else "changed",
        note=_note(text, said, sourced),
    )
    stands = said if said is not None else _own_run(text, frozenset(explained))
    return Rendered(row, frozenset(explained), stands)


def _open_as_create(text: str) -> frozenset[str]:
    """ "open" explains a request word only as the verb that opens a ticket, as in "open one
    ticket", never as the state of the tickets looked for."""
    tokens = [_low(t) for t, _, _ in _request_tokens(text)]
    for at, token in enumerate(tokens[:-1]):
        if token in ("open", "opens", "opening") and tokens[at + 1] in OPEN_AS_CREATE_AFTER:
            return frozenset({token})
    return frozenset()


def render_ticket(read: TicketRead, text: str) -> Rendered:
    """The do row, written from what happens with what was found. A detail is kept only when
    the request's own words for the ticket ask for it, in the quote as the request writes it
    or in its own words for the new ticket; a detail the model added is dropped, not claimed."""
    said = _locate(text, read.said)
    phrase = CREATE_PHRASE.search(text) if read.creates else None
    also = None if phrase is None else (phrase.start(), phrase.end())
    verbatim = _find(text, read.said)
    quoted = " ".join(text[span[0] : span[1]] for span in (verbatim, also) if span is not None)
    explained: set[str] = set(SAYS_VOCAB[read.says])
    if phrase is not None:
        explained.update(k.casefold() for k in PROJECT_KEY.findall(phrase.group(0)))
    what = {"list": "lists them", "count": "counts them", "summary": "sums them up"}[read.says]
    details: list[str] = []
    for detail in dict.fromkeys(read.shows):
        if not _forms_in(quoted, SHOWS_VOCAB[detail]):
            continue
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
    row = UnderstoodRow(
        kind="do",
        text=plain(shown, TEXT_LIMIT),
        state="understood",
        note=_note(text, _joined(text, verbatim, also), True),
    )
    return Rendered(row, frozenset(explained), said, also)


def _joined(
    text: str, said: tuple[int, int] | None, also: tuple[int, int] | None
) -> tuple[int, int] | None:
    """The request's words for the ticket, as one span when the model's quote and the request's
    own words for the new ticket stand together ("create one follow-up ticket that lists
    them" for a quote of "lists them"), so the note quotes the person's whole phrase."""
    if said is None or also is None:
        return said if said is not None else also
    start, end = min(said[0], also[0]), max(said[1], also[1])
    gap = text[min(said[1], also[1]) : max(said[0], also[0])]
    between = [_low(t) for t, _, _ in _request_tokens(gap)]
    return (start, end) if all(t in FILLER for t in between) else said


def render_place(read: PlaceRead, text: str) -> Rendered:
    """The where row, standing on the words the model quoted for the place ("in MOCK"), else
    on the key's last mention in the request."""
    project = _project_in(text, read.project)
    said = _find(text, read.said, last=True)
    if project is None:
        return Rendered(missing_row("where"), frozenset(), said)
    if said is None or not said_in(project, text[said[0] : said[1]]):
        # The model often fills the project and leaves said empty: the key as the request
        # writes it is the person's own, so the row stands on its last mention, in capitals
        # where the request writes it so, because "its" in "with its Environment" is not ITS.
        keys = list(re.finditer(rf"(?<!\w){re.escape(project)}(?!\w)", text))
        said = (keys[-1].start(), keys[-1].end()) if keys else _find(text, project, last=True)
    sourced = said is not None
    row = UnderstoodRow(
        kind="where",
        text=f"Jira project {project}",
        state="understood" if sourced else "changed",
        note=_note(text, said, sourced),
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


def _schedule_span(text: str, shown: str) -> tuple[int, int] | None:
    """Where the request's schedule stands: the model's schedule words as the request writes
    them, else the request's first run of schedule words, which is the person's own phrase
    for it ("Each week" read as "Every Monday"). A day word anywhere else, as in "finished by
    this Friday", is not the schedule's, and comes back if nothing else explains it."""
    found = _find(text, shown)
    if found is not None:
        return found
    run: list[tuple[int, int]] = []
    for raw, start, end in _request_tokens(text):
        if _schedule_token(raw):
            run.append((start, end))
        elif run:
            break
    return (
        None
        if not run or not any(_a_schedule_word(text[a:b]) for a, b in run)
        else (run[0][0], run[-1][1])
    )


def _schedule_explained(text: str) -> frozenset[str]:
    """What the schedule explains inside its own span: schedule words, and clock tokens and
    numbers as the request writes them."""
    return SCHEDULE_VOCAB | frozenset(
        _low(raw) for raw, _, _ in _request_tokens(text) if _schedule_token(raw)
    )


def render_schedule(schedule: str | None, text: str) -> Rendered:
    """The schedule row: the model's words kept to schedule words only, with a time the request
    never said asked for, not filled in, and a day it never said shown as a guess. With no
    schedule read, the row is missing and asks for one, and the request's own schedule words
    stand under it, so they are never a can't of another kind."""
    kept = [t for t in (visible_words(schedule) or "").split() if _schedule_token(t.strip(",."))]
    shown = " ".join(kept).strip(" ,")
    said = _schedule_span(text, shown)
    explained = _schedule_explained(text)
    if not any(_low(t) in SCHEDULE_WORDS or CLOCK_TOKEN.match(_low(t)) for t in kept):
        return Rendered(missing_row("schedule"), explained, said)
    if any(not said_in(time.strip(), text) for time in TIME_OF_DAY.findall(shown)):
        return Rendered(missing_row("schedule", _no_time_said(shown, text)), explained, said)
    guessed = [w for w in re.findall(r"\w+", shown) if w.casefold() in SCHEDULE_WORDS]
    sourced = _find(text, shown) is not None and all(said_in(w, text) for w in guessed)
    row = UnderstoodRow(
        kind="schedule",
        text=plain(shown[:1].upper() + shown[1:], TEXT_LIMIT),
        state="understood" if sourced else "changed",
        note=None if sourced else FILLED_IN,
    )
    return Rendered(row, explained, said)


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


def _asks_for_a_change(words: str) -> bool:
    """Whether the words order a change themselves, as "flag the new ticket", "and set their
    priority" or "email me a copy". A change verb that is not an order, as "my call" or "is set
    to Staging", is not one."""
    return commands_a_change(words) or (starts_with_a_verb(words) and bool(change_verbs_in(words)))


def _overlaps(said: tuple[int, int] | None, run: tuple[int, int]) -> bool:
    return said is not None and run[0] < said[1] and run[1] > said[0]


def _kind_of(
    text: str, start: int, end: int, run: tuple[int, int], said: Said, beside: RowKind | None
) -> RowKind | None:
    """The part the words are, judged on the words no structure explains in them (`run`):
    inside the model's quote for the search, what to look for; schedule words only, the
    schedule; an order for a change, the do part; else the part the place's quote covers, the
    part whose words they stand beside, or the part a quote covers. The model's quote for the
    ticket often covers the whole request, so it decides last. Words that still fit no part
    are what to look for when they name tickets, else None."""
    look = said.get("look_for")
    if look is not None and look[0] <= start and end <= look[1]:
        return "look_for"
    content = [t for t, _, _ in _request_tokens(text[start:end]) if _low(t) not in FILLER]
    if content and all(_schedule_token(t) for t in content):
        return "schedule"
    if _asks_for_a_change(text[run[0] : run[1]]):
        return "do"
    if _overlaps(said.get("where"), run):
        return "where"
    if beside is not None:
        return beside
    if _overlaps(said.get("do"), run):
        return "do"
    if _overlaps(said.get("look_for"), run) or any(_low(t) in TICKETS for t in content):
        return "look_for"
    return None


BESIDE_FIRST: Final[tuple[RowKind, ...]] = ("look_for", "do", "where", "schedule")
"""Which part a word two structures explain belongs to, as "tickets" in "the SUP tickets with
more than 10 comments", which the search and the new ticket both explain."""


def _beside(
    clause_of: list[int], parts_at: dict[int, set[RowKind]], first: int, last: int
) -> RowKind | None:
    """The part whose words the unexplained words from token `first` to `last` stand beside in
    their clause: the nearest word a structure explains before them, else after them, as
    "tasks" before "10 hours logged" in "the OPS tasks with over 10 hours logged"."""
    for at in (*range(first - 1, -1, -1), *range(last + 1, len(clause_of))):
        if clause_of[at] == clause_of[first] and parts_at.get(at):
            return next(k for k in BESIDE_FIRST if k in parts_at[at])
    return None


def negated(text: str) -> bool:
    """Whether the words say no to something, as "don't ping me" or "run it without me"."""
    return NEGATED.search(text) is not None


def names_a_yes(text: str) -> bool:
    """Whether the words name a yes, or a person left out of one."""
    text = FROM_ME.sub(" ", text)
    if A_YES.search(text) is not None or NOBODY.search(text) is not None:
        return True
    return SOMEONE.search(text) is not None and NEGATED.search(text) is not None


STATEMENT: Final = re.compile(
    r"\b(?:can|could|will|would|shall|should|may|might|must|is|are|was|were)\b|n't\b",
    re.IGNORECASE,
)


def a_statement(text: str) -> bool:
    """Whether the words are a statement about someone or something rather than an order:
    "the change board can catch up on it" has a modal after its first word."""
    first = TOKEN.search(text)
    return first is not None and STATEMENT.search(text[first.end() :]) is not None


def names_a_person(text: str, start: int, end: int) -> bool:
    """Whether the request's words from `start` to `end` name another person, a role or a
    group as someone who acts: one of `SOMEONE`, or a capitalised word that is not the
    request's first word, a project key, a system, or a word a structure could explain, framed
    as `NAMED_ACTOR` says. A person left out, as "without anyone", is `names_a_yes`'s."""
    for match in NAMED_ACTOR.finditer(text[start:end]):
        name = match.group("before") or match.group("after")
        if SOMEONE.fullmatch(name) is not None:
            return True
        if not NAME.fullmatch(name):
            continue
        at = start + match.start(match.lastgroup or "after")
        if at == 0 or name.casefold() in KNOWN_WORDS or name.casefold() in SYSTEMS:
            continue
        return True
    return False


KNOWN_WORDS: Final = (
    FILLER
    | SCHEDULE_VOCAB
    | SEARCH_VOCAB
    | REVIEW
    | STILL
    | ME_WORDS
    | ASSIGNEE_VOCAB
    | DAYS_VOCAB
    | TOPIC_VOCAB
    | CREATE_VOCAB
    | PLACE_VOCAB
    | frozenset(w for v in STATUS_VOCAB.values() for w in v)
    | frozenset(w for v in WHEN_VOCAB.values() for w in v)
    | frozenset(w for v in SAYS_VOCAB.values() for w in v)
    | frozenset(w for v in SHOWS_VOCAB.values() for w in v)
    | frozenset(TYPE_BY_FORM)
)
"""Every word a structure could explain, so a capitalised one of them at a clause's front
("Create", "List", "Every") is never read as a name."""


def _region(
    tokens: list[tuple[str, int, int]],
    clause_of: list[int],
    core: tuple[int, int],
    explained: frozenset[str],
) -> set[int]:
    """The token indexes a structure stands in: every token of `core`, the stretch of the
    request it was located in, grown outwards over filler and the structure's own words until
    a word it does not explain or the end of the clause. "me" after a verb the structure
    explains ("Show me the") is passed over."""
    inside = [i for i, (_, start, end) in enumerate(tokens) if start < core[1] and end > core[0]]
    if not inside:
        return set()
    found = set(inside)

    def own(i: int) -> bool:
        low = _low(tokens[i][0])
        return low in FILLER or low in explained

    for step, edge in ((-1, inside[0]), (1, inside[-1])):
        i = edge + step
        while 0 <= i < len(tokens) and clause_of[i] == clause_of[edge]:
            if own(i) or (
                step == -1
                and _low(tokens[i][0]) in ME_WORDS
                and i - 1 >= 0
                and clause_of[i - 1] == clause_of[edge]
                and _low(tokens[i - 1][0]) in explained
            ):
                found.add(i)
            else:
                break
            i += step
    return found


def leftovers(
    text: str,
    rendered: list[Rendered],
    covered: list[tuple[int, int]],
    said: Said,
    writes: bool = False,
) -> list[Span]:
    """The request's words that nothing explains, clause by clause. A structure explains a
    word only where it stands: in the stretch of the request its quote was located in, and
    the run of its own words and filler around that, so the search's assignee never explains
    "assign" in the new ticket's clause, and the schedule never explains "Friday" in "finished
    by this Friday". A clause whose first content word is unexplained comes back from that
    word to its end, because the whole part is unread; otherwise the run from the first
    unexplained word to the last. A "without", "no" or "not" right before the run comes with
    it, so "without approval" keeps its "without". In a request that writes, a run that names
    a yes, a person, a role or a group takes its whole clause, so the refusal reads as the
    person wrote it."""
    tokens = _request_tokens(text)
    clauses = _clauses(text)
    clause_of = [
        next((n for n, (a, b) in enumerate(clauses) if a <= start < b), -1)
        for _, start, _ in tokens
    ]
    explains: list[set[int]] = []
    for r in rendered:
        region: set[int] = set()
        for core in (r.said, r.also):
            if core is not None:
                region |= _region(tokens, clause_of, core, r.explained)
        explains.append({i for i in region if _low(tokens[i][0]) in r.explained})
    parts_at: dict[int, set[RowKind]] = {}
    for r, found in zip(rendered, explains, strict=True):
        for i in found:
            parts_at.setdefault(i, set()).add(r.row.kind)
    known = set[int]().union(*explains) if explains else set[int]()
    # A cover inside the search's own quote ("by me" in "the PAY tickets opened by me") would
    # hide a filter the search can't run, so the staff member's attention is only ever theirs
    # to skip outside it.
    quoted = [r.said for r in rendered if r.row.kind == "look_for" and r.said is not None]
    covered = [(a, b) for a, b in covered if not any(q[0] <= a and b <= q[1] for q in quoted)]
    known |= {
        i
        for i, (_, start, end) in enumerate(tokens)
        if any(a <= start and end <= b for a, b in covered)
    }
    spans: list[Span] = []
    for n, (c_start, c_end) in enumerate(clauses):
        clause = text[c_start:c_end]
        theirs = [(c_start + m.start(), c_start + m.end()) for m in FROM_ME.finditer(clause)]
        content: list[tuple[int, int]] = []
        unread: list[int] = []
        before = ""
        at = 0
        for i, (raw, start, end) in enumerate(tokens):
            if clause_of[i] != n:
                continue
            low = _low(raw)
            names = (
                A_YES.fullmatch(raw) is not None
                or SOMEONE.fullmatch(raw) is not None
                or (low == "one" and before == "no")
                or (low in ("team", "boss") and before == "the")
            ) and not any(a <= start and end <= b for a, b in theirs)
            filler = low in FILLER and not (raw[:1].isupper() and at) and not names
            before = low
            at += 1
            if filler:
                continue
            content.append((start, end))
            if i not in known:
                unread.append(i)
        if not unread:
            continue
        _, first, _ = tokens[unread[0]]
        _, _, last = tokens[unread[-1]]
        run = (first, last)
        start = first
        end = c_end if first == content[0][0] else last
        lead = LEAD_IN.search(text[c_start:start])
        if lead is not None:
            start = c_start + lead.start()
        names = names_a_yes(text[start:end])
        someone = names_a_person(text, start, end)
        if (names or someone) and writes:
            start, end = content[0][0], c_end
        start, end = _trim(text, start, end)
        beside = _beside(clause_of, parts_at, unread[0], unread[-1])
        kind = _kind_of(text, start, end, run, said, beside)
        spans.append(Span(text[start:end], start, end, kind, names, someone))
    return spans


def task_shaped(read: TaskRead, text: str) -> bool:
    """Whether the reading, or the request, describes a task: a structure is filled, or the
    request asks for a change in its own words."""
    return any((read.search, read.ticket, read.place, read.schedule)) or bool(change_verbs_in(text))


def speaks_only_of_self(text: str, start: int, end: int) -> bool:
    """Whether the request's words from `start` to `end`, which the model called the staff
    member's own, really name them and nobody else: the words say I, me, my, mine or myself,
    and no yes, no other person, and no name."""
    quote = FROM_ME.sub(" me ", text[start:end])
    return (
        SPEAKS_OF_SELF.search(quote) is not None
        and A_YES.search(quote) is None
        and SOMEONE.search(quote) is None
        and not names_a_person(text, start, end)
        and not any(
            NAME.fullmatch(w) and w.casefold() not in KNOWN_WORDS
            for w in re.findall(r"\w+", text[start:end])[1:]
        )
    )
