from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from platform_api.auth import CurrentPrincipal
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
from platform_api.builder.service import Builder
from platform_api.builder.templates import TEMPLATES, ParamErrors, UnknownTemplate
from platform_api.builder.views import template_view
from platform_api.shared import UseCaseId

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

router = APIRouter(prefix="/api/v1", tags=["builder"])

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No such use case"}}


@router.get("/templates")
def list_templates(principal: CurrentPrincipal) -> TemplateList:
    return TemplateList(templates=[template_view(t) for t in TEMPLATES.values()])


@router.post("/use-cases", status_code=201)
async def create_use_case(
    body: CreateUseCase, principal: CurrentPrincipal, builder: CurrentBuilder
) -> UseCaseCreated:
    match await builder.create_use_case(principal, body):
        case UseCaseCreated() as created:
            return created
        case UnknownTemplate():
            raise HTTPException(
                422,
                [{"loc": ["body", "template"], "msg": f"Unknown template {body.template!r}"}],
            )
        case ParamErrors(errors):
            raise HTTPException(
                422,
                [{"loc": ["body", "params", name], "msg": message} for name, message in errors],
            )


@router.get("/use-cases")
async def list_use_cases(principal: CurrentPrincipal, builder: CurrentBuilder) -> UseCaseList:
    return await builder.list_use_cases()


@router.post("/use-cases/suggest")
def suggest_template(
    body: SuggestIn, principal: CurrentPrincipal, builder: CurrentBuilder
) -> SuggestOut:
    return builder.suggest(body.text)


@router.get("/use-cases/{use_case_id}", responses=NOT_FOUND)
async def get_use_case(
    use_case_id: str, principal: CurrentPrincipal, builder: CurrentBuilder
) -> UseCaseView:
    view = await builder.get_use_case(use_case_id)
    if view is None:
        raise HTTPException(404, "No such use case")
    return view


@router.post("/use-cases/{use_case_id}/runs", status_code=201, responses=NOT_FOUND)
async def start_run(
    use_case_id: str,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    builder: CurrentBuilder,
    response: Response,
) -> RunStarted:
    started = await builder.start_run(UseCaseId(use_case_id), principal, idempotency_key)
    if started is None:
        raise HTTPException(404, "No such use case")
    if not started.created:
        response.status_code = 200
    return RunStarted(run_id=started.run_id, events_url=f"/api/v1/runs/{started.run_id}/events")
