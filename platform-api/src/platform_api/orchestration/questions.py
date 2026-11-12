"""Questions on a request (ADR 0043). An Approver who may decide the open step asks the
requester, who may answer once while the request waits. A question is a message on the request:
nothing in the approval gate reads it, so it never approves, declines or changes anything."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, NewType

from platform_api.db import UnitOfWork
from platform_api.orchestration.approvals import ApprovalStatus, Open
from platform_api.orchestration.spec import RunSpec
from platform_api.shared import ApprovalId, UserId, new_id

QuestionId = NewType("QuestionId", str)


@dataclass(frozen=True)
class Answer:
    text: str
    by: UserId
    at: datetime


@dataclass(frozen=True)
class Question:
    id: QuestionId
    approval_id: ApprovalId
    asked_by: UserId
    asked_at: datetime
    text: str
    answer: Answer | None


class AnswerRefusal(Enum):
    NOT_THE_REQUESTER = "not_the_requester"
    DECIDED = "decided"
    ANSWERED = "answered"


def requester_of(spec: RunSpec, started_by: UserId) -> UserId:
    """Who answers questions on a request: whoever started the run, or the workflow's owner when
    its schedule did. They are always a party to the run, so they never decide it."""
    return spec.owner if spec.trigger == "schedule" else started_by


def answer_refusal(
    question: Question, requester: UserId, status: ApprovalStatus, by: UserId
) -> AnswerRefusal | None:
    if by != requester:
        return AnswerRefusal.NOT_THE_REQUESTER
    if question.answer is not None:
        return AnswerRefusal.ANSWERED
    if not isinstance(status, Open):
        return AnswerRefusal.DECIDED
    return None


def repeats(question: Question, by: UserId, text: str) -> bool:
    """The same answer sent again, which finds it already kept."""
    answer = question.answer
    return answer is not None and answer.by == by and answer.text == text


_COLUMNS = "question_id, approval_id, asked_by, asked_at, text, answer, answered_by, answered_at"


def _question(row: Mapping[str, Any]) -> Question:
    answer = (
        None
        if row["answer"] is None
        else Answer(row["answer"], UserId(row["answered_by"]), row["answered_at"])
    )
    return Question(
        QuestionId(row["question_id"]),
        ApprovalId(row["approval_id"]),
        UserId(row["asked_by"]),
        row["asked_at"],
        row["text"],
        answer,
    )


async def asked_with(
    uow: UnitOfWork, approval_id: ApprovalId, by: UserId, idempotency_key: str
) -> Question | None:
    row = await (
        await uow.conn.execute(
            f"SELECT {_COLUMNS} FROM orchestration.approval_questions "
            "WHERE approval_id = %s AND asked_by = %s AND idempotency_key = %s",
            (approval_id, by, idempotency_key),
        )
    ).fetchone()
    return None if row is None else _question(row)


async def insert_question(
    uow: UnitOfWork, approval_id: ApprovalId, by: UserId, text: str, idempotency_key: str
) -> Question:
    row = await (
        await uow.conn.execute(
            "INSERT INTO orchestration.approval_questions (question_id, approval_id, asked_by, "
            "asked_at, text, idempotency_key) VALUES (%s, %s, %s, %s, %s, %s) "
            f"RETURNING {_COLUMNS}",
            (new_id("q"), approval_id, by, uow.now, text, idempotency_key),
        )
    ).fetchone()
    assert row is not None
    return _question(row)


async def load_question(
    uow: UnitOfWork, approval_id: ApprovalId, question_id: QuestionId
) -> Question | None:
    row = await (
        await uow.conn.execute(
            f"SELECT {_COLUMNS} FROM orchestration.approval_questions "
            "WHERE approval_id = %s AND question_id = %s",
            (approval_id, question_id),
        )
    ).fetchone()
    return None if row is None else _question(row)


async def save_answer(uow: UnitOfWork, question: Question, answer: Answer) -> Question | None:
    """The answered question, or None when it already has an answer."""
    row = await (
        await uow.conn.execute(
            "UPDATE orchestration.approval_questions SET answer = %s, answered_by = %s, "
            "answered_at = %s WHERE question_id = %s AND answer IS NULL "
            f"RETURNING {_COLUMNS}",
            (answer.text, answer.by, answer.at, question.id),
        )
    ).fetchone()
    return None if row is None else _question(row)


async def load_questions_for(
    uow: UnitOfWork, approval_ids: Collection[ApprovalId]
) -> dict[ApprovalId, tuple[Question, ...]]:
    """Each approval's questions, the first asked first. An approval with none is left out."""
    if not approval_ids:
        return {}
    rows = await (
        await uow.conn.execute(
            f"SELECT {_COLUMNS} FROM orchestration.approval_questions "
            "WHERE approval_id = ANY(%s) ORDER BY approval_id, asked_at, question_id",
            (list(approval_ids),),
        )
    ).fetchall()
    questions: dict[ApprovalId, tuple[Question, ...]] = {}
    for row in rows:
        question = _question(row)
        questions[question.approval_id] = (*questions.get(question.approval_id, ()), question)
    return questions
