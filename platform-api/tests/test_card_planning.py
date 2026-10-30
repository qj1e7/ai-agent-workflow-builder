"""The Planner's plan, with a fake planner standing in for the model."""

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from platform_api.builder.cards import VERSION_CHECKER
from platform_api.builder.models import (
    CannotDo,
    ModelTrouble,
    NewAgent,
    Starters,
    UnderstoodRows,
    UseSaved,
    WatchlistRedirect,
)
from platform_api.builder.planning import (
    FALLBACK_WORDS,
    FOLLOW_UP_TASK,
    PROBLEM_WORDS,
    STARTERS,
    UNDERSTAND_LIMIT_SECONDS,
    FallbackWhy,
    NoModelConnected,
    RuntimeNotAnswering,
    plan,
    understand,
)
from platform_api.orchestration import (
    BelongsOnWatchlist,
    CardDraft,
    Choice,
    ChooseResult,
    Chosen,
    ChosenAgent,
    Drafted,
    DraftResult,
    LibraryCard,
    ModelProblem,
    NoModel,
    RuntimeDown,
    UnderstandResult,
    Understood,
    UnderstoodRow,
)
from platform_api.orchestration.agents import DraftApproval, DraftBlock, DraftInput, MissingTool

pytestmark = pytest.mark.anyio

LIBRARY = [VERSION_CHECKER]
REPO = "GitHub repository"
PROJECT = "Jira project"


@dataclass
class FakePlanner:
    chose: ChooseResult | NoModel | RuntimeDown = field(
        default_factory=lambda: Chosen(choice=Choice(decision="cannot_do", reason="No."))
    )
    drafted: DraftResult | NoModel | RuntimeDown | None = None
    asked: list[Sequence[LibraryCard]] = field(default_factory=lambda: [])
    drafts: int = 0

    async def has_model(self) -> bool:
        return True

    async def choose(self, task: str, library: Sequence[LibraryCard]):
        self.asked.append(library)
        return self.chose

    async def draft(self, task: str):
        self.drafts += 1
        assert self.drafted is not None
        return self.drafted


def chosen(decision: str, *agents: ChosenAgent, reason: str = "Because.", **more: object):
    return Chosen(
        choice=Choice.model_validate(
            {"decision": decision, "agents": list(agents), "reason": reason, **more}
        )
    )


def agent(card_id: str = "crd_version_checker", **values: str) -> ChosenAgent:
    return ChosenAgent(card_id=card_id, part="Check it.", values=values)


def draft(**changes: object) -> Drafted:
    base: dict[str, object] = {
        "can_do": True,
        "name": "Weekly summary",
        "purpose": "Summarises the week.",
        "good_for": ["Every Friday summarise"],
        "inputs": [DraftInput(name="Project", kind="jira_project", example="MOCK")],
        "blocks": [DraftBlock(say="Search.", tool="jira.search")],
        "approvals": [],
    }
    return Drafted(draft=CardDraft.model_validate({**base, **changes}))


async def test_the_library_is_sent_as_summaries():
    planner = FakePlanner()
    await plan(planner, LIBRARY, "check langgraph")
    [sent] = planner.asked
    assert [c.card_id for c in sent] == ["crd_version_checker"]
    assert sent[0].tools == ["github.read_releases", "jira.search", "jira.create_ticket"]


async def test_one_saved_agent_with_values_from_the_task():
    planner = FakePlanner(
        chose=chosen("use_one", agent(**{REPO: "langchain-ai/langgraph", PROJECT: "MOCK"}))
    )
    result = await plan(planner, LIBRARY, "check langgraph")
    assert isinstance(result, UseSaved)
    assert result.decision == "use_one"
    [planned] = result.agents
    assert planned.card.card_id == "crd_version_checker"
    assert planned.values == {REPO: "langchain-ai/langgraph", PROJECT: "MOCK"}
    assert planned.missing == []
    assert planner.drafts == 0


async def test_a_value_that_does_not_fit_its_kind_is_dropped_and_listed_as_missing():
    planner = FakePlanner(
        chose=chosen("use_one", agent(**{REPO: "langchain-ai/langgraph", PROJECT: "the mock one"}))
    )
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, UseSaved)
    [planned] = result.agents
    assert planned.values == {REPO: "langchain-ai/langgraph"}
    assert planned.missing == [PROJECT]


async def test_values_for_inputs_the_card_does_not_have_are_ignored():
    planner = FakePlanner(chose=chosen("use_one", agent(**{"Target": "SECRET", PROJECT: "MOCK"})))
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, UseSaved)
    assert result.agents[0].values == {PROJECT: "MOCK"}
    assert result.agents[0].missing == [REPO]


async def test_agents_not_in_the_library_are_dropped_and_a_repeat_is_kept_once():
    planner = FakePlanner(
        chose=chosen("use_several", agent("crd_made_up"), agent(), agent(), reason="Two parts.")
    )
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, UseSaved)
    assert [a.card.card_id for a in result.agents] == ["crd_version_checker"]
    assert result.decision == "use_one"


async def test_no_real_agent_left_means_a_new_agent_is_drafted():
    planner = FakePlanner(chose=chosen("use_one", agent("crd_made_up")), drafted=draft())
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, NewAgent)
    assert planner.drafts == 1


async def test_at_most_three_agents():
    cards = [VERSION_CHECKER.model_copy(update={"card_id": f"crd_{n}"}) for n in range(5)]
    planner = FakePlanner(chose=chosen("use_several", *[agent(c.card_id) for c in cards]))
    result = await plan(planner, cards, "x")
    assert isinstance(result, UseSaved)
    assert len(result.agents) == 3 and result.decision == "use_several"


async def test_a_new_agent_comes_back_checked_and_never_saved():
    planner = FakePlanner(
        chose=chosen("new_agent", reason="Nothing fits.", questions=["Which project?"]),
        drafted=draft(
            blocks=[DraftBlock(say="Raise it.", tool="jira.create_ticket")],
            approvals=[DraftApproval(tool="jira.create_ticket", approvers=2, why="Be careful.")],
            questions=["Which project?", "Which day?"],
            missing_tools=[MissingTool(need="Teams", why="To post the summary.")],
        ),
    )
    result = await plan(planner, LIBRARY, "every Friday summarise")
    assert isinstance(result, NewAgent)
    assert result.problems == []
    assert [(a.tool, a.approvers) for a in result.approvals] == [("jira.create_ticket", 2)]
    assert result.draft.approvals == result.approvals
    assert result.reason == "Nothing fits."
    assert result.questions == ["Which project?", "Which day?"]
    assert [m.need for m in result.missing_tools] == ["Teams"]


async def test_a_draft_with_problems_comes_back_with_them_listed():
    planner = FakePlanner(
        chose=chosen("new_agent"),
        drafted=draft(
            name="Forge",
            blocks=[DraftBlock(say="Remove.", tool="gitlab.remove_member")],
            inputs=[],
        ),
    )
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, NewAgent)
    assert {p.field for p in result.problems} == {"name", "blocks.0.tool"}


async def test_a_draft_that_writes_without_a_target_input_is_flagged_not_fixed():
    planner = FakePlanner(
        chose=chosen("new_agent"),
        drafted=draft(blocks=[DraftBlock(say="Raise it.", tool="jira.create_ticket")], inputs=[]),
    )
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, NewAgent)
    assert [p.field for p in result.problems] == ["inputs"]


async def test_a_draft_that_cannot_be_done_is_a_refusal_with_the_missing_tools():
    planner = FakePlanner(
        chose=chosen("new_agent"),
        drafted=draft(
            can_do=False,
            why_not="It needs Confluence.",
            missing_tools=[MissingTool(need="Confluence", why="To edit the page.")],
        ),
    )
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, CannotDo)
    assert result.reason == "It needs Confluence."
    assert [m.need for m in result.missing_tools] == ["Confluence"]


async def test_the_planner_can_refuse_without_a_draft():
    planner = FakePlanner(chose=chosen("cannot_do", reason="Too risky to automate."))
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, CannotDo) and result.reason == "Too risky to automate."
    assert planner.drafts == 0


@pytest.mark.parametrize("reason", sorted(PROBLEM_WORDS))
async def test_a_model_problem_is_told_in_the_platforms_own_words(reason: str):
    problem = ModelProblem.model_validate(
        {"reason": reason, "message": "The provider said: sk-secret-key rejected"}
    )
    result = await plan(FakePlanner(chose=problem), LIBRARY, "x")
    assert isinstance(result, ModelTrouble)
    assert result.message == PROBLEM_WORDS[reason]
    assert "sk-" not in result.message


async def test_a_model_problem_while_drafting_is_told_too():
    problem = ModelProblem(reason="too_slow", message="slow")
    planner = FakePlanner(chose=chosen("new_agent"), drafted=problem)
    result = await plan(planner, LIBRARY, "x")
    assert result == ModelTrouble(message=PROBLEM_WORDS["too_slow"])


async def test_no_model_and_a_runtime_that_is_down_are_not_plans():
    assert isinstance(await plan(FakePlanner(chose=NoModel()), LIBRARY, "x"), NoModelConnected)
    assert isinstance(
        await plan(FakePlanner(chose=RuntimeDown("refused")), LIBRARY, "x"), RuntimeNotAnswering
    )
    down = FakePlanner(chose=chosen("new_agent"), drafted=RuntimeDown("refused"))
    assert isinstance(await plan(down, LIBRARY, "x"), RuntimeNotAnswering)
    gone = FakePlanner(chose=chosen("new_agent"), drafted=NoModel())
    assert isinstance(await plan(gone, LIBRARY, "x"), NoModelConnected)


async def test_the_models_long_text_is_cut_and_its_questions_trimmed():
    long = "word " * 400
    planner = FakePlanner(
        chose=chosen("cannot_do", reason=long, questions=["Q"] * 8 + [long]),
    )
    result = await plan(planner, LIBRARY, "x")
    assert isinstance(result, CannotDo) and len(result.reason) <= 500


ROWS = Understood(
    rows=[
        UnderstoodRow(kind="schedule", text="Every weekday at 3pm", state="understood"),
        UnderstoodRow(kind="look_for", text="Bug tickets in MOCK", state="understood"),
        UnderstoodRow(kind="do", text="Close every ticket", state="cant_do", note="No tool."),
        UnderstoodRow(kind="where", text="Jira project MOCK", state="understood"),
    ]
)


@dataclass
class FakeReader:
    answer: UnderstandResult | NoModel | RuntimeDown = field(default_factory=lambda: ROWS)
    wait: float = 0.0
    asked: list[str] = field(default_factory=lambda: [])

    async def understand(self, task: str) -> UnderstandResult | NoModel | RuntimeDown:
        self.asked.append(task)
        await asyncio.sleep(self.wait)
        return self.answer


async def test_the_planners_rows_are_shown_as_it_read_them():
    reader = FakeReader()
    result = await understand(reader, "the task")
    assert reader.asked == ["the task"]
    assert isinstance(result, UnderstoodRows)
    assert [(r.kind, r.state, r.note) for r in result.rows] == [
        ("schedule", "understood", None),
        ("look_for", "understood", None),
        ("do", "cant_do", "No tool."),
        ("where", "understood", None),
    ]


async def test_a_release_task_belongs_on_the_software_watchlist_naming_the_word():
    result = await understand(FakeReader(BelongsOnWatchlist(word="release")), "x")
    assert isinstance(result, WatchlistRedirect)
    assert (result.word, result.software) == ("release", None)
    assert "You mentioned “release”" in result.note
    assert "belongs on the Software watchlist" in result.note


@pytest.mark.parametrize(
    ("answer", "why", "logged"),
    [
        (NoModel(), "no_model", "no AI model is connected"),
        (RuntimeDown("The agent runtime answered 502"), "trouble", "answered 502"),
        (ModelProblem(reason="unusable_answer", message="x"), "trouble", "unusable_answer"),
        (ModelProblem(reason="too_slow", message="x"), "too_slow", "too_slow"),
    ],
)
async def test_without_a_usable_answer_the_starters_show_and_the_reason_is_logged(
    answer: UnderstandResult | NoModel | RuntimeDown,
    why: FallbackWhy,
    logged: str,
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.WARNING):
        result = await understand(FakeReader(answer), "x")
    assert result == Starters(message=FALLBACK_WORDS[why], starters=list(STARTERS))
    assert "fell back to the starter workflows" in caplog.text and logged in caplog.text


async def test_an_answer_slower_than_the_limit_shows_the_starters_in_time(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    assert UNDERSTAND_LIMIT_SECONDS == 10
    monkeypatch.setattr("platform_api.builder.planning.UNDERSTAND_LIMIT_SECONDS", 0.05)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        result = await understand(FakeReader(wait=5), "x")
    assert time.monotonic() - started < 1
    assert isinstance(result, Starters) and result.message == FALLBACK_WORDS["too_slow"]
    assert "no answer within 0.05 seconds" in caplog.text


class SettingsUnreadable:
    async def understand(self, task: str) -> UnderstandResult | NoModel | RuntimeDown:
        raise ConnectionError("the database is down")


async def test_a_failure_reading_the_model_settings_is_raised_not_shown_as_starters():
    with pytest.raises(ConnectionError):
        await understand(SettingsUnreadable(), "x")


def test_the_starters_are_the_prototypes_three_phrased_with_the_jira_tools_we_have():
    assert [(s.name, s.opens) for s in STARTERS] == [
        ("Keep our software up to date", "software_watchlist"),
        ("Weekly summary of closed tickets", None),
        ("Follow up stale bug tickets", None),
    ]
    assert STARTERS[0].task is None
    assert STARTERS[2].task == FOLLOW_UP_TASK
    for starter in STARTERS[1:]:
        assert starter.task and "MOCK" in starter.task and "ticket" in starter.task
        assert not any(word in starter.task for word in ("Teams", "Confluence", "email"))
