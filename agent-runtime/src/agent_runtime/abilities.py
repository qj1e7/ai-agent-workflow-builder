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
RELEASE_ROOTS: Final = {
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
        about=frozenset(RELEASE_ROOTS),
        reaches=frozenset({"github"}),
    ),
    Ability(
        "create a Jira ticket after a yes",
        words("create add file raise open make log propose draft write submit put generate"),
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
PLACE_ADVERBS: Final = words("somewhere anywhere everywhere elsewhere wherever here there")
PLACING_FORMS: Final = words("put puts putting go goes going went gone")
DELIVERS: Final = words("post send share save publish")
TOPICS: Final = words(
    "outage outages incident incidents migration migrations rollout rollouts downtime "
    "problem problems error errors decommission decommissioning review reviews"
) | frozenset(RELEASE_ROOTS)
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


def _its_own_tickets(clause: Clause, reaches: frozenset[str]) -> str | None:
    for word, after in zip(clause, clause[1:], strict=False):
        system = word.system
        names_its_own = after.low in TICKETS or after.low in ("merge", "pull")
        if system in TICKET_SYSTEMS and system not in reaches and names_its_own:
            return SYSTEMS[system]
    return None


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
        part = tuple(words_of_part)
        if not part or _is_place(part, places):
            continue
        if number == 0 and verb_at is not None and part[0].low not in TO_PLACE | IN_PLACE:
            what = _do_row(row[verb_at : at + len(part)], reader)
        else:
            what = _not_a_place(part, reader, places)
        if what is not None:
            return what
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
