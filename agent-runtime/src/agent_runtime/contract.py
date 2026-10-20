"""Agent API wire contract, the agent hub contract.

An agent takes a task, posts events to the callback it was given, and
returns proposed writes as data. It knows nothing about runs, n8n, Jira or
approvals. platform-api parses these shapes with its own models and never
imports this package.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentRef(WireModel):
    id: str
    display: str


class AgentAddressee(WireModel):
    kind: Literal["agent"] = "agent"
    id: str
    display: str


class RoomAddressee(WireModel):
    kind: Literal["room"] = "room"


type Addressee = Annotated[AgentAddressee | RoomAddressee, Field(discriminator="kind")]


class AgentJoinedData(WireModel):
    agent: AgentRef
    reason: str


class AgentStepStartedData(WireModel):
    step: str


class AgentStepFinishedData(WireModel):
    step: str
    result: dict[str, Any]


class AgentFailedData(WireModel):
    step: str | None
    error_type: str
    message: str
    retryable: bool


class AgentMessageData(WireModel):
    speaker: AgentRef
    addressee: Addressee
    text: str


class _AgentEnvelope(WireModel):
    agent_seq: int = Field(ge=1)
    ts: datetime
    agent: AgentRef
    summary: str


class AgentJoinedEvent(_AgentEnvelope):
    kind: Literal["agent_joined"] = "agent_joined"
    data: AgentJoinedData


class AgentStepStartedEvent(_AgentEnvelope):
    kind: Literal["agent_step_started"] = "agent_step_started"
    data: AgentStepStartedData


class AgentStepFinishedEvent(_AgentEnvelope):
    kind: Literal["agent_step_finished"] = "agent_step_finished"
    data: AgentStepFinishedData


class AgentFailedEvent(_AgentEnvelope):
    kind: Literal["agent_failed"] = "agent_failed"
    data: AgentFailedData


class AgentMessageEvent(_AgentEnvelope):
    kind: Literal["agent_message"] = "agent_message"
    data: AgentMessageData


type AgentEvent = Annotated[
    AgentJoinedEvent
    | AgentStepStartedEvent
    | AgentStepFinishedEvent
    | AgentFailedEvent
    | AgentMessageEvent,
    Field(discriminator="kind"),
]

agent_event_adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


class AgentEventPost(WireModel):
    task_id: str
    event: AgentEvent


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


class ProposedIntent(WireModel):
    kind: str
    fields: dict[str, Any]
    reason: str


class TaskOutput(WireModel):
    summary: str
    new_tags: list[str]
    proposed: list[ProposedIntent]
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


class Health(WireModel):
    status: Literal["ok"] = "ok"


class AgentApi(WireModel):
    """Every shape that crosses the Agent API, for the one schema document."""

    task_request: TaskRequest
    task_result: TaskResult
    callback: AgentEventPost
    agent_cards: AgentCards
