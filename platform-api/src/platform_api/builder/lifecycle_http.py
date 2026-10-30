from fastapi import APIRouter, HTTPException

from platform_api.auth import OPERATORS_ONLY
from platform_api.builder.http import CurrentBuilder, WorkflowOperator
from platform_api.builder.lifecycle import TooLate
from platform_api.builder.models import UseCaseDeleted, UseCaseView
from platform_api.builder.service import WatchlistStays
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])

NO_SUCH = "No such workflow"
NOT_FOUND = error_response("No such workflow, or it is deleted")
WATCHLIST_STAYS = "The Software watchlist can't be deleted. Remove its software instead."


@router.post(
    "/use-cases/{use_case_id}/pause",
    description="Stops the workflow starting runs, on its schedule or by hand, until an "
    "Operator resumes it. A run that has started carries on. Pausing a paused workflow "
    "changes nothing.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND},
)
async def pause_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    view = await builder.pause_use_case(use_case_id, principal)
    if view is None:
        raise HTTPException(404, NO_SUCH)
    return view


@router.post(
    "/use-cases/{use_case_id}/resume",
    description="Turns a paused workflow back on. Its next run is the next slot of its "
    "schedule. Resuming a workflow that is on changes nothing.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND},
)
async def resume_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    view = await builder.resume_use_case(use_case_id)
    if view is None:
        raise HTTPException(404, NO_SUCH)
    return view


@router.delete(
    "/use-cases/{use_case_id}",
    description="Takes the workflow out of the list and stops it running. Nothing is erased: "
    "its past runs stay readable, a run waiting for a yes can still be decided, and it can be "
    "restored for a day. Deleting it again answers the same.",
    responses={
        **OPERATORS_ONLY,
        404: error_response(NO_SUCH),
        409: error_response(WATCHLIST_STAYS),
    },
)
async def delete_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseDeleted:
    match await builder.delete_use_case(use_case_id, principal):
        case UseCaseDeleted() as deleted:
            return deleted
        case WatchlistStays():
            raise HTTPException(409, WATCHLIST_STAYS)
        case None:
            raise HTTPException(404, NO_SUCH)


@router.post(
    "/use-cases/{use_case_id}/restore",
    description="Puts a deleted workflow back as it was, paused or on, within a day of the "
    "delete. Restoring a workflow that is not deleted changes nothing.",
    responses={
        **OPERATORS_ONLY,
        404: error_response(NO_SUCH),
        410: error_response("The workflow was deleted more than a day ago"),
    },
)
async def restore_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    match await builder.restore_use_case(use_case_id):
        case TooLate():
            raise HTTPException(
                410, "This workflow was deleted more than a day ago, so it can't be put back."
            )
        case None:
            raise HTTPException(404, NO_SUCH)
        case view:
            return view
