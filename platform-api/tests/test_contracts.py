import json
from typing import Any, TypeAliasType, get_args

import pytest
from pydantic import TypeAdapter

from platform_api.auth import DevUsers
from platform_api.builder.http import SuggestOut, TemplateList, UseCaseView
from platform_api.builder.models import (
    AddSoftware,
    CannotDo,
    CardChecked,
    CardList,
    NewAgent,
    PlanOut,
    ScheduleIn,
    ToolList,
    UnderstandOut,
    UseSaved,
    WatchlistOut,
    WatchlistView,
)
from platform_api.monitoring.agent_events import AgentEventPost
from platform_api.monitoring.events import DeniedReason, WireVerdict, activity_events_adapter
from platform_api.monitoring.http import TroubleshootingOut
from platform_api.orchestration.agents import (
    AgentCards,
    ChooseRequest,
    ConnectRequest,
    DraftRequest,
    ModelAccess,
    TaskFinished,
    TaskRequest,
    UnderstandRequest,
    choose_result_adapter,
    connect_result_adapter,
    draft_result_adapter,
    model_test_result_adapter,
    task_result_adapter,
    understand_result_adapter,
)
from platform_api.orchestration.agents import ToolList as AgentToolList
from platform_api.orchestration.approvals import Refusal, Verdict
from platform_api.orchestration.http import (
    ApprovalView,
    DecisionOut,
    MockJiraTicket,
    MockJiraTickets,
    RefusalOut,
    StepResponseOut,
    TeamsStubMessages,
    TickOut,
    WorkflowFailureIn,
    run_view_adapter,
)
from platform_api.orchestration.runs import FailureReason, Leg, Stage, StepName
from platform_api.orchestration.settings_http import ModelSettingsView, SaveOut
from platform_api.orchestration.write_actions import DenyReason
from platform_api.wire import FailureReason as WireFailureReason
from platform_api.wire import FailureStage
from platform_api.wire import Leg as WireLeg
from platform_api.wire import StepName as WireStepName
from tests.support import FIXTURES

pytestmark = pytest.mark.skipif(
    not FIXTURES.exists(), reason="contracts/ is not in the test image. CI runs this on the host."
)

PARSERS: dict[str, TypeAdapter[Any]] = {
    "runs/success.json": activity_events_adapter,
    "runs/failure.json": activity_events_adapter,
    "runs/rejected.json": activity_events_adapter,
    "runs/watchlist.json": activity_events_adapter,
    "runs/card.json": activity_events_adapter,
    "cards/tools.json": TypeAdapter(ToolList),
    "cards/list.json": TypeAdapter(CardList),
    "cards/check.json": TypeAdapter(CardChecked),
    "cards/plan.use-one.json": TypeAdapter(PlanOut),
    "cards/plan.new-agent.json": TypeAdapter(PlanOut),
    "cards/plan.cannot-do.json": TypeAdapter(PlanOut),
    "cards/use-case.json": TypeAdapter(UseCaseView),
    "agent/tools.json": TypeAdapter(AgentToolList),
    "agent/card-task-request.json": TypeAdapter(TaskRequest),
    "agent/card-task-finished.json": task_result_adapter,
    "agent/card-draft-request.json": TypeAdapter(DraftRequest),
    "agent/card-drafted.json": draft_result_adapter,
    "agent/planner-choose-request.json": TypeAdapter(ChooseRequest),
    "agent/planner-chosen.json": choose_result_adapter,
    "agent/planner-understand-request.json": TypeAdapter(UnderstandRequest),
    "agent/planner-understood.json": understand_result_adapter,
    "agent/planner-watchlist.json": understand_result_adapter,
    "views/success.awaiting_approval.json": run_view_adapter,
    "views/success.final.json": run_view_adapter,
    "views/failure.working.json": run_view_adapter,
    "views/failure.final.json": run_view_adapter,
    "views/rejected.awaiting_approval.json": run_view_adapter,
    "views/rejected.final.json": run_view_adapter,
    "views/watchlist.awaiting_approval.json": run_view_adapter,
    "approvals/apr_01JB8.alice.json": TypeAdapter(ApprovalView),
    "approvals/apr_01JB8.bob.json": TypeAdapter(ApprovalView),
    "approvals/decision.approved.json": TypeAdapter(DecisionOut),
    "approvals/refusal.own_work.json": TypeAdapter(RefusalOut),
    "builder/templates.json": TypeAdapter(TemplateList),
    "builder/use-case.json": TypeAdapter(UseCaseView),
    "builder/suggest.json": TypeAdapter(SuggestOut),
    "builder/understand.rows.json": TypeAdapter(UnderstandOut),
    "builder/understand.watchlist.json": TypeAdapter(UnderstandOut),
    "builder/understand.starters.json": TypeAdapter(UnderstandOut),
    "internal/step-responses.json": TypeAdapter(list[StepResponseOut]),
    "internal/workflow-failure.json": TypeAdapter(WorkflowFailureIn),
    "stubs/dev-users.json": TypeAdapter(DevUsers),
    "stubs/teams-messages.json": TypeAdapter(TeamsStubMessages),
    "stubs/mock-jira-tickets.json": TypeAdapter(MockJiraTickets),
    "stubs/mock-jira-ticket.done.json": TypeAdapter(MockJiraTicket),
    "troubleshooting/failure.json": TypeAdapter(TroubleshootingOut),
    "agent/task-request.json": TypeAdapter(TaskRequest),
    "agent/task-finished.json": task_result_adapter,
    "agent/task-failed.json": task_result_adapter,
    "agent/watchlist-task-request.json": TypeAdapter(TaskRequest),
    "agent/watchlist-task-finished.json": task_result_adapter,
    "agent/callback-event.json": TypeAdapter(AgentEventPost),
    "agent/agent-cards.json": TypeAdapter(AgentCards),
    "agent/model-connect-request.json": TypeAdapter(ConnectRequest),
    "agent/model-connected.json": connect_result_adapter,
    "agent/model-test-request.json": TypeAdapter(ModelAccess),
    "agent/model-test-passed.json": model_test_result_adapter,
    "agent/model-problem.json": model_test_result_adapter,
    "settings/model.empty.json": TypeAdapter(ModelSettingsView),
    "settings/model.active.json": TypeAdapter(ModelSettingsView),
    "settings/model.pending.alice.json": TypeAdapter(ModelSettingsView),
    "settings/model.pending.bob.json": TypeAdapter(ModelSettingsView),
    "settings/connect.connected.json": connect_result_adapter,
    "settings/connect.problem.json": connect_result_adapter,
    "settings/save.saved.json": TypeAdapter(SaveOut),
    "settings/save.awaiting_confirmation.json": TypeAdapter(SaveOut),
    "settings/save.too_slow.json": TypeAdapter(SaveOut),
    "watchlist/none.json": TypeAdapter(WatchlistOut),
    "watchlist/empty.json": TypeAdapter(WatchlistView),
    "watchlist/statuses.json": TypeAdapter(WatchlistView),
    "watchlist/add-software.json": TypeAdapter(AddSoftware),
    "watchlist/schedule.in.json": TypeAdapter(ScheduleIn),
    "watchlist/schedule.saved.json": TypeAdapter(WatchlistView),
    "watchlist/schedule.off.json": TypeAdapter(WatchlistView),
    "internal/tick.started.json": TypeAdapter(TickOut),
    "internal/tick.nothing-due.json": TypeAdapter(TickOut),
    "views/scheduled.pending.json": run_view_adapter,
    "watchlist/before-check.json": TypeAdapter(WatchlistView),
}


def load(relative: str) -> object:
    return json.loads((FIXTURES / relative).read_text())


@pytest.mark.parametrize("relative", sorted(PARSERS))
def test_fixture_parses(relative: str):
    PARSERS[relative].validate_python(load(relative))


def test_every_fixture_file_has_a_parser():
    on_disk = {str(p.relative_to(FIXTURES)) for p in FIXTURES.rglob("*.json")}
    assert on_disk == set(PARSERS)


@pytest.mark.parametrize("story", ["success", "failure", "rejected", "watchlist", "card"])
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
    ("story", "result"),
    [("success", "task-finished"), ("failure", "task-failed"), ("card", "card-task-finished")],
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


def test_the_watchlist_fixture_shows_every_status_attention_first():
    view = WatchlistView.model_validate(load("watchlist/statuses.json"))
    assert [row.status for row in view.software] == [
        "cant_check",
        "behind",
        "awaiting_approval",
        "ticket_open",
        "not_checked",
        "up_to_date",
    ]
    assert view.schedule is not None
    none = WatchlistOut.model_validate(load("watchlist/none.json"))
    assert none.watchlist is None


def test_the_recorded_check_reads_every_watched_software_and_tickets_the_behind_ones():
    before = WatchlistView.model_validate(load("watchlist/before-check.json"))
    events = activity_events_adapter.validate_python(load("runs/watchlist.json"))
    read = [
        e.data.result
        for e in events
        if e.kind == "agent_step_finished" and e.data.step == "read_source"
    ]
    assert sorted(r["software_id"] for r in read) == sorted(row.id for row in before.software)
    behind = [r["software_id"] for r in read if r["state"] == "behind"]
    view = run_view_adapter.validate_python(load("views/watchlist.awaiting_approval.json"))
    assert view.state == "awaiting_approval"
    names = {row.id: row.name for row in before.software}
    titles = [str(action.fields["title"]) for action in view.proposal.actions]
    assert [title.split(" ")[1] for title in titles] == [names[sid] for sid in behind]
    written = [e.data.external_reference for e in events if e.kind == "write_action_done"]
    assert len(written) == len(behind)
    assert events[-1].kind == "run_succeeded"


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
    assert {r.value for r in FailureReason} == _literal_values(WireFailureReason)
    assert {s.value for s in Stage} == _literal_values(FailureStage)
    assert {s.value for s in StepName} == _literal_values(WireStepName)
    assert {leg.value for leg in Leg} == _literal_values(WireLeg)


def test_the_schedule_fixtures_show_the_owner_and_the_next_check():
    statuses = WatchlistView.model_validate(load("watchlist/statuses.json"))
    saved = WatchlistView.model_validate(load("watchlist/schedule.saved.json"))
    off = WatchlistView.model_validate(load("watchlist/schedule.off.json"))
    assert statuses.schedule is not None and saved.schedule is not None
    assert (statuses.schedule.day, statuses.schedule.owner_name) == ("monday", "Alice")
    assert (saved.schedule.day, saved.schedule.at, saved.schedule.owner) == (
        "every_day",
        "06:30",
        "carol",
    )
    assert saved.schedule.next_at > saved.schedule.saved_at
    assert off.schedule is None
    scheduled = run_view_adapter.validate_python(load("views/scheduled.pending.json"))
    assert (scheduled.trigger, scheduled.started_by) == ("schedule", "alice")
    ran = run_view_adapter.validate_python(load("views/success.final.json"))
    assert ran.trigger == "person"


def test_the_card_run_is_what_the_agent_sent_and_the_platform_bound():
    request = TypeAdapter(TaskRequest).validate_python(load("agent/card-task-request.json"))
    run = activity_events_adapter.validate_python(load("runs/card.json"))
    assert request.run_id == run[0].run_id
    finished = task_result_adapter.validate_python(load("agent/card-task-finished.json"))
    assert isinstance(finished, TaskFinished)
    proposed = next(e for e in run if e.kind == "write_action_proposed")
    [intent] = finished.output.proposed
    assert proposed.data.actions[0].line.endswith(str(intent.fields["title"]))
    assert run[-1].kind == "run_succeeded"


def test_the_three_plans_are_the_three_kinds_of_answer():
    plans = TypeAdapter(PlanOut)
    got = [
        plans.validate_python(load(f"cards/plan.{name}.json"))
        for name in ("use-one", "new-agent", "cannot-do")
    ]
    assert [type(p) for p in got] == [UseSaved, NewAgent, CannotDo]
    assert isinstance(got[1], NewAgent) and got[1].problems != []


def test_the_card_use_case_draws_agents_then_the_gate_then_the_write():
    view = UseCaseView.model_validate(load("cards/use-case.json"))
    assert [b.kind for b in view.plan] == ["agent", "approval", "write_action"]
    assert view.agents[0].values["Jira project"] == "MOCK"
