from fastapi import APIRouter, HTTPException

from platform_api.auth import OPERATORS_ONLY
from platform_api.builder.http import NO_SUCH, NOT_FOUND, CurrentBuilder, WorkflowOperator
from platform_api.builder.lifecycle import TooLate
from platform_api.builder.models import ScheduleIn, UseCaseDeleted, UseCaseView
from platform_api.builder.service import ScheduleOnSoftwarePage, WatchlistStays
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])

SCHEDULE_ON_SOFTWARE_PAGE = "The Software watchlist's schedule is saved on the Software page."
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


@router.put(
    "/use-cases/{use_case_id}/schedule",
    description="Saves when the workflow runs on its own, in Singapore time. The caller "
    "becomes the schedule owner, whose scheduled runs start as them and who can never approve "
    "them. That lifts a hold, so an Operator takes over a workflow whose owner can no longer "
    "run it by saving its schedule. A paused workflow stays paused. Saving is not a write to "
    "Jira or Confluence, so it needs no approval.",
    responses={
        **OPERATORS_ONLY,
        404: NOT_FOUND,
        409: error_response(SCHEDULE_ON_SOFTWARE_PAGE),
    },
)
async def save_schedule(
    use_case_id: str, body: ScheduleIn, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    match await builder.save_schedule(use_case_id, principal, body):
        case ScheduleOnSoftwarePage():
            raise HTTPException(409, SCHEDULE_ON_SOFTWARE_PAGE)
        case None:
            raise HTTPException(404, NO_SUCH)
        case view:
            return view
