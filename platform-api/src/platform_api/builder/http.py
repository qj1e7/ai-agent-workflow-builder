from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header

from platform_api.auth import CurrentPrincipal
from platform_api.shared import RunId, UserId
from platform_api.wire import WireModel, not_implemented

type BlockKind = Literal["agent", "approval", "write_action"]


class BlockView(WireModel):
    key: str
    name: str
    description: str
    kind: BlockKind


class ParamSpec(WireModel):
    name: str
    description: str
    example: str


class TemplateView(WireModel):
    key: str
    name: str
    description: str
    blocks: list[BlockView]
    params: list[ParamSpec]


class TemplateList(WireModel):
    templates: list[TemplateView]


class CreateUseCase(WireModel):
    template: str
    name: str
    instruction: str
    params: dict[str, str]


class UseCaseCreated(WireModel):
    use_case_id: str
    version: int


class UseCaseView(WireModel):
    use_case_id: str
    version: int
    template: str
    name: str
    instruction: str
    params: dict[str, str]
    owner: UserId
    created_at: datetime


class UseCaseList(WireModel):
    use_cases: list[UseCaseView]


class SuggestIn(WireModel):
    text: str


class SuggestOut(WireModel):
    template: TemplateView | None
    matched_terms: list[str]


class RunStarted(WireModel):
    run_id: RunId
    state: Literal["pending"] = "pending"
    events_url: str


router = APIRouter(prefix="/api/v1", tags=["builder"])


@router.get("/templates")
def list_templates(principal: CurrentPrincipal) -> TemplateList:
    not_implemented()


@router.post("/use-cases", status_code=201)
def create_use_case(body: CreateUseCase, principal: CurrentPrincipal) -> UseCaseCreated:
    not_implemented()


@router.get("/use-cases")
def list_use_cases(principal: CurrentPrincipal) -> UseCaseList:
    not_implemented()


@router.post("/use-cases/suggest")
def suggest_template(body: SuggestIn, principal: CurrentPrincipal) -> SuggestOut:
    not_implemented()


@router.get("/use-cases/{use_case_id}")
def get_use_case(use_case_id: str, principal: CurrentPrincipal) -> UseCaseView:
    not_implemented()


@router.post("/use-cases/{use_case_id}/runs", status_code=201)
def start_run(
    use_case_id: str,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> RunStarted:
    not_implemented()
