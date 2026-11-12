from dataclasses import replace
from typing import Any

import httpx
import pytest

from platform_api.orchestration.people import Person
from platform_api.shared import Principal, Role, RunId, UserId
from tests.declared import declared_status
from tests.support import CAROL, SPEC
from tests.test_home import (
    ALICE_NOW,
    TWO_STEPS,
    Lab,
    decide_first_step,
    lab,
    waiting_run,
    work,
    workflow,
)

__all__ = ["lab"]

pytestmark = pytest.mark.anyio

DAVE = Principal(UserId("dave"), frozenset({Role.OPERATOR, Role.APPROVER}), "Dave")
QUESTIONS = "/api/v1/approvals/{approval_id}/questions"
ANSWER = "/api/v1/approvals/{approval_id}/questions/{question_id}/answer"


async def send(
    lab: Lab, user: str, method: str, path: str, route: str, body: Any = None, key: str = ""
) -> httpx.Response:
    headers = {"X-Dev-User": user, **({"Idempotency-Key": key} if key else {})}
    response = await lab.client.request(method, path, headers=headers, json=body)
    if response.status_code != 422:
        declared_status(lab.app, method, route, response)
    return response


async def approval_of(lab: Lab, run_id: RunId, user: str = "bob") -> dict[str, Any]:
    run = (await lab.call(user, "GET", f"/api/v1/runs/{run_id}")).json()
    return await view(lab, run["approval"]["approval_id"], user)


async def view(lab: Lab, approval_id: str, user: str) -> dict[str, Any]:
    response = await lab.call(user, "GET", f"/api/v1/approvals/{approval_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def ask(lab: Lab, user: str, approval_id: str, text: str, key: str = "k1") -> httpx.Response:
    path = QUESTIONS.format(approval_id=approval_id)
    return await send(lab, user, "POST", path, QUESTIONS, {"text": text}, key)


async def answer(
    lab: Lab, user: str, approval_id: str, question_id: str, text: str
) -> httpx.Response:
    path = ANSWER.format(approval_id=approval_id, question_id=question_id)
    return await send(lab, user, "POST", path, ANSWER, {"text": text})


async def decide(lab: Lab, user: str, seen: dict[str, Any], verdict: str) -> httpx.Response:
    step = next(s["index"] for s in seen["steps"] if s["status"] == "open")
    body = {"step": step, "verdict": verdict, "digest": seen["digest"]}
    path = f"/api/v1/approvals/{seen['approval_id']}/decisions"
    return await lab.call(user, "POST", path, body)


def but_questions(approval: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in approval.items() if k != "questions"}


async def run_now(lab: Lab, run_id: RunId, user: str = "bob") -> tuple[str, int]:
    run = (await lab.call(user, "GET", f"/api/v1/runs/{run_id}")).json()
    return run["state"], run["last_seq"]


async def test_an_approver_who_may_decide_asks_and_the_request_keeps_waiting(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab), by="alice")
    before = await approval_of(lab, run_id)
    run_before = await run_now(lab, run_id)
    assert (before["requester"], before["questions"]) == ("alice", [])

    asked = await ask(lab, "bob", before["approval_id"], "  Has 1.3 been tested?  ")

    assert asked.status_code == 201, asked.text
    question = asked.json()
    assert (question["asked_by"], question["text"], question["answer"]) == (
        "bob",
        "Has 1.3 been tested?",
        None,
    )
    after = await view(lab, before["approval_id"], "bob")
    assert after["questions"] == [question]
    assert but_questions(after) == but_questions(before), "steps, digest and who decides stay"
    assert await run_now(lab, run_id) == run_before, "the run waits, with no new event"
    (item,) = (await lab.home("alice"))["questions_for_me"]
    assert (item["question_id"], item["asked_by_name"], item["text"], item["run_id"]) == (
        question["question_id"],
        "Bob",
        "Has 1.3 been tested?",
        run_id,
    )
    assert (await lab.home("bob"))["questions_for_me"] == [], "only the requester is asked"
    assert [a["run_id"] for a in (await lab.home("bob"))["approvals"]] == [run_id]


async def test_the_same_key_sent_again_finds_the_question_it_asked(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab))
    approval_id = (await approval_of(lab, run_id))["approval_id"]

    first = await ask(lab, "bob", approval_id, "Is it urgent?", key="same")
    again = await ask(lab, "bob", approval_id, "Is it urgent at all?", key="same")
    other = await ask(lab, "bob", approval_id, "Who uses it?", key="other")

    assert (first.status_code, again.status_code, other.status_code) == (201, 200, 201)
    assert again.json() == first.json()
    texts = [q["text"] for q in (await view(lab, approval_id, "bob"))["questions"]]
    assert texts == ["Is it urgent?", "Who uses it?"]


@pytest.mark.parametrize(
    ("user", "refusal"),
    [
        ("alice", "own_work"),
        ("carol", "not_an_approver"),
    ],
)
async def test_someone_the_gate_would_refuse_cannot_ask(lab: Lab, user: str, refusal: str):
    run_id = await waiting_run(lab, await workflow(lab), by="alice")
    approval_id = (await approval_of(lab, run_id))["approval_id"]

    refused = await ask(lab, user, approval_id, "Can I ask?")

    assert (refused.status_code, refused.json()["refusal"]) == (403, refusal)
    assert (await view(lab, approval_id, "bob"))["questions"] == []


async def test_an_approver_whose_role_is_taken_away_cannot_ask(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab), by="alice")
    approval_id = (await approval_of(lab, run_id))["approval_id"]
    assert isinstance(await lab.people.remove_approver(ALICE_NOW, "dave"), Person)

    refused = await ask(lab, "dave", approval_id, "Can I still ask?")

    assert refused.status_code == 403
    assert (await view(lab, approval_id, "bob"))["questions"] == []


async def test_an_approver_who_decided_the_first_step_cannot_ask_on_the_second(lab: Lab):
    started = await lab.h.orchestrator.start_run(
        replace(SPEC, approval_policy=TWO_STEPS), CAROL, "two-steps"
    )
    run_id = started.run_id
    await work(lab, run_id, cards=False)
    await decide_first_step(lab, "bob", run_id)
    approval_id = (await approval_of(lab, run_id))["approval_id"]

    refused = await ask(lab, "bob", approval_id, "One more thing?")
    asked = await ask(lab, "erin", approval_id, "Is the first yes enough?")

    assert (refused.status_code, refused.json()["refusal"]) == (403, "decided_earlier_step")
    assert asked.status_code == 201, asked.text
    assert [q["asked_by"] for q in (await view(lab, approval_id, "erin"))["questions"]] == ["erin"]


async def test_only_the_requester_answers_and_the_answer_decides_nothing(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab), by="alice")
    before = await approval_of(lab, run_id)
    approval_id = before["approval_id"]
    question = (await ask(lab, "bob", approval_id, "Has 1.3 been tested?")).json()
    asked = await view(lab, approval_id, "bob")
    run_asked = await run_now(lab, run_id)

    for other in ("bob", "carol", "erin"):
        refused = await answer(lab, other, approval_id, question["question_id"], "Yes.")
        assert refused.status_code == 403, other
    answered = await answer(lab, "alice", approval_id, question["question_id"], " Yes, Friday. ")

    assert answered.status_code == 201, answered.text
    kept = answered.json()["answer"]
    assert (kept["text"], kept["by"]) == ("Yes, Friday.", "alice")
    after = await view(lab, approval_id, "bob")
    assert after["questions"] == [answered.json()]
    assert but_questions(after) == but_questions(asked), "bob still decides, on the same digest"
    assert await run_now(lab, run_id) == run_asked, "the run waits, with no new event"
    assert (await lab.home("alice"))["questions_for_me"] == []
    own = await decide(lab, "alice", await view(lab, approval_id, "alice"), "approve")
    assert (own.status_code, own.json()["refusal"]) == (403, "own_work")
    assert (await decide(lab, "bob", after, "approve")).status_code == 201


async def test_the_same_answer_again_is_kept_once_and_a_different_one_is_refused(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab))
    approval_id = (await approval_of(lab, run_id))["approval_id"]
    question_id = (await ask(lab, "bob", approval_id, "Is it urgent?")).json()["question_id"]

    first = await answer(lab, "alice", approval_id, question_id, "No.")
    again = await answer(lab, "alice", approval_id, question_id, "No.")
    other = await answer(lab, "alice", approval_id, question_id, "Yes, actually.")

    assert (first.status_code, again.status_code, other.status_code) == (201, 200, 409)
    assert again.json() == first.json()
    (kept,) = (await view(lab, approval_id, "bob"))["questions"]
    assert kept["answer"]["text"] == "No."


async def test_once_the_request_is_decided_its_questions_stay_and_take_no_answer(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab))
    seen = await approval_of(lab, run_id)
    approval_id = seen["approval_id"]
    question = (await ask(lab, "bob", approval_id, "Is it urgent?")).json()
    assert (await decide(lab, "bob", seen, "decline")).status_code == 201

    late = await answer(lab, "alice", approval_id, question["question_id"], "No.")
    after = await ask(lab, "erin", approval_id, "Why was it declined?", key="late")

    assert late.status_code == 409
    assert (after.status_code, after.json()["refusal"]) == (403, "not_open")
    decided = await view(lab, approval_id, "alice")
    assert decided["questions"] == [question], "the question stays, with no answer"
    assert [s["status"] for s in decided["steps"]] == ["declined"]
    assert (await lab.home("alice"))["questions_for_me"] == []


async def test_on_a_scheduled_run_the_workflows_owner_answers_not_the_starter(lab: Lab):
    spec = replace(SPEC, trigger="schedule", owner=UserId("carol"))
    started = await lab.h.orchestrator.start_run(spec, DAVE, "scheduled")
    run_id = started.run_id
    await work(lab, run_id, cards=False)
    approval = await approval_of(lab, run_id)
    assert approval["requester"] == "carol"
    question_id = (await ask(lab, "bob", approval["approval_id"], "Is it urgent?")).json()[
        "question_id"
    ]

    assert [q["question_id"] for q in (await lab.home("carol"))["questions_for_me"]] == [
        question_id
    ]
    refused = await answer(lab, "dave", approval["approval_id"], question_id, "No.")
    answered = await answer(lab, "carol", approval["approval_id"], question_id, "No.")
    assert (refused.status_code, answered.status_code) == (403, 201)


async def test_a_question_is_found_only_on_its_own_approval(lab: Lab):
    use_case = await workflow(lab)
    first = (await approval_of(lab, await waiting_run(lab, use_case)))["approval_id"]
    second = (await approval_of(lab, await waiting_run(lab, use_case)))["approval_id"]
    question_id = (await ask(lab, "bob", first, "Is it urgent?")).json()["question_id"]

    assert (await answer(lab, "alice", second, question_id, "No.")).status_code == 404
    assert (await answer(lab, "alice", "apr_none", question_id, "No.")).status_code == 404
    assert (await ask(lab, "bob", "apr_none", "Is it there?")).status_code == 404


@pytest.mark.parametrize(
    ("text", "key", "why"),
    [
        ("   ", "k1", "a question has words in it"),
        ("x" * 1001, "k1", "a question is at most 1000 characters"),
        ("Is it urgent?", "", "a question needs an Idempotency-Key"),
    ],
)
async def test_a_question_it_cannot_take_is_refused_and_keeps_nothing(
    lab: Lab, text: str, key: str, why: str
):
    run_id = await waiting_run(lab, await workflow(lab))
    approval_id = (await approval_of(lab, run_id))["approval_id"]

    refused = await ask(lab, "bob", approval_id, text, key=key)

    assert refused.status_code == 422, why
    assert (await view(lab, approval_id, "bob"))["questions"] == []


async def test_an_answer_with_no_words_is_refused_and_keeps_none(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab))
    approval_id = (await approval_of(lab, run_id))["approval_id"]
    question_id = (await ask(lab, "bob", approval_id, "Is it urgent?")).json()["question_id"]

    for text in ("  ", "x" * 1001):
        assert (await answer(lab, "alice", approval_id, question_id, text)).status_code == 422
    (kept,) = (await view(lab, approval_id, "bob"))["questions"]
    assert kept["answer"] is None
