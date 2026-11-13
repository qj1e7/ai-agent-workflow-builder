from typing import Annotated

from fastapi import APIRouter, Body, HTTPException

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.http import NO_SUCH, NOT_FOUND, CurrentBuilder, WorkflowOperator
from platform_api.builder.lifecycle import TooLate
from platform_api.builder.models import (
    UndoIn,
    UseCaseDeleted,
    UseCaseScheduleIn,
    UseCaseView,
    VersionList,
)
from platform_api.builder.service import ScheduleOnSoftwarePage, WatchlistStays
from platform_api.builder.versions import ChangedSince, NoSuchVersion, NotAScheduleChange
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])

SCHEDULE_ON_SOFTWARE_PAGE = "The Software watchlist's schedule is saved on the Software page."
WATCHLIST_STAYS = "The Software watchlist can't be deleted. Remove its software instead."
NO_SUCH_VERSION = "No such version"
CHANGED_SINCE = (
    "The workflow changed again since this version, so Undo would throw that change away."
)
NOT_A_SCHEDULE_CHANGE = "Only a change of when the workflow runs can be undone."
NO_UNDO_BODY = UndoIn()


@router.post(
    "/use-cases/{use_case_id}/pause",
    description="Stops the workflow starting runs, on its schedule or by hand, until an "
    "Operator resumes it. A run that has started carries on. Pausing a paused workflow, or a "
    "draft, changes nothing.",
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
    "schedule. Resuming a workflow that is on changes nothing, and a draft stays a draft until "
    "it is turned on.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND},
)
async def resume_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    view = await builder.resume_use_case(use_case_id, principal)
    if view is None:
        raise HTTPException(404, NO_SUCH)
    return view


@router.post(
    "/use-cases/{use_case_id}/turn-on",
    description="Turns a draft on, publishing its version 1 (ADR 0044). Its next run is the next "
    "slot of its schedule, and a slot that fell while it was a draft never starts. Turning on a "
    "workflow that was turned on before, even one paused since, changes nothing. Not a write to "
    "Jira or Teams, so it needs no approval.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND},
)
async def turn_on_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    view = await builder.turn_on_use_case(use_case_id, principal)
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
    match await builder.restore_use_case(use_case_id, principal):
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
    "run it by saving its schedule. A new schedule publishes a new version of the workflow, "
    "which the answer names. Saving the same schedule again publishes none. A paused workflow "
    "stays paused. Saving is not a write to Jira or Confluence, so it needs no approval.",
    responses={
        **OPERATORS_ONLY,
        404: NOT_FOUND,
        409: error_response(SCHEDULE_ON_SOFTWARE_PAGE),
    },
)
async def save_schedule(
    use_case_id: str, body: UseCaseScheduleIn, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    match await builder.save_schedule(use_case_id, principal, body):
        case ScheduleOnSoftwarePage():
            raise HTTPException(409, SCHEDULE_ON_SOFTWARE_PAGE)
        case None:
            raise HTTPException(404, NO_SUCH)
        case view:
            return view


@router.get(
    "/use-cases/{use_case_id}/versions",
    description="Every published version of the workflow, newest first, with when, who and what "
    "changed. Changing when it runs, or undoing that, publishes a version.",
    responses={**SIGNED_IN, 404: NOT_FOUND},
)
async def list_versions(
    use_case_id: str, principal: CurrentPrincipal, builder: CurrentBuilder
) -> VersionList:
    versions = await builder.list_versions(use_case_id)
    if versions is None:
        raise HTTPException(404, NO_SUCH)
    return versions


@router.post(
    "/use-cases/{use_case_id}/versions/{version}/undo",
    description="Undoes a change of when the workflow runs: publishes the schedule from before "
    "it again, as a new version, and makes the caller the schedule owner, as a save does. Only "
    "the newest version can be undone, so Undo never throws away a later change. Undoing it "
    "again answers the same. Not a write to Jira or Confluence, so it needs no approval.",
    responses={
        **OPERATORS_ONLY,
        404: error_response("No such workflow, or it is deleted, or no such version"),
        409: error_response(f"{CHANGED_SINCE} Or: {NOT_A_SCHEDULE_CHANGE}"),
    },
)
async def undo_version(
    use_case_id: str,
    version: int,
    principal: WorkflowOperator,
    builder: CurrentBuilder,
    body: Annotated[UndoIn, Body()] = NO_UNDO_BODY,
) -> UseCaseView:
    match await builder.undo_version(use_case_id, version, principal, body):
        case None:
            raise HTTPException(404, NO_SUCH)
        case NoSuchVersion():
            raise HTTPException(404, NO_SUCH_VERSION)
        case ChangedSince():
            raise HTTPException(409, CHANGED_SINCE)
        case NotAScheduleChange():
            raise HTTPException(409, NOT_A_SCHEDULE_CHANGE)
        case view:
            return view
