"""The mock setup (ADR 0054, section 4): code builds the copy of a workflow version that the
simulation n8n runs, from the class file. Each block gets one mode, recorded so the results can say
what was not tried. A block the class file turns off or does not know is refused, and nothing is
made. The copy names only mock keys, made in the simulation n8n with made-up values."""

import json
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from platform_api.orchestration.mock_setup import (
    BlockMode,
    Copied,
    MockKey,
    MockSetup,
    MockSetups,
    SetupRefused,
    mock_keys,
    plan_copy,
)
from platform_api.orchestration.n8n import N8nCredential, N8nWorkflow
from platform_api.orchestration.node_classes import NODE_CLASSES, Mocked, OnType, Pinned
from platform_api.orchestration.platform_keys import KEYS

# Made up at run time. None is a real key.
SLACK_TOKEN = secrets.token_hex(16)
GITHUB = "http://mock-github:8200"
JIRA = "http://mock-jira:8700"
START = "Start from the Portal"

REAL_GITHUB = {"githubApi": {"id": "wab-github-read", "name": "The platform's GitHub key"}}
REAL_JIRA = {"jiraSoftwareServerApi": {"id": "wab-jira-read", "name": "The platform's Jira key"}}
REAL_SLACK = {"slackApi": {"id": "wab-slack-send", "name": "The platform's Slack key"}}
REAL_TEAMS = {"microsoftOAuth2Api": {"id": "staff-teams-key", "name": "Someone's Teams key"}}
REAL = ("wab-github-read", "wab-jira-read", "wab-slack-send", "staff-teams-key", "Someone's")


def node(
    name: str,
    node_type: str,
    version: float = 1,
    parameters: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    made: dict[str, Any] = {
        "id": f"id-{name}",
        "name": name,
        "type": node_type,
        "typeVersion": version,
        "position": [0, 0],
        "parameters": parameters or {},
    }
    if credentials is not None:
        made["credentials"] = credentials
    return made


def version(*extra: dict[str, Any]) -> dict[str, Any]:
    """A release check with one of each mode: ours, a read and a post with a mock, a read with no
    mock here, a post with no mock at all, and a branch that runs as it is."""
    nodes = [
        node(START, "CUSTOM.wabStartFromPortal"),
        node(
            "Read releases",
            "n8n-nodes-base.github",
            1.1,
            {
                "resource": "release",
                "operation": "getAll",
                "owner": "langchain-ai",
                "repository": "langgraph",
            },
            REAL_GITHUB,
        ),
        node(
            "Read issues",
            "n8n-nodes-base.jira",
            1,
            {"resource": "issue", "operation": "getAll", "jiraVersion": "server"},
            REAL_JIRA,
        ),
        node("Is it new", "n8n-nodes-base.if", 2.2),
        node("Ask for a yes", "CUSTOM.wabAskForYes"),
        node(
            "Post in Slack",
            "n8n-nodes-base.slack",
            2.3,
            {"select": "channel", "channelId": "C0SUPPORT", "text": "A new release is out."},
            REAL_SLACK,
        ),
        node(
            "Post in Teams",
            "n8n-nodes-base.microsoftTeams",
            2,
            {
                "resource": "channelMessage",
                "operation": "create",
                "teamId": "T1",
                "channelId": "C1",
                "message": "A new release is out.",
            },
            REAL_TEAMS,
        ),
        *extra,
    ]
    names = [n["name"] for n in nodes]
    return {
        "name": "Release check",
        "nodes": nodes,
        "connections": {
            a: {"main": [[{"node": b, "type": "main", "index": 0}]]}
            for a, b in zip(names, names[1:], strict=False)
        },
        "settings": {
            "executionOrder": "v1",
            "timezone": "Asia/Singapore",
            "errorWorkflow": "the-real-error-workflow",
            "callerPolicy": "any",
        },
    }


def counter() -> Callable[[], str]:
    made = iter(range(1000))
    return lambda: f"made-up-{next(made)}"


def keys(jira: str | None = None, slack: str | None = SLACK_TOKEN) -> dict[str, MockKey]:
    return mock_keys(GITHUB, jira, slack, made_up=counter())


def planned(
    given: Mapping[str, Any] | None = None,
    jira: str | None = None,
    pins: Mapping[str, list[dict[str, Any]]] | None = None,
) -> MockSetup:
    setup = plan_copy(version() if given is None else given, keys(jira), pins or {})
    assert isinstance(setup, MockSetup), setup
    return setup


def modes(setup: MockSetup) -> dict[str, tuple[str, str | None]]:
    return {b.block: (b.mode, b.mock) for b in setup.blocks}


def nodes_of(setup: MockSetup) -> dict[str, dict[str, Any]]:
    return {n["name"]: n for n in setup.document["nodes"]}


# Each block gets one mode, from the class file


def test_each_block_gets_its_mode_from_the_class_file() -> None:
    setup = planned()
    assert modes(setup) == {
        START: ("ours", None),
        "Read releases": ("mock", "github"),
        "Read issues": ("pinned", None),
        "Is it new": ("runs", None),
        "Ask for a yes": ("ours", None),
        "Post in Slack": ("mock", "slack"),
        "Post in Teams": ("pinned", None),
    }


def test_a_pinned_block_says_why_and_is_not_tried() -> None:
    setup = planned()
    why = {b.block: b.why for b in setup.blocks if b.mode == "pinned"}
    assert "Jira" in str(why["Read issues"])
    teams = NODE_CLASSES.entry("n8n-nodes-base.microsoftTeams")
    assert isinstance(teams, OnType) and isinstance(teams.simulated, Pinned)
    assert why["Post in Teams"] == teams.simulated.why
    assert setup.not_tried == ("Read issues", "Post in Teams")
    assert all(b.why is None for b in setup.blocks if b.mode != "pinned")


def test_a_system_gets_its_mock_only_where_the_mock_runs() -> None:
    assert modes(planned(jira=JIRA))["Read issues"] == ("mock", "jira")
    no_slack = plan_copy(version(), keys(slack=None), {})
    assert isinstance(no_slack, MockSetup)
    assert modes(no_slack)["Post in Slack"] == ("pinned", None)
    assert no_slack.not_tried == ("Read issues", "Post in Slack", "Post in Teams")


def test_every_system_block_says_how_a_simulation_stands_in_for_it() -> None:
    """A mock is one of the systems the platform makes keys for, of the same block type."""
    for name, kind in NODE_CLASSES.blocks().items():
        entry = NODE_CLASSES.entry(name)
        assert isinstance(entry, OnType)
        if kind != "system":
            assert entry.simulated is None, name
            continue
        match entry.simulated:
            case Mocked(mock=mock):
                assert KEYS[mock].node_type == name
            case Pinned(why=why):
                assert why.endswith(".")
            case None:
                pytest.fail(f"{name} says nothing of how a simulation stands in for it")


# Unknown or unlisted blocks are refused, never passed through


def http_request() -> dict[str, Any]:
    return node("Call anything", "n8n-nodes-base.httpRequest", 4.2, {"url": "https://x.example"})


@pytest.mark.parametrize(
    ("extra", "why"),
    [
        (http_request(), "send what a run read"),
        (node("Run code", "n8n-nodes-base.code", 2), "runs code"),
        (node("Something new", "n8n-nodes-base.somethingNew", 1), "does not know"),
        (node("Old Slack", "n8n-nodes-base.slack", 1, {"text": "x"}), "version 1"),
        (
            node("Make a release", "n8n-nodes-base.github", 1.1, {"resource": "release"}),
            "release create",
        ),
        (
            node("Picked later", "n8n-nodes-base.github", 1.1, {"resource": "={{ $json.r }}"}),
            "expression",
        ),
        (node(START, "n8n-nodes-base.noOp"), "Two blocks"),
    ],
)
def test_a_block_the_class_file_does_not_turn_on_is_refused(extra: dict[str, Any], why: str):
    refused = plan_copy(version(extra), keys(), {})
    assert isinstance(refused, SetupRefused)
    assert [b.block for b in refused.blocks] == [extra["name"]]
    assert why in refused.blocks[0].why


def test_every_refused_block_is_named_at_once() -> None:
    refused = plan_copy(version(http_request(), node("Run code", "n8n-nodes-base.code", 2)), {}, {})
    assert isinstance(refused, SetupRefused)
    assert [b.block for b in refused.blocks] == ["Call anything", "Run code"]


# Only mock keys, never a real one


def test_the_copy_names_only_mock_keys_and_none_of_the_versions() -> None:
    setup = planned(jira=JIRA)
    made = {key.id for key in setup.keys}
    for each in setup.document["nodes"]:
        for kind, named in (each.get("credentials") or {}).items():
            assert named["id"] in made, (each["name"], kind)
    text = json.dumps(setup.document)
    for real in REAL:
        assert real not in text
    assert set(nodes_of(setup)["Read releases"]["credentials"]) == {"githubApi"}
    assert set(nodes_of(setup)["Post in Slack"]["credentials"]) == {"slackApi"}


def test_a_block_with_no_mock_names_no_key_at_all() -> None:
    copy = nodes_of(planned())
    for name in (START, "Read issues", "Is it new", "Ask for a yes", "Post in Teams"):
        assert "credentials" not in copy[name], name


def test_a_mocked_block_asks_for_the_mock_keys_type_as_the_platforms_key_does() -> None:
    """A Jira block set to sign in with a password asks for the mock key of n8n's default Jira
    type, as attach_keys does for the platform's key. One that asks for a type with a mock keeps
    it. What it does is left as it is."""
    copy = nodes_of(planned(jira=JIRA))
    issues = copy["Read issues"]
    assert issues["parameters"] == {
        "resource": "issue",
        "operation": "getAll",
        "jiraVersion": "cloud",
    }
    assert set(issues["credentials"]) == {"jiraSoftwareCloudApi"}
    pat = node("Read by PAT", "n8n-nodes-base.jira", 1, {"jiraVersion": "serverPat"}, REAL_JIRA)
    pat["parameters"].update(resource="issue", operation="get")
    copy = nodes_of(planned(version(pat), jira=JIRA))
    assert copy["Read by PAT"]["parameters"]["jiraVersion"] == "serverPat"
    assert set(copy["Read by PAT"]["credentials"]) == {"jiraSoftwareServerPatApi"}


def test_mock_keys_point_at_the_mocks_with_made_up_values() -> None:
    made = mock_keys(GITHUB, JIRA, SLACK_TOKEN, made_up=counter())
    data = {kind: dict(key.data) for kind, key in made.items()}
    assert data["githubApi"]["server"] == GITHUB
    assert data["jiraSoftwareCloudApi"]["domain"] == JIRA
    assert data["jiraSoftwareServerPatApi"]["domain"] == JIRA
    assert data["slackApi"] == {"accessToken": SLACK_TOKEN}
    assert data["githubApi"]["accessToken"].startswith("made-up-")
    assert data["jiraSoftwareCloudApi"]["apiToken"].startswith("made-up-")
    assert data["jiraSoftwareServerPatApi"]["personalAccessToken"].startswith("made-up-")
    assert all(key.id.startswith("sim-mock-") and key.kind == kind for kind, key in made.items())
    assert all(len(key.id) <= 16 for key in made.values()), "n8n takes ids of 16 at most"
    assert SLACK_TOKEN not in repr(made)
    assert set(mock_keys(None, None, None)) == set()
    first = mock_keys(GITHUB, None, None)["githubApi"].data["accessToken"]
    assert first != mock_keys(GITHUB, None, None)["githubApi"].data["accessToken"]


# Pins for blocks with no mock


def test_only_blocks_with_no_mock_are_pinned() -> None:
    given = version()
    given["pinData"] = {
        "Post in Teams": [{"json": {"skipped": "Teams notice skipped in the test run."}}],
        "Post in Slack": [{"json": {"skipped": "Slack notice skipped in the test run."}}],
        "Read releases": [{"json": {"tag_name": "1.2.16"}}],
        "Ask for a yes": [{"json": {}}],
    }
    setup = planned(given)
    pins = setup.document["pinData"]
    assert set(pins) == {"Read issues", "Post in Teams"}
    assert pins["Post in Teams"] == given["pinData"]["Post in Teams"]
    assert pins["Read issues"] == [{"json": {"pinned": setup.blocks[2].why}}]


def test_a_scenario_pins_a_block_with_no_mock() -> None:
    """The hook PR 5 fills: a scenario's own output for a block with no mock comes first."""
    setup = planned(pins={"Post in Teams": [{"id": "message-1"}], "Read issues": []})
    assert setup.document["pinData"]["Post in Teams"] == [{"json": {"id": "message-1"}}]
    assert setup.document["pinData"]["Read issues"] == []


@pytest.mark.parametrize("block", ["Read releases", "Ask for a yes", "Is it new", "Nowhere"])
def test_a_scenario_may_not_pin_a_block_that_runs(block: str) -> None:
    refused = plan_copy(version(), keys(), {block: [{"x": 1}]})
    assert isinstance(refused, SetupRefused)
    assert [b.block for b in refused.blocks] == [block]


def test_the_copy_keeps_only_the_settings_a_simulation_needs() -> None:
    setup = planned()
    assert setup.document["settings"] == {
        "executionOrder": "v1",
        "timezone": "Asia/Singapore",
        "saveManualExecutions": True,
        "saveExecutionProgress": True,
    }
    assert setup.document["name"] == "Release check"
    assert setup.document["connections"] == version()["connections"]


def test_the_version_is_left_as_it_was() -> None:
    given = version()
    before = json.dumps(given, sort_keys=True)
    planned(given, jira=JIRA)
    assert json.dumps(given, sort_keys=True) == before


# Making the copy in the simulation n8n


class FakeSimulationN8n:
    def __init__(self) -> None:
        self.done: list[tuple[str, Any]] = []
        self.keys: dict[str, tuple[str, str, dict[str, str], str]] = {}

    async def personal_project(self) -> str:
        self.done.append(("project", None))
        return "project-1"

    async def delete_credential(self, credential_id: str) -> None:
        self.done.append(("delete", credential_id))
        self.keys.pop(credential_id, None)

    async def create_credential(
        self, credential_id: str, name: str, kind: str, data: Mapping[str, str], project_id: str
    ) -> N8nCredential:
        self.done.append(("credential", credential_id))
        self.keys[credential_id] = (name, kind, dict(data), project_id)
        now = datetime(2026, 11, 24, tzinfo=UTC)
        return N8nCredential(credential_id, name, kind, now, now, project_id)

    async def create(self, document: Mapping[str, Any]) -> N8nWorkflow:
        self.done.append(("workflow", document))
        return N8nWorkflow(f"copy-{len(self.done)}", "v1", None, dict(document))


@pytest.mark.anyio
async def test_the_copy_goes_to_the_simulation_n8n_with_its_mock_keys_made_once() -> None:
    n8n = FakeSimulationN8n()
    setups = MockSetups(n8n, keys())
    copied = await setups.copy(version(), {})
    assert isinstance(copied, Copied)
    made = [what for what, _ in n8n.done]
    assert made == ["project", "delete", "credential", "delete", "credential", "workflow"]
    assert {kind for _, kind, _, _ in n8n.keys.values()} == {"githubApi", "slackApi"}
    assert {project for _, _, _, project in n8n.keys.values()} == {"project-1"}
    assert copied.blocks == planned().blocks
    assert copied.workflow_id == "copy-6"
    assert copied.not_tried == ("Read issues", "Post in Teams")

    again = await setups.copy(version(), {})
    assert isinstance(again, Copied)
    assert [what for what, _ in n8n.done[len(made) :]] == ["workflow"]


@pytest.mark.anyio
async def test_a_refused_version_makes_nothing() -> None:
    n8n = FakeSimulationN8n()
    refused = await MockSetups(n8n, keys()).copy(version(http_request()), {})
    assert isinstance(refused, SetupRefused)
    assert n8n.done == []


def test_a_block_mode_is_plain_data() -> None:
    mode = BlockMode("Post in Teams", "n8n-nodes-base.microsoftTeams", "pinned", why="No mock.")
    assert (mode.mock, mode.why) == (None, "No mock.")
