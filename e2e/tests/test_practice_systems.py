"""Workflows tried on practice systems through the link (ADR 0054, "What the link chose"). Carol
drafts the release check with the mock model, which waits while it needs a setting, and answers
its one question. platform-api's driver then sends that revision to the simulation gateway, which
runs code's six templates in the simulation n8n with no model, and the drafted card reads back
code's grades. A release check the Planner builds from our blocks is tried the same way, the
first time its Check is read. Nothing is written and no run is made.

It runs only on a stack that `E2E_SIMULATION=on scripts/e2e.sh` starts, where platform-api shares
a network with the simulation gateway alone. Every other stack skips it."""

import os
import time
from collections.abc import Callable

import pytest
from harness import Api, Json, fail
from test_drafted_workflow import ANY_APPROVER, APPROVERS, SETTLED, WORDS, answer, drafted_now

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_SIMULATION") != "on",
    reason="needs the simulation stack linked to this one: E2E_SIMULATION=on scripts/e2e.sh",
)

ENDED = ("done", "not_run", "not_finished")
LANGGRAPH = {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}
SIMULATION_SECONDS = 6 * 120 + 120
"""platform-api's own limit for a whole simulation (simulation_driver.SIMULATION_SECONDS)."""


def lead(simulation: Json) -> str:
    """The card's first line, as the Portal words it (simulationLead in simulation.ts)."""
    tried = simulation["tried"]
    cases = "case" if tried == 1 else "cases"
    return f"Tried {tried} {cases} on practice systems: {simulation['passed']} passed."


def ended(read: Callable[[], Json], what: str) -> Json:
    deadline = time.monotonic() + SIMULATION_SECONDS
    while True:
        simulation = read()
        if simulation["state"] in ENDED:
            return simulation
        if time.monotonic() > deadline:
            fail(f"the simulation of {what} stayed {simulation['state']}: {simulation!r}")
        time.sleep(3)


def simulated(api: Api, drafted_id: str) -> Json:
    path = f"/api/v1/drafted-workflows/{drafted_id}"
    return ended(lambda: api.get("carol", path)["simulation"], drafted_id)


def graded(simulation: Json) -> None:
    """Code's grades, as the card shows them: printed for the job's log, and counted right."""
    print(f"\n{lead(simulation)}")
    for case in simulation["cases"]:
        print(f"  {case['kind']}: {case['verdict']}. {case['happened']}")
    assert simulation["state"] == "done", simulation
    assert simulation["tried"] == sum(c["verdict"] != "not_tried" for c in simulation["cases"])
    assert simulation["passed"] == sum(c["verdict"] == "passed" for c in simulation["cases"])
    assert all(case["note"] is None for case in simulation["cases"]), "no model was asked"


def test_a_drafted_workflow_is_tried_on_practice_systems_through_the_link(
    api: Api, mock_model: None
) -> None:
    tickets = len(api.tickets())
    runs = {run["run_id"] for run in api.get("alice", "/api/v1/runs")["runs"]}
    started = api.post("carol", "/api/v1/planner/answer", {"text": WORDS}, expect=(200,)).json()
    assert started["answer"] == "draft_started", started
    drafted_id = started["drafted_id"]

    view = drafted_now(api, drafted_id, SETTLED)
    assert view["state"] == "draft", view.get("said")
    assert view["needed"] == 1, view["report"]
    assert view["simulation"]["state"] == "waiting", "a revision with a blank waits to be tried"

    view = answer(api, "carol", view, APPROVERS, choice=ANY_APPROVER)
    assert (view["needed"], view["can_send"]) == (0, True), view["report"]
    assert view["simulation"]["state"] != "unavailable", "platform-api has no simulation gateway"

    simulation = simulated(api, drafted_id)
    graded(simulation)
    assert len(simulation["cases"]) == 6, [case["kind"] for case in simulation["cases"]]
    assert simulation["tried"] == 6, simulation

    assert len(api.tickets()) == tickets, "a simulation writes nothing"
    after = {run["run_id"] for run in api.get("alice", "/api/v1/runs")["runs"]}
    assert after == runs, "a simulation is not a run"


def test_a_workflow_the_planner_builds_from_our_blocks_is_tried_on_practice_systems_too(
    api: Api,
) -> None:
    tickets = len(api.tickets())
    runs = {run["run_id"] for run in api.get("alice", "/api/v1/runs")["runs"]}
    body: Json = {
        "name": "e2e release check on practice systems",
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": "crd_version_checker", "values": LANGGRAPH}],
        "schedule": {"day": "every_day", "at": "08:00"},
        "on": False,
    }
    made = api.post("carol", "/api/v1/agent-use-cases", body, expect=(201,)).json()
    use_case_id = made["use_case_id"]
    path = f"/api/v1/use-cases/{use_case_id}/simulation"

    first = api.get("bob", path)
    assert first["version"] == 1, first
    assert first["simulation"]["state"] in ("running", *ENDED), "its first read starts its try"
    simulation = ended(lambda: api.get("carol", path)["simulation"], use_case_id)
    graded(simulation)
    assert simulation["tried"] >= 1, simulation

    assert api.get("carol", f"/api/v1/use-cases/{use_case_id}")["state"] == "draft"
    assert len(api.tickets()) == tickets, "a simulation writes nothing"
    after = {run["run_id"] for run in api.get("alice", "/api/v1/runs")["runs"]}
    assert after == runs, "a simulation is not a run"
    api.delete("carol", f"/api/v1/use-cases/{use_case_id}", expect=(200,))
