from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import Field

from platform_api.orchestration.approvals import ApprovalPolicy
from platform_api.orchestration.write_actions import Binding
from platform_api.shared import Principal, RunId, SoftwareId, UseCaseId, UserId


@dataclass(frozen=True)
class ReleaseTask:
    repo: str
    tag_pattern: str
    last_known_tag: str | None
    kind: Literal["release"] = "release"


@dataclass(frozen=True)
class SoftwareSource:
    ref: str
    kind: Literal["github"] = "github"


@dataclass(frozen=True)
class WatchedSoftware:
    """One watched software as the platform described it to the agents when the check started."""

    id: SoftwareId
    name: str
    source: SoftwareSource
    our_version: str | None
    open_ticket: str | None
    awaiting_approval: bool


@dataclass(frozen=True)
class WatchlistTask:
    tag_pattern: str
    software: tuple[WatchedSoftware, ...]
    kind: Literal["watchlist"] = "watchlist"


type Task = Annotated[ReleaseTask | WatchlistTask, Field(discriminator="kind")]


@dataclass(frozen=True)
class RunSpec:
    use_case_id: UseCaseId
    use_case_version: int
    use_case_name: str
    owner: UserId
    workflow: str
    instruction: str
    task: Task
    bindings: Mapping[str, Binding]
    approval_policy: ApprovalPolicy


@dataclass(frozen=True)
class RunStarted:
    run_id: RunId
    created: bool


class RunStarter(Protocol):
    async def start_run(
        self, spec: RunSpec, principal: Principal, idempotency_key: str
    ) -> RunStarted: ...

    async def latest_carry_forward(self, use_case_id: UseCaseId) -> str | None: ...
