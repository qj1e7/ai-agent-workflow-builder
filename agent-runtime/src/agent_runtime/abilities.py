"""What the platform can do, and the rule that holds what the Planner read back to it.

`ABILITIES` is the whole list, one line for each thing the platform can do. A part the Planner
read back stays as the model said only when every action in it fits a line: its verb is one of the
line's verbs, the thing it makes is one the line makes, and every place it names is one the line
reaches. Anything else is can't do, with a note that says what the platform can't do yet. A new
tool is one more line."""

import re
from dataclasses import dataclass
from functools import cache
from typing import Final, Literal

from agent_runtime.contract import RowKind

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
RELEASE_WORDS: Final = {
    **dict.fromkeys(("version", "versions"), "version"),
    **dict.fromkeys(("release", "releases", "released", "releasing"), "release"),
    **dict.fromkeys(("upgrade", "upgrades", "upgraded", "upgrading"), "upgrade"),
    **dict.fromkeys(("patch", "patches", "patched", "patching"), "patch"),
    **dict.fromkeys(("vulnerability", "vulnerabilities", "vulnerable"), "vulnerability"),
}


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
        about=frozenset(RELEASE_WORDS),
        reaches=frozenset({"github"}),
    ),
    Ability(
        "create a Jira ticket after a yes",
        words("create add file raise open make log propose draft write submit put"),
        makes=TICKETS,
    ),
)

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
TOKEN: Final = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+|[-/.][A-Za-z0-9]+)*|[,;:.!?&+()]")
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
        return not self.starts and self.capital

    @property
    def key(self) -> bool:
        return KEY.fullmatch(self.raw) is not None and self.raw not in NOT_KEYS

    @property
    def system(self) -> str | None:
        if self.low in CASE_SENSITIVE and not self.capital:
            return None
        return self.low if self.low in SYSTEMS else None

    @property
    def product(self) -> bool:
        return self.system is None and CAMEL.fullmatch(self.raw) is not None


type Clause = tuple[_Word, ...]
type Phrases = list[tuple[str, Clause]]


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


def _said(clause: Clause, reader: _Reader) -> str:
    """The clause as the model wrote it, its verb in its plain form, to go after "I can't"."""
    first, *rest = clause
    found = reader.verb(first)
    titled = first.raw[1:] == first.raw[1:].lower()
    if found is not None:
        shown = found[0]
    elif first.system is None and first.capital and titled and first.starts:
        shown = first.low
    else:
        shown = first.raw
    for word in rest:
        glued = word.raw in ",;:.!?)" or shown.endswith("(")
        shown += word.raw if glued else f" {word.raw}"
    shown = shown.strip(" ,;:.!?")
    if len(shown) <= SAID_LIMIT:
        return shown
    return shown[: SAID_LIMIT - 1].rsplit(" ", 1)[0] + "…"


def _things(clause: Clause, start: int, reader: _Reader) -> tuple[list[Clause], int]:
    """The things the action acts on, each its own words, and where their words end."""
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
    return [tuple(thing) for thing in things if thing], at


def _phrases(clause: Clause, start: int, reader: _Reader) -> Phrases:
    phrases: list[tuple[str, list[_Word]]] = []
    for word in clause[start:]:
        if word.low in PARTICLES and not phrases:
            continue
        if word.low in PREPS:
            phrases.append((word.low, []))
            continue
        last = phrases[-1][1][-1] if phrases and phrases[-1][1] else None
        if (
            not phrases
            or word.mark
            or word.low in ENDS
            or (reader.acts(word) and not _noun_place(last))
        ):
            break
        phrases[-1][1].append(word)
    return [(prep, tuple(phrase)) for prep, phrase in phrases]


def _head(thing: Clause) -> _Word | None:
    return next((w for w in reversed(thing) if not w.raw.isdigit() and not w.key), None)


def _elsewhere(phrase: Clause, reaches: frozenset[str], products: bool = True) -> bool:
    """Whether the words name a place outside what an ability reaches."""
    for word in phrase:
        if word.system is not None and word.system not in reaches:
            return True
        if word.low in PLACES or (products and word.product):
            return True
    return False


def _names_jira(phrase: Clause) -> bool:
    return any(w.low in JIRA_ANCHORS or w.key for w in phrase)


def _jira_place(phrase: Clause) -> bool:
    """Every word is one a Jira place is written with, and one of them is Jira, a project, a
    board, a key, a ticket or the run."""
    named = False
    for at, word in enumerate(phrase):
        before = phrase[at - 1] if at else None
        after = phrase[at + 1] if at + 1 < len(phrase) else None
        beside = {w.low for w in (before, after) if w is not None}
        named_by = bool(beside & PROJECT_WORDS) or (
            before is not None and before.capital and before.low not in WHERE_WORDS
        )
        name = word.capital and word.system is None and not word.product and named_by
        if word.key or word.low in JIRA_ANCHORS | TICKETS | RUN_PLACES:
            named = True
        elif not (word.mark or word.low in WHERE_WORDS or name):
            return False
    return named and not _elsewhere(phrase, frozenset({JIRA}))


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


def _fits(ability: Ability, thing: Clause, phrases: Phrases) -> bool:
    if ability.makes is None:
        reads = any(w.low in TICKETS for w in thing) or not _elsewhere(
            thing, ability.reaches, False
        )
    else:
        reads = _makes(ability, ability.makes, thing, phrases)
    if not reads:
        return False
    for at, (prep, phrase) in enumerate(phrases):
        strict = at == 0 and prep in TO_PLACE and ability.makes is not None
        if strict and not _is_place(phrase, ability.reaches):
            return False
        named = prep == "for" and all(w.system or w.low in DETERMINERS for w in phrase)
        if (prep in IN_PLACE | TO_PLACE or named) and _elsewhere(phrase, ability.reaches):
            return False
    return True


def _made_so(clause: Clause, at: int) -> bool:
    """Whether a past form asks for a change, as in "get them closed", rather than says what
    happened, as in "tickets closed this week"."""
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
            if _made_so(clause, i):
                return True
        elif not _noun_place(clause[i - 1]):
            return True
    return False


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
    things, end = _things(clause, at if implied else at + 1, reader)
    phrases = _phrases(clause, end, reader)
    fits = bool(able) and all(any(_fits(a, t, phrases) for a in able) for t in things or [()])
    if fits and not _writes_in(clause, at, reader):
        return None
    return _said(clause[at:], reader)


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


def _source(clause: Clause, reaches: frozenset[str]) -> str | None:
    """The other system a search reads, as in "GitHub issues" or "users in Entra"."""
    for word, after in zip(clause, clause[1:], strict=False):
        system = word.system
        names_its_own = after.low in TICKETS or after.low in ("merge", "pull")
        if system in TICKET_SYSTEMS and system not in reaches and names_its_own:
            return SYSTEMS[system]
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
    at = _action_at(first)
    if at is not None:
        found = reader.verb(first[at])
        if found is not None and found[1] != "ed" and found[0] in reader.writes:
            return _said(first[at:], reader)
    reads = [
        ability
        for ability in reader.abilities
        if ability.makes is None
        and (ability.about is None or any(w.low in ability.about for w in row))
    ]
    reaches = frozenset(place for ability in reads for place in ability.reaches)
    source = _source(first, reaches)
    if source is not None:
        return f"read {source}"
    tickets = JIRA in reaches and any(w.low in TICKETS for w in first)
    if not tickets and not _names_jira(first) and not any(a.about for a in reads):
        named = next((w.system for w in first if w.system and w.system not in reaches), None)
        return f"read {SYSTEMS[named]}" if named else f"look for {_said(first, reader)}"
    return next((what for c in later if (what := _do(c, reader))), None)


def _where_row(row: Clause, reader: _Reader) -> str | None:
    at = _action_at(row)
    if at is None:
        return None
    found = reader.verb(row[at])
    if found is not None and found[1] != "ed":
        able = {verb for ability in reader.abilities for verb in ability.verbs}
        if found[0] not in able | PLACING:
            return _said(row[at:], reader)
        at += 1
        while at < len(row) and row[at].low in PRONOUNS:
            at += 1
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
    for part in (tuple(p) for p in parts if p):
        if not _is_place(part, places):
            lead = part[1:] if len(part) > 1 and part[0].low in TO_PLACE | IN_PLACE else part
            return f"put results in {_said(lead, reader)}"
    return None


def why_not(kind: RowKind, text: str, abilities: tuple[Ability, ...] = ABILITIES) -> str | None:
    """Why the platform can't do this part, in plain words, or None when every action in it fits
    one of the abilities."""
    reader = _reader(abilities)
    row = _tokens(text)
    match kind:
        case "schedule":
            what = _schedule_row(row, reader)
        case "look_for":
            what = _look_for_row(row, reader)
        case "do":
            what = _do_row(row, reader)
        case "where":
            what = _where_row(row, reader)
    return None if what is None else f"I can't {what} yet. {reader.can()}"
