from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal, NoReturn, cast

from fastapi import HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from platform_api.shared import UserId


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NUL_MESSAGE = "This text holds a NUL character (\\u0000), which can't be saved. Remove it."
BROKEN_TEXT_MESSAGE = (
    "This text holds half of a character pair (a lone \\ud800 to \\udfff escape), "
    "which can't be saved. Remove it."
)


def holds_text(value: object, bad: Callable[[str], bool]) -> bool:
    """Whether any text in the value, a key included, is bad."""
    match value:
        case str():
            return bad(value)
        case BaseModel():
            return any(holds_text(v, bad) for v in value.__dict__.values())
        case dict():
            entries = cast(dict[object, object], value)
            return any(holds_text(k, bad) or holds_text(v, bad) for k, v in entries.items())
        case list() | tuple():
            return any(holds_text(v, bad) for v in cast(Sequence[object], value))
        case _:
            return False


def _has_nul(text: str) -> bool:
    return "\x00" in text


def _breaks_utf8(text: str) -> bool:
    """A lone surrogate, such as one sent as the escape \\ud800, has no UTF-8 form."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def holds_nul(value: object) -> bool:
    return holds_text(value, _has_nul)


class WireIn(WireModel):
    """A request body. PostgreSQL text cannot hold a NUL byte or a lone surrogate, so any text
    that holds one is refused with a 422 naming its field, before it reaches a store."""

    @field_validator("*")
    @classmethod
    def _savable_text(cls, value: object) -> object:
        if holds_nul(value):
            raise PydanticCustomError("nul_character", NUL_MESSAGE)
        if holds_text(value, _breaks_utf8):
            raise PydanticCustomError("broken_character", BROKEN_TEXT_MESSAGE)
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
