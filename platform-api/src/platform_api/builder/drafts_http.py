from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response

from platform_api.auth import OPERATORS_ONLY
from platform_api.builder.drafts import TooManyDrafts
from platform_api.builder.http import CurrentBuilder, Operator
from platform_api.builder.models import DRAFT_ID_PATTERN, DraftIn, DraftList, DraftView
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])

DraftId = Annotated[
    str,
    Path(
        pattern=DRAFT_ID_PATTERN,
        description="Chosen by the Portal, such as a UUID. A draft id belongs to its author, "
        "so two people can use the same one.",
    ),
]
NO_SUCH = "No such draft"


@router.put(
    "/drafts/{draft_id}",
    description="Saves a New workflow draft for the signed-in Operator. Saving again replaces it.",
    responses={**OPERATORS_ONLY, 409: error_response("The Operator has the most drafts kept")},
)
async def save_draft(
    draft_id: DraftId, body: DraftIn, principal: Operator, builder: CurrentBuilder
) -> DraftView:
    match await builder.save_draft(principal, draft_id, body):
        case TooManyDrafts(limit):
            raise HTTPException(
                409, f"You have {limit} drafts. Delete one before you save another."
            )
        case saved:
            return saved


@router.get(
    "/drafts",
    description="The signed-in Operator's own drafts. Nobody else's are listed.",
    responses=OPERATORS_ONLY,
)
async def list_drafts(principal: Operator, builder: CurrentBuilder) -> DraftList:
    return await builder.list_drafts(principal)


@router.delete(
    "/drafts/{draft_id}",
    status_code=204,
    response_class=Response,
    responses={**OPERATORS_ONLY, 404: error_response(NO_SUCH)},
)
async def delete_draft(draft_id: DraftId, principal: Operator, builder: CurrentBuilder) -> Response:
    if not await builder.delete_draft(principal, draft_id):
        raise HTTPException(404, NO_SUCH)
    return Response(status_code=204)
