"""A drafted agent never stops at "The new agent has a problem. Change your words to fix it."
when changing the words can't fix it. Code repairs what it safely can, and says plainly what is
left: a part no tool does yet, the two projects the words name, or a draft to try again. Only a
word the person wrote, such as an old themed name, is theirs to change."""

from typing import Any

import pytest

from platform_api.builder.cards import (
    BLOCK_COUNT,
    INPUT_COUNT,
    NAME_LIMIT,
    PURPOSE_LIMIT,
    SAY_LIMIT,
    check_card,
)
from platform_api.builder.draft_repair import NEW_AGENT_NAME, one_project_only
from platform_api.builder.models import CannotDo, ModelTrouble, NewAgent, PlanOut
from platform_api.builder.planning import (
    PROBLEM_WORDS,
    NoModelConnected,
    RuntimeNotAnswering,
    plan,
)
from platform_api.orchestration.agents import DraftBlock, DraftInput
from tests.test_card_planning import LIBRARY, FakePlanner, chosen, draft

pytestmark = pytest.mark.anyio

PROJECT = "Jira project"
SEARCH = DraftBlock(say="Find the tickets nobody updated for 14 days.", tool="jira.search")
RAISE = DraftBlock(say="Raise one ticket that lists them.", tool="jira.create_ticket")
TASK = (
    "Find Jira tickets in project MOCK that nobody updated for 14 days. Raise one ticket that "
    "lists them. Where it goes: Jira project MOCK."
)


async def planned(
    task: str = TASK, **changes: Any
) -> PlanOut | NoModelConnected | RuntimeNotAnswering:
    """The plan for a draft with the changes, its steps Carol's two Jira steps by default."""
    changes.setdefault("blocks", [SEARCH, RAISE])
    return await plan(
        FakePlanner(chose=chosen("new_agent"), drafted=draft(**changes)), LIBRARY, task
    )


def inputs_of(result: PlanOut | NoModelConnected | RuntimeNotAnswering) -> list[tuple[str, str]]:
    assert isinstance(result, NewAgent), result
    assert result.problems == []
    return [(i.name, i.kind) for i in result.draft.inputs]


# Two Jira project inputs


@pytest.mark.parametrize("task", [TASK, "x"])
async def test_two_jira_project_inputs_become_one_when_the_words_name_one_project_or_none(
    task: str,
):
    """An agent reads and writes in one project, and the Portal fills every project input with
    the one the words name, so two inputs only asked the same thing twice."""
    two = [DraftInput(name="From", kind="jira_project"), DraftInput(name="To", kind="jira_project")]
    assert inputs_of(await planned(task, inputs=two)) == [(PROJECT, "jira_project")]


async def test_two_jira_project_inputs_for_two_named_projects_say_which_two():
    two = [DraftInput(name="From", kind="jira_project"), DraftInput(name="To", kind="jira_project")]
    task = (
        "Find tickets in MOCK. Raise one ticket that lists them. Where it goes: Jira project OPS."
    )
    result = await planned(task, inputs=two)
    assert result == CannotDo(reason=one_project_only(["MOCK", "OPS"]), missing_tools=[])
    assert "your words name MOCK and OPS" in one_project_only(["MOCK", "OPS"])


# Words that are only labels


async def test_a_long_name_is_cut_at_a_word():
    result = await planned(name="Stale ticket lister " * 6)
    assert isinstance(result, NewAgent) and result.problems == []
    assert len(result.draft.name) <= NAME_LIMIT and result.draft.name.endswith("lister…")


@pytest.mark.parametrize("name", ["", " ", "A"])
async def test_a_draft_with_no_name_is_called_new_agent(name: str):
    result = await planned(name=name)
    assert isinstance(result, NewAgent) and result.problems == []
    assert result.draft.name == NEW_AGENT_NAME


@pytest.mark.parametrize(
    ("name", "kept"), [("Forge reporter", "Reporter"), ("Scout", NEW_AGENT_NAME)]
)
async def test_an_old_name_the_model_gave_the_agent_is_left_out_of_its_name(name: str, kept: str):
    result = await planned(name=name)
    assert isinstance(result, NewAgent) and result.problems == []
    assert result.draft.name == kept


async def test_a_long_purpose_is_cut_and_an_empty_one_is_the_name():
    long = await planned(purpose="Lists the stale tickets. " * 20)
    assert isinstance(long, NewAgent) and long.problems == []
    assert len(long.draft.purpose) <= PURPOSE_LIMIT
    empty = await planned(purpose=" ")
    assert isinstance(empty, NewAgent) and empty.problems == []
    assert empty.draft.purpose == empty.draft.name


async def test_too_many_long_or_themed_examples_are_left_out():
    examples = ["List stale tickets " * 8, "Ask the Analyst", *[f"Example {n}" for n in range(6)]]
    result = await planned(good_for=examples)
    assert isinstance(result, NewAgent) and result.problems == []
    assert result.draft.good_for == [f"Example {n}" for n in range(5)]


@pytest.mark.parametrize(
    ("given", "kind"),
    [
        ("jira_key", "jira_project"),
        ("Jira Project Key", "jira_project"),
        ("repository", "github_repo"),
        ("number", "text"),
        ("", "text"),
    ],
)
async def test_an_input_kind_the_platform_does_not_have_is_one_it_has(given: str, kind: str):
    item = DraftInput(name="Thing", kind=given)
    blocks = [DraftBlock(say="Read the releases.", tool="github.read_releases")]
    assert inputs_of(await planned(inputs=[item], blocks=blocks)) == [("Thing", kind)]


async def test_an_input_with_no_name_long_words_or_a_long_example_is_tidied():
    item = DraftInput(name=" ", kind="github_repo", what="The repository. " * 20, example="x" * 101)
    blocks = [DraftBlock(say="Read the releases.", tool="github.read_releases")]
    result = await planned(inputs=[item], blocks=blocks)
    assert isinstance(result, NewAgent) and result.problems == []
    [kept] = result.draft.inputs
    assert (kept.name, kept.example) == ("GitHub repository", "")
    assert len(kept.what) <= 200


@pytest.mark.parametrize("second", ["text", "github_repo"])
async def test_two_inputs_with_one_name_are_one(second: str):
    """The Jira project input the tools need is the one kept."""
    two = [DraftInput(name="Board", kind=second), DraftInput(name="board", kind="jira_project")]
    assert inputs_of(await planned(inputs=two)) == [("board", "jira_project")]


async def test_two_text_inputs_with_one_name_are_one():
    two = [DraftInput(name="Label", kind="text"), DraftInput(name="Label", kind="text")]
    assert inputs_of(await planned(inputs=two)) == [("Label", "text"), (PROJECT, "jira_project")]


# Steps


async def test_a_step_with_a_tool_the_platform_does_not_have_comes_back_as_left_out():
    """The person sees which part no tool does yet, as when the model lists it itself."""
    post = DraftBlock(say="Post the list in Teams.", tool="teams.post_message")
    result = await planned(blocks=[SEARCH, post, RAISE])
    assert isinstance(result, NewAgent) and result.problems == []
    assert [b.tool for b in result.draft.blocks] == ["jira.search", "jira.create_ticket"]
    assert [m.need for m in result.missing_tools] == ["Post the list in Teams"]


async def test_a_draft_whose_every_step_needs_a_missing_tool_is_a_cant_naming_them():
    remove = DraftBlock(say="Remove the member from GitLab.", tool="gitlab.remove_member")
    result = await planned(blocks=[remove], inputs=[])
    assert isinstance(result, CannotDo)
    assert [m.need for m in result.missing_tools] == ["Remove the member from GitLab"]


@pytest.mark.parametrize("tool", ["Jira.Search", "jira_search", " jira.search "])
async def test_a_tool_id_written_another_way_is_the_tool(tool: str):
    result = await planned(blocks=[DraftBlock(say="Find them.", tool=tool)])
    assert isinstance(result, NewAgent) and result.problems == []
    assert [b.tool for b in result.draft.blocks] == ["jira.search"]


async def test_a_step_with_no_words_says_its_tool_or_is_left_out():
    blocks = [DraftBlock(say=" ", tool="jira.search"), DraftBlock(say="", tool=None), RAISE]
    result = await planned(blocks=blocks)
    assert isinstance(result, NewAgent) and result.problems == []
    assert [(b.say, b.tool) for b in result.draft.blocks] == [
        ("Search Jira.", "jira.search"),
        (RAISE.say, "jira.create_ticket"),
    ]


UNUSABLE = ModelTrouble(message=PROBLEM_WORDS["unusable_answer"])


@pytest.mark.parametrize(
    "changes",
    [
        {"blocks": []},
        {"blocks": [SEARCH] * (BLOCK_COUNT + 1)},
        {"blocks": [DraftBlock(say="Find " * 80, tool="jira.search")]},
        {"inputs": [DraftInput(name=f"Detail {n}", kind="text") for n in range(INPUT_COUNT + 1)]},
        {"blocks": [DraftBlock(say="Ask the Fixer to look.", tool="jira.search")]},
    ],
    ids=["no steps", "too many steps", "a long step", "too many inputs", "a themed step"],
)
async def test_a_draft_only_the_model_can_fix_asks_to_try_again(changes: dict[str, Any]):
    """Cutting a step would change what the agent does, so code never does. A fresh draft is
    the way on, and the card's Try again asks for one."""
    assert await planned(**changes) == UNUSABLE


async def test_an_old_name_the_person_wrote_is_theirs_to_change_and_named():
    task = "Find the tickets the Analyst team raised in MOCK and raise one ticket that lists them"
    step = DraftBlock(say="Find the tickets the Analyst team raised.", tool="jira.search")
    result = await planned(task, blocks=[step, RAISE])
    assert isinstance(result, NewAgent)
    assert [p.message for p in result.problems] == [
        "Analyst is an old name that confused the sponsor. Use plain words."
    ]


async def test_every_card_the_repair_gives_passes_the_check():
    result = await planned(
        name="",
        purpose="",
        inputs=[DraftInput(name="Jira project", kind="text"), DraftInput(name="", kind="number")],
        blocks=[DraftBlock(say="", tool="Jira.Search"), RAISE],
    )
    assert isinstance(result, NewAgent) and result.problems == []
    assert check_card(result.draft).problems == []
    assert max(len(b.say) for b in result.draft.blocks) <= SAY_LIMIT
