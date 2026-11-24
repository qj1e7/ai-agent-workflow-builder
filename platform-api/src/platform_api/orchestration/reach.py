"""What a simulated run reached, and what a version names (ADR 0055, PR 5). It fails closed.

The fix's scope check reads each block on its own, so it can't see data flow: a value a fix
changes upstream can be what a block downstream reads as its source. The run shows it. So each
simulated run says what it reached, from the records:

- the gateway's record of our blocks' calls: the source a Read asked for, the card an Agent asked
  for, the change a Propose a change proposed and where Tell would tell;
- n8n's run data, block by block, also for a block that went on past its failure: a block of
  n8n's that calls out reached its mock, whose address the mock setup puts in the block's key, and
  any address a parameter of it names; every address any block's errors name;
- n8n's error for the whole run.

The simulation n8n reaches only the mocks and the gateway, so a block that tried any other address
failed there, and n8n names the address. Mock GitHub and mock Slack keep no record of their own.

What can't be read is `unknown:<block>`, which always widens a fix: a block of n8n's that calls
out and has no try in the run data, an address an expression picks, and an error with no address
that came with no answer and that the scenario didn't play.

`named` is what the version names, the same way: our blocks' plain values, each block of n8n's
that calls out (`outbound:<block>@<type>`, so a new one widens), its mock, and each address its
parameters name. An expression in our block names nothing, as the run shows its value.

Each is a word such as `read:github_releases`, `mock:github` or `host:evil.example`.

Pure."""

import re
from collections.abc import Iterable, Mapping
from typing import Any, Final, cast
from urllib.parse import urlsplit

from platform_api.orchestration.n8n import ExecutionRecord
from platform_api.orchestration.scenarios import PlanBlock, SimulationPlan
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
UNKNOWN: Final = "unknown:"
ADDRESS_NAMES: Final = (
    "url",
    "uri",
    "endpoint",
    "host",
    "hostname",
    "domain",
    "server",
    "webhook",
    "address",
)
"""How the name of a parameter that picks where a block calls ends, once its case is gone."""
NETWORK_ERROR: Final = re.compile(
    r"\b(?:ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EHOSTUNREACH|ENETUNREACH)"
    r"\s+([^\s,;'\"()<>]+)"
)
"""Node's words for an address it could not reach, then the address."""
URL: Final = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s\"'<>]+", re.IGNORECASE)


def _expression(value: str) -> bool:
    return value.startswith("=") or "{{" in value


def _outbound(block: PlanBlock) -> bool:
    """One of n8n's own blocks for an outside system, which the class file names."""
    return not block.node_type.startswith("CUSTOM.") and block.role in ("read", "notice")


def named(plan: SimulationPlan) -> tuple[str, ...]:
    """What the version names, sorted."""
    found: set[str] = set()
    for block in plan.blocks:
        if _outbound(block):
            found.add(f"outbound:{block.name}@{block.node_type}")
            found.update(_addressed(block))
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
    plan: SimulationPlan,
    run: SimulatedRun | None,
    execution: ExecutionRecord | None,
    failing: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """What one simulated run reached, from the gateway's record and n8n's, sorted. `failing`
    names the blocks the scenario played as not found or too slow, whose errors are the mock's."""
    found: set[str] = set(_called(run)) if run is not None else set()
    if execution is not None:
        found.update(_addresses(execution.error or ""))
        for name in {*execution.ran, *execution.nodes}:
            block = plan.block(name)
            tried = execution.nodes.get(name)
            if tried is not None:
                found.update(word for error in tried.errors for word in _addresses(error))
            if block is None or block.mode != "mock" or not _outbound(block):
                continue
            if block.mock is not None:
                found.add(f"mock:{block.mock}")
            found.update(_addressed(block))
            unread = tried is None or any(
                not _addresses(error) and not tried.answered and name not in failing
                for error in tried.errors
            )
            if unread:
                found.add(f"{UNKNOWN}{name}")
    return tuple(sorted(found))


def _called(run: SimulatedRun) -> Iterable[str]:
    for call in run.calls:
        parameter = CALLED.get(call.kind)
        value = call.asked.get(parameter) if parameter is not None else None
        if isinstance(value, str) and value:
            yield f"{call.kind}:{value}"


def _addressed(block: PlanBlock) -> set[str]:
    """Each address a parameter of the block names, or unknown for one an expression picks."""
    words: set[str] = set()
    for name, value in _leaves(block.parameters):
        if not name.lower().endswith(ADDRESS_NAMES) or not isinstance(value, str) or not value:
            continue
        if _expression(value):
            words.add(f"{UNKNOWN}{block.name}")
            continue
        hosts = [_host(found.group()) for found in URL.finditer(value)]
        words.update(f"host:{host}" for host in hosts or [value.strip().lower()])
    return words


def _host(url: str) -> str:
    parts = urlsplit(url)
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        port = ""
    return f"{(parts.hostname or parts.netloc).lower()}{port}"


def _leaves(value: Any, name: str = "") -> Iterable[tuple[str, Any]]:
    match value:
        case dict():
            for key, inner in cast(dict[str, Any], value).items():
                yield from _leaves(inner, key)
        case list():
            for inner in cast(list[Any], value):
                yield from _leaves(inner, name)
        case _:
            yield name, value


def _addresses(error: str) -> set[str]:
    words: set[str] = set()
    for found in NETWORK_ERROR.finditer(error):
        address = found.group(1).rstrip(".").lower()
        if address:
            words.add(f"host:{address}")
    return words
