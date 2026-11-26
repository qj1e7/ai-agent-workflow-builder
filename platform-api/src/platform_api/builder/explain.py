import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field, ValidationError

from platform_api.builder.workflow_report import (
    CHANGES_NOTHING,
    CHANGES_NOTHING_ELSE,
    NOTHING_STARTS,
    SOMEONE_STARTS,
    UNSHOWN_SCHEDULE,
    AtSetUp,
    CantRunYet,
    EachRun,
    Quoted,
    Refused,
    Touch,
    Words,
    WorkflowReport,
    WriteApproval,
)
from platform_api.orchestration import (
    ApproverMayAccept,
    CantRun,
    Clears,
    CodeWording,
    ExplainFact,
    ExplainWordingResult,
    FixedForYou,
    Grade,
    NeedsAnAnswer,
    NeedsASetting,
    NoModel,
    RuntimeDown,
)
from platform_api.wire import WireModel


class Segment(WireModel):
    text: str
    quoted: bool = Field(
        description="A string from the plan or the document, such as a block's name or a "
        "notice's words. Show it in quotes, apart from code's own words."
    )


class ExplainStep(WireModel):
    name: str
    ours: bool = Field(description="A block of our node pack. False for one of n8n's own.")
    tag: str = Field(description="What it does, such as Reads Jira or Writes after approval.")


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
        description="each_run: Approvers approve it on each run. set_up: it runs on the set-up "
        "approval, with no approval on each run. refused: nothing asks for approval before it, "
        "so the platform refuses the write. cant_run_yet: no approval lets it run on this "
        "platform yet."
    )
    approvers: int | None = Field(
        description="How many Approvers approve on each run, one after the other. Null unless "
        "each_run."
    )
    words: str


class ExplainSetting(WireModel):
    label: list[Segment]
    value: list[Segment] | None = Field(description="Null while it is needed.")
    mark: Literal["filled", "guessed", "needed", "set"]
    said: str = Field(description="Where it was set, or its mark, in words to show.")


class WorkflowExplained(WireModel):
    """A drafted workflow or a fix, explained from the report code builds, as its card and its
    set-up approval show it. In in_short, phrase, label and value, each string from the plan or
    the document is a quoted segment, so a block named "Security approved" can't read as code's
    verdict."""

    use_case_id: str
    name: str
    grade: Grade = Field(description="The safety checker's grade under today's rules.")
    in_short: list[Segment] = Field(
        description="One or two sentences in code's own words: when it runs, what it reads, what "
        "it changes or posts, and what waits for approval."
    )
    reworded: str | None = Field(
        description="In short as the AI model smoothed it, when asked with reworded=true and it "
        "passed every check. Null otherwise."
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
class TooLongToSmooth:
    pass


def view_of(
    report: WorkflowReport, use_case_id: str, name: str, reworded: str | None = None
) -> WorkflowExplained:
    return WorkflowExplained(
        use_case_id=use_case_id,
        name=name,
        grade=report.grade,
        in_short=segments(report.in_short),
        reworded=reworded,
        steps=[ExplainStep(name=s.name.text, ours=s.ours, tag=s.tag) for s in report.steps],
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
AFTER_APPROVAL = "after approval"


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
    approved = ["approval"] if AFTER_APPROVAL in code else []
    together = [*_verbs(phrase), *system, *quoted, *approved]
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


class Wordings(Protocol):
    async def reword(self, asked: CodeWording) -> ExplainWordingResult | NoModel | RuntimeDown: ...
