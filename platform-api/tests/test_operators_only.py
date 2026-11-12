import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any, cast

import pytest
from fastapi import APIRouter, FastAPI, Header
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from fastapi.testclient import TestClient

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.http import Operator, operators_only
from platform_api.db import Database
from platform_api.orchestration.http import require_operator
from platform_api.orchestration.settings_http import Approver
from platform_api.practice_jira import PracticeJira
from platform_api.practice_jira.http import _operator as practice_jira_operator
from tests.declared import BOB, app_with

CHANGES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
OPERATOR_CHECKS = frozenset(
    check.__code__ for check in (operators_only(""), require_operator, practice_jira_operator)
)
# platform-api is reachable from the internet in Azure. Outside /api/v1 there are only n8n's and
# the agent runtime's calls, each keyed by a header, the practice Jira with its own token,
# health and the docs. A new prefix, such as /api/v2, fails until someone judges it.
SERVICE_PREFIXES = ("/api/v1/", "/internal/v1/", "/practice-jira/")
SERVICE_PATHS = frozenset(
    {"/healthz", "/healthz/ready", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
)
SERVICE_KEYS = frozenset({"X-Step-Key", "X-Callback-Token"})
LEAST_CHANGES = 43

# Who else may call a route that changes something, and why. Every other change needs an
# Operator, as in the prototype's OPEN_TO table, so a new route is an Operator's until it is
# added here. Reads are not walked, and two of them write our own row: GET
# /api/v1/settings/connections and GET /api/v1/capabilities check a connection never checked
# with what it uses now, as Check now does. That only reads Jira or GitHub and keeps the result
# in connection_checks, so it is not a write action under the approval gate.
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
    ("POST", "/api/v1/approvals/{approval_id}/questions"): (
        "An Approver who may decide the open step asks the requester a question. The domain "
        "refuses anyone the gate would refuse. The question is a message on the request: it "
        "decides nothing and the request keeps waiting (ADR 0043)."
    ),
    ("POST", "/api/v1/approvals/{approval_id}/questions/{question_id}/answer"): (
        "The requester answers a question on their own request. The domain refuses anyone "
        "else, and any answer once the request is decided. An answer decides nothing (ADR 0043)."
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


def changes(app: FastAPI, prefix: str = "/api/v1/") -> Iterator[tuple[str, str, RouteContext]]:
    for route in iter_route_contexts(app.routes):
        path, methods = route.path, route.methods
        if isinstance(route.original_route, APIRoute) and path and path.startswith(prefix):
            for method in sorted((methods or set()) & CHANGES):
                yield method, path, route


def calls(dependant: Dependant) -> Iterator[Callable[..., Any] | None]:
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from calls(dependency)


def headers(dependant: Dependant) -> set[str]:
    named = {param.alias for param in dependant.header_params}
    return named.union(*(headers(dependency) for dependency in dependant.dependencies))


def needs_an_operator(route: RouteContext) -> bool:
    return any(
        getattr(call, "__code__", None) in OPERATOR_CHECKS for call in calls(route.dependant)
    )


def unchecked(app: FastAPI) -> list[str]:
    return [
        f"{method} {path}"
        for method, path, route in changes(app)
        if (method, path) not in OPEN_TO and not needs_an_operator(route)
    ]


def undeclared(app: FastAPI) -> list[str]:
    return [
        f"{method} {path}"
        for method, path, route in changes(app)
        if needs_an_operator(route) and route.responses.get(403) != OPERATORS_ONLY[403]
    ]


def stale(app: FastAPI, open_to: Mapping[tuple[str, str], str] = OPEN_TO) -> list[str]:
    found = {(method, path): route for method, path, route in changes(app)}
    return [
        f"{method} {path}"
        for method, path in open_to
        if (method, path) not in found or needs_an_operator(found[(method, path)])
    ]


def not_refused(app: FastAPI) -> dict[str, int]:
    client = TestClient(app, raise_server_exceptions=False)
    answered = {
        f"{method} {path}": client.request(
            method, re.sub(r"\{\w+\}", "x", path), headers={**BOB, "Idempotency-Key": "k"}, json={}
        )
        for method, path, _ in changes(app)
        if (method, path) not in OPEN_TO
    }
    return {
        change: response.status_code
        for change, response in answered.items()
        if response.status_code != 403 or "Only an Operator" not in response.json()["detail"]
    }


def outside_the_known_prefixes(app: FastAPI) -> list[str]:
    return [
        f"{sorted(route.methods or set())} {route.path}"
        for route in iter_route_contexts(app.routes)
        if not (route.path or "").startswith(SERVICE_PREFIXES) and route.path not in SERVICE_PATHS
    ]


def internal_without_a_key(app: FastAPI) -> list[str]:
    return [
        f"{method} {path}"
        for method, path, route in changes(app, "/internal/v1/")
        if not headers(route.dependant) & SERVICE_KEYS
    ]


def practice_jira_without_its_token(app: FastAPI) -> dict[str, int]:
    client = TestClient(app, raise_server_exceptions=False)
    answered = {
        f"{method} {path}": client.request(
            method, path.replace("{version}", "2").replace("{key}", "x"), json={}
        )
        for method, path, _ in changes(app, "/practice-jira/rest/")
    }
    return {
        change: response.status_code
        for change, response in answered.items()
        if response.status_code != 401
    }


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return app_with()


def test_the_walk_sees_every_change(app: FastAPI):
    assert len(list(changes(app))) >= LEAST_CHANGES


def test_every_change_needs_an_operator_unless_it_is_open_to_others(app: FastAPI):
    assert unchecked(app) == []


def test_every_change_that_needs_an_operator_declares_it(app: FastAPI):
    assert undeclared(app) == []


def test_the_allow_list_names_only_changes_that_need_no_operator(app: FastAPI):
    assert stale(app) == []


def test_an_approver_is_refused_every_change_not_open_to_others(app: FastAPI):
    assert not_refused(app) == {}


def test_every_route_outside_api_v1_is_a_service_call_health_or_the_docs(app: FastAPI):
    assert outside_the_known_prefixes(app) == []


def test_every_internal_change_declares_its_service_key(app: FastAPI):
    assert len(list(changes(app, "/internal/v1/"))) >= 4
    assert internal_without_a_key(app) == []


def test_every_practice_jira_change_refuses_a_call_without_its_token():
    app = app_with()
    app.state.practice_jira = PracticeJira(cast(Database, object()), "practice-token", "http://x")
    assert len(list(changes(app, "/practice-jira/rest/"))) >= 5
    assert practice_jira_without_its_token(app) == {}


def with_route(add: Callable[[APIRouter], None], prefix: str = "/api/v1") -> FastAPI:
    app = app_with()
    router = APIRouter(prefix=prefix)
    add(router)
    app.include_router(router)
    return app


def test_the_walk_names_a_change_with_no_check():
    def add(router: APIRouter) -> None:
        @router.post("/use-cases/{use_case_id}/fake-change", responses=SIGNED_IN)
        def fake(use_case_id: str, principal: CurrentPrincipal) -> None: ...

    app = with_route(add)
    assert unchecked(app) == ["POST /api/v1/use-cases/{use_case_id}/fake-change"]
    assert not_refused(app) == {"POST /api/v1/use-cases/{use_case_id}/fake-change": 200}


def test_the_walk_names_a_change_only_an_approver_passes():
    def add(router: APIRouter) -> None:
        @router.patch("/fake-approver-change", responses=SIGNED_IN)
        def fake(principal: Approver) -> None: ...

    assert unchecked(with_route(add)) == ["PATCH /api/v1/fake-approver-change"]


def test_the_walk_names_an_operator_change_that_does_not_declare_it():
    def add(router: APIRouter) -> None:
        @router.delete("/fake-undeclared", responses=SIGNED_IN)
        def fake(principal: Operator) -> None: ...

    app = with_route(add)
    assert unchecked(app) == []
    assert undeclared(app) == ["DELETE /api/v1/fake-undeclared"]


def test_the_walk_names_a_stale_allow_list_entry(app: FastAPI):
    gone = {**OPEN_TO, ("POST", "/api/v1/gone"): "Removed long ago."}
    needs = {**OPEN_TO, ("POST", "/api/v1/people"): "An Operator's change put on the list."}
    assert stale(app, gone) == ["POST /api/v1/gone"]
    assert stale(app, needs) == ["POST /api/v1/people"]


def test_the_walk_names_a_route_under_a_new_prefix():
    def add(router: APIRouter) -> None:
        @router.get("/fake")
        def fake() -> None: ...

    assert outside_the_known_prefixes(with_route(add, "/api/v2")) == ["['GET'] /api/v2/fake"]


def test_the_walk_names_an_internal_change_with_no_service_key():
    def add(router: APIRouter) -> None:
        @router.post("/fake-step")
        def fake() -> None: ...

        @router.post("/fake-keyed-step")
        def keyed(step_key: str = Header(alias="X-Step-Key")) -> None: ...

    assert internal_without_a_key(with_route(add, "/internal/v1")) == [
        "POST /internal/v1/fake-step"
    ]


def test_the_walk_names_a_practice_jira_change_that_skips_its_token():
    def add(router: APIRouter) -> None:
        @router.post("/api/{version}/fake")
        def fake(version: str) -> None: ...

    app = with_route(add, "/practice-jira/rest")
    app.state.practice_jira = PracticeJira(cast(Database, object()), "practice-token", "http://x")
    assert practice_jira_without_its_token(app) == {
        "POST /practice-jira/rest/api/{version}/fake": 200
    }
