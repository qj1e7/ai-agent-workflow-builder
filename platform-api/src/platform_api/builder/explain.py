import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError

from platform_api.builder.card_store import CardLibrary
from platform_api.builder.models import CardView
from platform_api.builder.versions import NoSuchVersion, Version, authors_of, versions_of
from platform_api.builder.workflow_report import (
    CHANGES_NOTHING,
    CHANGES_NOTHING_ELSE,
    NOTHING_STARTS,
    SOMEONE_STARTS,
    UNSHOWN_SCHEDULE,
    AtSetUp,
    CantRunYet,
    EachRun,
    Older,
    Quoted,
    Refused,
    SetUp,
    Team,
    Touch,
    Words,
    WorkflowReport,
    WriteApproval,
    workflow_report,
)
from platform_api.db import Database
from platform_api.orchestration import (
    ApproverMayAccept,
    CantRun,
    Clears,
    CodeWording,
    ExplainFact,
    ExplainReworded,
    ExplainWordingResult,
    FixedForYou,
    Grade,
    ModelProblem,
    NeedsAnAnswer,
    NeedsASetting,
    NoModel,
    RuntimeDown,
    Unreadable,
    read_flow,
)
from platform_api.shared import Principal
from platform_api.wire import WireModel

log = logging.getLogger(__name__)

NOTHING_TO_EXPLAIN = (
    "Nothing to explain: this version ran on the shared n8n workflow, so the platform kept no "
    "copy of its blocks."
)


class Segment(WireModel):
    text: str
    quoted: bool = Field(
        description="A string from the plan or the document, such as a block's name or a "
        "notice's words. Show it in quotes, apart from code's own words."
    )


class ExplainStep(WireModel):
    name: str
    ours: bool = Field(description="A block of our node pack. False for one of n8n's own.")
    block_type: str | None = Field(
        description="n8n's type of the block. Null unless you have n8n access."
    )
    tag: str = Field(description="What it does, such as Reads Jira or Writes after a yes.")


class ExplainTouch(WireModel):
    action: Literal["reads", "writes", "posts"]
    system: str | None = Field(description="Null when code can't tell which system.")
    place: str | None = Field(
        description="Where, as the plan or the document names it. Null when nothing names it or "
        "the run's data picks it."
    )
    block: str = Field(description="The block that does it.")
    phrase: list[Segment] = Field(description='What it does, as In short says it after "It".')
    key: str | None = Field(
        description="Which of the platform's keys one of n8n's blocks uses, never its secret."
    )


type ClearedBy = Literal[
    "fixed_for_you", "needs_an_answer", "needs_a_setting", "cant_run", "approver_may_accept"
]


class ExplainFlag(WireModel):
    rule: str
    block: str | None = Field(description="The block that breaks it. Null for the whole workflow.")
    what: str
    why: str
    clears: ClearedBy = Field(
        description="fixed_for_you: code puts it right whenever it lays a workflow out. "
        "needs_an_answer: the person setting it up answers it. needs_a_setting: an Operator fixes "
        "it in Settings or the agent library. cant_run: nobody can clear it in the app. "
        "approver_may_accept: an Approver may accept it at set-up."
    )
    takes: str = Field(description="Who can clear it, in words to show.")


class ExplainCleared(WireModel):
    rule: str
    words: str


class ExplainWrite(WireModel):
    block: str
    decides: Literal["each_run", "set_up", "refused", "cant_run_yet"] = Field(
        description="each_run: Approvers say yes on each run. set_up: it runs on the set-up "
        "approval, with no yes on each run. refused: no yes comes before it, so the platform "
        "refuses the write. cant_run_yet: no approval lets it run on this platform yet."
    )
    approvers: int | None = Field(
        description="How many Approvers say yes on each run, one after the other. Null unless "
        "each_run."
    )
    words: str


class ExplainSetting(WireModel):
    label: list[Segment]
    value: list[Segment] | None = Field(description="Null while it is needed.")
    mark: Literal["filled", "guessed", "needed", "set"]
    said: str = Field(description="Where it was set, or its mark, in words to show.")


class ExplainThen(WireModel):
    number: int
    grade: Grade = Field(description="The grade it had when it was published.")


class WorkflowExplained(WireModel):
    """One version of a workflow, explained from the report code builds. In in_short, phrase,
    label and value, each string from the plan or the document is a quoted segment, so a block
    named "Security approved" can't read as code's verdict."""

    use_case_id: str
    name: str
    version: int | None = Field(description="Null for a draft, which has no published version.")
    grade: Grade = Field(description="The safety checker's grade under today's rules.")
    then: ExplainThen | None = Field(
        description="An older version's number and the grade it had when it was published. Null "
        "for the version in use and for a draft."
    )
    in_short: list[Segment] = Field(
        description="One or two sentences in code's own words: when it runs, what it reads, what "
        "it changes or posts, and what waits for a yes."
    )
    reworded: str | None = Field(
        description="In short as the AI model smoothed it, when asked with reworded=true and it "
        "passed every check. Show it labelled Reworded, with a way back to in_short. Null "
        "otherwise."
    )
    steps: list[ExplainStep] = Field(description="Each block in run order.")
    touches: list[ExplainTouch] = Field(description="What it reads, writes and posts.")
    flags: list[ExplainFlag] = Field(description="Each rule a block breaks, in the rules' order.")
    fixed: list[ExplainCleared] = Field(
        description="What code made sure of when it laid the workflow out."
    )
    passed: list[ExplainCleared] = Field(description="Every other rule no block breaks.")
    approves: list[ExplainWrite] = Field(description="Who decides each write.")
    settings: list[ExplainSetting]
    approval: str = Field(description="Whether its set-up needed an approval, in words to show.")
    needs_an_answer: int = Field(description="The questions left to answer.")


@dataclass(frozen=True)
class NoSuchWorkflow:
    pass


@dataclass(frozen=True)
class NothingToExplain:
    pass


@dataclass(frozen=True)
class TooLongToSmooth:
    pass


type Explained = WorkflowExplained | NoSuchWorkflow | NoSuchVersion | NothingToExplain


def view_of(
    report: WorkflowReport,
    use_case_id: str,
    name: str,
    version: int | None,
    n8n_access: bool,
    reworded: str | None = None,
) -> WorkflowExplained:
    then = report.then
    return WorkflowExplained(
        use_case_id=use_case_id,
        name=name,
        version=version,
        grade=report.grade,
        then=None if then is None else ExplainThen(number=then.number, grade=then.grade),
        in_short=segments(report.in_short),
        reworded=reworded,
        steps=[
            ExplainStep(
                name=s.name.text,
                ours=s.ours,
                block_type=s.block_type.text if n8n_access else None,
                tag=s.tag,
            )
            for s in report.steps
        ],
        touches=[_touch(t) for t in report.touches],
        flags=[
            ExplainFlag(
                rule=f.rule,
                block=None if f.block is None else f.block.text,
                what=f.what,
                why=f.why,
                clears=_cleared_by(f.clears),
                takes=f.takes,
            )
            for f in report.flags
        ],
        fixed=[ExplainCleared(rule=c.rule, words=c.words) for c in report.fixed],
        passed=[ExplainCleared(rule=c.rule, words=c.words) for c in report.passed],
        approves=[_write(a) for a in report.approves],
        settings=[
            ExplainSetting(
                label=segments(s.label),
                value=None if s.value is None else segments(s.value),
                mark=s.mark,
                said=s.said,
            )
            for s in report.settings
        ],
        approval=report.approval,
        needs_an_answer=report.needs_an_answer,
    )


def segments(words: Words) -> list[Segment]:
    return [
        Segment(text=w.text, quoted=True)
        if isinstance(w, Quoted)
        else Segment(text=w, quoted=False)
        for w in words
    ]


def _touch(touch: Touch) -> ExplainTouch:
    return ExplainTouch(
        action=touch.action,
        system=touch.system,
        place=None if touch.place is None else touch.place.text,
        block=touch.block.text,
        phrase=segments(touch.phrase),
        key=touch.key,
    )


def _cleared_by(clears: Clears) -> ClearedBy:
    match clears:
        case FixedForYou():
            return "fixed_for_you"
        case NeedsAnAnswer():
            return "needs_an_answer"
        case NeedsASetting():
            return "needs_a_setting"
        case CantRun():
            return "cant_run"
        case ApproverMayAccept():
            return "approver_may_accept"


def _write(write: WriteApproval) -> ExplainWrite:
    count: int | None = None
    match write.decides:
        case EachRun(approvers):
            decides, count = "each_run", approvers
        case AtSetUp():
            decides = "set_up"
        case Refused():
            decides = "refused"
        case CantRunYet():
            decides = "cant_run_yet"
    return ExplainWrite(block=write.block.text, decides=decides, approvers=count, words=write.words)


def wording_of(in_short: Words) -> str:
    return "".join(f"“{w.text}”" if isinstance(w, Quoted) else w for w in in_short)


_WORD = re.compile(r"[\w'’]+")
_DAY_AND_TIME = re.compile(r"Every (\S+) at (\d{1,2}:\d{2})")
START_WORDS: Mapping[str, str] = {
    UNSHOWN_SCHEDULE: "schedule",
    SOMEONE_STARTS: "starts",
    NOTHING_STARTS: "starts",
}
NEGATIONS = frozenset({"not", "no", "never", "nothing", "none", "nor", "cannot", "without"})
MODALS = frozenset({"can", "could", "would"})
BASE: Mapping[str, str] = {"posts": "post", "tells": "tell"}
AFTER_A_YES = "after a yes"


def explain_facts(report: WorkflowReport) -> list[ExplainFact]:
    in_short = report.in_short
    facts: list[ExplainFact] = []
    match in_short[:1]:
        case (str(when),) if (said := _DAY_AND_TIME.fullmatch(when)) is not None:
            facts.append(ExplainFact(kind="runs", together=[said[1], said[2]], negated=False))
        case (str(when),) if when in START_WORDS:
            facts.append(_fact("runs", [START_WORDS[when]], when))
        case _:
            pass
    for system, place in dict.fromkeys(
        (t.system, t.place) for t in report.touches if t.action == "reads"
    ):
        named = ["reads", *([system] if system else []), *([place.text] if place else [])]
        facts.append(ExplainFact(kind="reads", together=named, negated=False))
    phrases: dict[Words, Touch] = {}
    for touch in report.touches:
        if touch.action != "reads":
            phrases.setdefault(touch.phrase, touch)
    facts += [_phrase_fact(touch) for touch in phrases.values()]
    match in_short[-1:]:
        case (str(closing),) if closing in (CHANGES_NOTHING_ELSE, CHANGES_NOTHING):
            facts.append(_fact("changes", _WORD.findall(closing)[1:], closing))
        case _:
            pass
    return facts


def _fact(kind: Literal["runs", "changes"], together: list[str], said: str) -> ExplainFact:
    return ExplainFact(kind=kind, together=together, negated=_negated(said))


def _phrase_fact(touch: Touch) -> ExplainFact:
    phrase = touch.phrase
    code = "".join(w for w in phrase if isinstance(w, str))
    words = set(_WORD.findall(code))
    system = [w for w in _WORD.findall(touch.system or "") if w in words and w != "and"]
    quoted = dict.fromkeys(w.text for w in phrase if isinstance(w, Quoted))
    together = [*_verbs(phrase), *system, *quoted, *(["yes"] if AFTER_A_YES in code else [])]
    action: Literal["writes", "posts"] = "posts" if touch.action == "posts" else "writes"
    return ExplainFact(kind=action, together=together, negated=_negated(code))


def _verbs(phrase: Words) -> list[str]:
    opening = next((w for w in phrase if isinstance(w, str)), "")
    words = _WORD.findall(opening)
    at = 1 if words[:1] and words[0] in MODALS else 0
    if at >= len(words):
        return []
    verbs = [words[at]]
    while at + 2 < len(words) and words[at + 1] == "or":
        at += 2
        verbs.append(words[at])
    return [BASE.get(v, v) for v in verbs]


def _negated(said: str) -> bool:
    return any(
        w.lower() in NEGATIONS or w.lower().endswith(("n't", "n’t")) for w in _WORD.findall(said)
    )


def to_smooth(report: WorkflowReport) -> CodeWording | TooLongToSmooth:
    try:
        return CodeWording(wording=wording_of(report.in_short), facts=explain_facts(report))
    except ValidationError:
        return TooLongToSmooth()


class Grading(Protocol):
    async def todays_rules(self) -> Team: ...


class Wordings(Protocol):
    async def reword(self, asked: CodeWording) -> ExplainWordingResult | NoModel | RuntimeDown: ...


_WORKFLOW = """
    SELECT u.current_version, u.draft, u.made_in_n8n_by, v.name
    FROM builder.use_cases u
    JOIN builder.use_case_versions v
      ON v.use_case_id = u.use_case_id AND v.version = u.current_version
    WHERE u.use_case_id = %s AND u.deleted_at IS NULL
"""


class Explainer:
    def __init__(self, db: Database, grading: Grading, wordings: Wordings) -> None:
        self._db = db
        self._grading = grading
        self._wordings = wordings
        self._cards = CardLibrary(db)

    async def explain(
        self,
        use_case_id: str,
        viewer: Principal,
        version: int | None = None,
        reworded: bool = False,
    ) -> Explained:
        async with self._db.connection("builder") as conn:
            row = await (await conn.execute(_WORKFLOW, (use_case_id,))).fetchone()
            if row is None:
                return NoSuchWorkflow()
            versions = await versions_of(conn, use_case_id)
        draft, current = bool(row["draft"]), int(row["current_version"])
        asked = current if version is None else version
        found = next((v for v in versions if v.number == asked), None)
        if found is None or (draft and version is not None):
            return NoSuchVersion()
        if found.held is None:
            return NothingToExplain()
        laid = SetUp(
            _laid_by(found, row["made_in_n8n_by"] is not None),
            found.held.document,
            await self._pinned_or_newest_cards(use_case_id, found.number, found.held.document),
        )
        source = laid if asked == current else Older(laid, asked, found.held.grade)
        report = workflow_report(source, await self._grading.todays_rules())
        return view_of(
            report,
            use_case_id,
            str(row["name"]),
            None if draft else asked,
            viewer.n8n_access,
            await self._reworded(report) if reworded else None,
        )

    async def _pinned_or_newest_cards(
        self, use_case_id: str, version: int, document: Mapping[str, Any]
    ) -> dict[str, CardView]:
        pinned = await self._cards.agents_of([(use_case_id, version)])
        cards = {a.card.card_id: a.card for a in pinned.get((use_case_id, version), [])}
        for card_id in _agents_named(document):
            if card_id not in cards and (card := await self._cards.get(card_id)) is not None:
                cards[card_id] = card
        return cards

    async def _reworded(self, report: WorkflowReport) -> str | None:
        asked = to_smooth(report)
        if isinstance(asked, TooLongToSmooth):
            return None
        match await self._wordings.reword(asked):
            case ExplainReworded(text=text):
                return text
            case RuntimeDown(detail=detail):
                log.warning("Explain kept code's wording: %s", detail)
            case ModelProblem(reason=reason):
                log.warning("Explain kept code's wording: the model's answer was %s", reason)
            case _:
                pass
        return None


def _agents_named(document: Mapping[str, Any]) -> Sequence[str]:
    try:
        flow = read_flow(document)
    except Unreadable:
        return []
    return [str(b.parameters.get("agent")) for b in flow.of_kind("agent")]


def _laid_by(version: Version, made_in_n8n: bool) -> Literal["planner", "n8n"]:
    saved_there = version.made is not None and version.made.kind == "settings_changed_in_n8n"
    by_n8n = any(a.where == "n8n" for a in authors_of(version))
    return "n8n" if made_in_n8n or saved_there or by_n8n else "planner"
