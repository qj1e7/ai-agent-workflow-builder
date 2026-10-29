import json

import httpx
import pytest

from platform_api.orchestration.agents import (
    AgentRejected,
    AgentUnavailable,
    Connected,
    ConnectRequest,
    HttpAgentRuntime,
    ModelAccess,
    ModelTestPassed,
)

pytestmark = pytest.mark.anyio

KEY = "sk-example-key-not-real-x7"
ACCESS = ModelAccess(
    style="anthropic", base_url="https://llm-gateway.aisg.sg", model="claude-haiku-5-5", api_key=KEY
)


def runtime(status: int, body: object, seen: list[httpx.Request]) -> HttpAgentRuntime:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return HttpAgentRuntime("http://agent-runtime:8100", "agent-key-not-real", client=client)


async def test_connect_posts_the_address_and_key_with_the_agent_key():
    seen: list[httpx.Request] = []
    answer = {
        "status": "connected",
        "style": "openai",
        "base_url": "https://x.example/v1",
        "models": [],
    }
    result = await runtime(200, answer, seen).connect_model(
        ConnectRequest(base_url="https://x.example", api_key=KEY)
    )
    assert isinstance(result, Connected)
    assert seen[0].url.path == "/v1/models/connect"
    assert seen[0].headers["X-Agent-Key"] == "agent-key-not-real"
    assert json.loads(seen[0].content) == {"base_url": "https://x.example", "api_key": KEY}


async def test_test_returns_the_runtimes_answer():
    seen: list[httpx.Request] = []
    answer = {"status": "passed", "seconds": 1.4, "text": "Two new releases came out."}
    result = await runtime(200, answer, seen).test_model(ACCESS)
    assert result == ModelTestPassed(seconds=1.4, text="Two new releases came out.")
    assert seen[0].url.path == "/v1/models/test"


async def test_a_refusal_that_echoes_the_key_does_not_keep_its_text():
    seen: list[httpx.Request] = []
    echo = {"detail": [{"msg": "bad", "input": {"api_key": KEY}}]}
    result = await runtime(422, echo, seen).test_model(ACCESS)
    assert isinstance(result, AgentRejected)
    assert KEY not in result.detail


async def test_a_runtime_that_is_down_is_unavailable():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(down))
    agents = HttpAgentRuntime("http://agent-runtime:8100", "agent-key-not-real", client=client)
    assert isinstance(
        await agents.connect_model(ConnectRequest(base_url="https://x", api_key=KEY)),
        AgentUnavailable,
    )
    assert isinstance(await runtime(503, {}, []).test_model(ACCESS), AgentUnavailable)


async def test_choose_and_draft_post_with_the_agent_key_and_read_either_answer():
    from platform_api.orchestration.agents import (
        ChooseRequest,
        Chosen,
        Drafted,
        DraftRequest,
        ModelProblem,
    )

    seen: list[httpx.Request] = []
    chosen = {"status": "chosen", "choice": {"decision": "cannot_do", "reason": "No."}}
    result = await runtime(200, chosen, seen).choose(
        ChooseRequest(task="book a room", library=[], model=ACCESS)
    )
    assert isinstance(result, Chosen)
    assert seen[0].url.path == "/v1/planner/choose"
    assert seen[0].headers["X-Agent-Key"] == "agent-key-not-real"

    drafted = {"status": "drafted", "draft": {"can_do": False, "name": "", "purpose": ""}}
    result = await runtime(200, drafted, seen).draft(DraftRequest(task="x", model=ACCESS))
    assert isinstance(result, Drafted) and seen[1].url.path == "/v1/cards/draft"

    problem = {"status": "problem", "reason": "too_slow", "message": "slow"}
    result = await runtime(200, problem, seen).draft(DraftRequest(task="x", model=ACCESS))
    assert isinstance(result, ModelProblem)


async def test_a_refused_draft_does_not_keep_the_key():
    from platform_api.orchestration.agents import DraftRequest

    seen: list[httpx.Request] = []
    echo = {"detail": [{"input": {"api_key": KEY}}]}
    result = await runtime(422, echo, seen).draft(DraftRequest(task="x", model=ACCESS))
    assert isinstance(result, AgentRejected) and KEY not in result.detail
    assert isinstance(
        await runtime(503, {}, seen).draft(DraftRequest(task="x", model=ACCESS)), AgentUnavailable
    )
