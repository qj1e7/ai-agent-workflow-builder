from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol

import httpx
from pydantic import Field, TypeAdapter

from platform_api.monitoring import AgentEvent
from platform_api.wire import RepoName, WireModel


class ReleaseCheckInputs(WireModel):
    repo: RepoName
    tag_pattern: str


class CarryForward(WireModel):
    last_known_tag: str | None = None


class Callback(WireModel):
    url: str = Field(
        description="Where the agent posts each event. It names only the run and the task."
    )
    token: str = Field(
        description="Sent back as the X-Callback-Token header, never in the URL. The handler "
        "must compare it in constant time, bind it to this run_id and task_id, and give it "
        "an expiry."
    )


class TaskRequest(WireModel):
    task_id: str
    run_id: str
    instruction: str
    inputs: ReleaseCheckInputs
    carry_forward: CarryForward
    callback: Callback


class ProposedIntentIn(WireModel):
    kind: str
    fields: dict[str, Any]
    reason: str


class TaskOutput(WireModel):
    summary: str
    new_tags: list[str]
    proposed: list[ProposedIntentIn]
    carry_forward: CarryForward


class TaskError(WireModel):
    type: str
    message: str
    retryable: bool


class TaskFinished(WireModel):
    task_id: str
    status: Literal["finished"] = "finished"
    output: TaskOutput
    events: list[AgentEvent]


class TaskFailed(WireModel):
    task_id: str
    status: Literal["failed"] = "failed"
    error: TaskError
    events: list[AgentEvent]


type TaskResult = Annotated[TaskFinished | TaskFailed, Field(discriminator="status")]

task_result_adapter: TypeAdapter[TaskResult] = TypeAdapter(TaskResult)


class AgentCard(WireModel):
    id: str
    display: str
    description: str
    capabilities: list[str]


class AgentCards(WireModel):
    agents: list[AgentCard]


@dataclass(frozen=True)
class AgentUnavailable:
    detail: str


@dataclass(frozen=True)
class AgentRejected:
    detail: str


type AgentReply = TaskFinished | TaskFailed | AgentUnavailable | AgentRejected


class AgentRuntime(Protocol):
    async def run_task(self, request: TaskRequest) -> AgentReply: ...


AGENT_KEY_HEADER = "X-Agent-Key"
AGENT_TIMEOUT_SECONDS = 60.0


class HttpAgentRuntime:
    def __init__(self, base_url: str, api_key: str, client: httpx.AsyncClient | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=AGENT_TIMEOUT_SECONDS)

    async def run_task(self, request: TaskRequest) -> AgentReply:
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/tasks",
                json=request.model_dump(mode="json"),
                headers={AGENT_KEY_HEADER: self._api_key},
                timeout=AGENT_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            return AgentUnavailable(f"The agent runtime did not answer: {error!r}")
        if response.status_code >= 500:
            return AgentUnavailable(f"The agent runtime answered {response.status_code}")
        if response.status_code >= 400:
            return AgentRejected(
                f"The agent runtime refused the task ({response.status_code}): "
                f"{response.text[:200]}"
            )
        try:
            return task_result_adapter.validate_json(response.content)
        except ValueError as error:
            return AgentRejected(f"The agent runtime's reply did not parse: {error}")

    async def close(self) -> None:
        await self._client.aclose()
