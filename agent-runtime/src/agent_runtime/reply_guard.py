"""The code checks on the Planner's free reply (ADR 0047).

The model fills a closed envelope, `ReplyEnvelope`. Its words are made into what the person will
see once (`shown_of`), and the checks in `CHECKS` read only that, in order. The first that fails
swaps in the fixed fallback. They lean strict: a
strict check costs only a fallback, which the eval counts. Each check is a pure function of the
envelope and of what the reply was given, so each has its own tests. A guard is a filter, not a
proof. What slips past it can only mislead in words: the reply has no tool, and a write still
needs a card and a yes."""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from agent_runtime.abilities import (
    CAPABILITIES,
    OFFER_REQUESTS,
    PAST_THE_NEWEST,
    change_verbs_in,
    other_systems,
    skip_of_a_yes,
    unread_field_in,
    vulnerability_phrase,
    why_not,
    words,
)
from agent_runtime.contract import (
    CHOICE_LIMIT,
    REPLY_TEXT_LIMIT,
    FactSection,
    FreeReplyAnswer,
    ReplyEnvelope,
    ReplyForm,
    ReplyOffer,
)
from agent_runtime.planner import visible_words

type GuardCheck = Literal[
    "shape",
    "plain_text",
    "claims_done",
    "claims_unbuilt",
    "offers_to_act",
    "skips_a_yes",
    "made_up",
]


@dataclass(frozen=True)
class Given:
    """What the reply was given, which the checks hold it to."""

    message: str
    facts: str
    """The facts as the prompt carried them, or empty when none were sent."""
    sent: tuple[FactSection, ...] = ()
    sets_up: bool = True
    """True for an Operator, who sets up and changes workflows. An Approver asks questions and
    decides on requests, so the reply may not tell them they can set something up."""
    clarified_before: bool = False
    """True when the answer before was a clarifying question, so this one may not ask another."""


def shown_words(text: str) -> str:
    """The words as the person sees them: compatibility forms such as fullwidth letters folded to
    plain ones (NFKC), invisible characters dropped, and spaces collapsed."""
    return visible_words(unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class Shown:
    """The reply exactly as the person would see it. The checks take this, not the envelope, so
    none of them reads the model's raw text, and nothing changes the words after they pass."""

    form: ReplyForm
    text: str
    choices: tuple[str, ...]
    offer: str | None
    looked_at: tuple[str, ...]


def shown_of(reply: ReplyEnvelope) -> Shown:
    return Shown(
        form=reply.form,
        text=shown_words(reply.text),
        choices=tuple(shown_words(c) for c in reply.choices),
        offer=(reply.offer or "").strip() or None,
        looked_at=tuple(reply.looked_at),
    )


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


NEGATION: Final = re.compile(
    r"\b(?:can['’]?t|cannot|can\s+not|won['’]?t|don['’]?t|doesn['’]?t|isn['’]?t|aren['’]?t|"
    r"not|never|no|planned|yet)\b",
    re.IGNORECASE,
)


def negated(sentence: str) -> bool:
    return NEGATION.search(sentence) is not None


# 1. Shape.


def fits_its_form(reply: Shown, given: Given) -> bool:
    """The text fits, a clarifying question ends with "?" and has 2 to 4 short distinct choices,
    only a clarifying question has choices, and only a can't has an offer. A second clarifying
    question in a row is never asked."""
    choices = reply.choices
    if not 1 <= len(reply.text) <= REPLY_TEXT_LIMIT:
        return False
    if reply.form != "cant" and reply.offer is not None:
        return False
    if reply.form != "clarify":
        return not choices
    return (
        not given.clarified_before
        and reply.text.endswith("?")
        and 2 <= len(choices) <= 4
        and len({c.casefold() for c in choices}) == len(choices)
        and all(1 <= len(c) <= CHOICE_LIMIT for c in choices)
    )


# 2. Plain text.

MARKUP: Final = re.compile(
    r"\*\*|__|`|~~|\[[^\]]*\]\([^)]*\)|<\s*/?\s*[a-z!][^>]*>|&(?:[a-z]+|#\d+);"
    r"|(?:^|\s)#{1,6}\s|(?:^|[\s:])[-*+•]\s|(?:^|\s)1[.)]\s.*\s2[.)]\s|^>"
    r"|(?<!\w)\*(?=\S)[^*]+(?<=\S)\*(?!\w)",
    re.IGNORECASE,
)
"""Markdown and HTML, in words whose line breaks are already spaces: a heading, a list, a
quote, emphasis, code, a link or a tag."""
SHOWN_PUNCTUATION: Final = frozenset({"Pd", "Pi", "Pf", "Ps", "Pe", "Po", "Sc", "Zs"})
LINK: Final = re.compile(
    r"\b(?:https?://|ftp://|www\.|mailto:)"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|sg|gov|edu|co|ai|dev|app|info|me|uk|us)\b",
    re.IGNORECASE,
)


def _plain_characters(text: str) -> bool:
    """Every letter, digit and mark is plain ASCII, and anything else is punctuation, so a
    look-alike letter from another script, or a mark laid over a letter, can't carry a word past
    the other checks. An accented letter is refused too: the strict check costs a fallback."""
    return all(c.isascii() or unicodedata.category(c) in SHOWN_PUNCTUATION for c in text)


def is_plain(reply: Shown, given: Given) -> bool:
    """Plain characters, and no Markdown, HTML or link anywhere: the Portal draws the reply as
    text."""
    return all(
        _plain_characters(t) and not MARKUP.search(t) and not LINK.search(t)
        for t in (reply.text, *reply.choices)
    )


# 3. No claim that something happened.

DONE: Final = (
    r"(?:created|sent|posted|approved|changed|saved|scheduled|set\s+up|turned\s+(?:on|off)|"
    r"switched\s+(?:on|off)|paused|resumed|deleted|removed|added|updated|edited|filed|raised|"
    r"closed|moved|emailed|mailed|messaged|notified|published|submitted|written|wrote|logged|"
    r"assigned|cancell?ed|fixed|retried|restarted|completed|done)"
)
WRITTEN: Final = (
    r"(?:created|sent|posted|approved|deleted|emailed|published|submitted|filed|raised|saved|"
    r"set\s+up|turned\s+on|done)"
)
SOON: Final = r"(?:(?:just|already|now|successfully|also|been|all)\s+)*"
HAPPENED: Final = re.compile(
    rf"\b(?:have|has|had|['’]ve|was|were)\s+{SOON}{DONE}\b"
    rf"|\b(?:I|we|it|the\s+(?:planner|platform|agents?|app|system))\s+{SOON}{DONE}\b"
    rf"|\b(?:it|that|this|everything|all)['’]s\s+{SOON}{DONE}\b"
    rf"|\b(?:is|are|['’]s|['’]re)\s+(?:now|already|all)\s+(?:{DONE}|on|off|live|active|running|"
    rf"set|ready|in\s+place)\b"
    r"|\b\w+\s+(?:has\s+|had\s+|already\s+|just\s+)*(?:approved|declined)\s+"
    r"(?:it|your|the|this|that|them)\b"
    r"|\ball\s+set\b|^\s*done\b",
    re.IGNORECASE,
)
"""Words that say something happened: a change in the past or the present perfect, active or
passive, by the Planner, the platform or anyone, a decision someone made, or that something is
done or is now on."""
IS_WRITTEN: Final = re.compile(rf"\b(?:is|are)\s+{WRITTEN}\b", re.IGNORECASE)
"""A present passive, as "your ticket is created", which says it happened unless the sentence
says when, as "a ticket is created only after a yes"."""
CONDITION: Final = re.compile(
    r"\b(?:after|once|when|whenever|until|only|if|unless|before|each\s+time|every\s+time)\b",
    re.IGNORECASE,
)
SUBORDINATE: Final = re.compile(
    r"\b(?:that|which|who|when|whether|if|since|once|after|until|before)\s+(?:\S+\s+){0,2}$",
    re.IGNORECASE,
)
"""A clause that describes rather than claims, as "when it was created" or "tickets that were
updated"."""


def _says_it_happened(sentence: str) -> bool:
    for found in HAPPENED.finditer(sentence):
        if not SUBORDINATE.search(sentence[: found.start()]):
            return True
    return IS_WRITTEN.search(sentence) is not None and not CONDITION.search(sentence)


def claims_nothing_done(reply: Shown, given: Given) -> bool:
    """The reply never says that anything was created, sent, approved, changed or the like, nor
    that something is done or is now on. It did nothing: it only replies."""
    return not any(_says_it_happened(s) for s in sentences(reply.text))


# 4. No claim of an unbuilt ability.

CLAIM: Final = re.compile(
    r"\b(?P<who>I|you|we|it|the\s+(?:planner|platform|agents?|app|system))\s+"
    r"(?:(?:also|still|now|only|just|then|already|easily|simply)\s+)*"
    r"(?:can|could|am\s+able\s+to|are\s+able\s+to|is\s+able\s+to|will\s+be\s+able\s+to)"
    r"(?!['’]?t\b)(?!not\b)(?!\s+not\b)\s+"
    r"|\b(?P<able>I|you|we)['’](?:m|re)\s+able\s+to\s+"
    r"|\b(?:lets?|allows?|helps?|enables?)\s+(?P<let>you)\s+(?:to\s+)?",
    re.IGNORECASE,
)
HYPOTHETICAL: Final = re.compile(r"\b(?:if|whether)\s+$", re.IGNORECASE)
""""Ask the team whether it can be added" claims nothing."""
ADVERBS: Final = words(
    "also still now only just then simply easily always even first next quickly anytime"
)
EVERYONE_DOES: Final = words(
    "type ask say tell describe write tap click press pick choose select open see view find read "
    "check look review use get go come try report list show explain follow"
)
"""What anyone does in the app: say what they want, open a page, look something up."""
OPERATORS_DO: Final = EVERYONE_DOES | words(
    "watch track add set start run test turn pause resume change move save edit undo retry keep"
)
"""What an Operator does besides: set up workflows, change when they run, pause and resume
them, and add software to the Watchlist."""
APPROVERS_DO: Final = EVERYONE_DOES | words("approve decline")

TICKETS: Final = r"(?:tickets?|issues?|bugs?|stor(?:y|ies)|tasks?|epics?|incidents?)"
TEAMS: Final = r"(?-i:Teams)"


def _field_named(text: str) -> bool:
    return unread_field_in(text) is not None


def _found(pattern: re.Pattern[str]) -> Callable[[str], bool]:
    return lambda text: pattern.search(text) is not None


NOT_READY: Final[dict[str, Callable[[str], bool]]] = {
    "jira.find_by_detail": _field_named,
    "jira.find_older": _found(PAST_THE_NEWEST),
    "teams.post": _found(
        re.compile(
            r"\be-?mail\w*|\binbox\b|\boutlook\b"
            r"|\b(?:post|send|share|message|notify|ping|alert|announce|tell|remind|broadcast|"
            rf"forward)\w*\b[^.?!]{{0,60}}\b{TEAMS}"
            rf"|\b{TEAMS}\s+(?:channels?|chats?|messages?|posts?)\b",
            re.IGNORECASE,
        )
    ),
    "confluence.change": _found(
        re.compile(
            r"\b(?:updat(?:e|es|ing)|chang(?:e|es|ing)|edit(?:s|ing)?|writ(?:e|es|ing)|"
            r"post(?:s|ing)?|publish(?:es|ing)?|creat(?:e|es|ing)|add(?:s|ing)?|put(?:s|ting)?|"
            r"sav(?:e|es|ing))\b[^.?!]{0,60}\bconfluence\b"
            r"|\bconfluence\b[^.?!]{0,30}\b(?:updat(?:e|es|ing)|chang(?:e|es|ing)|edit(?:s|ing)?)\b",
            re.IGNORECASE,
        )
    ),
    "github.issues": _found(
        re.compile(
            r"\bgithub\s+issues?\b|\bissues?\s+(?:on|in|from)\s+github\b|\bpull\s+requests?\b",
            re.IGNORECASE,
        )
    ),
    "access.check": _found(
        re.compile(
            r"\bwho\s+has\s+access\b|\baccess\s+(?:review|reviews|rights|lists?)\b|\bentra\b|"
            r"\bactive\s+directory\b|\badmin\s+tools?\b|\bgitlab\b|\bpermissions?\b",
            re.IGNORECASE,
        )
    ),
    "registries.check": _found(
        re.compile(
            r"\bregistr(?:y|ies)\b|\bpypi\b|\bnpm\b|\bdocker\s+hub\b|\bmaven\b|\badvisor(?:y|ies)\b",
            re.IGNORECASE,
        )
    ),
    "jira.set_field": _field_named,
    "slack.send": _found(
        re.compile(
            r"\bslack\b|\bsms\b|\btext\s+messages?\b|\bwhatsapp\b|\btelegram\b", re.IGNORECASE
        )
    ),
    "jira.delete": _found(
        re.compile(
            r"\b(?:delet(?:e|es|ing)|purg(?:e|es|ing)|eras(?:e|es|ing)|wip(?:e|es|ing)|"
            r"destroy(?:s|ing)?|trash(?:es|ing)?|remov(?:e|es|ing))\b"
            rf"[^.?!]{{0,40}}\b(?:{TICKETS}|jira)\b",
            re.IGNORECASE,
        )
    ),
    "jira.change_tickets": _found(
        re.compile(
            r"\b(?:clos(?:e|es|ing)|resolv(?:e|es|ing)|reopen(?:s|ing)?|edit(?:s|ing)?|"
            r"mov(?:e|es|ing)|transition(?:s|ing)?|(?:re)?assign(?:s|ing)?|updat(?:e|es|ing)|"
            r"modif(?:y|ies|ying)|chang(?:e|es|ing)|label(?:s|l?ing)?|flag(?:s|ging)?|"
            rf"prioriti[sz](?:e|es|ing)|comment(?:s|ing)?\s+on)\b[^.?!]{{0,40}}\b{TICKETS}\b",
            re.IGNORECASE,
        )
    ),
}
"""For each capability the registry marks Planned or Unsupported, whether a piece of text names
it. A test holds this table to the registry, so a new entry can't be left out."""
REACHED_FOR_YES: Final = frozenset({"Teams"})
"""Approvers say yes in Teams, so naming Teams alone is no claim. Posting there is (teams.post)."""
ASK_THE_TEAM: Final = re.compile(r"\bask\s+the\s+team\b", re.IGNORECASE)


def names_the_unbuilt(text: str) -> bool:
    """Whether the text names something the platform can't do: a capability the registry marks
    Planned or Unsupported, known vulnerabilities, or a system the platform doesn't reach."""
    if any(named(text) for named in NOT_READY.values()) or vulnerability_phrase(text):
        return True
    return bool(set(other_systems(text)) - REACHED_FOR_YES)


def _fits_a_ready_line(fragment: str) -> bool:
    """`ABILITIES`' own rule for a set-up card's parts, read as an action or as a search."""
    return why_not("do", fragment) is None or why_not("look_for", fragment) is None


def _first_word(fragment: str) -> str:
    found = [w for w in re.findall(r"[a-z][a-z'’-]*", fragment.casefold()) if w not in ADVERBS]
    return found[0] if found else ""


def _can_do(fragment: str, does: frozenset[str]) -> bool:
    """One action a "can" sentence claims. An action in the app is the person's own, as long as
    whatever it asks someone "to" do fits a Ready line too. Anything else must fit a Ready line,
    and an action that is claimed never names something unbuilt, unless it asks the team."""
    if ASK_THE_TEAM.search(fragment):
        return True
    if names_the_unbuilt(fragment):
        return False
    if _first_word(fragment) not in does:
        return _fits_a_ready_line(fragment)
    for asked in re.finditer(r"\bto\s+([a-z]+)\b", fragment, re.IGNORECASE):
        if change_verbs_in(asked.group(1)) and not _fits_a_ready_line(fragment[asked.start(1) :]):
            return False
    return True


FRAGMENTS: Final = re.compile(r"[,;:]|\s+(?:and|or|then|but|plus)\s+", re.IGNORECASE)


def _claims_fit(sentence: str, yours: frozenset[str]) -> bool:
    """Every action the sentence claims after "can": the first always, and each later one that
    opens with a verb, as "pick a time and turn it on". What "you" can do is held to the
    person's own role. What the Planner or the platform can do is any action in the app."""
    for claim in CLAIM.finditer(sentence):
        if HYPOTHETICAL.search(sentence[: claim.start()]):
            continue
        who = (claim.group("who") or claim.group("able") or claim.group("let") or "").casefold()
        does = yours if who == "you" else OPERATORS_DO | APPROVERS_DO
        first, *later = FRAGMENTS.split(sentence[claim.end() :])
        if not _can_do(first, does):
            return False
        for fragment in later:
            word = _first_word(fragment)
            opens_with_a_verb = word in does or bool(change_verbs_in(word))
            if opens_with_a_verb and not _can_do(fragment, does):
                return False
    return True


def claims_only_what_is_built(reply: Shown, given: Given) -> bool:
    """Each sentence that says the platform, the Planner, "I" or "you" can do something fits a
    Ready line, or is an action in the app this person has. A sentence that names something
    unbuilt also says it can't be done yet, unless it points to Ask the team. A choice to tap
    names nothing unbuilt."""
    yours = OPERATORS_DO if given.sets_up else APPROVERS_DO
    for sentence in sentences(reply.text):
        if not _claims_fit(sentence, yours):
            return False
        unsaid = not negated(sentence) and not ASK_THE_TEAM.search(sentence)
        if unsaid and names_the_unbuilt(sentence):
            return False
    return not any(names_the_unbuilt(c) for c in reply.choices)


# 5. No offer to act.

OFFERS_TO_ACT: Final = re.compile(
    r"\b(?:I['’]ll|I\s+will|I\s+shall|I['’]m\s+going\s+to|I\s+am\s+going\s+to|we['’]ll|"
    r"we\s+will|let\s+me|let['’]s|want\s+me\s+to|would\s+you\s+like\s+me|shall\s+I|"
    r"happy\s+to|keep\s+you\s+(?:posted|updated|informed)|let\s+you\s+know|"
    r"get\s+back\s+to\s+you|promis\w*)\b",
    re.IGNORECASE,
)


def offers_nothing(reply: Shown, given: Given) -> bool:
    """The reply tells the person what to type or tap. It never promises to do it."""
    return OFFERS_TO_ACT.search(reply.text) is None


# 6. No skipped yes.

OWN_YES: Final = re.compile(
    r"\b(?:approv\w*|sign\w*\s+off\s+on|ok(?:ay)?s?|decid\w*\s+on)\s+(?:your|their|his|her|my|"
    r"our|its)\s+own\b",
    re.IGNORECASE,
)
MAKES_A_TICKET: Final = re.compile(
    r"\b(?:creat(?:e|es|ing)|fil(?:e|es|ing)|rais(?:e|es|ing)|log(?:s|ging)?|writ(?:e|es|ing)|"
    r"mak(?:e|es|ing)|add(?:s|ing)?|put(?:s|ting)?)\b[^.?!]{0,40}\btickets?\b"
    r"|\bnew\s+(?:jira\s+)?tickets?\b",
    re.IGNORECASE,
)
A_YES: Final = re.compile(r"\b(?:yes|approv\w*)\b", re.IGNORECASE)


def keeps_every_yes(reply: Shown, given: Given) -> bool:
    """The text and every choice pass the word rule that refuses a skipped yes before any model
    call. No sentence says someone approves their own work, and one that says a ticket is made
    also says it waits for a yes."""
    if any(skip_of_a_yes(t) for t in (reply.text, *reply.choices)):
        return False
    for sentence in sentences(reply.text):
        if negated(sentence):
            continue
        if OWN_YES.search(sentence) or (
            MAKES_A_TICKET.search(sentence) and not A_YES.search(sentence)
        ):
            return False
    return True


# 7. Nothing made up.

TICKET_KEY: Final = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
VERSION: Final = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+)+)\b", re.IGNORECASE)


def _seen(token: str, given: Given) -> bool:
    """Whether the facts sent, or the person's own words, hold the token. A key or a version the
    person typed is theirs, quoted back."""
    held = f"{given.facts}\n{given.message}"
    return re.search(rf"(?<![\w.]){re.escape(token)}(?!\w|\.\d)", held) is not None


def makes_nothing_up(reply: Shown, given: Given) -> bool:
    """A ticket key or a version number in the text appears in the facts sent or the message."""
    keys = TICKET_KEY.findall(reply.text)
    versions = [found.group(1) for found in VERSION.finditer(reply.text)]
    return all(_seen(token, given) for token in [*keys, *versions])


CHECKS: Final[tuple[tuple[GuardCheck, Callable[[Shown, Given], bool]], ...]] = (
    ("shape", fits_its_form),
    ("plain_text", is_plain),
    ("claims_done", claims_nothing_done),
    ("claims_unbuilt", claims_only_what_is_built),
    ("offers_to_act", offers_nothing),
    ("skips_a_yes", keeps_every_yes),
    ("made_up", makes_nothing_up),
)


def failed_check(reply: Shown, given: Given) -> GuardCheck | None:
    """The first check the reply fails, or None when it may be shown."""
    return next((name for name, passes in CHECKS if not passes(reply, given)), None)


# 8. Offers the person can use.

BY_ID: Final = {c.id: c for c in CAPABILITIES}


def offer_of(capability: str | None, given: Given) -> ReplyOffer | None:
    """The button for a can't: the request `OFFER_REQUESTS` holds for the capability, kept only
    when it is Ready, not the platform's own work, and the person sets up workflows. None means
    the button is Ask the team."""
    spec = BY_ID.get((capability or "").strip())
    if spec is None or spec.state != "ready" or spec.platform or not given.sets_up:
        return None
    request = OFFER_REQUESTS.get(spec.id)
    return None if request is None else ReplyOffer(capability=spec.id, request=request)


def guarded(reply: ReplyEnvelope, given: Given) -> FreeReplyAnswer | GuardCheck:
    """The reply the person sees, or the check it failed. The words are made into what is shown
    once, checked, and shown as they were checked."""
    shown = shown_of(reply)
    failed = failed_check(shown, given)
    if failed is not None:
        return failed
    return FreeReplyAnswer(
        form=shown.form,
        text=shown.text,
        choices=list(shown.choices),
        offer=offer_of(shown.offer, given) if shown.form == "cant" else None,
        looked_at=[s for s in given.sent if s in shown.looked_at],
    )
