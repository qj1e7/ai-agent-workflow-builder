"""The checks on a card, the starter card, the run line and the values an agent runs with."""

import pytest

from platform_api.builder.cards import (
    RELEASE_CHECKER,
    card_spec,
    check_card,
    check_values,
    library_card,
    plan_for_cards,
    tool_list,
)
from platform_api.builder.models import (
    ApprovalView,
    CardBlock,
    CardDefinition,
    CardInput,
)
from platform_api.orchestration import TOOL_RULES

REPO = CardInput(name="Repo", kind="github_repo", what="", example="a/b")
PROJECT = CardInput(name="Project", kind="jira_project", what="", example="MOCK")


def definition(**changes: object) -> CardDefinition:
    base: dict[str, object] = {
        "name": "Release checker",
        "purpose": "Checks a repository.",
        "good_for": ["Check a repo"],
        "inputs": [REPO, PROJECT],
        "blocks": [
            CardBlock(say="Read releases.", tool="github.read_releases"),
            CardBlock(say="Raise a ticket.", tool="jira.create_ticket"),
        ],
        "approvals": [],
    }
    return CardDefinition.model_validate({**base, **changes})


def problems_of(card: CardDefinition) -> dict[str | None, str]:
    return {p.field: p.message for p in check_card(card).problems}


def test_a_good_card_has_no_problems_and_gets_the_rules_approval():
    checked = check_card(definition())
    assert checked.problems == []
    assert checked.approvals == [ApprovalView(tool="jira.create_ticket", approvers=1)]
    assert checked.card.approvals == checked.approvals


def test_the_starter_card_passes_its_own_check_unchanged():
    definition_of_starter = CardDefinition.model_validate(
        RELEASE_CHECKER.model_dump(
            include={"name", "purpose", "good_for", "inputs", "blocks", "approvals"}
        )
    )
    checked = check_card(definition_of_starter)
    assert checked.problems == []
    assert checked.card == definition_of_starter


def test_the_starter_card_reads_as_the_spec_says():
    assert (RELEASE_CHECKER.card_id, RELEASE_CHECKER.version, RELEASE_CHECKER.starter) == (
        "crd_release_checker",
        1,
        True,
    )
    assert RELEASE_CHECKER.owner == "platform"
    assert [i.kind for i in RELEASE_CHECKER.inputs] == ["github_repo", "jira_project"]
    assert RELEASE_CHECKER.tools == [
        "github.read_releases",
        "jira.search",
        "jira.create_ticket",
    ]
    assert RELEASE_CHECKER.approvals == [ApprovalView(tool="jira.create_ticket", approvers=1)]


@pytest.mark.parametrize("asked", [0, 1, -3])
def test_an_approval_below_the_minimum_is_raised_to_it(asked: int):
    card = definition(approvals=[ApprovalView(tool="jira.create_ticket", approvers=asked)])
    assert check_card(card).approvals == [ApprovalView(tool="jira.create_ticket", approvers=1)]


@pytest.mark.parametrize(("asked", "got"), [(2, 2), (3, 2), (50, 2)])
def test_an_approval_above_two_is_capped(asked: int, got: int):
    card = definition(approvals=[ApprovalView(tool="jira.create_ticket", approvers=asked)])
    checked = check_card(card)
    assert checked.problems == []
    assert checked.approvals == [ApprovalView(tool="jira.create_ticket", approvers=got)]


def test_approvals_for_tools_the_blocks_do_not_use_are_dropped():
    card = definition(
        blocks=[CardBlock(say="Read.", tool="github.read_releases")],
        inputs=[REPO],
        approvals=[
            ApprovalView(tool="jira.create_ticket", approvers=2),
            ApprovalView(tool="gitlab.remove_member", approvers=2),
            ApprovalView(tool="github.read_releases", approvers=2),
        ],
    )
    checked = check_card(card)
    assert checked.problems == [] and checked.approvals == []


def test_the_largest_of_repeated_asks_wins():
    card = definition(
        approvals=[
            ApprovalView(tool="jira.create_ticket", approvers=2),
            ApprovalView(tool="jira.create_ticket", approvers=1),
        ]
    )
    assert check_card(card).approvals == [ApprovalView(tool="jira.create_ticket", approvers=2)]


def test_a_tool_that_is_not_on_the_list_is_a_problem():
    card = definition(blocks=[CardBlock(say="Remove.", tool="gitlab.remove_member")])
    assert "blocks.0.tool" in problems_of(card)


def test_a_write_with_no_input_of_its_target_kind_is_a_problem():
    card = definition(inputs=[REPO])
    assert "jira_project" in problems_of(card)["inputs"]


def test_a_write_with_two_inputs_of_its_target_kind_is_a_problem():
    second = CardInput(name="Other project", kind="jira_project")
    assert "Only one input" in problems_of(definition(inputs=[REPO, PROJECT, second]))["inputs"]


def test_duplicate_input_names_ignore_case():
    card = definition(inputs=[REPO, PROJECT, CardInput(name="repo", kind="text")])
    assert problems_of(card)["inputs.2.name"] == "Two inputs are called repo."


def test_an_unknown_input_kind_is_a_problem():
    card = definition(inputs=[REPO, PROJECT, CardInput(name="Secret", kind="password")])
    assert "inputs.2.kind" in problems_of(card)


def test_no_blocks_is_a_problem():
    assert problems_of(definition(blocks=[], inputs=[]))["blocks"] == "Add at least one block."


@pytest.mark.parametrize(
    "name", ["Flint", "Forge helper", "the Striker", "Spark Map", "spark  map", "SCOUT", "Clerk"]
)
def test_an_old_themed_name_is_a_problem_wherever_it_appears(name: str):
    assert "name" in problems_of(definition(name=name))
    assert "purpose" in problems_of(definition(purpose=f"Works like {name}."))
    blocks = [CardBlock(say=f"Ask {name}.", tool=None)]
    assert "blocks.0.say" in problems_of(definition(blocks=blocks, inputs=[]))


def test_ordinary_words_that_contain_an_old_name_are_fine():
    assert problems_of(definition(name="Forgejo reader")) == {}


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"name": "x"}, "name"),
        ({"name": "x" * 61}, "name"),
        ({"purpose": ""}, "purpose"),
        ({"purpose": "x" * 301}, "purpose"),
        ({"good_for": ["x"] * 6}, "good_for"),
        ({"good_for": ["x" * 101]}, "good_for.0"),
        ({"blocks": [CardBlock(say="x" * 301, tool=None)], "inputs": []}, "blocks.0.say"),
        ({"blocks": [CardBlock(say="", tool=None)], "inputs": []}, "blocks.0.say"),
        ({"blocks": [CardBlock(say="x", tool=None)] * 13, "inputs": []}, "blocks"),
        (
            {"inputs": [CardInput(name="n", kind="text")] * 9, "blocks": [CardBlock(say="x")]},
            "inputs",
        ),
        (
            {
                "inputs": [CardInput(name="n", kind="text", what="x" * 201)],
                "blocks": [CardBlock(say="x")],
            },
            "inputs.0.what",
        ),
        (
            {
                "inputs": [CardInput(name="n", kind="text", example="x" * 101)],
                "blocks": [CardBlock(say="x")],
            },
            "inputs.0.example",
        ),
        (
            {"inputs": [CardInput(name="", kind="text")], "blocks": [CardBlock(say="x")]},
            "inputs.0.name",
        ),
    ],
)
def test_length_limits_are_problems(changes: dict[str, object], field: str):
    assert field in problems_of(definition(**changes))


def test_text_is_cleaned_to_one_line_and_an_empty_tool_means_no_tool():
    card = definition(
        name="  Release \n checker ",
        blocks=[CardBlock(say=" Read\n the   releases. ", tool=" ")],
        inputs=[],
    )
    checked = check_card(card)
    assert checked.problems == []
    assert checked.card.name == "Release checker"
    assert checked.card.blocks == [CardBlock(say="Read the releases.", tool=None)]


def test_the_tool_list_has_every_rule_in_order_with_its_target_and_minimum():
    tools = tool_list().tools
    assert [t.id for t in tools] == [r.id for r in TOOL_RULES]
    write = next(t for t in tools if t.id == "jira.create_ticket")
    assert (write.kind, write.target_input, write.min_approvers) == ("write", "jira_project", 1)
    read = next(t for t in tools if t.id == "jira.search")
    assert (read.kind, read.target_input, read.min_approvers) == ("read", None, None)


def test_a_card_reads_as_the_runtimes_spec_and_the_librarys_summary():
    spec = card_spec(RELEASE_CHECKER)
    assert (spec.id, spec.version, spec.name) == ("crd_release_checker", 1, "Release checker")
    assert [b.tool for b in spec.blocks] == [
        "github.read_releases",
        "jira.search",
        "jira.create_ticket",
    ]
    summary = library_card(RELEASE_CHECKER)
    assert summary.card_id == "crd_release_checker"
    assert [(i.name, i.kind) for i in summary.inputs] == [
        ("GitHub repository", "github_repo"),
        ("Jira project", "jira_project"),
    ]
    assert summary.tools == RELEASE_CHECKER.tools


def test_the_run_line_has_an_agent_block_each_then_the_gate_and_one_block_per_write():
    plan = plan_for_cards([RELEASE_CHECKER])
    assert [(b.kind, b.key, b.name) for b in plan] == [
        ("agent", "crd_release_checker", "Release checker"),
        ("approval", "approval_gate", "Approval gate"),
        ("write_action", "jira_create_ticket", "Create Jira tickets"),
    ]
    assert plan[0].description == RELEASE_CHECKER.purpose


def test_two_agents_that_both_write_still_have_one_gate_and_one_write_block():
    other = RELEASE_CHECKER.model_copy(update={"card_id": "crd_two", "name": "Second"})
    plan = plan_for_cards([RELEASE_CHECKER, other])
    assert [b.kind for b in plan] == ["agent", "agent", "approval", "write_action"]


def test_agents_that_only_read_have_no_gate():
    reading = RELEASE_CHECKER.model_copy(update={"tools": ["github.read_releases"]})
    assert [b.kind for b in plan_for_cards([reading])] == ["agent"]


def test_values_are_trimmed_and_checked_by_kind():
    clean, errors = check_values(
        RELEASE_CHECKER,
        {"GitHub repository": " langchain-ai/langgraph ", "Jira project": "MOCK"},
    )
    assert errors == []
    assert clean == {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}


def test_values_that_are_wrong_missing_or_unknown_are_each_reported():
    clean, errors = check_values(
        RELEASE_CHECKER, {"GitHub repository": "not a repo", "Surprise": "x"}
    )
    assert clean == {}
    by_name = dict(errors)
    assert set(by_name) == {"GitHub repository", "Jira project", "Surprise"}
    assert by_name["Surprise"] == "This agent has no such input."
    assert by_name["Jira project"].startswith("Required.")
    assert "owner/name" in by_name["GitHub repository"]


def test_a_project_key_that_is_not_one_never_gets_through():
    _, errors = check_values(
        RELEASE_CHECKER, {"GitHub repository": "a/b", "Jira project": "MOCK-1; x"}
    )
    assert [name for name, _ in errors] == ["Jira project"]


@pytest.mark.parametrize("tool", ["jira.search", "jira.read_ticket"])
def test_a_jira_read_needs_one_jira_project_input_to_limit_it(tool: str):
    reading = definition(blocks=[CardBlock(say="Look.", tool=tool)])
    assert problems_of(reading.model_copy(update={"inputs": [REPO]}))["inputs"].endswith(
        "so the agent knows which project it may read. Add one."
    )
    assert (
        "Only one input"
        in problems_of(
            reading.model_copy(
                update={"inputs": [PROJECT, CardInput(name="P2", kind="jira_project")]}
            )
        )["inputs"]
    )
    assert problems_of(reading.model_copy(update={"inputs": [PROJECT]})) == {}


def test_reads_and_writes_share_the_one_jira_project_input():
    blocks = [
        CardBlock(say="Look.", tool="jira.search"),
        CardBlock(say="Raise.", tool="jira.create_ticket"),
    ]
    assert problems_of(definition(blocks=blocks, inputs=[PROJECT])) == {}
    problem = problems_of(definition(blocks=blocks, inputs=[]))["inputs"]
    assert "Search Jira, Create a Jira ticket" in problem
