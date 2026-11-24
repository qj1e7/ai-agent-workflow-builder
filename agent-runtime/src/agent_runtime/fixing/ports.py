"""What the coordinator hands work to (ADR 0055, section 3), each behind a port.

The AI troubleshooter, the Fix drafter and the Scenario writer are sub-agents. The simulation, the
scope check, the checker and the store of revisions are code. In PR 3 each one is a fake: the Fix
drafter and the scope check join in PR 4, and the simulation and the checker in PR 5. None of them
writes to a real system or a live workflow. Each takes data and gives data back, and the
coordinator's code checks what comes back before the model reads it."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import Field, JsonValue, StringConstraints

from agent_runtime.contract import CauseFound, WireModel, WorkflowPlan
from agent_runtime.fixing.events import FixRecorder, FixWidening

type ScenarioName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]


class Scenario(WireModel):
    """A situation to try a version in (ADR 0054), as the Scenario writer wrote it: how each
    block that reads, and each Agent block, is served. The plays are the simulation's to read.
    Code checks only that each block it names is a block of the version."""

    name: ScenarioName
    reads: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue], max_length=100)
    agents: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue], max_length=100)

    def blocks(self) -> set[str]:
        return {*self.reads, *self.agents}


type Verdict = Literal["passed", "failed", "not_tried"]


class ScenarioResult(WireModel):
    """One scenario's grade, as the simulation's grader gives it. A scenario that is not tried
    doesn't apply."""

    name: str
    verdict: Verdict
    step: str | None = Field(default=None, description="The block where it failed, if it did.")
    why: str | None = Field(default=None, max_length=40, description="The grader's reason code.")


class Simulated(WireModel):
    results: list[ScenarioResult]
    not_reached: list[str] = Field(
        default_factory=list[str], description="Blocks no scenario reached: a gap in coverage."
    )


@dataclass(frozen=True)
class FixDraftRequest:
    """One round's ask of the Fix drafter: change only `change_only`, inside the failed part of
    the stopped version, with the scenarios that failed in the round before and why."""

    stopped: WorkflowPlan
    cause: CauseFound
    change_only: tuple[str, ...]
    failed: tuple[ScenarioResult, ...]
    round: int


type NotDrafted = Literal["not_in_catalogue", "no_answer"]


@dataclass(frozen=True)
class Inside:
    """The change stays inside the failed part. `changed` names the blocks it changed."""

    changed: tuple[str, ...]


@dataclass(frozen=True)
class Widened:
    by: FixWidening


type Scope = Inside | Widened


@dataclass(frozen=True)
class StoredRevision:
    version: int
    digest: str


class Troubleshooter(Protocol):
    """Names the cause and the failed part of the stopped run, or looks again at one block."""

    def find_cause(self, look_at: str | None) -> CauseFound | None: ...


class FixDrafter(Protocol):
    def draft(self, request: FixDraftRequest) -> WorkflowPlan | NotDrafted: ...


class ScenarioWriter(Protocol):
    """Writes scenarios for the version, or more that reach the blocks in `cover`."""

    def write(self, version: WorkflowPlan, cover: Sequence[str]) -> list[Scenario] | None: ...


class Simulation(Protocol):
    """Runs scenarios on a version in the simulation n8n, which holds no real key (ADR 0054)."""

    def run(self, version: WorkflowPlan, scenarios: Sequence[Scenario]) -> Simulated | None: ...


class ScopeCheck(Protocol):
    """Code's check that a fixed version changes only the failed part of the stopped one."""

    def check(
        self, stopped: WorkflowPlan, fixed: WorkflowPlan, failed_part: Sequence[str]
    ) -> Scope: ...


class Checker(Protocol):
    """The platform's grade of a version: the node allow list and the safety checker."""

    def passes(self, version: WorkflowPlan) -> bool: ...


class Revisions(Protocol):
    """Stores a fixed version as a new revision of the workflow, which waits for a yes. It turns
    nothing on and approves nothing."""

    def store(self, fixed: WorkflowPlan) -> StoredRevision: ...


@dataclass(frozen=True)
class FixParts:
    """Everything a fix hands work to, and the recorder its events go to."""

    troubleshooter: Troubleshooter
    drafter: FixDrafter
    scenario_writer: ScenarioWriter
    simulation: Simulation
    scope: ScopeCheck
    checker: Checker
    revisions: Revisions
    recorder: FixRecorder
