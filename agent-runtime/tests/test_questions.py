from typing import Any, cast

import pytest

from agent_runtime.answers import AskTheQuestionLane, TaskRead, answer_task, decide
from agent_runtime.contract import (
    AbilitiesAnswer,
    Answered,
    AnswerRequest,
    NeedsYouFact,
    PlannerFacts,
    QuestionAnswer,
    SetupCardAnswer,
    WatchedFact,
    WatchlistAnswer,
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


def reading(about: str = "abilities", **fields: Any) -> TaskRead:
    return TaskRead.model_validate(
        {"skips_the_yes": {"whose": "nobody"}, "asks_about": about, **fields}
    )


def watch_reading(software: str | None) -> TaskRead:
    return reading("none", belongs_on_watchlist=True, watchlist_word="version", software=software)


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
    reply = QuestionReply(about_their_data=True, text="Three: LangGraph, Redis and n8n.")
    result, chat = ask(reply)
    assert result == Answered(
        answer=QuestionAnswer(text="Three: LangGraph, Redis and n8n.", looked_at=["watchlist"])
    )
    assert chat.asked == [TaskRead, QuestionReply]
    assert chat.calls[1][0] == ("system", QUESTION_SYSTEM)
    user = cast(tuple[str, str], chat.calls[1][1])[1]
    assert user.startswith('The facts:\n{"watchlist":[{"name":"LangGraph"')
    assert user.endswith(f"The question:\n{QUESTION}")


def test_looked_at_is_the_sections_that_were_sent_whatever_the_model_says():
    result, _ = ask(QuestionReply(about_their_data=True, text="Three."))
    assert result.answer.looked_at == ["watchlist"]


def test_sections_are_listed_in_the_order_the_facts_hold_them():
    facts = PlannerFacts(
        watchlist=WATCHED,
        workflows=[WorkflowFact(name="Weekly", state="on", last_run=None, last_run_at=None)],
        needs_you=NeedsYouFact(
            approvals=1, confirmations=0, stopped=0, connections=0, addresses=0, replies=0, total=1
        ),
    )
    reply = QuestionReply(about_their_data=True, text="One thing needs you.")
    result, _ = ask(reply, facts)
    assert result.answer.looked_at == ["watchlist", "workflows", "needs_you"]


def test_no_facts_means_no_lane_so_the_fixed_answer_stands_and_the_model_is_asked_once():
    reply = QuestionReply(about_their_data=True, text="Three.")
    for facts in (None, PlannerFacts()):
        result, chat = ask(reply, facts=facts)
        assert result == Answered(answer=AbilitiesAnswer())
        assert len(chat.calls) == 1


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
    result, _ = ask(QuestionReply(about_their_data=True, text=text))
    assert result.answer == QuestionAnswer(text=COULD_NOT_ANSWER, looked_at=[])


def test_a_plain_cant_is_not_an_offer():
    reply = QuestionReply(about_their_data=True, text="I can't see Postgres on the watchlist.")
    result, _ = ask(reply)
    assert result.answer.text == "I can't see Postgres on the watchlist."


def test_a_second_call_that_fails_gives_the_first_answer():
    slow = type("ReadTimeout", (Exception,), {})("took too long")
    result, _ = ask(slow)
    assert isinstance(result, Answered) and result.answer == AbilitiesAnswer()


def test_the_catch_all_is_sent_to_the_lane_and_a_no_keeps_the_abilities_answer():
    reply = QuestionReply(about_their_data=False)
    result, chat = ask(reply, task="What can you do?")
    assert result == Answered(answer=AbilitiesAnswer())
    assert chat.asked == [TaskRead, QuestionReply]


def test_without_facts_the_catch_all_stays_abilities_and_the_lane_is_not_asked():
    result, chat = ask(QuestionReply(about_their_data=True, text="Three."), facts=None)
    assert result == Answered(answer=AbilitiesAnswer())
    assert len(chat.calls) == 1


def test_a_reading_that_asks_for_a_task_never_reaches_the_lane():
    task = "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days"
    result, chat = ask(
        QuestionReply(about_their_data=True, text="Three."), task=task, first=follow_up()
    )
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


@pytest.mark.parametrize(
    ("task", "software"),
    [
        ("Is there a newer version of FastAPI?", "FastAPI"),
        ("Which version of Grafana do we run?", "Grafana"),
    ],
)
def test_a_watchlist_offer_for_unwatched_software_stands_without_the_lane(task: str, software: str):
    first = watch_reading(software)
    out, chat = ask(QuestionReply(about_their_data=True, text="Three."), task=task, first=first)
    assert isinstance(out.answer, WatchlistAnswer) and out.answer.software == software
    assert len(chat.calls) == 1


def test_a_watchlist_offer_for_watched_software_goes_to_the_lane_whatever_the_case():
    task = "Is there a newer version of langgraph?"
    reply = QuestionReply(about_their_data=True, text="Yes, 1.2.16.")
    out, _ = ask(reply, task=task, first=watch_reading(" LangGraph "))
    assert out.answer == QuestionAnswer(text="Yes, 1.2.16.", looked_at=["watchlist"])


def test_a_lane_no_on_a_watched_software_keeps_the_watchlist_offer():
    task = "Keep track of the LangGraph version"
    out, _ = ask(QuestionReply(about_their_data=False), task=task, first=watch_reading("LangGraph"))
    assert isinstance(out.answer, WatchlistAnswer) and out.answer.software == "LangGraph"


def test_decide_leaves_which_software_cants_and_tasks_alone():
    request = AnswerRequest(
        task="Tell me when there's a new version", model=answer_request().model, facts=FACTS
    )
    assert not isinstance(decide(watch_reading(None), request), AskTheQuestionLane)
    jira = AnswerRequest(
        task="How many Jira tickets are open in MOCK?", model=answer_request().model, facts=FACTS
    )
    assert not isinstance(decide(reading("none"), jira), AskTheQuestionLane)


@pytest.mark.parametrize(
    "offer",
    [
        "I'd be glad to add it.",
        "I could add FastAPI.",
        "Shall I add FastAPI?",
        "Would you like me to add FastAPI?",
        "We can add FastAPI.",
        "We could add FastAPI.",
        "It can be added to your watchlist.",
        "The Planner can watch it.",
        "I am going to add it.",
    ],
)
def test_more_offer_phrasings_fall_back_to_the_fixed_text(offer: str):
    result, _ = ask(QuestionReply(about_their_data=True, text=f"Three. {offer}"))
    assert result.answer == QuestionAnswer(text=COULD_NOT_ANSWER, looked_at=[])


def test_the_prompt_keeps_the_facts_out_of_the_answer():
    assert 'Never say "the facts"' in QUESTION_SYSTEM
