"""A change to a workflow the person already has, asked for in the chat (plan 4.2, spec 6.4, 6.7).

Commands fail closed. Code takes the question's own words and the workflows' names out of the
request, and a change word left over makes it a command, never a status answer. A schedule word
inside a workflow's own name is neither, and "the run" is a noun. An edit changes only when a
workflow runs: any other change, and a schedule it can't hold, come back as what the chat can't do
yet. The answer only proposes. Nothing changes until the person saves it. A pause or a resume and
nothing else is its own answer, which the platform carries out for the workflow it names.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Final

from agent_runtime.abilities import change_verbs_in, commands_a_change, words
from agent_runtime.contract import (
    EditAnswer,
    EditCant,
    PartMark,
    PartReason,
    PauseAnswer,
    PlannerFacts,
    ResumeAnswer,
    ScheduleChange,
    WatchDay,
)
from agent_runtime.planner import visible_words, whole_word_of
from agent_runtime.reading import (
    DAY_NAMES,
    FILLER,
    FREQUENCY,
    OFTEN,
    SCHEDULE_VOCAB,
    Clash,
    TaskRead,
    clashes_in,
    clauses_of,
    said_schedule,
)

type Span = tuple[int, int]

QUESTION_START: Final = re.compile(
    r"^(?:which|what|what's|how|is|are|do|does|did|when|why|who|whose|has|have|any|anything)\b",
    re.IGNORECASE,
)
STATE_WORDS: Final = re.compile(
    r"\b(?:workflows?|running|runs?\s+next|next\s+run|stopped|stop|failed|fail|broke|broken|"
    r"wrong|paused|status|doing|going|waiting|attention|approv\w*|decided|decisions?|"
    r"declined?|behind|up\s+to\s+date|versions?|software|watchlist|watching|watched|latest|"
    r"newest|releases?|needs?\s+(?:me|my)|for\s+me|on\s+me)\b",
    re.IGNORECASE,
)
"""Words that ask about the person's workflows, approvals or software."""
ASKING_VERBS: Final = re.compile(
    r"\b(?:run|runs|running|ran|start|starts|started|starting|stops?|stopping|set)\b",
    re.IGNORECASE,
)
"""Verbs a question uses about a workflow's state, as "when does it run", "why did it stop" or
"is it set to run on Mondays"."""
TELL_ME: Final = re.compile(
    r"^(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
    r"(?:(?:tell|show|remind)\s+(?:me|us)|let\s+(?:me|us)\s+know)\b",
    re.IGNORECASE,
)
"""A question put as a request, as "can you tell me when it runs next" or "show me the last
run"."""
PAST: Final = re.compile(r"^(?:did|has|have|was|were)\b", re.IGNORECASE)
"""A question about what was done, as "did anyone change it", which changes nothing."""
ORDER_LEAD: Final = re.compile(
    r"^(?:please\s+)?(?:can|could|would)\b|^(?:please\s+)?will\s+you\b|^please\b|"
    r"^(?:have|get)\s+(?:it|them)\b",
    re.IGNORECASE,
)
"""A clause that opens like this asks for something to be done, whatever its question mark, as
"could it run on Tuesdays?" or "have it run on Mondays"."""
LANE_BLOCKERS: Final = re.compile(
    r"\b(?:stop\s+watching|unwatch(?:ing)?|stop\s+tracking)\b", re.IGNORECASE
)
"""Changes that `change_verbs_in` misses. They stay out of it because it feeds other answers."""

SCHEDULE_VERBS: Final = words(
    "make change switch move set reschedule shift push bring run start update edit"
)
"""Verbs that change when a workflow runs, as "make it run on Mondays"."""
OTHER_CHANGES: Final = words(
    "pause resume unpause stop halt kill suspend restart delete remove drop rename turn cancel "
    "disable enable retry rerun"
)
"""Verbs that change a workflow some other way, which the chat can't do yet."""
EDIT_VERBS: Final = SCHEDULE_VERBS | OTHER_CHANGES
PAUSES: Final = words("pause stop halt suspend disable")
RESUMES: Final = words("resume unpause enable")
SWITCH_WORDS: Final = PAUSES | RESUMES | words("turn running")
TURNED: Final = re.compile(r"\bturn\b(?:\s+(?:it|them|back))*\s+(on|off)\b", re.IGNORECASE)
"""Turning a workflow on or off, as "turn it back on", once the workflow's name is out."""
FROM_TO_VERBS: Final = words("change move switch shift reschedule push bring")
"""Verbs whose "from Mondays to Tuesdays" names the schedule now and the new one."""
NOUN: Final = re.compile(
    r"\b(?:a|an|the|this|that|any|no|last|next|each|its|my|our|every|latest|new|recent|first|"
    r"previous)\s+(?:run|runs|update|updates|change|changes|set|edit|edits|move|start|stop)\b",
    re.IGNORECASE,
)
"""A change verb after an article is a noun, as "the last run" or "an update"."""
CANT_HOLD: Final = frozenset({"month", "quarter", "year", "fortnight", "hour"})
SO_OFTEN: Final = re.compile(
    rf"\bevery\s+(?:other|second|third|\d+|two|three|four|five|six)\s+"
    rf"(?:days?|weeks?|months?|hours?|(?:{DAY_NAMES})s?)\b|"
    r"\b(?:twice|(?:three|four|five|\d+)\s+times)\s+(?:a|an|per|each|every)\s+\w+|"
    r"\b(?:on\s+)?(?:the\s+)?weekends?\b|"
    r"\b(?:except|excluding|but\s+not|apart\s+from|other\s+than)\b[^,.;!?]*",
    re.IGNORECASE,
)
"""A schedule it can't hold beyond the frequencies, as "every other day", "twice a week", "on
weekends" or "every weekday except Friday"."""
NEW_WORKFLOW: Final = re.compile(
    r"^(?:(?:and|then|also|please)\s+)*(?:(?:can|could|would|will)\s+you\s+)?"
    r"(?:set\s+up|make|build)\s+(?:a|an|another|one|some)\s+(?:new\s+)?"
    r"(?!(?:jira\s+)?tickets?\b)",
    re.IGNORECASE,
)
"""A clause that asks for a new workflow, as "set up a weekly summary". It changes nothing that
exists, so it is a task beside a question, never a command on one."""
DEFINITE: Final = re.compile(r"\b(?:the|my|our|this|that)\s+$", re.IGNORECASE)
REFERENCE: Final = re.compile(
    r"\b(?:the|my|our|that|this)\s+((?:[\w.+'’-]+\s+){1,4})"
    r"(?:checks?|summary|summaries|workflow|review|report|list|one)\b|"
    r"\bthe\s+(?:software\s+)?watchlist\b",
    re.IGNORECASE,
)
"""A short form of a workflow's name, as "the morning check", "the React check" or "the weekly
one"."""
ARTICLE: Final = re.compile(r"^(?:the|my|our|that|this|a|an)\s+", re.IGNORECASE)
PRONOUNS: Final = frozenset({"it", "this", "that", "them", "this one", "that one"})
NEGATIONS: Final = words("not never no dont")
PRONOUN: Final = re.compile(r"\b(?:it|them|this\s+one|that\s+one)\b", re.IGNORECASE)
"""A workflow named only as the one just talked about, as "make it daily"."""
UNREAD_TIME: Final = re.compile(
    r"\b(?:in\s+the\s+)?(?:morning|afternoon|evening|night)\b|\btonight\b|"
    r"\b(?:(?:an?|one|two|three|\d+)\s+hours?\s+)?(?:later|earlier|sooner)\b|"
    r"\bat\s+(?:\d{1,2}(?:\.\d{2})?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve)\b(?!\s*(?:am|pm|:))",
    re.IGNORECASE,
)
"""A time the schedule can't read, as "in the afternoon", "an hour later" or "at nine". The
person picks one, and it is never guessed."""
START: Final = re.compile(
    r"\b(?:from|starting|beginning|as\s+of)\s+(?:next\s+\w+|tomorrow)\b|"
    rf"\b(?:starting|beginning|as\s+of)\s+(?:on\s+)?(?:{DAY_NAMES})s?\b",
    re.IGNORECASE,
)
"""When the change should start, as "from next week", which the chat can't set: a change starts
when it is saved."""
TIME: Final = re.compile(
    r"(?<![\d.:])\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)\b|(?<![\d.:])\b\d{1,2}:\d{2}\b|"
    r"\bat\s+\d{1,2}\b(?![:.]\d)|\b(?:noon|midday|midnight)\b",
    re.IGNORECASE,
)
UNIT: Final = (
    rf"(?:(?:every|each|on|the|at)\s+)?(?:(?:{DAY_NAMES})s?|weekdays?|weekends?|day|week|daily|"
    r"weekly|\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2}|noon|midnight|\d{1,2})"
)
INSTEAD: Final = re.compile(rf"\b(?:instead\s+of|rather\s+than)\s+{UNIT}\b", re.IGNORECASE)
"""The schedule it runs on now, as "instead of every Friday"."""
FROM: Final = re.compile(rf"\bfrom\s+{UNIT}\b", re.IGNORECASE)
NOW: Final = re.compile(r"\b(?:now|currently|at\s+the\s+moment|these\s+days)\b", re.IGNORECASE)
SCHEDULE_SAID: Final = re.compile(
    rf"\b(?:{DAY_NAMES})s?\b|\bweekdays?\b|{TIME.pattern}|{FREQUENCY.pattern}", re.IGNORECASE
)
EDIT_WORDS: Final = (
    FILLER | SCHEDULE_VOCAB | EDIT_VERBS | words("runs only instead rather than o clock")
)
"""Words a clause that changes a schedule may hold beside the workflow's name and the schedule."""
STATE_KINDS: Final = ("my_workflows", "why_stopped", "needs_me")


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0).casefold(), m.start(), m.end()) for m in re.finditer(r"[^\W_]+", text)]


def _blank(text: str, spans: Iterable[Span]) -> str:
    """The text with each span turned to spaces, so every other word keeps its place."""
    out = list(text)
    for start, end in spans:
        out[start:end] = " " * (end - start)
    return "".join(out)


def _inside(span: Span, clause: Span) -> bool:
    return clause[0] <= span[0] < clause[1]


def asks(text: str, clause: Span) -> bool:
    """Whether the clause asks a question: it opens like one, or ends at a question mark, and it
    doesn't ask for something to be done, as "could it run on Tuesdays?"."""
    words_ = text[clause[0] : clause[1]]
    if TELL_ME.match(words_):
        return True
    if ORDER_LEAD.match(words_):
        return False
    return bool(QUESTION_START.match(words_) or re.match(r"\s*\?", text[clause[1] :]))


@dataclass(frozen=True)
class _Names:
    """Where the request names workflows: `all` for every name and short form, `target` for the
    words that name the workflow to change."""

    all: list[Span]
    target: Span | None

    def others(self, clause: Span) -> list[Span]:
        """The names in the clause that are not the target's."""
        t = self.target
        return [
            s
            for s in self.all
            if _inside(s, clause) and (t is None or s[1] <= t[0] or t[1] <= s[0])
        ]


def _names(read: TaskRead | None, text: str, facts: PlannerFacts | None) -> list[Span]:
    """Where the request names a workflow or a watched software: the reading's words for one,
    each workflow's whole name or a run of two or more of its words after "the", and a short form
    such as "the morning check"."""
    found: list[Span] = [m.span() for m in REFERENCE.finditer(text)]
    said = _said(read.workflow_words if read is not None else None, text)
    found += [said] if said is not None else []
    for name in _workflow_names(facts):
        found += _name_runs(text, name)
    for name in [w.name for w in (facts.watchlist if facts is not None else None) or []]:
        at = _whole(text, name)
        found += [at] if at is not None else []
    return _merged(found)


def _merged(spans: list[Span]) -> list[Span]:
    """The spans, with each run of overlapping ones made one."""
    found: list[Span] = []
    for start, end in sorted(spans):
        if found and start < found[-1][1]:
            found[-1] = (found[-1][0], max(end, found[-1][1]))
        else:
            found.append((start, end))
    return found


def _workflow_names(facts: PlannerFacts | None) -> list[str]:
    return [w.name for w in (facts.workflows if facts is not None else None) or []]


def _whole(text: str, words_: str) -> Span | None:
    wanted = visible_words(words_)
    if not wanted:
        return None
    found = re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", text, re.IGNORECASE)
    return None if found is None else found.span()


def _said(words_: str | None, text: str) -> Span | None:
    """Where the request writes the reading's words for a workflow, articles aside. "it" names
    none."""
    wanted = ARTICLE.sub("", visible_words(words_))
    if not wanted or wanted.casefold() in PRONOUNS:
        return None
    return _whole(text, wanted)


def _name_runs(text: str, name: str) -> list[Span]:
    """The stretches of the request that name a workflow: its whole name, or two or more of its
    words in a row after "the", "my" or "our", as "the weekly summary" for "Weekly closed-ticket
    summary". "a weekly summary" is a new one."""
    whole = _whole(text, name)
    if whole is not None:
        return [whole]
    own = {w for w, _, _ in _tokens(name)}
    runs: list[Span] = []
    run: list[tuple[str, int, int]] = []
    for token in [*_tokens(text), ("", len(text), len(text))]:
        if token[0] in own:
            run.append(token)
            continue
        if len(run) >= 2 and DEFINITE.search(text[: run[0][1]]):
            runs.append((run[0][1], run[-1][2]))
        run = []
    return runs


def _without_questions(text: str, rest: str) -> str:
    """`rest` with the question's own words taken out of each clause that asks one."""
    out = rest
    for clause in clauses_of(text):
        if not asks(text, clause):
            continue
        part = out[clause[0] : clause[1]]
        for pattern in (QUESTION_START, STATE_WORDS, ASKING_VERBS):
            part = pattern.sub(lambda m: " " * len(m.group(0)), part)
        if PAST.match(text[clause[0] : clause[1]]):
            part = _blank(part, [(a, b) for w, a, b in _tokens(part) if w in EDIT_VERBS])
        out = out[: clause[0]] + part + out[clause[1] :]
    return out


def left_over(read: TaskRead | None, text: str, facts: PlannerFacts | None) -> str:
    """The request with the names, the nouns, the new workflows asked for and the questions' own
    words turned to spaces: what is left to be a command."""
    new = [c for c in clauses_of(text) if NEW_WORKFLOW.match(text[c[0] : c[1]])]
    nouns = [m.span() for m in NOUN.finditer(text)]
    return _without_questions(text, _blank(text, _names(read, text, facts) + new + nouns))


def _edit_words(rest: str) -> bool:
    """A verb that changes a workflow, as "make", "pause" or "rename". A schedule beside a
    question with no such verb, as "every Friday sum up the closed tickets", is a new task."""
    tokens = [w for w, _, _ in _tokens(rest)]
    return any(
        w in EDIT_VERBS
        and not (w == "make" and tokens[at + 1 : at + 2] == ["sure"])
        and not _negated(tokens[:at])
        for at, w in enumerate(tokens)
    )


def _negated(before: list[str]) -> bool:
    """Whether the words before a verb say not to do it, as "don't" or "never"."""
    return bool(before) and (
        before[-1] in NEGATIONS or (before[-1] == "t" and before[-2:-1] in (["don"], ["doesn"]))
    )


def asks_for_a_change(read: TaskRead | None, text: str, facts: PlannerFacts | None) -> bool:
    """Whether a verb that changes a workflow is left once the question's own words and the
    names are out. A reading that calls a request a change is trusted only with one."""
    return _edit_words(left_over(read, text, facts))


def commanded(read: TaskRead | None, text: str, facts: PlannerFacts | None) -> bool:
    """Whether a change word is left once the question's own words and the names are out: a
    write, or a change to a workflow. The question lane stays closed to it."""
    rest = left_over(read, text, facts)
    return bool(
        change_verbs_in(rest)
        or commands_a_change(rest)
        or LANE_BLOCKERS.search(rest)
        or _edit_words(rest)
    )


type Switch = PauseAnswer | ResumeAnswer


def edit_of(read: TaskRead, text: str, facts: PlannerFacts | None) -> EditAnswer | Switch | None:
    """The edit a request asks for, or None. The reading calls it a change; or it asks about
    the person's workflows and a change word is left over, which fails closed to the edit; or an
    order to change one stands beside a workflow the person has, whatever the reading said. A
    watch request goes to the Software watchlist's answers instead. A pause or a resume with no
    other word of a change beside it is a pause or a resume answer."""
    if read.belongs_on_watchlist and _watch_verb(text, _names(read, text, facts)):
        return None
    if not asks_for_a_change(read, text, facts):
        return None
    if read.asks_about not in ("change", *STATE_KINDS) and not _orders_one(read, text, facts):
        return None
    target = _target(read, text, facts)
    if target is None and not PRONOUN.search(text):
        # "delete every closed ticket" changes tickets, not a workflow: it is a task's can't.
        return None
    names = _Names(_names(read, text, facts), None if target is None else _said(target, text))
    switch = _switch_of(text, names)
    if switch is not None:
        return switch(workflow_words=target, software=_software(read, text, target))
    schedule, cant, clashes = _schedule_of(text, names)
    return EditAnswer(
        workflow_words=target,
        software=_software(read, text, target),
        schedule=schedule,
        cant=cant,
        holds_save=bool(clashes) and cant is None,
    )


def _switch_of(text: str, names: _Names) -> type[Switch] | None:
    """Pause or resume, when the change holds nothing else: no schedule, no write and no word
    beyond the order itself, so "pause it for a week" stays a change the chat can't make."""
    rest = _rest(text, names)
    said = {w for w, _, _ in _tokens(rest) if w not in FILLER}
    if not said or not said <= SWITCH_WORDS:
        return None
    turned = {m.group(1).casefold() for m in TURNED.finditer(rest)}
    if "turn" in said and len(turned) != 1:
        return None
    pauses = bool(said & PAUSES) or turned == {"off"}
    resumes = bool(said & RESUMES) or turned == {"on"}
    if pauses == resumes:
        return None
    return PauseAnswer if pauses else ResumeAnswer


def switch_marks(
    read: TaskRead | None,
    text: str,
    answer: Switch,
    clauses: list[Span],
    facts: PlannerFacts | None = None,
) -> list[EditMark]:
    """The marks of a pause or a resume: the edit's own, with the order it carries out ticked
    where an edit would cross it as a change the chat can't make."""
    edit = EditAnswer(
        workflow_words=answer.workflow_words, software=answer.software, cant="only_schedule"
    )
    return [
        replace(m, mark="will_do", reason=None) if m.reason == "only_schedule" else m
        for m in edit_marks(read, text, edit, clauses, facts)
    ]


WATCH_VERB: Final = re.compile(
    r"\b(?:watch|track|monitor|keep\s+(?:track|an\s+eye|tabs))\b", re.IGNORECASE
)


def _watch_verb(text: str, names: list[Span]) -> bool:
    return WATCH_VERB.search(_blank(text, names)) is not None


def _orders_one(read: TaskRead, text: str, facts: PlannerFacts | None) -> bool:
    """Whether a clause orders a change with a verb and names one of the person's workflows, the
    workflow the reading named, or a software's check, as "make the React check run daily". A
    clause that asks for a new workflow, or a question, orders nothing."""
    named = [s for s in [_said(read.workflow_words, text)] if s is not None]
    for name in _workflow_names(facts):
        named += _name_runs(text, name)
    software = whole_word_of(text, read.software)
    named += [
        m.span()
        for m in REFERENCE.finditer(text)
        if software is not None and whole_word_of(m.group(0), software) is not None
    ]
    named += [m.span() for m in REFERENCE.finditer(text) if WATCHLIST.search(m.group(0))]
    new = [c for c in clauses_of(text) if NEW_WORKFLOW.match(text[c[0] : c[1]])]
    named = [s for s in named if not any(_inside(s, c) for c in new)]
    rest = left_over(read, text, facts)
    return any(
        not NEW_WORKFLOW.match(text[c[0] : c[1]])
        and (
            any(_inside(s, c) for s in named)
            or (bool(named) and "it" in {w for w, _, _ in _tokens(text[c[0] : c[1]])})
        )
        and any(w in EDIT_VERBS for w, _, _ in _tokens(rest[c[0] : c[1]]))
        for c in clauses_of(text)
    )


WATCHLIST: Final = re.compile(r"\bwatchlist\b", re.IGNORECASE)


def _target(read: TaskRead, text: str, facts: PlannerFacts | None) -> str | None:
    """The words that name the workflow to change, as the request wrote them: the reading's,
    else one of the person's workflow names or a run of its words, else a short form such as
    "the morning check", else the software the reading named. None for "make it daily"."""
    said = _said(read.workflow_words, text)
    runs = [r for name in _workflow_names(facts) for r in _name_runs(text, name)]
    if said is not None:
        known = [r for r in runs if r[0] <= said[0] and said[1] <= r[1]]
        start, end = max(known, key=lambda r: r[1] - r[0], default=said)
        return text[start:end]
    if runs:
        return text[runs[0][0] : runs[0][1]]
    reference = REFERENCE.search(text)
    if reference is not None:
        return ARTICLE.sub("", reference.group(0))
    return whole_word_of(text, read.software)


def _software(read: TaskRead, text: str, target: str | None) -> str | None:
    """The software the target names, as the request wrote it."""
    software = whole_word_of(text, read.software)
    if software is None or target is None or whole_word_of(target, software) is None:
        return None
    return software


TRAILING_JOIN: Final = re.compile(r"[\s,;]*(?:\b(?:and|then|also|plus)\b)?[\s,;]*$", re.IGNORECASE)


def _split(text: str, clauses: list[Span], names: _Names) -> list[Span]:
    """The clauses, each cut where it goes on to another workflow after naming a schedule for
    the target, as "Make the morning check run at 10am and the weekly summary run on Mondays"."""
    found: list[Span] = []
    for start, end in clauses:
        target = names.target
        cut = next(
            (
                other[0]
                for other in names.others((start, end))
                if target is not None
                and start <= target[0] < other[0]
                and SCHEDULE_SAID.search(text[target[1] : other[0]])
            ),
            None,
        )
        if cut is None:
            found.append((start, end))
            continue
        head = TRAILING_JOIN.search(text, start, cut)
        found += [(start, head.start() if head else cut), (cut, end)]
    return found


def change_clauses(text: str, names: _Names) -> list[Span]:
    """The clauses that hold the change: each that doesn't ask a question or for a new workflow,
    and orders one with a verb, names the workflow or says "it", or holds nothing but a schedule.
    A clause that names another workflow belongs to the change only when the target's own clause
    names no schedule, as "Make the morning check and the weekly summary run at 10am"."""
    unnamed = _blank(text, [*names.all, *(m.span() for m in TIME.finditer(text))])
    found: list[Span] = []
    elsewhere: list[Span] = []
    for clause in _split(text, clauses_of(text), names):
        if asks(text, clause) or NEW_WORKFLOW.match(text[clause[0] : clause[1]]):
            continue
        tokens = {w for w, _, _ in _tokens(unnamed[clause[0] : clause[1]])}
        target = names.target is not None and _inside(names.target, clause)
        if names.others(clause) and not target:
            elsewhere.append(clause)
        elif tokens & EDIT_VERBS or target or "it" in tokens or tokens <= EDIT_WORDS:
            found.append(clause)
    scheduled = any(SCHEDULE_SAID.search(text[a:b]) for a, b in found)
    return sorted(found + ([] if scheduled else elsewhere))


def _now(text: str, clauses: list[Span]) -> list[Span]:
    """Where the request says the schedule it runs on now: "instead of every Friday", "from
    Mondays" after a verb that moves it, as "move it from Mondays to Tuesdays", and a clause that
    says when it runs now, as "it runs on Friday now". "run from Monday to Friday" is a range."""
    found = [m.span() for m in INSTEAD.finditer(text)]
    for clause in clauses:
        words_ = {w for w, _, _ in _tokens(text[clause[0] : clause[1]])}
        if words_ & FROM_TO_VERBS:
            found += [m.span() for m in FROM.finditer(text, clause[0], clause[1])]
        elif NOW.search(text, clause[0], clause[1]) and not words_ & EDIT_VERBS:
            found.append(clause)
    return found


def _rest(text: str, names: _Names) -> str:
    """The request with all but the new schedule turned to spaces: the names, the schedule it
    runs on now, and every clause that doesn't hold the change."""
    kept = change_clauses(text, names)
    others = [c for c in _split(text, clauses_of(text), names) if c not in kept]
    start = [m.span() for m in START.finditer(text)]
    return _blank(text, [*names.all, *_now(text, kept), *others, *start])


def _writes(words_: str) -> set[str]:
    """The writes in the words, as "open a ticket" or "send it to Teams", which the chat can't
    make. They are crossed, and the schedule beside them still changes."""
    return set(change_verbs_in(words_)) - SCHEDULE_VERBS


def _unclear(answer: EditAnswer) -> bool:
    return answer.schedule is not None and answer.schedule.time_unclear


def _schedule_of(
    text: str, names: _Names
) -> tuple[ScheduleChange | None, EditCant | None, list[Clash]]:
    """The new schedule in the request's own words, in the schedule's terms. Any other change,
    as "pause it" or "rename it", and no schedule at all, are a change the chat can't make yet. A
    schedule it can't hold is a can't. Two days, two times or two frequencies are a clash, never
    the first."""
    rest = _rest(text, names)
    if OTHER_CHANGES & {w for w, _, _ in _tokens(rest)}:
        return None, "only_schedule", []
    if how_often(rest) is not None:
        return None, "how_often", []
    clashes = clashes_in(rest)
    if clashes:
        return None, None, clashes
    day, at = said_schedule(rest)
    often = {OFTEN.get(w, w) for m in FREQUENCY.finditer(rest) for w in m.groups() if w}
    weekly = day is None and "week" in often
    hour = None
    if at is not None and at.isdigit():
        hour, at = _hour(int(at))
    unclear = at is None and hour is None and UNREAD_TIME.search(rest) is not None
    if day is None and at is None and hour is None and not weekly and not unclear:
        return None, "only_schedule", []
    change = ScheduleChange(day=_day(day), weekly=weekly, at=at, hour=hour, time_unclear=unclear)
    return change, None, []


def _hour(hour: int) -> tuple[int | None, str | None]:
    """A bare hour: 1 to 12 could be morning or evening, so the person picks; 0 and 13 to 23 can
    only be one time; anything else is no time at all."""
    if 1 <= hour <= 12:
        return hour, None
    return None, (f"{hour:02d}:00" if hour <= 23 else None)


def _day(day: str | None) -> WatchDay | None:
    match day:
        case (
            "every_day"
            | "weekdays"
            | "monday"
            | "tuesday"
            | "wednesday"
            | "thursday"
            | "friday"
            | "saturday"
            | "sunday"
        ):
            return day
        case _:
            return None


def how_often(rest: str) -> Span | None:
    """Where the words ask for a schedule it can't hold, as "monthly" or "twice a week"."""
    for match in FREQUENCY.finditer(rest):
        word = (match.group(1) or match.group(2)).casefold()
        if OFTEN.get(word, word) in CANT_HOLD:
            return match.span()
    found = SO_OFTEN.search(rest)
    return None if found is None else found.span()


@dataclass(frozen=True)
class EditMark:
    """What the edit does with one stretch of the request."""

    start: int
    end: int
    mark: PartMark
    reason: PartReason | None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Edit:
    """What marking a clause of an edit needs to know of the whole request."""

    answer: EditAnswer
    names: _Names
    unnamed: str
    kept: list[Span]
    clashes: list[Clash]
    often: Span | None
    unread: list[Span]
    read: list[Span]


def edit_marks(
    read: TaskRead | None,
    text: str,
    answer: EditAnswer,
    clauses: list[Span],
    facts: PlannerFacts | None = None,
) -> list[EditMark]:
    """Each clause of a request the edit answers, marked: the change it reads, a cross on what it
    can't make or didn't follow, and a question, a task or another workflow beside it kept to ask
    on its own."""
    target = _said(answer.workflow_words, text)
    names = _Names(_names(read, text, facts) + ([target] if target else []), target)
    rest = _rest(text, names)
    kept = change_clauses(text, names)
    edit = _Edit(
        answer=answer,
        names=names,
        unnamed=_blank(text, names.all),
        kept=kept,
        clashes=clashes_in(rest) if answer.holds_save else [],
        often=how_often(rest) if answer.cant == "how_often" else None,
        unread=[
            *(m.span() for m in START.finditer(text)),
            *(m.span() for m in UNREAD_TIME.finditer(rest) if _unclear(answer)),
        ],
        read=[*names.all, *_now(text, kept), *(m.span() for m in TIME.finditer(text))],
    )
    return [
        mark
        for clause in _split(text, clauses, names)
        for mark in _clause_marks(text, clause, edit)
    ]


def _clause_marks(text: str, clause: Span, edit: _Edit) -> list[EditMark]:
    start, end = clause
    words_ = text[start:end]
    tokens = {w for w, _, _ in _tokens(edit.unnamed[start:end])}
    changes = clause in edit.kept
    if asks(text, clause) or (
        not changes and not tokens & EDIT_VERBS and STATE_WORDS.search(words_)
    ):
        return [EditMark(start, end, "cant", "ask_on_its_own")]
    scheduled = SCHEDULE_SAID.search(edit.unnamed[start:end]) is not None
    writes = _writes(edit.unnamed[start:end])
    if (
        tokens & OTHER_CHANGES
        or (writes and not scheduled)
        or (edit.answer.cant == "only_schedule" and changes)
    ):
        return [EditMark(start, end, "cant", "only_schedule")]
    if not changes:
        task = NEW_WORKFLOW.match(words_) or SCHEDULE_SAID.search(words_) or tokens & EDIT_VERBS
        task = task or edit.names.others(clause)
        return [EditMark(start, end, "cant", "ask_on_its_own" if task else "not_followed")]
    marks = [
        EditMark(max(c.start, start), min(c.end, end), "cant", c.reason, c.choices)
        for c in edit.clashes
        if c.start < end and c.end > start
    ]
    if edit.often is not None and edit.often[0] < end and edit.often[1] > start:
        marks.append(EditMark(*edit.often, "cant", "how_often"))
    for other in edit.names.others(clause):
        bare = ARTICLE.match(text[other[0] : other[1]])
        at = other[0] + (bare.end() if bare else 0)
        marks.append(EditMark(at, other[1], "cant", "ask_on_its_own"))
    marks += [EditMark(a, b, "cant", "not_followed") for a, b in edit.unread if start <= a < end]
    reads = edit.read + [(m.start, m.end) for m in marks]
    marks += [
        EditMark(a, b, "cant", "only_schedule" if _writes(text[a:b]) else "not_followed")
        for a, b in unexplained(text, clause, reads)
    ]
    return sorted(marks, key=lambda m: m.start) or [EditMark(start, end, "will_do")]


def unexplained(text: str, clause: Span, explained: list[Span]) -> list[Span]:
    """The runs of words in a clause that changes a schedule that no part of the edit reads."""
    found: list[Span] = []
    run: list[tuple[str, int, int]] = []
    tokens = [
        t
        for t in _tokens(text[clause[0] : clause[1]])
        if not any(a <= clause[0] + t[1] < b for a, b in explained)
    ]
    for word, start, end in [*tokens, ("", -1, -1)]:
        if word and (word not in EDIT_WORDS or (run and word in FILLER)):
            run.append((word, start, end))
            continue
        while run and run[-1][0] in FILLER:
            run.pop()
        if run:
            found.append((clause[0] + run[0][1], clause[0] + run[-1][2]))
        run = []
    return found
