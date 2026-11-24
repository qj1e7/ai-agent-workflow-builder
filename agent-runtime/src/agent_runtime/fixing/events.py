"""The events of one fix, as platform-api's activity log takes them (ADR 0055, section 8).

The coordinator hands each event to a `FixRecorder`, the port to platform-api's
`ActivityLog.note_fix`. These models hold the same fields, limits and checks as platform-api's
`monitoring/fix_events.py`, one for one, and a contract test holds their JSON schema to
contracts/activity-event.schema.json. So an event that leaves here is one the log can take, and
one that can't be made here, such as a block whose name the log can't show, never leaves. The log
may still refuse an event for the reasons in `FixRefusal`."""

import unicodedata
from collections.abc import Mapping
from datetime import timedelta
from typing import Annotated, Final, Literal, Protocol, Self

from pydantic import AfterValidator, AwareDatetime, Field, StringConstraints, model_validator

from agent_runtime.contract import WireModel

MOST_ROUNDS: Final = 3
MOST_HANDOFFS: Final = 12
FIX_TIME_LIMIT: Final = timedelta(minutes=20)
"""ADR 0055, section 5: at most 3 rounds, 12 hand-offs and 20 minutes in one fix."""
MOST_BLOCKS: Final = 10
MOST_SCENARIOS: Final = 100
NAME_LIMIT: Final = 80

UNSHOWN: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})
"""Control and format characters, and line and paragraph separators."""
QUOTES: Final = "“”"
"""The marks platform-api shows a name in, so a name can't close its own quote."""


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
type FixHandedTo = Literal[
    "troubleshooter", "fix_drafter", "scenario_writer", "simulation", "checker"
]
type FixFound = Literal[
    "confirmed",
    "not_in_version",
    "not_where_it_stopped",
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
]
type FixHandBack = Literal[
    "no_cause",
    "no_progress",
    "widened",
    "round_limit",
    "handoff_limit",
    "cost_limit",
    "time_limit",
    "gave_up",
]

FOUND_BY: Final[Mapping[FixHandedTo, frozenset[FixFound]]] = {
    "troubleshooter": frozenset(
        {"confirmed", "not_in_version", "not_where_it_stopped", "no_answer"}
    ),
    "fix_drafter": frozenset({"inside", "widened", "not_in_catalogue", "no_answer"}),
    "scenario_writer": frozenset({"kept", "refused", "no_answer"}),
    "simulation": frozenset({"ran", "no_answer"}),
    "checker": frozenset({"passed", "failed"}),
}


class FixStartedData(WireModel):
    fix_id: FixId
    asked_by: str
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
    version: int = Field(ge=1, description="The fixed version, which waits for a yes.")
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


type FixRefusal = Literal[
    "not_stopped", "another_fix", "not_started", "ended", "deadline", "conflict"
]
"""platform-api's `FixRefused.why`: the run isn't stopped, another fix runs on it, this fix never
started at this stop, it already ended or ran out of time, a start's deadline isn't within 20
minutes, or this step was written before with other data."""


class FixRecorder(Protocol):
    """Writes one event of a fix on the stopped run, or says why the log took none."""

    def note(self, data: FixData) -> FixRefusal | None: ...
