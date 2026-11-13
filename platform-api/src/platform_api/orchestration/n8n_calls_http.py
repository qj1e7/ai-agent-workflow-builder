"""The routes only our n8n node pack calls, with the node key from n8n's environment
(ENGINE-PLAN 2.2). A refusal answers 4xx with a plain `detail`, which the block shows in n8n. A
503 asks n8n to try the same call again."""

import hmac
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, Self

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ConfigDict, Field, model_validator

from platform_api.orchestration.cards import BODY_LIMIT, TITLE_LIMIT
from platform_api.orchestration.dispatch import resume_path
from platform_api.orchestration.n8n_call_service import FailedRun, LeftAsIs, NodeCalls
from platform_api.orchestration.n8n_calls import (
    AgentCall,
    Answer,
    AskCall,
    CallResult,
    NodeCall,
    NothingToChange,
    OptionKind,
    ProposeCall,
    ReadCall,
    Refused,
    TellCall,
    TryLater,
    Waiting,
    Work,
)
from platform_api.orchestration.tell import TellStatus, TellWhat, TellWhere, Told
from platform_api.shared import N8nExecutionId
from platform_api.wire import WireIn, WireModel, error_response

NODE_KEY_HEADER = "X-Wab-Node-Key"
INPUT_BYTES = 8 * 1024
INPUTS_BYTES = 64 * 1024
QUERY_LIMIT = 2000

NodeKey = Annotated[str | None, Header(alias=NODE_KEY_HEADER)]
Token = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Choice = Annotated[str, Field(min_length=1, max_length=200)]


def check_node_key(request: Request, node_key: NodeKey = None) -> None:
    """Runs before the body is read. With no WAB_NODE_KEY set, this platform takes no node calls
    at all."""
    expected: str | None = request.app.state.settings.node_key
    if (
        expected is None
        or node_key is None
        or not hmac.compare_digest(node_key.encode(), expected.encode())
    ):
        raise HTTPException(status_code=401, detail="Bad node key")


class _NoEcho(APIRoute):
    """A refused body is never echoed. n8n shows the refusal on the execution, where anyone who
    holds the workflow reads it, and a resume address carries n8n's signature."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def without_input(request: Request) -> Response:
            try:
                return await handle(request)
            except RequestValidationError as error:
                problems = [
                    {"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]}
                    for e in error.errors()
                ]
                return JSONResponse(status_code=422, content={"detail": problems})

        return without_input


router = APIRouter(
    prefix="/internal/v1/n8n",
    tags=["internal"],
    dependencies=[Depends(check_node_key)],
    route_class=_NoEcho,
)


def current_node_calls(request: Request) -> NodeCalls:
    return request.app.state.node_calls


CurrentNodeCalls = Annotated[NodeCalls, Depends(current_node_calls)]


class _From(WireIn):
    """The fields every block sends with its own."""

    execution_id: Token
    workflow_id: Token | None
    node_name: str = Field(min_length=1, max_length=200)
    mode: str = Field(min_length=1, max_length=40)


class ReadIn(_From):
    source: Choice
    place: Choice
    query: str | None = Field(default=None, max_length=QUERY_LIMIT)


class AgentIn(_From):
    agent: Choice
    inputs: dict[Annotated[str, Field(max_length=200)], str] = Field(max_length=50)

    @model_validator(mode="after")
    def _inputs_fit(self) -> Self:
        sizes = [len(value.encode()) for value in self.inputs.values()]
        if any(size > INPUT_BYTES for size in sizes):
            raise ValueError("An input can be at most 8 KB.")
        if sum(sizes) > INPUTS_BYTES:
            raise ValueError("The inputs can be at most 64 KB in all.")
        return self


class ProposeIn(_From):
    action: Choice
    place: Choice
    title: str = Field(min_length=1, max_length=TITLE_LIMIT)
    body: str = Field(max_length=BODY_LIMIT)
    subject: str = Field(default="", max_length=200)


class AskIn(_From):
    resume_url: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def _for_this_execution(self) -> Self:
        if resume_path(self.resume_url, N8nExecutionId(self.execution_id)) is None:
            raise ValueError("This is not n8n's resume address for this execution.")
        return self


class TellIn(_From):
    """Only the block's two choices. A body with an address or any text of its own is refused,
    so a notice goes only to the fixed recipients, with only what the run read."""

    where: TellWhere
    what: TellWhat


class TellOut(WireModel):
    status: TellStatus
    line: str = Field(description="What the block did, in the words the Portal shows.")


class FailureIn(_From):
    """Which execution failed. The block also sends what the Error Trigger said about it, and
    our API drops all of that here: it checks that the block's own execution is one of our error
    workflow, and reads the failed block and its words from n8n's own record."""

    model_config = ConfigDict(extra="ignore")

    failed_execution_id: Token | None = None


class FailureOut(WireModel):
    status: Literal["failed", "left_as_is"]
    run_id: str | None = Field(default=None, description="The run the report failed.")
    detail: str


class AskOut(WireModel):
    status: Literal["waiting", "nothing_to_change"]
    request_id: str | None = Field(
        default=None, description="Our request the execution waits for. Only while waiting."
    )


class AnswerOut(WireModel):
    items: list[dict[str, Any]] = Field(description="Each becomes one n8n item.")
    replayed: bool = Field(
        description="True when this is the answer the block already had, so nothing ran again."
    )
    cut_off: bool = Field(description="True when a Read stopped at its cap of items.")


class RetryOut(WireModel):
    retryable: Literal[True] = True
    detail: str


class OptionOut(WireModel):
    id: str
    name: str


class OptionsOut(WireModel):
    options: list[OptionOut]


REFUSALS: dict[int | str, dict[str, Any]] = {
    401: error_response("Bad node key, or this platform takes no node calls"),
    403: error_response("Refused by a safety rule, such as a start or a version that fails"),
    409: error_response("The run has stopped, or another execution carries it"),
    422: error_response("The block names something our platform does not allow"),
    503: {"model": RetryOut, "description": "Try the same call again soon"},
}


def _answered(result: CallResult) -> AnswerOut | AskOut | TellOut | JSONResponse:
    match result:
        case Answer(items, replayed, cut_off):
            return AnswerOut(
                items=[dict(item) for item in items], replayed=replayed, cut_off=cut_off
            )
        case Waiting(request_id):
            return AskOut(status="waiting", request_id=request_id)
        case NothingToChange():
            return AskOut(status="nothing_to_change")
        case Told(status, line):
            return TellOut(status=status, line=line)
        case Refused(status, detail):
            return JSONResponse(status_code=status, content={"detail": detail})
        case TryLater(detail):
            return JSONResponse(status_code=503, content=RetryOut(detail=detail).model_dump())


async def _call(calls: NodeCalls, body: _From, work: Work) -> AnswerOut | JSONResponse:
    call = NodeCall(N8nExecutionId(body.execution_id), body.node_name, work)
    answer = _answered(await calls.call(call))
    assert not isinstance(answer, AskOut | TellOut)
    return answer


@router.get(
    "/options",
    response_model=OptionsOut,
    description="The editor's lists for our blocks: names and ids from the Portal's settings, "
    "never run data.",
    responses={401: REFUSALS[401]},
)
async def options(
    calls: CurrentNodeCalls,
    kind: OptionKind,
    source: Annotated[str | None, Query(max_length=200)] = None,
    action: Annotated[str | None, Query(max_length=200)] = None,
    agent: Annotated[str | None, Query(max_length=200)] = None,
) -> OptionsOut:
    given = {"source": source, "action": action, "agent": agent}
    of = {name: value for name, value in given.items() if value is not None}
    found = await calls.options(kind, of)
    return OptionsOut(options=[OptionOut(id=option.id, name=option.name) for option in found])


@router.post(
    "/calls/read",
    response_model=AnswerOut,
    description="Reads one allowed place. The first answer is kept and given again.",
    responses=REFUSALS,
)
async def read(body: ReadIn, calls: CurrentNodeCalls) -> AnswerOut | JSONResponse:
    return await _call(calls, body, ReadCall(body.source, body.place, body.query))


@router.post(
    "/calls/agent",
    response_model=AnswerOut,
    description="Runs one of the team's agents. What it proposes joins the run's proposal.",
    responses=REFUSALS,
)
async def agent(body: AgentIn, calls: CurrentNodeCalls) -> AnswerOut | JSONResponse:
    return await _call(calls, body, AgentCall(body.agent, body.inputs))


@router.post(
    "/calls/propose",
    response_model=AnswerOut,
    description="Adds one change at an allowed place to the run's proposal. Nothing is written "
    "until an Approver says yes.",
    responses=REFUSALS,
)
async def propose(body: ProposeIn, calls: CurrentNodeCalls) -> AnswerOut | JSONResponse:
    work = ProposeCall(body.action, body.place, body.title, body.body, body.subject or None)
    return await _call(calls, body, work)


@router.post(
    "/calls/ask",
    response_model=AskOut,
    description="Asks the workflow's Approvers for a yes on the run's proposal. n8n holds the "
    "wait, and our API wakes the execution with the decision. A test run stops here.",
    responses=REFUSALS,
)
async def ask(body: AskIn, calls: CurrentNodeCalls) -> AskOut | JSONResponse:
    call = NodeCall(N8nExecutionId(body.execution_id), body.node_name, AskCall(body.resume_url))
    answer = _answered(await calls.call(call))
    assert not isinstance(answer, AnswerOut | TellOut)
    return answer


@router.post(
    "/calls/tell",
    response_model=TellOut,
    description="Tells the team what the run read, in its fixed Teams channel, by its fixed email "
    "list or both, with no yes (the Tell rule). Sent at most once, and never in a test run.",
    responses=REFUSALS,
)
async def tell(body: TellIn, calls: CurrentNodeCalls) -> TellOut | JSONResponse:
    call = NodeCall(
        N8nExecutionId(body.execution_id), body.node_name, TellCall(body.where, body.what)
    )
    answer = _answered(await calls.call(call))
    assert not isinstance(answer, AnswerOut | AskOut)
    return answer


@router.post(
    "/failures",
    response_model=FailureOut,
    description="Report a failure, from our error workflow only. When n8n's own record says the "
    "execution failed, fails the run it carries with n8n's words for the block. A run that has "
    "ended, or that another attempt carries now, stays as it is.",
    responses={
        401: REFUSALS[401],
        403: error_response("The report did not come from our error workflow"),
        409: error_response("n8n does not say this execution failed"),
        503: REFUSALS[503],
    },
)
async def failures(body: FailureIn, calls: CurrentNodeCalls) -> FailureOut | JSONResponse:
    if body.failed_execution_id is None:
        return FailureOut(status="left_as_is", detail="The report names no execution.")
    reporter = N8nExecutionId(body.execution_id)
    match await calls.report(reporter, N8nExecutionId(body.failed_execution_id)):
        case FailedRun(run_id):
            return FailureOut(status="failed", run_id=run_id, detail="The run failed.")
        case LeftAsIs(detail):
            return FailureOut(status="left_as_is", detail=detail)
        case Refused(status, detail):
            return JSONResponse(status_code=status, content={"detail": detail})
        case TryLater(detail):
            return JSONResponse(status_code=503, content=RetryOut(detail=detail).model_dump())
