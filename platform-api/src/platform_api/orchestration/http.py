import hmac
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, TypeAdapter

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.orchestration.approvals import (
    ApprovalRequest,
    Approved,
    Decision,
    Declined,
    Refusal,
    Verdict,
    why_not,
)
from platform_api.orchestration.runs import (
    Acting,
    AwaitingApproval,
    Failed,
    Pending,
    Proposed,
    Rejected,
    Succeeded,
    Working,
)
from platform_api.orchestration.runs import StepName as DomainStep
from platform_api.orchestration.schedule_store import ScheduleTicker
from platform_api.orchestration.service import (
    Decided,
    DecisionRace,
    DecisionRefused,
    NotFound,
    NotRetryable,
    Orchestrator,
    Retried,
    RunDetail,
    approval_link,
    steps_view,
)
from platform_api.orchestration.service import RetryLater as RetryLaterError
from platform_api.orchestration.teams import AdaptiveCard, TeamsStub
from platform_api.orchestration.write_actions import (
    MockJiraConnector,
    MockTicket,
    Proposal,
    TicketStatus,
)
from platform_api.shared import (
    ApprovalId,
    Digest,
    N8nExecutionId,
    Principal,
    ProposalId,
    Role,
    RunId,
    UserId,
    has_id_shape,
)
from platform_api.wire import (
    ApprovalStepView,
    ErrorBody,
    FailureReason,
    FailureStage,
    RunOutcome,
    StepName,
    StepOutcome,
    Trigger,
    WireIn,
    WireModel,
    error_response,
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
    trigger: Trigger
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
    you_can_decide: bool


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


class DecisionIn(WireIn):
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


class TickOut(WireModel):
    started: list[RunId]


class WorkflowFailureIn(WireIn):
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
    card: AdaptiveCard | None = Field(
        description="The Adaptive Card a real Teams channel gets, with its outcome on top once "
        "decided. Null only for a message posted before cards."
    )


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
    status: TicketStatus
    done_at: datetime | None


class MockJiraTickets(WireModel):
    tickets: list[MockJiraTicket]


router = APIRouter()

StepKey = Annotated[str, Header(alias="X-Step-Key")]


def current_orchestrator(request: Request) -> Orchestrator:
    orchestrator: Orchestrator = request.app.state.orchestrator
    return orchestrator


def current_ticker(request: Request) -> ScheduleTicker:
    ticker: ScheduleTicker = request.app.state.schedule_ticker
    return ticker


def current_teams_stub(request: Request) -> TeamsStub:
    stub: TeamsStub = request.app.state.teams_stub
    return stub


def current_mock_jira(request: Request) -> MockJiraConnector:
    jira: MockJiraConnector = request.app.state.mock_jira
    return jira


def check_step_key(request: Request, step_key: StepKey) -> None:
    expected: str = request.app.state.step_key
    if not hmac.compare_digest(step_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Bad step key")


def require_operator(principal: CurrentPrincipal) -> Principal:
    if Role.OPERATOR not in principal.roles:
        raise HTTPException(
            status_code=403, detail="Only an Operator can do this. Ask an Operator on the team."
        )
    return principal


CurrentOrchestrator = Annotated[Orchestrator, Depends(current_orchestrator)]
Operator = Annotated[Principal, Depends(require_operator)]


def proposal_view(proposal: Proposal) -> ProposalView:
    return ProposalView(
        proposal_id=proposal.id,
        digest=proposal.digest,
        actions=[
            WriteActionView(
                connector=a.connector,
                operation=a.operation,
                target=dict(a.target),
                fields=dict(a.fields),
            )
            for a in proposal.actions
        ],
    )


def approval_ref(request: ApprovalRequest, decisions: tuple[Decision, ...]) -> ApprovalRef:
    return ApprovalRef(
        approval_id=request.id,
        link=approval_link(request.id),
        steps=steps_view(request, decisions),
    )


class RunBaseFields(TypedDict):
    run_id: RunId
    use_case_id: str
    use_case_name: str
    use_case_version: int
    started_by: UserId
    trigger: Trigger
    started_at: datetime
    updated_at: datetime
    last_seq: int
    events_url: str


def run_view(detail: RunDetail, viewer: Principal) -> RunView:
    record = detail.record
    base = RunBaseFields(
        run_id=record.run_id,
        use_case_id=record.spec.use_case_id,
        use_case_name=record.spec.use_case_name,
        use_case_version=record.spec.use_case_version,
        started_by=record.started_by,
        trigger=record.spec.trigger,
        started_at=record.started_at,
        updated_at=record.updated_at,
        last_seq=detail.last_seq,
        events_url=f"/api/v1/runs/{record.run_id}/events",
    )
    state = record.state
    match state:
        case Pending():
            return PendingView(**base)
        case Working():
            return WorkingView(**base, n8n_execution_id=state.execution, attempt=state.attempt)
        case Proposed():
            assert detail.proposal is not None
            return ProposedView(**base, proposal=proposal_view(detail.proposal))
        case AwaitingApproval():
            assert detail.proposal is not None and detail.approval is not None
            return AwaitingApprovalView(
                **base,
                proposal=proposal_view(detail.proposal),
                approval=approval_ref(detail.approval, detail.decisions),
                # The same rule, and the same person, as the approval's own view.
                you_can_decide=why_not(detail.approval, detail.decisions, viewer) is None,
            )
        case Acting():
            assert detail.proposal is not None and detail.approval is not None
            return ActingView(
                **base,
                proposal=proposal_view(detail.proposal),
                approval=approval_ref(detail.approval, detail.decisions),
            )
        case Succeeded():
            return SucceededView(
                **base,
                outcome=state.outcome.value,
                written=[
                    WriteDoneView(
                        connector=w.connector,
                        operation=w.operation,
                        external_reference=w.external_reference,
                        approved_by=list(w.approved_by),
                    )
                    for w in state.written
                ],
            )
        case Rejected():
            assert detail.proposal is not None and detail.approval is not None
            return RejectedView(
                **base,
                proposal=proposal_view(detail.proposal),
                approval=approval_ref(detail.approval, detail.decisions),
                rejected_by=state.by,
                step=state.step,
            )
        case Failed():
            return FailedView(
                **base,
                stage=state.stage.value,
                reason=state.failure.reason.value,
                retryable=state.failure.retryable,
                message=state.failure.message,
            )


REFUSAL_MESSAGES: dict[Refusal, str] = {
    Refusal.OWN_WORK: "This run is your own work, so another Approver must decide.",
    Refusal.NOT_AN_APPROVER: "Only an Approver can decide.",
    Refusal.NOT_OPEN: "This approval is already decided.",
    Refusal.WRONG_STEP: "This is not the step that is open now.",
    Refusal.DECIDED_EARLIER_STEP: (
        "You decided an earlier step. Another Approver must decide this one."
    ),
    Refusal.NOT_ELIGIBLE: "You are not one of the people who can decide this step.",
    Refusal.STALE_DIGEST: "The proposal changed since you saw it. Reload the page and look again.",
    Refusal.INVALID_DECISIONS: "The recorded decisions are inconsistent. Ask a maintainer.",
}


def _json(status_code: int, body: WireModel) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _decision_out(decided: Decided) -> DecisionOut:
    match decided.status:
        case Approved():
            status = "approved"
        case Declined():
            status = "declined"
        case _:
            status = "open"
    d = decided.decision
    return DecisionOut(
        status=status, decision=DecisionView(step=d.step_index, by=d.by, verdict=d.verdict, at=d.at)
    )


@router.get("/api/v1/runs", tags=["orchestration"], responses=SIGNED_IN)
async def list_runs(principal: CurrentPrincipal, orchestrator: CurrentOrchestrator) -> RunList:
    return RunList(runs=[run_view(d, principal) for d in await orchestrator.list_runs()])


@router.get(
    "/api/v1/runs/{run_id}",
    tags=["orchestration"],
    responses={**SIGNED_IN, 404: error_response("No such run")},
)
async def get_run(
    run_id: RunId, principal: CurrentPrincipal, orchestrator: CurrentOrchestrator
) -> RunView:
    detail = await orchestrator.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="No such run")
    return run_view(detail, principal)


@router.post(
    "/api/v1/runs/{run_id}/retry",
    status_code=202,
    tags=["orchestration"],
    responses={
        **OPERATORS_ONLY,
        404: error_response("No such run"),
        409: error_response("The run is not failed, or its failure cannot be retried"),
    },
)
async def retry_run(
    run_id: RunId, principal: Operator, orchestrator: CurrentOrchestrator
) -> RetryAccepted:
    match await orchestrator.retry(run_id, principal):
        case Retried(state):
            return RetryAccepted(state="acting" if isinstance(state, Acting) else "pending")
        case NotRetryable(detail):
            raise HTTPException(status_code=409, detail=detail)
        case NotFound():
            raise HTTPException(status_code=404, detail="No such run")


@router.get(
    "/api/v1/approvals/{approval_id}",
    tags=["orchestration"],
    responses={**SIGNED_IN, 404: error_response("No such approval")},
)
async def get_approval(
    approval_id: ApprovalId, principal: CurrentPrincipal, orchestrator: CurrentOrchestrator
) -> ApprovalView:
    detail = await orchestrator.get_approval(approval_id, principal)
    if detail is None:
        raise HTTPException(status_code=404, detail="No such approval")
    return ApprovalView(
        approval_id=detail.request.id,
        run_id=detail.request.run_id,
        digest=detail.request.digest,
        actions=proposal_view(detail.proposal).actions,
        steps=steps_view(detail.request, detail.decisions),
        you_can_decide=detail.why_not is None,
        why_not=detail.why_not,
    )


@router.post(
    "/api/v1/approvals/{approval_id}/decisions",
    status_code=201,
    response_model=DecisionOut,
    tags=["orchestration"],
    responses={
        **SIGNED_IN,
        200: {"model": DecisionOut, "description": "The same decision was already recorded"},
        403: {
            "model": RefusalOut | ErrorBody,
            "description": "This person cannot decide this step, or is not on the People list",
        },
        404: error_response("No such approval"),
        409: error_response("Another Approver decided this step first"),
    },
)
async def decide(
    approval_id: ApprovalId,
    body: DecisionIn,
    principal: CurrentPrincipal,
    orchestrator: CurrentOrchestrator,
    response: Response,
) -> DecisionOut | JSONResponse:
    result = await orchestrator.decide(approval_id, principal, body.step, body.verdict, body.digest)
    match result:
        case Decided() as decided:
            if decided.repeated:
                response.status_code = 200
            return _decision_out(decided)
        case DecisionRefused(reason):
            return _json(403, RefusalOut(refusal=reason, message=REFUSAL_MESSAGES[reason]))
        case DecisionRace():
            raise HTTPException(status_code=409, detail="Another Approver decided this step first")
        case NotFound():
            raise HTTPException(status_code=404, detail="No such approval")


@router.post(
    "/internal/v1/runs/{run_id}/steps/{step}",
    response_model=StepResponseOut,
    tags=["internal"],
    responses={
        401: error_response("Bad step key"),
        503: {"model": RetryLater, "description": "Try the same step again later"},
    },
)
async def run_step(
    run_id: RunId,
    step: StepName,
    step_key: StepKey,
    n8n_execution: Annotated[str, Header(alias="X-N8N-Execution")],
    request: Request,
    orchestrator: CurrentOrchestrator,
) -> StepResponseOut | JSONResponse:
    check_step_key(request, step_key)
    # n8n's run workflow copies run_id from a webhook body that anyone may send while its editor
    # is open (ADR 0034), so only an id that new_id could have made goes on.
    if not has_id_shape(run_id, "run"):
        raise HTTPException(status_code=422, detail="Not a run id")
    try:
        reply = await orchestrator.on_step(run_id, DomainStep(step), N8nExecutionId(n8n_execution))
    except RetryLaterError as error:
        return _json(503, RetryLater(detail=str(error)))
    return StepResponseOut(proceed=reply.proceed, outcome=reply.outcome, detail=reply.detail)


@router.post(
    "/internal/v1/schedules/tick",
    tags=["internal"],
    description=(
        "Asked every 5 minutes by the schedule_tick workflow. Starts one check for each "
        "schedule that is due and answers the runs it started."
    ),
    responses={401: error_response("Bad step key")},
)
async def tick_schedules(
    step_key: StepKey, request: Request, ticker: Annotated[ScheduleTicker, Depends(current_ticker)]
) -> TickOut:
    check_step_key(request, step_key)
    return TickOut(started=await ticker.tick())


@router.post(
    "/internal/v1/workflow-failures",
    status_code=202,
    tags=["internal"],
    response_class=Response,
    responses={401: error_response("Bad step key")},
)
async def report_workflow_failure(
    body: WorkflowFailureIn, step_key: StepKey, request: Request, orchestrator: CurrentOrchestrator
) -> None:
    check_step_key(request, step_key)
    await orchestrator.on_workflow_failure(
        N8nExecutionId(body.execution_id), body.workflow, body.last_node, body.message
    )


@router.get("/api/v1/teams-stub/messages", tags=["stubs"], responses=SIGNED_IN)
async def list_teams_stub_messages(
    principal: CurrentPrincipal, stub: Annotated[TeamsStub, Depends(current_teams_stub)]
) -> TeamsStubMessages:
    return TeamsStubMessages(
        messages=[
            TeamsStubMessage(
                id=m.id,
                ts=m.ts,
                channel=m.channel,
                text=m.text,
                link=m.link,
                run_id=m.run_id,
                approval_id=m.approval_id,
                card=m.card,
            )
            for m in await stub.messages()
        ]
    )


def mock_jira_ticket(ticket: MockTicket) -> MockJiraTicket:
    return MockJiraTicket(
        key=ticket.key,
        project=ticket.project,
        title=ticket.title,
        body=ticket.body,
        created_at=ticket.created_at,
        run_id=ticket.run_id,
        proposal_id=ticket.proposal_id,
        status=ticket.status,
        done_at=ticket.done_at,
    )


MockJira = Annotated[MockJiraConnector, Depends(current_mock_jira)]


@router.get("/api/v1/mock-jira/tickets", tags=["stubs"], responses=SIGNED_IN)
async def list_mock_jira_tickets(principal: CurrentPrincipal, jira: MockJira) -> MockJiraTickets:
    return MockJiraTickets(tickets=[mock_jira_ticket(t) for t in await jira.tickets()])


@router.post(
    "/api/v1/mock-jira/tickets/{key}/done",
    tags=["stubs"],
    description=(
        "Marks a practice Jira ticket Done, as a person would in Jira. The watchlist then "
        "moves our version to the version the ticket named, so only an Operator may do it. "
        "Marking a Done ticket again changes nothing."
    ),
    responses={**OPERATORS_ONLY, 404: error_response("No such ticket")},
)
async def mark_mock_jira_ticket_done(
    key: str, principal: Operator, jira: MockJira
) -> MockJiraTicket:
    ticket = await jira.mark_done(key)
    if ticket is None:
        raise HTTPException(status_code=404, detail="No such ticket")
    return mock_jira_ticket(ticket)
