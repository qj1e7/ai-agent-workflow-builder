"""Code's scope check of a fix (ADR 0055, sections 3 and 4). It denies by default: a draft may
change only the parameters of the blocks the coordinator named, and nothing there may touch what
a block does, where it reaches, a key, a setting or a yes. The eval has one red-team case for each
widening (test_eval_fix.py). These pin each way code finds one."""

from typing import Any

import pytest

from agent_runtime.contract import PlanBlock, PlanSetting, PlanWire, WorkflowPlan
from agent_runtime.fixing.events import FixWidening
from agent_runtime.fixing.ports import Inside, Widened
from agent_runtime.fixing.scope import PlanScope, scope_of
from agent_runtime.monitoring.masking import KEPT_KEY

READ = "Read new releases"
PROPOSE = "Propose a ticket"
YES = "Ask for a yes"
RELEASES = "https://api.github.com/repos/langchain-ai/langgraph/releases"


def _block(name: str, node_type: str, **parameters: Any) -> PlanBlock:
    return PlanBlock(name=name, type=node_type, version=1, parameters=parameters)


def _wire(source: str, target: str, exit_index: int = 0) -> PlanWire:
    return PlanWire(
        from_block=source, exit="main", to_block=target, exit_index=exit_index, input_index=0
    )


SETTING = PlanSetting.model_validate(
    {
        "id": "jira_project",
        "kind": "jira_project",
        "label": "The Jira project",
        "fills": [{"block": PROPOSE, "parameter": "place"}],
        "value": "MOCK",
        "mark": "filled",
    }
)
STOPPED = WorkflowPlan(
    name="LangGraph release check",
    blocks=[
        _block("Every Monday", "n8n-nodes-base.scheduleTrigger", rule="monday 09:00"),
        _block(READ, "n8n-nodes-base.httpRequest", method="GET", url=RELEASES),
        _block(
            PROPOSE,
            "CUSTOM.wabProposeChange",
            action="jira.create_ticket",
            place="<<jira_project>>",
        ),
        _block(YES, "CUSTOM.wabAskForYes"),
        _block("Make the ticket", "CUSTOM.wabMakeApprovedChanges"),
    ],
    wires=[
        _wire("Every Monday", READ),
        _wire(READ, PROPOSE),
        _wire(PROPOSE, YES),
        _wire(YES, "Make the ticket", 1),
    ],
    settings=[SETTING],
)


def fixed(
    name: str = READ, *, node_type: str | None = None, version: float = 1, **parameters: Any
) -> WorkflowPlan:
    """The stopped plan with one block's parameters changed, a key set to None removed."""
    blocks: list[PlanBlock] = []
    for block in STOPPED.blocks:
        if block.name == name:
            merged = {**block.parameters, **parameters}
            block = block.model_copy(
                update={
                    "type": node_type or block.type,
                    "version": version,
                    "parameters": {k: v for k, v in merged.items() if v is not None},
                }
            )
        blocks.append(block)
    return STOPPED.model_copy(update={"blocks": blocks})


def widened(plan: WorkflowPlan, change_only: tuple[str, ...] = (READ,)) -> FixWidening | None:
    found = scope_of(STOPPED, plan, change_only)
    return found.by if isinstance(found, Widened) else None


def key_like() -> str:
    """A made-up key in a known shape, built here so no key is ever written in the repository."""
    return "ghp_" + "Zq7" * 12


def test_a_draft_that_changes_nothing_stays_inside_and_changes_nothing():
    assert PlanScope().check(STOPPED, STOPPED, [READ]) == Inside(())


def test_a_new_path_on_the_same_host_is_a_small_fix():
    renamed = fixed(url=RELEASES.replace("langgraph", "langgraph-py"))
    assert scope_of(STOPPED, renamed, (READ,)) == Inside((READ,))


def test_an_expression_that_reads_a_moved_field_is_a_small_fix():
    moved = fixed(PROPOSE, title="={{ 'New release ' + $json.release.tag }}")
    assert scope_of(STOPPED, moved, (PROPOSE,)) == Inside((PROPOSE,))


@pytest.mark.parametrize(
    "plan",
    [
        fixed(node_type="CUSTOM.wabMakeApprovedChanges"),
        fixed(method="POST"),
        fixed(version=4.2),
        fixed(PROPOSE, action="jira.close_ticket"),
        fixed(operation="create"),
    ],
    ids=["type", "method", "version", "action", "operation"],
)
def test_a_change_to_what_a_block_does_adds_a_write(plan: WorkflowPlan):
    assert widened(plan, (READ, PROPOSE)) == "adds_a_write"


@pytest.mark.parametrize(
    "plan",
    [
        fixed(url="https://collector.example.net/langgraph/releases"),
        fixed(url="={{ $json.where }}"),
        fixed(options={"proxy": "http://relay.example.org:8080"}),
        fixed(PROPOSE, source="jira_tickets"),
        fixed(PROPOSE, where="email"),
    ],
    ids=["another host", "an expression", "a new host anywhere", "source", "where"],
)
def test_a_change_that_reaches_another_system_adds_a_system(plan: WorkflowPlan):
    assert widened(plan, (READ, PROPOSE)) == "adds_a_system"


@pytest.mark.parametrize(
    "plan",
    [
        fixed(authentication="predefinedCredentialType", nodeCredentialType="githubApi"),
        fixed(headerParameters={"parameters": [{"name": "X-Api-Key", "value": "={{ $json.k }}"}]}),
        fixed(queryParameters={"parameters": [{"name": "access_token", "value": "abc"}]}),
        fixed(password="hunter" + "2"),
        fixed(body=f"token {key_like()}"),
        fixed(url=RELEASES.replace("https://", "https://bot:pa55@")),
        fixed(url=RELEASES + "?api_key=abc"),
    ],
    ids=[
        "picks a key",
        "a header named as a key",
        "a query parameter named as a key",
        "a parameter named as a key",
        "a key's shape",
        "a name and password in the address",
        "a key in the address",
    ],
)
def test_a_parameter_that_adds_a_credential_adds_a_key(plan: WorkflowPlan):
    assert widened(plan) == "adds_a_key"


def test_a_draft_that_moves_or_drops_a_key_the_platform_kept_out_touches_a_key():
    kept = fixed(headerParameters={"parameters": [{"name": "Authorization", "value": KEPT_KEY}]})
    moved = kept.model_copy(
        update={
            "blocks": [
                b.model_copy(update={"parameters": {**b.parameters, "headerParameters": {}}})
                if b.name == READ
                else b
                for b in kept.blocks
            ]
        }
    )
    assert scope_of(kept, kept, (READ,)) == Inside(())
    found = scope_of(kept, moved, (READ,))
    assert isinstance(found, Widened) and found.by == "adds_a_key"


@pytest.mark.parametrize(
    ("parameters", "by"),
    [
        ({"onError": "continueRegularOutput"}, "goes_past_a_failure"),
        ({"continueOnFail": True}, "goes_past_a_failure"),
        ({"alwaysOutputData": True}, "goes_past_a_failure"),
        ({"disabled": True}, "goes_past_a_failure"),
        ({"onError": "stopWorkflow"}, None),
    ],
)
def test_what_lets_a_block_go_past_its_failure_widens(parameters: dict[str, Any], by: str | None):
    assert widened(fixed(**parameters)) == by


def test_a_setting_a_person_filled_stays_as_it_was():
    other_value = STOPPED.model_copy(
        update={"settings": [SETTING.model_copy(update={"value": "MOCK2"})]}
    )
    written_over = fixed(PROPOSE, place="MOCK2")
    added = STOPPED.model_copy(
        update={"settings": [SETTING, SETTING.model_copy(update={"id": "another"})]}
    )
    for plan in (other_value, written_over, added):
        assert widened(plan, (PROPOSE,)) == "changes_a_persons_setting"


def test_a_change_outside_the_blocks_named_widens_even_inside_the_failed_part():
    assert widened(fixed(PROPOSE, title="New"), (READ,)) == "outside_failed_part"


@pytest.mark.parametrize(
    "plan",
    [
        STOPPED.model_copy(update={"name": "Another name"}),
        STOPPED.model_copy(update={"blocks": STOPPED.blocks[:-1]}),
        STOPPED.model_copy(update={"wires": STOPPED.wires[1:]}),
    ],
    ids=["the name", "a block gone", "a wire gone"],
)
def test_anything_else_that_changes_is_outside(plan: WorkflowPlan):
    assert widened(plan) == "outside_failed_part"


def test_a_yes_stays_as_it_was_and_where_it_was():
    no_yes = STOPPED.model_copy(update={"blocks": [b for b in STOPPED.blocks if b.name != YES]})
    not_a_yes = fixed(YES, node_type="n8n-nodes-base.noOp")
    rewired = STOPPED.model_copy(
        update={"wires": [*STOPPED.wires[:2], _wire(PROPOSE, "Make the ticket")]}
    )
    weakened = fixed(YES, approvers="anyone")
    assert widened(no_yes) == "removes_a_yes"
    assert widened(not_a_yes, (YES,)) == "removes_a_yes"
    assert widened(rewired) == "moves_a_yes"
    assert widened(weakened, (YES,)) == "moves_a_yes"


def test_a_new_block_widens():
    more = STOPPED.model_copy(
        update={"blocks": [*STOPPED.blocks, _block("Tell the team", "CUSTOM.wabTell")]}
    )
    assert widened(more) == "adds_a_block"
