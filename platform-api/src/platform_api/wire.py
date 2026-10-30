from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal, NoReturn, cast

from fastapi import HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from platform_api.shared import UserId


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NUL_MESSAGE = "This text holds a NUL character (\\u0000), which can't be saved. Remove it."


def holds_nul(value: object) -> bool:
    match value:
        case str():
            return "\x00" in value
        case BaseModel():
            return any(holds_nul(v) for v in value.__dict__.values())
        case dict():
            entries = cast(dict[object, object], value)
            return any(holds_nul(k) or holds_nul(v) for k, v in entries.items())
        case list() | tuple():
            return any(holds_nul(v) for v in cast(Sequence[object], value))
        case _:
            return False


class WireIn(WireModel):
    """A request body. PostgreSQL text cannot hold a NUL byte, so any text that holds one is
    refused with a 422 naming its field, before it reaches a store."""

    @field_validator("*")
    @classmethod
    def _no_nul(cls, value: object) -> object:
        if holds_nul(value):
            raise PydanticCustomError("nul_character", NUL_MESSAGE)
        return value


class ErrorBody(WireModel):
    detail: str


type Responses = dict[int | str, dict[str, Any]]


def error_response(description: str) -> dict[str, Any]:
    return {"model": ErrorBody, "description": description}


def not_implemented() -> NoReturn:
    raise HTTPException(status_code=501, detail="Not implemented yet")


type Leg = Literal["work", "act"]
type StepName = Literal["run_agents", "ask_approval", "write_action"]
type StepOutcome = Literal[
    "proposed",
    "nothing_to_write",
    "approval_opened",
    "written",
    "failed",
    "superseded",
    "refused",
    "replayed",
]
type RunState = Literal[
    "pending",
    "working",
    "proposed",
    "awaiting_approval",
    "acting",
    "succeeded",
    "rejected",
    "failed",
]
type RunOutcome = Literal["written", "nothing_to_write"]
type FailureStage = Literal["pending", "working", "proposed", "acting"]
type FailureReason = Literal[
    "AgentError",
    "WorkflowNodeError",
    "TimedOut",
    "DispatchFailed",
    "WriteFailed",
    "SafetyDenied",
    "UnboundIntent",
    "OutOfOrderStep",
]
type Trigger = Literal["person", "schedule"]
type ApprovalStepStatus = Literal["waiting", "open", "approved", "declined"]


class ApprovalStepView(WireModel):
    index: int
    label: str
    status: ApprovalStepStatus
    decided_by: UserId | None = None
    decided_at: datetime | None = None


REPO_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"


def _not_a_dot_segment(repo: str) -> str:
    if repo.split("/")[-1] in {".", ".."}:
        raise ValueError("repo must not be . or ..")
    return repo


type RepoName = Annotated[str, Field(pattern=REPO_PATTERN), AfterValidator(_not_a_dot_segment)]
