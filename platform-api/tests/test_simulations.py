"""A simulation (ADR 0054, PR 5): code runs each scenario on a copy of its own in the simulation
n8n, grades it from the gateway's record and n8n's, and deletes the copy, whatever happened. Here a
small stand-in for the simulation n8n runs each copy in a line, calling the gateway as our blocks
do, and plays mock GitHub as the mock does."""

import json
import re
import secrets
from collections.abc import Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from platform_api.orchestration.mock_setup import MockSetups, SetupRefused, mock_keys
from platform_api.orchestration.n8n import ExecutionRecord, N8nError, NodeError, NodeRun
from platform_api.orchestration.n8n_calls import (
    AgentCall,
    Answer,
    AskCall,
    NodeCall,
    NothingToChange,
    ProposeCall,
    ReadCall,
    Refused,
    TellCall,
    TryLater,
    Waiting,
    WriteCall,
)
from platform_api.orchestration.recorded_samples import RecordedSamples
from platform_api.orchestration.scenario_grades import ENDED
from platform_api.orchestration.scenarios import KINDS, GitHubPlay, ScenarioSpec
from platform_api.orchestration.simulated_calls import SimulatedCalls
from platform_api.orchestration.simulation_gateway import gateway_app
from platform_api.orchestration.simulations import Simulation, SimulationRefused, Simulations
from platform_api.shared import N8nExecutionId
from tests.test_mock_setup import FakeSimulationN8n
from tests.test_scenarios import (
    GITHUB_URL,
    START,
    github_read,
    jira_read,
    our_read,
    release_check,
)
from tests.test_simulation_gateway import SETTINGS, FakeWaker, no_wait, signed

DROPPED = (
    "The connection to the server was closed unexpectedly, perhaps it is offline. You can retry "
    "the request immediately or wait and retry later."
)
NOT_FOUND = "The resource you are requesting could not be found"
EXIT_OF = {"no_answer": 0, "yes": 1, "no": 2}
PLANNERS_RELEASE_CHECK = Path(__file__).parent / "golden" / "n8n" / "release_check.json"
"""The release check the Planner lays out, with the yes the safety checker added (test_layout)."""
IS_TRUE = re.compile(r"^=\{\{ \$json\.(\w+) \}\}$")


class FakeMockGitHub:
    """Mock GitHub as a simulation steers it."""

    def __init__(self) -> None:
        self.played: list[GitHubPlay | None] = []
        self.now: GitHubPlay | None = None

    async def play(self, play: GitHubPlay | None) -> None:
        self.played.append(play)
        self.now = play


class LineN8n(FakeSimulationN8n):
    """The simulation n8n: it keeps the copies, and runs one by hand in a line from Start from the
    Portal, following the first link of each exit, as n8n runs a line of blocks."""

    def __init__(self, github: FakeMockGitHub) -> None:
        super().__init__()
        self.github = github
        self.calls: SimulatedCalls | None = None
        self.waker: FakeWaker | None = None
        self.copies: dict[str, dict[str, Any]] = {}
        self.records: dict[str, ExecutionRecord] = {}
        self.deleted: list[str] = []
        self.served: dict[str, list[Any]] = {}
        self.fail_runs = False
        self.fail_deletes = False
        self.hang_runs = False
        """Each run by hand stays running, as a run past the wait limit does."""
        self.asked: list[dict[str, Any]] = []
        """The start item of each run by hand n8n was asked for."""
        self.order: list[tuple[str, str]] = []
        """Each stop and delete, in turn, with the execution or workflow it was for."""

    async def create(self, document: Mapping[str, Any]) -> Any:
        made = await super().create(document)
        self.copies[made.id] = dict(document)
        return made

    async def delete(self, workflow_id: str) -> None:
        self.deleted.append(workflow_id)
        self.order.append(("delete", workflow_id))
        if self.fail_deletes:
            raise RuntimeError("something nobody expected")
        self.copies.pop(workflow_id, None)

    async def execution(self, execution_id: str, data: bool = True) -> ExecutionRecord | None:
        return self.records.get(execution_id)

    async def run_draft(self, workflow_id: str, item: Mapping[str, Any]) -> str:
        self.asked.append(dict(item))
        if self.fail_runs:
            raise N8nError("the simulation n8n is down")
        execution = str(len(self.records) + 100)
        nonce = str(item["nonce"])
        self.records[execution] = record(execution, workflow_id, nonce, "running", {})
        if not self.hang_runs:
            await self._run(execution, workflow_id, nonce, self.copies[workflow_id])
        return execution

    async def stop(self, execution_id: str) -> None:
        """n8n's stop: a run still going or waiting ends as canceled."""
        self.order.append(("stop", execution_id))
        found = self.records.get(execution_id)
        if found is not None and found.status not in ENDED:
            self.records[execution_id] = replace(found, status="canceled")

    async def _run(
        self, execution: str, workflow: str, nonce: str, document: Mapping[str, Any]
    ) -> None:
        assert self.calls is not None and self.waker is not None
        nodes = {n["name"]: n for n in document["nodes"]}
        pins: Mapping[str, Any] = document.get("pinData") or {}
        ran: dict[str, str] = {}
        name: str | None = START
        before: str | None = None
        while name is not None:
            node = nodes[name]
            exit_index, stop = 0, None
            if name in pins:
                count = len(pins[name])
            elif node["type"].startswith("CUSTOM."):
                count, exit_index, stop = await self._ours(execution, node)
            elif node["type"] == "n8n-nodes-base.github":
                count, stop = self._github(node)
            elif node["type"] == "n8n-nodes-base.if":
                count, exit_index = 1, if_exit(node, self.served.get(before or "", []))
            else:
                count = 1
            ran[name] = "error" if stop else "success"
            if name not in self.served:
                self.served[name] = []
            if stop is not None:
                self.records[execution] = record(
                    execution, workflow, nonce, "error", ran, name, stop, node
                )
                return
            if count == 0:
                break
            before, name = name, following(document, name, exit_index)
        self.records[execution] = record(execution, workflow, nonce, "success", ran)

    async def _ours(self, execution: str, node: Mapping[str, Any]) -> tuple[int, int, str | None]:
        assert self.calls is not None and self.waker is not None
        p = node["parameters"]
        kind = node["type"].removeprefix("CUSTOM.wab")
        match kind:
            case "Read":
                work: Any = ReadCall(p.get("source", "github_releases"), p.get("place", ""), None)
            case "Agent":
                rows = (p.get("inputs") or {}).get("input") or []
                work = AgentCall(p.get("agent", ""), {r["name"]: r["value"] for r in rows})
            case "ProposeChange":
                work = ProposeCall(p["action"], p["place"], p["title"], p["body"], p.get("subject"))
            case "AskForYes":
                work = AskCall("http://n8n:5678/webhook-waiting/1?signature=made-up")
            case "MakeApprovedChanges":
                work = WriteCall()
            case "Tell":
                work = TellCall("channel", "result")
            case _:
                return 1, 0, None
        answer = await self.calls.call(NodeCall(N8nExecutionId(execution), node["name"], work))
        match answer:
            case Answer(items):
                self.served[node["name"]] = [dict(item) for item in items]
                return (len(items) if kind == "Read" else 1), 0, None
            case Waiting():
                await self.calls.settle()
                decision = self.waker.wakes[-1][2]
                return 1, EXIT_OF[decision], None
            case NothingToChange():
                return 1, 3, None
            case Refused(detail=detail) | TryLater(detail):
                return 0, 0, detail
            case _:
                return 1, 0, None

    def _github(self, node: Mapping[str, Any]) -> tuple[int, str | None]:
        play = self.github.now or GitHubPlay("ok", None)
        p = node["parameters"]
        if play.mode == "not_found" or f"{p.get('owner')}/{p.get('repository')}" in play.gone:
            return 0, NOT_FOUND
        if play.mode == "drop":
            return 0, DROPPED
        served = [{"tag_name": "1.2.16"}] if play.releases is None else list(play.releases)
        self.served[node["name"]] = served
        return len(served), None


def if_exit(node: Mapping[str, Any], items: list[Any]) -> int:
    """n8n's IF as the Planner's layout uses it: is one field of the item before it true. Exit 0
    is true and 1 is false. A field the item lacks is false, as the simulation n8n showed for
    Newer? on 25 Nov."""
    [condition] = node["parameters"]["conditions"]["conditions"]
    assert condition["operator"] == {"type": "boolean", "operation": "true", "singleValue": True}
    field = IS_TRUE.match(condition["leftValue"])
    assert field is not None, condition["leftValue"]
    item = items[0] if items else {}
    return 0 if item.get(field.group(1)) is True else 1


def following(document: Mapping[str, Any], name: str, exit_index: int) -> str | None:
    outputs = (document["connections"].get(name) or {}).get("main") or []
    links = outputs[exit_index] if exit_index < len(outputs) else []
    return str(links[0]["node"]) if links else None


def record(
    execution: str,
    workflow: str,
    nonce: str,
    status: str,
    ran: Mapping[str, str],
    failed: str | None = None,
    error: str | None = None,
    block: Mapping[str, Any] | None = None,
) -> ExecutionRecord:
    """n8n's record, with each block's last try as its run data holds it. A not found came with
    GitHub's answer, a 404, and a dropped connection with none."""
    answer = "404" if error == NOT_FOUND else None
    nodes = {
        name: NodeRun(state, (NodeError(error, answer),) if name == failed and error else ())
        for name, state in ran.items()
    }
    return ExecutionRecord(
        execution,
        workflow,
        status,
        "manual",
        None,
        "v1",
        nonce,
        failed,
        error,
        dict(ran),
        None if block is None else dict(block),
        nodes,
    )


class Ticks:
    """A clock that moves only when the simulation waits."""

    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class Stack:
    def __init__(self) -> None:
        self.github = FakeMockGitHub()
        self.n8n = LineN8n(self.github)
        self.waker = FakeWaker()
        self.calls = SimulatedCalls(self.n8n, self.waker, None, sleep=no_wait)
        self.n8n.calls, self.n8n.waker = self.calls, self.waker
        self.setups = MockSetups(self.n8n, mock_keys(GITHUB_URL, None, None))
        self.ticks = Ticks()
        self.simulations = Simulations(
            self.setups,
            self.calls,
            self.n8n,
            self.github,
            sleep=self.ticks.sleep,
            clock=self.ticks.clock,
        )

    async def simulate(
        self,
        version: dict[str, Any],
        scenarios: list[dict[str, Any]] | None = None,
        samples: RecordedSamples | None = None,
    ) -> Simulation | SimulationRefused | SetupRefused:
        given = None if scenarios is None else [ScenarioSpec.model_validate(s) for s in scenarios]
        return await self.simulations.simulate(version, given, samples or RecordedSamples())


@pytest.fixture
def stack() -> Stack:
    return Stack()


def verdicts(simulation: object) -> dict[str, str]:
    assert isinstance(simulation, Simulation), simulation
    return {graded.name: graded.verdict for graded in simulation.results}


# Running the six scenarios


@pytest.mark.anyio
async def test_a_release_check_passes_each_of_the_six_scenarios(stack: Stack) -> None:
    simulation = await stack.simulate(release_check())
    assert verdicts(simulation) == dict.fromkeys(KINDS, "passed")
    assert isinstance(simulation, Simulation)
    assert (simulation.tried, simulation.passed) == (6, 6)
    assert stack.github.played == [], "no block reads mock GitHub"


@pytest.mark.anyio
async def test_the_release_check_the_planner_lays_out_passes_each_of_the_six_scenarios(
    stack: Stack,
) -> None:
    """Its Version checker proposes the change itself, and Newer? goes on to Ask for approval only
    when the checker's answer says newer."""
    simulation = await stack.simulate(json.loads(PLANNERS_RELEASE_CHECK.read_text()))
    assert verdicts(simulation) == dict.fromkeys(KINDS, "passed"), simulation
    assert isinstance(simulation, Simulation)
    happy = next(graded for graded in simulation.results if graded.kind == "happy_path")
    assert "Ask for approval" in happy.ran and "Nothing to change" not in happy.ran


@pytest.mark.anyio
async def test_each_scenario_runs_on_a_copy_of_its_own_that_is_deleted_after_grading(
    stack: Stack,
) -> None:
    await stack.simulate(release_check())
    made = [doc for what, doc in stack.n8n.done if what == "workflow"]
    assert len(made) == len(KINDS)
    assert len(stack.n8n.deleted) == len(KINDS)
    assert stack.n8n.copies == {}, "/copies never removes one, so the simulation does"


@pytest.mark.anyio
async def test_mock_github_is_played_for_each_scenario_and_set_back_after(stack: Stack) -> None:
    simulation = await stack.simulate(release_check([github_read()]))
    assert verdicts(simulation) == dict.fromkeys(KINDS, "passed")
    plays = stack.github.played
    assert plays[1::2] == [None] * len(KINDS), "set back after each scenario"
    assert [p.mode for p in plays[0::2] if p is not None] == [
        "ok",
        "ok",
        "not_found",
        "drop",
        "ok",
        "ok",
    ]


@pytest.mark.anyio
async def test_the_copy_is_deleted_and_mock_github_set_back_even_when_a_run_fails(
    stack: Stack,
) -> None:
    stack.n8n.fail_runs = True
    with pytest.raises(N8nError):
        await stack.simulate(release_check([github_read()]))
    assert len(stack.n8n.deleted) == 1
    assert stack.n8n.copies == {}
    assert stack.github.played[-1] is None


@pytest.mark.anyio
async def test_mock_github_is_set_back_even_when_the_delete_fails_unexpectedly(
    stack: Stack,
) -> None:
    stack.n8n.fail_deletes = True
    with pytest.raises(RuntimeError):
        await stack.simulate(release_check([github_read()]))
    assert len(stack.n8n.deleted) == 1
    assert stack.github.played[-1] is None


@pytest.mark.anyio
async def test_a_run_still_going_when_the_wait_ends_is_stopped_before_its_copy_is_deleted(
    stack: Stack,
) -> None:
    """n8n 2.42.6 deletes a workflow's executions with it, but stops none that is running or
    waiting (WorkflowService.delete), so the run would go on calling the gateway."""
    stack.n8n.hang_runs = True
    simulation = await stack.simulate(release_check(), [{"kind": "happy_path"}])
    assert verdicts(simulation) == {"happy_path": "failed"}
    [execution] = stack.n8n.records
    [copy] = stack.n8n.deleted
    assert stack.n8n.order == [("stop", execution), ("delete", copy)]
    assert stack.n8n.records[execution].status == "canceled"


@pytest.mark.anyio
async def test_a_run_that_ended_is_not_stopped(stack: Stack) -> None:
    await stack.simulate(release_check())
    assert [what for what, _ in stack.n8n.order] == ["delete"] * len(KINDS)


@pytest.mark.anyio
async def test_the_gateway_forgets_the_run_of_a_start_n8n_never_ran(stack: Stack) -> None:
    stack.n8n.fail_runs = True
    with pytest.raises(N8nError):
        await stack.simulate(release_check())
    [item] = stack.n8n.asked
    assert stack.calls.run(str(item["nonce"])) is None


@pytest.mark.anyio
async def test_a_scenario_no_block_can_play_is_never_run(stack: Stack) -> None:
    simulation = await stack.simulate(release_check([jira_read()]))
    assert verdicts(simulation) == {
        **dict.fromkeys(KINDS, "passed"),
        "source_not_found": "not_tried",
        "timeout": "not_tried",
    }
    assert isinstance(simulation, Simulation)
    assert (simulation.tried, simulation.passed) == (4, 4)
    assert len(stack.n8n.deleted) == 4


@pytest.mark.anyio
async def test_a_scenario_that_does_not_fit_the_version_is_refused_and_nothing_is_made(
    stack: Stack,
) -> None:
    refused = await stack.simulate(
        release_check(), [{"kind": "happy_path", "reads": {"Nowhere": {"serve": "recorded"}}}]
    )
    assert refused == SimulationRefused(
        ('happy_path: The version has no block "Nowhere" that reads a source.',)
    )
    assert stack.n8n.done == []


@pytest.mark.anyio
async def test_a_version_the_mock_setup_refuses_makes_nothing(stack: Stack) -> None:
    version = release_check()
    version["nodes"].append(
        {"name": "Call", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "parameters": {}}
    )
    assert isinstance(await stack.simulate(version), SetupRefused)
    assert stack.n8n.done == []


@pytest.mark.anyio
async def test_given_scenarios_run_in_place_of_the_templates(stack: Stack) -> None:
    simulation = await stack.simulate(
        release_check(),
        [
            {"kind": "approver_says_no"},
            {
                "kind": "odd_data",
                "reads": {"Read releases": {"serve": "varied", "vary": ["suffix"]}},
            },
        ],
    )
    assert verdicts(simulation) == {"approver_says_no": "passed", "odd_data": "passed"}
    assert isinstance(simulation, Simulation)
    assert stack.n8n.served["Read releases"][0]["id"].endswith("-rc.1")
    assert simulation.coverage.kinds_without_a_scenario == (
        "happy_path",
        "nothing_new",
        "source_not_found",
        "timeout",
    )


@pytest.mark.anyio
async def test_a_sample_from_a_real_run_is_served_only_as_scrubbed(stack: Stack) -> None:
    who = f"person.{secrets.token_hex(4)}@example.com"
    samples = RecordedSamples()
    samples.record(
        "read.release",
        [{"kind": "release", "id": "2.0.0", "name": who, "published_at": "2026-11-01", "by": who}],
        "real_run",
        block="Read releases",
    )
    await stack.simulate(release_check(), [{"kind": "happy_path"}], samples)
    assert stack.n8n.served["Read releases"][0]["id"] == "2.0.0"
    assert who not in json.dumps(stack.n8n.served)


# The gateway's route


class GatewayWithRuns:
    def __init__(self) -> None:
        self.stack = Stack()
        self.client = TestClient(
            gateway_app(SETTINGS, self.stack.calls, self.stack.setups, self.stack.simulations)
        )

    def post(self, body: dict[str, Any], secret: str | None = None) -> Any:
        raw = json.dumps(body).encode()
        path = "/simulation/v1/simulations"
        headers = signed("POST", path, raw) if secret is None else signed("POST", path, raw, secret)
        return self.client.post(path, content=raw, headers=headers)


@pytest.fixture
def gw() -> Iterator[GatewayWithRuns]:
    gateway = GatewayWithRuns()
    with gateway.client:
        yield gateway


def test_the_gateway_runs_a_simulation_signed_with_the_start_secret(gw: GatewayWithRuns) -> None:
    answer = gw.post({"version": release_check()})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["tried"], body["passed"]) == (6, 6)
    assert [r["kind"] for r in body["results"]] == list(KINDS)
    happy = body["results"][0]
    assert set(happy) == {
        "name",
        "kind",
        "verdict",
        "expected",
        "happened",
        "ran",
        "not_tried",
        "ending",
        "stopped_at",
        "plays",
        "reached",
    }
    assert happy["reached"] == [
        "agent:release_checker",
        "propose:jira.create_ticket",
        "read:github_releases",
    ]
    assert body["named"] == [
        "agent:release_checker",
        "propose:jira.create_ticket",
        "read:github_releases",
        "tell:channel",
    ]
    assert (body["scenarios_from"], body["refused"]) == ("templates", [])
    assert body["coverage"]["not_tried"] == [
        {"block": "Tell", "why": "A simulation never writes, so a block after a write never runs."}
    ]
    assert {b["block"]: b["mode"] for b in body["blocks"]}[START] == "ours"


def test_the_gateway_scrubs_the_samples_it_is_given(gw: GatewayWithRuns) -> None:
    who = f"person.{secrets.token_hex(4)}@example.com"
    sample = {
        "id": "real-1",
        "answer": "read.release",
        "block": "Read releases",
        "items": [{"kind": "release", "id": "2.0.0", "name": who, "by": who}],
    }
    scenario = {
        "kind": "happy_path",
        "reads": {"Read releases": {"serve": "recorded", "sample": "real-1"}},
    }
    answer = gw.post({"version": release_check(), "scenarios": [scenario], "samples": [sample]})
    assert answer.status_code == 200, answer.text
    assert who not in json.dumps(gw.stack.n8n.served)


def test_a_simulation_the_scenarios_do_not_fit_is_refused_in_words(gw: GatewayWithRuns) -> None:
    scenario = {"kind": "timeout", "reads": {"Read releases": {"serve": "not_found"}}}
    answer = gw.post({"version": release_check(), "scenarios": [scenario]})
    assert answer.status_code == 422
    assert answer.json() == {
        "detail": "The scenarios don't fit this version, so nothing ran.",
        "problems": [
            'timeout: "Timeout" plays at least one read as too slow, and serves every other '
            "as recorded."
        ],
    }
    assert gw.stack.n8n.done == []


def test_a_simulation_not_signed_with_the_start_secret_is_refused(gw: GatewayWithRuns) -> None:
    assert gw.post({"version": release_check()}, secrets.token_hex(24)).status_code == 401
    assert gw.stack.n8n.done == []


# The scenario writer's scenarios (PR 6)

UNFIT = [{"kind": "happy_path", "reads": {"Nowhere": {"serve": "recorded"}}}]


@pytest.mark.anyio
async def test_written_scenarios_that_do_not_fit_fall_back_to_the_templates_when_asked(
    stack: Stack,
) -> None:
    given = [ScenarioSpec.model_validate(s) for s in UNFIT]
    simulation = await stack.simulations.simulate(
        release_check(), given, RecordedSamples(), fall_back=True
    )
    assert verdicts(simulation) == dict.fromkeys(KINDS, "passed")
    assert isinstance(simulation, Simulation)
    assert simulation.scenarios_from == "templates"
    assert simulation.refused == (
        'happy_path: The version has no block "Nowhere" that reads a source.',
    )


@pytest.mark.anyio
async def test_written_scenarios_that_fit_run_as_given(stack: Stack) -> None:
    given = [ScenarioSpec.model_validate({"kind": "approver_says_no"})]
    simulation = await stack.simulations.simulate(
        release_check(), given, RecordedSamples(), fall_back=True
    )
    assert verdicts(simulation) == {"approver_says_no": "passed"}
    assert isinstance(simulation, Simulation)
    assert (simulation.scenarios_from, simulation.refused) == ("given", ())


@pytest.mark.anyio
async def test_a_scenario_names_how_it_ended_where_it_stopped_and_its_plays(stack: Stack) -> None:
    given = [
        ScenarioSpec.model_validate(
            {"kind": "source_not_found", "reads": {"Read releases": {"serve": "not_found"}}}
        )
    ]
    simulation = await stack.simulations.simulate(release_check(), given, RecordedSamples())
    assert isinstance(simulation, Simulation)
    (graded,) = simulation.results
    assert (graded.verdict, graded.ending, graded.stopped_at) == (
        "passed",
        "stopped",
        "Read releases",
    )
    assert [(p.block, p.serve) for p in graded.plays] == [("Read releases", "not_found")]


def test_the_gateway_falls_back_to_the_templates_and_says_why(gw: GatewayWithRuns) -> None:
    answer = gw.post({"version": release_check(), "scenarios": UNFIT, "fall_back": True})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["tried"], body["passed"]) == (6, 6)
    assert body["scenarios_from"] == "templates"
    assert body["refused"] == [
        'happy_path: The version has no block "Nowhere" that reads a source.'
    ]
    odd = body["results"][5]
    assert odd["plays"] == [
        {
            "block": "Read releases",
            "serve": "varied",
            "vary": ["suffix", "empty_field", "long_text"],
        }
    ]


def post_plan(gw: GatewayWithRuns, body: dict[str, Any], secret: str | None = None) -> Any:
    raw = json.dumps(body).encode()
    path = "/simulation/v1/plans"
    headers = signed("POST", path, raw) if secret is None else signed("POST", path, raw, secret)
    return gw.client.post(path, content=raw, headers=headers)


def test_the_gateway_answers_a_versions_plan_for_the_scenario_writer(gw: GatewayWithRuns) -> None:
    who = f"person.{secrets.token_hex(4)}@example.com"
    sample = {
        "id": "real-1",
        "answer": "read.release",
        "block": "Read releases",
        "items": [{"kind": "release", "id": "2.0.0", "name": who, "by": who}],
    }
    version = release_check([our_read(), github_read()])
    answer = post_plan(gw, {"version": version, "samples": [sample]})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["kinds"] == list(KINDS)
    blocks = {b["name"]: b for b in body["blocks"]}
    assert blocks["Read releases"] == {
        "name": "Read releases",
        "node_type": "CUSTOM.wabRead",
        "role": "read",
        "mode": "ours",
        "mock": None,
        "answer": "read.release",
        "plays": ["recorded", "varied", "empty", "not_found", "too_slow"],
        "varies": ["suffix", "empty_field", "long_text"],
    }
    assert (blocks["Compare"]["role"], blocks["Compare"]["plays"]) == (
        "agent",
        ["recorded", "too_slow"],
    )
    assert blocks["GitHub releases"]["mode"] == "mock"
    assert [s["id"] for s in body["samples"]] == [
        "real-1",
        "made_up.github.release",
        "made_up.read.release",
    ]
    assert body["samples"][0]["items"] == [{"kind": "release", "id": "2.0.0", "name": "2.0.0"}]
    assert who not in answer.text
    assert gw.stack.n8n.done == [], "a plan makes nothing"


def test_a_plan_is_refused_without_the_start_secret_or_for_a_version_it_cannot_run(
    gw: GatewayWithRuns,
) -> None:
    assert post_plan(gw, {"version": release_check()}, secrets.token_hex(24)).status_code == 401
    version = release_check()
    version["nodes"].append(
        {"name": "Call", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "parameters": {}}
    )
    refused = post_plan(gw, {"version": version})
    assert refused.status_code == 422
    assert [b["block"] for b in refused.json()["blocks"]] == ["Call"]
