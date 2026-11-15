from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.http import NO_SUCH, NOT_FOUND, WorkflowOperator
from platform_api.builder.n8n_holds import Free, Held, Holding, HoldRefused
from platform_api.builder.n8n_view import InN8nViews, RunN8nView, UseCaseN8nView
from platform_api.orchestration.n8n_staff import NO_ACCESS, OFF
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


CurrentHolding = Annotated[Holding, Depends(_holding)]
CurrentViews = Annotated[InN8nViews, Depends(_views)]


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
