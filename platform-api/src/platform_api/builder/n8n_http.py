from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.http import NO_SUCH, NOT_FOUND, WorkflowOperator
from platform_api.builder.made_in_n8n import (
    FIX_IN_N8N,
    NOT_LOADED,
    SET_UP_ALREADY,
    MadeInN8n,
    MadeInN8nList,
    SetUpFromN8n,
)
from platform_api.builder.models import UseCaseCreated
from platform_api.builder.n8n_holds import Free, Held, Holding, HoldRefused
from platform_api.builder.n8n_view import InN8nViews, RunN8nView, UseCaseN8nView
from platform_api.orchestration import NO_ACCESS, OFF
from platform_api.shared import Principal, RunId, UserId
from platform_api.wire import WireModel, error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])


class HoldOut(WireModel):
    use_case_id: str
    workflow_id: str
    held_by: UserId | None = Field(description="Who has it open in n8n now. Null for nobody.")
    held_since: datetime | None
    editor_url: str | None = Field(
        description="The workflow in n8n's editor, for the person who just opened it."
    )


REFUSED = {
    409: error_response(f"{OFF} Or: someone else has it open in n8n, in words to show"),
    503: error_response("n8n did not do it, so nothing changed"),
}


def _holding(request: Request) -> Holding:
    holding: Holding | None = request.app.state.builder.holding
    if holding is None:
        raise HTTPException(409, OFF)
    return holding


def _views(request: Request) -> InN8nViews:
    views: InN8nViews | None = getattr(request.app.state, "in_n8n", None)
    if views is None:
        raise HTTPException(409, OFF)
    return views


def _made(request: Request) -> MadeInN8n | None:
    """None on a platform that does not lay workflows out in n8n. The route refuses, so a body
    that can't be read is still a 422 first."""
    made: MadeInN8n | None = getattr(request.app.state, "made_in_n8n", None)
    return made


CurrentHolding = Annotated[Holding, Depends(_holding)]
CurrentViews = Annotated[InN8nViews, Depends(_views)]
CurrentMade = Annotated[MadeInN8n | None, Depends(_made)]
NOT_WAITING = "No workflow made in n8n with this id waits to be set up."


def _with_access(principal: CurrentPrincipal) -> Principal:
    if not principal.n8n_access:
        raise HTTPException(403, NO_ACCESS)
    return principal


N8nViewer = Annotated[Principal, Depends(_with_access)]


@router.post(
    "/use-cases/{use_case_id}/open-in-n8n",
    description="Moves the workflow to your own n8n space and answers its address in n8n's "
    "editor (ENGINE-PLAN 2.5). Only an Operator with n8n access can, and never an Approver. "
    "While you hold it, anything you publish there is a new version, which the safety check "
    "grades, with you as its publisher, who can never approve its runs. Opening it again "
    "changes nothing. 409 while staff access to n8n is off, the allow list is unproven, or "
    "someone else holds it.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND, **REFUSED},
)
async def open_in_n8n(
    use_case_id: str, principal: WorkflowOperator, holding: CurrentHolding, views: CurrentViews
) -> HoldOut:
    match await holding.open(use_case_id, principal):
        case None:
            raise HTTPException(404, NO_SUCH)
        case HoldRefused() as refused:
            raise HTTPException(refused.status, refused.words)
        case Held(workflow_id=workflow_id, by=by, since=since):
            url = views.editor_url(workflow_id)
            return HoldOut(
                use_case_id=use_case_id,
                workflow_id=workflow_id,
                held_by=by,
                held_since=since,
                editor_url=url,
            )


@router.post(
    "/use-cases/{use_case_id}/take-back",
    description="Moves the workflow back to the platform's n8n project. The person who holds "
    "it can, and so can any Operator with n8n access, who the record then names. Taking back "
    "one nobody holds changes nothing.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND, **REFUSED},
)
async def take_back(
    use_case_id: str, principal: WorkflowOperator, holding: CurrentHolding
) -> HoldOut:
    match await holding.take_back(use_case_id, principal):
        case None:
            raise HTTPException(404, NO_SUCH)
        case HoldRefused() as refused:
            raise HTTPException(refused.status, refused.words)
        case Free(workflow_id=workflow_id):
            return HoldOut(
                use_case_id=use_case_id,
                workflow_id=workflow_id,
                held_by=None,
                held_since=None,
                editor_url=None,
            )


@router.get(
    "/use-cases/{use_case_id}/n8n",
    description="The workflow as n8n holds the version in use: its blocks and edges, who "
    "published it, who has it open in n8n, and whether you can open n8n's editor now. For "
    "people with n8n access.",
    responses={**SIGNED_IN, 403: error_response(NO_ACCESS), 404: NOT_FOUND},
)
async def use_case_in_n8n(
    use_case_id: str, principal: N8nViewer, views: CurrentViews
) -> UseCaseN8nView:
    view = await views.use_case(use_case_id, principal)
    if view is None:
        raise HTTPException(404, NO_SUCH)
    return view


@router.get(
    "/runs/{run_id}/n8n",
    description="A run as n8n carried it: the blocks and edges of the version it ran, and each "
    "block's state, from our blocks' calls and, once the run ended, n8n's own record. For "
    "people with n8n access.",
    responses={**SIGNED_IN, 403: error_response(NO_ACCESS), 404: error_response("No such run")},
)
async def run_in_n8n(run_id: RunId, principal: N8nViewer, views: CurrentViews) -> RunN8nView:
    view = await views.run(run_id)
    if view is None:
        raise HTTPException(404, "No such run")
    return view


@router.get(
    "/n8n/workflows",
    description="Every workflow made in n8n that waits to be set up (ENGINE-PLAN E15): those in "
    "the own n8n space of someone the platform made an n8n account for, and those n8n moved to "
    "the platform's project when their maker's account ended. Each names its maker, matched by "
    "the n8n account the platform made for them, and the safety checker's grade. Only for "
    "someone who can open n8n now.",
    responses={
        **SIGNED_IN,
        403: error_response(NO_ACCESS),
        409: error_response(f"{OFF} Or: n8n can't be opened now, in words to show"),
    },
)
async def made_in_n8n(principal: CurrentPrincipal, made: CurrentMade) -> MadeInN8nList:
    if made is None:
        raise HTTPException(409, OFF)
    match await made.waiting(principal):
        case HoldRefused() as refused:
            raise HTTPException(refused.status, refused.words)
        case views:
            return MadeInN8nList(workflows=views)


@router.post(
    "/use-cases/from-n8n",
    status_code=201,
    description="Sets up a workflow made in n8n as one the platform runs (ENGINE-PLAN E15, ADR "
    "0027). It moves to the platform's project first, and what n8n holds there is graded and "
    "registered, as version 1. One published in n8n is on at once, with its maker as its "
    "publisher. One that is not is set up as a draft, and only when it passes the check. Only a "
    "safe version asks for a yes and writes, and any Approver decides, never its maker or the "
    "person who set it up. Only an Operator who can open n8n now.",
    responses={
        **OPERATORS_ONLY,
        404: error_response(NOT_WAITING),
        409: error_response(
            f"{SET_UP_ALREADY} Or: {FIX_IN_N8N} Or: {NOT_LOADED} Or: {OFF} Or: n8n can't be "
            "opened now, in words to show"
        ),
        503: error_response("n8n did not move or show it, so nothing is set up"),
    },
)
async def set_up_from_n8n(
    body: SetUpFromN8n, principal: WorkflowOperator, made: CurrentMade
) -> UseCaseCreated:
    if made is None:
        raise HTTPException(409, OFF)
    match await made.set_up(body.workflow_id, principal):
        case None:
            raise HTTPException(404, NOT_WAITING)
        case HoldRefused() as refused:
            raise HTTPException(refused.status, refused.words)
        case created:
            return created
