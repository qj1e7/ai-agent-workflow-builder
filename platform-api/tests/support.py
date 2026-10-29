import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platform_api.orchestration import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalStep,
    Binding,
    RunSpec,
    SoftwareSource,
    WatchedSoftware,
    WatchlistTask,
)
from platform_api.shared import Principal, Role, SoftwareId, UseCaseId, UserId

LOCAL_ENV = {
    "AUTH_MODE": "dev",
    "PUBLIC_BASE_URL": "http://localhost:8000",
    "DATABASE_URL_BUILDER": "postgresql://wab_builder:x@localhost/platform",
    "DATABASE_URL_ORCHESTRATION": "postgresql://wab_orchestration:x@localhost/platform",
    "DATABASE_URL_MONITORING": "postgresql://wab_monitoring:x@localhost/platform",
    "AGENT_RUNTIME_URL": "http://agent-runtime:8100",
    "AGENT_API_KEY": "test-agent-key",
    "N8N_BASE_URL": "http://n8n:5678",
    "STEP_KEY": "test-step-key",
    "PLATFORM_INTERNAL_URL": "http://platform-api:8000",
    "CALLBACK_SIGNING_KEY": "test-callback-key",
}

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts"
FIXTURES = Path(os.environ.get("CONTRACT_FIXTURES") or CONTRACTS / "fixtures")
"""The test image has no contracts/ folder, so CI mounts it and names it here."""
MOCK_OIDC_CONFIG = Path(
    os.environ.get("MOCK_OIDC_CONFIG") or REPO / "deploy" / "mock-oidc" / "config.json"
)

ALICE = Principal(UserId("alice"), frozenset({Role.OPERATOR, Role.APPROVER}), "Alice")
BOB = Principal(UserId("bob"), frozenset({Role.APPROVER}), "Bob")
CAROL = Principal(UserId("carol"), frozenset({Role.OPERATOR}), "Carol")
NOW = datetime(2026, 11, 3, 2, 14, tzinfo=UTC)

LANGGRAPH = SoftwareId("sw_01JC2A3B4C5D6E7F8G9H0J1K2M")
REDIS = SoftwareId("sw_01REDIS")
FASTAPI = SoftwareId("sw_01FASTAPI")
POSTGRES = SoftwareId("sw_01POSTGRES")


def watched(
    software_id: SoftwareId,
    name: str,
    ref: str,
    our_version: str | None,
    open_ticket: str | None = None,
    awaiting_approval: bool = False,
) -> WatchedSoftware:
    return WatchedSoftware(
        software_id, name, SoftwareSource(ref), our_version, open_ticket, awaiting_approval
    )


SUMMARY = "1 of 1 watched software has new releases: LangGraph 1.2.16."
TICKET_TITLE = "Upgrade LangGraph from 1.2.14 to 1.2.16"
INSTRUCTION = (
    "Check the team's watched software for new releases and raise an upgrade ticket for each "
    "one that is behind."
)

SPEC = RunSpec(
    use_case_id=UseCaseId("uc_01JB7"),
    use_case_version=1,
    use_case_name="Software watchlist",
    owner=UserId("alice"),
    workflow="run",
    instruction=INSTRUCTION,
    task=WatchlistTask(
        tag_pattern=r"^\d+\.\d+\.\d+$",
        software=(watched(LANGGRAPH, "LangGraph", "langchain-ai/langgraph", "1.2.14"),),
    ),
    bindings={"create_ticket": Binding("jira", "create_ticket", {"project": "MOCK"})},
    approval_policy=ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
)
"""A check of a watchlist that holds one software, LangGraph at 1.2.14. The recorded stories in
contracts/ follow this run."""

WATCHLIST_TASK = WatchlistTask(
    tag_pattern=r"^\d+\.\d+\.\d+$",
    software=(
        watched(LANGGRAPH, "LangGraph", "langchain-ai/langgraph", "1.2.14"),
        watched(REDIS, "Redis", "redis/redis", None),
        watched(FASTAPI, "FastAPI", "fastapi/fastapi", "0.115.0"),
        watched(POSTGRES, "PostgreSQL", "postgres/postgres", "17.2.0"),
    ),
)

WATCHLIST_SPEC = RunSpec(
    use_case_id=UseCaseId("uc_01WATCH"),
    use_case_version=3,
    use_case_name="Software watchlist",
    owner=UserId("alice"),
    workflow="run",
    instruction=INSTRUCTION,
    task=WATCHLIST_TASK,
    bindings={"create_ticket": Binding("jira", "create_ticket", {"project": "MOCK"})},
    approval_policy=ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
)


def fixture(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text())
