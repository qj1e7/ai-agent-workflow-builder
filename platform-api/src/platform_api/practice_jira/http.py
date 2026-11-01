"""The practice Jira's routes (ADR 0035).

Under /practice-jira it answers the part of Jira's REST API the platform uses, as Data Center
(/rest/api/2) and as Cloud (/rest/api/3), so the one Jira adapter calls it exactly as it calls a
real Jira. Those routes are Jira's API, not ours, so they stay out of our OpenAPI document.

Under /api/v1/mock-jira are its own pages for the Portal: the list of tickets, and Mark done,
which a person does in Jira's own screens.
"""

import base64
import binascii
import hmac
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.jira_format import from_adf, from_wiki, json_list, json_object, to_adf, to_wiki
from platform_api.practice_jira.jql import JqlError, ordered, parse
from platform_api.practice_jira.store import (
    PRACTICE_ACCOUNT,
    PRACTICE_EMAIL,
    PracticeJira,
    PracticeTicket,
)
from platform_api.shared import (
    JIRA_KEY_PATTERN,
    JIRA_PROJECT_PATTERN,
    Principal,
    Role,
    TicketStatus,
)
from platform_api.wire import WireModel, error_response

router = APIRouter()
API = "/practice-jira/rest/api/{version}"
DONE_TRANSITION = "31"
MAX_RESULTS = 100


def current_practice(request: Request) -> PracticeJira:
    practice: PracticeJira = request.app.state.practice_jira
    return practice


Practice = Annotated[PracticeJira, Depends(current_practice)]


def _errors(status: int, messages: list[str], errors: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"errorMessages": messages, "errors": errors or {}}, status_code=status)


def _signed_in(practice: PracticeJira, header: str) -> bool:
    scheme, _, value = header.partition(" ")
    match scheme.lower():
        case "bearer":
            token = value.strip()
        case "basic":
            try:
                _, _, token = base64.b64decode(value.strip(), validate=True).decode().partition(":")
            except binascii.Error, UnicodeDecodeError:
                return False
        case _:
            return False
    return bool(token) and hmac.compare_digest(token.encode(), practice.token.encode())


def _gate(request: Request, practice: PracticeJira, version: str) -> JSONResponse | None:
    """What every REST call meets first: a failure a test asked for, the API version, sign-in."""
    failure = practice.take_failure()
    if failure is not None:
        headers = {} if failure.retry_after is None else {"Retry-After": str(failure.retry_after)}
        response = _errors(failure.status, ["The practice Jira was told to fail this call."])
        response.headers.update(headers)
        return response
    if version not in {"2", "3"}:
        return _errors(404, ["No such API version."])
    if not _signed_in(practice, request.headers.get("authorization", "")):
        return _errors(
            401, ["You are not authenticated. Authentication required to perform this operation."]
        )
    practice.calls.append(f"{request.method} {request.url.path.removeprefix('/practice-jira')}")
    return None


def _stamp(at: datetime | None) -> str | None:
    if at is None:
        return None
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}" + at.strftime("%z")


def _category(status: TicketStatus) -> dict[str, Any]:
    if status == "Done":
        return {"id": 3, "key": "done", "name": "Done", "colorName": "green"}
    return {"id": 2, "key": "new", "name": "To Do", "colorName": "blue-gray"}


def _account(version: str, account: str) -> dict[str, Any]:
    """A user as Jira shows one: Cloud names it by accountId, Data Center by name and key."""
    shown = {"displayName": account, "active": True}
    if version == "3":
        return {"accountId": account, **shown}
    return {"name": account, "key": account, **shown}


def _issue(request: Request, version: str, ticket: PracticeTicket) -> dict[str, Any]:
    description: object
    if not ticket.body:
        description = None
    elif version == "3":
        description = to_adf(ticket.body)
    else:
        description = to_wiki(ticket.body)
    api = str(request.base_url).rstrip("/") + f"/practice-jira/rest/api/{version}"
    return {
        "id": str(ticket.number),
        "key": ticket.key,
        "self": f"{api}/issue/{ticket.number}",
        "fields": {
            "summary": ticket.title,
            "description": description,
            "project": {"id": ticket.project, "key": ticket.project, "name": ticket.project},
            "issuetype": {"name": ticket.issue_type},
            "labels": list(ticket.labels),
            "creator": None if ticket.creator is None else _account(version, ticket.creator),
            "reporter": None if ticket.creator is None else _account(version, ticket.creator),
            "status": {"name": ticket.status, "statusCategory": _category(ticket.status)},
            "resolution": None if ticket.done_at is None else {"name": "Done"},
            "created": _stamp(ticket.created_at),
            "updated": _stamp(ticket.done_at or ticket.created_at),
            "resolutiondate": _stamp(ticket.done_at),
            "statuscategorychangedate": _stamp(ticket.done_at or ticket.created_at),
        },
    }


@router.post(API + "/issue", include_in_schema=False)
async def create_issue(version: str, request: Request, practice: Practice) -> Response:
    if (refused := _gate(request, practice, version)) is not None:
        return refused
    body = await _json(request)
    if body is None:
        return _errors(400, ["The request body is not JSON."])
    if not isinstance(json_object(body).get("fields"), dict):
        return _errors(400, ["The request needs fields."])
    fields = json_object(json_object(body).get("fields"))
    problems: dict[str, str] = {}
    project = json_object(fields.get("project")).get("key")
    if not isinstance(project, str) or JIRA_PROJECT_PATTERN.match(project) is None:
        problems["project"] = "valid project is required"
        project = ""
    summary = fields.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        problems["summary"] = "You must specify a summary of the issue."
        summary = ""
    elif "\n" in summary or "\r" in summary or len(summary) > 255:
        problems["summary"] = "Summary must be one line of less than 255 characters."
    issue_type = json_object(fields.get("issuetype")).get("name")
    if not isinstance(issue_type, str) or not issue_type:
        problems["issuetype"] = "issue type is required"
        issue_type = ""
    raw_labels = fields.get("labels", [])
    listed = json_list(raw_labels)
    labels = [label for label in listed if isinstance(label, str)]
    whole = isinstance(raw_labels, list) and len(labels) == len(listed)
    if not whole or not all(label and " " not in label and len(label) <= 255 for label in labels):
        problems["labels"] = "A label must be one word of 255 characters or fewer."
    description = fields.get("description")
    if version == "3":
        if description is not None and json_object(description).get("type") != "doc":
            problems["description"] = "Operation value must be an Atlassian Document."
        text = from_adf(description)
    else:
        if description is not None and not isinstance(description, str):
            problems["description"] = "Operation value must be a string."
        text = from_wiki(description)
    if problems:
        return _errors(400, [], problems)
    ticket = await practice.create(project, summary, text, labels, issue_type)
    issue = _issue(request, version, ticket)
    return JSONResponse(
        {"id": issue["id"], "key": issue["key"], "self": issue["self"]}, status_code=201
    )


@router.get(API + "/issue/{key}", include_in_schema=False)
async def get_issue(version: str, key: str, request: Request, practice: Practice) -> Response:
    if (refused := _gate(request, practice, version)) is not None:
        return refused
    ticket = await practice.get(key.upper())
    if ticket is None:
        return _errors(404, ["Issue does not exist or you do not have permission to see it."])
    return JSONResponse(_issue(request, version, ticket))


async def _search(
    request: Request, practice: PracticeJira, version: str, jql: str, max_results: int
) -> dict[str, Any] | JSONResponse:
    try:
        query = parse(jql, practice.time_zone)
    except JqlError as error:
        return _errors(400, [str(error)])
    tickets = await practice.newest_first()
    known = {ticket.key for ticket in tickets}
    for key in query.keys:
        if JIRA_KEY_PATTERN.match(key) is None:
            return _errors(400, [f"The issue key '{key}' for field 'key' is invalid."])
        if key not in known:
            return _errors(400, [f"An issue with key '{key}' does not exist for field 'key'."])
    found = ordered([t for t in tickets if query.where(t)], query)
    limit = max(0, min(max_results, MAX_RESULTS))
    return {
        "total": len(found),
        "issues": [_issue(request, version, ticket) for ticket in found[:limit]],
    }


async def _json(request: Request) -> object | None:
    try:
        body: object = await request.json()
    except ValueError:
        return None
    return body


async def _search_params(request: Request) -> tuple[str, int] | JSONResponse:
    if request.method == "POST":
        body = await _json(request)
        given = json_object(body)
        if not isinstance(body, dict):
            return _errors(400, ["The request body is not a JSON object."])
        jql: object = given.get("jql", "")
        wanted: object = given.get("maxResults", 50)
    else:
        jql = request.query_params.get("jql", "")
        wanted = request.query_params.get("maxResults", "50")
    if not isinstance(wanted, int | str):
        return _errors(400, ["maxResults must be a number."])
    try:
        return str(jql), int(wanted)
    except ValueError:
        return _errors(400, ["maxResults must be a number."])


@router.api_route(
    "/practice-jira/rest/api/2/search", methods=["GET", "POST"], include_in_schema=False
)
async def search_datacenter(request: Request, practice: Practice) -> Response:
    if (refused := _gate(request, practice, "2")) is not None:
        return refused
    params = await _search_params(request)
    if isinstance(params, JSONResponse):
        return params
    answer = await _search(request, practice, "2", *params)
    if isinstance(answer, JSONResponse):
        return answer
    return JSONResponse({"startAt": 0, "maxResults": params[1], **answer})


@router.api_route(
    "/practice-jira/rest/api/3/search/jql", methods=["GET", "POST"], include_in_schema=False
)
async def search_cloud(request: Request, practice: Practice) -> Response:
    if (refused := _gate(request, practice, "3")) is not None:
        return refused
    params = await _search_params(request)
    if isinstance(params, JSONResponse):
        return params
    answer = await _search(request, practice, "3", *params)
    if isinstance(answer, JSONResponse):
        return answer
    return JSONResponse({"issues": answer["issues"], "isLast": True})


@router.api_route(
    "/practice-jira/rest/api/3/search", methods=["GET", "POST"], include_in_schema=False
)
async def search_cloud_retired(request: Request, practice: Practice) -> Response:
    if (refused := _gate(request, practice, "3")) is not None:
        return refused
    return _errors(
        410,
        ["The requested API has been removed. Please migrate to the /rest/api/3/search/jql API."],
    )


def _transitions() -> dict[str, Any]:
    return {
        "expand": "transitions",
        "transitions": [
            {
                "id": DONE_TRANSITION,
                "name": "Done",
                "to": {"name": "Done", "statusCategory": _category("Done")},
            }
        ],
    }


@router.get(API + "/issue/{key}/transitions", include_in_schema=False)
async def list_transitions(
    version: str, key: str, request: Request, practice: Practice
) -> Response:
    if (refused := _gate(request, practice, version)) is not None:
        return refused
    if await practice.get(key.upper()) is None:
        return _errors(404, ["Issue does not exist or you do not have permission to see it."])
    return JSONResponse(_transitions())


@router.post(API + "/issue/{key}/transitions", include_in_schema=False)
async def make_transition(version: str, key: str, request: Request, practice: Practice) -> Response:
    if (refused := _gate(request, practice, version)) is not None:
        return refused
    body = await _json(request)
    wanted = json_object(json_object(body).get("transition")).get("id")
    if await practice.get(key.upper()) is None:
        return _errors(404, ["Issue does not exist or you do not have permission to see it."])
    if str(wanted) != DONE_TRANSITION:
        return _errors(400, [f"Transition id '{wanted}' is not valid for this issue."])
    await practice.mark_done(key.upper())
    return Response(status_code=204)


@router.get(API + "/myself", include_in_schema=False)
async def myself(version: str, request: Request, practice: Practice) -> Response:
    """The account the token signs in as. Every token the practice Jira accepts is the
    platform's own account."""
    if (refused := _gate(request, practice, version)) is not None:
        return refused
    return JSONResponse(
        {
            **_account(version, PRACTICE_ACCOUNT),
            "emailAddress": PRACTICE_EMAIL,
            "timeZone": practice.time_zone,
        }
    )


@router.get(API + "/project/{key}", include_in_schema=False)
async def get_project(version: str, key: str, request: Request, practice: Practice) -> Response:
    """The practice Jira has every project whose key Jira would allow."""
    if (refused := _gate(request, practice, version)) is not None:
        return refused
    if JIRA_PROJECT_PATTERN.match(key) is None:
        return _errors(404, [f"No project could be found with key '{key}'."])
    return JSONResponse({"id": key, "key": key, "name": key})


@router.get("/practice-jira/browse/{key}", include_in_schema=False)
async def browse(key: str, practice: Practice) -> Response:
    """Where a person opens a ticket: the Portal's Practice Jira page."""
    return RedirectResponse(f"{practice.portal_url}/jira/{quote(key, safe='')}", status_code=302)


class MockJiraTicket(WireModel):
    key: str
    project: str
    title: str
    body: str
    created_at: datetime
    run_id: str | None
    proposal_id: str | None
    status: TicketStatus
    done_at: datetime | None


class MockJiraTickets(WireModel):
    tickets: list[MockJiraTicket]


def mock_jira_ticket(ticket: PracticeTicket) -> MockJiraTicket:
    return MockJiraTicket(
        key=ticket.key,
        project=ticket.project,
        title=ticket.title,
        body=ticket.body,
        created_at=ticket.created_at,
        run_id=ticket.run_id,
        proposal_id=ticket.proposal_id,
        status=ticket.status,
        done_at=ticket.done_at,
    )


def _operator(principal: CurrentPrincipal) -> Principal:
    if Role.OPERATOR not in principal.roles:
        raise HTTPException(
            status_code=403, detail="Only an Operator can do this. Ask an Operator on the team."
        )
    return principal


@router.get("/api/v1/mock-jira/tickets", tags=["stubs"], responses=SIGNED_IN)
async def list_mock_jira_tickets(
    principal: CurrentPrincipal, practice: Practice
) -> MockJiraTickets:
    return MockJiraTickets(tickets=[mock_jira_ticket(t) for t in await practice.tickets()])


@router.post(
    "/api/v1/mock-jira/tickets/{key}/done",
    tags=["stubs"],
    description=(
        "Marks a practice Jira ticket Done, as a person would in Jira. The watchlist then "
        "moves our version to the version the ticket named, so only an Operator may do it. "
        "Marking a Done ticket again changes nothing."
    ),
    responses={**OPERATORS_ONLY, 404: error_response("No such ticket")},
)
async def mark_mock_jira_ticket_done(
    key: str, principal: Annotated[Principal, Depends(_operator)], practice: Practice
) -> MockJiraTicket:
    ticket = await practice.mark_done(key)
    if ticket is None:
        raise HTTPException(status_code=404, detail="No such ticket")
    return mock_jira_ticket(ticket)
