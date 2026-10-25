"""The practice Jira, read by the agents while a card run works (ADR 0023).

Only a running task may read it: the callback token names one run and one task, and the agent
runtime holds it for that task alone. The routes are under /internal/, so the Portal's proxy
never serves them.
"""

import re
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from platform_api.monitoring import verify_callback
from platform_api.orchestration.cards import JIRA_PROJECT_PATTERN, read_projects
from platform_api.orchestration.http import current_mock_jira
from platform_api.orchestration.spec import CardsTask
from platform_api.orchestration.write_actions import MockJiraConnector, MockTicket, TicketStatus
from platform_api.settings import Settings
from platform_api.shared import RunId, TaskId
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


def _summary(ticket: MockTicket) -> PracticeTicketSummary:
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


router = APIRouter(prefix="/internal/v1/runs/{run_id}/practice-jira", tags=["internal"])
Jira = Annotated[MockJiraConnector, Depends(current_mock_jira)]
CallbackToken = Annotated[str, Header(alias="X-Callback-Token")]
UNAUTHORIZED = error_response("The callback token is not valid for this run and task")
FORBIDDEN = error_response("The run does not read Jira, or the project is not one of its cards'")
NO_RUN = error_response("No such run, or no such ticket")


async def _admit(
    request: Request, jira: MockJiraConnector, run_id: RunId, task: str, token: str
) -> frozenset[str]:
    """Checks the token, then answers the Jira projects this run may read. Only a run of agent
    cards may read at all, and only the projects on its cards."""
    settings: Settings = request.app.state.settings
    if not verify_callback(settings.callback_signing_key, run_id, TaskId(task), token, jira.now()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    spec = await jira.run_spec(run_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="No such run")
    if not isinstance(spec.task, CardsTask):
        raise HTTPException(status_code=403, detail="This run does not read Jira")
    return read_projects(spec.task)


@router.get("/tickets", responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NO_RUN})
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
    allowed = await _admit(request, jira, run_id, task, token)
    if project and JIRA_PROJECT_PATTERN.match(project) is None:
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
    found = await jira.search(
        [project] if project else sorted(allowed),
        words,
        wanted[status],
        since,
    )
    return PracticeTickets(tickets=[_summary(t) for t in found])


@router.get("/tickets/{key}", responses={401: UNAUTHORIZED, 403: FORBIDDEN, 404: NO_RUN})
async def read_ticket(
    run_id: RunId,
    key: str,
    task: Annotated[str, Query()],
    token: CallbackToken,
    request: Request,
    jira: Jira,
) -> PracticeTicket:
    allowed = await _admit(request, jira, run_id, task, token)
    ticket = await jira.find(key)
    if ticket is None or ticket.project not in allowed:
        raise HTTPException(status_code=404, detail="No such ticket")
    return PracticeTicket(**_summary(ticket).model_dump(), body=ticket.body)
