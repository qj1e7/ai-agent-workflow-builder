from harness import Api, Json, approval_requested, assert_gapless, bob_decides, tickets_for

SUMMARY_TASK = "Every Friday summarise the tickets we finished in MOCK."
RELEASE_TASK = "Check acme/planted for a new release and raise a ticket in MOCK."
PLANTED = {"GitHub repository": "acme/planted", "Jira project": "MOCK"}


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


def test_the_plan_for_a_task_the_platform_cannot_do_says_so(api: Api, mock_model: None) -> None:
    plan = api.post(
        "alice", "/api/v1/builder/plan", {"task": "Book a meeting room for Friday."}, expect=(200,)
    ).json()
    assert plan["decision"] == "cannot_do"
