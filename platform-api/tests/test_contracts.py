import json
from pathlib import Path
from typing import Any, TypeAliasType, get_args

import pytest
from pydantic import TypeAdapter

from platform_api.auth import DevUsers
from platform_api.builder.http import SuggestOut, TemplateList, UseCaseView
from platform_api.monitoring.agent_events import AgentEventPost
from platform_api.monitoring.events import DeniedReason, WireVerdict, activity_events_adapter
from platform_api.monitoring.http import TroubleshootingOut
from platform_api.orchestration.agents import AgentCards, TaskRequest, task_result_adapter
from platform_api.orchestration.approvals import Refusal, Verdict
from platform_api.orchestration.http import (
    ApprovalView,
    DecisionOut,
    MockJiraTickets,
    RefusalOut,
    StepResponseOut,
    TeamsStubMessages,
    WorkflowFailureIn,
    run_view_adapter,
)
from platform_api.orchestration.write_actions import DenyReason

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
FIXTURES = CONTRACTS / "fixtures"

pytestmark = pytest.mark.skipif(
    not FIXTURES.exists(), reason="contracts/ is not in the test image. CI runs this on the host."
)

PARSERS: dict[str, TypeAdapter[Any]] = {
    "runs/success.json": activity_events_adapter,
    "runs/failure.json": activity_events_adapter,
    "runs/rejected.json": activity_events_adapter,
    "views/success.awaiting_approval.json": run_view_adapter,
    "views/success.final.json": run_view_adapter,
    "views/failure.working.json": run_view_adapter,
    "views/failure.final.json": run_view_adapter,
    "views/rejected.awaiting_approval.json": run_view_adapter,
    "views/rejected.final.json": run_view_adapter,
    "approvals/apr_01JB8.alice.json": TypeAdapter(ApprovalView),
    "approvals/apr_01JB8.bob.json": TypeAdapter(ApprovalView),
    "approvals/decision.approved.json": TypeAdapter(DecisionOut),
    "approvals/refusal.own_work.json": TypeAdapter(RefusalOut),
    "builder/templates.json": TypeAdapter(TemplateList),
    "builder/use-case.json": TypeAdapter(UseCaseView),
    "builder/suggest.json": TypeAdapter(SuggestOut),
    "internal/step-responses.json": TypeAdapter(list[StepResponseOut]),
    "internal/workflow-failure.json": TypeAdapter(WorkflowFailureIn),
    "stubs/dev-users.json": TypeAdapter(DevUsers),
    "stubs/teams-messages.json": TypeAdapter(TeamsStubMessages),
    "stubs/mock-jira-tickets.json": TypeAdapter(MockJiraTickets),
    "troubleshooting/failure.json": TypeAdapter(TroubleshootingOut),
    "agent/task-request.json": TypeAdapter(TaskRequest),
    "agent/task-finished.json": task_result_adapter,
    "agent/task-failed.json": task_result_adapter,
    "agent/callback-event.json": TypeAdapter(AgentEventPost),
    "agent/agent-cards.json": TypeAdapter(AgentCards),
}


def load(relative: str) -> object:
    return json.loads((FIXTURES / relative).read_text())


@pytest.mark.parametrize("relative", sorted(PARSERS))
def test_fixture_parses(relative: str):
    PARSERS[relative].validate_python(load(relative))


def test_every_fixture_file_has_a_parser():
    on_disk = {str(p.relative_to(FIXTURES)) for p in FIXTURES.rglob("*.json")}
    assert on_disk == set(PARSERS)


@pytest.mark.parametrize("story", ["success", "failure", "rejected"])
def test_run_events_are_gapless_and_in_time_order(story: str):
    events = activity_events_adapter.validate_python(load(f"runs/{story}.json"))
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert all(a.ts <= b.ts for a, b in zip(events, events[1:], strict=False))
    assert len({e.run_id for e in events}) == 1


AGENT_KINDS = {
    "agent_joined",
    "agent_step_started",
    "agent_step_finished",
    "agent_failed",
    "agent_message",
}


@pytest.mark.parametrize(
    ("story", "result"), [("success", "task-finished"), ("failure", "task-failed")]
)
def test_agent_events_in_the_run_match_the_agent_result(story: str, result: str):
    run_events = activity_events_adapter.validate_python(load(f"runs/{story}.json"))
    from_run = [e for e in run_events if e.kind in AGENT_KINDS]
    task = task_result_adapter.validate_python(load(f"agent/{result}.json"))
    assert [e.agent_seq for e in task.events] == list(range(1, len(task.events) + 1))
    assert len(from_run) == len(task.events)
    for run_event, agent_event in zip(from_run, task.events, strict=True):
        assert run_event.kind == agent_event.kind
        assert run_event.ts == agent_event.ts
        assert run_event.summary == agent_event.summary
        assert (run_event.actor.id, run_event.actor.display) == (
            agent_event.agent.id,
            agent_event.agent.display,
        )
        assert run_event.data.model_dump() == agent_event.data.model_dump()


def test_stories_end_as_their_names_say():
    assert activity_events_adapter.validate_python(load("runs/success.json"))[-1].kind == (
        "run_succeeded"
    )
    failed = activity_events_adapter.validate_python(load("runs/failure.json"))[-1]
    assert failed.kind == "run_failed"
    assert (failed.data.reason, failed.data.retryable) == ("AgentError", True)
    rejected = activity_events_adapter.validate_python(load("runs/rejected.json"))[-1]
    assert rejected.kind == "run_rejected"
    assert rejected.data.by == "bob"


def test_approval_views_follow_the_own_work_rule():
    alice = ApprovalView.model_validate(load("approvals/apr_01JB8.alice.json"))
    bob = ApprovalView.model_validate(load("approvals/apr_01JB8.bob.json"))
    assert (alice.you_can_decide, alice.why_not) == (False, Refusal.OWN_WORK)
    assert (bob.you_can_decide, bob.why_not) == (True, None)
    assert alice.digest == bob.digest


def _literal_values(alias: TypeAliasType) -> set[str]:
    return set(get_args(alias.__value__))


def test_wire_sets_cover_the_domain_enums():
    assert {r.value for r in DenyReason} <= _literal_values(DeniedReason)
    assert {v.value for v in Verdict} == _literal_values(WireVerdict)
