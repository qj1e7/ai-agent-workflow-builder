"""What the platform can do, and the rule that holds what the Planner read back to it.

`ABILITIES` is the whole list, one line for each thing the platform can do. A part the Planner
read back stays as the model said only when every action in it fits a line: its verb is one of the
line's verbs, the thing it makes is one the line makes, it mentions what the line is about when the
line names that, and every place it names is one the line reaches. Anything else is can't do, with
a note that says what the platform can't do yet. A new tool is one more line."""

import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from typing import Final, Literal, NamedTuple

from agent_runtime.contract import (
    CapabilityKind,
    CapabilityList,
    CapabilitySpec,
    CapabilityState,
    ConnectionId,
    ExampleSpec,
    RowKind,
    ToolId,
)

type Form = Literal["base", "s", "ing", "ed"]


def words(text: str) -> frozenset[str]:
    return frozenset(text.split())


JIRA: Final = "jira"
TICKETS: Final = words(
    "ticket tickets issue issues bug bugs story stories task tasks epic epics incident incidents "
    "subtask subtasks sub-task sub-tasks follow-up follow-ups followup followups"
)
OUTPUTS: Final = words(
    "summary summaries list lists report reports overview overviews digest digests table tables "
    "recap recaps roundup round-up breakdown count counts total totals tally note notes update "
    "updates rundown"
)
RELEASE_ROOTS: Final = {
    **dict.fromkeys(("version", "versions"), "version"),
    **dict.fromkeys(("release", "releases", "released", "releasing"), "release"),
    **dict.fromkeys(("upgrade", "upgrades", "upgraded", "upgrading"), "upgrade"),
    **dict.fromkeys(("patch", "patches", "patched", "patching"), "patch"),
}
VULNERABILITY_ROOTS: Final = dict.fromkeys(
    ("vulnerability", "vulnerabilities", "vulnerable"), "vulnerability"
)
VULNERABILITIES: Final = frozenset(VULNERABILITY_ROOTS) | words("cve cves nvd advisory advisories")
SECURITY_PHRASE_ENDS: Final = words("fix fixes patch patches alert alerts bulletin bulletins")
CVE_ID: Final = re.compile(r"cve-\d{4}-\d+")
VULNERABILITIES_PLANNED: Final = "I can't check for known vulnerabilities yet. It's planned."


@dataclass(frozen=True)
class Ability:
    plain: str
    verbs: frozenset[str]
    makes: frozenset[str] | None = None
    about: frozenset[str] | None = None
    reaches: frozenset[str] = frozenset({JIRA})


ABILITIES: Final = (
    Ability(
        "read Jira tickets",
        words(
            "find search look list read check count sum summarise summarize total tally group "
            "sort rank order collect gather compile compare review note pick select filter fetch "
            "get pull spot identify include keep track watch monitor scan query explain describe "
            "outline"
        ),
    ),
    Ability(
        "sum up what I find",
        words("write make draft prepare produce give compile create build generate put"),
        makes=OUTPUTS,
    ),
    Ability(
        "check software for new releases",
        words("check watch track monitor compare look"),
        about=frozenset(RELEASE_ROOTS),
        reaches=frozenset({"github"}),
    ),
    Ability(
        "create a Jira ticket after a yes",
        words("create add file raise open make log propose draft write submit put generate"),
        makes=TICKETS,
    ),
)

ABILITY_OF: Final = {
    "jira.read": "read Jira tickets",
    "jira.find_by_update": "read Jira tickets",
    "summarise": "sum up what I find",
    "github.releases": "check software for new releases",
    "jira.create": "create a Jira ticket after a yes",
}


def _ready(
    id: str,
    plain: str,
    kind: CapabilityKind,
    system: str | None,
    connection: ConnectionId | None,
    tools: list[ToolId],
    needs_model: bool = False,
    platform: bool = False,
    focus: bool = False,
    short: str | None = None,
) -> CapabilitySpec:
    return CapabilitySpec(
        id=id,
        plain=plain,
        kind=kind,
        system=system,
        state="ready",
        cant=None,
        why=None,
        connection=connection,
        needs_model=needs_model,
        platform=platform,
        focus=focus,
        tools=tools,
        short=short,
    )


def _not_yet(
    id: str,
    plain: str,
    kind: CapabilityKind,
    system: str | None,
    connection: ConnectionId | None,
    cant: str,
    why: str,
    state: CapabilityState = "planned",
    short: str | None = None,
    instead: str | None = None,
) -> CapabilitySpec:
    return CapabilitySpec(
        id=id,
        plain=plain,
        kind=kind,
        system=system,
        state=state,
        cant=cant,
        why=why,
        connection=connection,
        needs_model=False,
        platform=False,
        focus=False,
        tools=[],
        short=short,
        instead=instead,
    )


CAPABILITIES: Final = (
    _ready(
        "jira.read",
        "Read Jira tickets",
        "read",
        "Jira",
        "jira",
        ["jira.search", "jira.read_ticket"],
        needs_model=True,
    ),
    _ready(
        "jira.find_by_update",
        "Find tickets by when they were last updated, their type or who owns them",
        "read",
        "Jira",
        "jira",
        ["jira.search"],
        needs_model=True,
    ),
    _not_yet(
        "jira.find_by_detail",
        "Find tickets by their component or priority",
        "read",
        "Jira",
        "jira",
        "see a ticket's component or priority",
        "Those details don't reach the agents yet.",
    ),
    _not_yet(
        "jira.find_older",
        "Find older tickets, beyond the newest 50",
        "read",
        "Jira",
        "jira",
        "look past the 50 newest tickets",
        "A search stops there.",
    ),
    _ready("summarise", "Sum up what I find", "none", None, None, [], needs_model=True),
    _ready(
        "github.releases",
        "Check software for new releases on GitHub",
        "read",
        "GitHub",
        "github",
        ["github.read_releases"],
        focus=True,
        short="Watch software for new releases",
    ),
    _ready(
        "jira.create",
        "Create a Jira ticket after a yes",
        "write",
        "Jira",
        "jira",
        ["jira.create_ticket"],
        needs_model=True,
        focus=True,
        short="Create Jira tickets, after a yes",
    ),
    _ready(
        "teams.ask",
        "Ask Approvers for a yes in Teams",
        "notify",
        "Teams",
        "teams",
        [],
        platform=True,
        focus=True,
    ),
    _ready(
        "runs.explain",
        "Explain a stopped run, and retry it",
        "none",
        None,
        None,
        [],
        platform=True,
        short="Explain a stopped run, and retry it",
    ),
    _ready(
        "workflows.change",
        "Change when a workflow runs, or pause it",
        "none",
        None,
        None,
        [],
        platform=True,
        short="Change or pause your workflows",
    ),
    _not_yet(
        "teams.post",
        "Posts in Teams and emails",
        "notify",
        "Teams",
        None,
        "post in Teams or send email",
        "The team's Tell flow isn't connected yet. Until it is, Teams carries approval requests, "
        "run outcomes and requests for the team, and nothing is emailed.",
        # Two names in the chat's Not yet note, as the sketch lists them. Once the flow is set,
        # platform-api makes the entry ready and names it by its plain words.
        short="Teams channels, email",
        instead="Run results show here, in the chat.",
    ),
    _not_yet(
        "confluence.change",
        "Change Confluence pages",
        "write",
        "Confluence",
        None,
        "update Confluence",
        "Confluence isn't connected to the platform.",
        short="Confluence",
        instead="I can create a Jira ticket, after a yes.",
    ),
    _not_yet(
        "github.issues",
        "Read GitHub issues",
        "read",
        "GitHub",
        "github",
        "read GitHub issues",
        "There's no tool for that yet.",
    ),
    _not_yet(
        "access.check",
        "Check who has access in Entra ID, the admin tools and GitLab",
        "read",
        None,
        None,
        "check who has access",
        "Those systems aren't connected to the platform.",
    ),
    _not_yet(
        "registries.check",
        "Check package registries and security advisories",
        "read",
        None,
        None,
        "check registries or security advisories",
        "Only GitHub releases are checked today.",
    ),
    _not_yet(
        "jira.set_field",
        "Set a field such as a component on new Jira tickets",
        "write",
        "Jira",
        "jira",
        "set a component",
        "That needs a new tool. The team decides on new tools.",
    ),
    _not_yet(
        "slack.send",
        "Send Slack or text messages",
        "write",
        None,
        None,
        "send Slack or text messages",
        "Slack and text messages aren't on the team's plan.",
        state="unsupported",
    ),
    _not_yet(
        "jira.delete",
        "Delete Jira tickets",
        "write",
        "Jira",
        "jira",
        "delete anything in Jira",
        "Only people do that here.",
        state="unsupported",
        instead="A Jira admin can do that.",
    ),
    _not_yet(
        "jira.change_tickets",
        "Close, edit or move tickets",
        "write",
        "Jira",
        "jira",
        "close, edit or move tickets",
        "Only people do that here.",
        state="unsupported",
    ),
)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


EXAMPLES: Final = (
    ExampleSpec(
        text="Keep track of the LangGraph version", kind="monitor", needs=["github.releases"]
    ),
    ExampleSpec(text="What can you do?", kind="learn", needs=[]),
)
CAPABILITY_LIST: Final = CapabilityList(capabilities=list(CAPABILITIES), examples=list(EXAMPLES))

WRITES: Final = words(
    "close resolve cancel reopen delete remove purge erase wipe destroy trash discard drop archive "
    "update edit change modify rename replace rewrite set label tag flag mark prioritise "
    "prioritize escalate transition move merge link unlink attach lock unlock bump convert split "
    "fix assign reassign unassign comment reply post send share forward publish message text "
    "email mail notify remind ping nudge chase tell ask alert warn inform contact invite dm "
    "broadcast announce upload export save copy download print grant revoke disable enable "
    "suspend deactivate activate block unblock ban reset restart reboot deploy run install "
    "uninstall upgrade patch execute trigger kill rollback push commit sync schedule book call"
)
SYSTEMS: Final = {
    "jira": "Jira",
    "github": "GitHub",
    "gitlab": "GitLab",
    "bitbucket": "Bitbucket",
    "servicenow": "ServiceNow",
    "devops": "Azure DevOps",
    "trello": "Trello",
    "asana": "Asana",
    "zendesk": "Zendesk",
    "freshdesk": "Freshdesk",
    "confluence": "Confluence",
    "slack": "Slack",
    "outlook": "Outlook",
    "sharepoint": "SharePoint",
    "onedrive": "OneDrive",
    "excel": "Excel",
    "entra": "Entra",
    "azure": "Azure",
    "notion": "Notion",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "discord": "Discord",
    "zoom": "Zoom",
    "gmail": "Gmail",
    "google": "Google",
    "airtable": "Airtable",
    "dropbox": "Dropbox",
    "salesforce": "Salesforce",
    "jenkins": "Jenkins",
    "email": "email",
    "e-mail": "email",
    "mail": "email",
    "sms": "text messages",
    "teams": "Teams",
}
CASE_SENSITIVE: Final = words("teams")
TICKET_SYSTEMS: Final = words(
    "jira github gitlab bitbucket servicenow devops trello asana zendesk freshdesk"
)
PLACES: Final = words(
    "sheet sheets spreadsheet spreadsheets workbook page pages wiki doc docs document documents "
    "file files folder folders drive chat chats channel channels inbox mailbox message messages "
    "dm thread repo repos repository repositories branch branches pr prs server servers database "
    "calendar site website"
)
JIRA_ANCHORS: Final = words("jira project projects board boards backlog queue")
PROJECT_WORDS: Final = words("project board")
RUN_PLACES: Final = words("run run's report")
WHERE_WORDS: Final = words(
    "the a an one new same single our my your their its this that it them in into to on under "
    "inside within of for as and or plus default saved agent agent's card card's team team's "
    "results result created raised filed logged opened put goes go will be is are"
)
NOT_KEYS: Final = words("AD AWS GCP SSO MFA VPN PR PRS MR CI CD API URL SMS CSV PDF HR OK")
PLACING: Final = words("put go")
PLACE_ADVERBS: Final = words("somewhere anywhere everywhere elsewhere wherever here there")
PLACING_FORMS: Final = words("put puts putting go goes going went gone")
DELIVERS: Final = words("post send share save publish")
TOPICS: Final = (
    words(
        "outage outages incident incidents migration migrations rollout rollouts downtime "
        "problem problems error errors decommission decommissioning review reviews"
    )
    | frozenset(RELEASE_ROOTS)
    | VULNERABILITIES
)
SUBJECTS: Final = words("i we you")
WANTING: Final = words("want wants need needs would like prefer")

STRONG: Final = words("then also afterwards afterward finally additionally")
SOFT: Final = words("and or plus but next later before after while & + , ; : . ! ? ( )")
HARD: Final = frozenset(";:.!?()")
FILLER: Final = words(
    "please kindly just also then and or so now next finally first firstly simply always "
    "automatically afterwards afterward later plus additionally that to after before while but "
    "& +"
)
PARTICLES: Final = words("up down out together back off away")
PREPS: Final = words(
    "to into onto in on inside within under at via through over for of with without by about "
    "from per across after before since until during against among between like than as "
    "regarding toward towards"
)
TO_PLACE: Final = words("to into onto")
IN_PLACE: Final = words("in on inside within under at via through")
SOURCES: Final = words("in from on inside within at across")
ENDS: Final = words(
    "that which who whom where when whenever if whether so because unless once while then also but"
)
DETERMINERS: Final = words(
    "the a an no every each any some all their its his her our my your this these those whose "
    "last latest first new recent per one two three several many few more most other another "
    "such own same both either neither"
)
NOUN_AFTER: Final = words("with without of per about")
PRONOUNS: Final = words("them it they these those all everything each both one ones")
NAMES_NOTHING: Final = DETERMINERS | PREPS | PRONOUNS | PLACING_FORMS
NEW: Final = words("a an one new single")
MODALS: Final = words("should must will would can could may might shall to need needs")
GETS: Final = words("get gets got getting gotten")
CAUSATIVES: Final = words(
    "get gets got getting have having make makes making keep keeps kept leave leaves let lets "
    "want wants need needs see"
)
IRREGULAR: Final = {
    "send": ("sent",),
    "write": ("wrote", "written"),
    "rewrite": ("rewrote", "rewritten"),
    "tell": ("told",),
    "get": ("got", "gotten"),
    "give": ("gave", "given"),
    "make": ("made",),
    "find": ("found",),
    "keep": ("kept",),
    "run": ("ran",),
    "build": ("built",),
}
VOWELS: Final = "aeiou"
MARKS: Final = "".join(
    chr(code) for code in range(0x300, 0x20000) if unicodedata.category(chr(code))[0] == "M"
)
"""Accents and vowel signs written as their own character, as in Tamil or a decomposed "é"."""
LETTERS: Final = rf"[^\W\d_](?:[^\W\d_]|[{MARKS}])*"
"""Letters of any script. On ASCII text it is exactly [A-Za-z]+."""
LETTERS_DIGITS: Final = rf"[^\W_](?:[^\W_]|[{MARKS}])*"
"""Letters and digits of any script. On ASCII text it is exactly [A-Za-z0-9]+."""
TOKEN: Final = re.compile(rf"{LETTERS_DIGITS}(?:['’]{LETTERS}|[-/.]{LETTERS_DIGITS})*|[,;:.!?&+()]")
KEY: Final = re.compile(r"[A-Z][A-Z0-9]{1,9}(?:-[0-9]{1,9})?")
CAMEL: Final = re.compile(r"[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*")
SAID_LIMIT: Final = 90


@dataclass(frozen=True)
class _Word:
    raw: str
    low: str
    starts: bool

    @property
    def bare(self) -> str:
        return self.low.replace("-", "").replace("'", "")

    @property
    def mark(self) -> bool:
        return not self.raw[:1].isalnum()

    @property
    def capital(self) -> bool:
        return self.raw[:1].isupper()

    @property
    def proper(self) -> bool:
        return not self.starts and self.capital and not self.raw.isupper()

    @property
    def key(self) -> bool:
        return KEY.fullmatch(self.raw) is not None and self.raw not in NOT_KEYS

    @property
    def system(self) -> str | None:
        """The system the word names, also with an 's, as in "Slack's". A trailing s' never
        reaches here: TOKEN drops an apostrophe with no letter after it."""
        name = self.low.removesuffix("'s")
        if name in CASE_SENSITIVE and not self.capital:
            return None
        return name if name in SYSTEMS else None

    @property
    def product(self) -> bool:
        return self.system is None and CAMEL.fullmatch(self.raw) is not None


type Clause = tuple[_Word, ...]
type Phrases = list[tuple[str, Clause]]


class _Objects(NamedTuple):
    things: list[Clause]
    end: int


def _tokens(text: str) -> Clause:
    found: list[_Word] = []
    starts = True
    for raw in TOKEN.findall(text):
        found.append(_Word(raw, raw.casefold().replace("’", "'"), starts))
        starts = raw in HARD
    return tuple(found)


def _inflections(verb: str) -> dict[str, Form]:
    out: dict[str, Form] = {verb: "base"}
    consonant_y = verb.endswith("y") and verb[-2:-1] not in VOWELS
    if verb.endswith(("s", "x", "z", "ch", "sh")):
        out.setdefault(verb + "es", "s")
    elif consonant_y:
        out.setdefault(verb[:-1] + "ies", "s")
    else:
        out.setdefault(verb + "s", "s")
    if verb.endswith("ie"):
        out.setdefault(verb[:-2] + "ying", "ing")
    elif verb.endswith("e") and not verb.endswith(("ee", "ye", "oe")):
        out.setdefault(verb[:-1] + "ing", "ing")
    else:
        out.setdefault(verb + "ing", "ing")
    if verb.endswith("e"):
        out.setdefault(verb + "d", "ed")
    elif consonant_y:
        out.setdefault(verb[:-1] + "ied", "ed")
    else:
        out.setdefault(verb + "ed", "ed")
    short = len(verb) >= 3 and verb[-3] not in VOWELS and verb[-2] in VOWELS
    if short and verb[-1] not in VOWELS + "wxy":
        out.setdefault(verb + verb[-1] + "ing", "ing")
        out.setdefault(verb + verb[-1] + "ed", "ed")
    for past in IRREGULAR.get(verb, ()):
        out.setdefault(past, "ed")
    return out


@dataclass(frozen=True)
class _Reader:
    abilities: tuple[Ability, ...]
    forms: dict[str, tuple[str, Form]]
    writes: frozenset[str]

    def verb(self, word: _Word) -> tuple[str, Form] | None:
        return None if word.mark else self.forms.get(word.bare)

    def acts(self, word: _Word) -> bool:
        return self.verb(word) is not None and not word.proper

    def can(self) -> str:
        if self.abilities is ABILITIES:
            plain = [_lower_first(c.plain) for c in CAPABILITIES if c.state == "ready" and c.focus]
        else:
            plain = list(dict.fromkeys(ability.plain for ability in self.abilities))
        listed = plain[0] if len(plain) == 1 else f"{', '.join(plain[:-1])}, and {plain[-1]}"
        return f"I can only {listed}."


@cache
def _reader(abilities: tuple[Ability, ...]) -> _Reader:
    able = frozenset(verb for ability in abilities for verb in ability.verbs)
    forms: dict[str, tuple[str, Form]] = {}
    for verb in sorted(able | WRITES):
        for form, kind in _inflections(verb).items():
            forms.setdefault(form, (verb, kind))
    return _Reader(abilities, forms, WRITES - able)


def _content(word: _Word) -> bool:
    return not word.mark and word.low not in FILLER


def _action_at(clause: Clause) -> int | None:
    return next((i for i, word in enumerate(clause) if _content(word)), None)


def _noun_place(before: _Word | None) -> bool:
    return before is not None and before.low in DETERMINERS | NOUN_AFTER


def _starts_clause(row: Clause, at: int, reader: _Reader, purpose: bool) -> bool:
    word = row[at]
    if word.low in STRONG:
        return True
    if word.low not in SOFT and not (purpose and word.low == "to"):
        return False
    after = next((w for w in row[at + 1 :] if _content(w)), None)
    return after is not None and reader.acts(after)


def _clauses(row: Clause, reader: _Reader, purpose: bool) -> list[Clause]:
    clauses: list[list[_Word]] = [[]]
    for at, word in enumerate(row):
        if any(_content(w) for w in clauses[-1]) and _starts_clause(row, at, reader, purpose):
            clauses.append([])
        clauses[-1].append(word)
    return [tuple(clause) for clause in clauses if clause]


def _cant_phrase(clause: Clause, reader: _Reader) -> str:
    first, *rest = clause
    found = reader.verb(first)
    titled = first.raw[1:] == first.raw[1:].lower()
    if found is not None:
        shown = found[0]
    elif first.low in CAUSATIVES or (
        first.system is None and first.capital and titled and first.starts and first.raw != "I"
    ):
        shown = first.low
    else:
        shown = first.raw
    for word in rest:
        glued = word.raw in ",;:.!?)" or shown.endswith("(")
        shown += word.raw if glued else f" {word.raw}"
    shown = shown.strip(" ,;:.!?")
    if shown.endswith(")") and "(" not in shown:
        shown = shown[:-1]
    if len(shown) <= SAID_LIMIT:
        return shown
    return shown[: SAID_LIMIT - 1].rsplit(" ", 1)[0] + "…"


def _objects(clause: Clause, start: int, reader: _Reader) -> _Objects:
    at = start
    while at < len(clause) and clause[at].low in PARTICLES:
        at += 1
    things: list[list[_Word]] = [[]]
    while at < len(clause):
        word = clause[at]
        acts = bool(things[-1]) and reader.acts(word) and not _noun_place(things[-1][-1])
        if word.low in ("and", "or", ","):
            things.append([])
        elif word.mark or word.low in PREPS | ENDS | PARTICLES or acts:
            break
        else:
            things[-1].append(word)
        at += 1
    return _Objects([tuple(thing) for thing in things if thing], at)


def _phrases(clause: Clause, start: int, reader: _Reader) -> Phrases:
    """The phrases after what the action is done to, each with its preposition. The words after
    a mark, as in "(Slack)" or ": Teams", are a phrase too, with the mark in place of the
    preposition."""
    phrases: list[tuple[str, list[_Word]]] = []
    for word in clause[start:]:
        if word.low in PARTICLES and not phrases:
            continue
        if word.low in PREPS or word.mark:
            phrases.append((word.low, []))
            continue
        last = phrases[-1][1][-1] if phrases and phrases[-1][1] else None
        if not phrases or word.low in ENDS or (reader.acts(word) and not _noun_place(last)):
            break
        phrases[-1][1].append(word)
    return [(prep, tuple(phrase)) for prep, phrase in phrases]


def _every_phrase(clause: Clause, start: int, reader: _Reader) -> Phrases:
    """Every phrase from `start` on, read as `_phrases` reads them, and also the ones after a
    later verb or "that", as in "listing them for the Slack bot". A topic that is also a verb,
    as in "the GitLab access review", stays in its phrase."""
    phrases: list[tuple[str, list[_Word]]] = []
    taking = False
    for word in clause[start:]:
        if word.low in PREPS or word.mark:
            phrases.append((word.low, []))
            taking = True
            continue
        last = phrases[-1][1][-1] if phrases and phrases[-1][1] else None
        topic = last is not None and word.low in TOPICS
        if word.low in ENDS or (reader.acts(word) and not _noun_place(last) and not topic):
            taking = False
        elif taking:
            phrases[-1][1].append(word)
    return [(prep, tuple(phrase)) for prep, phrase in phrases]


def _head(thing: Clause) -> _Word | None:
    return next((w for w in reversed(thing) if not w.raw.isdigit() and not w.key), None)


def _elsewhere(phrase: Clause, reaches: frozenset[str], products: bool = True) -> bool:
    for word in phrase:
        if word.system is not None and word.system not in reaches:
            return True
        if word.low in PLACES or (products and word.product):
            return True
    return False


def _only_the_topic(phrase: Clause) -> bool:
    """Whether a phrase names another system only as what a result is about: it ends in a topic
    such as "outage" or "release", or in Jira tickets, as in "the Teams outage tickets", but not
    in that system's own, as in "the GitHub issue"."""
    for at in range(len(phrase) - 1, -1, -1):
        word = phrase[at]
        if word.raw.isdigit() or word.key:
            continue
        before = phrase[at - 1].system if at else None
        return word.low in TOPICS or (word.low in TICKETS and before not in TICKET_SYSTEMS)
    return False


def _another_systems_place(prep: str, phrase: Clause, known: frozenset[str]) -> bool:
    """Whether a phrase names a system the platform neither reaches nor reads, as in "for the
    Slack workspace" or "for the Teams admins", other than as the topic, as in "a ticket for the
    Teams outage". After "from" or a mark, as in "from the Slack outage" or "(Slack)", even a
    topic counts."""
    if all(word.system is None or word.system in known for word in phrase):
        return False
    return prep == "from" or not prep[:1].isalnum() or not _only_the_topic(phrase)


def _names_jira(phrase: Clause) -> bool:
    return any(w.low in JIRA_ANCHORS or w.key for w in phrase)


def _names_a_jira_place(word: _Word) -> bool:
    return word.key or word.low in JIRA_ANCHORS | TICKETS | RUN_PLACES


def _project_name(word: _Word, before: _Word | None, after: _Word | None) -> bool:
    beside = {w.low for w in (before, after) if w is not None}
    named_by = bool(beside & PROJECT_WORDS) or (
        before is not None and before.capital and before.low not in WHERE_WORDS
    )
    return word.capital and word.system is None and not word.product and named_by


def _jira_place_word(word: _Word, before: _Word | None, after: _Word | None) -> bool:
    return (
        _names_a_jira_place(word)
        or word.mark
        or word.low in WHERE_WORDS
        or _project_name(word, before, after)
    )


def _jira_place(phrase: Clause) -> bool:
    if not phrase:
        return False
    beside = zip((None, *phrase[:-1]), phrase, (*phrase[1:], None), strict=True)
    return (
        all(_jira_place_word(word, before, after) for before, word, after in beside)
        and any(_names_a_jira_place(word) for word in phrase)
        and not _elsewhere(phrase, frozenset({JIRA}))
    )


def _is_place(phrase: Clause, reaches: frozenset[str]) -> bool:
    if JIRA in reaches and _jira_place(phrase):
        return True
    named = {w.system for w in phrase if w.system is not None}
    rest = [w for w in phrase if w.system is None and not w.mark]
    return bool(named) and named <= reaches and all(w.low in WHERE_WORDS for w in rest)


def _makes(ability: Ability, makes: frozenset[str], thing: Clause, phrases: Phrases) -> bool:
    head = _head(thing)
    if head is None:
        return False
    if head.low in makes:
        before = thing[-2].system if len(thing) > 1 and thing[-1] is head else None
        if before is None or before in ability.reaches:
            return True
        return head.low in TICKETS and before not in TICKET_SYSTEMS
    if head.low not in PRONOUNS:
        return False
    return any(
        prep in TO_PLACE | IN_PLACE and place and place[0].low in NEW and place[-1].low in makes
        for prep, place in phrases
    )


def _fits(
    ability: Ability, thing: Clause, phrases: Phrases, around: Phrases, read: frozenset[str]
) -> bool:
    """Whether one thing the action is done to, and every phrase after it, fits the ability.
    `phrases` are the ones right after the thing, `around` every phrase to the end of the
    clause, and `read` every system the platform reads for this clause."""
    if ability.makes is None:
        reads = any(w.low in TICKETS for w in thing) or not _elsewhere(
            thing, ability.reaches, False
        )
    else:
        reads = _makes(ability, ability.makes, thing, phrases)
    if not reads:
        return False
    for at, (prep, phrase) in enumerate(phrases):
        if not phrase:
            continue
        strict = at == 0 and prep in TO_PLACE and ability.makes is not None
        if strict and not _is_place(phrase, ability.reaches):
            return False
        named = prep == "for" and all(w.system or w.low in DETERMINERS for w in phrase)
        if (prep in IN_PLACE | TO_PLACE or named) and _elsewhere(phrase, ability.reaches):
            return False
    known = ability.reaches | read
    return not any(_another_systems_place(prep, phrase, known) for prep, phrase in around)


def _asks_for_change(clause: Clause, at: int) -> bool:
    before = [w.low for w in clause[max(0, at - 3) : at]]
    if not before:
        return False
    if before[-1] in GETS:
        return True
    if before[-1] in ("be", "being") and len(before) > 1 and before[-2] in MODALS:
        return True
    if before[-1] in ("is", "are", "be") and any(w.low in ("sure", "ensure") for w in clause[:at]):
        return True
    return "been" not in before and any(w in CAUSATIVES for w in before[:-1])


def _writes_in(clause: Clause, at: int, reader: _Reader) -> bool:
    for i in range(at + 1, len(clause)):
        word = clause[i]
        found = reader.verb(word)
        if found is None or found[0] not in reader.writes or word.proper:
            continue
        if found[1] == "ed":
            if _asks_for_change(clause, i):
                return True
        elif not _noun_place(clause[i - 1]):
            return True
    return False


def _reading(reader: _Reader, clause: Clause) -> list[Ability]:
    """The abilities that read, and that fit what the clause is about."""
    return [
        ability
        for ability in reader.abilities
        if ability.makes is None
        and (ability.about is None or any(w.low in ability.about for w in clause))
    ]


def _do(clause: Clause, reader: _Reader) -> str | None:
    at = _action_at(clause)
    if at is None:
        return None
    action = clause[at]
    found = reader.verb(action)
    implied = found is None and action.low in DETERMINERS
    able = [
        ability
        for ability in reader.abilities
        if (ability.makes is not None if implied else found and found[0] in ability.verbs)
        and (ability.about is None or any(w.low in ability.about for w in clause))
    ]
    things, end = _objects(clause, at if implied else at + 1, reader)
    phrases = _phrases(clause, end, reader)
    around = _every_phrase(clause, end, reader)
    read = frozenset(place for ability in _reading(reader, clause) for place in ability.reaches)
    fits = bool(able) and all(
        any(_fits(a, t, phrases, around, read) for a in able) for t in things or [()]
    )
    if fits and not _writes_in(clause, at, reader):
        return None
    return _cant_phrase(clause[at:], reader)


def _do_row(row: Clause, reader: _Reader) -> str | None:
    return next((what for c in _clauses(row, reader, True) if (what := _do(c, reader))), None)


def _schedule_row(row: Clause, reader: _Reader) -> str | None:
    for at, word in enumerate(row):
        found = reader.verb(word)
        if found is None or found[1] == "ed" or word.proper:
            continue
        if at and row[at - 1].low in DETERMINERS | (PREPS - {"to"}):
            continue
        return _do_row(row[at:], reader)
    return None


OWN_REQUESTS: Final = {"merge": "gitlab", "pull": "github"}
"""Whose a request is when no system is named: merge requests are GitLab's, pull requests
GitHub's."""


def _own_requests(clause: Clause) -> str | None:
    """The system whose requests a clause names without naming the system, as in "merge
    requests merged without approval"."""
    if any(w.system is not None for w in clause):
        return None
    for word, after in zip(clause, clause[1:], strict=False):
        if word.low in OWN_REQUESTS and after.low in ("request", "requests"):
            return OWN_REQUESTS[word.low]
    return None


def _its_own_tickets(clause: Clause, reaches: frozenset[str]) -> str | None:
    for word, after in zip(clause, clause[1:], strict=False):
        system = word.system
        names_its_own = after.low in TICKETS or after.low in ("merge", "pull")
        if system in TICKET_SYSTEMS and system not in reaches and names_its_own:
            return SYSTEMS[system]
    own = _own_requests(clause)
    return SYSTEMS[own] if own is not None and own not in reaches else None


def _read_from(clause: Clause, reaches: frozenset[str]) -> str | None:
    for at, word in enumerate(clause):
        if word.low not in SOURCES:
            continue
        phrase: list[_Word] = []
        for later in clause[at + 1 :]:
            if later.mark or later.low in PREPS | ENDS:
                break
            phrase.append(later)
        if _names_jira(tuple(phrase)):
            continue
        for named in phrase:
            if named.system is not None and named.system not in reaches:
                return SYSTEMS[named.system]
            if named.product:
                return named.raw
    return None


def _look_for_row(row: Clause, reader: _Reader) -> str | None:
    clauses = _clauses(row, reader, False)
    if not clauses:
        return None
    first, *later = clauses
    own = _own_requests(first)
    if own is not None and own not in REACHED:
        return f"read {SYSTEMS[own]}"
    at = _action_at(first)
    if at is not None:
        found = reader.verb(first[at])
        if found is not None and found[1] != "ed" and found[0] in reader.writes:
            return _cant_phrase(first[at:], reader)
    reads = _reading(reader, row)
    reaches = frozenset(place for ability in reads for place in ability.reaches)
    source = _its_own_tickets(first, reaches) or _read_from(first, reaches)
    if source is not None:
        return f"read {source}"
    tickets = JIRA in reaches and any(w.low in TICKETS for w in first)
    if not tickets and not _names_jira(first) and not any(a.about for a in reads):
        named = next((w.system for w in first if w.system and w.system not in reaches), None)
        return f"read {SYSTEMS[named]}" if named else f"look for {_cant_phrase(first, reader)}"
    return next((what for c in later if (what := _do(c, reader))), None)


def _says_an_action(word: _Word, reader: _Reader) -> bool:
    found = reader.verb(word)
    named = found is not None and found[1] != "s" and not word.proper
    return named or word.bare in CAUSATIVES | PLACING_FORMS


def _a_ticket_already_there(place: Clause) -> bool:
    """Whether a place names a ticket that is already there, such as MOCK-12 or "the ticket",
    not a project or a new ticket."""
    return any(
        (word.key and "-" in word.raw)
        or (word.low in TICKETS and not (before and before.low in NEW))
        for before, word in zip((None, *place), place, strict=False)
    )


def _places_it(word: _Word, reader: _Reader, place: Clause) -> bool:
    found = reader.verb(word)
    if found is None or found[1] != "ed":
        return word.bare in PLACING_FORMS
    if _a_ticket_already_there(place):
        return False
    return found[0] not in reader.writes or found[0] in DELIVERS


def _lead_in(part: Clause, reader: _Reader) -> Clause:
    """The part without the words before what it names: "then", "let's", "I want it", and a
    placing verb or a past form just before a place, as in "it goes to Slack", "posted in Teams"
    or "summarised in MOCK". The past form of a write that only delivers (post, send, share,
    save, publish) is a lead. One that changes data, as in "moved to" or "attached to", stays,
    and so does any past form before a ticket that is already there, as in "posted to
    MOCK-12"."""
    at = 0
    while at < len(part) and (part[at].mark or part[at].low in (FILLER - TO_PLACE) | {"let's"}):
        at += 1
    if at < len(part) and part[at].low in SUBJECTS:
        at += 1
        wants = at
        while at < len(part) and part[at].low in WANTING:
            at += 1
        while wants < at < len(part) and part[at].low in PRONOUNS:
            at += 1
    verb = at
    while verb < len(part) and part[verb].low in PRONOUNS:
        verb += 1
    after = verb + 1
    while after < len(part) and part[after].low in PRONOUNS:
        after += 1
    to_place = after < len(part) and part[after].low in TO_PLACE | IN_PLACE
    if to_place and _places_it(part[verb], reader, part[after + 1 :]):
        at = after
    return part[at:]


def _not_a_place(part: Clause, reader: _Reader, places: frozenset[str]) -> str | None:
    """What the note says for one part of where it goes that is not a place the platform
    reaches: the action itself when the part says one, so the sentence never reads "put results
    in let the team know". None when the part names nothing, such as "then", "in the" or "it
    goes", or when its lead words come before a place it reaches, as in "Posted in Jira project
    MOCK"."""
    lead = _lead_in(part, reader)
    if all(word.mark or word.low in NAMES_NOTHING for word in lead) or _is_place(lead, places):
        return None
    first, rest = lead[0], lead[1:]
    if first.low in TO_PLACE | IN_PLACE:
        verb = "send results to" if first.low == "to" else "put results in"
        return f"{verb} {_cant_phrase(rest, reader)}"
    if _says_an_action(first, reader):
        return _cant_phrase(lead, reader)
    if first.low in PLACE_ADVERBS:
        return f"put results {_cant_phrase(lead, reader)}"
    return f"put results in {_cant_phrase(lead, reader)}"


A_YES_WORDS: Final = words("yes approval approvals approver approvers approve approves approved")
AFTER: Final = words("after once when")


def _place_only(part: Clause) -> Clause:
    """A part of where it goes without what only describes the ticket or the platform's own
    step: a relative clause, as in "one new Jira ticket that lists them", and an "after an
    Approver says yes" clause, which every write goes through anyway."""
    if part and part[0].low in AFTER and any(w.low in A_YES_WORDS for w in part):
        return ()
    end = next((i for i, w in enumerate(part) if i and w.low in RELATIVES), len(part))
    return part[:end]


def _where_row(row: Clause, reader: _Reader) -> str | None:
    at = _action_at(row)
    if at is None:
        return None
    verb_at: int | None = None
    found = reader.verb(row[at])
    if found is not None and found[1] != "ed":
        able = {verb for ability in reader.abilities for verb in ability.verbs}
        if found[0] not in able | PLACING:
            return _cant_phrase(row[at:], reader)
        verb_at = at
        at += 1
        while at < len(row) and row[at].low in PRONOUNS:
            at += 1
    elif at and row[at - 1].low in TO_PLACE:
        at -= 1
    places = frozenset(
        place
        for ability in reader.abilities
        if ability.makes is not None
        for place in ability.reaches
    )
    parts: list[list[_Word]] = [[]]
    for word in row[at:]:
        if word.low in ("and", "or", "plus", "&", ",", ";"):
            parts.append([])
        else:
            parts[-1].append(word)
    for number, words_of_part in enumerate(parts):
        part = _place_only(tuple(words_of_part))
        if not part or _is_place(part, places):
            continue
        if number == 0 and verb_at is not None and part[0].low not in TO_PLACE | IN_PLACE:
            what = _do_row(row[verb_at : at + len(part)], reader)
        else:
            what = _not_a_place(part, reader, places)
        if what is not None:
            return what
    return None


def _is_ticket_search(clause: Clause) -> bool:
    return any(w.low in TICKETS or w.system == JIRA for w in clause)


def _vulnerability_phrase(clause: Clause) -> str | None:
    for word, after in zip(clause, (*clause[1:], None), strict=False):
        if word.low in VULNERABILITIES or CVE_ID.fullmatch(word.low):
            return word.raw
        if word.low == "security" and after is not None and after.low in SECURITY_PHRASE_ENDS:
            return f"{word.raw} {after.raw}"
    return None


def vulnerability_phrase(text: str) -> str | None:
    reader = _reader(ABILITIES)
    for clause in _clauses(_tokens(text), reader, True):
        if _is_ticket_search(clause):
            continue
        phrase = _vulnerability_phrase(clause)
        if phrase is not None:
            return phrase
    return None


def _asks_for_vulnerabilities(row: Clause, reader: _Reader) -> bool:
    return any(
        _vulnerability_phrase(clause) is not None and not _is_ticket_search(clause)
        for clause in _clauses(row, reader, True)
    )


def _cant_act(kind: RowKind, row: Clause, reader: _Reader) -> str | None:
    """The action in this part that no ability fits, or None when every action fits."""
    match kind:
        case "schedule":
            return _schedule_row(row, reader)
        case "look_for":
            return _look_for_row(row, reader)
        case "do":
            return _do_row(row, reader)
        case "where":
            return _where_row(row, reader)


DELETES: Final = words("delete purge erase wipe destroy trash")
UNSUPPORTED_WORDS: Final = {
    "slack.send": (words("slack sms text texts"), False),
    "jira.delete": (DELETES, True),
    "jira.change_tickets": (
        words(
            "close resolve cancel reopen remove edit move transition rename assign reassign "
            "update change modify"
        ),
        True,
    ),
}
"""For each Unsupported entry of the registry, the words that name it and whether only the
part's first word counts (an action word, as "close"). A part named by them is something the
platform won't do, so the refusal does not say "yet"."""


def _is_unsupported(what: str) -> bool:
    row = _tokens(what)
    for id, (named, first_only) in UNSUPPORTED_WORDS.items():
        if next(c for c in CAPABILITIES if c.id == id).state != "unsupported":
            continue
        if any(
            w.low.removesuffix("'s").removesuffix("’s") in named
            for w in (row[:1] if first_only else row)
        ):
            return True
    return False


PAST_THE_NEWEST: Final = re.compile(
    r"\b(?:beyond|past)\s+(?:the\s+)?(?:newest|latest|first|last|most recent)\b"
    r"|\b(?:older|earlier|previous)\s+tickets\b",
    re.IGNORECASE,
)


def _past_the_newest(text: str) -> str | None:
    """The registry's words for a search that reaches past the newest 50 tickets, which a search
    can't, when the part asks for it ("older than 10 days" is a filter and is not this)."""
    if PAST_THE_NEWEST.search(text) is None:
        return None
    return next(c.cant for c in CAPABILITIES if c.id == "jira.find_older")


SAID_FOR: Final = {
    "Teams": ("teams.post", "post in Teams channels"),
    "email": ("teams.post", "send email"),
    "Confluence": ("confluence.change", None),
}
"""The registry entry whose one-line can't stands for a part that sends to or changes the system
it names, by that system's plain name, with the words for that system when the entry covers two."""


def cant_entry(text: str, system: str | None) -> CapabilitySpec | None:
    """The registry entry with words of its own that a can't part asks for: a post or a send to
    Teams or email, a change in Confluence, or a delete of Jira tickets. A part that names only
    the place, as "Teams", sends there. None for anything else, as reading Teams or deleting a
    branch, which keeps its own words."""
    row = _tokens(text)
    at = _action_at(row)
    found = _reader(ABILITIES).verb(row[at]) if at is not None else None
    verb = None if found is None else found[0]
    tickets = system == SYSTEMS[JIRA] or any(w.low in TICKETS for w in row)
    if verb in DELETES and tickets:
        return next(c for c in CAPABILITIES if c.id == "jira.delete")
    named = SAID_FOR.get(system or "")
    if named is None or (verb is not None and verb not in WRITES):
        return None
    named_id, cant = named
    entry = next(c for c in CAPABILITIES if c.id == named_id)
    return entry if cant is None else entry.model_copy(update={"cant": cant})


def one_line_cant(entry: CapabilitySpec) -> str:
    """The entry's can't as one sentence: what the platform won't do, or can't do yet."""
    if entry.state == "unsupported":
        return f"I don't {entry.cant}."
    return f"I can't {entry.cant} yet."


def _cant_sentence(what: str, reader: _Reader) -> str:
    yet = "" if _is_unsupported(what) else " yet"
    return f"I can't {what}{yet}. {reader.can()}"


def why_not(kind: RowKind, text: str, abilities: tuple[Ability, ...] = ABILITIES) -> str | None:
    """Why the platform can't do this part, in plain words, or None when every action in it fits
    one of the abilities and no field it reads is one the agents can't see."""
    reader = _reader(abilities)
    row = _tokens(text)
    if _asks_for_vulnerabilities(row, reader):
        return VULNERABILITIES_PLANNED
    what = _cant_act(kind, row, reader) or (
        _past_the_newest(text) if kind in ("look_for", "do") else None
    )
    if what is not None:
        return _cant_sentence(what, reader)
    field = unread_field_in(text) if kind in ("look_for", "do") else None
    return None if field is None else why_not_the_field(kind, text, field)


def why_not_the_field(kind: RowKind, text: str, field: TicketField) -> str:
    """Why the platform can't do a part that reads or sets `field`, in the words `why_not` uses:
    a field put on the new ticket is one it can't set, one read from the found tickets one it
    can't tell. A field read only in some values, as status, names them."""
    reader = _reader(ABILITIES)
    row = _tokens(text)
    verb = "set" if kind == "do" and _sets_on_a_new_ticket(row, reader) else "tell"
    beyond = f" beyond {' or '.join(sorted(field.values))}" if field.values else ""
    return f"I can't {verb} {field.plain}{beyond} yet. {reader.can()}"


def _sets_on_a_new_ticket(row: Clause, reader: _Reader) -> bool:
    """Whether a part puts the field on the ticket it creates, as in "Create one ticket with
    component Backend", rather than reading it from the tickets found, as in "Create one ticket
    that lists them and their components"."""
    at = _action_at(row)
    found = reader.verb(row[at]) if at is not None else None
    if found is None or found[0] not in ABILITIES[-1].verbs:
        return False
    for i in range(2, len(row)):
        if _field_at(row, i) and row[i - 1].low == "with" and row[i - 2].low in TICKETS:
            return True
        if _field_at(row, i) and row[i - 2].low == "with" and row[i - 3].low in TICKETS:
            return True
    return False


REACHED: Final = frozenset(place for ability in ABILITIES for place in ability.reaches)
NOTIFIES: Final = words(
    "post send share forward publish message text email mail notify remind ping nudge chase "
    "tell ask alert warn inform contact invite dm broadcast announce upload export print call"
)
NOT_SOFTWARE: Final = words(
    "software package packages dependency dependencies library libraries tool tools app apps "
    "system systems service services component components version versions release releases "
    "code"
)
"""Common words the model has named as software. A stopgap until the find route (N20) checks
every name against a real project."""


type TicketFieldName = Literal[
    "assignee",
    "issue_type",
    "status",
    "created",
    "updated",
    "done",
    "component",
    "priority",
    "label",
    "epic",
    "sprint",
    "due_date",
    "reporter",
    "fix_version",
    "story_points",
    "severity",
    "other",
]
"""The closed set of ticket fields the model names on a row it read. The model reads which
field a request filters by, in whatever words; this table decides whether the agents can read
it. N6's registry entry `jira.find_by_detail` should derive from the same table."""


@dataclass(frozen=True)
class TicketField:
    """A field of a Jira ticket that a request can name. `read_as` is the `JiraTicket` attribute
    the agents see, or None while no tool gives it. `values` are the values the search can
    filter by when it reads only a closed set of them, as status; empty when it reads any
    value. `words` are the first net, consulted with no model and only for a field the agents
    can't read; for the others they record how a request names it. A value the request gives
    instead of the field's name, such as P1 for priority, is in the words too when it can mean
    nothing else."""

    name: TicketFieldName
    plain: str
    words: frozenset[str]
    read_as: str | None = None
    values: frozenset[str] = frozenset()


TICKET_FIELDS: Final = (
    TicketField(
        "assignee", "who owns a ticket", words("assignee assignees owner owners"), "assignee"
    ),
    TicketField("issue_type", "a ticket's type", words("type types"), "issue_type"),
    TicketField(
        "status",
        "a ticket's status",
        words("status statuses"),
        "status",
        frozenset({"open", "done"}),
    ),
    TicketField("created", "when a ticket was created", words("created"), "created_at"),
    TicketField("updated", "when a ticket was last updated", words("updated update"), "updated_at"),
    TicketField("done", "when a ticket was done", words("done closed"), "done_at"),
    TicketField("component", "a ticket's component", words("component components")),
    TicketField(
        "priority",
        "a ticket's priority",
        words("priority priorities p1 p2 p3 p4 p5 critical blocker blockers urgent"),
    ),
    TicketField("label", "a ticket's labels", words("label labels labelled labeled tagged")),
    TicketField("epic", "a ticket's epic", words("epic epics")),
    TicketField("sprint", "a ticket's sprint", words("sprint sprints")),
    TicketField("due_date", "a ticket's due date", words("due overdue deadline deadlines")),
    TicketField("reporter", "a ticket's reporter", words("reporter reporters reported")),
    TicketField("fix_version", "a ticket's fix version", frozenset()),
    TicketField("story_points", "a ticket's story points", words("points")),
    TicketField("severity", "a ticket's severity", words("severity severities")),
    TicketField("other", "that detail of a ticket", frozenset()),
)
FIELD_BY_NAME: Final[dict[TicketFieldName, TicketField]] = {f.name: f for f in TICKET_FIELDS}
UNREAD_FIELDS: Final = tuple(field for field in TICKET_FIELDS if field.read_as is None)
HELD_FIELD_PLAIN: Final = tuple(
    field.plain for field in TICKET_FIELDS if field.read_as is None or field.values
)
"""The plain names a hold's own note can use: the fields the agents can't read, and the ones
they read only some values of."""


SETTABLE_TOO: Final = words("assignee assignees field fields")
"""Fields a new tool could set, besides the ones the agents can't read."""
EPIC_LEADS: Final = words("in under of by per with within for their its")
"""The words that make "epic" a field of the tickets looked for, as in "in the epic", rather
than the tickets themselves, as in "list epics"."""
TOPIC_LEADS: Final = words(
    "about mentioning mention mentions mentioned titled called named regarding word words"
)
"""A field word after these is what tickets are about, as in "about the login component" or
"the word urgent in the title"."""
PHRASE_ENDS: Final = PREPS | words("and or plus")
RELATIVES: Final = words("that which who whose where")
COPULAS: Final = words("is are was were be been being has have had")
VALUE_NOUNS: Final = TICKETS | PRONOUNS | words("ones items requests request changes change")


def _led(row: Clause, at: int, leads: frozenset[str], through: int = 3) -> bool:
    """Whether one of `leads` comes before `at`, with only determiners and names between."""
    for back in range(at - 1, max(at - through, 0) - 1, -1):
        word = row[back]
        if word.low in leads:
            return True
        if word.low not in DETERMINERS and not word.capital:
            return False
    return False


def _a_topic(row: Clause, at: int) -> bool:
    """Whether the field word at `at` is what tickets are about, as in "about the login
    component", rather than a filter on them: a topic lead comes before it in its phrase."""
    for back in range(at - 1, max(at - 5, 0) - 1, -1):
        word = row[back]
        if word.low in TOPIC_LEADS:
            return True
        if word.mark or word.low in PHRASE_ENDS:
            return False
    return False


def _field_at(row: Clause, at: int) -> TicketField | None:
    word = row[at]
    parts = word.low.split("-")
    field = next((f for f in UNREAD_FIELDS if any(part in f.words for part in parts)), None)
    if field is None or _a_topic(row, at):
        return None
    if "epic" not in field.words:
        return field
    after = row[at + 1] if at + 1 < len(row) else None
    return field if _led(row, at, EPIC_LEADS) or (after is not None and after.key) else None


def unread_field_in(text: str) -> TicketField | None:
    """The first field named in the text that no tool gives the agents, or None."""
    row = _tokens(text)
    return next((f for at in range(len(row)) if (f := _field_at(row, at)) is not None), None)


def names_a_ticket_field(text: str) -> bool:
    """Whether the text names a field of a ticket, read or set, that a new Jira tool could give:
    by one of its words, or by the plain name the hold's own note uses."""
    row = _tokens(text)
    low = text.casefold()
    if "fix version" in low:
        return True
    return any(plain in low for plain in HELD_FIELD_PLAIN) or any(
        _field_at(row, at) is not None or row[at].low in SETTABLE_TOO for at in range(len(row))
    )


def _phrase_pattern(phrase: str) -> str | None:
    """A pattern for the phrase's words in order, whatever the case, spaces or marks between
    them, or None when it has no words."""
    found = re.findall(r"\w+", phrase)
    return r"\W+".join(re.escape(word) for word in found) if found else None


def phrase_in(text: str, phrase: str) -> str | None:
    """The phrase as the text writes it, or None when the text lacks it."""
    pattern = _phrase_pattern(phrase)
    if pattern is None:
        return None
    found = re.search(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE)
    return None if found is None else found.group(0)


def _without(text: str, phrase: str) -> str | None:
    """The text with the phrase cut, or None when the text lacks it."""
    pattern = _phrase_pattern(phrase)
    if pattern is None:
        return None
    found = re.search(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE)
    if found is None:
        return None
    return f"{text[: found.start()]} {text[found.end() :]}"


WRITE_VERBS: Final = WRITES | ABILITIES[-1].verbs
"""The verbs that ask for a change: a write, or the creation of a ticket."""
OPENS_A_TICKET_BEFORE: Final = words("a an one single new another the")
""""open" asks for a change only before a ticket to open, as "open one ticket"; "open bugs" is
the state of the tickets looked for."""


def change_verbs_in(text: str) -> list[str]:
    """The verbs in the text that ask for a change, in base, -s or -ing form. A past form
    describes tickets ("tickets closed"), and "open" is also the state of a ticket, so neither
    counts."""
    reader = _reader(ABILITIES)
    row = _tokens(text)
    found: list[str] = []
    for at, word in enumerate(row):
        verb = reader.verb(word)
        if verb is None or word.proper or verb[1] == "ed":
            continue
        after = row[at + 1].low if at + 1 < len(row) else ""
        if verb[0] == "open" and after not in OPENS_A_TICKET_BEFORE:
            continue
        if verb[0] in WRITE_VERBS:
            found.append(verb[0])
    return found


def starts_with_a_verb(text: str) -> bool:
    """Whether the first content word is a verb in its base form, as "flag the new ticket"."""
    reader = _reader(ABILITIES)
    row = _tokens(text)
    at = _action_at(row)
    if at is None:
        return False
    verb = reader.verb(row[at])
    return verb is not None and verb[1] == "base" and not row[at].proper


def commands_a_change(text: str) -> bool:
    """Whether a clause of the text starts with a verb that asks for a change to tickets, as
    "Create the ticket" or "please file one", and not "don't close it" or "tell me"."""
    reader = _reader(ABILITIES)
    row = _tokens(text)
    for at, word in enumerate(row):
        if not (word.starts or (at and row[at - 1].low in FILLER | DETERMINERS)):
            continue
        before = row[at - 1].low if at else ""
        if before in ("don't", "do", "never", "not", "no", "without"):
            continue
        verb = reader.verb(word)
        after = row[at + 1].low if at + 1 < len(row) else ""
        if verb is None or word.proper or verb[1] != "base":
            continue
        if verb[0] == "open" and after not in OPENS_A_TICKET_BEFORE:
            continue
        if verb[0] in WRITE_VERBS - NOTIFIES and (word.starts or not reader.acts(row[at - 1])):
            return True
    return False


_A_YES: Final = (
    r"(?:approvals?|approvers?|approving|yes|sign[- ]?off|permission|confirmation|ok|okay|"
    r"go-ahead|green\s+light)"
)
_PEOPLE: Final = (
    r"(?:anyone|anybody|someone|somebody|a\s+human|a\s+person|people|(?:an?|the)\s+approvers?|"
    r"(?:a|my|the)\s+managers?|the\s+boss|(?-i:[A-Z][a-z]+))"
)
_SOMEONE_ELSE: Final = rf"(?:{_PEOPLE}|the\s+team)"
_THEIR_YES: Final = rf"(?:'s\s+{_A_YES})?"
_NOT_ME: Final = r"(?!\s+(?:me|us|myself|ourselves|my)\b)"
_NOT_FROM_ME: Final = r"(?!\s+(?:from|of)\s+(?:me|us)\b)"
_SAYS_YES: Final = r"(?:sign[- ]?off|approve|say\s+yes|ok|okay|check|confirm|agree)"
_NOT_NEEDED: Final = r"(?:needed|required|necessary)"
_IT: Final = r"(?:it|them|this|that|everything|each|every|all|(?:the|my|our|a|an)\s+(?:own\s+)?\w+)"
SKIPS_A_YES: Final = re.compile(
    rf"""
    (?P<command>
        \bwithout\s+{_SOMEONE_ELSE}\s+(?:approving|signing\s+off|checking|saying\s+yes)\b
      | \bno\s+need\s+(?:for\s+{_SOMEONE_ELSE}\s+to\s+{_SAYS_YES}
            |for\s+(?:an?\s+|any\s+)?{_A_YES}
            |to\s+(?:get|ask\s+for|wait\s+for|have)\s+(?:an?\s+|any\s+)?{_A_YES}
            |to\s+(?:wait\s+for|ask|check\s+with|bother)\s+{_SOMEONE_ELSE})\b
      | \b(?:nobody|no\s+one)\s+(?:needs?|has)\s+to\s+{_SAYS_YES}\b
      | \bno\s+need\s+to\s+ask\b{_NOT_ME}
      | \bno\s+(?:[\w']+\s+)?{_A_YES}(?:\s+from\s+[\w']+)?\s+(?:{_NOT_NEEDED}|first|at\s+all)\b
      | (?:^|[,;:(\-]\s*)no\s+{_A_YES}\s*(?:[,;.!)]|$)
      | \bno\s+questions\s+asked\b
      | \bfast-?track(?:s|ed|ing)?\b
      | \b(?:push|rush|wave|force)\s+{_IT}\s+(?:straight\s+)?through\b
      | \bno\s+human\s+in\s+the\s+loop\b
      | \bon\s+my\s+(?:authority|say-so)\b
      | \b{_A_YES}\s+can\s+wait\b
      | \b(?:with\s+)?approvals?\s+(?:off|turned\s+off|switched\s+off|disabled)\b
      | \b(?:(?:treat|consider|take)\s+{_IT}\s+(?:as\s+)?)?pre-?approv(?:e|es|ed|ing|al)\b
      | \b(?:treat|consider|take)\s+{_IT}\s+as\s+approved\b
      | \b(?:i|we)(?:'ve|\s+have)?\s+already\s+approved(?:\s+{_IT})?\b
      | \bsign\s+{_IT}\s+off\s+(?:yourself|yourselves|itself)\b
      | \bskip(?:s|ped|ping)?\s+(?:asking\s+(?:for\s+)?)?
            (?:the\s+|an?\s+|any\s+|all\s+|my\s+)?(?:{_A_YES}|teams)\b
      | \bbypass(?:es|ed|ing)?\s+(?:the\s+|an?\s+)?(?:{_A_YES}|gate|check|teams|{_SOMEONE_ELSE})\b
      | \b(?:don'?t|do\s+not|never)\s+(?:ask(?:ing)?|wait(?:ing)?|bother(?:ing)?)\s+
            (?:getting\s+|to\s+get\s+|with\s+)?(?:for\s+)?
            (?:an?\s+|any\s+|the\s+)?(?:{_A_YES}|{_PEOPLE}){_THEIR_YES}\b
      | \b(?:don'?t|do\s+not|never)\s+(?:route|send|submit|put|pass)\s+{_IT}\s+
            (?:for|to|through|by|past)\s+(?:an?\s+|the\s+|any\s+)?(?:{_A_YES}|{_SOMEONE_ELSE})\b
      | \bwithout\s+(?:sending|routing|submitting|passing|putting)\s+{_IT}\s+
            (?:for|to|through|by|past)\s+(?:an?\s+|the\s+|any\s+)?(?:{_A_YES}|{_SOMEONE_ELSE})\b
      | \b(?:auto|self)-?approv(?:e|es|ing|al|als)\b
      | \bapprov(?:e|es|ing)\s+(?:{_IT}\s+)?(?:(?:of\s+)?\w+\s+)?
            (?:automatically|by\s+itself|itself|on\s+its\s+own|myself|ourselves|yourself|
            yourselves|for\s+me|for\s+us|as\s+me|as\s+us|on\s+(?:my|our)\s+behalf)\b
      | \bautomatic\s+approv\w*
      | \bautomatically\s+approv(?:e|es|ing)\b
      | \bapprov\w*\s+(?:my\s+own|our\s+own)\b
      | \bmark(?:s|ed|ing)?\s+{_IT}\s+(?:as\s+)?approved\b
      | \b(?:tick|check|mark)(?:s|ed|ing)?\s+(?:the\s+|my\s+|an?\s+)?{_A_YES}\s+box\b
      | \b(?:i'?ll|i\s+will|i\s+can|i\s+shall|i'?d|let\s+me|i)\s+approve
            (?:\s+{_IT})?(?:\s+(?:myself|ourselves))?\b
      | \bi(?:'ll|\s+will|\s+can|\s+could|\s+should)?\s+(?:be|am)\s+the\s+approver\b
    )
  | (?P<filter>
        \bwithout\s+asking\b{_NOT_ME}(?!\s+for\s+[\w\s]*?\bfrom\s+(?:me|us)\b)
      | \bwithout\s+(?:asking|waiting(?:\s+for)?|checking\s+with|telling|consulting|bothering|
            running\s+it\s+(?:by|past)|clearing\s+it\s+with)\s+
            (?:for\s+)?(?:an?\s+|any\s+|the\s+|my\s+)?(?:{_A_YES}|{_SOMEONE_ELSE}){_THEIR_YES}\b
            {_NOT_FROM_ME}
      | \bwithout\s+(?:[\w']+\s+){{0,2}}?{_A_YES}\b{_NOT_FROM_ME}
      | \bwith\s+no\s+(?:[\w']+\s+)?{_A_YES}\b
      | \b{_A_YES}\s+(?:isn'?t|aren'?t|is\s+not|are\s+not|not)\s+{_NOT_NEEDED}\b
      | \bwithout\s+(?:an?\s+)?(?:review|reviews)\b
      | \bwithout\s+(?:going\s+through\s+|using\s+)?teams\b
      | \bauto-?approved\b
      | \bapproved\s+(?:automatically|by\s+itself|on\s+its\s+own)\b
      | \bautomatically\s+approved\b
      | \bapprov\w*\s+(?:its\s+own|their\s+own)\b
      | \b{_A_YES}\s+(?:afterwards|afterward|later|after\s+that|after\s+the\s+fact)\b
    )
""",
    re.IGNORECASE | re.VERBOSE,
)
"""The first net, kept so a refusal works with no model and before any model call. A command
skips a yes wherever it stands. A filter-shaped phrase, such as "without an approver",
"approval is not needed" or "auto-approved", can also describe the tickets looked for, so it
skips a yes only when the clause before it writes or approves rather than reads. "skip" and
"bypass" are commands, except right after "that" or "which", as in "tickets that bypass the
gate". The model's own answer to the same question, `TaskRead.skips_the_yes`, is the second
net, because no list of phrases is complete."""
_CONNECTOR: Final = r"(?:and|but|then|so|just|please)"
READS_TOO: Final = words("show tell")
READ_VERBS: Final = (
    frozenset(verb for ability in ABILITIES if ability.makes is None for verb in ability.verbs)
    - CAUSATIVES
)
NOUNS_TOO: Final = TICKETS | OUTPUTS | words("request requests change changes grant grants")


class Need(NamedTuple):
    needs: Literal["new_tool", "new_system"]
    system: str | None


def _reads_before(text: str, at: int) -> bool:
    """Whether the clause before `at` reads tickets, so a filter-shaped phrase there describes
    the tickets looked for: its last verb reads, or it has no verb and names tickets. A past
    form describes tickets ("tickets closed"), an -s form after a noun is a noun ("access
    changes"), and "get" and the other causatives are not reads ("get it approved")."""
    clause = _tokens(text[:at])
    first = next((i for i in range(len(clause) - 1, -1, -1) if clause[i].starts), 0)
    clause = clause[first:]
    if clause and clause[-1].low in RELATIVES and clause[-1].low != "whose":
        return True
    reader = _reader(ABILITIES)
    for back in range(len(clause) - 1, -1, -1):
        word = clause[back]
        if word.low in READS_TOO:
            return True
        found = reader.verb(word)
        if found is None or word.proper or found[1] == "ed":
            continue
        before = clause[back - 1] if back else None
        after = clause[back + 1] if back + 1 < len(clause) else None
        if found[1] == "s" and before is not None and before.low not in RELATIVES | PRONOUNS:
            continue
        if after is not None and word.low in OWN_REQUESTS and after.low in ("request", "requests"):
            continue
        return found[0] in READ_VERBS
    return any(w.low in NOUNS_TOO for w in clause)


_AFTER_A_RELATIVE: Final = re.compile(r"\b(?:that|which|who)\s+$", re.IGNORECASE)


def _skips(text: str) -> list[re.Match[str]]:
    skips: list[re.Match[str]] = []
    for found in SKIPS_A_YES.finditer(text):
        if found.group("command") is None:
            if not _reads_before(text, found.start()):
                skips.append(found)
        elif not (
            found.group(0).lower().startswith(("skip", "bypass"))
            and _AFTER_A_RELATIVE.search(text[: found.start()])
        ):
            skips.append(found)
    return skips


def skip_of_a_yes(text: str) -> str | None:
    found = _skips(text)
    return found[0].group(0) if found else None


def _tidied(rest: str) -> str:
    rest = re.sub(r"\s+([,;:.!?])", r"\1", " ".join(rest.split()))
    rest = re.sub(r"\s*,(?:\s*,)+", ",", rest).strip(" ,;.")
    rest = re.sub(r"([;:.!?])\s*,", r"\1", rest)
    rest = re.sub(rf"^{_CONNECTOR}\b[\s,]*", "", rest, flags=re.IGNORECASE)
    rest = re.sub(rf"[\s,]*\b{_CONNECTOR}$", "", rest, flags=re.IGNORECASE)
    return rest.strip(" ,;.")


def without_the_skip(text: str) -> str:
    rest = text
    for found in reversed(_skips(text)):
        rest = f"{rest[: found.start()]} {rest[found.end() :]}"
    return _tidied(rest)


def without_the_phrase(text: str, phrase: str) -> str | None:
    """The text with the person's phrase cut out and the edges tidied, as `without_the_skip`
    does, or None when the text lacks the phrase."""
    cut = _without(text, phrase)
    return None if cut is None else _tidied(cut)


def need_of(kind: RowKind, text: str, unreached_source: str | None = None) -> Need:
    reader = _reader(ABILITIES)
    row = _tokens(text)
    named = [w.system for w in row if w.system is not None]
    own = _own_requests(row)
    if own is not None:
        named.append(own)
    other = next((s for s in named if s not in REACHED), None)
    if other is not None:
        return Need("new_system", SYSTEMS[other])
    if _asks_for_vulnerabilities(row, reader) or any(w.low in PLACES or w.product for w in row):
        return Need("new_system", None)
    reached = next((s for s in named if s in REACHED), None)
    if reached is not None:
        return Need("new_tool", SYSTEMS[reached])
    if any(w.low in TICKETS or w.low in JIRA_ANCHORS for w in row) or names_a_ticket_field(text):
        return Need("new_tool", SYSTEMS[JIRA])
    if kind in ("look_for", "where"):
        return Need("new_system", None)
    if unreached_source is not None:
        return Need("new_system", unreached_source)
    at = _action_at(row)
    verb = reader.verb(row[at]) if at is not None else None
    if verb is not None and verb[0] in NOTIFIES:
        return Need("new_system", None)
    return Need("new_tool", SYSTEMS[JIRA])


NOT_SOFTWARE_SYSTEMS: Final = REACHED | words("teams email e-mail mail sms")
"""Systems the platform reaches or sends to, never the software a watch is about. Other systems
in `SYSTEMS`, such as GitLab or Jenkins, are also software with releases."""


def software_name(said: str | None) -> str | None:
    """The software in a name the model gave, with common words such as "releases" or "the"
    trimmed from its ends, or None when what is left is a common word, a vulnerability word, a
    CVE, or a system the platform itself uses."""
    row = list(_tokens(said or ""))
    while row and (row[0].low in NOT_SOFTWARE | DETERMINERS or row[0].mark):
        row.pop(0)
    while row and (row[-1].low in NOT_SOFTWARE or row[-1].mark):
        row.pop()
    name = " ".join(w.raw for w in row)
    if not row or vulnerability_phrase(name) is not None:
        return None
    if any(
        w.low in NOT_SOFTWARE | VULNERABILITIES
        or w.system in NOT_SOFTWARE_SYSTEMS
        or CVE_ID.fullmatch(w.low) is not None
        for w in row
    ):
        return None
    return name


def release_word_in(text: str) -> str | None:
    return next((w for w in re.findall(r"\w+", text) if w.casefold() in RELEASE_ROOTS), None)


RELEASE_SOURCES: Final = {
    "maven central": "Maven Central",
    "maven": "Maven",
    "npm": "npm",
    "pypi": "PyPI",
    "docker hub": "Docker Hub",
    "dockerhub": "Docker Hub",
    "nuget": "NuGet",
    "rubygems": "RubyGems",
    "crates.io": "crates.io",
    "helm": "Helm",
}
"""Places a person may name for a software's releases. The platform reads GitHub only."""

_PREPOSITION: Final = r"(?:from|on|in|via|at|using|through|of)"
_ALSO_A_NAME: Final = frozenset({"maven", "helm"})
"""Sources that are also the names of software, so a "watch Helm" is not a source."""
_RELEASE_SOURCE: Final = re.compile(
    rf"(?<![\w.\-])(?:({_PREPOSITION})\s+)?("
    + "|".join(re.escape(k) for k in RELEASE_SOURCES)
    + r")(?![\w\-])",
    re.IGNORECASE,
)


def other_release_source(text: str) -> str | None:
    """The first release source in the text other than GitHub, as the person wrote it. A source
    that is also a software name counts only after "from", "on" and the like."""
    for found in _RELEASE_SOURCE.finditer(text):
        if found.group(1) is not None or found.group(2).casefold() not in _ALSO_A_NAME:
            return found.group(2)
    return None


def release_source_note(source: str) -> str:
    name = RELEASE_SOURCES.get(source.casefold(), source)
    return f"I only read releases on GitHub. {name} isn't a source I read yet."


def other_systems(text: str) -> list[str]:
    found = [w.system for w in _tokens(text) if w.system is not None and w.system not in REACHED]
    return list(dict.fromkeys(SYSTEMS[name] for name in found))
