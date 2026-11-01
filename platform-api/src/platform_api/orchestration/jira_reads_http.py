"""Jira, read by the agents while a card run works (ADR 0023, ADR 0035).

The agents read through our platform, never from Jira itself, so they hold no Jira key. Only a
running task may read: the callback token names one run and one task, and the agent runtime holds
it for that task alone. The routes are under /internal/, so the Portal's proxy never serves them.
"""

import re
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from platform_api.db import Database
from platform_api.monitoring import verify_callback
from platform_api.orchestration.cards import read_projects
from platform_api.orchestration.jira import (
    IssueSearch,
    JiraError,
    JiraIssue,
    JiraPort,
    TicketStatus,
)
from platform_api.orchestration.spec import CardsTask
from platform_api.orchestration.store import Store
from platform_api.settings import Settings
from platform_api.shared import (
    STORED_JIRA_KEY_PATTERN,
    STORED_JIRA_PROJECT_PATTERN,
    RunId,
    TaskId,
)
from platform_api.wire import WireModel, error_response

MIN_WORD = 3
_WORD = re.compile(r"[A-Za-z0-9]{3,}")


class PracticeTicketSummary(WireModel):
    key: str
    project: str
    title: str
    status: TicketStatus
    created_at: datetime
    done_at: datetime | None


class PracticeTicket(PracticeTicketSummary):
    body: str


class PracticeTickets(WireModel):
    tickets: list[PracticeTicketSummary]


def _summary(ticket: JiraIssue) -> PracticeTicketSummary:
    return PracticeTicketSummary(
        key=ticket.key,
        project=ticket.project,
        title=ticket.title,
        status=ticket.status,
        created_at=ticket.created_at,
        done_at=ticket.done_at,
    )


def _words(text: str) -> list[str]:
    """The words a search matches on: letters and digits, at least 3 of them, each once."""
    return list(dict.fromkeys(word.lower() for word in _WORD.findall(text)))


def current_jira(request: Request) -> JiraPort:
    jira: JiraPort = request.app.state.jira
    return jira


router = APIRouter(prefix="/internal/v1/runs/{run_id}/jira", tags=["internal"])
Jira = Annotated[JiraPort, Depends(current_jira)]
CallbackToken = Annotated[str, Header(alias="X-Callback-Token")]
UNAUTHORIZED = error_response("The callback token is not valid for this run and task")
FORBIDDEN = error_response("The run does not read Jira, or the project is not one of its cards'")
NO_RUN = error_response("No such run, or no such ticket")
JIRA_DOWN = error_response("Jira could not answer")


async def _admit(request: Request, run_id: RunId, task: str, token: str) -> frozenset[str]:
    """Checks the token, then answers the Jira projects this run may read. Only a run of agent
    cards may read at all, and only the projects on its cards."""
    settings: Settings = request.app.state.settings
    db: Database = request.app.state.db
    if not verify_callback(settings.callback_signing_key, run_id, TaskId(task), token, db.clock()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with db.transaction("orchestration") as uow:
        record = await Store().load_run(uow, run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such run")
    spec = record.spec
    if not isinstance(spec.task, CardsTask):
        raise HTTPException(status_code=403, detail="This run does not read Jira")
    return read_projects(spec.task)


@router.get("/tickets", responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NO_RUN, 503: JIRA_DOWN})
async def search_tickets(
    run_id: RunId,
    task: Annotated[str, Query()],
    token: CallbackToken,
    request: Request,
    jira: Jira,
    project: str = "",
    text: str = "",
    status: str = "",
    done_since: str = "",
) -> PracticeTickets:
    """At most 50 tickets, newest first. An empty filter is not applied. Words of `text` shorter
    than 3 characters are ignored, and text with no word left matches nothing."""
    allowed = await _admit(request, run_id, task, token)
    if project and STORED_JIRA_PROJECT_PATTERN.match(project) is None:
        raise HTTPException(422, "project is not a Jira project key")
    wanted: dict[str, TicketStatus | None] = {"": None, "To Do": "To Do", "Done": "Done"}
    if status not in wanted:
        raise HTTPException(422, "status is To Do or Done")
    since: datetime | None = None
    if done_since:
        try:
            since = datetime.combine(date.fromisoformat(done_since), datetime.min.time(), UTC)
        except ValueError:
            raise HTTPException(422, "done_since is a day, YYYY-MM-DD") from None
    if project and project not in allowed:
        raise HTTPException(403, "This run may not read that Jira project")
    words = _words(text)
    if text.strip() and not words:
        return PracticeTickets(tickets=[])
    query = IssueSearch(
        tuple([project] if project else sorted(allowed)), tuple(words), wanted[status], since
    )
    try:
        found = await jira.search(query)
    except JiraError as error:
        raise HTTPException(status_code=503, detail="Jira could not answer") from error
    return PracticeTickets(tickets=[_summary(t) for t in found if t.project in allowed])


@router.get(
    "/tickets/{key}", responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NO_RUN, 503: JIRA_DOWN}
)
async def read_ticket(
    run_id: RunId,
    key: str,
    task: Annotated[str, Query()],
    token: CallbackToken,
    request: Request,
    jira: Jira,
) -> PracticeTicket:
    allowed = await _admit(request, run_id, task, token)
    if STORED_JIRA_KEY_PATTERN.match(key) is None or key.rsplit("-", 1)[0] not in allowed:
        raise HTTPException(status_code=404, detail="No such ticket")
    try:
        ticket = await jira.get_issue(key)
    except JiraError as error:
        raise HTTPException(status_code=503, detail="Jira could not answer") from error
    if ticket is None or ticket.project not in allowed:
        raise HTTPException(status_code=404, detail="No such ticket")
    return PracticeTicket(**_summary(ticket).model_dump(), body=ticket.body)
