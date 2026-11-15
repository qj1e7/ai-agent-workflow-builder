"""Confluence, read by the agents while a card run works (ENGINE-PLAN 2.7).

The agents read through our platform, never from Confluence itself, so they hold no Confluence
key. Only a running task may read: the callback token names one run and one task, as for Jira.
And only a page on the allowed list is read, named by its id or its title. The route is under
/internal/, so the Portal's proxy never serves it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import Field

from platform_api.db import Database
from platform_api.monitoring import verify_callback
from platform_api.orchestration.confluence_rest import (
    ConfluencePages,
    ConfluenceRefused,
    ConfluenceUnavailable,
)
from platform_api.orchestration.spec import CardsTask
from platform_api.orchestration.store import Store
from platform_api.settings import Settings
from platform_api.shared import RunId, TaskId
from platform_api.wire import WireModel, error_response

# A refusal is not an outage: asking again is refused the same way until someone fixes the
# connection or the page. 424 keeps it apart from 503, which an agent may retry.
REFUSED_STATUS = 424
NOT_CONNECTED = "Confluence is not connected. Ask whoever set up the platform to connect it."


class ConfluencePageOut(WireModel):
    id: str
    title: str
    version: int
    url: str = Field(description="Where people open the page.")
    text: str = Field(description="The page as plain lines, each table row on one line.")


def current_confluence(request: Request) -> ConfluencePages:
    pages: ConfluencePages = request.app.state.confluence
    return pages


router = APIRouter(prefix="/internal/v1/runs/{run_id}/confluence", tags=["internal"])
Pages = Annotated[ConfluencePages, Depends(current_confluence)]
CallbackToken = Annotated[str, Header(alias="X-Callback-Token")]


async def _admit(request: Request, run_id: RunId, task: str, token: str) -> None:
    """Checks the token, then that the run is a run of agent cards, the only runs that read."""
    settings: Settings = request.app.state.settings
    db: Database = request.app.state.db
    if not verify_callback(settings.callback_signing_key, run_id, TaskId(task), token, db.clock()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with db.transaction("orchestration") as uow:
        record = await Store().load_run(uow, run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such run")
    if not isinstance(record.spec.task, CardsTask):
        raise HTTPException(status_code=403, detail="This run does not read Confluence")


@router.get(
    "/pages/{page:path}",
    responses={
        401: error_response("The callback token is not valid for this run and task"),
        403: error_response("The run does not read Confluence, or the page is not allowed"),
        404: error_response("No such run, or Confluence has no such page"),
        REFUSED_STATUS: error_response("Confluence is not connected, or refused the read"),
        503: error_response("Confluence could not answer"),
    },
)
async def read_page(
    run_id: RunId,
    page: str,
    task: Annotated[str, Query()],
    token: CallbackToken,
    request: Request,
    pages: Pages,
) -> ConfluencePageOut:
    """One page by its id or its title, from the pages the platform may read. Anything else is
    refused before Confluence is asked."""
    await _admit(request, run_id, task, token)
    if not pages.connected:
        raise HTTPException(status_code=REFUSED_STATUS, detail=NOT_CONNECTED)
    allowed = pages.find(page)
    if allowed is None:
        raise HTTPException(status_code=403, detail="This run may not read that Confluence page")
    try:
        read = await pages.read_page(allowed)
    except ConfluenceRefused as refused:
        raise HTTPException(status_code=REFUSED_STATUS, detail=str(refused)) from refused
    except ConfluenceUnavailable as down:
        raise HTTPException(status_code=503, detail="Confluence could not answer") from down
    if read is None:
        raise HTTPException(status_code=404, detail="Confluence has no such page")
    return ConfluencePageOut(
        id=read.id,
        title=read.title,
        version=read.version,
        url=read.url,
        text=read.text,
    )
