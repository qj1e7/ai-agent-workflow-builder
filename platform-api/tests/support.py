import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platform_api.orchestration import AnyApprover, ApprovalPolicy, ApprovalStep, Binding, RunSpec
from platform_api.shared import Principal, Role, UseCaseId, UserId

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
"""The same for deploy/, which holds the mock identity provider's users."""

ALICE = Principal(UserId("alice"), frozenset({Role.OPERATOR, Role.APPROVER}), "Alice")
BOB = Principal(UserId("bob"), frozenset({Role.APPROVER}), "Bob")
CAROL = Principal(UserId("carol"), frozenset({Role.OPERATOR}), "Carol")
NOW = datetime(2026, 11, 3, 2, 14, tzinfo=UTC)

SPEC = RunSpec(
    use_case_id=UseCaseId("uc_01JB7"),
    use_case_version=1,
    use_case_name="LangGraph releases",
    owner=UserId("alice"),
    workflow="release_check",
    instruction="Check langchain-ai/langgraph for new releases and open a ticket for the team.",
    repo="langchain-ai/langgraph",
    tag_pattern=r"^\d+\.\d+\.\d+$",
    last_known_tag="1.2.14",
    bindings={"create_ticket": Binding("jira", "create_ticket", {"project": "MOCK"})},
    approval_policy=ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
)


def fixture(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text())
