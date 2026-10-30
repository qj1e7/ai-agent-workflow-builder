from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.card_store import NoSuchCard, StarterCard
from platform_api.builder.models import (
    BlockView,
    CardChecked,
    CardDefinition,
    CardList,
    CardRefused,
    CardView,
    CreateAgentUseCase,
    CreateUseCase,
    ParamSpec,
    PlanIn,
    PlanOut,
    RunStarted,
    SuggestIn,
    SuggestOut,
    TemplateList,
    TemplateView,
    ToolList,
    UnderstandIn,
    UnderstandOut,
    UseCaseCreated,
    UseCaseList,
    UseCaseView,
)
from platform_api.builder.planning import NoModelConnected, RuntimeNotAnswering
from platform_api.builder.service import (
    AgentUseCaseRefused,
    Builder,
    CardsRefused,
    NoModelToRun,
    NothingToCheck,
    UseCasePaused,
)
from platform_api.builder.templates import (
    AGENT_CARDS,
    SOFTWARE_WATCHLIST,
    TEMPLATES,
)
from platform_api.builder.views import template_view
from platform_api.shared import Principal, Role, UseCaseId
from platform_api.wire import error_response

__all__ = [
    "BlockView",
    "CardChecked",
    "CardDefinition",
    "CardList",
    "CardRefused",
    "CardView",
    "CreateAgentUseCase",
    "CreateUseCase",
    "ParamSpec",
    "PlanIn",
    "PlanOut",
    "RunStarted",
    "SuggestIn",
    "SuggestOut",
    "TemplateList",
    "TemplateView",
    "ToolList",
    "UseCaseCreated",
    "UseCaseList",
    "UseCaseView",
    "router",
]


def current_builder(request: Request) -> Builder:
    builder: Builder = request.app.state.builder
    return builder


CurrentBuilder = Annotated[Builder, Depends(current_builder)]


def operators_only(refusal: str) -> Callable[[Principal], Principal]:
    def require_operator(principal: CurrentPrincipal) -> Principal:
        if Role.OPERATOR not in principal.roles:
            raise HTTPException(403, refusal)
        return principal

    return require_operator


SET_UP_OR_RUN = "Only an Operator can set up workflows or start runs. Ask an Operator on the team."
CHANGE_WORKFLOWS = "Only an Operator can change workflows."

Operator = Annotated[Principal, Depends(operators_only(SET_UP_OR_RUN))]
WorkflowOperator = Annotated[Principal, Depends(operators_only(CHANGE_WORKFLOWS))]

router = APIRouter(prefix="/api/v1", tags=["builder"])

NOT_FOUND = error_response("No such use case")
NO_MODEL = "Connect an AI model in Settings first."
NO_MODEL_TO_RUN = "Connect an AI model in Settings to run agents."
NOT_OFFERED = {
    SOFTWARE_WATCHLIST.key: "Add software on the Software page",
    AGENT_CARDS.key: "Describe the task on the Builder page",
}
CARD_NOT_FOUND = error_response("No such agent")


@router.get("/templates", responses=SIGNED_IN)
def list_templates(principal: CurrentPrincipal) -> TemplateList:
    return TemplateList(templates=[template_view(t) for t in TEMPLATES.values()])


@router.post("/use-cases", status_code=201, responses=OPERATORS_ONLY)
async def create_use_case(
    body: CreateUseCase, principal: Operator, builder: CurrentBuilder
) -> UseCaseCreated:
    template = TEMPLATES.get(body.template)
    if template is None:
        raise HTTPException(
            422, [{"loc": ["body", "template"], "msg": f"Unknown template {body.template!r}"}]
        )
    raise HTTPException(
        422, [{"loc": ["body", "template"], "msg": NOT_OFFERED.get(template.key, "Not offered")}]
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
        409: error_response(
            "The watchlist is empty, so there is nothing to check, an agent use case has no "
            "AI model connected, or the workflow is paused"
        ),
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
    if isinstance(started, NoModelToRun):
        raise HTTPException(409, NO_MODEL_TO_RUN)
    if isinstance(started, UseCasePaused):
        raise HTTPException(409, "This workflow is paused. Resume it to start a run.")
    if not started.created:
        response.status_code = 200
    return RunStarted(run_id=started.run_id, events_url=f"/api/v1/runs/{started.run_id}/events")


@router.get("/tools", responses=SIGNED_IN)
def list_tools(principal: CurrentPrincipal, builder: CurrentBuilder) -> ToolList:
    return builder.tools()


@router.get("/agent-cards", responses=SIGNED_IN)
async def list_agent_cards(principal: CurrentPrincipal, builder: CurrentBuilder) -> CardList:
    return await builder.list_cards()


@router.post(
    "/agent-cards/check",
    description="Checks a card without saving it, for the editor to call as the Operator types.",
    responses=SIGNED_IN,
)
def check_agent_card(
    body: CardDefinition, principal: CurrentPrincipal, builder: CurrentBuilder
) -> CardChecked:
    return builder.check_card(body)


@router.get("/agent-cards/{card_id}", responses={**SIGNED_IN, 404: CARD_NOT_FOUND})
async def get_agent_card(
    card_id: str, principal: CurrentPrincipal, builder: CurrentBuilder
) -> CardView:
    card = await builder.get_card(card_id)
    if card is None:
        raise HTTPException(404, "No such agent")
    return card


@router.post(
    "/agent-cards",
    status_code=201,
    response_model=CardView,
    responses={
        **OPERATORS_ONLY,
        422: {"model": CardRefused, "description": "The card has problems, so it was not saved"},
    },
)
async def create_agent_card(
    body: CardDefinition, principal: Operator, builder: CurrentBuilder
) -> CardView | JSONResponse:
    match await builder.create_card(principal, body):
        case CardView() as card:
            return card
        case CardsRefused(refused):
            return JSONResponse(status_code=422, content=refused.model_dump(mode="json"))


@router.put(
    "/agent-cards/{card_id}",
    response_model=CardView,
    description="Saves the next version of a card. Use cases made before keep the version they "
    "were made with.",
    responses={
        **OPERATORS_ONLY,
        404: CARD_NOT_FOUND,
        409: error_response("Starter agents cannot be changed. Copy it instead."),
        422: {"model": CardRefused, "description": "The card has problems, so it was not saved"},
    },
)
async def update_agent_card(
    card_id: str, body: CardDefinition, principal: Operator, builder: CurrentBuilder
) -> CardView | JSONResponse:
    match await builder.update_card(principal, card_id, body):
        case CardView() as card:
            return card
        case CardsRefused(refused):
            return JSONResponse(status_code=422, content=refused.model_dump(mode="json"))
        case NoSuchCard():
            raise HTTPException(404, "No such agent")
        case StarterCard():
            raise HTTPException(409, "Starter agents cannot be changed. Copy it instead.")


@router.post(
    "/builder/plan",
    description="The Planner reads the task and picks saved agents, or drafts a new one. "
    "Nothing is saved.",
    responses={
        **OPERATORS_ONLY,
        409: error_response(NO_MODEL),
        503: error_response("The agent runtime did not answer"),
    },
)
async def plan_task(body: PlanIn, principal: Operator, builder: CurrentBuilder) -> PlanOut:
    planned = await builder.plan(body.task)
    match planned:
        case NoModelConnected():
            raise HTTPException(409, NO_MODEL)
        case RuntimeNotAnswering():
            raise HTTPException(503, "The agent runtime did not answer. Try again in a minute.")
        case _:
            return planned


@router.post(
    "/builder/understand",
    description="The Planner reads the task back in parts, each understood, changed, missing or "
    "can't do, or says it belongs on the Software watchlist. Without an AI model, or after 10 "
    "seconds, it answers the starter workflows. Nothing is saved or written.",
    responses=OPERATORS_ONLY,
)
async def understand_task(
    body: UnderstandIn, principal: Operator, builder: CurrentBuilder
) -> UnderstandOut:
    return await builder.understand(body.text)


@router.post(
    "/agent-use-cases",
    status_code=201,
    responses=OPERATORS_ONLY,
)
async def create_agent_use_case(
    body: CreateAgentUseCase, principal: Operator, builder: CurrentBuilder
) -> UseCaseCreated:
    match await builder.create_agent_use_case(principal, body):
        case UseCaseCreated() as created:
            return created
        case AgentUseCaseRefused(errors):
            raise HTTPException(
                422, [{"loc": list(where), "msg": message} for where, message in errors]
            )
