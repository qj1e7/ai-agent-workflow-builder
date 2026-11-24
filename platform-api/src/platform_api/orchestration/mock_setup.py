"""The mock setup (ADR 0054, section 4): the copy of one workflow version that a simulation runs
in the simulation n8n. Code builds it from the class file (node_classes.json), never the model.

Each block of the version gets one mode, which the setup records, so the results can say what a
simulation tried and what it did not:

- `ours`: one of our blocks. It calls the simulation gateway, which answers it from the scenario.
- `runs`: one of n8n's own blocks that starts a run, or moves or reshapes items. It runs as it is.
- `mock`: one of n8n's own blocks for an outside system with a mock here. It runs against the
  mock, with a mock key of a type the platform's own key for that system has.
- `pinned`: one of n8n's own blocks for a system with no mock here. Its output is pinned, so it
  never runs, and its "not found" and "timeout" are never tried (ADR 0054, Upkeep). The pin is the
  scenario's own, or an item that says it was pinned. The version's own pinned output is never
  used, since it may be what a real run read.

A block the class file turns off or does not know is refused, and the setup makes nothing: it
never passes a block through. The copy names no key the version names. A block that runs against
a mock names the mock key the setup made in the simulation n8n, and every other block names none.

The setup reaches only the simulation n8n it is given, through that n8n's own API key. The
simulation gateway gives it the one it holds, at an address only the simulation's network has.
"""

import asyncio
import secrets
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from platform_api.orchestration.n8n import N8nCredential, N8nWorkflow
from platform_api.orchestration.node_classes import (
    NODE_CLASSES,
    OURS,
    Mock,
    Mocked,
    Off,
    OffType,
    OnType,
    Pinned,
)
from platform_api.orchestration.platform_keys import KEYS

type Mode = Literal["ours", "runs", "mock", "pinned"]
type Items = Sequence[Mapping[str, Any]]

KEPT_SETTINGS = ("executionOrder", "timezone")
"""The version's settings the copy keeps. Its error workflow is the platform n8n's, and n8n runs
none for a run by hand anyway (ADR 0054, spike S3)."""
SIMULATION_SETTINGS = {"saveManualExecutions": True, "saveExecutionProgress": True}
"""So n8n keeps each block's run, which the grader reads (ADR 0054, spike S7)."""
MOCK_EMAIL = "simulation@simulation.example"
NOT_PINNABLE = "A scenario may pin only a block with no mock."
NO_SUCH_BLOCK = "The version has no block by this name."


@dataclass(frozen=True)
class MockKey:
    """A key the setup makes in the simulation n8n, of one credential type, for one mock."""

    kind: str
    """n8n's credential type, such as githubApi."""
    id: str
    """At most 16 characters, as n8n's public API takes one."""
    name: str
    data: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True)
class BlockMode:
    """How the copy runs one block of the version."""

    block: str
    node_type: str
    mode: Mode
    mock: Mock | None = None
    """For a block that runs against a mock, which one."""
    why: str | None = None
    """For a pinned block, why no mock stands in for it."""


@dataclass(frozen=True)
class RefusedBlock:
    block: str
    node_type: str
    why: str


@dataclass(frozen=True)
class SetupRefused:
    """Every block the setup refused. It made nothing."""

    blocks: tuple[RefusedBlock, ...]


def _not_tried(blocks: Sequence[BlockMode]) -> tuple[str, ...]:
    return tuple(block.block for block in blocks if block.mode == "pinned")


@dataclass(frozen=True)
class MockSetup:
    document: dict[str, Any]
    """The copy, as n8n's public API takes a workflow."""
    blocks: tuple[BlockMode, ...]
    """Each block's mode, in the version's order."""
    keys: tuple[MockKey, ...]
    """The mock keys the copy names."""

    @property
    def not_tried(self) -> tuple[str, ...]:
        """The pinned blocks, whose failures no scenario can play."""
        return _not_tried(self.blocks)


@dataclass(frozen=True)
class Copied:
    """A copy the simulation n8n holds."""

    workflow_id: str
    blocks: tuple[BlockMode, ...]

    @property
    def not_tried(self) -> tuple[str, ...]:
        return _not_tried(self.blocks)


def mock_keys(
    github_url: str | None,
    jira_url: str | None,
    slack_token: str | None,
    made_up: Callable[[], str] = lambda: secrets.token_hex(20),
) -> dict[str, MockKey]:
    """The mock keys, by credential type, for each mock this simulation n8n reaches. A mock with
    no address here gets none, so its blocks are pinned. Every secret in them is made up here,
    but mock Slack's, which takes only the key its stack made up at its start. Mock Slack has no
    address field: n8n's Slack block always calls slack.com, which the simulation's network names
    mock Slack (ADR 0054, spike S2)."""
    keys: list[MockKey] = []
    if github_url:
        github = {"server": github_url, "accessToken": made_up()}
        keys.append(MockKey("githubApi", "sim-mock-github", "Mock GitHub", github))
    if jira_url:
        cloud = {"domain": jira_url, "email": MOCK_EMAIL, "apiToken": made_up()}
        keys.append(MockKey("jiraSoftwareCloudApi", "sim-mock-jira", "Mock Jira", cloud))
        pat = {"domain": jira_url, "personalAccessToken": made_up()}
        keys.append(MockKey("jiraSoftwareServerPatApi", "sim-mock-jirapat", "Mock Jira", pat))
    if slack_token:
        slack = {"accessToken": slack_token}
        keys.append(MockKey("slackApi", "sim-mock-slack", "Mock Slack", slack))
    return {key.kind: key for key in keys}


def plan_copy(
    version: Mapping[str, Any], keys: Mapping[str, MockKey], pins: Mapping[str, Items]
) -> MockSetup | SetupRefused:
    """The copy of a version, as n8n's public API keeps a workflow, with a mode for each block.
    `pins` is a scenario's own output for blocks with no mock, by block name (PR 5 fills it). The
    version is left as it is."""
    blocks: list[BlockMode] = []
    nodes: list[dict[str, Any]] = []
    refused: list[RefusedBlock] = []
    used: dict[str, MockKey] = {}
    for node in cast(list[Mapping[str, Any]], version.get("nodes") or []):
        name, node_type = str(node.get("name")), str(node.get("type"))
        if any(block.block == name for block in blocks):
            refused.append(RefusedBlock(name, node_type, f'Two blocks share the name "{name}".'))
            continue
        decided = _mode(name, node_type, node, keys)
        if isinstance(decided, RefusedBlock):
            refused.append(decided)
            continue
        mode, key = decided
        blocks.append(mode)
        nodes.append(_copied(node, mode, key))
        if key is not None:
            used[key.kind] = key
    modes = {block.block: block for block in blocks}
    for name in pins:
        found = modes.get(name)
        if found is None:
            refused.append(RefusedBlock(name, "", NO_SUCH_BLOCK))
        elif found.mode != "pinned":
            refused.append(RefusedBlock(name, found.node_type, NOT_PINNABLE))
    if refused:
        return SetupRefused(tuple(refused))
    settings = cast(Mapping[str, Any], version.get("settings") or {})
    document: dict[str, Any] = {
        "name": version.get("name"),
        "nodes": nodes,
        "connections": deepcopy(cast(Mapping[str, Any], version.get("connections") or {})),
        "settings": {
            **{key: settings[key] for key in KEPT_SETTINGS if key in settings},
            **SIMULATION_SETTINGS,
        },
    }
    pinned = _pins(blocks, pins)
    if pinned:
        document["pinData"] = pinned
    return MockSetup(document, tuple(blocks), tuple(used.values()))


def _mode(
    name: str, node_type: str, node: Mapping[str, Any], keys: Mapping[str, MockKey]
) -> tuple[BlockMode, MockKey | None] | RefusedBlock:
    entry = NODE_CLASSES.entry(node_type)
    parameters = cast(Mapping[str, object], node.get("parameters") or {})
    verdict = NODE_CLASSES.verdict(node_type, node.get("typeVersion"), parameters)
    if isinstance(verdict, Off) or not isinstance(entry, OnType):
        off = verdict if isinstance(verdict, Off) else None
        return RefusedBlock(name, node_type, _why_off(node_type, entry, off))
    if node_type.startswith(OURS):
        return BlockMode(name, node_type, "ours"), None
    match entry.simulated:
        case None:
            return BlockMode(name, node_type, "runs"), None
        case Pinned(why=why):
            return BlockMode(name, node_type, "pinned", why=why), None
        case Mocked(mock=mock):
            key = _mock_key(mock, parameters, keys)
            if key is None:
                why = f"No mock {KEYS[mock].said} runs in this simulation, so its output is pinned."
                return BlockMode(name, node_type, "pinned", why=why), None
            return BlockMode(name, node_type, "mock", mock=mock), key


def _why_off(node_type: str, entry: OnType | OffType | None, off: Off | None) -> str:
    if isinstance(entry, OffType):
        return entry.why
    match None if off is None else (off.because, off.value):
        case ("version", version):
            return f"Its version {version} is not on the allow list."
        case ("expression", _):
            return "It picks what it does with an expression, which could pick anything."
        case ("operation", what):
            return f"What it is set to do, {what}, is off."
        case _:
            return f"The class file does not know {node_type}, so nothing may run it."


def _mock_key(
    mock: Mock, parameters: Mapping[str, object], keys: Mapping[str, MockKey]
) -> MockKey | None:
    """The mock key of the type the block asks for, else of the type n8n asks for by default, as
    the platform's own key goes on the block (platform_keys.attach_keys)."""
    spec = KEYS[mock]
    kinds = [kind for kind in spec.by_kind if kind in keys]
    for wanted in (parameters.get(spec.picks, spec.picked), spec.picked):
        for kind in kinds:
            if spec.by_kind[kind] == wanted:
                return keys[kind]
    return keys[kinds[0]] if kinds else None


def _copied(node: Mapping[str, Any], mode: BlockMode, key: MockKey | None) -> dict[str, Any]:
    copied = deepcopy(dict(node))
    copied.pop("credentials", None)
    if key is None or mode.mock is None:
        return copied
    spec = KEYS[mode.mock]
    copied["credentials"] = {key.kind: {"id": key.id, "name": key.name}}
    parameters = copied.setdefault("parameters", {})
    # It picks only which credential type the block asks for. What the block does was classed
    # above and stays as it is.
    if parameters.get(spec.picks, spec.picked) != spec.by_kind[key.kind]:
        parameters[spec.picks] = spec.by_kind[key.kind]
    return copied


def _pins(blocks: Sequence[BlockMode], scenario: Mapping[str, Items]) -> dict[str, Any]:
    """Output for each pinned block: the scenario's, which comes from a scrubbed recorded sample
    (recorded_samples.py), else an item that says it was pinned. No pin the version holds is
    used, as it may be a real run's output, and each block with a mock runs."""
    pins: dict[str, Any] = {}
    for block in blocks:
        if block.mode != "pinned":
            continue
        if block.block in scenario:
            pins[block.block] = [{"json": dict(item)} for item in scenario[block.block]]
        else:
            pins[block.block] = [{"json": {"pinned": block.why}}]
    return pins


class SimulationN8n(Protocol):
    """The simulation n8n, as N8nApi reaches it with that n8n's own API key."""

    async def personal_project(self) -> str: ...

    async def delete_credential(self, credential_id: str) -> None: ...

    async def create_credential(
        self, credential_id: str, name: str, kind: str, data: Mapping[str, str], project_id: str
    ) -> N8nCredential: ...

    async def create(self, document: Mapping[str, Any]) -> N8nWorkflow: ...


class MockSetups:
    """Makes each version's copy in the simulation n8n. It makes each mock key there once a
    process, and first removes any key with its id, which an earlier process may have made with
    other made-up values."""

    def __init__(self, n8n: SimulationN8n, keys: Mapping[str, MockKey]) -> None:
        self._n8n = n8n
        self._keys = dict(keys)
        self._made: set[str] = set()
        self._lock = asyncio.Lock()

    def modes(self, version: Mapping[str, Any]) -> tuple[BlockMode, ...] | SetupRefused:
        """How a copy would run each block of the version, without making anything."""
        setup = plan_copy(version, self._keys, {})
        return setup if isinstance(setup, SetupRefused) else setup.blocks

    async def copy(
        self, version: Mapping[str, Any], pins: Mapping[str, Items]
    ) -> Copied | SetupRefused:
        setup = plan_copy(version, self._keys, pins)
        if isinstance(setup, SetupRefused):
            return setup
        async with self._lock:
            missing = [key for key in setup.keys if key.id not in self._made]
            if missing:
                project = await self._n8n.personal_project()
                for key in missing:
                    await self._n8n.delete_credential(key.id)
                    await self._n8n.create_credential(key.id, key.name, key.kind, key.data, project)
                    self._made.add(key.id)
        made = await self._n8n.create(setup.document)
        return Copied(made.id, setup.blocks)
