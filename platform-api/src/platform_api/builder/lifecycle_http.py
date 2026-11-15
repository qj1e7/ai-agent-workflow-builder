from typing import Annotated

from fastapi import APIRouter, Body, HTTPException

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.http import NO_SUCH, NOT_FOUND, CurrentBuilder, WorkflowOperator
from platform_api.builder.lifecycle import TooLate
from platform_api.builder.models import (
    RepublishIn,
    SweepOut,
    UndoIn,
    UseCaseDeleted,
    UseCaseScheduleIn,
    UseCaseView,
    VersionList,
)
from platform_api.builder.n8n_draft import DraftRefused, N8nNotReady, NotSafe
from platform_api.builder.n8n_holds import HeldInN8n
from platform_api.builder.service import (
    InN8nRefused,
    Republished,
    ScheduleOnSoftwarePage,
    WatchlistStays,
)
from platform_api.builder.versions import (
    ChangedSince,
    DeletedInN8n,
    InUseChanged,
    NoSuchVersion,
    NotAScheduleChange,
    NotSafeToPublish,
)
from platform_api.orchestration import ChangedInN8n
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
NO_REPUBLISH_BODY = RepublishIn()
IN_USE_CHANGED = "Another version is in use by now, so nothing changed."
DELETED_IN_N8N = "This workflow was deleted in n8n, so it can't change there."
CHANGED_IN_N8N = "Changed again since, in n8n. Nothing was saved."
N8N_NOT_READY = error_response(
    "n8n did not take the change in time, so nothing changed. Or: sign-in could not be checked "
    "because the identity provider's keys are unavailable"
)
N8N_CHANGED = error_response(CHANGED_IN_N8N)
NOT_SAFE = "This version did not pass the safety check, so it cannot be turned on."


NOT_PUT_IN_USE = "This version did not pass the safety check, so it was not put in use."


def not_safe_to_publish(findings: tuple[str, ...]) -> str:
    return " ".join((NOT_PUT_IN_USE, *findings))


def refused_in_n8n(
    refused: InN8nRefused | NotSafe | NotSafeToPublish | InUseChanged | DeletedInN8n,
) -> HTTPException:
    """Why an own workflow's change was not made, as the words the Portal shows."""
    match refused:
        case NotSafeToPublish(findings):
            return HTTPException(409, not_safe_to_publish(findings))
        case InUseChanged():
            return HTTPException(409, IN_USE_CHANGED)
        case DeletedInN8n():
            return HTTPException(409, DELETED_IN_N8N)
        case N8nNotReady(detail):
            return HTTPException(503, detail)
        case ChangedInN8n():
            return HTTPException(409, CHANGED_IN_N8N)
        case NotSafe():
            return HTTPException(409, NOT_SAFE)
        case HeldInN8n(words):
            return HTTPException(409, words)
        case DraftRefused(findings):
            return HTTPException(422, [{"loc": ["body"], "msg": f.text} for f in findings])


def _moved(found: UseCaseView | N8nNotReady | NotSafe | HeldInN8n | None) -> UseCaseView:
    match found:
        case None:
            raise HTTPException(404, NO_SUCH)
        case N8nNotReady() | NotSafe() | HeldInN8n():
            raise refused_in_n8n(found)
        case view:
            return view


@router.post(
    "/use-cases/{use_case_id}/pause",
    description="Stops the workflow starting runs, on its schedule or by hand, until an "
    "Operator resumes it. A run that has started carries on. Pausing a paused workflow, or a "
    "draft, changes nothing. A workflow n8n carries is taken off in n8n first.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND, 503: N8N_NOT_READY},
)
async def pause_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    return _moved(await builder.pause_use_case(use_case_id, principal))


@router.post(
    "/use-cases/{use_case_id}/resume",
    description="Turns a paused workflow back on. Its next run is the next slot of its "
    "schedule. Resuming a workflow that is on changes nothing, and a draft stays a draft until "
    "it is turned on. A workflow n8n carries reads on only once n8n has every trigger live.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND, 409: error_response(NOT_SAFE), 503: N8N_NOT_READY},
)
async def resume_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    return _moved(await builder.resume_use_case(use_case_id, principal))


@router.post(
    "/use-cases/{use_case_id}/turn-on",
    description="Turns a draft on, publishing its version 1 (ADR 0044). Its next run is the next "
    "slot of its schedule, and a slot that fell while it was a draft never starts. Turning on a "
    "workflow that was turned on before, even one paused since, changes nothing. Not a write to "
    "Jira or Teams, so it needs no approval. A workflow n8n carries is published in n8n, and "
    "the answer says on only once n8n has every trigger live (ENGINE-PLAN 2.5). The caller is "
    "its publisher, whose scheduled runs are their work and who can never approve them.",
    responses={**OPERATORS_ONLY, 404: NOT_FOUND, 409: error_response(NOT_SAFE), 503: N8N_NOT_READY},
)
async def turn_on_use_case(
    use_case_id: str, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    return _moved(await builder.turn_on_use_case(use_case_id, principal))


@router.delete(
    "/use-cases/{use_case_id}",
    description="Takes the workflow out of the list and stops it running. Nothing is erased: "
    "its past runs stay readable, a run waiting for a yes can still be decided, and it can be "
    "restored for a day. Deleting it again answers the same. One someone holds in n8n is taken "
    "back first, and stays theirs when n8n does not move it.",
    responses={
        **OPERATORS_ONLY,
        404: error_response(NO_SUCH),
        409: error_response(WATCHLIST_STAYS),
        503: N8N_NOT_READY,
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
        case N8nNotReady() as refused:
            raise refused_in_n8n(refused)
        case None:
            raise HTTPException(404, NO_SUCH)


@router.post(
    "/use-cases/{use_case_id}/restore",
    description="Puts a deleted workflow back as it was, paused or on, within a day of the "
    "delete. Restoring a workflow that is not deleted changes nothing.",
    responses={
        **OPERATORS_ONLY,
        404: error_response(NO_SUCH),
        409: error_response(NOT_SAFE),
        410: error_response("The workflow was deleted more than a day ago"),
        503: N8N_NOT_READY,
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
        case N8nNotReady() | NotSafe() as refused:
            raise refused_in_n8n(refused)
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
        409: error_response(f"{SCHEDULE_ON_SOFTWARE_PAGE} Or: {CHANGED_IN_N8N}"),
        503: N8N_NOT_READY,
    },
)
async def save_schedule(
    use_case_id: str, body: UseCaseScheduleIn, principal: WorkflowOperator, builder: CurrentBuilder
) -> UseCaseView:
    match await builder.save_schedule(use_case_id, principal, body):
        case ScheduleOnSoftwarePage():
            raise HTTPException(409, SCHEDULE_ON_SOFTWARE_PAGE)
        case N8nNotReady() | ChangedInN8n() | DraftRefused() | HeldInN8n() as refused:
            raise refused_in_n8n(refused)
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
        409: error_response(f"{CHANGED_SINCE} Or: {NOT_A_SCHEDULE_CHANGE} Or: {CHANGED_IN_N8N}"),
        503: N8N_NOT_READY,
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
        case N8nNotReady() | ChangedInN8n() | DraftRefused() | HeldInN8n() as refused:
            raise refused_in_n8n(refused)
        case view:
            return view


def _republished(answer: Republished | None) -> UseCaseView:
    match answer:
        case None:
            raise HTTPException(404, NO_SUCH)
        case NoSuchVersion():
            raise HTTPException(404, NO_SUCH_VERSION)
        case UseCaseView() as view:
            return view
        case refused:
            raise refused_in_n8n(refused)


REPUBLISH_REFUSED = error_response(
    f"{IN_USE_CHANGED} Or: {CHANGED_IN_N8N} Or: {NOT_PUT_IN_USE} Or: {DELETED_IN_N8N}"
)


@router.post(
    "/use-cases/{use_case_id}/versions/{version}/rollback",
    description="Puts an earlier version back in use, as a new version, so the list only grows "
    "(ENGINE-PLAN 2.5). n8n publishes the version it still holds, or, after the day n8n keeps "
    "history for, the workflow the platform kept for it, each under the version compare: "
    'anything changed in n8n since the platform last looked answers 409 with "Changed again '
    'since, in n8n." and changes nothing. Only a version that passes the safety check now is '
    "put back. A paused workflow stays paused, and the version is in use once it is resumed. "
    "The caller is its publisher, and whoever published the version it puts back joins every "
    "run of it, so neither can approve one. Rolling back again answers the same.",
    responses={
        **OPERATORS_ONLY,
        404: error_response("No such workflow, or it is deleted, or no such version"),
        409: REPUBLISH_REFUSED,
        503: N8N_NOT_READY,
    },
)
async def rollback_version(
    use_case_id: str,
    version: int,
    principal: WorkflowOperator,
    builder: CurrentBuilder,
    body: Annotated[RepublishIn, Body()] = NO_REPUBLISH_BODY,
) -> UseCaseView:
    return _republished(await builder.rollback_version(use_case_id, version, principal, body))


@router.post(
    "/use-cases/{use_case_id}/add-the-yes-back",
    description="Puts Ask for a yes back before each write that can run without one, in the "
    "version in use, and publishes that as a new version under the version compare, as a roll "
    "back does. When every write already waits for a yes, nothing changes. When the version "
    "still would not pass the safety check, nothing changes and the answer says why: undo it "
    "instead. The caller is its publisher, and whoever published the version it changes joins "
    "every run of it.",
    responses={
        **OPERATORS_ONLY,
        404: NOT_FOUND,
        409: REPUBLISH_REFUSED,
        503: N8N_NOT_READY,
    },
)
async def add_the_yes_back(
    use_case_id: str,
    principal: WorkflowOperator,
    builder: CurrentBuilder,
    body: Annotated[RepublishIn, Body()] = NO_REPUBLISH_BODY,
) -> UseCaseView:
    return _republished(await builder.add_the_yes_back(use_case_id, principal, body))


@router.post(
    "/n8n/sweep",
    description="Looks in n8n now for versions published in its editor, as the sweep does every "
    "minute: for one workflow, or for all when use_case_id is left out. The Portal asks when its "
    "tab regains focus, so a Changed in n8n card comes without the minute's wait. Each version "
    "found is graded and kept, and Home lists it. Asked again within a few seconds, it looks "
    "only once. Only Operators get the Changed in n8n card, so only they ask.",
    responses={**OPERATORS_ONLY},
)
async def sweep_versions(
    principal: WorkflowOperator, builder: CurrentBuilder, use_case_id: str | None = None
) -> SweepOut:
    return await builder.sweep_now(use_case_id)
