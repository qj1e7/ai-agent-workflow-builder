"""Code's record of one fix, and the checks that decide it (ADR 0055, sections 3 and 4).

Code fills the ledger from what each hand-off brought back, once it has checked it. The model
never writes here, and its "done" counts for nothing: `done_needs` decides when a fix is done,
and `made_progress` decides when the rounds stop."""

from dataclasses import dataclass, field
from typing import Final, Literal

from agent_runtime.contract import CauseFound, WorkflowPlan
from agent_runtime.fixing.events import FixFound, FixRefusal, FixWidening
from agent_runtime.fixing.ports import Scenario, ScenarioResult
from agent_runtime.fixing.replay import REPLAY

NEEDS_A_REPLAY: Final = "a replay of the stop that fails on the stopped version"


@dataclass
class DraftTried:
    """One round's draft, and what code found of it."""

    round: int
    failed_part: tuple[str, ...]
    """The failed part of the cause it was drafted for."""
    found: FixFound
    change_only: tuple[str, ...] = ()
    """The blocks the Fix drafter was asked to change, which the scope check held it to."""
    plan: WorkflowPlan | None = None
    widened_by: FixWidening | None = None
    changed: tuple[str, ...] = ()
    results: dict[str, ScenarioResult] = field(default_factory=dict[str, ScenarioResult])
    """Each scenario's latest grade on this draft."""
    checker: bool | None = None

    def passed(self) -> set[str]:
        return {name for name, result in self.results.items() if result.verdict == "passed"}

    def applies(self) -> list[ScenarioResult]:
        return [result for result in self.results.values() if result.verdict != "not_tried"]

    def failed(self) -> tuple[ScenarioResult, ...]:
        return tuple(r for r in self.results.values() if r.verdict == "failed")


@dataclass(frozen=True)
class RoundTried:
    """What one round tried, for the hand-back: what changed, and which scenarios failed."""

    round: int
    found: FixFound
    widened_by: FixWidening | None
    changed: tuple[str, ...]
    passed: int | None
    scenarios: int | None
    """The scenarios that applied, or None when the round's draft was never simulated."""
    failed: tuple[ScenarioResult, ...]


type UnloggedWhy = Literal["shape", "failed"] | FixRefusal


@dataclass(frozen=True)
class Unlogged:
    """An event the activity log didn't take, kept here so it is never lost without a word.
    shape: its data doesn't fit platform-api's contract, as a block whose name the log can't
    show. failed: the recorder couldn't reach the log. Otherwise the log's own refusal."""

    kind: str
    handoff: int | None
    why: UnloggedWhy


@dataclass
class Ledger:
    blocks: frozenset[str]
    stopped_at: frozenset[str]
    cause: CauseFound | None = None
    scenarios: dict[str, Scenario] = field(default_factory=dict[str, Scenario])
    baseline: dict[str, ScenarioResult] = field(default_factory=dict[str, ScenarioResult])
    """Each scenario's grade on the stopped version, tried before a draft's first simulation."""
    allowed: set[str] = field(default_factory=set[str])
    """What the stopped version names or reached in those tries. A draft's run that reaches
    anything else widens the fix."""
    drafts: list[DraftTried] = field(default_factory=list[DraftTried])
    handoffs: int = 0
    turns: int = 0
    tools: list[str] = field(default_factory=list[str])
    """Each tool the model called, in order, refused or not."""
    refused: list[str] = field(default_factory=list[str])
    """Each call code refused, by the tool's name."""
    unlogged: list[Unlogged] = field(default_factory=list[Unlogged])

    def current(self) -> DraftTried | None:
        """The draft the fix stands on: the last one, when it stayed inside the failed part of
        the cause as it stands now."""
        if not self.drafts or self.cause is None:
            return None
        last = self.drafts[-1]
        if last.found != "inside" or last.failed_part != tuple(self.cause.failed_part):
            return None
        return last

    def done_needs(self) -> list[str]:
        """What code still needs before the fix is done, or nothing when it is: a confirmed
        cause, a draft that changes the failed part and stays inside it, every scenario run on
        that draft, at least one that applies, every one that applies passing, code's replay of
        the stop failing on the stopped version, and the checker's pass."""
        if self.cause is None:
            return ["a confirmed cause"]
        draft = self.current()
        if draft is None:
            return ["a draft that stays inside the failed part"]
        needs: list[str] = []
        if not draft.changed:
            needs.append("a draft that changes the failed part")
        if not self.scenarios:
            needs.append("scenarios")
        elif any(name not in draft.results for name in self.scenarios):
            needs.append("every scenario run on this draft")
        elif not draft.applies():
            needs.append("a scenario that applies")
        elif draft.failed():
            needs.append("every scenario that applies to pass")
        if REPLAY not in self.baseline or self.baseline[REPLAY].verdict != "failed":
            needs.append(NEEDS_A_REPLAY)
        if draft.checker is not True:
            needs.append("the checker's pass")
        return needs

    def simulated_before(self, draft: DraftTried) -> DraftTried | None:
        """The last draft before this one that the simulation ran."""
        earlier = self.drafts[: self.drafts.index(draft)]
        return next((d for d in reversed(earlier) if d.results), None)

    def rounds(self) -> tuple[RoundTried, ...]:
        return tuple(
            RoundTried(
                round=draft.round,
                found=draft.found,
                widened_by=draft.widened_by,
                changed=draft.changed,
                passed=len(draft.passed()) if draft.results else None,
                scenarios=len(draft.applies()) if draft.results else None,
                failed=draft.failed(),
            )
            for draft in self.drafts
        )


def made_progress(before: DraftTried | None, now: DraftTried) -> bool:
    """ADR 0055, section 4: more scenarios pass than in the round before, and none that passed
    then fails now. The first round is held to none passing before it."""
    earlier = before.passed() if before is not None else set[str]()
    passed = now.passed()
    return len(passed) > len(earlier) and earlier <= passed
