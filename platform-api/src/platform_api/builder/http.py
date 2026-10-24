from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.models import (
    BlockView,
    CreateUseCase,
    ParamSpec,
    RunStarted,
    SuggestIn,
    SuggestOut,
    TemplateList,
    TemplateView,
    UseCaseCreated,
    UseCaseList,
    UseCaseView,
)
from platform_api.builder.service import Builder, NothingToCheck
from platform_api.builder.templates import (
    TEMPLATES,
    ParamErrors,
    TemplateNotOffered,
    UnknownTemplate,
)
from platform_api.builder.views import template_view
from platform_api.shared import Principal, Role, UseCaseId
from platform_api.wire import error_response

__all__ = [
    "BlockView",
    "CreateUseCase",
    "ParamSpec",
    "RunStarted",
    "SuggestIn",
    "SuggestOut",
    "TemplateList",
    "TemplateView",
    "UseCaseCreated",
    "UseCaseList",
    "UseCaseView",
    "router",
]


def current_builder(request: Request) -> Builder:
    builder: Builder = request.app.state.builder
    return builder


CurrentBuilder = Annotated[Builder, Depends(current_builder)]


def require_operator(principal: CurrentPrincipal) -> Principal:
    if Role.OPERATOR not in principal.roles:
        raise HTTPException(
            403, "Only an Operator can build use cases or start runs. Ask an Operator on the team."
        )
    return principal


Operator = Annotated[Principal, Depends(require_operator)]

router = APIRouter(prefix="/api/v1", tags=["builder"])

NOT_FOUND = error_response("No such use case")


@router.get("/templates", responses=SIGNED_IN)
def list_templates(principal: CurrentPrincipal) -> TemplateList:
    return TemplateList(templates=[template_view(t) for t in TEMPLATES.values()])


@router.post("/use-cases", status_code=201, responses=OPERATORS_ONLY)
async def create_use_case(
    body: CreateUseCase, principal: Operator, builder: CurrentBuilder
) -> UseCaseCreated:
    match await builder.create_use_case(principal, body):
        case UseCaseCreated() as created:
            return created
        case UnknownTemplate():
            raise HTTPException(
                422,
                [{"loc": ["body", "template"], "msg": f"Unknown template {body.template!r}"}],
            )
        case TemplateNotOffered():
            raise HTTPException(
                422, [{"loc": ["body", "template"], "msg": "Add software on the Software page"}]
            )
        case ParamErrors(errors):
            raise HTTPException(
                422,
                [{"loc": ["body", "params", name], "msg": message} for name, message in errors],
            )


@router.get("/use-cases", responses=SIGNED_IN)
async def list_use_cases(principal: CurrentPrincipal, builder: CurrentBuilder) -> UseCaseList:
    return await builder.list_use_cases()


@router.post("/use-cases/suggest", responses=SIGNED_IN)
def suggest_template(
    body: SuggestIn, principal: CurrentPrincipal, builder: CurrentBuilder
) -> SuggestOut:
    return builder.suggest(body.text)


@router.get("/use-cases/{use_case_id}", responses={**SIGNED_IN, 404: NOT_FOUND})
async def get_use_case(
    use_case_id: str, principal: CurrentPrincipal, builder: CurrentBuilder
) -> UseCaseView:
    view = await builder.get_use_case(use_case_id)
    if view is None:
        raise HTTPException(404, "No such use case")
    return view


@router.post(
    "/use-cases/{use_case_id}/runs",
    status_code=201,
    responses={
        **OPERATORS_ONLY,
        200: {"model": RunStarted, "description": "This Idempotency-Key started the run before"},
        404: NOT_FOUND,
        409: error_response("The watchlist is empty, so there is nothing to check"),
    },
)
async def start_run(
    use_case_id: str,
    principal: Operator,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    builder: CurrentBuilder,
    response: Response,
) -> RunStarted:
    started = await builder.start_run(UseCaseId(use_case_id), principal, idempotency_key)
    if started is None:
        raise HTTPException(404, "No such use case")
    if isinstance(started, NothingToCheck):
        raise HTTPException(409, "The watchlist is empty. Add software before starting a check.")
    if not started.created:
        response.status_code = 200
    return RunStarted(run_id=started.run_id, events_url=f"/api/v1/runs/{started.run_id}/events")
