"""What a Check card reads of a version tried on practice systems (ADR 0054): a drafted revision's,
or the version of a workflow the Planner built from our blocks. The wire models. Pure."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from platform_api.orchestration import ScenarioKind
from platform_api.wire import WireIn, WireModel

type SimulationState = Literal[
    "unavailable", "waiting", "not_started", "running", "done", "not_run", "not_finished"
]


class SimulatedBlockView(WireModel):
    block: str
    why: str = Field(description="Why no case could try it, in code's words.")


class SimulatedCaseView(WireModel):
    """One scenario of a simulation, as code graded it (ADR 0054, section 5)."""

    kind: ScenarioKind
    verdict: Literal["passed", "failed", "not_tried"] = Field(
        description="Code's grade, the verdict. not_tried: no block could play it, so it never "
        "ran and never counts as passed."
    )
    expected: str = Field(description="What code expects of this kind, in plain words.")
    happened: str = Field(description="What code read in the records, in plain words.")
    note: str | None = Field(
        description="For a failure, the explainer's one sentence, which code writes from its "
        "picks. It helps the reader and is never the verdict. Null with no model."
    )


class SimulationView(WireModel):
    """A version tried on practice systems, by its digest (ADR 0054). A result belongs to one
    digest, so a changed version never shows an older one, and a digest is tried once. A
    simulation is not a run, and never stands in for the test run Turn on starts."""

    state: SimulationState = Field(
        description="unavailable: there is no simulation n8n here. waiting: a setting is still "
        "needed, so it is tried once every setting is filled. not_started: it was never tried. "
        "running: it is being tried now. done: code graded each case. not_run: nothing was "
        "tried, with said. not_finished: it ran past its limit, so there is no result."
    )
    started_at: datetime | None = Field(
        description="When this try began. Null when unavailable, waiting or never tried."
    )
    case_seconds: int = Field(description="The most each case may take to end.")
    tried: int = Field(description="The cases that ran, leaving out those not tried.")
    passed: int
    cases: list[SimulatedCaseView] = Field(description="Each case, once done.")
    not_tried: list[SimulatedBlockView] = Field(
        description="Blocks no case could try, such as a pinned one or one after a write."
    )
    said: str | None = Field(description="Why nothing was tried, in words to show.")
    can_try_again: bool = Field(
        description="Whether this person can start it now: an Operator, once it was never tried, "
        "was not run or didn't finish, and only where there is a simulation n8n."
    )


class UseCaseSimulationView(WireModel):
    """The Check of a workflow the Planner built from our blocks: its current version tried on
    practice systems (ADR 0054, section 1)."""

    use_case_id: str
    version: int = Field(description="The version tried, the workflow's current one.")
    simulation: SimulationView | None = Field(
        description="Null when the version has nothing to try: it isn't laid out as a workflow "
        "of its own in n8n, or it wasn't built by the Planner from our blocks."
    )


class UseCaseSimulationIn(WireIn):
    version: int = Field(ge=1, description="The current version, to try on practice systems.")
