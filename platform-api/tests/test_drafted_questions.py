"""A drafted workflow's questions and Edit in n8n (ADR 0051, build step 7), in platform-api with
the drafter, n8n and Teams faked: one question at a time, each answer a new revision made by code
with no model, the never-guessed kinds read only by code, the approval held until nothing is
needed, and a workflow changed in n8n read back and checked again."""

from typing import Any

import pytest

from platform_api.builder.drafted_settings import ANY_APPROVER, APPROVERS
from platform_api.builder.drafted_workflows import IN_N8N_NOW, KEY_IN_N8N, KEY_PASTED
from platform_api.orchestration import WorkflowPlan
from tests.test_drafted_layout import block, release_check, wire
from tests.test_drafted_workflows import Lab, drafted, lab

pytestmark = pytest.mark.anyio

__all__ = ["lab"]


def setting_of(view: dict[str, Any], setting_id: str) -> dict[str, Any]:
    return next(s for s in view["settings"] if s["id"] == setting_id)


async def test_the_run_time_is_asked_how_often_then_at_what_time_and_never_guessed(lab: Lab):
    lab.drafter.answers = [drafted(release_check(run_time=None))]
    view = await lab.start(answered=False)

    assert (view["question"], view["revision"]) == ("run_time", 1)
    asked = setting_of(view, "run_time")
    assert asked["question"] == "How often should it run?"
    assert [c["label"] for c in asked["choices"]] == ["Every day", "Weekdays", "Mondays", "Fridays"]

    view = await lab.answer(view, "run_time", choice="monday")
    asked = setting_of(view, "run_time")
    assert (view["revision"], view["card_revision"], view["question"]) == (2, 1, "run_time")
    assert (asked["question"], asked["typed"]) == ("Mondays, at what time?", "Type a time")

    unread = await lab.answer(view, "run_time", typed="9", status=409)
    assert unread["detail"].startswith("I couldn't read a time in that.")
    view = await lab.answer(view, "run_time", typed="9:30")

    asked = setting_of(view, "run_time")
    assert (asked["mark"], asked["value"], asked["said"]) == (
        "filled",
        "every Monday at 9:30",
        "You typed it",
    )
    assert view["question"] == APPROVERS
    assert len(lab.drafter.asked) == 1, "an answer never asks the model"


async def test_the_approval_is_held_until_nothing_is_needed(lab: Lab):
    view = await lab.start(answered=False)

    assert (view["question"], view["needed"], view["can_send"]) == (APPROVERS, 1, False)
    assert view["why_not_send"] == "Answer 1 question first"
    assert (await lab.send(view["drafted_id"], view["revision"])).status_code == 409
    approvers = setting_of(view, APPROVERS)
    assert approvers["question"] == "Who says yes to “Make the ticket” on each run?"
    assert [c["value"] for c in approvers["choices"]] == [ANY_APPROVER]

    view = await lab.answer(view, APPROVERS, choice=ANY_APPROVER)

    assert (view["needed"], view["can_send"], view["question"]) == (0, True, None)
    assert (await lab.send(view["drafted_id"], view["revision"])).status_code == 200


async def test_a_choice_the_question_doesn_t_offer_is_refused(lab: Lab):
    plan = release_check().model_dump()
    plan["settings"][2].update({"value": None, "mark": "needed"})
    lab.drafter.answers = [drafted(WorkflowPlan.model_validate(plan))]
    view = await lab.start(answered=False)

    assert view["question"] == "jira_project"
    assert [c["value"] for c in setting_of(view, "jira_project")["choices"]] == ["MOCK"]
    refused = await lab.answer(view, "jira_project", choice="SECRET", status=409)
    assert refused["detail"] == "Pick one of the choices."
    view = await lab.answer(view, "jira_project", choice="MOCK")
    assert setting_of(view, "jira_project")["mark"] == "filled"


async def test_a_flag_a_needed_place_causes_is_not_counted_while_it_is_asked(lab: Lab):
    plan = release_check(run_time=None).model_dump()
    plan["settings"][2].update({"value": None, "mark": "needed"})
    lab.drafter.answers = [drafted(WorkflowPlan.model_validate(plan))]
    view = await lab.start(answered=False)

    assert (view["flags"], view["needed"]) == (0, 3)
    assert view["report"]["flags"] == []


async def test_a_typed_answer_shaped_like_a_key_is_refused_before_anything_is_kept(lab: Lab):
    plan = release_check().model_dump()
    plan["blocks"][1]["parameters"]["place"] = "<<repository>>"
    plan["settings"][1].update({"value": "fastapi/fastapi", "mark": "guessed"})
    lab.drafter.answers = [drafted(WorkflowPlan.model_validate(plan))]
    view = await lab.start(answered=False)

    typed = "ghp_abcdefghijklmnopqrstuvwxyz0123"
    refused = await lab.answer(view, "repository", typed=typed, status=409)

    assert refused["detail"] == KEY_PASTED
    after = await lab.read(view["drafted_id"])
    assert after["revision"] == view["revision"]
    async with lab.db.connection("builder") as conn:
        rows = await (await conn.execute("SELECT words FROM builder.drafted_revisions")).fetchall()
    assert all(typed not in str(row["words"]) for row in rows)


async def test_a_guessed_setting_shows_as_a_guess_that_can_be_changed(lab: Lab):
    plan = release_check().model_dump()
    plan["settings"][1].update({"value": "fastapi/fastapi", "mark": "guessed"})
    lab.drafter.answers = [drafted(WorkflowPlan.model_validate(plan))]
    view = await lab.start()

    guess = setting_of(view, "repository")
    assert (guess["mark"], guess["said"], guess["typed"]) == ("guessed", "I guessed", "Type one")
    view = await lab.answer(view, "repository", typed="langchain-ai/langgraph")

    changed = setting_of(view, "repository")
    assert (changed["mark"], changed["value"], changed["said"]) == (
        "filled",
        "langchain-ai/langgraph",
        "You typed it",
    )
    seen_by_bob = setting_of(await lab.read(view["drafted_id"]), "repository")
    assert seen_by_bob["said"] == "Alice typed it"


async def test_whoever_answers_is_a_party_to_the_set_up_approval(lab: Lab):
    view = await lab.start(user="carol", answered=False)
    view = await lab.answer(view, APPROVERS, user="alice", choice=ANY_APPROVER)
    sent = (await lab.send(view["drafted_id"], view["revision"], user="carol")).json()

    page = await lab.call(
        "alice", "GET", f"/api/v1/setup-approvals/{sent['approval']['approval_id']}"
    )
    assert page.json()["you_can_decide"] is False


async def test_a_write_by_one_of_n8n_s_own_blocks_waits_for_a_write_key_and_is_never_asked(
    lab: Lab,
):
    plan = release_check().model_dump()
    plan["blocks"].append(
        block("Close the issue", "n8n-nodes-base.github", 1.1, resource="issue", operation="edit")
    )
    plan["wires"].append(wire("Make the ticket", "Close the issue"))
    lab.drafter.answers = [drafted(WorkflowPlan.model_validate(plan))]
    view = await lab.start()

    key = setting_of(view, "key:Close the issue")
    assert (key["mark"], key["choices"], key["typed"]) == ("needed", [], None)
    assert "later step" in key["waits"]
    assert view["question"] is None
    assert view["can_send"] is False
    assert view["why_not_send"] is not None and "flag" in view["why_not_send"]


async def test_edit_in_n8n_opens_it_without_keys_and_done_reads_it_back_checked_again(lab: Lab):
    view = await lab.start()
    drafted_id = view["drafted_id"]
    assert view["can_edit_in_n8n"] is True

    opened = await lab.call(
        "alice",
        "POST",
        f"/api/v1/drafted-workflows/{drafted_id}/n8n",
        {"revision": view["revision"]},
    )
    assert opened.status_code == 200, opened.text
    held = opened.json()["in_n8n"]
    assert held["by"] == "alice" and held["editor_url"] == "https://n8n.example/workflow/wf1"
    assert lab.n8n.projects["wf1"] == "space-n8n-alice"
    assert all("credentials" not in node for node in lab.n8n.saved[0]["nodes"])
    assert (await lab.read(drafted_id))["in_n8n"]["editor_url"] is None, "only for the opener"

    for refused in (
        await lab.send(drafted_id, view["revision"]),
        await lab.call(
            "alice",
            "POST",
            f"/api/v1/drafted-workflows/{drafted_id}/changes",
            {"words": "post at 10:00 instead", "revision": view["revision"]},
        ),
    ):
        assert (refused.status_code, refused.json()["detail"]) == (409, IN_N8N_NOW)

    for node in lab.n8n.held["wf1"].document["nodes"]:
        if node["name"] == "Every Monday":
            node["parameters"]["rule"]["interval"][0]["triggerAtHour"] = 17
    by_carol = await lab.call("carol", "POST", f"/api/v1/drafted-workflows/{drafted_id}/n8n/done")
    assert by_carol.status_code == 403
    carol_answers = await lab.answer(
        await lab.read(drafted_id), APPROVERS, "carol", choice=ANY_APPROVER, status=409
    )
    assert carol_answers["detail"].startswith("Alice has it open in n8n since ")
    done = await lab.call("alice", "POST", f"/api/v1/drafted-workflows/{drafted_id}/n8n/done")

    assert done.status_code == 200, done.text
    after = done.json()
    assert (after["made_by"], after["revision"], after["card_revision"]) == ("n8n", 3, 3)
    assert after["in_n8n"] is None and after["can_send"] is True
    run_time = setting_of(after, "run_time")
    assert (run_time["value"], run_time["said"]) == ("every Monday at 17:00", "You typed it in n8n")
    assert setting_of(after, APPROVERS)["said"] == "You chose"
    assert lab.n8n.removed == ["wf1"]
    assert len(lab.drafter.asked) == 1, "a read-back never asks the model"


async def test_what_n8n_holds_that_a_plan_can_t_comes_back_as_words_and_stays_there(lab: Lab):
    view = await lab.start()
    drafted_id = view["drafted_id"]
    await lab.call(
        "alice",
        "POST",
        f"/api/v1/drafted-workflows/{drafted_id}/n8n",
        {"revision": view["revision"]},
    )
    for node in lab.n8n.held["wf1"].document["nodes"]:
        if node["name"] == "Read new releases":
            node["onError"] = "continueRegularOutput"

    done = await lab.call("alice", "POST", f"/api/v1/drafted-workflows/{drafted_id}/n8n/done")

    assert done.status_code == 409
    assert "onError" in done.json()["detail"]
    assert (await lab.read(drafted_id))["in_n8n"] is not None
    assert lab.n8n.removed == []


TOKEN = "ghp_" + "Zx9" * 12
"""Shaped like a GitHub token, made at run time so no scanner reads it as a leaked one."""


def nested(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        if node["name"] == "Propose a ticket":
            node["parameters"]["options"] = {"labels": [{"text": f"see {TOKEN}"}]}


def in_a_header(nodes: list[dict[str, Any]]) -> None:
    nodes.append(
        {
            "id": "n-http",
            "name": "Call it",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [0, 0],
            "parameters": {
                "method": "GET",
                "url": "https://api.example.com/x",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [{"name": "Authorization", "value": f"Bearer {TOKEN}"}]
                },
            },
        }
    )


def in_code(nodes: list[dict[str, Any]]) -> None:
    nodes.append(
        {
            "id": "n-code",
            "name": "Shape it",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [0, 0],
            "parameters": {"jsCode": f"const key = '{TOKEN}';\nreturn items;"},
        }
    )


def in_an_expression(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        if node["name"] == "Propose a ticket":
            node["parameters"]["title"] = f"={{{{ 'token=' + '{TOKEN}' }}}}"


def in_a_name(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        if node["name"] == "Ask for a yes":
            node["name"] = f"Ask {TOKEN}"


@pytest.mark.parametrize("hide", [nested, in_a_header, in_code, in_an_expression, in_a_name])
async def test_a_key_typed_in_n8n_is_never_read_back_kept_or_echoed(lab: Lab, hide: Any):
    view = await lab.start()
    drafted_id = view["drafted_id"]
    await lab.call(
        "alice",
        "POST",
        f"/api/v1/drafted-workflows/{drafted_id}/n8n",
        {"revision": view["revision"]},
    )
    hide(lab.n8n.held["wf1"].document["nodes"])
    async with lab.db.connection("builder") as conn:
        before = await (
            await conn.execute("SELECT count(*) AS n FROM builder.drafted_revisions")
        ).fetchone()

    done = await lab.call("alice", "POST", f"/api/v1/drafted-workflows/{drafted_id}/n8n/done")

    assert done.status_code == 409
    assert TOKEN not in done.text
    assert done.json()["detail"] == KEY_IN_N8N
    async with lab.db.connection("builder") as conn:
        rows = await (await conn.execute("SELECT * FROM builder.drafted_revisions")).fetchall()
    assert before is not None and len(rows) == before["n"], "nothing new was kept"
    assert all(TOKEN not in str(dict(row)) for row in rows)
    assert lab.n8n.removed == [], "it stays in n8n, to be put right there"
    assert (await lab.read(drafted_id))["in_n8n"] is not None


async def test_a_value_shaped_like_a_key_is_never_shown_even_if_one_slips_in(lab: Lab):
    plan = release_check().model_dump()
    plan["settings"][1].update({"value": TOKEN, "mark": "guessed"})
    lab.drafter.answers = [drafted(WorkflowPlan.model_validate(plan))]
    view = await lab.start()

    assert TOKEN not in str(view)
    assert setting_of(view, "repository")["value"] == "(hidden, looks like a key)"


async def test_only_an_operator_with_n8n_access_can_edit_in_n8n(lab: Lab):
    lab.drafted._staff.with_access = frozenset({"carol"})  # type: ignore[attr-defined]
    view = await lab.start()

    assert view["can_edit_in_n8n"] is False
    refused = await lab.call(
        "alice",
        "POST",
        f"/api/v1/drafted-workflows/{view['drafted_id']}/n8n",
        {"revision": view["revision"]},
    )
    assert refused.status_code == 403
    assert lab.n8n.saved == []
