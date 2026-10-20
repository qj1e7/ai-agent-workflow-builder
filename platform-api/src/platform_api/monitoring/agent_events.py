"""The agent's side of the Agent API event contract, as platform-api parses it.

Agents post these to the callback URL while they run and return the full list
in their final reply. Run monitoring turns each one into an activity event with
the agent as the actor, so the `data` shapes are shared with `events.py`.
This mirrors `agent_runtime.contract`, which platform-api must not import.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from platform_api.wire import Json, WireModel


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
    result: Mapping[str, Json]


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
    """Body of the callback POST, one event per post."""

    task_id: str
    event: AgentEvent
