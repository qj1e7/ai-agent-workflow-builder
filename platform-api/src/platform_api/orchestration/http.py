from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Response
from pydantic import Field, TypeAdapter

from platform_api.auth import CurrentPrincipal
from platform_api.orchestration.approvals import Refusal, Verdict
from platform_api.shared import ApprovalId, Digest, ProposalId, RunId, UserId
from platform_api.wire import (
    ApprovalStepView,
    FailureReason,
    FailureStage,
    RunOutcome,
    StepName,
    StepOutcome,
    WireModel,
    not_implemented,
)


class WriteActionView(WireModel):
    connector: str
    operation: str
    target: dict[str, Any]
    fields: dict[str, Any]


class ProposalView(WireModel):
    proposal_id: ProposalId
    digest: Digest
    actions: list[WriteActionView]


class ApprovalRef(WireModel):
    approval_id: ApprovalId
    link: str
    steps: list[ApprovalStepView]


class WriteDoneView(WireModel):
    connector: str
    operation: str
    external_reference: str
    approved_by: list[UserId]


class _RunBase(WireModel):
    run_id: RunId
    use_case_id: str
    use_case_name: str
    use_case_version: int
    started_by: UserId
    started_at: datetime
    updated_at: datetime
    last_seq: int
    events_url: str


class PendingView(_RunBase):
    state: Literal["pending"] = "pending"


class WorkingView(_RunBase):
    state: Literal["working"] = "working"
    n8n_execution_id: str
    attempt: int


class ProposedView(_RunBase):
    state: Literal["proposed"] = "proposed"
    proposal: ProposalView


class AwaitingApprovalView(_RunBase):
    state: Literal["awaiting_approval"] = "awaiting_approval"
    proposal: ProposalView
    approval: ApprovalRef


class ActingView(_RunBase):
    state: Literal["acting"] = "acting"
    proposal: ProposalView
    approval: ApprovalRef


class SucceededView(_RunBase):
    state: Literal["succeeded"] = "succeeded"
    outcome: RunOutcome
    written: list[WriteDoneView]


class RejectedView(_RunBase):
    state: Literal["rejected"] = "rejected"
    proposal: ProposalView
    approval: ApprovalRef
    rejected_by: UserId
    step: int


class FailedView(_RunBase):
    state: Literal["failed"] = "failed"
    stage: FailureStage
    reason: FailureReason
    retryable: bool
    message: str


type RunView = Annotated[
    PendingView
    | WorkingView
    | ProposedView
    | AwaitingApprovalView
    | ActingView
    | SucceededView
    | RejectedView
    | FailedView,
    Field(discriminator="state"),
]

run_view_adapter: TypeAdapter[RunView] = TypeAdapter(RunView)


class RunList(WireModel):
    runs: list[RunView]


class RetryAccepted(WireModel):
    state: Literal["pending", "acting"]


class ApprovalView(WireModel):
    approval_id: ApprovalId
    run_id: RunId
    digest: Digest
    actions: list[WriteActionView]
    steps: list[ApprovalStepView]
    you_can_decide: bool
    why_not: Refusal | None


class DecisionIn(WireModel):
    step: int
    verdict: Verdict
    digest: Digest


class DecisionView(WireModel):
    step: int
    by: UserId
    verdict: Verdict
    at: datetime


class DecisionOut(WireModel):
    status: Literal["open", "approved", "declined"]
    decision: DecisionView


class RefusalOut(WireModel):
    refusal: Refusal
    message: str


class StepResponseOut(WireModel):
    proceed: bool
    outcome: StepOutcome
    detail: str


class RetryLater(WireModel):
    retryable: Literal[True] = True
    detail: str


class WorkflowFailureIn(WireModel):
    execution_id: str
    workflow: str
    last_node: str
    message: str
    execution_url: str


class TeamsStubMessage(WireModel):
    id: str
    ts: datetime
    channel: str
    text: str
    link: str
    run_id: RunId
    approval_id: ApprovalId


class TeamsStubMessages(WireModel):
    messages: list[TeamsStubMessage]


class MockJiraTicket(WireModel):
    key: str
    project: str
    title: str
    body: str
    created_at: datetime
    run_id: RunId
    proposal_id: ProposalId


class MockJiraTickets(WireModel):
    tickets: list[MockJiraTicket]


router = APIRouter()

StepKey = Annotated[str, Header(alias="X-Step-Key")]


@router.get("/api/v1/runs", tags=["orchestration"])
def list_runs(principal: CurrentPrincipal) -> RunList:
    not_implemented()


@router.get("/api/v1/runs/{run_id}", tags=["orchestration"])
def get_run(run_id: RunId, principal: CurrentPrincipal) -> RunView:
    not_implemented()


@router.post("/api/v1/runs/{run_id}/retry", status_code=202, tags=["orchestration"])
def retry_run(run_id: RunId, principal: CurrentPrincipal) -> RetryAccepted:
    not_implemented()


@router.get("/api/v1/approvals/{approval_id}", tags=["orchestration"])
def get_approval(approval_id: ApprovalId, principal: CurrentPrincipal) -> ApprovalView:
    not_implemented()


@router.post(
    "/api/v1/approvals/{approval_id}/decisions",
    status_code=201,
    tags=["orchestration"],
    responses={
        200: {"model": DecisionOut, "description": "The same decision was already recorded"},
        403: {"model": RefusalOut, "description": "This person cannot decide this step"},
        409: {"description": "Another Approver decided this step first"},
    },
)
def decide(approval_id: ApprovalId, body: DecisionIn, principal: CurrentPrincipal) -> DecisionOut:
    not_implemented()


@router.post(
    "/internal/v1/runs/{run_id}/steps/{step}",
    tags=["internal"],
    responses={503: {"model": RetryLater, "description": "Try the same step again later"}},
)
def run_step(
    run_id: RunId,
    step: StepName,
    step_key: StepKey,
    n8n_execution: Annotated[str, Header(alias="X-N8N-Execution")],
) -> StepResponseOut:
    not_implemented()


@router.post(
    "/internal/v1/workflow-failures",
    status_code=202,
    tags=["internal"],
    response_class=Response,
)
def report_workflow_failure(body: WorkflowFailureIn, step_key: StepKey) -> None:
    not_implemented()


@router.get("/api/v1/teams-stub/messages", tags=["stubs"])
def list_teams_stub_messages(principal: CurrentPrincipal) -> TeamsStubMessages:
    not_implemented()


@router.get("/api/v1/mock-jira/tickets", tags=["stubs"])
def list_mock_jira_tickets(principal: CurrentPrincipal) -> MockJiraTickets:
    not_implemented()
