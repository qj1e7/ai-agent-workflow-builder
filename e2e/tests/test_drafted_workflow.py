"""A workflow drafted from Carol's words with the mock model, sent for a set-up approval, approved
by Bob, and set up in the real n8n as a Draft whose digest is the approved one (ADR 0051, build
step 6). The drafter runs in the agent runtime against the pinned catalogue."""

import time

from harness import N8N_OWNER, Api, Json, fail

WORDS = (
    "Draft an n8n workflow that every Monday at 09:00 checks langchain-ai/langgraph for a new "
    "release and raises a ticket in MOCK"
)
SETTLED = ("draft", "not_drafted")


def drafted_now(api: Api, drafted_id: str, states: tuple[str, ...], seconds: float = 60) -> Json:
    deadline = time.monotonic() + seconds
    while True:
        view = api.get("bob", f"/api/v1/drafted-workflows/{drafted_id}")
        if view["state"] in states or (view.get("set_up") or {}).get("state") in states:
            return view
        if time.monotonic() > deadline:
            fail(f"drafted workflow {drafted_id} stayed {view['state']}: {view!r}"[:600])
        time.sleep(1)


def test_a_drafted_release_check_is_approved_by_another_and_set_up_as_a_draft(
    api: Api, mock_model: None
) -> None:
    started = api.post("carol", "/api/v1/planner/answer", {"text": WORDS}, expect=(200,)).json()
    assert started["answer"] == "draft_started", started
    drafted_id = started["drafted_id"]

    view = drafted_now(api, drafted_id, SETTLED)
    assert view["state"] == "draft", view.get("said")
    assert (view["needed"], view["flags"], view["can_send"]) == (0, 0, True), view["report"]
    names = [b["name"] for b in view["blocks"]]
    assert names[:2] == ["Every Monday", "Start from the Portal"]

    api.post("bob", f"/api/v1/drafted-workflows/{drafted_id}/send", {"revision": 1}, expect=(403,))
    sent = api.post(
        "carol", f"/api/v1/drafted-workflows/{drafted_id}/send", {"revision": 1}, expect=(200,)
    ).json()
    approval_id = sent["approval"]["approval_id"]
    assert sent["state"] == "waiting"

    as_carol = api.get("carol", f"/api/v1/setup-approvals/{approval_id}")
    assert as_carol["you_can_decide"] is False, "the sender is a party"
    page = api.get("bob", f"/api/v1/setup-approvals/{approval_id}")
    assert page["you_can_decide"] is True
    api.post(
        "bob",
        f"/api/v1/setup-approvals/{approval_id}/decisions",
        {"verdict": "approve", "digest": page["digest"]},
        expect=(201,),
    )

    done = drafted_now(api, drafted_id, ("set_up", "failed", "refused"))
    assert done["set_up"]["state"] == "set_up", done["set_up"]
    use_case_id = done["set_up"]["use_case_id"]
    workflow = api.get("alice", f"/api/v1/use-cases/{use_case_id}")
    assert workflow["state"] == "draft"

    held = N8N_OWNER.call("GET", f"/workflows/{workflow['n8n_workflow_id']}")
    assert held["activeVersionId"] is None, "set up as a draft, not published"
    types = {node["name"]: node["type"] for node in held["nodes"]}
    assert types["Ask for a yes"] == "CUSTOM.wabAskForYes"
    assert types["Start from the Portal"] == "CUSTOM.wabStartFromPortal"

    messages = api.get("bob", "/api/v1/teams-stub/messages")["messages"]
    [card] = [m for m in messages if m["approval_id"] == approval_id]
    assert (card["run_id"], card["link"]) == (None, f"/setup-approvals/{approval_id}")
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))
