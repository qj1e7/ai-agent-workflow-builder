import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field

from platform_api.auth import SIGNED_IN, CurrentPrincipal, PeopleDirectory
from platform_api.monitoring.agent_events import AgentEventPost
from platform_api.monitoring.callbacks import verify_callback
from platform_api.monitoring.events import ActivityEvent, RunFailedData, current_failure
from platform_api.monitoring.log import ActivityLog
from platform_api.monitoring.troubleshooter import (
    Advice,
    Answers,
    AskedCause,
    CauseFinder,
    FoundCause,
    answers,
    asks_the_model,
    explain_failure,
)
from platform_api.settings import Settings
from platform_api.shared import RunId, TaskId
from platform_api.wire import WireModel, error_response

logger = logging.getLogger(__name__)

KEEP_ALIVE_SECONDS = 15.0
PERSON_RECHECK_SECONDS = 60.0
CAUSE_WAIT_SECONDS = 10.0
"""ADR 0032: after ten seconds the troubleshooter's rule table answers alone."""


class EventPage(WireModel):
    events: list[ActivityEvent]


class TroubleshootingOut(WireModel):
    run_id: RunId
    failure: RunFailedData
    advice: Advice
    answers: Answers
    found: FoundCause | None = Field(
        default=None,
        description="The AI model's cause and failed part, only when find_cause=true asked for "
        "them, the rule table knows no cause for this stop, and code checked the answer. Null "
        "otherwise, and the rest of the answer is the rule table's either way.",
    )


def _activity_log(request: Request) -> ActivityLog:
    return request.app.state.activity_log


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _keep_alive_seconds(request: Request) -> float:
    return getattr(request.app.state, "sse_keepalive_seconds", KEEP_ALIVE_SECONDS)


def _recheck_seconds(request: Request) -> float:
    return getattr(request.app.state, "person_recheck_seconds", PERSON_RECHECK_SECONDS)


def _people(request: Request) -> PeopleDirectory:
    return request.app.state.people


def _cause_finder(request: Request) -> CauseFinder | None:
    return getattr(request.app.state, "cause_finder", None)


def _cause_wait_seconds(request: Request) -> float:
    return getattr(request.app.state, "cause_wait_seconds", CAUSE_WAIT_SECONDS)


Log = Annotated[ActivityLog, Depends(_activity_log)]
AppSettings = Annotated[Settings, Depends(_settings)]
KeepAlive = Annotated[float, Depends(_keep_alive_seconds)]
Recheck = Annotated[float, Depends(_recheck_seconds)]
Directory = Annotated[PeopleDirectory, Depends(_people)]
Finder = Annotated[CauseFinder | None, Depends(_cause_finder)]
CauseWait = Annotated[float, Depends(_cause_wait_seconds)]

router = APIRouter()


@router.get(
    "/api/v1/runs/{run_id}/events",
    tags=["monitoring"],
    description=(
        "With `Accept: text/event-stream` this is the live stream. Each frame is "
        "`id: <seq>`, `event: activity`, `data: <ActivityEvent>`. The server replays from "
        "the event after `Last-Event-ID` and then waits for new ones. Every minute it checks "
        "the person is still on the People list, and closes the stream when they are not. "
        "Otherwise it returns the events after `after` as one JSON page."
    ),
    response_model=EventPage,
    responses={
        **SIGNED_IN,
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string", "description": "SSE frames of ActivityEvent"}
                }
            }
        },
    },
)
async def run_events(
    run_id: RunId,
    principal: CurrentPrincipal,
    log: Log,
    keep_alive: KeepAlive,
    recheck: Recheck,
    people: Directory,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    accept: Annotated[str, Header()] = "application/json",
) -> EventPage | StreamingResponse:
    if "text/event-stream" not in accept:
        return EventPage(events=await log.read_after(run_id, after))
    start = int(last_event_id) if last_event_id is not None and last_event_id.isdigit() else after

    async def still_listed() -> bool:
        return await people.person(principal.user_id) is not None

    return StreamingResponse(
        _frames(log, run_id, start, keep_alive, still_listed, recheck),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _frames(
    log: ActivityLog,
    run_id: RunId,
    after: int,
    keep_alive: float,
    still_listed: Callable[[], Awaitable[bool]],
    recheck: float,
) -> AsyncIterator[str]:
    """Pumps the subscription through a queue so the keep-alive timeout cancels a queue read,
    never the subscription itself. The stream ends once the person is no longer on the list."""
    queue: asyncio.Queue[ActivityEvent | Exception] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for event in log.subscribe(run_id, after):
                await queue.put(event)
        except Exception as error:
            await queue.put(error)

    task = asyncio.create_task(pump())
    next_check = time.monotonic() + recheck
    try:
        while True:
            if time.monotonic() >= next_check:
                if not await still_listed():
                    return
                next_check = time.monotonic() + recheck
            try:
                item = await asyncio.wait_for(
                    queue.get(), min(keep_alive, max(next_check - time.monotonic(), 0.0))
                )
            except TimeoutError:
                if time.monotonic() < next_check:
                    yield ": keep-alive\n\n"
                continue
            if isinstance(item, Exception):
                raise item
            yield f"id: {item.seq}\nevent: activity\ndata: {item.model_dump_json()}\n\n"
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@router.get(
    "/api/v1/runs/{run_id}/troubleshoot",
    tags=["monitoring"],
    description=(
        "Why the run stopped and what to do, from the rule table. With find_cause=true, a stop "
        "the rule table knows no cause for also asks the AI model for the cause and the failed "
        "part (ADR 0055, section 10), and found holds them only when code checked them. Any "
        "doubt, a failed or slow call, or no model connected leaves found null. It only "
        "explains: it writes nothing and never changes a run."
    ),
    responses={
        **SIGNED_IN,
        404: error_response("No such run"),
        409: error_response("The run has not failed, or it was retried since"),
    },
)
async def troubleshoot(
    run_id: RunId,
    principal: CurrentPrincipal,
    log: Log,
    settings: AppSettings,
    finder: Finder,
    wait: CauseWait,
    find_cause: Annotated[
        bool, Query(description="Ask the AI model for the cause and the failed part.")
    ] = False,
) -> TroubleshootingOut:
    events = await log.read_after(run_id, 0)
    if not events:
        raise HTTPException(status_code=404, detail="No such run")
    failure = current_failure(events)
    if failure is None:
        raise HTTPException(status_code=409, detail="The run has not failed")
    found = None
    if find_cause and finder is not None and asks_the_model(failure.data):
        summaries = [e.summary for e in events]
        found = await _found(finder, AskedCause(run_id, failure.seq, failure.data, summaries, wait))
    return TroubleshootingOut(
        run_id=run_id,
        failure=failure.data,
        advice=explain_failure(failure.data),
        answers=answers(failure.data, failure.ts.astimezone(settings.team_time_zone)),
        found=found,
    )


async def _found(finder: CauseFinder, asked: AskedCause) -> FoundCause | None:
    """The model's checked cause, or None, so the rule table answers alone whatever goes wrong:
    the finder failing, or taking longer than the wait."""
    try:
        async with asyncio.timeout(asked.seconds):
            return await finder.find(asked)
    except Exception as error:
        logger.warning("The troubleshooter's rule table answered alone: %s", type(error).__name__)
        return None


@router.post(
    "/internal/v1/runs/{run_id}/agent-events",
    status_code=202,
    tags=["internal"],
    response_class=Response,
    responses={401: error_response("The callback token is not valid for this run and task")},
)
async def ingest_agent_event(
    run_id: RunId,
    body: AgentEventPost,
    task: Annotated[str, Query()],
    callback_token: Annotated[str, Header(alias="X-Callback-Token")],
    log: Log,
    settings: AppSettings,
) -> None:
    task_id = TaskId(task)
    now = log.database.clock()
    if body.task_id != task or not verify_callback(
        settings.callback_signing_key, run_id, task_id, callback_token, now
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with log.database.transaction("monitoring") as uow:
        await log.ingest_agent_events(uow, run_id, task_id, [body.event])
