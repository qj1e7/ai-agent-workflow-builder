from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.http import SET_UP_OR_RUN, operators_only
from platform_api.builder.planner import (
    AnswerIn,
    CapabilitiesView,
    CheckPartIn,
    NoSuchWorkflow,
    PartChecked,
    PlannerFront,
    PlannerReply,
    RegistryUnavailable,
)
from platform_api.shared import Principal
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])

Operator = Annotated[Principal, Depends(operators_only(SET_UP_OR_RUN))]
NOT_ANSWERING = "The agent runtime did not answer. Try again in a minute."


def current_front(request: Request) -> PlannerFront:
    front: PlannerFront = request.app.state.planner_front
    return front


CurrentFront = Annotated[PlannerFront, Depends(current_front)]


@router.post(
    "/planner/answer",
    description="The Planner's one answer to what a person types or taps on Home. A typed "
    "request is read by the AI model and answered as a set-up card, a part, a can't, a "
    "watchlist row, a question about software, a refusal, or one of the question kinds the "
    "Portal fills from its own routes. An intent chip never asks the model. Without a model, "
    "or after 10 seconds, or when the answer cannot be used, it answers `offline` with the "
    "starter workflows. Someone who isn't an Operator asks questions only (ADR 0043): they "
    "get the question kinds, `decided` for their own decisions and `decide` for an approve or "
    "decline, which goes to the request. Anything else answers `operators`, and a change "
    "beside a question is a part marked `operators`. Nothing is saved or written.",
    responses={**SIGNED_IN, 404: error_response("No such workflow")},
)
async def answer(body: AnswerIn, principal: CurrentPrincipal, front: CurrentFront) -> PlannerReply:
    match await front.answer(body, principal):
        case NoSuchWorkflow():
            raise HTTPException(404, "No such workflow")
        case reply:
            return reply


@router.post(
    "/planner/check-part",
    description="Checks one part the person changed, by code only, through the agent runtime's "
    "abilities check. No AI model is asked.",
    responses={**OPERATORS_ONLY, 503: error_response(NOT_ANSWERING)},
)
async def check_part(body: CheckPartIn, principal: Operator, front: CurrentFront) -> PartChecked:
    match await front.check_part(body):
        case RegistryUnavailable():
            raise HTTPException(503, NOT_ANSWERING)
        case checked:
            return checked


@router.get(
    "/capabilities",
    description="What the platform can do, from the agent runtime's registry. Each capability "
    "has a state that code works out from the registry and the connections it uses, so no "
    "screen decides it for itself, and the agents that use it. The last good registry is "
    "served while the runtime is waking up.",
    responses={**SIGNED_IN, 503: error_response(NOT_ANSWERING)},
)
async def capabilities(principal: CurrentPrincipal, front: CurrentFront) -> CapabilitiesView:
    match await front.capabilities():
        case RegistryUnavailable():
            raise HTTPException(503, NOT_ANSWERING)
        case view:
            return view
