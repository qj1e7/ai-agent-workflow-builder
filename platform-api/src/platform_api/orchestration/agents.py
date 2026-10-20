"""platform-api's own parse models for the Agent API.

The event shapes come from run monitoring, which ingests them. The task
shapes are here because orchestration is the only caller of `POST /v1/tasks`.
"""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from platform_api.monitoring import AgentEvent
from platform_api.wire import Json, WireModel


class ReleaseCheckInputs(WireModel):
    repo: str
    tag_pattern: str


class CarryForward(WireModel):
    last_known_tag: str | None = None


class TaskRequest(WireModel):
    task_id: str
    run_id: str
    instruction: str
    inputs: ReleaseCheckInputs
    carry_forward: CarryForward
    callback_url: str


class ProposedIntentIn(WireModel):
    kind: str
    fields: Mapping[str, Json]
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
