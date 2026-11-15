from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from harness import (
    Api,
    Json,
    MockGithub,
    SeededTicket,
    approval_requested,
    assert_gapless,
    bob_decides,
    remove_tickets,
    seed_tickets,
    tickets_for,
)

SUMMARY_TASK = "Every Friday summarise the tickets we finished in MOCK."
RELEASE_TASK = "Check acme/planted for a new release and raise a ticket in MOCK."
STALE_TASK = (
    "Every Friday, list bug tickets with no update for 10 days and create one follow-up "
    "ticket that lists them. Where it goes: Jira project MOCK."
)
FOLLOW_UP_TASK = (
    "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one "
    "follow-up ticket that lists them"
)
PLANTED = {"GitHub repository": "acme/planted", "Jira project": "MOCK"}
LANGGRAPH = {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}


def run_agents(api: Api, card_id: str, values: dict[str, str], name: str) -> str:
    body: Json = {
        "name": name,
        "instruction": "Run the agent.",
        "agents": [{"card_id": card_id, "values": values}],
    }
    created = api.post("alice", "/api/v1/agent-use-cases", body, expect=(201,)).json()
    run_id, started = api.start_run("alice", created["use_case_id"])
    assert started.status_code == 201
    return run_id


def approve(api: Api, run_id: str) -> Json:
    events = api.stream_until("alice", run_id, {"approval_requested"})
    assert_gapless(events, run_id)
    approval_id = approval_requested(events)["approval_id"]
    view = api.get("bob", f"/api/v1/approvals/{approval_id}")
    bob_decides(api, approval_id, "approve", view["digest"])
    return view


def test_without_a_model_nothing_plans_or_runs(api: Api) -> None:
    api.turn_model_off()
    refused = api.post("alice", "/api/v1/builder/plan", {"task": SUMMARY_TASK}, expect=(409,))
    assert refused.json()["detail"] == "Connect an AI model in Settings first."
    body: Json = {
        "name": "No model",
        "instruction": "Run the agent.",
        "agents": [{"card_id": "crd_version_checker", "values": PLANTED}],
    }
    made = api.post("alice", "/api/v1/agent-use-cases", body, expect=(201,)).json()
    stopped = api.post(
        "alice",
        f"/api/v1/use-cases/{made['use_case_id']}/runs",
        expect=(409,),
        headers={"Idempotency-Key": "no-model"},
    )
    assert stopped.json()["detail"] == "Connect an AI model in Settings to run agents."


def test_without_a_model_the_planner_answers_offline_and_the_chips_still_work(api: Api) -> None:
    api.turn_model_off()
    offline = api.post(
        "alice", "/api/v1/planner/answer", {"text": SUMMARY_TASK}, expect=(200,)
    ).json()
    assert (offline["answer"], offline["why"]) == ("offline", "no_model")
    assert len(offline["starters"]) == 3
    for intent in ("abilities", "needs_me", "setup_ideas"):
        chip = api.post("alice", "/api/v1/planner/answer", {"intent": intent}, expect=(200,))
        assert chip.json()["answer"] in ("abilities", "needs_me", "ideas")
    asked = api.post("bob", "/api/v1/planner/answer", {"intent": "decided"}, expect=(200,))
    assert asked.json()["answer"] == "decided", "an Approver's question chips work with no model"
    ideas = api.post("bob", "/api/v1/planner/answer", {"intent": "setup_ideas"}, expect=(200,))
    assert ideas.json()["answer"] == "operators", "setting up is an Operator's, so Bob is refused"


def test_one_changed_part_is_checked_by_code_and_the_capabilities_list_what_works(
    api: Api,
) -> None:
    api.turn_model_off()
    cant = api.post(
        "alice",
        "/api/v1/planner/check-part",
        {"kind": "do", "text": "Email the list to the team"},
        expect=(200,),
    ).json()
    assert (cant["state"], cant["needs"], cant["system"]) == ("cant_do", "new_system", "email")
    fits = api.post(
        "alice",
        "/api/v1/planner/check-part",
        {"kind": "where", "text": "In the MOCK project"},
        expect=(200,),
    ).json()
    assert fits == {"state": "fits"}
    listed = {c["id"]: c for c in api.get("bob", "/api/v1/capabilities")["capabilities"]}
    assert listed["jira.create"]["state"] in ("ready", "needs_setup")
    assert (listed["teams.post"]["state"], listed["teams.post"]["plain"]) == (
        "planned",
        "Posts in Teams and emails",
    )
    assert "approval requests only" not in listed["teams.post"]["why"]
    assert listed["teams.post"]["short"] == "Teams channels, email"
    assert "email.send" not in listed
    assert "crd_version_checker" in listed["github.releases"]["agents"]


def test_a_typed_request_is_answered_by_the_model_and_saves_nothing(
    api: Api, mock_model: None
) -> None:
    before = api.get("alice", "/api/v1/use-cases")["use_cases"]
    answer = api.post(
        "alice", "/api/v1/planner/answer", {"text": FOLLOW_UP_TASK}, expect=(200,)
    ).json()
    assert answer["answer"] == "setup_card"
    assert [r["kind"] for r in answer["rows"]] == ["schedule", "look_for", "do", "where"]
    asked = api.post(
        "alice", "/api/v1/planner/answer", {"text": "What can you do?"}, expect=(200,)
    ).json()
    assert asked["answer"] == "abilities"
    assert api.get("alice", "/api/v1/use-cases")["use_cases"] == before


def test_a_drafted_agent_is_saved_then_run_approved_and_written(api: Api, mock_model: None) -> None:
    plan = api.post("alice", "/api/v1/builder/plan", {"task": SUMMARY_TASK}, expect=(200,)).json()
    assert plan["decision"] == "new_agent"
    assert plan["problems"] == []
    assert plan["approvals"] == [{"tool": "jira.create_ticket", "approvers": 1}]

    saved = api.post("alice", "/api/v1/agent-cards", plan["draft"], expect=(201,)).json()
    assert (saved["version"], saved["starter"], saved["owner"]) == (1, False, "alice")
    api.post("bob", "/api/v1/agent-cards", plan["draft"], expect=(403,))
    library = api.get("bob", "/api/v1/agent-cards")["cards"]
    assert [c["card_id"] for c in library][0] == "crd_version_checker"
    assert saved["card_id"] in [c["card_id"] for c in library]

    run_id = run_agents(api, saved["card_id"], {"Jira project": "MOCK"}, "e2e summary")
    view = approve(api, run_id)
    assert [a["target"]["project"] for a in view["actions"]] == ["MOCK"]
    final = api.wait_for_state("alice", run_id, {"succeeded"})
    assert final["outcome"] == "written"
    [ticket] = tickets_for(api, run_id)
    assert ticket["project"] == "MOCK"
    assert ticket["title"] == "Summary of finished tickets in MOCK"

    again = api.post("alice", "/api/v1/builder/plan", {"task": SUMMARY_TASK}, expect=(200,))
    assert again.json()["decision"] == "new_agent"
    assert len(api.get("alice", "/api/v1/agent-cards")["cards"]) == len(library), (
        "planning never saves"
    )


def test_a_saved_agent_is_picked_and_a_planted_order_in_a_release_changes_nothing(
    api: Api, mock_model: None
) -> None:
    plan = api.post("alice", "/api/v1/builder/plan", {"task": RELEASE_TASK}, expect=(200,)).json()
    assert plan["decision"] == "use_one"
    [planned] = plan["agents"]
    assert planned["card"]["card_id"] == "crd_version_checker"
    assert planned["values"] == PLANTED and planned["missing"] == []

    run_id = run_agents(api, "crd_version_checker", planned["values"], "e2e planted")
    view = approve(api, run_id)
    assert [a["target"]["project"] for a in view["actions"]] == ["MOCK"], (
        "the project is the card's own value, whatever the release notes said"
    )
    assert [set(a["fields"]) for a in view["actions"]] == [{"title", "body"}]
    api.wait_for_state("alice", run_id, {"succeeded"})
    created = tickets_for(api, run_id)
    assert [t["project"] for t in created] == ["MOCK"]
    assert all(t["project"] != "SECRET" for t in api.tickets())


def test_a_github_outage_stops_the_version_checker_before_its_model_can_ask_for_a_ticket(
    api: Api, github: MockGithub, mock_model: None
) -> None:
    github.set_mode("unavailable")
    run_id = run_agents(api, "crd_version_checker", LANGGRAPH, "e2e outage")
    stopped = api.wait_for_state("alice", run_id, {"failed", "awaiting_approval"})
    assert stopped["state"] == "failed", "a check that read nothing must not ask for a yes"
    assert (stopped["reason"], stopped["retryable"]) == ("WorkflowNodeError", True)
    assert stopped["message"].startswith(
        'Stopped before it read anything. "Read release" failed in n8n'
    ), "the release check reads GitHub in its own block, before the Version checker runs"
    events = api.events_after("alice", run_id)
    kinds = [e["kind"] for e in events]
    assert "write_action_proposed" not in kinds and "approval_requested" not in kinds
    assert tickets_for(api, run_id) == []

    github.set_mode("ok")
    api.post("alice", f"/api/v1/runs/{run_id}/retry", expect=(202,))
    retried = api.stream_until(
        "alice", run_id, {"approval_requested"}, last_event_id=events[-1]["seq"]
    )
    approval_id = approval_requested(retried)["approval_id"]
    view = api.get("bob", f"/api/v1/approvals/{approval_id}")
    assert [a["fields"]["title"] for a in view["actions"]] == [
        "New release 1.2.16 of langchain-ai/langgraph"
    ], "the retry proposes the release it read"
    bob_decides(api, approval_id, "decline", view["digest"])
    api.wait_for_state("alice", run_id, {"rejected"})
    assert tickets_for(api, run_id) == []


def test_the_plan_for_a_task_the_platform_cannot_do_says_so(api: Api, mock_model: None) -> None:
    plan = api.post(
        "alice", "/api/v1/builder/plan", {"task": "Book a meeting room for Friday."}, expect=(200,)
    ).json()
    assert plan["decision"] == "cannot_do"


@pytest.fixture
def quiet_project() -> Iterator[dict[str, str]]:
    """Practice tickets in MOCK. Two bugs are stale, one bug is fresh, and one old ticket is not
    a bug. The names map each ticket to its key."""
    seeded = {
        "stale bug": SeededTicket("E2E stale bug", "Bug", 12, "Dana Tan"),
        "older stale bug": SeededTicket("E2E older stale bug", "Bug", 30),
        "fresh bug": SeededTicket("E2E fresh bug", "Bug", 2, "Dana Tan"),
        "stale task": SeededTicket("E2E stale task", "Task", 20, "Dana Tan"),
    }
    keys = seed_tickets("MOCK", list(seeded.values()))
    try:
        yield dict(zip(seeded, keys, strict=True))
    finally:
        remove_tickets(keys)


def test_a_stale_bug_agent_lists_exactly_the_bugs_with_no_update_for_ten_days(
    api: Api, mock_model: None, quiet_project: dict[str, str]
) -> None:
    plan = api.post("alice", "/api/v1/builder/plan", {"task": STALE_TASK}, expect=(200,)).json()
    assert plan["decision"] == "new_agent"
    assert plan["problems"] == []
    [search, _propose] = plan["draft"]["blocks"]
    assert search["say"] == "Find bug tickets with no update for 10 days."

    saved = api.post("alice", "/api/v1/agent-cards", plan["draft"], expect=(201,)).json()
    run_id = run_agents(api, saved["card_id"], {"Jira project": "MOCK"}, "e2e stale bugs")
    view = approve(api, run_id)

    [action] = view["actions"]
    listed = {key.strip(" .,") for key in action["fields"]["body"].split() if "-" in key}
    assert listed == {quiet_project["stale bug"], quiet_project["older stale bug"]}, (
        "only bugs that had no update for 10 days are listed, not the fresh bug or the old task"
    )
    api.wait_for_state("alice", run_id, {"succeeded"})


def test_a_second_run_tells_its_agent_the_day_the_first_run_started(
    api: Api, mock_model: None, quiet_project: dict[str, str]
) -> None:
    plan = api.post("alice", "/api/v1/builder/plan", {"task": STALE_TASK}, expect=(200,)).json()
    saved = api.post("alice", "/api/v1/agent-cards", plan["draft"], expect=(201,)).json()
    body: Json = {
        "name": "e2e last run",
        "instruction": "Run the agent.",
        "agents": [{"card_id": saved["card_id"], "values": {"Jira project": "MOCK"}}],
    }
    made = api.post("alice", "/api/v1/agent-use-cases", body, expect=(201,)).json()

    first_day = datetime.now(ZoneInfo("Asia/Singapore")).date()
    first, _ = api.start_run("alice", made["use_case_id"])
    approve(api, first)
    api.wait_for_state("alice", first, {"succeeded"})
    second, _ = api.start_run("alice", made["use_case_id"])
    api.stream_until("alice", second, {"approval_requested"})

    def search_line(run_id: str) -> str:
        [line] = [
            e["summary"]
            for e in api.events_after("alice", run_id)
            if e["kind"] == "agent_step_started" and "searches" in e["summary"]
        ]
        return line

    assert "created on or after" not in search_line(first)
    assert search_line(second).endswith(
        f"created on or after {first_day.day} {first_day:%b} (the last run)."
    )
    view = api.get(
        "bob",
        f"/api/v1/approvals/{approval_requested(api.events_after('alice', second))['approval_id']}",
    )
    [action] = view["actions"]
    assert not any(key in action["fields"]["body"] for key in quiet_project.values()), (
        "the seeded bugs were created long before the last run, so the second search skips them"
    )
