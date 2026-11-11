import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from fastapi.testclient import TestClient

from platform_api.auth import OPERATORS_ONLY
from platform_api.builder.http import operators_only
from platform_api.orchestration.http import require_operator
from platform_api.practice_jira.http import _operator as practice_jira_operator
from tests.declared import BOB, app_with

CHANGES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
OPERATOR_CHECKS = frozenset(
    check.__code__ for check in (operators_only(""), require_operator, practice_jira_operator)
)

# Who else may call a route that changes something, and why. Every other change needs an
# Operator, as in the prototype's OPEN_TO table, so a new route is an Operator's until it is
# added here.
OPEN_TO: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/team-requests"): (
        "Anyone signed in asks the team or reports to support. The request stays in our own "
        "database, and Approvers take part (ADR 0038)."
    ),
    ("POST", "/api/v1/team-requests/{request_id}/replies"): (
        "Anyone signed in replies to a team request (ADR 0038)."
    ),
    ("POST", "/api/v1/team-requests/{request_id}/seen"): (
        "The asker marks their own request seen. The service refuses anyone else."
    ),
    ("POST", "/api/v1/approvals/{approval_id}/decisions"): (
        "Approvers decide on a request. The domain refuses anyone else and their own work, "
        "and keeps the access review's two Approvers in turn."
    ),
    ("POST", "/api/v1/confirmations/{confirmation_id}/decisions"): (
        "Approvers confirm a new Approver or a new AI model address. The domain refuses "
        "anyone else, the person who asked, and the person it is about."
    ),
    ("POST", "/api/v1/settings/model/address-decision"): (
        "Approvers confirm a new AI model address. The route refuses anyone else, and the "
        "person who entered it."
    ),
    ("POST", "/api/v1/use-cases/suggest"): (
        "Only reads: it matches the words to a template in memory and keeps nothing."
    ),
    ("POST", "/api/v1/agent-cards/check"): (
        "Only reads: it checks a card without saving it, for the editor as the Operator types."
    ),
}


def changes(app: FastAPI) -> Iterator[tuple[str, str, RouteContext]]:
    for route in iter_route_contexts(app.routes):
        path, methods = route.path, route.methods
        if isinstance(route.original_route, APIRoute) and path and path.startswith("/api/v1/"):
            for method in sorted((methods or set()) & CHANGES):
                yield method, path, route


def calls(dependant: Dependant) -> Iterator[Callable[..., Any] | None]:
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from calls(dependency)


def needs_an_operator(route: RouteContext) -> bool:
    return any(
        getattr(call, "__code__", None) in OPERATOR_CHECKS for call in calls(route.dependant)
    )


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return app_with()


def test_every_change_needs_an_operator_unless_it_is_open_to_others(app: FastAPI):
    unchecked = [
        f"{method} {path}"
        for method, path, route in changes(app)
        if (method, path) not in OPEN_TO and not needs_an_operator(route)
    ]
    assert unchecked == []


def test_every_change_that_needs_an_operator_declares_it(app: FastAPI):
    undeclared = [
        f"{method} {path}"
        for method, path, route in changes(app)
        if needs_an_operator(route) and route.responses.get(403) != OPERATORS_ONLY[403]
    ]
    assert undeclared == []


def test_the_allow_list_names_only_changes_that_need_no_operator(app: FastAPI):
    found = {(method, path): route for method, path, route in changes(app)}
    assert sorted(set(OPEN_TO) - set(found)) == []
    assert [f"{m} {p}" for m, p in OPEN_TO if needs_an_operator(found[(m, p)])] == []


def test_an_approver_is_refused_every_change_not_open_to_others(app: FastAPI):
    client = TestClient(app, raise_server_exceptions=False)
    answered = {
        f"{method} {path}": client.request(
            method, re.sub(r"\{\w+\}", "x", path), headers={**BOB, "Idempotency-Key": "k"}, json={}
        )
        for method, path, _ in changes(app)
        if (method, path) not in OPEN_TO
    }
    not_refused = {
        change: response.status_code
        for change, response in answered.items()
        if response.status_code != 403 or "Only an Operator" not in response.json()["detail"]
    }
    assert answered
    assert not_refused == {}
