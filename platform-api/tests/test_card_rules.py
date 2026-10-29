"""The platform's rules for agent cards: where a write lands, who must approve, and which of the
agents' proposals are kept (ADR 0023)."""

import json

import pytest

from platform_api.orchestration import Binding, CardRun, CardSpec, CardsTask
from platform_api.orchestration.agents import CardBlock, CardInput, ProposedIntentIn
from platform_api.orchestration.cards import (
    RULES,
    TOOL_RULES,
    ReviewedCards,
    approvers_needed,
    bind_cards,
    card_bindings,
    cards_policy,
    check_value,
    review_cards,
)
from platform_api.orchestration.watch import Unusable
from platform_api.orchestration.write_actions import UnboundIntent, WriteAction
from tests.support import FIXTURES


def card(card_id: str = "crd_a", name: str = "Version checker", write: bool = True) -> CardSpec:
    blocks = [CardBlock(say="Read.", tool="github.read_releases")]
    if write:
        blocks.append(CardBlock(say="Raise a ticket.", tool="jira.create_ticket"))
    return CardSpec(
        id=card_id,
        version=1,
        name=name,
        purpose="Checks releases.",
        inputs=[
            CardInput(name="Repo", kind="github_repo"),
            CardInput(name="Project", kind="jira_project"),
        ],
        blocks=blocks,
    )


def run_of(spec: CardSpec, project: str = "MOCK") -> CardRun:
    values = {"Repo": "langchain-ai/langgraph", "Project": project}
    return CardRun(spec, values, card_bindings(spec, values))


TASK = CardsTask((run_of(card()),))
GOOD = {"title": "New release 1.2.16", "body": "Details."}


def intent(**changes: object) -> ProposedIntentIn:
    base: dict[str, object] = {
        "kind": "jira.create_ticket",
        "fields": GOOD,
        "reason": "A new release.",
        "subject": "crd_a",
    }
    return ProposedIntentIn.model_validate({**base, **changes})


def test_the_rules_match_the_runtimes_published_tool_list():
    published = FIXTURES / "agent" / "tools.json"
    if not published.exists():
        pytest.skip("the runtime's tools.json arrives with the runtime's branch")
    tools = json.loads(published.read_text())["tools"]
    assert [(t["id"], t["kind"]) for t in tools] == [(r.id, r.kind) for r in TOOL_RULES]


def test_every_write_tool_has_a_target_a_minimum_and_a_connector():
    for rule in TOOL_RULES:
        if rule.kind == "write":
            assert rule.target_input and rule.min_approvers and rule.connector
            assert rule.operation and rule.target_key and rule.action_name
        else:
            assert rule.target_input is None and rule.min_approvers is None


@pytest.mark.parametrize(
    ("kind", "value", "fits"),
    [
        ("github_repo", "langchain-ai/langgraph", True),
        ("github_repo", "langgraph", False),
        ("github_repo", "a/..", False),
        ("jira_project", "MOCK", True),
        ("jira_project", "mock", False),
        ("jira_project", "MOCK\n", False),
        ("jira_project", "ABCDEFGHIJK", False),
        ("jira_project", "1ABC", False),
        ("text", "Quarterly review", True),
        ("text", "two\nlines", False),
        ("text", "", False),
        ("text", "x" * 201, False),
        ("secret", "anything", False),
    ],
)
def test_a_value_must_fit_its_input_kind(kind: str, value: str, fits: bool):
    assert (check_value(kind, value) is None) is fits


def test_a_write_lands_in_the_project_the_card_was_given():
    bindings = card_bindings(card(), {"Repo": "a/b", "Project": "ABC"})
    assert bindings == {"jira.create_ticket": Binding("jira", "create_ticket", {"project": "ABC"})}


def test_a_card_that_only_reads_binds_nothing():
    assert card_bindings(card(write=False), {"Repo": "a/b", "Project": "ABC"}) == {}


def test_a_bad_project_never_reaches_a_binding():
    with pytest.raises(ValueError, match="no valid value"):
        card_bindings(card(), {"Repo": "a/b", "Project": "abc; DROP"})


def test_a_write_without_its_one_target_input_cannot_be_bound():
    spec = card().model_copy(update={"inputs": []})
    with pytest.raises(ValueError, match="exactly one jira_project"):
        card_bindings(spec, {})


@pytest.mark.parametrize(
    ("write", "asked", "steps"),
    [
        (False, 1, ["Team approver"]),
        (True, 0, ["Team approver"]),
        (True, 1, ["Team approver"]),
        (True, 2, ["Team approver", "Second approver"]),
        (True, 9, ["Team approver", "Second approver"]),
    ],
)
def test_the_steps_follow_the_rules_and_the_ask_never_below_the_minimum(
    write: bool, asked: int, steps: list[str]
):
    policy = cards_policy([card(write=write)], asked)
    assert [step.label for step in policy.steps] == steps
    assert approvers_needed([card(write=write)], asked) == len(steps)


def test_the_steps_are_the_most_any_card_needs():
    assert approvers_needed([card("crd_a"), card("crd_b")], 2) == 2
    assert approvers_needed([], 1) == 1


def test_a_proposal_for_a_card_in_the_run_is_kept_with_its_card():
    reviewed = review_cards(TASK, [intent()])
    assert isinstance(reviewed, ReviewedCards)
    [item] = reviewed.intents
    assert (item.card_id, item.intent.kind, dict(item.intent.fields)) == (
        "crd_a",
        "jira.create_ticket",
        GOOD,
    )


def test_no_proposals_is_a_fine_answer():
    assert review_cards(TASK, []) == ReviewedCards(())


@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"subject": None}, "not in this run"),
        ({"subject": "crd_other"}, "not in this run"),
        ({"kind": "jira.search"}, "does not allow"),
        ({"kind": "gitlab.remove_member"}, "does not allow"),
        ({"fields": {"title": "T", "body": "B", "project": "SECRET"}}, "not exactly"),
        ({"fields": {"title": "T"}}, "not exactly"),
        ({"fields": {"title": "T", "body": 5}}, "not text"),
        ({"fields": {"title": " ", "body": ""}}, "title is empty"),
        ({"fields": {"title": "x" * 201, "body": ""}}, "title is empty or longer"),
        ({"fields": {"title": "T", "body": "x" * 5001}}, "body is longer"),
    ],
)
def test_a_proposal_that_does_not_fit_fails_the_whole_run(changes: dict[str, object], words: str):
    result = review_cards(TASK, [intent(**changes)])
    assert isinstance(result, Unusable) and words in result.detail


def test_a_card_cannot_propose_a_write_its_blocks_do_not_use():
    reading = CardsTask((run_of(card(write=False)),))
    result = review_cards(reading, [intent()])
    assert isinstance(result, Unusable) and "does not allow" in result.detail


def test_one_agent_cannot_speak_for_another():
    # crd_b only reads, so a ticket claimed for it is refused even though crd_a may write.
    two = CardsTask((run_of(card("crd_a")), run_of(card("crd_b", "Reader", write=False))))
    assert isinstance(review_cards(two, [intent()]), ReviewedCards)
    assert isinstance(review_cards(two, [intent(subject="crd_b")]), Unusable)


def test_at_most_ten_proposals():
    assert isinstance(review_cards(TASK, [intent()] * 10), ReviewedCards)
    result = review_cards(TASK, [intent()] * 11)
    assert isinstance(result, Unusable) and "10" in result.detail


def test_each_proposal_lands_in_its_own_cards_project_in_the_order_proposed():
    two = CardsTask((run_of(card("crd_a", "Alpha"), "AAA"), run_of(card("crd_b", "Beta"), "BBB")))
    reviewed = review_cards(
        two,
        [intent(subject="crd_b"), intent(subject="crd_a"), intent(subject="crd_b")],
    )
    assert isinstance(reviewed, ReviewedCards)
    actions = bind_cards(two, reviewed)
    assert not isinstance(actions, UnboundIntent)
    assert [a.target for a in actions] == [
        {"project": "BBB"},
        {"project": "AAA"},
        {"project": "BBB"},
    ]
    assert all(isinstance(a, WriteAction) and a.fields == GOOD for a in actions)


def test_the_model_cannot_choose_the_target():
    # Even a field named project is refused, and the binding is the card's value alone.
    refused = review_cards(TASK, [intent(fields={"title": "T", "body": "B", "project": "OTHER"})])
    assert isinstance(refused, Unusable)
    reviewed = review_cards(TASK, [intent()])
    assert isinstance(reviewed, ReviewedCards)
    [action] = bind_cards(TASK, reviewed)  # pyright: ignore[reportGeneralTypeIssues]
    assert action.target == {"project": "MOCK"}


def test_a_proposal_with_no_binding_is_reported():
    unbound = CardsTask((CardRun(card(), {}, {}),))
    reviewed = review_cards(unbound, [intent()])
    assert isinstance(reviewed, ReviewedCards)
    assert bind_cards(unbound, reviewed) == UnboundIntent(("jira.create_ticket",))


def test_the_rule_ids_are_keyed_for_lookup():
    assert set(RULES) == {r.id for r in TOOL_RULES}
