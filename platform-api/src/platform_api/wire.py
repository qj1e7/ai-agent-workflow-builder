from datetime import datetime
from typing import Annotated, Any, Literal, NoReturn

from fastapi import HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from platform_api.shared import UserId


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
