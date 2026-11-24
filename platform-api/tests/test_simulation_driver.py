"""platform-api's side of a simulation (ADR 0054, PR 7): it sends a workflow version to the
simulation gateway's signed routes and reads back code's grades. Without the model setting, code's
own six templates run and no model is asked, so nothing is paid for. With it, the scenario
writer's scenarios go with fall_back and the explainer explains each failure."""

import json
import time
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
import pytest

from platform_api.orchestration.scenarios import ScenarioSpec
from platform_api.orchestration.simulation_driver import (
    CANT_RUN,
    DIDNT_ANSWER,
    DONT_FIT,
    NotSimulated,
    Simulated,
    SimulationClient,
    SimulationDriver,
    version_of,
)
from platform_api.orchestration.simulation_gateway import (
    PAST,
    CoverageOut,
    PlanOut,
    ResultOut,
    SimulationOut,
    control_signature,
)

pytestmark = pytest.mark.anyio

# Made up at run time, so no key shape sits in the file.
SECRET = "-".join(["sim", "start", uuid.uuid4().hex])
BASE = "http://gateway:8600"
VERSION: dict[str, Any] = {
    "id": "wfDrafted01",
    "name": "Release check",
    "nodes": [{"name": "Every Monday", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}}],
    "connections": {},
    "settings": {"executionOrder": "v1"},
    "pinData": {"Every Monday": [{"json": {"real": "run"}}]},
    "active": False,
}


def result(kind: str, verdict: str, happened: str = "It ran to the end.") -> ResultOut:
    return ResultOut(
        name=kind,
        kind=kind,  # type: ignore[arg-type]
        verdict=verdict,  # type: ignore[arg-type]
        expected="It runs to the end.",
        happened=happened,
        ran=["Every Monday"],
        not_tried=[],
        ending=None if verdict == "not_tried" else "finished",
        stopped_at=None,
        plays=[],
    )


DONE = SimulationOut(
    tried=2,
    passed=1,
    results=[
        result("happy_path", "passed"),
        result("source_not_found", "failed", "It failed, and n8n names no block."),
        result("timeout", "not_tried", "No block here can play this case, so it was not tried."),
    ],
    coverage=CoverageOut(not_reached=[], not_tried=[], kinds_without_a_scenario=[]),
    blocks=[],
    scenarios_from="templates",
    refused=[],
)
PLAN = PlanOut(blocks=[], kinds=["happy_path", "source_not_found"], samples=[])


class Gateway:
    """The gateway's control routes, which check each signature as `signed_body` does."""

    def __init__(self, *answers: httpx.Response) -> None:
        self.answers = list(answers)
        self.seen: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        expires = int(request.headers["X-Wab-Expires"])
        now = int(time.time())
        assert now - PAST <= expires <= now + 360
        assert request.headers["X-Wab-Signature"] == control_signature(
            SECRET, request.method, request.url.path, expires, request.content
        )
        self.seen.append((request.url.path, json.loads(request.content)))
        if self.answers:
            return self.answers.pop(0)
        if request.url.path.endswith("/plans"):
            return httpx.Response(200, json=PLAN.model_dump(mode="json"))
        return httpx.Response(200, json=DONE.model_dump(mode="json"))


def client_of(gateway: Gateway) -> SimulationClient:
    return SimulationClient(
        BASE, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(gateway))
    )


class Model:
    def __init__(self, written: list[ScenarioSpec] | None) -> None:
        self.written = written
        self.plans: list[PlanOut] = []
        self.explained: list[Sequence[ResultOut]] = []

    async def write(self, plan: PlanOut) -> list[ScenarioSpec] | None:
        self.plans.append(plan)
        return self.written

    async def explain(self, results: Sequence[ResultOut]) -> dict[str, str]:
        self.explained.append(results)
        return {"source_not_found": '"Read releases" stopped the run with no reason.'}


def test_only_the_version_s_name_blocks_links_and_settings_go_never_its_pins():
    assert version_of(VERSION) == {
        "name": "Release check",
        "nodes": VERSION["nodes"],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }


async def test_without_the_model_setting_code_s_templates_run_and_no_model_is_asked():
    gateway = Gateway()

    done = await SimulationDriver(client_of(gateway)).run(VERSION)

    assert isinstance(done, Simulated)
    assert done.out == DONE
    assert done.notes == {}
    [(path, body)] = gateway.seen
    assert path == "/simulation/v1/simulations"
    assert body["scenarios"] is None
    assert body["fall_back"] is False
    assert body["version"] == version_of(VERSION)


async def test_with_the_model_on_written_scenarios_go_with_fall_back_and_failures_are_explained():
    gateway = Gateway()
    model = Model([ScenarioSpec(kind="happy_path")])

    done = await SimulationDriver(client_of(gateway), model).run(VERSION)

    assert isinstance(done, Simulated)
    assert [path for path, _ in gateway.seen] == [
        "/simulation/v1/plans",
        "/simulation/v1/simulations",
    ]
    assert model.plans == [PLAN]
    body = gateway.seen[1][1]
    assert body["fall_back"] is True
    assert [s["kind"] for s in body["scenarios"]] == ["happy_path"]
    assert done.notes == {"source_not_found": '"Read releases" stopped the run with no reason.'}
    [explained] = model.explained
    assert [r.kind for r in explained] == ["happy_path", "source_not_found", "timeout"]


async def test_a_writer_that_writes_nothing_leaves_code_s_templates_to_run():
    gateway = Gateway()

    done = await SimulationDriver(client_of(gateway), Model(None)).run(VERSION)

    assert isinstance(done, Simulated)
    body = gateway.seen[1][1]
    assert (body["scenarios"], body["fall_back"]) == (None, False)


async def test_a_version_the_mock_setup_refuses_is_not_tried_and_names_each_block():
    refused = {
        "detail": "The simulation can't run every block of this version.",
        "blocks": [
            {"block": "Run code", "node_type": "n8n-nodes-base.code", "why": "Not on the list."}
        ],
    }
    gateway = Gateway(httpx.Response(422, json=refused))

    done = await SimulationDriver(client_of(gateway)).run(VERSION)

    assert done == NotSimulated(CANT_RUN.format(blocks='"Run code"'), again=False)


async def test_scenarios_that_don_t_fit_are_not_tried_and_trying_again_won_t_help():
    gateway = Gateway(httpx.Response(422, json={"detail": "x", "problems": ["no such block"]}))

    done = await SimulationDriver(client_of(gateway)).run(VERSION)

    assert done == NotSimulated(DONT_FIT, again=False)


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(503, json={"detail": "The simulation n8n or a mock did not answer."}),
        httpx.Response(500, text="boom"),
        httpx.Response(200, json={"not": "a simulation"}),
    ],
    ids=["503", "500", "unreadable"],
)
async def test_a_gateway_that_doesn_t_answer_as_it_should_can_be_tried_again(
    answer: httpx.Response,
):
    done = await SimulationDriver(client_of(Gateway(answer))).run(VERSION)

    assert done == NotSimulated(DIDNT_ANSWER, again=True)


async def test_a_gateway_that_can_t_be_reached_can_be_tried_again():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = SimulationClient(
        BASE, SECRET, client=httpx.AsyncClient(transport=httpx.MockTransport(down))
    )

    assert await SimulationDriver(client).run(VERSION) == NotSimulated(DIDNT_ANSWER, again=True)
