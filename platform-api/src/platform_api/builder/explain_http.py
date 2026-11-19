from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from platform_api.auth import SIGNED_IN, CurrentPrincipal
from platform_api.builder.explain import (
    NOTHING_TO_EXPLAIN,
    Explainer,
    NoSuchWorkflow,
    NothingToExplain,
    WorkflowExplained,
)
from platform_api.builder.http import NO_SUCH
from platform_api.builder.versions import NoSuchVersion
from platform_api.wire import error_response

router = APIRouter(prefix="/api/v1", tags=["builder"])

NO_SUCH_VERSION = "No such version"


def current_explainer(request: Request) -> Explainer:
    explainer: Explainer = request.app.state.explainer
    return explainer


CurrentExplainer = Annotated[Explainer, Depends(current_explainer)]


@router.get(
    "/use-cases/{use_case_id}/explain",
    description="One version of a workflow, explained from the report code builds (ADR 0051, "
    "section 6): In short, each step, what it reads, writes and posts, every flag, who approves "
    "each write, its settings and its approval. Anyone signed in may ask. Block types come only "
    "to people with n8n access. An older version is checked again "
    "under today's rules, with the grade it had when it was published beside it. With "
    "reworded=true the AI model may smooth In short, and reworded holds its text only when it "
    "passed every check. Anything else leaves reworded null, and the answer is still 200. It "
    "writes nothing, starts nothing and asks no Approver.",
    responses={
        **SIGNED_IN,
        404: error_response("No such workflow, or it is deleted, or no such version"),
        409: error_response(NOTHING_TO_EXPLAIN),
    },
)
async def explain_workflow(
    use_case_id: str,
    principal: CurrentPrincipal,
    explainer: CurrentExplainer,
    version: Annotated[
        int | None,
        Query(
            ge=1,
            description="The version to explain, as the versions list numbers it. Leave it out "
            "for the version in use, or for a draft.",
        ),
    ] = None,
    reworded: Annotated[
        bool,
        Query(description="Ask the AI model to smooth In short, as the chat card does."),
    ] = False,
) -> WorkflowExplained:
    match await explainer.explain(use_case_id, principal, version, reworded):
        case WorkflowExplained() as explained:
            return explained
        case NoSuchWorkflow():
            raise HTTPException(404, NO_SUCH)
        case NoSuchVersion():
            raise HTTPException(404, NO_SUCH_VERSION)
        case NothingToExplain():
            raise HTTPException(409, NOTHING_TO_EXPLAIN)
