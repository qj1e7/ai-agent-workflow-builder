"""Code grades each scenario (ADR 0054, section 5, and spike S7). It reads two records: the
gateway's record of the simulated run (each call, what was proposed, what Ask for approval got and
what the write would have made) and n8n's record of the execution (its status, which blocks ran,
and the block and words of a failure). The model never grades. Its words, from PR 6, only help
the reader.

What code expects of each kind:

- Happy path: it reaches the yes, and asks to make every change proposed, each the one its
  Propose a change block names. A version with no Ask for a yes runs to the end.
- Nothing new: it ends with nothing proposed, nobody asked and nothing written.
- Source not found, and Timeout: a block the scenario played that way stops it, with words, and
  nothing is written. At one of n8n's own blocks, a timeout's words are ones the troubleshooter
  names (block_sources.source_stop).
- Approver says no: it ends as Declined, with nothing written.
- Odd data: it ends in one of the cases above, never in a failure with no reason. A stop
  counts only with our own words, or words the troubleshooter names: a block that throws on the
  odd data fails.

Whatever the kind, a run that asks to write with no yes fails. A pinned block never counts as run,
since n8n shows it as run although it never ran. It is listed as not tried, with why.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from platform_api.monitoring import stop_words
from platform_api.orchestration.block_sources import source_stop
from platform_api.orchestration.n8n import ExecutionRecord
from platform_api.orchestration.node_classes import OURS
from platform_api.orchestration.scenarios import (
    NotTried,
    Played,
    ScenarioKind,
    SimulationPlan,
    Staged,
)
from platform_api.orchestration.simulated_calls import SimulatedRun

type Verdict = Literal["passed", "failed", "not_tried"]
type Ending = Literal[
    "reached_yes",
    "finished",
    "nothing_new",
    "declined",
    "no_answer",
    "stopped",
    "failed",
    "wrong_write",
    "did_not_end",
]

WAIT_LIMIT_SECONDS: Final = 120
"""How long code waits for one scenario's run to end."""
ENDED: Final = frozenset({"success", "error", "crashed", "canceled"})
AFTER_WRITE: Final = "A simulation never writes, so a block after a write never runs."
NOT_PLAYED: Final = "No block here can play this case, so it was not tried."
EXPECTED: Final[Mapping[ScenarioKind, str]] = {
    "happy_path": "It reaches the approval step with the expected change.",
    "nothing_new": "It ends as Nothing new and proposes nothing.",
    "source_not_found": "It stops with a reason when the source is not found, and writes nothing.",
    "timeout": "It stops with a reason when the source is too slow, and writes nothing.",
    "approver_says_no": "It ends as Declined, with nothing written.",
    "odd_data": "It ends in one of the cases above, never in a failure with no reason.",
}
NO_ASK_EXPECTED: Final = "It runs to the end."
WITH_A_REASON: Final[frozenset[Ending]] = frozenset(
    {"reached_yes", "finished", "nothing_new", "declined", "stopped"}
)


@dataclass(frozen=True)
class Graded:
    name: str
    kind: ScenarioKind
    verdict: Verdict
    expected: str
    happened: str
    ran: tuple[str, ...]
    """The blocks that ran, pinned ones left out."""
    not_tried: tuple[NotTried, ...]
    ending: Ending | None = None
    """How code read the run's end. None for a scenario that never ran."""
    stopped_at: str | None = None
    """The block that stopped the run, when one did."""
    plays: tuple[Played, ...] = ()
    """How the scenario played each block other than as recorded."""
    reached: tuple[str, ...] = ()
    """What the run reached, from the gateway's record and n8n's (reach.py)."""


@dataclass(frozen=True)
class Coverage:
    """The coverage gaps code finds (ADR 0054, section 7)."""

    not_reached: tuple[str, ...]
    """Blocks that could run in a simulation, but no scenario reached."""
    not_tried: tuple[NotTried, ...]
    """Blocks no simulation runs: pinned ones, and those after a write."""
    kinds_without_a_scenario: tuple[ScenarioKind, ...]


@dataclass(frozen=True)
class _Seen:
    ending: Ending
    happened: str
    at: str | None = None
    """The block that stopped it."""
    named: bool = False
    """Whether the stop is in our own words, or words the troubleshooter names."""
    said: str = ""
    """The words of the stop."""


def _changes(count: int) -> str:
    return f"{count} change" + ("" if count == 1 else "s")


def _seen(
    plan: SimulationPlan, run: SimulatedRun | None, execution: ExecutionRecord | None
) -> _Seen:
    if execution is None or execution.status not in ENDED:
        return _Seen("did_not_end", f"It did not end within {WAIT_LIMIT_SECONDS} seconds.")
    if run is None:
        return _Seen("failed", "The simulation gateway no longer keeps this run.")
    written = run.would_have_written
    if written is not None and run.approver != "yes":
        return _Seen("wrong_write", "It asked to make changes without approval from an Approver.")
    if written is not None and written < len(run.proposed):
        proposed = len(run.proposed)
        made = f"It would have made {written} of the {proposed} changes proposed."
        return _Seen("wrong_write", made)
    match execution.status:
        case "crashed":
            return _Seen("failed", "n8n crashed while it ran.")
        case "canceled":
            return _Seen("failed", "n8n canceled it.")
        case "error":
            return _stopped(plan, run, execution)
        case _:
            return _ended(run)


def _stopped(plan: SimulationPlan, run: SimulatedRun, execution: ExecutionRecord) -> _Seen:
    at = execution.failed_node
    block = None if at is None else plan.block(at)
    words = (execution.error or "").strip()
    if block is not None and block.role == "write" and run.would_have_written is not None:
        made = _changes(run.would_have_written)
        happened = (
            f"It reached the approval step and would have made {made}, which the simulation "
            "refused."
        )
        return _Seen("reached_yes", happened, at)
    if at is None or block is None:
        return _Seen("failed", "It failed, and n8n names no block.")
    if block.node_type.startswith(OURS):
        # The gateway's own words, as n8n shows only its status for an answer to try again.
        said = next((c.detail for c in reversed(run.calls) if c.block == at and c.detail), words)
        if said:
            return _Seen("stopped", f'"{at}" stopped it: {said}', at, named=True, said=said)
    if not words:
        return _Seen("failed", f'It failed at "{at}" with no words for why.', at)
    if block.role in ("read", "notice") and block.mode != "pinned":
        stop = source_stop(at, execution.failed_block, words)
        said = words if stop is None else stop_words(stop)
        named = stop is not None
        return _Seen("stopped", f'"{at}" stopped it: {said}', at, named=named, said=said)
    return _Seen("failed", f'It failed at "{at}", which is not a stop with a reason: {words}', at)


def _ended(run: SimulatedRun) -> _Seen:
    match run.approver:
        case "no":
            return _Seen("declined", "It ended as Declined, with nothing written.")
        case "no_answer":
            return _Seen("no_answer", "It ended with no answer from an Approver.")
        case "yes":
            made = _changes(len(run.proposed))
            return _Seen("reached_yes", f"It reached the approval step with {made} proposed.")
        case None if not run.proposed:
            return _Seen("nothing_new", "It ended with nothing new and proposed nothing.")
        case None:
            return _Seen("finished", "It ran to the end.")


def _literal(value: object) -> str | None:
    """A parameter as the block writes it out. None for an expression, which could be anything."""
    return value if isinstance(value, str) and not value.startswith("=") else None


def _wrong_change(plan: SimulationPlan, run: SimulatedRun) -> str | None:
    for change in run.proposed:
        block = plan.block(change.block)
        if block is None or block.role != "propose":
            continue
        action, place = (_literal(block.parameters.get(k)) for k in ("action", "place"))
        said = f'"{change.block}" proposed'
        if action is not None and change.action != action:
            return f"{said} {change.action}, but the block names {action}."
        if place is not None and change.place != place:
            return f"{said} a change in {change.place}, but the block names {place}."
    return None


_GATEWAY_SERVES: Final[Mapping[ScenarioKind, str]] = {
    "source_not_found": "not_found",
    "timeout": "timeout",
}
_GITHUB_PLAYS: Final[Mapping[ScenarioKind, str]] = {
    "source_not_found": "not_found",
    "timeout": "drop",
}


def _played(staged: Staged, plan: SimulationPlan) -> frozenset[str]:
    """The blocks the scenario played as not found, or as too slow, for its kind."""
    played = {
        name
        for name, answer in staged.gateway.blocks.items()
        if answer.serve == _GATEWAY_SERVES[staged.kind]
    }
    if staged.github is not None and staged.github.mode == _GITHUB_PLAYS[staged.kind]:
        played |= {b.name for b in plan.reads if b.mode == "mock" and b.mock == "github"}
    return frozenset(played)


def _problem(
    plan: SimulationPlan, staged: Staged, run: SimulatedRun | None, seen: _Seen
) -> str | None:
    """None when the run is what the kind expects, else the words of what happened instead."""
    asks = bool(plan.having("ask"))
    match staged.kind:
        case "happy_path" if asks:
            if seen.ending != "reached_yes" or run is None:
                return seen.happened
            if plan.having("write") and run.would_have_written is None:
                return "It reached the approval step, but never asked to make the changes."
            return _wrong_change(plan, run)
        case "happy_path":
            return None if seen.ending in ("finished", "nothing_new") else seen.happened
        case "nothing_new":
            return None if seen.ending == "nothing_new" else seen.happened
        case "source_not_found" | "timeout":
            if seen.ending != "stopped" or seen.at not in _played(staged, plan):
                return seen.happened
            block = plan.block(seen.at)
            own = block is not None and not block.node_type.startswith(OURS)
            if staged.kind == "timeout" and own and not seen.named:
                return f'"{seen.at}" stopped it, but not as a slow source: {seen.said}'
            return None
        case "approver_says_no":
            return None if seen.ending == "declined" else seen.happened
        case "odd_data" if seen.ending == "stopped" and not seen.named:
            return f'It failed at "{seen.at}", which is not a stop with a reason: {seen.said}'
        case "odd_data":
            return None if seen.ending in WITH_A_REASON else seen.happened


def grade(
    plan: SimulationPlan,
    staged: Staged,
    run: SimulatedRun | None,
    execution: ExecutionRecord | None,
) -> Graded:
    """One scenario's verdict, from the gateway's record and n8n's."""
    seen = _seen(plan, run, execution)
    failed = seen.ending in ("failed", "wrong_write", "did_not_end")
    problem = seen.happened if failed else _problem(plan, staged, run, seen)
    pinned = {b.name for b in plan.blocks if b.mode == "pinned"}
    ran = () if execution is None else tuple(n for n in execution.ran if n not in pinned)
    expected = EXPECTED[staged.kind]
    if staged.kind == "happy_path" and not plan.having("ask"):
        expected = NO_ASK_EXPECTED
    verdict: Verdict = "passed" if problem is None else "failed"
    happened = seen.happened if problem is None else problem
    stopped_at = seen.at if seen.ending in ("stopped", "failed") else None
    return Graded(
        staged.name,
        staged.kind,
        verdict,
        expected,
        happened,
        ran,
        staged.not_tried,
        seen.ending,
        stopped_at,
        staged.plays,
    )


def not_tried(staged: Staged) -> Graded:
    """A scenario no block could play, which never ran."""
    expected = EXPECTED[staged.kind]
    return Graded(
        staged.name,
        staged.kind,
        "not_tried",
        expected,
        NOT_PLAYED,
        (),
        staged.not_tried,
        plays=staged.plays,
    )


def coverage(
    plan: SimulationPlan, results: Sequence[Graded], kinds: Sequence[ScenarioKind]
) -> Coverage:
    reached = {name for graded in results for name in graded.ran}
    pinned = [NotTried(b.name, b.why or "") for b in plan.blocks if b.mode == "pinned"]
    after = [
        NotTried(b.name, AFTER_WRITE)
        for b in plan.blocks
        if b.name in plan.after_write and b.mode != "pinned"
    ]
    could_run = [
        b.name
        for b in plan.blocks
        if b.role != "idle" and b.mode != "pinned" and b.name not in plan.after_write
    ]
    given = {graded.kind for graded in results}
    return Coverage(
        tuple(name for name in could_run if name not in reached),
        (*pinned, *after),
        tuple(kind for kind in kinds if kind not in given),
    )
