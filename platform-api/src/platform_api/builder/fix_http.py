"""The routes a fix's coordinator in the agent runtime calls (ADR 0055, PR 5). Each needs the
fix's own token, for one fix on one stopped run. None writes to a real system, stores a version
or turns anything on: the events route writes only the fix's own events, under the activity log's
rules for a fix."""

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
    FixScenariosIn,
    FixScenariosOut,
    FixSimulationIn,
    FixSimulationOut,
    fix_token_ok,
)
from platform_api.monitoring import (
    FixData,
    FixHandedBackData,
    FixHandoffData,
    FixProposedData,
    FixRoundData,
    FixStartedData,
)
from platform_api.orchestration import NotSimulated, WorkflowPlan
from platform_api.shared import RunId
from platform_api.wire import WireIn, WireModel, error_response

router = APIRouter(prefix="/internal/v1/runs/{run_id}/fixes/{fix_id}", tags=["internal"])

type FixKind = Literal["fix_started", "fix_handoff", "fix_round", "fix_proposed", "fix_handed_back"]
FIX_DATA: dict[str, type[FixData]] = {
    "fix_started": FixStartedData,
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
    token: Annotated[str, Header(alias=FIX_TOKEN_HEADER)],
) -> None:
    if not fix_token_ok(key, run_id, fix_id, token, datetime.now(UTC)):
        raise HTTPException(status_code=401, detail="Unauthorized")


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
    "for a fix, or says why the log took none.",
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
    return FixEventOut(refused=await _here(parts).note(run_id, data))


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
