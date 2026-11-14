from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Literal, Protocol

from pydantic import Field

from platform_api.orchestration.agents import CardSpec
from platform_api.orchestration.approvals import ApprovalPolicy
from platform_api.orchestration.working_hours import EXPIRES_AFTER
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
    from_first_check: bool = False
    """True when our_version is the newest release the first check read, not one anyone gave."""


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
class N8nTarget:
    """The use case's own n8n workflow, which carries its runs (ENGINE-PLAN 2.3)."""

    workflow_id: str
    webhook_id: str | None
    """Start from the Portal's webhookId in the version that runs, where Run now is sent. None
    in a workflow without that block, which only its schedule or a test run starts."""


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
    test: bool = False
    """A person started it with Do a test run. A row stored without it reads False."""
    stops_at_gate: bool = False
    """A test run of a draft: it stops at the approval gate, asks nobody for a yes and writes
    nothing (ADR 0044). A row stored without it reads False."""
    expires_after: timedelta = EXPIRES_AFTER
    """How long its request waits for a yes, in working hours, before it expires (ADR 0024)."""
    n8n: N8nTarget | None = None
    """Set when the use case runs as its own n8n workflow. None runs it through the shared run
    workflow, as every use case did before (ENGINE-PLAN 2.6). A row stored without it reads
    None."""


@dataclass(frozen=True)
class RunStarted:
    run_id: RunId
    created: bool


class RunStarter(Protocol):
    async def start_run(
        self, spec: RunSpec, principal: Principal, idempotency_key: str
    ) -> RunStarted: ...
