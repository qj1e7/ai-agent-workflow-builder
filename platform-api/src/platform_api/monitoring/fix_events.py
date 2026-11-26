"""The events of one fix on a stopped run (ADR 0055, section 8). The coordinator acts behind the
AI troubleshooter's face: it hands work to the sub-agents, and to the simulation and the checker,
which are code. Each event holds only bounded fields that code chose, and code writes the summary
from them, so no words of a model reach the log. A block's name is copied from the workflow, and
stays a name whatever it says."""

import unicodedata
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, StringConstraints, model_validator

from platform_api.shared import UserId
from platform_api.wire import WireModel

MOST_ROUNDS: Final = 3
MOST_HANDOFFS: Final = 12
FIX_TIME_LIMIT: Final = timedelta(minutes=20)
"""ADR 0055, section 5: at most 3 rounds, 12 hand-offs and 20 minutes in one fix."""
MOST_BLOCKS: Final = 10
MOST_SCENARIOS: Final = 100
NAME_LIMIT: Final = 80
"""As long as the builder lets a name be, once trimmed (CreateAgentUseCase.name)."""

UNSHOWN: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})
"""Control and format characters, and line and paragraph separators: they hide text, reorder it
or break a line, so a name could pass as the platform's own words."""
QUOTES: Final = "\u201c\u201d"
"""The marks a name is shown in, so a name can't close its own quote."""


def _shown_as_written(name: str) -> str:
    if any(unicodedata.category(c) in UNSHOWN or c in QUOTES for c in name):
        raise ValueError("a name has no control, format or separator characters, and no quotes")
    if not any(unicodedata.category(c)[0] in "LNPS" for c in name):
        raise ValueError("a name has something to see")
    return name


type FixId = Annotated[str, StringConstraints(pattern=r"^fix_[0-9A-Za-z]{1,40}$")]
type ShownName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_LIMIT),
    AfterValidator(_shown_as_written),
]
"""A name people see in a sentence: a block's, or a person's."""
type FixHandedTo = Literal[
    "troubleshooter", "fix_drafter", "scenario_writer", "simulation", "checker"
]
type FixFound = Literal[
    "confirmed",
    "not_in_version",
    "not_where_it_stopped",
    "too_wide",
    "inside",
    "widened",
    "not_in_catalogue",
    "kept",
    "refused",
    "ran",
    "passed",
    "failed",
    "no_answer",
]
type FixWidening = Literal[
    "outside_failed_part",
    "adds_a_block",
    "adds_a_write",
    "adds_a_system",
    "adds_a_key",
    "removes_a_yes",
    "moves_a_yes",
    "goes_past_a_failure",
    "changes_a_persons_setting",
    "cant_check",
]
type FixHandBack = Literal[
    "no_cause",
    "no_progress",
    "no_answer",
    "widened",
    "round_limit",
    "handoff_limit",
    "cost_limit",
    "time_limit",
    "gave_up",
    "not_replayed",
]

FOUND_BY: Final[Mapping[FixHandedTo, frozenset[FixFound]]] = {
    "troubleshooter": frozenset(
        {"confirmed", "not_in_version", "not_where_it_stopped", "too_wide", "no_answer"}
    ),
    "fix_drafter": frozenset({"inside", "widened", "not_in_catalogue", "no_answer"}),
    "scenario_writer": frozenset({"kept", "refused", "no_answer"}),
    "simulation": frozenset({"ran", "no_answer"}),
    "checker": frozenset({"passed", "failed"}),
}
"""What code can find of each one's work."""


class FixStartedData(WireModel):
    fix_id: FixId
    asked_by: UserId
    asked_by_name: ShownName
    ends_by: AwareDatetime = Field(
        description="When the fix counts as handed back for time if nothing ended it: at most 20 "
        "minutes after the press of the button."
    )


class FixHandoffData(WireModel):
    fix_id: FixId
    handoff: int = Field(ge=1, le=MOST_HANDOFFS, description="Its number in the fix, from 1.")
    to: FixHandedTo
    blocks: list[ShownName] = Field(
        default_factory=list[str],
        max_length=MOST_BLOCKS,
        description="For the AI troubleshooter, the failed part it named, only once code found "
        "each block in the version, and for the Fix drafter, the failed part it may change. Each "
        "block once. Empty for the others, and for the AI troubleshooter when it named a block "
        "the version doesn't have or gave no answer.",
    )
    found: FixFound = Field(description="What code found of the work that came back.")
    widened_by: FixWidening | None = Field(
        default=None, description="How the Fix drafter's change went too far, when it did."
    )
    passed: int | None = Field(default=None, ge=0, description="When the simulation ran.")
    scenarios: int | None = Field(
        default=None, ge=1, le=MOST_SCENARIOS, description="When the simulation ran."
    )

    @model_validator(mode="after")
    def _fits(self) -> Self:
        if self.found not in FOUND_BY[self.to]:
            raise ValueError(f"{self.found} isn't something code finds of {self.to}")
        named = self.to == "fix_drafter" or self.found in ("confirmed", "not_where_it_stopped")
        if named != bool(self.blocks):
            raise ValueError("blocks name the failed part, only for the hand-offs about it")
        if len(set(self.blocks)) != len(self.blocks):
            raise ValueError("each block is named once")
        if (self.found == "widened") != (self.widened_by is not None):
            raise ValueError("widened_by says how a widened change went too far, and only that")
        if self.found != "ran":
            if self.passed is not None or self.scenarios is not None:
                raise ValueError("passed and scenarios count a simulation that ran, and only that")
        elif self.passed is None or self.scenarios is None or self.passed > self.scenarios:
            raise ValueError("a simulation that ran says how many scenarios ran and passed")
        return self


class FixRoundData(WireModel):
    fix_id: FixId
    round: int = Field(ge=1, le=MOST_ROUNDS)
    passed: int = Field(ge=0)
    scenarios: int = Field(ge=1, le=MOST_SCENARIOS, description="The scenarios that apply.")
    progress: bool = Field(
        description="More scenarios passed than in the round before, and none that passed fails."
    )

    @model_validator(mode="after")
    def _fits(self) -> Self:
        if self.passed > self.scenarios:
            raise ValueError("more scenarios passed than ran")
        return self


class FixProposedData(WireModel):
    fix_id: FixId
    version: int = Field(ge=1, description="The fixed version, which waits for approval.")
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class FixHandedBackData(WireModel):
    fix_id: FixId
    why: FixHandBack


type FixData = FixStartedData | FixHandoffData | FixRoundData | FixProposedData | FixHandedBackData

FIX_KINDS: Final[Mapping[type[WireModel], str]] = {
    FixStartedData: "fix_started",
    FixHandoffData: "fix_handoff",
    FixRoundData: "fix_round",
    FixProposedData: "fix_proposed",
    FixHandedBackData: "fix_handed_back",
}


def fix_kind(data: FixData) -> str:
    return FIX_KINDS[type(data)]


def fix_dedupe_key(data: FixData) -> str:
    """One event for each step of a fix, so a repeat writes nothing."""
    match data:
        case FixStartedData():
            return f"fix:{data.fix_id}:started"
        case FixHandoffData():
            return f"fix:{data.fix_id}:handoff:{data.handoff}"
        case FixRoundData():
            return f"fix:{data.fix_id}:round:{data.round}"
        case FixProposedData():
            return f"fix:{data.fix_id}:proposed"
        case FixHandedBackData():
            return f"fix:{data.fix_id}:handed_back"


WIDENED: Final[Mapping[FixWidening, str]] = {
    "outside_failed_part": "changes a block outside the failed part",
    "adds_a_block": "adds a block",
    "adds_a_write": "adds a write",
    "adds_a_system": "adds a system",
    "adds_a_key": "adds a key",
    "removes_a_yes": "removes an approval step",
    "moves_a_yes": "moves an approval step",
    "goes_past_a_failure": "lets a block go past a failure",
    "changes_a_persons_setting": "changes a setting a person filled in",
    "cant_check": "is one the platform can't check",
}

HANDED_BACK: Final[Mapping[FixHandBack, str]] = {
    "no_cause": "The cause couldn't be confirmed.",
    "no_progress": "A round made no progress.",
    "no_answer": "The Fix drafter didn't answer.",
    "widened": "The change went further than the failed part.",
    "round_limit": f"I reached the limit of {MOST_ROUNDS} rounds.",
    "handoff_limit": f"I reached the limit of {MOST_HANDOFFS} hand-offs.",
    "cost_limit": "I reached the cost limit for one fix.",
    "time_limit": "I reached the time limit for one fix.",
    "gave_up": "I found no change that works.",
    "not_replayed": "The practice systems couldn't replay the stop, so no fix could be proven.",
}


def _blocks(names: Sequence[str]) -> str:
    """The blocks by name, each in quotes, so a name never reads as the platform's words."""
    *before, last = [f"\u201c{name}\u201d" for name in names]
    joined = f"{', '.join(before)} and {last}" if before else last
    return f"the {joined} block{'s' if before else ''}"


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _handoff_words(data: FixHandoffData) -> str:
    match data.to, data.found:
        case "troubleshooter", "confirmed":
            return (
                f"I found the cause in {_blocks(data.blocks)}, and the platform checked the run "
                "stopped there."
            )
        case "troubleshooter", "not_where_it_stopped":
            return f"I named {_blocks(data.blocks)}, but the run didn't stop there."
        case "troubleshooter", "not_in_version":
            return "I named a block that isn't in this workflow, so the platform didn't use it."
        case "troubleshooter", "too_wide":
            return (
                f"I named more than {MOST_BLOCKS} blocks, too many for one fix, so the platform "
                "didn't use them."
            )
        case "troubleshooter", _:
            return "I looked for the cause, but got no answer."
        case "fix_drafter", found:
            asked = f"I asked the Fix drafter to change only {_blocks(data.blocks)}"
            if found == "inside":
                return f"{asked}. The platform checked the change stays inside the failed part."
            if found == "widened" and data.widened_by is not None:
                how = WIDENED[data.widened_by]
                return f"{asked}, but its change {how}, so the platform refused it."
            if found == "not_in_catalogue":
                return f"{asked}, but its change uses a block the platform can't run."
            return f"{asked}, but it didn't answer."
        case "scenario_writer", "kept":
            return (
                "I asked the Scenario writer for scenarios, and the platform checked they fit "
                "this workflow."
            )
        case "scenario_writer", "refused":
            return "I asked the Scenario writer for scenarios, but they didn't fit this workflow."
        case "scenario_writer", _:
            return "I asked the Scenario writer for scenarios, but it didn't answer."
        case "simulation", "ran" if data.passed is not None and data.scenarios is not None:
            ran = _count(data.scenarios, "scenario")
            return f"I ran {ran} in the simulation, and {data.passed} passed."
        case "simulation", _:
            return "I tried to run the scenarios in the simulation, but it didn't answer."
        case "checker", "passed":
            return "The platform checked the fixed version, and it passed."
        case _:
            return "The platform checked the fixed version, and it didn't pass."


def fix_summary(data: FixData) -> str:
    """The plain sentence for the activity log, as the AI troubleshooter says it, from the fields
    only."""
    match data:
        case FixStartedData():
            return f"{data.asked_by_name} asked for a fix."
        case FixHandoffData():
            return _handoff_words(data)
        case FixRoundData():
            of = _count(data.scenarios, "scenario")
            passed = f"Round {data.round}: {data.passed} of {of} passed"
            if data.round == 1:
                return f"{passed}."
            return f"{passed}, {'more than' if data.progress else 'no better than'} before."
        case FixProposedData():
            return (
                f"A fix is ready as version {data.version}. Nothing changes until an Approver "
                "approves it."
            )
        case FixHandedBackData():
            return f"I couldn't fix this. {HANDED_BACK[data.why]} Nothing was changed."


# What happens to a fix after it is handed in (ADR 0055, section 8): the decision with the
# Approver, and how its test run went. A person or the platform writes these, never the
# coordinator, after the fix's own events have ended.

type ApprovalIdText = Annotated[str, StringConstraints(pattern=r"^apr_[0-9A-Za-z]{1,40}$")]
type RunIdText = Annotated[str, StringConstraints(pattern=r"^run_[0-9A-Za-z]{1,40}$")]
type FixVerdict = Literal["approved", "declined"]
type FixTriedResult = Literal["turned_on", "kept_paused", "test_failed", "not_put_live"]


class FixDecidedData(WireModel):
    """An Approver's approve or decline on a fix's set-up approval."""

    fix_id: FixId
    approval_id: ApprovalIdText
    verdict: FixVerdict
    by: UserId
    by_name: ShownName
    reason: ShownName | None = Field(
        default=None, description="Why the Approver said no, from the short list."
    )


class FixTriedData(WireModel):
    """How the one real test run of a fix went, and what that did to the workflow."""

    fix_id: FixId
    approval_id: ApprovalIdText
    approved_by: UserId
    approved_by_name: ShownName
    pressed_by: UserId = Field(description="Who pressed Turn back on.")
    result: FixTriedResult
    test_run_id: RunIdText | None = None


type FixOutcomeData = FixDecidedData | FixTriedData

TRIED: Final[Mapping[FixTriedResult, str]] = {
    "turned_on": "The fix passed its test run, so the workflow is back on with it.",
    "kept_paused": "The fix passed its test run and is saved. The workflow stays paused.",
    "test_failed": "The fix's test run didn't pass, so the workflow stays as it was.",
    "not_put_live": (
        "The fix passed its test run, but the platform couldn't put it live. The workflow stays "
        "as it was."
    ),
}


def fix_outcome_kind(data: FixOutcomeData) -> str:
    return "fix_decided" if isinstance(data, FixDecidedData) else "fix_tried"


def fix_outcome_key(data: FixOutcomeData) -> str:
    return f"fix:{data.fix_id}:{'decided' if isinstance(data, FixDecidedData) else 'tried'}"


def fix_outcome_summary(data: FixOutcomeData) -> str:
    match data:
        case FixDecidedData(verdict="approved"):
            return f"{data.by_name} approved the fix."
        case FixDecidedData():
            reason = f": {data.reason}" if data.reason else ""
            return f"{data.by_name} said no to the fix{reason}. The workflow stays as it was."
        case FixTriedData():
            return f"{TRIED[data.result]} {data.approved_by_name} approved it."
