"""Code's record of one fix, and the checks that decide it (ADR 0055, sections 3 and 4).

Code fills the ledger from what each hand-off brought back, once it has checked it. The model
never writes here, and its "done" counts for nothing: `done_needs` decides when a fix is done,
and `made_progress` decides when the rounds stop.

A refinement of a drafted workflow's Check (ADR 0054, section 7) is a fix of a draft. Its ledger
starts with round 0, the draft as the Check tried it, which the coordinator may simulate before
any change. There is no stopped run, so no replay of the stop. Its failed part is code's: the
blocks where a scenario failed on that draft, which grows as more scenarios run on it."""

from dataclasses import dataclass, field
from typing import Final, Literal

from agent_runtime.contract import CauseFound, WorkflowPlan
from agent_runtime.fixing.events import FixFound, FixRefusal, FixWidening
from agent_runtime.fixing.ports import Scenario, ScenarioResult
from agent_runtime.fixing.replay import REPLAY

NEEDS_A_REPLAY: Final = "a replay of the stop that fails on the stopped version"
NEEDS_A_CHANGE: Final = "a draft that changes the failed part"
NEEDS_THE_GAPS: Final = "a scenario that reaches each block no scenario reached"


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
    not_reached: frozenset[str] | None = None
    """The blocks no scenario reached, from the last simulation that ran every scenario."""

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
    of_a_draft: bool = False
    """A refinement of a drafted workflow's Check: round 0 is the draft as the Check tried it."""
    gaps: frozenset[str] = frozenset()
    """For a refinement, the blocks no case of the Check reached."""

    def current(self) -> DraftTried | None:
        """The draft the fix stands on: the last one, when it stayed inside the failed part of
        the cause as it stands now. A refinement's failed part only grows, as more scenarios run
        on round 0, and the scope check held each draft to the blocks it was asked to change."""
        if not self.drafts:
            return None
        last = self.drafts[-1]
        if self.of_a_draft:
            return last if last.found == "inside" else None
        if self.cause is None:
            return None
        if last.found != "inside" or last.failed_part != tuple(self.cause.failed_part):
            return None
        return last

    def drafted(self) -> list[DraftTried]:
        """The rounds the Fix drafter drafted, round 0 of a refinement left out."""
        return [draft for draft in self.drafts if draft.round >= 1]

    def done_needs(self) -> list[str]:
        """What code still needs before the fix is done, or nothing when it is: a confirmed
        cause, a draft that changes the failed part and stays inside it, every scenario run on
        that draft, at least one that applies, every one that applies passing, code's replay of
        the stop failing on the stopped version, and the checker's pass.

        A refinement needs no confirmed cause and no replay. Its round 0, the draft unchanged,
        is done only when no scenario failed on it and a scenario reached each block no case of
        the Check reached. Any later round must change a block where a scenario failed."""
        if self.cause is None and not self.of_a_draft:
            return ["a confirmed cause"]
        draft = self.current()
        if draft is None:
            return ["a draft that stays inside the failed part"]
        needs: list[str] = []
        if draft.round >= 1 and not draft.changed or draft.round == 0 and self.cause is not None:
            needs.append(NEEDS_A_CHANGE)
        elif draft.round == 0 and (draft.not_reached is None or self.gaps & draft.not_reached):
            needs.append(NEEDS_THE_GAPS)
        if not self.scenarios:
            needs.append("scenarios")
        elif any(name not in draft.results for name in self.scenarios):
            needs.append("every scenario run on this draft")
        elif not draft.applies():
            needs.append("a scenario that applies")
        elif draft.failed():
            needs.append("every scenario that applies to pass")
        replayed = REPLAY in self.baseline and self.baseline[REPLAY].verdict == "failed"
        if not self.of_a_draft and not replayed:
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
            for draft in self.drafted()
        )


def made_progress(before: DraftTried | None, now: DraftTried) -> bool:
    """ADR 0055, section 4: more scenarios pass than in the round before, and none that passed
    then fails now. The first round is held to none passing before it."""
    earlier = before.passed() if before is not None else set[str]()
    passed = now.passed()
    return len(passed) > len(earlier) and earlier <= passed
