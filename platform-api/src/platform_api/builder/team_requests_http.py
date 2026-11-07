from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from platform_api.auth import SIGNED_IN, CurrentPrincipal
from platform_api.builder.team_requests import (
    CreateTeamRequest,
    NoSuchRun,
    ReplyIn,
    TeamRequestList,
    TeamRequests,
    TeamRequestView,
)
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])


def current_team_requests(request: Request) -> TeamRequests:
    kept: TeamRequests = request.app.state.team_requests
    return kept


CurrentTeamRequests = Annotated[TeamRequests, Depends(current_team_requests)]


@router.post(
    "/team-requests",
    status_code=201,
    description=(
        "Keeps a request for the team: Ask the team, or Report to support. Any Operator or "
        "Approver can send one. It is kept in our own database and posts a card to the team's "
        "Teams channel when one is set up. It writes nothing to Jira or any outside system. "
        "`posted_to_teams` says whether the card went."
    ),
    responses={
        **SIGNED_IN,
        200: {"model": TeamRequestView, "description": "This Idempotency-Key made the request"},
        422: error_response("The request is not valid, or the run it is about does not exist"),
    },
)
async def create_team_request(
    body: CreateTeamRequest,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    kept: CurrentTeamRequests,
    response: Response,
) -> TeamRequestView:
    match await kept.create(principal, idempotency_key, body):
        case NoSuchRun(run_id):
            problem = {
                "type": "no_such_run",
                "loc": ["body", "about", "run_id"],
                "msg": f"There is no run {run_id}",
            }
            raise HTTPException(422, [problem])
        case created:
            if not created.new:
                response.status_code = 200
            return created.request


@router.get(
    "/team-requests",
    description=(
        "Every request for the team, the newest first. Any Operator or Approver can read them. "
        "A request marked Done leaves the list after 30 days."
    ),
    responses=SIGNED_IN,
)
async def list_team_requests(
    principal: CurrentPrincipal, kept: CurrentTeamRequests
) -> TeamRequestList:
    return await kept.list()


@router.post(
    "/team-requests/{request_id}/replies",
    status_code=201,
    description=(
        "Replies to a request and sets its status. Any Operator or Approver can reply. A reply "
        "changes no workflow, writes nothing outside the app and approves nothing."
    ),
    responses={**SIGNED_IN, 404: error_response("No such request")},
)
async def reply_to_team_request(
    request_id: str, body: ReplyIn, principal: CurrentPrincipal, kept: CurrentTeamRequests
) -> TeamRequestView:
    replied = await kept.reply(principal, request_id, body)
    if replied is None:
        raise HTTPException(404, "No such request")
    return replied
