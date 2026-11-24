"""Code's replay of the stop (ADR 0055, PR 5): one scenario, built from the stopped run's own
facts, that a fix must pass and the stopped version must fail.

Without it, a set of happy paths could pass a draft that touches the failed part but fixes
nothing, since the stopped version would pass them too. So before a draft's first simulation,
code adds this scenario to the set, and tries the stopped version in it first. If the stopped
version passes it, the practice systems can't show the stop, so no fix can be proven.

The replay is a happy path: the run should get through the situation that stopped it and reach
the yes. Where the stop was a source not found, at one of our Read blocks or n8n's GitHub block,
the replay serves that block as recorded everywhere but the place the stopped run read, which is
gone: the name the cause copied from the stop, else the place the block reads, written out. Any
other stop replays as the happy path with the stopped run's samples, and the baseline decides
whether it shows the stop. A place an expression picks is never guessed.

Pure."""

from collections.abc import Sequence
from typing import Final

from agent_runtime.contract import CauseFound, PlanBlock, WorkflowPlan
from agent_runtime.fixing.ports import Scenario

REPLAY: Final = "replay_the_stop"
"""The replay's name, which no written scenario may take."""
OUR_READ: Final = "CUSTOM.wabRead"
GITHUB: Final = "n8n-nodes-base.github"


def replay_of(version: WorkflowPlan, stopped_at: Sequence[str], cause: CauseFound) -> Scenario:
    reads: dict[str, object] = {}
    if cause.failure_kind == "not_found":
        blocks = {block.name: block for block in version.blocks}
        filled = _filled(version)
        for name in cause.failed_part:
            block = blocks.get(name)
            if block is None or name not in stopped_at:
                continue
            place = cause.detail if cause.detail else _place(block, filled)
            if place is not None and block.type in (OUR_READ, GITHUB):
                reads[name] = {"serve": "recorded", "gone": [place]}
    return Scenario.model_validate({"name": REPLAY, "kind": "happy_path", "reads": reads})


def _filled(version: WorkflowPlan) -> dict[str, str]:
    """Each setting's placeholder, with the value a person filled in."""
    return {f"<<{s.id}>>": s.value for s in version.settings if s.value}


def _place(block: PlanBlock, filled: dict[str, str]) -> str | None:
    """The place the block reads, when it is written out or a setting holds it, never when an
    expression picks it."""
    parameters = block.parameters
    if block.type == OUR_READ:
        return _written(parameters.get("place"), filled)
    owner = _written(parameters.get("owner"), filled)
    repository = _written(parameters.get("repository"), filled)
    return None if owner is None or repository is None else f"{owner}/{repository}"


def _written(value: object, filled: dict[str, str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = filled.get(value.strip(), value)
    if value.startswith("=") or "{{" in value or "<<" in value:
        return None
    return value.strip()
