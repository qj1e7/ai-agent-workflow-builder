from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter

from platform_api.monitoring import AgentEvent
from platform_api.wire import WireModel


class ReleaseCheckInputs(WireModel):
    repo: str
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
