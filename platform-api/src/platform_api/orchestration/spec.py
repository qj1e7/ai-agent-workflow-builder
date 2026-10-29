from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import Field

from platform_api.orchestration.agents import CardSpec
from platform_api.orchestration.approvals import ApprovalPolicy
from platform_api.orchestration.write_actions import Binding
from platform_api.shared import Principal, RunId, SoftwareId, UseCaseId, UserId
from platform_api.wire import Trigger


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


@dataclass(frozen=True)
class CardRun:
    """One agent of a card run: the card as it was when the run started, the Operator's values,
    and where its writes land. The bindings come from the tool rules and the values, never from
    anything the model says."""

    card: CardSpec
    values: Mapping[str, str]
    bindings: Mapping[str, Binding]


@dataclass(frozen=True)
class CardsTask:
    agents: tuple[CardRun, ...]
    kind: Literal["cards"] = "cards"


type Task = Annotated[WatchlistTask | CardsTask, Field(discriminator="kind")]


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
    trigger: Trigger = "person"


@dataclass(frozen=True)
class RunStarted:
    run_id: RunId
    created: bool


class RunStarter(Protocol):
    async def start_run(
        self, spec: RunSpec, principal: Principal, idempotency_key: str
    ) -> RunStarted: ...
