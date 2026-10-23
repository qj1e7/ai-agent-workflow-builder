from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from agent_runtime.contract import (
    AgentEvent,
    AgentFailedData,
    AgentJoinedData,
    AgentMessageData,
    AgentRef,
    AgentStepFinishedData,
    AgentStepStartedData,
    agent_event_adapter,
)

type Clock = Callable[[], datetime]
type EventSink = Callable[[AgentEvent], None]
type EventData = (
    AgentJoinedData
    | AgentStepStartedData
    | AgentStepFinishedData
    | AgentFailedData
    | AgentMessageData
)

_KIND: dict[type[EventData], str] = {
    AgentJoinedData: "agent_joined",
    AgentStepStartedData: "agent_step_started",
    AgentStepFinishedData: "agent_step_finished",
    AgentFailedData: "agent_failed",
    AgentMessageData: "agent_message",
}


@dataclass(frozen=True)
class Draft:
    agent: AgentRef
    summary: str
    data: EventData


class EventLog:
    def __init__(self, clock: Clock, sink: EventSink) -> None:
        self._clock = clock
        self._sink = sink
        self.events: list[AgentEvent] = []

    def add(self, draft: Draft) -> None:
        event = agent_event_adapter.validate_python(
            {
                "kind": _KIND[type(draft.data)],
                "agent_seq": len(self.events) + 1,
                "ts": self._clock(),
                "agent": draft.agent,
                "summary": draft.summary,
                "data": draft.data,
            }
        )
        self.events.append(event)
        self._sink(event)
