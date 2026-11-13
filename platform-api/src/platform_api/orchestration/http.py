import hmac
import logging
from datetime import datetime
from typing import Annotated, Any, Literal, Self, TypedDict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, TypeAdapter, model_validator

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
from platform_api.orchestration.connections import Connections
from platform_api.orchestration.questions import AnswerRefusal, Question, QuestionId
from platform_api.orchestration.runs import (
    Acting,
    AwaitingApproval,
    Expired,
    Failed,
    Lost,
    Pending,
    Proposed,
    Rejected,
    Skipped,
    Succeeded,
    Working,
)
from platform_api.orchestration.runs import StepName as DomainStep
from platform_api.orchestration.schedule_store import ScheduleTicker
from platform_api.orchestration.service import (
    AnswerRefused,
    Decided,
    DecisionRace,
    DecisionRefused,
    KeyAskedAnother,
    NotFound,
    NotRetryable,
    Orchestrator,
    QuestionAnswered,
    QuestionAsked,
    QuestionRefused,
    Retried,
    RunDetail,
    approval_link,
    steps_view,
)
from platform_api.orchestration.service import RetryLater as RetryLaterError
from platform_api.orchestration.teams import AdaptiveCard, TeamsStub
from platform_api.orchestration.write_actions import Proposal
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
    DeclineReason,
    ErrorBody,
    FailureReason,
    FailureStage,
    QuestionText,
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


class ApprovalActionView(WriteActionView):
    site_name: str = Field(
        description="Where this write goes, as the Approver reads it before saying yes: "
        '"the practice Jira", or the host of the Jira set up now. "a Jira that is no longer set '
        'up" when the target names another Jira site, or none, so the write would be refused.'
    )


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
    url: str | None = None


class _RunBase(WireModel):
    run_id: RunId
    use_case_id: str
    use_case_name: str
    use_case_version: int
    started_by: UserId
    trigger: Trigger
    test: bool = Field(description="True when a person started it with Do a test run.")
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


class SkippedView(_RunBase):
    state: Literal["skipped"] = "skipped"
    waiting_run_id: RunId = Field(
        description="The earlier run of the same workflow that was still waiting for a yes."
    )


class ExpiredView(_RunBase):
    state: Literal["expired"] = "expired"
    proposal: ProposalView
    approval: ApprovalRef


class LostView(_RunBase):
    state: Literal["lost"] = "lost"
    proposal: ProposalView
    approval: ApprovalRef


type RunView = Annotated[
    PendingView
    | WorkingView
    | ProposedView
    | AwaitingApprovalView
    | ActingView
    | SucceededView
    | RejectedView
    | FailedView
    | SkippedView
    | ExpiredView
    | LostView,
    Field(discriminator="state"),
]

run_view_adapter: TypeAdapter[RunView] = TypeAdapter(RunView)


class RunList(WireModel):
    runs: list[RunView]


class RetryAccepted(WireModel):
    state: Literal["pending", "acting"]


class AnswerView(WireModel):
    text: str
    by: UserId
    at: datetime


class QuestionView(WireModel):
    question_id: QuestionId
    asked_by: UserId
    asked_at: datetime
    text: str
    answer: AnswerView | None = Field(
        description="The requester's answer. Null until they answer, and for good when the "
        "request was decided first."
    )


class QuestionIn(WireIn):
    text: QuestionText = Field(description="The question for the requester, 1 to 1000 characters.")


class QuestionAnswerIn(WireIn):
    text: QuestionText = Field(description="The requester's answer, 1 to 1000 characters.")


class ApprovalView(WireModel):
    approval_id: ApprovalId
    run_id: RunId
    digest: Digest
    actions: list[ApprovalActionView]
    steps: list[ApprovalStepView]
    you_can_decide: bool
    why_not: Refusal | None
    use_case_id: str
    use_case_name: str
    owner: UserId = Field(description="Who set the workflow up.")
    started_by: UserId
    trigger: Trigger
    retried_by: list[UserId] = Field(
        description="Who retried the run, as the approval gate counts them for this request, "
        "each named once, in the order of their first retry. The gate refuses owner, started_by "
        "and these people as their own work."
    )
    found: str = Field(
        description="What the agents found, in their own words. It is empty once the request is "
        "decided, and it can be empty before. The digest covers only the actions, so a decision "
        "never covers this text."
    )
    not_checked: list[str] = Field(
        description="What this run couldn't check: the software a check couldn't read, by name, "
        "in the watchlist's order. Empty when it read everything and for a workflow of agents. "
        "It stays once the request is decided, so the record shows what the Approver was told. "
        "It is for the reader and decides nothing."
    )
    requester: UserId = Field(
        description="Who answers questions on this request: whoever started the run, or the "
        "workflow's owner when its schedule started it."
    )
    questions: list[QuestionView] = Field(
        description="What Approvers asked the requester, the first asked first. A question "
        "decides nothing. Once the request is decided they stay here, read only."
    )


class DecisionIn(WireIn):
    step: int
    verdict: Verdict
    digest: Digest
    reason: DeclineReason | None = Field(
        default=None,
        description="Why the Approver declines, up to 200 characters. Optional, and only with "
        '"verdict": "decline". It is a note on the decline and decides nothing.',
    )

    @model_validator(mode="after")
    def _a_reason_only_with_a_decline(self) -> Self:
        if self.reason is not None and self.verdict is not Verdict.DECLINE:
            raise ValueError("A reason goes only with a decline.")
        return self


class DecisionView(WireModel):
    step: int
    by: UserId
    verdict: Verdict
    at: datetime
    reason: str | None = Field(description="Why the Approver declined, when they gave a reason.")


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


log = logging.getLogger(__name__)

router = APIRouter()

StepKey = Annotated[str, Header(alias="X-Step-Key")]


def current_orchestrator(request: Request) -> Orchestrator:
    orchestrator: Orchestrator = request.app.state.orchestrator
    return orchestrator


def current_ticker(request: Request) -> ScheduleTicker:
    ticker: ScheduleTicker = request.app.state.schedule_ticker
    return ticker


def current_connections(request: Request) -> Connections:
    connections: Connections = request.app.state.connections
    return connections


def current_teams_stub(request: Request) -> TeamsStub:
    stub: TeamsStub = request.app.state.teams_stub
    return stub


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
    test: bool
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
        test=record.spec.test,
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
                        url=w.url,
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
        case Skipped():
            return SkippedView(**base, waiting_run_id=state.waiting)
        case Expired() | Lost():
            assert detail.proposal is not None and detail.approval is not None
            view = ExpiredView if isinstance(state, Expired) else LostView
            return view(
                **base,
                proposal=proposal_view(detail.proposal),
                approval=approval_ref(detail.approval, detail.decisions),
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


ANSWER_REFUSALS: dict[AnswerRefusal, tuple[int, str]] = {
    AnswerRefusal.NOT_THE_REQUESTER: (
        403,
        "Only the person who started this run, or owns its schedule, can answer.",
    ),
    AnswerRefusal.DECIDED: (409, "The request was decided before this answer."),
    AnswerRefusal.ANSWERED: (409, "This question already has an answer."),
}


def question_view(question: Question) -> QuestionView:
    answer = question.answer
    return QuestionView(
        question_id=question.id,
        asked_by=question.asked_by,
        asked_at=question.asked_at,
        text=question.text,
        answer=None if answer is None else AnswerView(text=answer.text, by=answer.by, at=answer.at),
    )


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
        status=status,
        decision=DecisionView(
            step=d.step_index, by=d.by, verdict=d.verdict, at=d.at, reason=d.reason
        ),
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
    run = detail.run
    return ApprovalView(
        approval_id=detail.request.id,
        run_id=detail.request.run_id,
        digest=detail.request.digest,
        actions=[
            ApprovalActionView(**action.model_dump(), site_name=name)
            for action, name in zip(
                proposal_view(detail.proposal).actions, detail.site_names, strict=True
            )
        ],
        steps=steps_view(detail.request, detail.decisions),
        you_can_decide=detail.why_not is None,
        why_not=detail.why_not,
        use_case_id=run.spec.use_case_id,
        use_case_name=run.spec.use_case_name,
        owner=run.spec.owner,
        started_by=run.started_by,
        trigger=run.spec.trigger,
        retried_by=[u for u in dict.fromkeys(run.retried_by) if u in detail.request.parties],
        found=detail.found,
        not_checked=list(detail.not_checked),
        requester=detail.requester,
        questions=[question_view(q) for q in detail.questions],
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
    result = await orchestrator.decide(
        approval_id, principal, body.step, body.verdict, body.digest, body.reason
    )
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
    "/api/v1/approvals/{approval_id}/questions",
    status_code=201,
    response_model=QuestionView,
    tags=["orchestration"],
    description=(
        "Asks the requester a question on a request that waits for a yes. Only someone who may "
        "decide the open step may ask. A question decides nothing: the request keeps waiting, "
        "and its steps and decisions stay as they were. The same Idempotency-Key from the same "
        "person, with the same words, answers the question it asked before."
    ),
    responses={
        **SIGNED_IN,
        200: {"model": QuestionView, "description": "This Idempotency-Key asked it before"},
        403: {
            "model": RefusalOut | ErrorBody,
            "description": "This person cannot decide the open step, so cannot ask, or is not "
            "on the People list",
        },
        404: error_response("No such approval"),
        409: error_response("This Idempotency-Key already asked a question with other words"),
    },
)
async def ask_question(
    approval_id: ApprovalId,
    body: QuestionIn,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    orchestrator: CurrentOrchestrator,
    response: Response,
) -> QuestionView | JSONResponse:
    match await orchestrator.ask(approval_id, principal, body.text, idempotency_key):
        case QuestionAsked(question, repeated):
            if repeated:
                response.status_code = 200
            return question_view(question)
        case QuestionRefused(reason):
            return _json(403, RefusalOut(refusal=reason, message=REFUSAL_MESSAGES[reason]))
        case KeyAskedAnother():
            raise HTTPException(
                status_code=409, detail="This key already asked a question with other words."
            )
        case NotFound():
            raise HTTPException(status_code=404, detail="No such approval")


@router.post(
    "/api/v1/approvals/{approval_id}/questions/{question_id}/answer",
    status_code=201,
    response_model=QuestionView,
    tags=["orchestration"],
    description=(
        "Answers a question on a request. Only the requester may answer: whoever started the "
        "run, or the workflow's owner when its schedule started it. Each question takes one "
        "answer, while the request waits. An answer decides nothing: the request keeps waiting "
        "for someone else's yes. The same answer sent again answers the question as it is."
    ),
    responses={
        **SIGNED_IN,
        200: {"model": QuestionView, "description": "The same answer was already kept"},
        403: error_response(
            "Only the requester can answer, or the person is not on the People list"
        ),
        404: error_response("No such question on this approval"),
        409: error_response(
            "The request was decided before the answer, or the question has another answer"
        ),
    },
)
async def answer_question(
    approval_id: ApprovalId,
    question_id: QuestionId,
    body: QuestionAnswerIn,
    principal: CurrentPrincipal,
    orchestrator: CurrentOrchestrator,
    response: Response,
) -> QuestionView:
    match await orchestrator.answer(approval_id, question_id, principal, body.text):
        case QuestionAnswered(question, repeated):
            if repeated:
                response.status_code = 200
            return question_view(question)
        case AnswerRefused(reason):
            status, words = ANSWER_REFUSALS[reason]
            raise HTTPException(status_code=status, detail=words)
        case NotFound():
            raise HTTPException(status_code=404, detail="No such question on this approval")


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
    step_key: StepKey,
    request: Request,
    ticker: Annotated[ScheduleTicker, Depends(current_ticker)],
    connections: Annotated[Connections, Depends(current_connections)],
) -> TickOut:
    check_step_key(request, step_key)
    started = await ticker.tick()
    try:
        await connections.check_due()
    except Exception as error:
        # The runs are already started, so a check that fails must not fail the tick.
        log.warning("the connection checks did not finish: %s", type(error).__name__)
    return TickOut(started=started)


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
