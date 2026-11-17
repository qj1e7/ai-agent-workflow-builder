"""A workflow drafted from Carol's words with the mock model, its questions answered one at a time,
sent for a set-up approval, approved by Bob, and set up in the real n8n as a Draft whose digest is
the approved one (ADR 0051, build steps 6 and 7). The drafter runs in the agent runtime against the
pinned catalogue. A draft edited in n8n by an Operator with n8n access is read back and checked
again."""

import time
import uuid
from typing import Any

from harness import N8N_OWNER, Api, Json, fail
from test_n8n_access import sits_in
from test_n8n_versions import staff_member

WORDS = (
    "Draft an n8n workflow that every Monday at 09:00 checks langchain-ai/langgraph for a new "
    "release and raises a ticket in MOCK"
)
SETTLED = ("draft", "not_drafted")
APPROVERS = "approvers"
ANY_APPROVER = "Any Approver on the team"


def setting_of(view: Json, setting_id: str) -> Json:
    found: Json = next(s for s in view["settings"] if s["id"] == setting_id)
    return found


def answer(
    api: Api,
    user: str,
    view: Json,
    setting: str,
    *,
    choice: str | None = None,
    typed: str | None = None,
    expect: tuple[int, ...] = (200,),
) -> Any:
    body = {"revision": view["revision"], "setting": setting, "choice": choice, "typed": typed}
    path = f"/api/v1/drafted-workflows/{view['drafted_id']}/answers"
    return api.post(user, path, body, expect=expect).json()


def in_n8n(use_case_id: str) -> Json:
    """The workflow in n8n whose Sticky Note links to this workflow's page."""
    for listed in N8N_OWNER.call("GET", "/workflows"):
        held = N8N_OWNER.call("GET", f"/workflows/{listed['id']}")
        if any(f"/workflows/{use_case_id}" in str(n["parameters"]) for n in held["nodes"]):
            return held
    fail(f"n8n holds no workflow for {use_case_id}")


def drafted_now(api: Api, drafted_id: str, states: tuple[str, ...], seconds: float = 60) -> Json:
    deadline = time.monotonic() + seconds
    while True:
        view = api.get("bob", f"/api/v1/drafted-workflows/{drafted_id}")
        set_up: Json = view["set_up"] or {}
        if view["state"] in states or set_up.get("state") in states:
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
    assert (view["needed"], view["flags"], view["can_send"]) == (1, 0, False), view["report"]
    assert (view["question"], view["why_not_send"]) == (APPROVERS, "Answer 1 question first")
    names = [b["name"] for b in view["blocks"]]
    assert names[:2] == ["Every Monday", "Start from the Portal"]

    answer(api, "bob", view, APPROVERS, choice=ANY_APPROVER, expect=(403,))
    view = answer(api, "carol", view, APPROVERS, choice=ANY_APPROVER)
    assert (view["revision"], view["card_revision"], view["can_send"]) == (2, 1, True)
    assert setting_of(view, APPROVERS)["said"] == "You chose"

    revision = {"revision": view["revision"]}
    api.post("bob", f"/api/v1/drafted-workflows/{drafted_id}/send", revision, expect=(403,))
    sent = api.post(
        "carol", f"/api/v1/drafted-workflows/{drafted_id}/send", revision, expect=(200,)
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

    held = in_n8n(use_case_id)
    assert held["activeVersionId"] is None, "set up as a draft, not published"
    types = {node["name"]: node["type"] for node in held["nodes"]}
    assert types["Ask for a yes"] == "CUSTOM.wabAskForYes"
    assert types["Start from the Portal"] == "CUSTOM.wabStartFromPortal"

    tickets = len(api.tickets())
    test_run = api.post(
        "carol",
        f"/api/v1/use-cases/{use_case_id}/runs",
        {"test": True},
        expect=(201,),
        headers={"Idempotency-Key": f"t-{use_case_id}"},
    ).json()
    finished = api.wait_for_state("carol", test_run["run_id"], {"succeeded", "failed"})
    assert finished["state"] == "succeeded", finished
    assert finished["outcome"] in ("test_passed", "nothing_to_write"), finished["outcome"]
    assert (finished["written"], len(api.tickets())) == ([], tickets), "a test run writes nothing"

    messages = api.get("bob", "/api/v1/teams-stub/messages")["messages"]
    [card] = [m for m in messages if m["approval_id"] == approval_id]
    assert (card["run_id"], card["link"]) == (None, f"/setup-approvals/{approval_id}")
    api.delete("alice", f"/api/v1/use-cases/{use_case_id}", expect=(200,))


NO_TIME = (
    "Draft an n8n workflow that every Monday checks langchain-ai/langgraph for a new release and "
    "raises a ticket in MOCK"
)


def drafted_by(api: Api, user: str, words: str) -> Json:
    started = api.post(
        user,
        "/api/v1/drafted-workflows",
        {"words": words},
        expect=(202,),
        headers={"Idempotency-Key": str(uuid.uuid4())},
    ).json()
    view = drafted_now(api, started["drafted_id"], SETTLED)
    assert view["state"] == "draft", view.get("said")
    return view


def test_a_run_time_the_words_left_out_is_asked_and_never_guessed(api: Api, mock_model: None):
    view = drafted_by(api, "carol", NO_TIME)

    asked = setting_of(view, "run_time")
    assert (view["question"], asked["question"]) == ("run_time", "Mondays, at what time?")
    assert view["report"]["flags"] == [], "the place still needed is the question, not a flag"
    unread = answer(api, "carol", view, "run_time", typed="9", expect=(409,))
    assert unread["detail"].startswith("I couldn't read a time in that.")
    key = answer(api, "carol", view, "run_time", typed="ghp_" + "a" * 36, expect=(409,))
    assert key["detail"] == "Don't paste keys here. An Operator adds keys in Settings."

    view = answer(api, "carol", view, "run_time", choice="09:00")
    assert setting_of(view, "run_time")["value"] == "every Monday at 9:00"
    view = answer(api, "carol", view, APPROVERS, choice=ANY_APPROVER)
    assert (view["needed"], view["can_send"], view["revision"]) == (0, True, 3)
    assert "".join(s["text"] for s in view["report"]["in_short"]).startswith("Every Monday at 9:00")


def test_a_draft_edited_in_n8n_is_read_back_and_checked_again(api: Api, mock_model: None):
    erin = staff_member(api, "Erin")
    view = drafted_by(api, erin.person, NO_TIME)
    view = answer(api, erin.person, view, "run_time", choice="09:00")
    drafted_id = view["drafted_id"]
    assert view["can_edit_in_n8n"] is True
    assert api.get("carol", f"/api/v1/drafted-workflows/{drafted_id}")["in_n8n"] is None

    opened = api.post(
        erin.person,
        f"/api/v1/drafted-workflows/{drafted_id}/n8n",
        {"revision": view["revision"]},
        expect=(200,),
    ).json()
    workflow_id = opened["in_n8n"]["editor_url"].rsplit("/", 1)[1]
    assert sits_in(erin.member.project, workflow_id), "in Erin's own n8n space"
    held = erin.member.call("GET", f"/workflows/{workflow_id}")
    assert all(not node.get("credentials") for node in held["nodes"]), "without its keys"
    waiting = api.get(erin.person, "/api/v1/n8n/workflows")["workflows"]
    assert workflow_id not in {w["workflow_id"] for w in waiting}, "never waits to be set up"

    for node in held["nodes"]:
        if node["type"] == "n8n-nodes-base.scheduleTrigger":
            node["parameters"]["rule"]["interval"][0]["triggerAtHour"] = 17
    edit = {
        "nodes": held["nodes"],
        "connections": held["connections"],
        "settings": held["settings"],
        "versionId": held["versionId"],
    }
    erin.member.call("PATCH", f"/workflows/{workflow_id}", edit)

    done = api.post(
        erin.person, f"/api/v1/drafted-workflows/{drafted_id}/n8n/done", expect=(200,)
    ).json()
    assert (done["made_by"], done["card_revision"], done["in_n8n"]) == ("n8n", 3, None)
    run_time = setting_of(done, "run_time")
    assert (run_time["value"], run_time["said"]) == ("every Monday at 17:00", "You typed it in n8n")
    assert done["question"] == APPROVERS, "the Approvers are still asked"
    gone = N8N_OWNER.send("GET", f"/rest/workflows/{workflow_id}")
    assert gone.status_code in (403, 404), "taken out of Erin's n8n space"
