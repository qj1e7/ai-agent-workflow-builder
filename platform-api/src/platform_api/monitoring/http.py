from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from platform_api.auth import CurrentPrincipal
from platform_api.monitoring.agent_events import AgentEventPost
from platform_api.monitoring.events import ActivityEvent, RunFailedData
from platform_api.monitoring.troubleshooter import Advice
from platform_api.shared import RunId
from platform_api.wire import WireModel, not_implemented


class EventPage(WireModel):
    events: list[ActivityEvent]


class TroubleshootingOut(WireModel):
    run_id: RunId
    failure: RunFailedData
    advice: Advice


router = APIRouter()


@router.get(
    "/api/v1/runs/{run_id}/events",
    tags=["monitoring"],
    description=(
        "With `Accept: text/event-stream` this is the live stream. Each frame is "
        "`id: <seq>`, `event: activity`, `data: <ActivityEvent>`. The server replays from "
        "the event after `Last-Event-ID` and then waits for new ones. "
        "Otherwise it returns the events after `after` as one JSON page."
    ),
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string", "description": "SSE frames of ActivityEvent"}
                }
            }
        }
    },
)
def run_events(
    run_id: RunId,
    principal: CurrentPrincipal,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    accept: Annotated[str, Header()] = "application/json",
) -> EventPage:
    not_implemented()


@router.get("/api/v1/runs/{run_id}/troubleshoot", tags=["monitoring"])
def troubleshoot(run_id: RunId, principal: CurrentPrincipal) -> TroubleshootingOut:
    not_implemented()


@router.post(
    "/internal/v1/runs/{run_id}/agent-events",
    status_code=202,
    tags=["internal"],
    response_class=Response,
)
def ingest_agent_event(
    run_id: RunId,
    body: AgentEventPost,
    task: Annotated[str, Query()],
    sig: Annotated[str, Query()],
) -> None:
    not_implemented()
