"""A drafted agent never stops at "The new agent has a problem. Change your words to fix it."
when changing the words can't fix it. Code repairs what it safely can, and says plainly what is
left: a part no tool does yet, the two projects the words name, or a draft to try again. Only a
word the person wrote, such as an old themed name, is theirs to change."""

from datetime import UTC, datetime
from typing import Any

import pytest

from platform_api.builder.cards import (
    BLOCK_COUNT,
    INPUT_COUNT,
    NAME_LIMIT,
    PURPOSE_LIMIT,
    SAY_LIMIT,
    card_spec,
    card_view,
    check_card,
)
from platform_api.builder.draft_repair import (
    NEW_AGENT_NAME,
    one_project_input,
    one_project_only,
    projects_named,
)
from platform_api.builder.models import CannotDo, ModelTrouble, NewAgent, PlanOut
from platform_api.builder.planning import (
    MISSING_COUNT,
    PROBLEM_WORDS,
    NoModelConnected,
    RuntimeNotAnswering,
    plan,
)
from platform_api.orchestration import cards_policy
from platform_api.orchestration.agents import DraftApproval, DraftBlock, DraftInput, MissingTool
from platform_api.shared import UserId
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
    task: str = TASK, known: tuple[str, ...] = (), **changes: Any
) -> PlanOut | NoModelConnected | RuntimeNotAnswering:
    """The plan for a draft with the changes, its steps Carol's two Jira steps by default, for a
    team whose Jira allows the known projects."""
    changes.setdefault("blocks", [SEARCH, RAISE])
    planner = FakePlanner(chose=chosen("new_agent"), drafted=draft(**changes))
    return await plan(planner, LIBRARY, task, known)


def inputs_of(result: PlanOut | NoModelConnected | RuntimeNotAnswering) -> list[tuple[str, str]]:
    assert isinstance(result, NewAgent), result
    assert result.problems == []
    return [(i.name, i.kind) for i in result.draft.inputs]


# Two Jira project inputs, and two projects in the words


TWO = [DraftInput(name="From", kind="jira_project"), DraftInput(name="To", kind="jira_project")]


async def test_two_jira_project_inputs_become_one_when_the_words_name_one_project():
    """An agent reads and writes in one project, and the Portal fills every project input with
    the one the words name, so two inputs only asked the same thing twice."""
    assert inputs_of(await planned(TASK, inputs=TWO)) == [(PROJECT, "jira_project")]


async def test_two_jira_project_inputs_are_never_joined_when_the_words_name_no_project():
    """Which of two projects is the target is the person's choice, so it is never picked, and
    the two are never decided to be one (#309)."""
    result = await planned("x", inputs=TWO)
    assert result == CannotDo(reason=one_project_input(["From", "To"]), missing_tools=[])


TWO_PROJECTS = [
    "Find tickets in MOCK. Raise one ticket that lists them. Where it goes: Jira project OPS.",
    "In MOCK, find the stale tickets. Project OPS gets one ticket that lists them.",
    "Find stale tickets from MOCK and raise one ticket into OPS that lists them",
    "Copy stale tickets from MOCK to OPS",
    "Find the MOCK tickets nobody updated and raise one OPS ticket that lists them",
    "Find stale tickets in projects MOCK and OPS",
    "Find stale tickets in MOCK-14 and raise one ticket in OPS",
    "Find stale tickets in project mock and raise one ticket in project ops",
    "Read https://jira.example.com/browse/MOCK-12 and raise one ticket in OPS",
    "Read https://jira.example.com/projects/mock/issues and raise one ticket in OPS",
]


@pytest.mark.parametrize("task", TWO_PROJECTS)
@pytest.mark.parametrize(
    "inputs",
    [
        TWO,
        [DraftInput(name="Jira project", kind="jira_project")],
        [
            DraftInput(name="Jira project", kind="text", what="Where to search"),
            DraftInput(name="Project", kind="text", what="Where the ticket goes"),
        ],
        [],
    ],
    ids=["two project inputs", "one project input", "two text inputs named for it", "none"],
)
async def test_two_projects_in_the_words_say_which_two_whatever_the_inputs(
    task: str, inputs: list[DraftInput]
):
    """Before, two text inputs named for the project, one input, or wording such as "from MOCK
    to OPS" went through as one project, and the Portal filled the first, MOCK."""
    result = await planned(task, inputs=inputs)
    assert result == CannotDo(reason=one_project_only(["MOCK", "OPS"]), missing_tools=[])
    assert "your words name MOCK and OPS" in one_project_only(["MOCK", "OPS"])


async def test_a_project_the_team_allows_counts_in_small_letters():
    result = await planned(
        "find stale tickets in mock and raise one in ops", ("MOCK", "OPS"), inputs=TWO
    )
    assert result == CannotDo(reason=one_project_only(["MOCK", "OPS"]), missing_tools=[])


@pytest.mark.parametrize(
    ("task", "named"),
    [
        ("Every Friday at 16:00 in SGT, find stale tickets in MOCK", ["MOCK"]),
        ("Find tickets in MOCK, raise one in MOCK, report in PDF", ["MOCK"]),
        ("Find ALL the stale tickets in MOCK, ASAP", ["MOCK"]),
        ("Find the stale tickets in Jira and raise one", []),
        ("x", []),
        ("Find tickets in MOCK with status DONE and raise one ticket", ["MOCK"]),
        ("Find tickets in MOCK with status IN PROGRESS and raise one ticket", ["MOCK"]),
        ("For each CVE in the list, raise one ticket in MOCK", ["MOCK"]),
        ("Fix CVE-2024-3094 and raise one ticket in MOCK", ["MOCK"]),
        ("For each EOL software and each new LTS release, raise one ticket in MOCK", ["MOCK"]),
        ("Raise a BUG in MOCK", ["MOCK"]),
        ("NOTE: raise one ticket in MOCK for the SRE team", ["MOCK"]),
        ("Raise one ticket in MOCK about the CODESparks NPS survey", ["MOCK"]),
        ("RAISE ONE TICKET IN MOCK", ["MOCK"]),
        ("Read HTTPS://JIRA.NCS.COM.SG/browse/MOCK-1 and raise one", ["MOCK"]),
        ("Find tickets in MOCK moved to DONE this week", ["MOCK"]),
    ],
)
def test_words_in_capitals_that_name_no_project_are_not_read_as_one(task: str, named: list[str]):
    """Before, DONE, PROGRESS, CVE, EOL, LTS, BUG, NOTE, SRE and NPS were read as projects, so
    these were told they named two. A capital word is a project only where it stands as one."""
    assert projects_named(task, ("MOCK",)) == named


@pytest.mark.parametrize(
    ("task", "named"),
    [
        ("Find stale tickets in IT and raise one ticket in MOCK", ["IT", "MOCK"]),
        ("Find stale tickets in HR, raise one in QA", ["HR", "QA"]),
        ("find stale tickets in mock and raise one in project ops", ["MOCK", "OPS"]),
        ("Raise it in MOCK", ["MOCK"]),
    ],
)
def test_a_key_where_a_project_stands_is_read_even_a_short_or_small_one(
    task: str, named: list[str]
):
    """Before, IT, HR and QA were on the list of words that name no project, so "in IT ... in
    MOCK" read as one project and the Portal filled IT."""
    assert projects_named(task, ("MOCK", "IT")) == named
    assert projects_named(task, ("MOCK",)) == named


NOT_TO_FILL = [
    "Raise a ticket in the Jira project for each new LangGraph release",
    "Find the closed tickets and raise one ticket with the project status",
    "Raise one ticket for each project update",
    "Find tickets about project management and raise one",
    "Find stale tickets and send the list to HR",
    "Find tickets closed in Q4 and raise one ticket that lists them",
    "Find tickets in UAT and raise one ticket",
    "Raise a ticket for each service deployed to PROD",
    "Find the DEV tickets and raise one",
    "Escalate stale tickets to L2 and raise one",
    "Find HIGH issues and raise one ticket",
    "Raise a ticket for each server still on PHP-7",
    "Raise a ticket for each server still on RHEL-7",
    "Raise a ticket for each repo listed at https://example.com/projects/langgraph",
    "find stale tickets in mock and raise one in ops",
    "Find tickets from Bob and raise one in MOCK",
    "Raise a ticket in Jira for each new release",
    "Raise a ticket into the backlog",
]


@pytest.mark.parametrize("task", NOT_TO_FILL)
async def test_the_project_input_is_never_filled_with_words_that_name_no_project_of_the_team(
    task: str,
):
    """The input decides where the ticket is written. Before, it was filled with FOR, STATUS,
    UPDATE, MANAGEMENT, HR, Q4, PROD, L2, HIGH, PHP, RHEL or LANGGRAPH, or with MOCK while "in
    ops" was dropped. Now it is filled only with a project the team's Jira allows, and the
    Portal asks otherwise, or the card names two projects."""
    result = await planned(task, ("MOCK",))
    assert isinstance(result, CannotDo) or (isinstance(result, NewAgent) and result.project is None)


@pytest.mark.parametrize(
    ("task", "project"),
    [
        ("every Monday at 9am raise tickets in MOCK", "MOCK"),
        (TASK, "MOCK"),
        ("Find tickets in MOCK, and email the list to me", "MOCK"),
        ("Raise a ticket in the MOCK project", "MOCK"),
        ("Find tickets in MOCK closed in Q4", "MOCK"),
    ],
)
async def test_a_project_the_team_allows_is_filled(task: str, project: str):
    result = await planned(task, ("MOCK",))
    assert isinstance(result, NewAgent) and result.project == project


@pytest.mark.parametrize(
    ("task", "project"),
    [
        ("Raise a ticket in OPS", "OPS"),
        ("Find tickets in project OPS and raise one", "OPS"),
        ("Raise a ticket in the Jira project for each new LangGraph release", None),
        ("Find stale tickets and send the list to HR", None),
        ("Find tickets closed in Q4 and raise one ticket", None),
        ("Find the DEV tickets and raise one", None),
    ],
)
async def test_with_no_team_list_only_a_capital_key_after_project_or_in_is_filled(
    task: str, project: str | None
):
    result = await planned(task)
    assert isinstance(result, NewAgent) and result.project == project


async def test_the_one_project_the_words_name_comes_with_the_plan_for_the_portal_to_fill():
    """The Portal fills the project input from this key, so the builder and the Portal read the
    words the same way."""
    result = await planned(TASK)
    assert isinstance(result, NewAgent) and result.project == "MOCK"
    assert isinstance(none := await planned("x"), NewAgent) and none.project is None


async def test_a_card_that_uses_no_jira_tool_never_counts_projects():
    blocks = [DraftBlock(say="Read the releases.", tool="github.read_releases")]
    result = await planned("Check MOCK and OPS releases", inputs=[], blocks=blocks)
    assert isinstance(result, NewAgent) and result.problems == []


# Approvals


async def test_a_write_written_another_way_keeps_the_approvers_asked_for_and_its_two_yeses():
    """Before, "Jira.Create_Ticket" with two approvers came back as jira.create_ticket with one,
    and the run asked only one Approver in Teams."""
    result = await planned(
        blocks=[SEARCH, DraftBlock(say="Raise one ticket.", tool="Jira.Create_Ticket")],
        approvals=[DraftApproval(tool="Jira.Create_Ticket", approvers=2)],
    )
    assert isinstance(result, NewAgent) and result.problems == []
    assert [(a.tool, a.approvers) for a in result.approvals] == [("jira.create_ticket", 2)]
    saved = card_view(
        card_id="crd_x",
        version=1,
        starter=False,
        owner=UserId("alice"),
        created_at=datetime(2026, 11, 18, tzinfo=UTC),
        definition=result.draft,
    )
    asked = max(a.approvers for a in saved.approvals)
    assert len(cards_policy([card_spec(saved)], asked).steps) == 2


@pytest.mark.parametrize(
    "approvals",
    [
        [DraftApproval(tool="create_ticket", approvers=2)],
        [
            DraftApproval(tool="jira.create_ticket", approvers=1),
            DraftApproval(tool="Jira.Create_Ticket", approvers=2),
        ],
    ],
    ids=["an approval for no tool", "two approvals for one tool"],
)
async def test_approvals_that_cant_be_read_for_sure_ask_to_try_again(
    approvals: list[DraftApproval],
):
    """Never a lower count than the model asked for: a fresh draft instead."""
    result = await planned(approvals=approvals)
    assert result == ModelTrouble(message=PROBLEM_WORDS["unusable_answer"])


async def test_an_approval_for_a_step_set_aside_goes_with_it():
    post = DraftBlock(say="Post the list in Teams.", tool="teams.post_message")
    result = await planned(
        blocks=[SEARCH, post, RAISE],
        approvals=[DraftApproval(tool="teams.post_message", approvers=1)],
    )
    assert isinstance(result, NewAgent) and result.problems == []
    assert [m.need for m in result.missing_tools] == ["Post the list in Teams"]


@pytest.mark.parametrize("tool", ["jira.create_ticket2", "1jira2search3", "jira.\u017fearch"])
async def test_a_tool_id_with_other_digits_or_letters_is_no_tool(tool: str):
    result = await planned(blocks=[SEARCH, DraftBlock(say="Do the thing.", tool=tool)])
    assert isinstance(result, NewAgent) and result.problems == []
    assert [b.tool for b in result.draft.blocks] == ["jira.search"]
    assert [m.need for m in result.missing_tools] == ["Do the thing"]


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
        ("jira_user", "text"),
        ("jira_issue_key", "text"),
        ("jira_status", "text"),
        ("report_format", "text"),
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


@pytest.mark.parametrize(
    ("kind", "name"), [("jira_user", "Assignee"), ("jira_issue_key", "Ticket key")]
)
async def test_a_jira_kind_that_is_no_project_stays_beside_the_project_as_text(
    kind: str, name: str
):
    """Before, it became the input a write goes to, so "bob" under Assignee was project BOB, or
    it was joined into the project input without a word."""
    read = DraftBlock(say="Read the ticket.", tool="jira.read_ticket")
    alone = await planned(inputs=[DraftInput(name=name, kind=kind)], blocks=[read, RAISE])
    assert inputs_of(alone) == [(name, "text"), (PROJECT, "jira_project")]
    beside = [DraftInput(name=PROJECT, kind="jira_project"), DraftInput(name=name, kind=kind)]
    assert inputs_of(await planned(inputs=beside, blocks=[read, RAISE])) == [
        (PROJECT, "jira_project"),
        (name, "text"),
    ]


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


async def test_every_step_set_aside_is_named_beside_the_models_own_list():
    """Before, the list was cut at five, so a step set aside could go untold."""
    five = [MissingTool(need=f"Need {n}", why="x") for n in range(5)]
    post = DraftBlock(say="Post the list in Teams.", tool="teams.post_message")
    result = await planned(blocks=[SEARCH, post, RAISE], missing_tools=five)
    assert isinstance(result, NewAgent)
    assert [m.need for m in result.missing_tools] == [
        "Post the list in Teams",
        *[f"Need {n}" for n in range(MISSING_COUNT - 1)],
        "and 1 more",
    ]
    six = [DraftBlock(say=f"Step {n}.", tool=f"x.tool{n}") for n in range(6)]
    result = await planned(blocks=[SEARCH, *six])
    assert isinstance(result, NewAgent)
    assert [m.need for m in result.missing_tools] == [f"Step {n}" for n in range(6)]


async def test_a_step_with_no_words_and_no_tool_we_have_is_told_in_plain_words():
    result = await planned(blocks=[SEARCH, DraftBlock(say="", tool="teams.post"), RAISE])
    assert isinstance(result, NewAgent)
    assert [m.need for m in result.missing_tools] == ['A step with no words, for "teams.post"']


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
