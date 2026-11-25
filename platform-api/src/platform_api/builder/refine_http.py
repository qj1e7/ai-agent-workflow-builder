"""The routes a refinement's coordinator in the agent runtime calls (ADR 0054, section 7, PR 8).
Each needs the refinement's own token, for one refinement of one drafted workflow's Check, and a
call without one answers 401. A fix's token never opens them. The Scenario writer, the
simulation and the checker are a fix's own parts. The events route keeps the refinement's events
by the drafted workflow, never on a run, and never its start, which platform-api kept itself. The
revisions route keeps the refined plan as the drafted workflow's next revision, which goes
through the normal Check. None writes to a real system or turns anything on."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, JsonValue, ValidationError

from platform_api.builder.fix_http import FIX_DATA, NOT_SET_UP, NOT_THIS_FIX, FixCheckIn
from platform_api.builder.fix_parts import (
    FIX_TOKEN_HEADER,
    FixCheckOut,
    FixId,
    FixParts,
    FixRevisionOut,
    FixScenariosIn,
    FixScenariosOut,
    FixSimulationIn,
    FixSimulationOut,
    refine_token_ok,
)
from platform_api.builder.fixes import NotStored
from platform_api.builder.refinements import Refinements
from platform_api.orchestration import CauseFound, NotSimulated, WorkflowPlan
from platform_api.wire import WireIn, WireModel, error_response

router = APIRouter(
    prefix="/internal/v1/drafted/{drafted_id}/refinements/{fix_id}", tags=["internal"]
)

type RefineKind = Literal["fix_handoff", "fix_round", "fix_proposed", "fix_handed_back"]
type DraftedId = Annotated[str, Field(pattern=r"^dw_[0-9A-Za-z]{1,40}$")]


def _key(request: Request) -> str:
    return str(request.app.state.settings.callback_signing_key)


async def _authorized(
    drafted_id: DraftedId,
    fix_id: FixId,
    key: Annotated[str, Depends(_key)],
    token: Annotated[str | None, Header(alias=FIX_TOKEN_HEADER)] = None,
) -> None:
    if token is None or not refine_token_ok(key, drafted_id, fix_id, token, datetime.now(UTC)):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _parts(request: Request) -> FixParts | None:
    return getattr(request.app.state, "refine_parts", None)


def _refinements(request: Request) -> Refinements | None:
    return getattr(request.app.state, "refinements", None)


def _here[T](part: T | None) -> T:
    """The part, once the request is valid and authorized. An app the wiring never set up
    answers 503."""
    if part is None:
        raise HTTPException(status_code=503, detail=NOT_SET_UP)
    return part


Authorized = Annotated[None, Depends(_authorized)]
Parts = Annotated[FixParts | None, Depends(_parts)]
AllRefinements = Annotated[Refinements | None, Depends(_refinements)]
REFUSED: dict[int | str, dict[str, Any]] = {
    401: error_response("The token is not valid for this drafted workflow and refinement"),
    503: error_response(NOT_SET_UP),
}


class RefineEventIn(WireIn):
    kind: RefineKind
    data: dict[str, JsonValue]


class RefineEventOut(WireModel):
    refused: str | None = Field(description="Why no event was kept, or null when it was.")


class RefineRevisionIn(WireIn):
    version: WorkflowPlan = Field(description="The refined draft, which code accepted.")
    cause: CauseFound | None = Field(
        description="The blocks where a case failed on the draft as checked, or null when none "
        "failed and the draft comes back unchanged."
    )


def _not_simulated(not_simulated: NotSimulated) -> JSONResponse:
    status = 503 if not_simulated.again else 422
    return JSONResponse(status_code=status, content={"detail": not_simulated.words})


@router.post(
    "/events",
    response_model=RefineEventOut,
    description="Keeps one event of the refinement by its drafted workflow, under the rules a "
    "fix's events keep on a run, or says why none was kept. Never its start. A proposal must "
    "name the revision the refinement kept.",
    responses={**REFUSED, 422: error_response(NOT_THIS_FIX)},
)
async def note_refine_event(
    drafted_id: DraftedId,
    fix_id: FixId,
    body: RefineEventIn,
    _: Authorized,
    refinements: AllRefinements,
) -> RefineEventOut:
    try:
        data = FIX_DATA[body.kind].model_validate(body.data)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=[e["msg"] for e in error.errors()]) from None
    if data.fix_id != fix_id:
        raise HTTPException(status_code=422, detail=NOT_THIS_FIX)
    try:
        return RefineEventOut(refused=await _here(refinements).note(drafted_id, fix_id, data))
    except NotStored as not_stored:
        raise HTTPException(status_code=422, detail=not_stored.words) from None


@router.post(
    "/revisions",
    response_model=FixRevisionOut,
    description="Keeps the refined draft as the drafted workflow's next revision, once: asking "
    "again with the same plan answers the same. Only while the refinement runs, with no setting "
    "changed, the change inside the blocks where a case failed, a simulation here that every "
    "case passed, and the safety checker's grade of safe. A draft that comes back unchanged keeps "
    "nothing new. The revision goes through the normal Check.",
    responses={
        **REFUSED,
        409: error_response("The refinement ended, or nothing here proved the draft"),
        422: error_response("A refinement can't change a setting."),
    },
)
async def keep_refined(
    drafted_id: DraftedId,
    fix_id: FixId,
    body: RefineRevisionIn,
    _: Authorized,
    refinements: AllRefinements,
) -> FixRevisionOut:
    try:
        return await _here(refinements).store(drafted_id, fix_id, body.version, body.cause)
    except NotStored as refused:
        raise HTTPException(status_code=refused.status, detail=refused.words) from None


@router.post(
    "/scenarios",
    response_model=FixScenariosOut,
    description="Scenarios for the draft: code's template for each kind that applies, or the "
    "Scenario writer's, also aimed at blocks no scenario reached, when Simulation mode's model "
    "is on and the refinement can pay for it.",
    responses={
        **REFUSED,
        422: error_response("The draft can't be simulated"),
    },
)
async def refine_scenarios(
    fix_id: FixId, body: FixScenariosIn, _: Authorized, parts: Parts
) -> FixScenariosOut | JSONResponse:
    written = await _here(parts).scenarios(fix_id, body)
    return _not_simulated(written) if isinstance(written, NotSimulated) else written


@router.post(
    "/simulations",
    response_model=FixSimulationOut,
    description="Runs a plan in the scenarios given on practice systems, and grades each run, "
    "with what it reached.",
    responses={
        **REFUSED,
        422: error_response("The draft or a scenario can't be simulated"),
    },
)
async def refine_simulation(
    fix_id: FixId, body: FixSimulationIn, _: Authorized, parts: Parts
) -> FixSimulationOut | JSONResponse:
    done = await _here(parts).simulate(fix_id, body)
    return _not_simulated(done) if isinstance(done, NotSimulated) else done


@router.post(
    "/checks",
    response_model=FixCheckOut,
    description="The safety checker's grade of a plan, laid out as any drafted plan is.",
    responses=REFUSED,
)
async def refine_check(fix_id: FixId, body: FixCheckIn, _: Authorized, parts: Parts) -> FixCheckOut:
    return await _here(parts).check(fix_id, body.version)
