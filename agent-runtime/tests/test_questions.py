from typing import Any, cast

import pytest

from agent_runtime.answers import TaskRead, answer_task
from agent_runtime.contract import (
    AbilitiesAnswer,
    Answered,
    AnswerRequest,
    ModelProblem,
    NeedsYouFact,
    PlannerFacts,
    QuestionAnswer,
    SetupCardAnswer,
    WatchedFact,
    WorkflowFact,
)
from agent_runtime.contracts import answer_request
from agent_runtime.questions import COULD_NOT_ANSWER, QUESTION_SYSTEM, QuestionReply
from tests.fakes import ScriptedChat
from tests.test_answers import follow_up

QUESTION = "how many software are on our watchlist"
WATCHED = [
    WatchedFact(name=name, repo=repo, our_version=ours, newest_version=newest, state=state)
    for name, repo, ours, newest, state in (
        ("LangGraph", "langchain-ai/langgraph", "1.2.14", "1.2.16", "New version"),
        ("Redis", "redis/redis", "8.0.2", "8.0.2", "Up to date"),
        ("n8n", "n8n-io/n8n", None, "2.42.6", "Not checked yet"),
    )
]
FACTS = PlannerFacts(watchlist=WATCHED)


def reading(about: str = "my_data") -> TaskRead:
    return TaskRead.model_validate({"skips_the_yes": {"whose": "nobody"}, "asks_about": about})


def ask(
    reply: QuestionReply | Exception,
    facts: PlannerFacts | None = FACTS,
    task: str = QUESTION,
    first: TaskRead | None = None,
) -> tuple[Any, ScriptedChat]:
    chat = ScriptedChat(structured=[first or reading(), reply])
    request = AnswerRequest(task=task, model=answer_request().model, facts=facts)
    return answer_task(request, lambda timeout: chat), chat


def test_a_question_about_the_persons_data_is_answered_from_the_facts_in_the_models_words():
    reply = QuestionReply(text="Three: LangGraph, Redis and n8n.", used=["watchlist"])
    result, chat = ask(reply)
    assert result == Answered(
        answer=QuestionAnswer(text="Three: LangGraph, Redis and n8n.", looked_at=["watchlist"])
    )
    assert chat.asked == [TaskRead, QuestionReply]
    assert chat.calls[1][0] == ("system", QUESTION_SYSTEM)
    user = cast(tuple[str, str], chat.calls[1][1])[1]
    assert user.startswith('The facts:\n{"watchlist":[{"name":"LangGraph"')
    assert user.endswith(f"The question:\n{QUESTION}")


def test_only_the_sections_that_were_sent_are_kept_as_looked_at():
    reply = QuestionReply(text="Three.", used=["workflows", "watchlist", "needs_you"])
    result, _ = ask(reply)
    assert result.answer.looked_at == ["watchlist"]


def test_sections_are_listed_in_the_order_the_facts_hold_them():
    facts = PlannerFacts(
        watchlist=WATCHED,
        workflows=[WorkflowFact(name="Weekly", state="on", last_run=None, last_run_at=None)],
        needs_you=NeedsYouFact(
            approvals=1, confirmations=0, stopped=0, connections=0, addresses=0, replies=0, total=1
        ),
    )
    reply = QuestionReply(text="One thing needs you.", used=["needs_you", "watchlist"])
    result, _ = ask(reply, facts)
    assert result.answer.looked_at == ["watchlist", "needs_you"]


def test_no_facts_gives_the_fixed_text_and_the_model_is_not_asked_again():
    result, chat = ask(QuestionReply(text="Three."), facts=None)
    assert result == Answered(answer=QuestionAnswer(text=COULD_NOT_ANSWER, looked_at=[]))
    assert len(chat.calls) == 1
    result, _ = ask(QuestionReply(text="Three."), facts=PlannerFacts())
    assert result.answer.text == COULD_NOT_ANSWER


@pytest.mark.parametrize(
    "text",
    [
        "Three. I can set up a check for you.",
        "Three. I'll add Redis too.",
        "Three. Want me to watch them?",
        "Three. Let me set that up.",
        "Three. I will tell you when one is behind.",
        "x" * 601,
        "   ",
    ],
)
def test_a_reply_that_offers_to_act_or_runs_long_gets_the_fixed_text(text: str):
    result, _ = ask(QuestionReply(text=text, used=["watchlist"]))
    assert result.answer == QuestionAnswer(text=COULD_NOT_ANSWER, looked_at=[])


def test_a_plain_cant_is_not_an_offer():
    reply = QuestionReply(text="I can't see Postgres on the watchlist.", used=["watchlist"])
    result, _ = ask(reply)
    assert result.answer.text == "I can't see Postgres on the watchlist."


def test_a_problem_with_the_second_call_passes_through():
    slow = type("ReadTimeout", (Exception,), {})("took too long")
    result, _ = ask(slow)
    assert isinstance(result, ModelProblem) and result.reason == "too_slow"


def test_a_reading_that_is_not_my_data_never_asks_the_second_question():
    result, chat = ask(QuestionReply(text="Three."), first=reading("abilities"))
    assert result == Answered(answer=AbilitiesAnswer())
    assert len(chat.calls) == 1


def test_a_my_data_reading_that_also_reads_as_a_task_stays_a_task():
    task = "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days"
    first = follow_up().model_copy(update={"asks_about": "my_data"})
    result, chat = ask(QuestionReply(text="Three."), task=task, first=first)
    assert isinstance(result.answer, SetupCardAnswer)
    assert len(chat.calls) == 1


def test_the_prompt_forbids_offers_and_guessing():
    lowered = QUESTION_SYSTEM.lower()
    for rule in (
        "only from the facts",
        "never say what the platform can or will do",
        "never guess",
    ):
        assert rule in lowered
