from datetime import datetime
from typing import Literal, NoReturn

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from platform_api.shared import UserId


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
type ApprovalStepStatus = Literal["waiting", "open", "approved", "declined"]


class ApprovalStepView(WireModel):
    index: int
    label: str
    status: ApprovalStepStatus
    decided_by: UserId | None = None
    decided_at: datetime | None = None
