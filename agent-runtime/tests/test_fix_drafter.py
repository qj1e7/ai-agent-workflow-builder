"""The Fix drafter (ADR 0055, PR 4): ADR 0051's drafter, given the stopped version as the current
plan and asked to change only the blocks named, behind the coordinator's draft_fix port. A
recorded model plays the drafter, so no model is called. CI mounts contracts/ into the test image,
where it is /contracts."""

import json
from pathlib import Path
from typing import Any

import pytest
from evals.fix import (
    FIX,
    STARTED,
    Clock,
    Fakes,
    RecordedCall,
    RecordedChat,
    RecordedTurn,
    prices,
    request_of,
)
from langchain_core.messages import HumanMessage

from agent_runtime.catalogue import Catalogue, load
from agent_runtime.contract import (
    CauseFound,
    DrafterFacts,
    ModelAccess,
    WorkflowDraftRequest,
    WorkflowPlan,
)
from agent_runtime.fixing.coordinator import HandedBack, HandedIn, coordinating
from agent_runtime.fixing.drafter import WORDS, ModelFixDrafter, fix_ask
from agent_runtime.fixing.ports import FixDraftRequest, ScenarioResult
from agent_runtime.monitoring.masking import KEPT_KEY
from agent_runtime.workflow_drafter import TURN_TIMEOUT_SECONDS, check_plan
from agent_runtime.workflow_plan import ProposedPlan

CATALOGUE = Path(__file__).resolve().parents[2] / "contracts" / "n8n" / "catalogue.json"
FACTS = DrafterFacts(jira_projects=["MOCK"], repositories=["langchain-ai/langgraph"])
ACCESS = ModelAccess(
    style="anthropic", base_url="https://llm.example", model="claude-sonnet-5-5", api_key="unused"
)
READ = "Read new releases"
PROPOSE = "Propose a ticket"
YES = "Ask for a yes"
OLD_TITLE = "={{ 'New release ' + $json.tag_name }}"
NEW_TITLE = "={{ 'New release ' + $json.release.tag }}"
CASE = next(case for case in FIX.cases() if case.id == "fixable-a-field-that-moved")

type Json = dict[str, Any]


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load(CATALOGUE)


def _block(name: str, node_type: str, version: float, **parameters: object) -> Json:
    parameters_text = json.dumps(parameters)
    return {"name": name, "type": node_type, "version": version, "parameters": parameters_text}


def _wire(source: str, target: str, exit_name: str = "main") -> Json:
    return {"from_block": source, "exit": exit_name, "to_block": target, "input": None}


def proposed(title: str = OLD_TITLE, add: list[Json] | None = None) -> Json:
    """The release check as the drafter submits it, the title reading the tag where it was."""
    return {
        "name": "LangGraph release check",
        "blocks": [
            _block("Every Monday", "n8n-nodes-base.scheduleTrigger", 1.4, rule="<<run_time>>"),
            _block(READ, "CUSTOM.wabRead", 1, source="github_releases", place="<<repository>>"),
            _block(
                PROPOSE,
                "CUSTOM.wabProposeChange",
                1,
                action="jira.create_ticket",
                place="<<jira_project>>",
                title=title,
            ),
            _block(YES, "CUSTOM.wabAskForYes", 1),
            _block("Make the ticket", "CUSTOM.wabMakeApprovedChanges", 1),
            *(add or []),
        ],
        "wires": [
            _wire("Every Monday", READ),
            _wire(READ, PROPOSE),
            _wire(PROPOSE, YES),
            _wire(YES, "Make the ticket", "Yes"),
        ],
        "settings": [
            {"id": "run_time", "kind": "run_time", "label": "When it runs", "value": None},
            {
                "id": "repository",
                "kind": "repository",
                "label": "The repository",
                "value": "langchain-ai/langgraph",
            },
            {"id": "jira_project", "kind": "jira_project", "label": "The project", "value": None},
        ],
    }


@pytest.fixture(scope="module")
def stopped(catalogue: Catalogue) -> WorkflowPlan:
    """The version that ran, as the drafter planned it and code checked and marked it."""
    asked = WorkflowDraftRequest(
        words="Every Monday at 9am, check langchain-ai/langgraph and propose a ticket in MOCK.",
        facts=FACTS,
        model=ACCESS,
    )
    plan = check_plan(ProposedPlan.model_validate(proposed()), catalogue, asked)
    assert isinstance(plan, WorkflowPlan), plan
    assert {s.id: s.mark for s in plan.settings} == {
        "run_time": "filled",
        "repository": "filled",
        "jira_project": "filled",
    }
    return plan


def submits(plan: Json) -> RecordedTurn:
    return RecordedTurn(calls=[RecordedCall(name="submit_plan", args=plan)])


def asked_of(stopped: WorkflowPlan, round_: int = 1) -> FixDraftRequest:
    failed = (ScenarioResult(name="Two new releases", verdict="failed", step=PROPOSE, why="empty"),)
    return FixDraftRequest(
        stopped=stopped,
        cause=CauseFound(
            failed_part=[PROPOSE], system=None, failure_kind="changed_field", detail="tag_name"
        ),
        change_only=(PROPOSE,),
        failed=failed if round_ > 1 else (),
        round=round_,
    )


def drafter(catalogue: Catalogue, chat: RecordedChat, asked: list[float] | None = None):
    def chat_for(timeout: float) -> RecordedChat:
        if asked is not None:
            asked.append(timeout)
        return chat

    return ModelFixDrafter(chat_for, catalogue, FACTS, ACCESS)


def test_it_returns_the_plan_code_checked_with_only_the_block_named_changed(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    chat = RecordedChat(turns=[submits(proposed(NEW_TITLE))])
    plan = drafter(catalogue, chat).draft(asked_of(stopped), 100.0, lambda: 1.0)
    assert isinstance(plan, WorkflowPlan)
    title = {b.name: b.parameters.get("title") for b in plan.blocks}[PROPOSE]
    assert title == NEW_TITLE
    assert plan.settings == stopped.settings


def test_it_reads_the_stopped_version_the_blocks_the_cause_and_the_failed_scenarios(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    chat = RecordedChat(turns=[submits(proposed(NEW_TITLE))])
    drafter(catalogue, chat).draft(asked_of(stopped, 2), 100.0, lambda: 1.0)
    [first, *_] = chat.seen
    asked = first[-1]
    assert isinstance(asked, HumanMessage)
    assert asked.content == fix_ask(asked_of(stopped, 2), FACTS)
    text = str(asked.content)
    assert stopped.model_dump_json() in text
    assert f'["{PROPOSE}"]' in text
    assert '"failure_kind":"changed_field","detail":"tag_name"' in text
    assert '"name":"Two new releases","step":"Propose a ticket","why":"empty"' in text
    assert "The person's words" not in text and WORDS not in text


def test_a_plan_that_never_passes_the_catalogue_check_is_not_in_the_catalogue(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    made_up = proposed(NEW_TITLE, add=[_block("Mail it", "n8n-nodes-base.noSuchBlock", 1)])
    chat = RecordedChat(turns=[submits(made_up)] * 4)
    assert drafter(catalogue, chat).draft(asked_of(stopped), 100.0, lambda: 1.0) == (
        "not_in_catalogue"
    )


def test_a_drafter_with_no_tool_call_gives_no_answer(catalogue: Catalogue, stopped: WorkflowPlan):
    chat = RecordedChat(turns=[RecordedTurn(text="I can't.")])
    assert drafter(catalogue, chat).draft(asked_of(stopped), 100.0, lambda: 1.0) == "no_answer"


def test_it_stops_before_a_turn_once_the_cost_cap_is_spent(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    chat = RecordedChat(turns=[submits(proposed(NEW_TITLE))])
    assert drafter(catalogue, chat).draft(asked_of(stopped), 100.0, lambda: 0.0) == "no_answer"
    assert chat.seen == []


def test_it_waits_for_the_model_no_longer_than_the_seconds_left(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    timeouts: list[float] = []
    chat = RecordedChat(turns=[submits(proposed(NEW_TITLE))])
    drafter(catalogue, chat, timeouts).draft(asked_of(stopped), 12.5, lambda: 1.0)
    late = RecordedChat(turns=[submits(proposed(NEW_TITLE))])
    assert drafter(catalogue, late, timeouts).draft(asked_of(stopped), 0.0, lambda: 1.0) == (
        "no_answer"
    )
    assert timeouts == [12.5, 0.0]
    assert late.seen == []
    assert TURN_TIMEOUT_SECONDS > 12.5


def test_a_key_the_platform_kept_out_stays_where_it_stood(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    blocks = [
        b.model_copy(update={"parameters": {**b.parameters, "body": KEPT_KEY}})
        if b.name == PROPOSE
        else b
        for b in stopped.blocks
    ]
    kept = stopped.model_copy(update={"blocks": blocks})
    asked = asked_of(kept)
    assert KEPT_KEY in fix_ask(asked, FACTS)


def test_a_stopped_version_shaped_like_a_key_is_never_read(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    key = "ghp_" + "Zq7" * 12
    blocks = [
        b.model_copy(update={"parameters": {**b.parameters, "body": key}})
        if b.name == PROPOSE
        else b
        for b in stopped.blocks
    ]
    chat = RecordedChat(turns=[submits(proposed(NEW_TITLE))])
    leaked = asked_of(stopped.model_copy(update={"blocks": blocks}))
    assert drafter(catalogue, chat).draft(leaked, 100.0, lambda: 1.0) == "no_answer"
    assert chat.seen == []


def plugged(catalogue: Catalogue, stopped: WorkflowPlan, *turns: RecordedTurn):
    """The coordinator with the real Fix drafter and code's scope check, the other parts the
    eval's fakes, on the case where a field the workflow reads moved."""
    clock = Clock(STARTED)
    fakes = Fakes(CASE, clock)
    fakes.simulation.stopped = stopped
    drafted = RecordedChat(turns=list(turns))
    parts = fakes.parts()
    parts = type(parts)(**{**parts.__dict__, "drafter": drafter(catalogue, drafted)})
    request = request_of(CASE).model_copy(update={"version": stopped})
    coordinated = RecordedChat(turns=list(CASE.replies), clock=clock)
    fixing = coordinating(request, lambda _t: coordinated, parts, prices(), clock)
    return fixing, fakes, drafted


def test_plugged_into_the_coordinator_a_field_that_moved_is_fixed_and_handed_in(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    fixing, fakes, drafted = plugged(catalogue, stopped, submits(proposed(NEW_TITLE)))
    outcome = fixing.outcome
    assert isinstance(outcome, HandedIn), outcome
    assert fakes.revisions.stored == [outcome.plan]
    title = {b.name: b.parameters.get("title") for b in outcome.plan.blocks}[PROPOSE]
    assert title == NEW_TITLE
    assert [r.changed for r in outcome.rounds] == [(PROPOSE,)]
    assert fixing.cost.calls == len(CASE.replies) + len(drafted.seen)


def test_plugged_into_the_coordinator_a_draft_that_changes_a_setting_is_handed_back(
    catalogue: Catalogue, stopped: WorkflowPlan
):
    renamed = proposed(NEW_TITLE)
    renamed["blocks"][1] = _block(
        READ, "CUSTOM.wabRead", 1, source="github_releases", place="<<renamed>>"
    )
    renamed["settings"][1] = {
        "id": "renamed",
        "kind": "repository",
        "label": "The repository",
        "value": "langchain-ai/langgraph-py",
    }
    fixing, fakes, _ = plugged(catalogue, stopped, submits(renamed))
    outcome = fixing.outcome
    assert isinstance(outcome, HandedBack) and outcome.why == "widened"
    assert [r.widened_by for r in outcome.rounds] == ["changes_a_persons_setting"]
    assert fakes.revisions.stored == []
