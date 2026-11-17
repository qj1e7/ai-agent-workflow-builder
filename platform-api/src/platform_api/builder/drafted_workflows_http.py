from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from platform_api.auth import SIGNED_IN, CurrentPrincipal
from platform_api.builder.drafted_workflows import (
    DraftChangeIn,
    DraftedWorkflows,
    DraftedWorkflowView,
    DraftSendIn,
    DraftWorkflowIn,
    Forbidden,
    NotFound,
    Refused,
    SetUpApprovalView,
    SetUpDecisionIn,
)
from platform_api.builder.http import operators_only
from platform_api.shared import Principal
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])

DRAFT_WORKFLOWS = "Only an Operator can draft workflows. Ask an Operator on the team."
NO_SUCH_DRAFT = "No such drafted workflow"
NO_SUCH_SET_UP = "No such set-up approval"
DECLINE_NEEDS_A_REASON = "Pick a reason to decline."
APPROVE_HAS_NO_REASON = "Only a decline has a reason."

Drafter = Annotated[Principal, Depends(operators_only(DRAFT_WORKFLOWS))]


def current_drafted(request: Request) -> DraftedWorkflows:
    drafted: DraftedWorkflows = request.app.state.drafted
    return drafted


CurrentDrafted = Annotated[DraftedWorkflows, Depends(current_drafted)]


def _refused(answer: object) -> None:
    match answer:
        case NotFound():
            raise HTTPException(404, NO_SUCH_DRAFT)
        case Refused(words):
            raise HTTPException(409, words)
        case _:
            pass


@router.post(
    "/drafted-workflows",
    status_code=202,
    description="Starts the workflow drafter on an Operator's words, unchanged (ADR 0051). It "
    "answers at once with the drafted workflow drafting its first revision. Read it again to see "
    "the plan laid out, checked and reported. Words shaped like a key are refused, and nothing is "
    "kept or sent. The same Idempotency-Key answers the drafted workflow it started.",
    responses={
        **SIGNED_IN,
        403: error_response(DRAFT_WORKFLOWS),
        409: error_response("Don't paste keys here. An Operator adds keys in Settings."),
    },
)
async def start_drafting(
    body: DraftWorkflowIn,
    principal: Drafter,
    drafted: CurrentDrafted,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=200)
    ] = None,
) -> DraftedWorkflowView:
    answer = await drafted.start(principal, body.words, idempotency_key)
    _refused(answer)
    assert isinstance(answer, DraftedWorkflowView)
    return answer


@router.get(
    "/drafted-workflows/{drafted_id}",
    description="A drafted workflow's newest revision: its state, steps, code's report, the "
    "settings still needed, the flags, whether it can be sent for approval and why not, and its "
    "set-up approval and set-up once there are.",
    responses={**SIGNED_IN, 404: error_response(NO_SUCH_DRAFT)},
)
async def read_drafted(
    drafted_id: str, principal: CurrentPrincipal, drafted: CurrentDrafted
) -> DraftedWorkflowView:
    view = await drafted.view(drafted_id)
    if view is None:
        raise HTTPException(404, NO_SUCH_DRAFT)
    return view


@router.post(
    "/drafted-workflows/{drafted_id}/changes",
    status_code=202,
    description="A change asked for in the chat. The drafter gets the plan as it stands and these "
    "words, and its whole new plan becomes the next revision, drafting now. A setting with the "
    "same id and kind keeps its value unless the words change it. A set-up approval still waiting "
    "is replaced. 409 when the revision named is not the newest, it is still drafting, or it is "
    "set up already.",
    responses={
        **SIGNED_IN,
        403: error_response(DRAFT_WORKFLOWS),
        404: error_response(NO_SUCH_DRAFT),
    },
)
async def change_drafted(
    drafted_id: str, body: DraftChangeIn, principal: Drafter, drafted: CurrentDrafted
) -> DraftedWorkflowView:
    answer = await drafted.change(drafted_id, principal, body.revision, body.words)
    _refused(answer)
    assert isinstance(answer, DraftedWorkflowView)
    return answer


@router.post(
    "/drafted-workflows/{drafted_id}/send",
    description="Sends the newest revision for a set-up approval, to any Approver who is not a "
    "party: the person who described it, everyone who changed it, and the sender. It goes to the "
    "Teams channel with a link to the approval page. 409, with the words the card shows, while "
    "any setting is still needed, when the check found a flag, or when it changes someone's "
    "access, until those steps are built.",
    responses={
        **SIGNED_IN,
        403: error_response(DRAFT_WORKFLOWS),
        404: error_response(NO_SUCH_DRAFT),
    },
)
async def send_drafted(
    drafted_id: str, body: DraftSendIn, principal: Drafter, drafted: CurrentDrafted
) -> DraftedWorkflowView:
    answer = await drafted.send(drafted_id, principal, body.revision)
    _refused(answer)
    assert isinstance(answer, DraftedWorkflowView)
    return answer


@router.post(
    "/drafted-workflows/{drafted_id}/set-up",
    description="Tries the set-up of an approved revision again, after n8n didn't take it.",
    responses={
        **SIGNED_IN,
        403: error_response(DRAFT_WORKFLOWS),
        404: error_response(NO_SUCH_DRAFT),
    },
)
async def set_up_drafted_again(
    drafted_id: str, principal: Drafter, drafted: CurrentDrafted
) -> DraftedWorkflowView:
    answer = await drafted.set_up_again(drafted_id, principal)
    _refused(answer)
    assert isinstance(answer, DraftedWorkflowView)
    return answer


@router.get(
    "/setup-approvals/{approval_id}",
    description="A set-up approval as its page shows it: code's report of the exact revision "
    "its digest binds, and whether the signed-in person may decide it now. A party to it never "
    "may.",
    responses={**SIGNED_IN, 404: error_response(NO_SUCH_SET_UP)},
)
async def read_set_up_approval(
    approval_id: str, principal: CurrentPrincipal, drafted: CurrentDrafted
) -> SetUpApprovalView:
    view = await drafted.approval(approval_id, principal)
    if view is None:
        raise HTTPException(404, NO_SUCH_SET_UP)
    return view


@router.post(
    "/setup-approvals/{approval_id}/decisions",
    status_code=201,
    description="An Approver's yes or no to set up the revision with this digest. One Approver "
    "who is not a party decides. A decline needs a reason from the short list. Once approved, the "
    "platform sets it up as a Draft in n8n, read back and compared by digest. 200 when the same "
    "decision was recorded before.",
    responses={
        **SIGNED_IN,
        200: {"model": SetUpApprovalView, "description": "Recorded before"},
        403: error_response("This person can't decide it now, with why"),
        404: error_response(NO_SUCH_SET_UP),
        422: error_response(DECLINE_NEEDS_A_REASON),
    },
)
async def decide_set_up(
    approval_id: str,
    body: SetUpDecisionIn,
    principal: CurrentPrincipal,
    drafted: CurrentDrafted,
    response: Response,
) -> SetUpApprovalView:
    if body.verdict == "decline" and body.reason is None:
        raise HTTPException(422, DECLINE_NEEDS_A_REASON)
    if body.verdict == "approve" and body.reason is not None:
        raise HTTPException(422, APPROVE_HAS_NO_REASON)
    match await drafted.decide(approval_id, principal, body):
        case Forbidden(words=words):
            raise HTTPException(403, words)
        case NotFound():
            raise HTTPException(404, NO_SUCH_SET_UP)
        case (view, recorded_now):
            response.status_code = 201 if recorded_now else 200
            return view
