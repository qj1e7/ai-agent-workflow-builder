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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_runtime.abilities import (
    CAPABILITIES,
    OFFER_REQUESTS,
    PAST_THE_NEWEST,
    change_verbs_in,
    nothing_close,
    other_systems,
    skip_of_a_yes,
    unread_field_in,
    vulnerability_phrase,
    why_not,
    words,
)
from agent_runtime.contract import (
    ABOUT_LIMIT,
    CHOICE_LIMIT,
    REPLY_TEXT_LIMIT,
    FactSection,
    FreeReplyAnswer,
    ReplyAbout,
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


NOT: Final = (
    r"(?:can['’]?t|cannot|can\s+not|won['’]?t|don['’]?t|doesn['’]?t|isn['’]?t|aren['’]?t|"
    r"wasn['’]?t|weren['’]?t|hasn['’]?t|haven['’]?t|not|never)"
)
NEGATION: Final = re.compile(rf"\b{NOT}\b", re.IGNORECASE)
"""A negation as an auxiliary says it: "can't", "isn't", "never". "No", "planned" or "yet" never
counts, so "No problem, ..." clears nothing."""
RIGHT_BEFORE: Final = re.compile(rf"\b{NOT}\s+$", re.IGNORECASE)
"""A negation directly before the words it governs, with nothing between, as "never approve"."""


CLAUSE_BREAK: Final = re.compile(
    r"[,;:]|\s+(?:but|so|while|whereas|although|though|because|however|then|yet)\s+",
    re.IGNORECASE,
)


def clauses(sentence: str) -> list[str]:
    """The sentence cut where a new clause starts, so a negation covers only its own words: in
    "It cannot phone you, but SMS alerts go out", the SMS clause is checked on its own."""
    return [c.strip() for c in CLAUSE_BREAK.split(sentence) if c.strip()]


def negated(clause: str) -> bool:
    """Whether the clause says something can't be done, with an auxiliary negation."""
    return NEGATION.search(clause) is not None


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
TLDS: Final = (
    "com|org|net|io|sg|gov|edu|mil|int|co|ai|dev|app|info|biz|me|uk|us|my|au|cn|jp|de|fr|es|it|"
    "nl|in|tv|cc|ly|gg|xyz|site|online|tech|cloud|store|link|page|so|to|sh|local|internal|test"
)
LINK: Final = re.compile(
    r"\b(?:https?|ftp|file)://|\bwww\.|\bmailto:|\blocalhost\b"
    rf"|\b[\w-]+(?:\.[\w-]+)*\.(?:{TLDS})\b|\b[\w-]+\s+dot\s+(?:{TLDS})\b"
    r"|\b[\w-]+\.[a-z]{2,}/|\b\d{1,3}(?:\.\d{1,3}){3}\b",
    re.IGNORECASE,
)
"""A link in any form: a scheme, www, a host with a known top-level domain, spelled out with
"dot", a host with a path, or an IP address."""
ARROWS: Final = re.compile(r"-{2,}>|<-{1,}|=>")
ENGLISH: Final = words(
    "the a an to of in on at for with and or but is are was be it its this that these those you "
    "your i me my we our they them their what which who when where how why can not no yes do does "
    "did if so as by from about into than then there here will would should could just only also "
    "each every all any some more one first next please thanks thank welcome hello hi sure okay "
    "ok you're it's i'm don't can't isn't won't let's here's that's what's i've we've you've i'll "
    "we'll you'll i'd has have had been being am were get got go make use see new now after "
    "before until up out over very too own same other"
)
"""Common English words. A reply reads as English when enough of its words are these."""


def _reads_as_english(text: str) -> bool:
    """Whether the words read as English: one common word in a very short reply, and at least
    one in five words in a longer one. The staff read English, and the checks only know it."""
    found = re.findall(r"[a-z]+(?:['’][a-z]+)?", text.casefold())
    common = sum(w.replace("’", "'") in ENGLISH for w in found)
    if len(found) < 4:
        return common >= 1
    return common / len(found) >= 0.2


def _plain_characters(text: str) -> bool:
    """Every letter, digit and mark is plain ASCII, and anything else is punctuation, so a
    look-alike letter from another script, or a mark laid over a letter, can't carry a word past
    the other checks. An accented letter is refused too: the strict check costs a fallback."""
    return all(c.isascii() or unicodedata.category(c) in SHOWN_PUNCTUATION for c in text)


def is_plain(reply: Shown, given: Given) -> bool:
    """Plain English text: plain characters, no Markdown, HTML, arrow or link anywhere, and a
    text that reads as English. The Portal draws the reply as text."""
    plain = all(
        _plain_characters(t)
        and not MARKUP.search(t)
        and not LINK.search(t)
        and not ARROWS.search(t)
        for t in (reply.text, *reply.choices)
    )
    return plain and _reads_as_english(reply.text)


# 3. No claim that something happened.

DONE: Final = (
    r"(?:created|sent|posted|approved|changed|saved|scheduled|set\s+up|turned\s+(?:on|off)|"
    r"switched\s+(?:on|off)|paused|resumed|deleted|removed|added|updated|edited|filed|raised|"
    r"closed|moved|emailed|mailed|messaged|notified|published|submitted|written|wrote|logged|"
    r"assigned|cancell?ed|fixed|retried|restarted|completed|done|made|opened|booked|arranged|"
    r"handled|sorted|received|put|enabled|launched|started|queued|activated)"
)
WRITTEN: Final = (
    r"(?:created|sent|posted|approved|deleted|emailed|published|submitted|filed|raised|saved|"
    r"set\s+up|turned\s+on|done|made|opened|booked|arranged|handled|sorted|received|queued|"
    r"enabled|activated|launched)"
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
    r"|\ball\s+set\b|^\s*(?:done|sorted)\b|\b(?:gone|went)\s+ahead\b"
    r"|\b(?:took|taken|taking)\s+care\b|\bconsider\s+it\s+(?:done|handled|sorted|taken)\b"
    r"|\bgot\s+it\s+done\b|\breceived\b|\bis\s+in\s*(?:[.!?]|$)|\b(?:went|gone|is)\s+through\b"
    r"|\bsaid\s+(?:yes|ok(?:ay)?)\b|\bsigned\s+off\b|\bgave\s+(?:it\s+|you\s+)?(?:a\s+|the\s+|their\s+)?"
    r"(?:yes|go-?ahead|ok(?:ay)?)\b|\bexists?\b|\bfrom\s+now\s+on\b"
    r"|\b(?:is|are|['’]s|['’]re)\s+(?:now\s+|already\s+)?(?:live|active|running|underway|"
    r"in\s+progress|happening|in\s+place)\b",
    re.IGNORECASE,
)
"""Words that say something happened: a change in the past or the present perfect, active or
passive, by the Planner, the platform or anyone, a decision someone made, or that something is
done, exists, or is now on or running. A first net only: the verifier asks the same question in
other words (`reply_verifier`)."""
WILL_HAPPEN: Final = re.compile(
    r"\b(?:will|['’]ll)\s+(?:now\s+|then\s+|also\s+)?(?:run|check|start|post|send|create|"
    r"raise|file|go\s+out|write|email|notify)\b",
    re.IGNORECASE,
)
"""A promise that something set up will happen, which says it was set up, unless the sentence
says when, as "once you turn it on, it will run every Monday"."""
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
    """No negation exempts a claim here. The reply is told never to say what was or wasn't
    done, so an honest "nothing was created" falls back too, on the safe side."""
    for clause in clauses(sentence):
        for found in HAPPENED.finditer(clause):
            before = clause[: found.start()]
            if not SUBORDINATE.search(before):
                return True
    promised = IS_WRITTEN.search(sentence) or WILL_HAPPEN.search(sentence)
    return promised is not None and not CONDITION.search(sentence)


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
NOTHING_I_CAN: Final = re.compile(
    r"\b(?:nothing|(?:isn['’]?t|is\s+not|not)\s+(?:something|anything))\s+(?:that\s+)?$",
    re.IGNORECASE,
)
"""A negated thing right before "I can", as "Nothing I can do comes close" or "isn't something
I can do yet". The negation acts on what "I can" would claim, so it claims nothing."""
ADVERBS: Final = words(
    "also still now only just then simply easily always even first next quickly anytime"
)
EVERYONE_DOES: Final = words(
    "type ask say tell describe write tap click press pick choose select open see view find read "
    "check look review use get go come try report list show explain follow help answer"
)
"""What anyone does in the app: say what they want, open a page, look something up."""
OPERATORS_DO: Final = EVERYONE_DOES | words(
    "watch track add set start run test turn pause resume change move save edit undo retry keep"
)
"""What an Operator does besides: set up workflows, change when they run, pause and resume
them, and add software to the Watchlist."""
OFF_THE_WATCHLIST: Final = re.compile(
    r"^\W*(?:remove|take)\b[^.?!]{0,60}?\b(?:off|from)\s+(?:the\s+|your\s+|my\s+|our\s+)?"
    r"(?:software\s+)?watch\s*-?list\b",
    re.IGNORECASE,
)
"""Taking software off the Watchlist (watchlist.remove), which only an Operator does."""
APPROVERS_DO: Final = EVERYONE_DOES | words("approve decline")

TICKETS: Final = r"(?:tickets?|issues?|bugs?|stor(?:y|ies)|tasks?|epics?|incidents?)"
TEAMS: Final = r"(?-i:Teams)"


def _field_named(text: str) -> bool:
    return unread_field_in(text) is not None


def _found(pattern: re.Pattern[str]) -> Callable[[str], bool]:
    return lambda text: pattern.search(text) is not None


def _n8n_block(system: str) -> Callable[[str], bool]:
    """n8n's own block for a system, which someone adds in n8n, never from the chat."""
    return _found(
        re.compile(rf"\bn8n\b[^.?!]{{0,20}}\b{system}\s+(?:blocks?|nodes?)\b", re.IGNORECASE)
    )


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
            r"\bslack\b|\bsms\b|\btext\s+messages?\b|\bwhatsapp\b|\btelegram\b|\bphones?\b|"
            r"\bchat\s+channels?\b",
            re.IGNORECASE,
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
    "jira.block_read": _n8n_block("jira"),
    "github.block_read": _n8n_block("github"),
    "slack.post": _n8n_block("slack"),
    "teams.block_post": _n8n_block("teams"),
    "outlook.send": _n8n_block("outlook"),
    "gmail.send": _n8n_block("gmail"),
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
    if OFF_THE_WATCHLIST.match(fragment):
        return does >= OPERATORS_DO
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
        before = sentence[: claim.start()]
        who = (claim.group("who") or claim.group("able") or claim.group("let") or "").casefold()
        if HYPOTHETICAL.search(before) or (who == "i" and NOTHING_I_CAN.search(before)):
            continue
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
    unbuilt also says, in the same clause, that it can't be done yet, unless it points to Ask the
    team. A choice to tap names nothing unbuilt."""
    yours = OPERATORS_DO if given.sets_up else APPROVERS_DO
    for sentence in sentences(reply.text):
        if not _claims_fit(sentence, yours):
            return False
        for clause in clauses(sentence):
            unsaid = not negated(clause) and not ASK_THE_TEAM.search(clause)
            if unsaid and names_the_unbuilt(clause):
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
SKIPS: Final = re.compile(
    r"\b(?:auto|pre|self)-?approv\w*|\bskips?\s+(?:the\s+|a\s+|any\s+)?(?:gate|yes|approval|"
    r"approver|review|check)\b|\bwithout\s+(?:a\s+|an\s+|any\s+|the\s+)?(?:one|yes|approval|"
    r"approver|sign-?off|review|person|anyone|asking)\b|\bdon['’]?t\s+need\s+(?:a\s+|an\s+|any\s+|"
    r"another\s+|a\s+second\s+|the\s+)?(?:person|approver|yes|approval|sign-?off|review)\b"
    r"|\bno\s+(?:need\s+(?:for|of)\s+(?:a\s+|an\s+)?)?(?:yes|approval|approver|sign-?off|wait|"
    r"waiting)\b|\bnot\s+every\s+(?:change|write|ticket)\s+needs\b|\b(?:straight|right)\s+"
    r"(?:away|out|through)\b|\bstraight\s+in\b|\bat\s+once\b|\bimmediately\b|\binstantly\b"
    rf"|\b{NOT}\s+(?:(?:need|needs|have|has)\s+to\s+)?(?:wait(?:s|ing)?|be\s+waiting)\b",
    re.IGNORECASE,
)
"""Words that say or imply a change goes ahead with no yes, or with no wait for one, as "it isn't
waiting for a yes". They count in a clause with a negation too: "no wait" is the claim."""

DENIES_A_SKIP: Final = re.compile(
    r"\bI\s+(?:can['’]?t|cannot|can\s+not|won['’]?t|don['’]?t|never)\s+"
    r"(?P<action>(?P<verb>[a-z]+)(?:\s+(?:a|an|the|that|this|any|one|new|jira)){0,3}\s+"
    r"(?:tickets?|changes?|it|that|this|one))\s+"
    r"without\s+(?:an?\s+|any\s+|the\s+)?(?:approver['’]s\s+)?(?:yes|approval)(?:\s+in\s+teams)?"
    r"(?=\s*(?:[,;:.!?]|$))",
    re.IGNORECASE,
)
"""An honest can't of a skipped yes, as "I can't create a ticket without an Approver's yes": a
first-person negation right before a change, then the yes it waits for, ending the clause."""
DENIAL_BEFORE: Final = re.compile(r"(?:^|,\s+because\s+)\Z", re.IGNORECASE)
DENIAL_AFTER: Final = re.compile(
    r"\s*(?:[.!?]\s*)?\Z|,\s+(?:because|as|since|and)\s+", re.IGNORECASE
)
"""How a denial may join the rest of its sentence: it opens the sentence or follows ", because",
and it ends the sentence or goes on with ", because", ", as", ", since" or ", and"."""
LEFT_OPEN: Final = re.compile(
    r"\b(?:but|though|although|however|whereas|while|except|unlike)\b"
    r"|\b(?:can|could|will|would|may|might|shall|should|must|do|does|did|is|are|was|were|has|"
    r"have|had)(?:\s+(?:too|also|instead|anyway))?\s*(?:[,;:.!?]|$)"
    r"|\bso\s+(?:can|could|will|would|may|might|do|does|did|is|are|has|have)\b",
    re.IGNORECASE,
)
"""Words in the rest of the sentence that could carry the denied change on without its yes: a
contrast, as "but you can", or a verb left out, as "and an Operator can" or "and so can you"."""


def _cut_a_denial(sentence: str) -> str:
    """The sentence with its honest can't of a skipped yes cut out, so the skip words in it are
    not read as a skip and the rest is read as usual. The can't must deny a change the platform
    makes after a yes, as the can check reads it, so "I can't delete a ticket without a yes"
    claims nothing unbuilt by the back door. Any other sentence is kept whole."""
    found = DENIES_A_SKIP.search(sentence)
    if found is None:
        return sentence
    before, after = sentence[: found.start()], sentence[found.end() :]
    joined = DENIAL_BEFORE.search(before) and DENIAL_AFTER.match(after)
    if not joined or LEFT_OPEN.search(f"{before} {after}"):
        return sentence
    planner_does = OPERATORS_DO | APPROVERS_DO
    if not change_verbs_in(found["verb"]) or not _can_do(found["action"], planner_does):
        return sentence
    return f"{before} {after}"


def keeps_every_yes(reply: Shown, given: Given) -> bool:
    """The text and every choice pass the word rule that refuses a skipped yes before any model
    call, and say no change goes ahead without a yes or without waiting for one. An honest can't
    of a skip in the text, as "I can't create a ticket without a yes", is no skip. No clause says
    someone approves their own work, and a sentence that says a ticket is made also says it waits
    for a yes."""
    heard = (" ".join(_cut_a_denial(s) for s in sentences(reply.text)), *reply.choices)
    if any(skip_of_a_yes(t) or SKIPS.search(t) for t in heard):
        return False
    shown = (reply.text, *reply.choices)
    for t in shown:
        if any(not RIGHT_BEFORE.search(t[: m.start()]) for m in OWN_YES.finditer(t)):
            return False
    for sentence in sentences(reply.text):
        found = MAKES_A_TICKET.finditer(sentence)
        made = any(not RIGHT_BEFORE.search(sentence[: m.start()]) for m in found)
        if made and not A_YES.search(sentence):
            return False
    return True


# 7. Nothing made up.

TICKET_KEY: Final = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,9}-\d+\b")
VERSION: Final = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+)+)\b", re.IGNORECASE)


def _seen(token: str, given: Given) -> bool:
    """Whether the facts sent, or the person's own words, hold the token. A key or a version the
    person typed is theirs, quoted back."""
    held = f"{given.facts}\n{given.message}"
    pattern = rf"(?<![\w.]){re.escape(token)}(?!\w|\.\d)"
    return re.search(pattern, held, re.IGNORECASE) is not None


COUNT: Final = re.compile(
    r"(?<![\w.])(\d+)\s+(?:workflows?|tickets?|software|requests?|runs?|approvals?|things?|"
    r"items?|bugs?|people|approvers?|operators?)\b",
    re.IGNORECASE,
)


type ListName = Literal["watchlist", "workflows", "needs_you"]

A_LIST: Final = (
    r"(?P<list>(?:(?:the|your|our|this)\s+(?:team['’]s\s+)?)"
    r"(?:(?:software\s+)?watch\s*list|list\s+of\s+workflows|workflows?\s+(?:list|page)|workflows)"
    r"|needs\s+you)"
)
STILL: Final = r"(?:(?:already|also|still|now|currently|only)\s+)*"
SAYS_IT_HOLDS: Final = re.compile(
    rf"\b{A_LIST}\s+{STILL}(?:holds?|has|have|includes?|contains?|lists?|shows?|keeps?|tracks?|"
    r"watch(?:es)?|covers?|carries|is\s+(?:watching|tracking|holding|showing))\b",
    re.IGNORECASE,
)
"""A list said to hold what follows, as "Your Watchlist already holds Redis"."""
YOU_WATCH: Final = re.compile(
    rf"\b(?:you|we|your\s+team|the\s+team)\s+{STILL}(?:watch|track|follow|"
    r"are\s+(?:watching|tracking|following))\b",
    re.IGNORECASE,
)
"""The Watchlist said to hold what follows, in other words, as "You already watch Redis"."""
IS_ON: Final = re.compile(
    rf"\b(?:is|are|['’]s|['’]re)\s+{STILL}(?:on|in|among|listed\s+(?:on|in)|part\s+of|"
    rf"one\s+of)\s+{A_LIST}",
    re.IGNORECASE,
)
"""What comes before said to be on a list, as "Redis is on your Watchlist". A negation, as
"isn't on", says it is not, and claims nothing held."""
SUBJECT_START: Final = re.compile(
    r"[;:]|\b(?:but|so|while|whereas|because|although|though|however|then|yet|if|when|once)\b",
    re.IGNORECASE,
)
ITEM_BREAK: Final = re.compile(
    r"\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or|plus|as\s+well\s+as|along\s+with)\s+",
    re.IGNORECASE,
)
LEADING: Final = re.compile(
    r"^(?:(?:the|a|an|your|our|their|its|this|that|both|also|only|just|already|still|now|"
    r"currently|even|software|workflows?|called|named|one)\s+)+",
    re.IGNORECASE,
)
TOKEN: Final = re.compile(r"[A-Za-z0-9][\w.+#'’-]*")
NUMBER: Final = re.compile(r"v?\d[\d.]*", re.IGNORECASE)
NOT_A_NAME: Final = ENGLISH | words(
    "software workflow workflows watchlist list lists page pages ticket tickets version versions "
    "release releases newest latest current older team run runs ran check checks checked state "
    "states nothing none everything anything something everyone approval approvals request "
    "requests items things whatever less several many few most date behind ahead waiting stopped "
    "paused draft drafts people person once twice since till yet either neither such another two "
    "three four five six seven eight nine ten zero approve open add type tap pick"
)
"""Plain lowercase words that open a description or a new clause, never a name: "the software
your team runs", "no software yet", "so open the Watchlist". Written with a capital mid-sentence,
as "holds Go", the same word is a name."""
APP_WORDS: Final = words(
    "ai troubleshooter planner operator operators approver approvers rail card cards button chat "
    "guide needs watchlist workflow workflows home teams jira github confluence"
)
"""The app's own words, as "the AI troubleshooter explains why" or "an Approver says yes". They
are never a name a list holds, capitalised or not."""
ALWAYS_CAPITAL: Final = words(
    "i i'm i've i'll i'd monday tuesday wednesday thursday friday saturday sunday january "
    "february march april june july august september october november december"
)
"""Words written with a capital wherever they stand, so the capital says nothing about them."""
SUBJECT_WORDS: Final = words(
    "it its this that these those they them all each every everything anything something nothing "
    "none both either neither which what who whatever one some any many most few several another "
    "other such you we i your our their my"
)
"""What opens a sentence that says something is on a list without naming it, as "It is on your
Watchlist". At the start of a sentence a capital says nothing, so any other word is a name."""


class _Named(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str


class _Lists(BaseModel):
    """The lists in the facts as the prompt carried them, and nothing else of them."""

    model_config = ConfigDict(extra="ignore")
    watchlist: list[_Named] | None = None
    workflows: list[_Named] | None = None
    other_workflows: list[str] | None = None


def _held(facts: str) -> Mapping[ListName, tuple[str, ...]]:
    """The names each list holds in the facts. Needs you holds counts, never names. Facts that
    don't parse hold nothing, so no name can be said to be held."""
    try:
        lists = _Lists.model_validate_json(facts) if facts else _Lists()
    except ValidationError:
        lists = _Lists()
    flows = [w.name for w in lists.workflows or []] + list(lists.other_workflows or [])
    return {
        "watchlist": tuple(w.name for w in lists.watchlist or []),
        "workflows": tuple(flows),
        "needs_you": (),
    }


def _list_of(said: str) -> ListName:
    low = said.casefold()
    return "watchlist" if "watch" in low else "needs_you" if "needs" in low else "workflows"


def _name_like(token: str, opens: bool = False) -> bool:
    """Whether a word reads as a name. A number, or a word of the app or the calendar, never does.
    At the start of a sentence any word but a pronoun or a determiner does, so "Go is on your
    Watchlist" names Go. Elsewhere a capital makes a name of a plain word, as "holds Go", and a
    plain lowercase word opens a description or a new clause."""
    word = token.casefold().rstrip(".").replace("’", "'")
    if NUMBER.fullmatch(word) or word in APP_WORDS or word in ALWAYS_CAPITAL:
        return False
    if opens:
        return word not in SUBJECT_WORDS
    return word not in NOT_A_NAME or any(c.isupper() for c in token)


def _item_made_up(item: str, names: tuple[str, ...], opens: bool) -> bool:
    """Whether a thing a list is said to hold names something the list doesn't: a name that is
    none of the facts' names, exactly, case aside. A longer name that starts with a held one, as
    "LangGraph Studio", is another name. `opens` is true for the words that open the sentence."""
    said = item.strip(" \"'“”‘’([)]")
    rest = LEADING.sub("", said)
    opens = opens and rest == said
    first = TOKEN.match(rest)
    if first is None:
        return False
    for name in sorted(names, key=len, reverse=True):
        held = re.match(rf"{_spelled(name)}(?![\w-])", rest, re.IGNORECASE)
        if held is not None:
            longer = re.match(rf"\s+({TOKEN.pattern})", rest[held.end() :])
            return longer is not None and _name_like(longer.group(1))
    return _name_like(first.group(0), opens)


def _claims_held(sentence: str) -> list[tuple[ListName, str, bool]]:
    """Each list the sentence says holds something, the words for what it holds, and whether
    those words open the sentence."""
    found: list[tuple[ListName, str, bool]] = []
    for m in SAYS_IT_HOLDS.finditer(sentence):
        found.append((_list_of(m.group("list")), sentence[m.end() :], False))
    for m in YOU_WATCH.finditer(sentence):
        found.append(("watchlist", sentence[m.end() :], False))
    for m in IS_ON.finditer(sentence):
        start = max((b.end() for b in SUBJECT_START.finditer(sentence, 0, m.start())), default=0)
        found.append((_list_of(m.group("list")), sentence[start : m.start()], start == 0))
    return found


def holds_only_what_the_facts_hold(text: str, facts: str) -> bool:
    """Every name the text says a list holds is in that list in the facts (ADR 0049). The third
    check lets "holds" through, so without this a reply could say the Watchlist holds software it
    doesn't."""
    held = _held(facts)
    return not any(
        _item_made_up(item, held[name], opens and n == 0)
        for sentence in sentences(text)
        for name, words_held, opens in _claims_held(sentence)
        for n, item in enumerate(ITEM_BREAK.split(words_held))
    )


def _spelled(name: str) -> str:
    return r"\s+".join(re.escape(part) for part in name.split())


def about_of(names: Sequence[str], text: str, facts: str) -> list[ReplyAbout]:
    """The watched software and workflows a reply speaks of (ADR 0049): each name the model gave
    that a list in the facts holds, case aside, and that the text names, spelled as the facts
    spell it, in the model's order, at most `ABOUT_LIMIT`. The Portal draws each one's line."""
    held = _held(facts)
    kept: list[ReplyAbout] = []
    for given in names:
        for section in ("watchlist", "workflows"):
            name = next(
                (n for n in held[section] if n.casefold() == given.strip().casefold()), None
            )
            about = None if name is None else ReplyAbout(section=section, name=name)
            named = name is not None and re.search(
                rf"(?<![\w-]){_spelled(name)}(?![\w-])", text, re.I
            )
            if about is not None and named and about not in kept:
                kept.append(about)
                break
    return kept[:ABOUT_LIMIT]


def makes_nothing_up(reply: Shown, given: Given) -> bool:
    """A ticket key, a version number, or a count of the person's things in the text appears in
    the facts sent or the message, and every name a list is said to hold is in that list."""
    keys = TICKET_KEY.findall(reply.text)
    versions = [found.group(1) for found in VERSION.finditer(reply.text)]
    counts = COUNT.findall(reply.text)
    seen = all(_seen(token, given) for token in [*keys, *versions, *counts])
    return seen and holds_only_what_the_facts_hold(reply.text, given.facts)


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
    once, checked, and shown as they were checked. A can't with nothing close, whose button is
    Ask the team, also says what the app is for and what it can do, in the registry's words, and
    those are checked with the rest."""
    shown = shown_of(reply)
    offer = offer_of(shown.offer, given) if shown.form == "cant" else None
    if shown.form == "cant" and offer is None:
        shown = replace(shown, text=f"{shown.text} {nothing_close()}")
    failed = failed_check(shown, given)
    if failed is not None:
        return failed
    return FreeReplyAnswer(
        form=shown.form,
        text=shown.text,
        choices=list(shown.choices),
        offer=offer,
        looked_at=[s for s in given.sent if s in shown.looked_at],
    )
