"""The simulation gateway (ADR 0054, PR 3) answers our blocks in the simulation n8n as the real API
does, with the ADR's differences. A start must be signed with the simulation's own start secret.
Every call links to its simulated run by the start's nonce. Ask for a yes gets the scenario's
answer and asks nobody. Every write is refused, and what it would have written is kept. Tell
sends nothing. The record is what the scenario grader reads."""

import json
import secrets
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_api.auth import ConfigError
from platform_api.orchestration import n8n_calls_http
from platform_api.orchestration.dispatch import (
    Delivered,
    DispatchFailure,
    HeldWait,
    N8nWaker,
    WakeAnswer,
    WakeDecision,
    wake_mac,
)
from platform_api.orchestration.mock_setup import MockSetups, mock_keys
from platform_api.orchestration.n8n import ExecutionRecord
from platform_api.orchestration.n8n_calls import (
    TEST_RUN_WRITES_NOTHING,
    AskCall,
    NodeCall,
    ProposeCall,
    ReadFailed,
    ReadItems,
    TellCall,
    Waiting,
    WriteCall,
)
from platform_api.orchestration.simulated_calls import (
    MockGitHub,
    Scenario,
    SimulatedCalls,
    Unsealed,
)
from platform_api.orchestration.simulation_gateway import (
    GatewaySettings,
    control_signature,
    gateway_app,
    gateway_settings_from_env,
)
from platform_api.orchestration.simulations import Simulations
from platform_api.settings import N8nOwner
from platform_api.shared import ApprovalId, N8nExecutionId
from tests.declared import FakeNodeCalls
from tests.test_mock_setup import FakeSimulationN8n, http_request, version

# Made up at run time. None is a real key.
NODE_KEY = secrets.token_hex(24)
START_SECRET = secrets.token_hex(24)
OTHER_SECRET = secrets.token_hex(24)
SLACK_TOKEN = secrets.token_hex(16)
SETTINGS = GatewaySettings(
    node_key=NODE_KEY,
    start_secret=START_SECRET,
    n8n_base_url="http://n8n:5678",
    n8n_owner=N8nOwner("owner@simulation.example", secrets.token_hex(12)),
    mock_github_url="http://mock-github:8200",
    mock_slack_token=SLACK_TOKEN,
)
WORKFLOW = "wf_sim"
RELEASE = {"kind": "release", "id": "1.2.16", "name": "1.2.16", "published_at": "2026-10-28"}
RESUME = "http://n8n:5678/webhook-waiting/41?signature=made-up"
FROM = {"execution_id": "41", "workflow_id": WORKFLOW, "mode": "manual"}
READ = {**FROM, "node_name": "Read releases", "source": "github_releases", "place": "a/b"}
AGENT = {**FROM, "node_name": "Compare", "agent": "crd_compare", "inputs": {"release": "1.2.16"}}
PROPOSE = {
    **FROM,
    "node_name": "Propose a change",
    "action": "jira.create_ticket",
    "place": "MOCK",
    "title": "Upgrade LangGraph",
    "body": "1.2.16 is out.",
    "subject": "",
}
ASK = {**FROM, "node_name": "Ask for a yes", "resume_url": RESUME}
WRITE = {**FROM, "node_name": "Make the approved changes"}
TELL = {**FROM, "node_name": "Tell", "where": "channel", "what": "result"}
KEY = {"X-Wab-Node-Key": NODE_KEY}


class FakeN8n:
    """The simulation n8n's records of its executions."""

    def __init__(self) -> None:
        self.records: dict[str, ExecutionRecord] = {}

    async def execution(self, execution_id: str, data: bool = True) -> ExecutionRecord | None:
        return self.records.get(execution_id)

    def started(self, execution: str, nonce: str | None, workflow: str = WORKFLOW) -> None:
        self.records[execution] = ExecutionRecord(
            execution, workflow, "running", "manual", None, "v1", nonce
        )


class FakeWaker:
    def __init__(self, refusals: int = 0) -> None:
        self.refusals = refusals
        self.wakes: list[tuple[HeldWait, ApprovalId, WakeDecision]] = []

    async def wake(
        self, held: HeldWait, request_id: ApprovalId, decision: WakeDecision
    ) -> WakeAnswer:
        if self.refusals:
            self.refusals -= 1
            raise DispatchFailure("n8n answered the wake with 404")
        self.wakes.append((held, request_id, decision))
        return Delivered()


class FakeGitHub:
    def __init__(self, answer: ReadItems | ReadFailed) -> None:
        self.answer = answer
        self.asked: list[str] = []

    async def releases(self, repo: str) -> ReadItems | ReadFailed:
        self.asked.append(repo)
        return self.answer


async def no_wait(seconds: float) -> None:
    return None


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def scenario(
    blocks: dict[str, Any] | None = None, approver: str = "yes", name: str = "happy_path"
) -> dict[str, Any]:
    default = {
        "Read releases": {"serve": "recorded", "items": [RELEASE]},
        "Compare": {"serve": "recorded", "items": [{"summary": "1.2.16 is new."}]},
    }
    return {"name": name, "blocks": default if blocks is None else blocks, "approver": approver}


def signed(
    method: str, path: str, body: bytes, secret: str = START_SECRET, expires: int | None = None
) -> dict[str, str]:
    expires = int(time.time()) + 60 if expires is None else expires
    return {
        "Content-Type": "application/json",
        "X-Wab-Expires": str(expires),
        "X-Wab-Signature": control_signature(secret, method, path, expires, body),
    }


class Gateway:
    def __init__(self, github: FakeGitHub | None = None, waker: FakeWaker | None = None) -> None:
        self.n8n = FakeN8n()
        self.waker = waker or FakeWaker()
        self.github = github or FakeGitHub([RELEASE])
        self.clock = Clock()
        self.calls = SimulatedCalls(
            self.n8n, self.waker, self.github, clock=self.clock, sleep=no_wait
        )
        self.simulation_n8n = FakeSimulationN8n()
        keys = mock_keys(SETTINGS.mock_github_url, None, SETTINGS.mock_slack_token)
        self.setups = MockSetups(self.simulation_n8n, keys)
        simulations = Simulations(self.setups, self.calls, self.simulation_n8n, None)
        self.client = TestClient(gateway_app(SETTINGS, self.calls, self.setups, simulations))

    def start(self, given: dict[str, Any] | None = None, workflow: str = WORKFLOW) -> str:
        body = json.dumps({"workflow_id": workflow, "scenario": given or scenario()}).encode()
        path = "/simulation/v1/starts"
        answer = self.client.post(path, content=body, headers=signed("POST", path, body))
        assert answer.status_code == 201, answer.text
        return str(answer.json()["nonce"])

    def run(self, given: dict[str, Any] | None = None, execution: str = "41") -> str:
        nonce = self.start(given)
        self.n8n.started(execution, nonce)
        return nonce

    def call(self, path: str, body: dict[str, Any]) -> httpx.Response:
        return self.client.post(f"/internal/v1/n8n/{path}", json=body, headers=KEY)

    def record(self, nonce: str) -> dict[str, Any]:
        path = f"/simulation/v1/runs/{nonce}"
        answer = self.client.get(path, headers=signed("GET", path, b""))
        assert answer.status_code == 200, answer.text
        found: dict[str, Any] = answer.json()
        return found


@pytest.fixture
def gw() -> Iterator[Gateway]:
    gateway = Gateway()
    with gateway.client:
        yield gateway


# A start, and who may read the record


def test_a_start_signed_with_the_simulations_own_secret_is_taken(gw: Gateway) -> None:
    body = json.dumps({"workflow_id": WORKFLOW, "scenario": scenario()}).encode()
    path = "/simulation/v1/starts"
    answer = gw.client.post(path, content=body, headers=signed("POST", path, body))
    assert answer.status_code == 201
    started = answer.json()
    assert started["item"] == {"nonce": started["nonce"], "kind": "test", "workflow_id": WORKFLOW}


STARTS = "/simulation/v1/starts"


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(lambda body: signed("POST", STARTS, body, OTHER_SECRET), id="other-secret"),
        pytest.param(lambda body: {"Content-Type": "application/json"}, id="unsigned"),
        pytest.param(lambda body: signed("POST", STARTS, body + b" "), id="changed"),
        pytest.param(lambda body: signed("POST", "/simulation/v1/runs", body), id="other-path"),
        pytest.param(
            lambda body: signed("POST", STARTS, body, expires=int(time.time()) - 120),
            id="expired",
        ),
        pytest.param(
            lambda body: signed("POST", STARTS, body, expires=int(time.time()) + 3600),
            id="too-far-ahead",
        ),
    ],
)
def test_any_other_start_is_refused(gw: Gateway, headers: Any) -> None:
    body = json.dumps({"workflow_id": WORKFLOW, "scenario": scenario()}).encode()
    answer = gw.client.post(STARTS, content=body, headers=headers(body))
    assert answer.status_code == 401
    assert set(answer.json()) == {"detail"}


def test_a_signed_start_with_a_bad_scenario_is_refused_without_echo(gw: Gateway) -> None:
    secret_words = "never-shown-" + secrets.token_hex(4)
    bad = scenario({"Read releases": {"serve": "invent", "items": [{"x": secret_words}]}})
    body = json.dumps({"workflow_id": WORKFLOW, "scenario": bad}).encode()
    path = "/simulation/v1/starts"
    answer = gw.client.post(path, content=body, headers=signed("POST", path, body))
    assert answer.status_code == 422
    assert secret_words not in answer.text


def test_the_record_needs_the_same_signature(gw: Gateway) -> None:
    nonce = gw.start()
    path = f"/simulation/v1/runs/{nonce}"
    assert gw.client.get(path).status_code == 401
    assert gw.client.get(path, headers=signed("GET", path, b"", OTHER_SECRET)).status_code == 401
    assert gw.record(nonce)["scenario"] == "happy_path"
    missing = "/simulation/v1/runs/sim_unknown"
    assert gw.client.get(missing, headers=signed("GET", missing, b"")).status_code == 404


def test_a_node_call_needs_the_simulations_node_key(gw: Gateway) -> None:
    gw.run()
    assert gw.client.post("/internal/v1/n8n/calls/read", json=READ).status_code == 401
    other = {"X-Wab-Node-Key": secrets.token_hex(24)}
    answer = gw.client.post("/internal/v1/n8n/calls/read", json=READ, headers=other)
    assert answer.status_code == 401


# Linking each call to its simulated run


def test_every_call_links_to_the_run_by_its_start_nonce(gw: Gateway) -> None:
    nonce = gw.run()
    assert gw.call("calls/read", READ).json()["items"] == [RELEASE]
    assert gw.call("calls/agent", AGENT).status_code == 200
    record = gw.record(nonce)
    assert record["execution_id"] == "41"
    assert record["mode"] == "manual"
    assert record["workflow_id"] == WORKFLOW
    assert [(c["block"], c["kind"], c["outcome"], c["items"]) for c in record["calls"]] == [
        ("Read releases", "read", "answered", 1),
        ("Compare", "agent", "answered", 1),
    ]
    asked = {"source": "github_releases", "place": "a/b", "query": None}
    assert record["calls"][0]["asked"] == asked


def test_an_execution_the_gateway_did_not_start_is_refused(gw: Gateway) -> None:
    nonce = gw.start()
    cases = {
        "no-start-item": (None, WORKFLOW, 403),
        "unknown-nonce": ("sim_" + secrets.token_hex(8), WORKFLOW, 403),
        "other-workflow": (nonce, "wf_other", 403),
    }
    for number, (label, (given, workflow, status)) in enumerate(cases.items()):
        execution = str(100 + number)
        gw.n8n.started(execution, given, workflow)
        answer = gw.call("calls/read", {**READ, "execution_id": execution})
        assert answer.status_code == status, label
        assert set(answer.json()) == {"detail"}, label
    assert gw.record(nonce)["calls"] == []


def test_n8n_without_a_record_yet_asks_for_a_try_again(gw: Gateway) -> None:
    answer = gw.call("calls/read", {**READ, "execution_id": "999"})
    assert answer.status_code == 503
    assert answer.json()["retryable"] is True


def test_a_second_execution_of_one_start_is_refused(gw: Gateway) -> None:
    nonce = gw.run()
    assert gw.call("calls/read", READ).status_code == 200
    gw.n8n.started("42", nonce)
    assert gw.call("calls/read", {**READ, "execution_id": "42"}).status_code == 409


def test_a_start_unused_for_too_long_is_refused(gw: Gateway) -> None:
    gw.run()
    gw.clock.now += timedelta(minutes=10)
    assert gw.call("calls/read", READ).status_code == 403


# Read and Agent


def test_read_serves_recorded_data_or_mock_github() -> None:
    github = FakeGitHub([RELEASE, {**RELEASE, "id": "1.2.15"}])
    gateway = Gateway(github=github)
    with gateway.client:
        blocks = {
            "Read releases": {"serve": "mock"},
            "Read nothing new": {"serve": "recorded", "items": []},
        }
        nonce = gateway.run(scenario(blocks))
        assert len(gateway.call("calls/read", READ).json()["items"]) == 2
        assert github.asked == ["a/b"]
        empty = {**READ, "node_name": "Read nothing new"}
        assert gateway.call("calls/read", empty).json()["items"] == []
        assert [c["items"] for c in gateway.record(nonce)["calls"]] == [2, 0]


def test_read_plays_a_missing_source_and_a_timeout_at_once(gw: Gateway) -> None:
    blocks = {
        "Read releases": {"serve": "not_found"},
        "Read slow": {"serve": "timeout"},
    }
    nonce = gw.run(scenario(blocks))
    missing = gw.call("calls/read", READ)
    slow = gw.call("calls/read", {**READ, "node_name": "Read slow"})
    for answer in (missing, slow):
        assert answer.status_code == 503
        assert answer.json()["retryable"] is True
    assert "not found" in missing.json()["detail"]
    assert "in time" in slow.json()["detail"]
    calls = gw.record(nonce)["calls"]
    assert [(c["outcome"], c["status"]) for c in calls] == [("try_again", 503)] * 2


def test_mock_github_failing_is_a_try_again() -> None:
    gateway = Gateway(github=FakeGitHub(ReadFailed("GitHub has no repository a/b.")))
    with gateway.client:
        gateway.run(scenario({"Read releases": {"serve": "mock"}}))
        answer = gateway.call("calls/read", READ)
        assert answer.status_code == 503
        assert answer.json()["detail"] == "GitHub has no repository a/b."


def test_a_block_the_scenario_cannot_answer_is_refused(gw: Gateway) -> None:
    blocks = {
        "Read releases": {"serve": "recorded", "items": [RELEASE]},
        "Read a page": {"serve": "mock"},
        "Compare": {"serve": "mock"},
    }
    nonce = gw.run(scenario(blocks))
    unnamed = gw.call("calls/read", {**READ, "node_name": "Read the unnamed"})
    page = {**READ, "node_name": "Read a page", "source": "confluence_page", "place": "1"}
    no_mock = gw.call("calls/read", page)
    agent_mock = gw.call("calls/agent", AGENT)
    for answer in (unnamed, no_mock, agent_mock):
        assert answer.status_code == 409
    assert "Read the unnamed" in unnamed.json()["detail"]
    assert [c["outcome"] for c in gw.record(nonce)["calls"]] == ["refused"] * 3


def test_an_agent_takes_a_recorded_reply_and_its_proposals_join_the_run(gw: Gateway) -> None:
    proposal = {"action": "jira.create_ticket", "place": "MOCK", "title": "Upgrade", "body": "x"}
    reply = {"serve": "recorded", "items": [{"summary": "new"}], "proposes": [proposal]}
    nonce = gw.run(scenario({"Compare": reply}))
    assert gw.call("calls/agent", AGENT).json()["items"] == [{"summary": "new"}]
    proposed = gw.record(nonce)["proposed"]
    assert [(p["block"], p["title"]) for p in proposed] == [("Compare", "Upgrade")]


def test_a_repeat_returns_the_first_answer_and_other_content_is_refused(gw: Gateway) -> None:
    nonce = gw.run()
    first = gw.call("calls/read", READ).json()
    assert gw.call("calls/read", READ).json() == first
    assert gw.call("calls/read", {**READ, "place": "c/d"}).status_code == 409
    calls = gw.record(nonce)["calls"]
    assert [(c["replayed"], c["outcome"]) for c in calls] == [
        (False, "answered"),
        (True, "answered"),
        (False, "refused"),
    ]


# Ask for a yes, the write and Tell


def test_ask_for_a_yes_gets_the_scenarios_answer(gw: Gateway) -> None:
    nonce = gw.run(scenario(approver="no"))
    assert gw.call("calls/propose", PROPOSE).json() == {
        "items": [],
        "replayed": False,
        "cut_off": False,
    }
    asked = gw.call("calls/ask", ASK).json()
    assert asked["status"] == "waiting"
    record = gw.record(nonce)
    assert record["approver"] == "no"
    assert [(c["kind"], c["outcome"], c["asked"]) for c in record["calls"][-1:]] == [
        ("ask", "waiting", {})
    ]
    assert "signature" not in json.dumps(record)


def test_ask_with_nothing_proposed_leaves_by_nothing_to_change(gw: Gateway) -> None:
    nonce = gw.run()
    assert gw.call("calls/ask", ASK).json() == {"status": "nothing_to_change", "request_id": None}
    assert gw.record(nonce)["approver"] is None
    assert gw.waker.wakes == []


@pytest.mark.parametrize("approver", ["yes", "no", "no_answer"])
@pytest.mark.anyio
async def test_the_scenarios_answer_wakes_the_execution(approver: WakeDecision) -> None:
    n8n, waker = FakeN8n(), FakeWaker(refusals=2)
    calls = SimulatedCalls(n8n, waker, None, sleep=no_wait)
    run = calls.start(WORKFLOW, Scenario.model_validate(scenario(approver=approver)))
    n8n.started("41", run.nonce)
    execution = N8nExecutionId("41")
    propose = ProposeCall("jira.create_ticket", "MOCK", "Upgrade", "x", None)
    await calls.call(NodeCall(execution, "Propose a change", propose))
    asked = await calls.call(NodeCall(execution, "Ask for a yes", AskCall(RESUME)))
    assert isinstance(asked, Waiting)
    await calls.settle()
    assert [(h.execution_id, h.sealed_url, r, d) for h, r, d in waker.wakes] == [
        (execution, RESUME, asked.request_id, approver)
    ]
    record = calls.run(run.nonce)
    assert record is not None
    assert record.woke == "delivered"


@pytest.mark.anyio
async def test_the_wake_goes_only_to_the_simulation_n8n_with_its_node_key() -> None:
    sent: list[httpx.Request] = []

    def n8n(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(n8n))
    waker = N8nWaker(SETTINGS.n8n_base_url, NODE_KEY, Unsealed(), client)
    fake = FakeN8n()
    calls = SimulatedCalls(fake, waker, None, sleep=no_wait)
    run = calls.start(WORKFLOW, Scenario.model_validate(scenario(approver="no")))
    fake.started("41", run.nonce)
    execution = N8nExecutionId("41")
    await calls.call(NodeCall(execution, "Propose", ProposeCall("a", "b", "c", "d", None)))
    elsewhere = "https://teams.example.com/webhook-waiting/41?signature=made-up"
    asked = await calls.call(NodeCall(execution, "Ask for a yes", AskCall(elsewhere)))
    assert isinstance(asked, Waiting)
    await calls.settle()
    await client.aclose()
    assert [str(r.url) for r in sent] == ["http://n8n:5678/webhook-waiting/41?signature=made-up"]
    body = json.loads(sent[0].content)
    assert body["decision"] == "no"
    assert body["mac"] == wake_mac(NODE_KEY, execution, asked.request_id, "no")


def test_every_write_is_refused_as_the_real_gateway_refuses_and_kept(gw: Gateway) -> None:
    nonce = gw.run()
    gw.call("calls/propose", PROPOSE)
    gw.call("calls/ask", ASK)
    refused = gw.call("calls/write", WRITE)
    again = gw.call("calls/write", WRITE)
    real = real_refusal(TEST_RUN_WRITES_NOTHING)
    for answer in (refused, again):
        assert answer.status_code == real.status_code == 403
        assert set(answer.json()) == set(real.json()) == {"detail"}
        assert answer.json()["detail"] == "A simulation never writes."
    record = gw.record(nonce)
    assert record["approver"] == "yes"
    assert record["would_have_written"] == 1
    written = record["proposed"][: record["would_have_written"]]
    assert [(c["title"], c["place"]) for c in written] == [("Upgrade LangGraph", "MOCK")]
    assert [c["replayed"] for c in record["calls"] if c["kind"] == "write"] == [False, True]


def test_a_write_with_no_yes_is_kept_too(gw: Gateway) -> None:
    nonce = gw.run(scenario(approver="no"))
    gw.call("calls/propose", PROPOSE)
    assert gw.call("calls/write", WRITE).status_code == 403
    record = gw.record(nonce)
    assert record["approver"] is None
    assert record["would_have_written"] == 1


def test_a_run_that_never_writes_keeps_nothing_written(gw: Gateway) -> None:
    nonce = gw.run(scenario(approver="no"))
    gw.call("calls/propose", PROPOSE)
    gw.call("calls/ask", ASK)
    assert gw.record(nonce)["would_have_written"] is None


def test_tell_sends_nothing(gw: Gateway) -> None:
    nonce = gw.run()
    answer = gw.call("calls/tell", TELL)
    assert answer.status_code == 200
    assert answer.json()["status"] == "would_have_sent"
    assert gw.record(nonce)["calls"][-1]["asked"] == {"where": "channel", "what": "result"}


def test_a_failure_report_fails_no_run(gw: Gateway) -> None:
    nonce = gw.run()
    gw.call("calls/read", READ)
    report = {
        "execution_id": "77",
        "workflow_id": "wf_errors",
        "node_name": "Report a failure",
        "mode": "error",
        "failed_execution_id": "41",
    }
    answer = gw.call("failures", report)
    assert answer.status_code == 200
    assert answer.json()["status"] == "left_as_is"
    assert gw.record(nonce)["calls"][-1]["kind"] == "failure"


def test_the_editor_lists_are_empty(gw: Gateway) -> None:
    answer = gw.client.get("/internal/v1/n8n/options?kind=agents", headers=KEY)
    assert answer.json() == {"options": []}


@pytest.mark.anyio
async def test_a_run_that_calls_without_end_is_stopped() -> None:
    n8n = FakeN8n()
    calls = SimulatedCalls(n8n, FakeWaker(), None, sleep=no_wait, call_limit=3)
    run = calls.start(WORKFLOW, Scenario.model_validate(scenario()))
    n8n.started("41", run.nonce)
    answers = [
        await calls.call(NodeCall(N8nExecutionId("41"), f"Write {n}", WriteCall()))
        for n in range(4)
    ]
    assert [getattr(a, "status", None) for a in answers] == [403, 403, 403, 409]
    record = calls.run(run.nonce)
    assert record is not None
    assert len(record.calls) == 3


@pytest.mark.anyio
async def test_a_run_that_sends_too_much_is_stopped() -> None:
    """The record is capped by its size too, so a few large calls can't fill the gateway's
    memory either."""
    n8n = FakeN8n()
    calls = SimulatedCalls(n8n, FakeWaker(), None, sleep=no_wait, byte_limit=3000)
    run = calls.start(WORKFLOW, Scenario.model_validate(scenario()))
    n8n.started("41", run.nonce)
    long = "x" * 1200
    answers = [
        await calls.call(
            NodeCall(
                N8nExecutionId("41"),
                f"Propose {n}",
                ProposeCall("jira.create_ticket", "MOCK", "Upgrade", long, None),
            )
        )
        for n in range(4)
    ]
    assert [getattr(a, "status", None) for a in answers] == [None, None, 409, 409]
    assert "too much" in str(getattr(answers[2], "detail", ""))
    record = calls.run(run.nonce)
    assert record is not None
    assert len(record.calls) == 2
    assert len(record.model_dump_json()) < 2 * 3000, "past the limit by one call at most"


@pytest.mark.anyio
async def test_a_refused_write_counts_only_its_own_call_toward_the_size_limit() -> None:
    """What the write would have made is the changes already proposed. The record holds them
    once, as proposed, and counts them once, so a write after a large change is not taken for
    a run that sent too much."""
    n8n = FakeN8n()
    calls = SimulatedCalls(n8n, FakeWaker(), None, sleep=no_wait, byte_limit=4000)
    run = calls.start(WORKFLOW, Scenario.model_validate(scenario()))
    n8n.started("41", run.nonce)
    large = ProposeCall("jira.create_ticket", "MOCK", "Upgrade", "x" * 1200, None)
    execution = N8nExecutionId("41")
    await calls.call(NodeCall(execution, "Propose a change", large))
    refused = await calls.call(NodeCall(execution, "Write", WriteCall()))
    assert getattr(refused, "status", None) == 403
    told = await calls.call(NodeCall(execution, "Tell", TellCall("channel", "result")))
    assert getattr(told, "status", None) != 409, "counted once, the record is under its limit"
    record = calls.run(run.nonce)
    assert record is not None
    assert record.would_have_written == 1
    assert len(record.model_dump_json()) < 4000


@pytest.mark.anyio
async def test_the_gateway_keeps_only_its_newest_runs() -> None:
    calls = SimulatedCalls(FakeN8n(), FakeWaker(), None, sleep=no_wait, run_limit=2)
    given = Scenario.model_validate(scenario())
    first, second, third = (calls.start(WORKFLOW, given) for _ in range(3))
    assert calls.run(first.nonce) is None
    assert calls.run(second.nonce) is not None
    assert calls.run(third.nonce) is not None


# Mock GitHub


@pytest.mark.anyio
async def test_mock_github_answers_as_the_read_block_expects() -> None:
    asked: list[str] = []

    def github(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if request.url.path == "/repos/a/missing/releases":
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(
            200,
            json=[
                {"tag_name": "1.2.16", "name": "", "published_at": "2026-10-28", "draft": False},
                {"tag_name": "1.3.0", "name": "1.3.0", "published_at": None, "draft": True},
            ],
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(github))
    mock = MockGitHub("http://mock-github:8200", client)
    assert await mock.releases("a/b") == [
        {"kind": "release", "id": "1.2.16", "name": "1.2.16", "published_at": "2026-10-28"}
    ]
    assert isinstance(await mock.releases("a/missing"), ReadFailed)
    assert isinstance(await mock.releases("../../user"), ReadFailed)
    await client.aclose()
    assert asked == [
        "http://mock-github:8200/repos/a/b/releases?per_page=100",
        "http://mock-github:8200/repos/a/missing/releases?per_page=100",
    ]


# The mock setup (ADR 0054, PR 4)

COPIES = "/simulation/v1/copies"


def ask_copy(gw: Gateway, given: dict[str, Any], secret: str = START_SECRET) -> httpx.Response:
    body = json.dumps(given).encode()
    return gw.client.post(COPIES, content=body, headers=signed("POST", COPIES, body, secret))


def test_a_signed_request_makes_the_versions_copy_in_the_simulation_n8n(gw: Gateway) -> None:
    answer = ask_copy(gw, {"version": version()})
    assert answer.status_code == 201, answer.text
    copied = answer.json()
    made = [what for what, _ in gw.simulation_n8n.done]
    assert made == ["project", "delete", "credential", "delete", "credential", "workflow"]
    assert copied["workflow_id"] == "copy-6"
    assert {b["block"]: (b["mode"], b["mock"]) for b in copied["blocks"]} == {
        "Start from the Portal": ("ours", None),
        "Read releases": ("mock", "github"),
        "Read issues": ("pinned", None),
        "Is it new": ("runs", None),
        "Ask for a yes": ("ours", None),
        "Post in Slack": ("mock", "slack"),
        "Post in Teams": ("pinned", None),
    }
    assert copied["not_tried"] == ["Read issues", "Post in Teams"]
    slack = gw.simulation_n8n.keys["sim-mock-slack"]
    assert slack[2] == {"accessToken": SLACK_TOKEN}
    assert SLACK_TOKEN not in answer.text


def test_a_scenario_may_pin_a_block_with_no_mock(gw: Gateway) -> None:
    answer = ask_copy(gw, {"version": version(), "pins": {"Read issues": [{"key": "MOCK-1"}]}})
    assert answer.status_code == 201, answer.text
    document = gw.simulation_n8n.done[-1][1]
    assert document["pinData"]["Read issues"] == [{"json": {"key": "MOCK-1"}}]


def test_a_copy_request_not_signed_with_the_start_secret_makes_nothing(gw: Gateway) -> None:
    answer = ask_copy(gw, {"version": version()}, OTHER_SECRET)
    assert answer.status_code == 401
    assert gw.simulation_n8n.done == []


def test_a_version_with_a_block_that_is_off_is_refused_and_makes_nothing(gw: Gateway) -> None:
    answer = ask_copy(gw, {"version": version(http_request())})
    assert answer.status_code == 422
    refused = answer.json()
    assert [b["block"] for b in refused["blocks"]] == ["Call anything"]
    assert "send what a run read" in refused["blocks"][0]["why"]
    assert gw.simulation_n8n.done == []


# Its settings


def test_the_gateway_reads_only_its_own_settings() -> None:
    env = {
        "WAB_NODE_KEY": NODE_KEY,
        "WAB_START_SECRET": START_SECRET,
        "N8N_BASE_URL": "http://n8n:5678/",
        "N8N_OWNER_EMAIL": "owner@simulation.example",
        "N8N_OWNER_PASSWORD": SETTINGS.n8n_owner.password,
        "MOCK_GITHUB_URL": "http://mock-github:8200",
        "MOCK_JIRA_URL": "http://mock-jira:8700/",
        "MOCK_SLACK_TOKEN": SLACK_TOKEN,
        "DATABASE_URL": "postgresql://someone@elsewhere/platform",
    }
    settings = gateway_settings_from_env(env)
    assert settings == GatewaySettings(
        NODE_KEY,
        START_SECRET,
        "http://n8n:5678",
        N8nOwner("owner@simulation.example", SETTINGS.n8n_owner.password),
        "http://mock-github:8200",
        "http://mock-jira:8700",
        SLACK_TOKEN,
    )
    assert NODE_KEY not in repr(settings)
    assert START_SECRET not in repr(settings)
    assert SLACK_TOKEN not in repr(settings)
    for name in ("WAB_NODE_KEY", "WAB_START_SECRET", "N8N_BASE_URL", "N8N_OWNER_PASSWORD"):
        with pytest.raises(ConfigError, match=name):
            gateway_settings_from_env({k: v for k, v in env.items() if k != name})
    mocks = ("MOCK_GITHUB_URL", "MOCK_JIRA_URL", "MOCK_SLACK_TOKEN")
    bare = gateway_settings_from_env({k: v for k, v in env.items() if k not in mocks})
    assert (bare.mock_github_url, bare.mock_jira_url, bare.mock_slack_token) == (None, None, None)


def test_the_gateway_has_only_its_own_routes(gw: Gateway) -> None:
    app = gw.client.app
    assert isinstance(app, FastAPI)
    platform = FastAPI()
    platform.include_router(n8n_calls_http.router)
    real = set(platform.openapi()["paths"])
    assert len(real) == 8
    assert set(app.openapi()["paths"]) == {
        "/healthz",
        "/simulation/v1/starts",
        "/simulation/v1/runs/{nonce}",
        "/simulation/v1/copies",
        "/simulation/v1/simulations",
        *real,
    }


def real_refusal(refused: Any) -> httpx.Response:
    """How the platform's own API answers a test run's write, with the same router."""
    app = FastAPI()
    app.state.settings = SETTINGS
    app.state.node_calls = FakeNodeCalls(refused)
    app.include_router(n8n_calls_http.router)
    with TestClient(app) as client:
        return client.post("/internal/v1/n8n/calls/write", json=WRITE, headers=KEY)
