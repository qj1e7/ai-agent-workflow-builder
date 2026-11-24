"""The routes a fix's coordinator in the agent runtime calls (ADR 0055, PR 5 and PR 6). Each needs
the fix's own token, for one fix on one stopped run, and a call without one answers 401. None
writes to a real system or turns anything on. The events route writes only the fix's own events,
under the activity log's rules for a fix, and never its start: platform-api writes that itself,
with who asked from their session. The revisions route stores the fixed version under the fix's
id, which waits for a yes only once the fix's proposal names it."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, JsonValue, ValidationError

from platform_api.builder.fix_parts import (
    FIX_TOKEN_HEADER,
    FixCheckOut,
    FixId,
    FixParts,
    FixRevisionIn,
    FixRevisionOut,
    FixScenariosIn,
    FixScenariosOut,
    FixSimulationIn,
    FixSimulationOut,
    fix_token_ok,
)
from platform_api.builder.fixes import Fixes, NotStored
from platform_api.monitoring import (
    FixData,
    FixHandedBackData,
    FixHandoffData,
    FixProposedData,
    FixRoundData,
)
from platform_api.orchestration import NotSimulated, WorkflowPlan
from platform_api.shared import RunId
from platform_api.wire import WireIn, WireModel, error_response

router = APIRouter(prefix="/internal/v1/runs/{run_id}/fixes/{fix_id}", tags=["internal"])

type FixKind = Literal["fix_handoff", "fix_round", "fix_proposed", "fix_handed_back"]
FIX_DATA: dict[str, type[FixData]] = {
    "fix_handoff": FixHandoffData,
    "fix_round": FixRoundData,
    "fix_proposed": FixProposedData,
    "fix_handed_back": FixHandedBackData,
}
NOT_THIS_FIX = "The event is another fix's."


def _parts(request: Request) -> FixParts | None:
    return getattr(request.app.state, "fix_parts", None)


def _key(request: Request) -> str:
    return str(request.app.state.settings.callback_signing_key)


Parts = Annotated[FixParts | None, Depends(_parts)]
NOT_SET_UP = "Fixes aren't set up here."


def _here(parts: FixParts | None) -> FixParts:
    """The fix's parts, once the request is valid and authorized. An app the wiring never set
    up answers 503."""
    if parts is None:
        raise HTTPException(status_code=503, detail=NOT_SET_UP)
    return parts


async def _authorized(
    run_id: RunId,
    fix_id: FixId,
    key: Annotated[str, Depends(_key)],
    token: Annotated[str | None, Header(alias=FIX_TOKEN_HEADER)] = None,
) -> None:
    if token is None or not fix_token_ok(key, run_id, fix_id, token, datetime.now(UTC)):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _fixes(request: Request) -> Fixes | None:
    return getattr(request.app.state, "fixes", None)


AllFixes = Annotated[Fixes | None, Depends(_fixes)]


Authorized = Annotated[None, Depends(_authorized)]
REFUSED: dict[int | str, dict[str, Any]] = {
    401: error_response("The fix's token is not valid for this run and fix")
}


class FixEventIn(WireIn):
    kind: FixKind
    data: dict[str, JsonValue]


class FixEventOut(WireModel):
    refused: str | None = Field(description="Why the log took no event, or null when it did.")


class FixCheckIn(WireIn):
    version: WorkflowPlan


def _not_simulated(not_simulated: NotSimulated) -> JSONResponse:
    status = 503 if not_simulated.again else 422
    return JSONResponse(status_code=status, content={"detail": not_simulated.words})


@router.post(
    "/events",
    response_model=FixEventOut,
    description="Writes one event of the fix on the stopped run, under the activity log's rules "
    "for a fix, or says why the log took none. Never the fix's start, which platform-api writes "
    "itself. A proposal must name the version stored under the fix, and once the log takes it, "
    "the version waits for a set-up approval.",
    responses={**REFUSED, 422: error_response(NOT_THIS_FIX)},
)
async def note_fix_event(
    run_id: RunId, fix_id: FixId, body: FixEventIn, _: Authorized, parts: Parts
) -> FixEventOut:
    try:
        data = FIX_DATA[body.kind].model_validate(body.data)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=[e["msg"] for e in error.errors()]) from None
    if data.fix_id != fix_id:
        raise HTTPException(status_code=422, detail=NOT_THIS_FIX)
    try:
        return FixEventOut(refused=await _here(parts).note(run_id, data))
    except NotStored as not_stored:
        raise HTTPException(status_code=422, detail=not_stored.words) from None


@router.post(
    "/revisions",
    response_model=FixRevisionOut,
    description="Stores the fixed version under the fix's id, once: asking again with the same "
    "version answers the same. Only while the fix runs, with no setting changed, the failed "
    "part where the run stopped, the checker's pass, and a simulation here that every scenario "
    "passed. It waits for an Approver only once the fix's proposal names it.",
    responses={
        **REFUSED,
        409: error_response("The fix ended, or nothing here proved the version"),
        422: error_response("A fix can't change a setting."),
        503: error_response(NOT_SET_UP),
    },
)
async def store_fix(
    run_id: RunId, fix_id: FixId, body: FixRevisionIn, _: Authorized, fixes: AllFixes
) -> FixRevisionOut:
    if fixes is None:
        raise HTTPException(status_code=503, detail=NOT_SET_UP)
    try:
        return await fixes.store(run_id, fix_id, body.version, body.cause)
    except NotStored as refused:
        raise HTTPException(status_code=refused.status, detail=refused.words) from None


@router.post(
    "/scenarios",
    response_model=FixScenariosOut,
    description="Scenarios for the stopped version: code's template for each kind that applies, "
    "or the Scenario writer's when Simulation mode's model is on and the fix can pay for it.",
    responses={
        **REFUSED,
        422: error_response("The version can't be simulated"),
        503: error_response("The practice systems didn't answer"),
    },
)
async def fix_scenarios(
    fix_id: FixId, body: FixScenariosIn, _: Authorized, parts: Parts
) -> FixScenariosOut | JSONResponse:
    written = await _here(parts).scenarios(fix_id, body)
    return _not_simulated(written) if isinstance(written, NotSimulated) else written


@router.post(
    "/simulations",
    response_model=FixSimulationOut,
    description="Runs a plan in the scenarios given on practice systems, and grades each run, "
    "with what it reached. The explainer picks why each failed only when its model is on and the "
    "fix can pay for it.",
    responses={
        **REFUSED,
        422: error_response("The version or a scenario can't be simulated"),
        503: error_response("The practice systems didn't answer"),
    },
)
async def fix_simulation(
    fix_id: FixId, body: FixSimulationIn, _: Authorized, parts: Parts
) -> FixSimulationOut | JSONResponse:
    done = await _here(parts).simulate(fix_id, body)
    return _not_simulated(done) if isinstance(done, NotSimulated) else done


@router.post(
    "/checks",
    response_model=FixCheckOut,
    description="The checker's grade of a plan, laid out as any drafted plan is.",
    responses=REFUSED,
)
async def fix_check(fix_id: FixId, body: FixCheckIn, _: Authorized, parts: Parts) -> FixCheckOut:
    return await _here(parts).check(fix_id, body.version)
