"""Every free reply the real model wrote in the free-reply spike's runs (baseline, parity and
parity2 on `spike/dspy-free-reply`, 19 Nov 2026), replayed through the code checks with no model
call. Each row keeps why it fell back then, and the team's reading of it: a reply that was shown,
a true catch, an honest can't the guard now shows (ADR 0047, amended 20 Nov 2026), an honest reply
outside the allow-list that still falls back, or the verifier's call, which no code replays."""

import json
from typing import Any

import pytest
from evals.anything import ANYTHING
from evals.jobs import CASES
from evals.reply import REPLY

from agent_runtime.contract import AnswerRequest, FreeReplyAnswer, ReplyEnvelope
from agent_runtime.contracts import answer_request
from agent_runtime.free_reply import answer_of_envelope

ROWS: list[dict[str, Any]] = json.loads((CASES / "recorded_replies.json").read_text())
CASES_BY_SET = {
    "reply": {case.id: case for case in REPLY.cases()},
    "anything": {case.id: case for case in ANYTHING.cases()},
}


def request_of(row: dict[str, Any]) -> AnswerRequest:
    case = CASES_BY_SET[row["set"]][row["case"]]
    return AnswerRequest(
        task=case.task,
        model=answer_request().model,
        facts=case.facts,
        previous=case.previous,
        changes_workflows=case.changes_workflows,
    )


def checked(row: dict[str, Any]) -> str | None:
    envelope = ReplyEnvelope(
        form=row["form"],
        text=row["text"],
        choices=row["choices"],
        offer=row["offer"],
        looked_at=row["looked_at"],
    )
    shown = answer_of_envelope(envelope, request_of(row))
    return None if isinstance(shown, FreeReplyAnswer) else shown


def label(row: dict[str, Any]) -> str:
    return f"{row['set']}:{row['case']}@{row['run']}"


@pytest.mark.parametrize("row", ROWS, ids=label)
def test_each_recorded_reply_gets_the_verdict_its_reading_gives(row: dict[str, Any]):
    assert checked(row) == row["expect"], row["text"]


def test_the_readings_agree_with_what_the_runs_recorded():
    """A true catch, and an honest reply outside the allow-list, fail the check that failed in the
    run. An honest can't failed a check then. A reply the verifier stopped passed the code."""
    for row in ROWS:
        match row["call"]:
            case "caught" | "honest_kept":
                assert row["recorded"] == row["expect"] is not None, label(row)
            case "honest_cant":
                assert row["recorded"] in ("claims_unbuilt", "skips_a_yes"), label(row)
            case "verifier":
                assert str(row["recorded"]).startswith("verifier_"), label(row)
            case "shown":
                assert row["recorded"] is None, label(row)
            case other:
                pytest.fail(f"{label(row)}: unknown reading {other}")
