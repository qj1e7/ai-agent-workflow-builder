"""What a simulated run reached, and what a version names (ADR 0055, PR 5).

The fix's scope check reads each block on its own, so it can't see data flow: a value a fix
changes upstream can be what a block downstream reads as its source. The run shows it. So each
simulated run says what it reached, from the records:

- the gateway's record of our blocks' calls: the source a Read asked for, the card an Agent asked
  for, the change a Propose a change proposed and where Tell would tell;
- n8n's record of its own blocks: one that ran against a mock reached that mock, whose address
  the mock setup fixes in the block's key;
- n8n's error words: the simulation n8n reaches only the mocks and the gateway, so a block that
  tried any other address failed there, and n8n names the address.

`named` is what the version names in plain values, the same way. An expression names nothing, as
its value is known only once the run reads it. A pinned block never runs, so it names nothing.

Each is a word such as `read:github_releases`, `mock:github` or `host:evil.example`. The
coordinator counts a word that the stopped version neither names nor reached as widening.

Pure."""

import re
from collections.abc import Iterable, Mapping
from typing import Final

from platform_api.orchestration.n8n import ExecutionRecord
from platform_api.orchestration.scenarios import SimulationPlan
from platform_api.orchestration.simulated_calls import SimulatedRun

OURS: Final[Mapping[str, tuple[str, str]]] = {
    "CUSTOM.wabRead": ("read", "source"),
    "CUSTOM.wabAgent": ("agent", "agent"),
    "CUSTOM.wabProposeChange": ("propose", "action"),
    "CUSTOM.wabTell": ("tell", "where"),
}
"""For each of our blocks that reaches a system, the word for it and the parameter that picks it."""
CALLED: Final[Mapping[str, str]] = {kind: parameter for kind, parameter in OURS.values()}
"""The same, by the kind of call the gateway records."""
NETWORK_ERROR: Final = re.compile(
    r"\b(?:ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EHOSTUNREACH|ENETUNREACH)"
    r"\s+([^\s,;'\"()<>]+)"
)
"""Node's words for an address it could not reach, then the address."""


def _expression(value: str) -> bool:
    return value.startswith("=") or "{{" in value


def named(plan: SimulationPlan) -> tuple[str, ...]:
    """What the version names in plain values, sorted."""
    found: set[str] = set()
    for block in plan.blocks:
        if block.mode == "mock" and block.mock is not None:
            found.add(f"mock:{block.mock}")
        picked = OURS.get(block.node_type)
        if block.mode != "ours" or picked is None:
            continue
        kind, parameter = picked
        value = block.parameters.get(parameter)
        if isinstance(value, str) and value and not _expression(value):
            found.add(f"{kind}:{value}")
    return tuple(sorted(found))


def reached(
    plan: SimulationPlan, run: SimulatedRun | None, execution: ExecutionRecord | None
) -> tuple[str, ...]:
    """What one simulated run reached, from the gateway's record and n8n's, sorted."""
    found: set[str] = set(_called(run)) if run is not None else set()
    if execution is not None:
        for name in execution.ran:
            block = plan.block(name)
            if block is not None and block.mode == "mock" and block.mock is not None:
                found.add(f"mock:{block.mock}")
        found.update(_addresses(execution.error or ""))
    return tuple(sorted(found))


def _called(run: SimulatedRun) -> Iterable[str]:
    for call in run.calls:
        parameter = CALLED.get(call.kind)
        value = call.asked.get(parameter) if parameter is not None else None
        if isinstance(value, str) and value:
            yield f"{call.kind}:{value}"


def _addresses(error: str) -> Iterable[str]:
    for found in NETWORK_ERROR.finditer(error):
        address = found.group(1).rstrip(".").lower()
        if address:
            yield f"host:{address}"
