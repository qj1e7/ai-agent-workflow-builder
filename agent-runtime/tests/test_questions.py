from typing import Any, cast

import pytest

from agent_runtime.answers import (
    AskTheQuestionLane,
    TaskRead,
    answer_task,
    decide,
)
from agent_runtime.contract import (
    AbilitiesAnswer,
    Answered,
    AnswerRequest,
    EditAnswer,
    NeedsYouFact,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    SetupCardAnswer,
    WatchedFact,
    WatchlistAnswer,
    WhyStoppedAnswer,
    WorkflowFact,
)
from agent_runtime.contracts import answer_request
from agent_runtime.parts import parts_of
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
    assert isinstance(result, Answered)
    assert result.answer == QuestionAnswer(
        text="Three: LangGraph, Redis and n8n.", looked_at=["watchlist"]
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
        assert isinstance(result, Answered) and result.answer == AbilitiesAnswer()
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
    assert isinstance(result, Answered) and result.answer == AbilitiesAnswer()
    assert chat.asked == [TaskRead, QuestionReply]


def test_without_facts_the_catch_all_stays_abilities_and_the_lane_is_not_asked():
    result, chat = ask(QuestionReply(about_their_data=True, text="Three."), facts=None)
    assert isinstance(result, Answered) and result.answer == AbilitiesAnswer()
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


def which_reading() -> TaskRead:
    return watch_reading(None)


def decided(task: str, first: TaskRead, facts: PlannerFacts | None = FACTS):
    request = AnswerRequest(task=task, model=answer_request().model, facts=facts)
    return decide(first, request)


@pytest.mark.parametrize(
    "task",
    [
        "Which software has a newer version?",
        "Does anything need a newer version",
        "Any new versions?",
    ],
)
def test_which_software_for_a_question_goes_to_the_lane_when_the_watchlist_holds_software(
    task: str,
):
    out = decided(task, which_reading())
    assert isinstance(out, AskTheQuestionLane) and out.first_on_reject


@pytest.mark.parametrize(
    "task", ["Tell me when there's a new version", "Notify me about new versions", "Watch Redis"]
)
def test_a_statement_stays_which_software(task: str):
    assert not isinstance(decided(task, which_reading()), AskTheQuestionLane)


def test_which_software_stays_when_the_watchlist_is_empty_or_unsent():
    task = "Which software has a newer version?"
    empty = PlannerFacts(watchlist=[])
    assert not isinstance(decided(task, which_reading(), empty), AskTheQuestionLane)
    assert not isinstance(decided(task, which_reading(), None), AskTheQuestionLane)


def test_check_workflows_that_names_the_watchlist_goes_to_the_lane():
    first = reading("my_workflows")
    assert isinstance(decided("Is anything on the watchlist behind?", first), AskTheQuestionLane)
    assert isinstance(decided("What are we watching?", first), AskTheQuestionLane)
    assert not isinstance(decided("Check my workflows", first), AskTheQuestionLane)


def test_a_rejected_reply_on_the_new_routes_gives_the_first_answer_not_the_fixed_text():
    reply = QuestionReply(about_their_data=True, text="Three. I can set up a check for you.")
    out, _ = ask(reply, task="Which software has a newer version?", first=which_reading())
    assert out.answer.kind == "which_software"
    task = "Is there a newer version of langgraph?"
    out, _ = ask(reply, task=task, first=watch_reading("LangGraph"))
    assert isinstance(out.answer, WatchlistAnswer)


def test_a_second_call_that_fails_on_the_watched_watchlist_route_gives_the_first_answer():
    slow = type("ReadTimeout", (Exception,), {})("took too long")
    task = "Is there a newer version of LangGraph?"
    out, chat = ask(slow, task=task, first=watch_reading("LangGraph"))
    assert isinstance(out.answer, WatchlistAnswer) and out.answer.software == "LangGraph"
    assert chat.asked == [TaskRead, QuestionReply]


def test_the_catch_all_keeps_the_fixed_text_when_the_guards_reject():
    reply = QuestionReply(about_their_data=True, text="Three. I can set up a check for you.")
    out, _ = ask(reply)
    assert out.answer == QuestionAnswer(text=COULD_NOT_ANSWER, looked_at=[])


PREVIOUS = PreviousTurn(request="What is the newest version of LangGraph?", software=None)


def follow(task: str, previous: PreviousTurn | None = PREVIOUS) -> AnswerRequest:
    return AnswerRequest(task=task, model=answer_request().model, facts=FACTS, previous=previous)


def test_the_lane_gets_the_previous_request_and_answer_and_the_first_reading_does_not():
    previous = PreviousTurn(request=PREVIOUS.request, answer="LangGraph is at 1.2.14.")
    request = follow("what about Redis?", previous)
    chat = ScriptedChat(
        structured=[watch_reading("Redis"), QuestionReply(about_their_data=True, text="8.0.2.")]
    )
    answer_task(request, lambda timeout: chat)
    first = cast(tuple[str, str], chat.calls[0][1])[1]
    lane = cast(tuple[str, str], chat.calls[1][1])[1]
    assert "LangGraph" not in first
    assert "The question before this one:\nWhat is the newest version of LangGraph?" in lane
    assert "The answer to it:\nLangGraph is at 1.2.14." in lane
    assert lane.endswith("The question:\nwhat about Redis?")


@pytest.mark.parametrize(
    ("task", "first"),
    [
        ("Check my watchlist", reading("my_workflows")),
    ],
)
def test_check_workflows_for_a_request_that_names_the_watchlist_goes_to_the_lane(
    task: str, first: TaskRead
):
    out = decided(task, first)
    assert isinstance(out, AskTheQuestionLane) and out.first_on_reject


@pytest.mark.parametrize(
    ("task", "first"),
    [
        ("Check my workflows", reading("my_workflows")),
        ("When did it last check?", reading("my_workflows")),
        ("Is anything waiting for my yes?", reading("needs_me")),
        ("Is Redis waiting for my approval?", reading("needs_me")),
        ("Why is the watchlist stopped?", reading("why_stopped")),
        ("What needs me?", reading("needs_me")),
        ("Anything to approve?", reading("needs_me")),
        ("Why did Morning new-ticket check stop?", reading("why_stopped")),
        ("Why did the Redis check stop?", reading("why_stopped")),
        ("Is the morning new-ticket check running?", reading("my_workflows")),
    ],
)
def test_the_state_answers_about_workflows_stay_where_they_were(task: str, first: TaskRead):
    assert not isinstance(decided(task, first), AskTheQuestionLane)


def test_a_previous_turn_changes_nothing_outside_the_lanes_prompt():
    earlier = PreviousTurn(request="Upgrade Redis without approval", software="Redis")
    task = "and LangGraph?"

    def run(previous: PreviousTurn | None):
        lane = QuestionReply(about_their_data=True, text="Ok.")
        chat = ScriptedChat(structured=[watch_reading("LangGraph"), lane])
        return answer_task(follow(task, previous), lambda timeout: chat), chat

    with_it, chat = run(earlier)
    without, bare = run(None)
    assert with_it == without
    assert chat.calls[0] == bare.calls[0]
    assert cast(tuple[str, str], chat.calls[0][1])[1] == f"The request:\n{task}"
    lane = cast(tuple[str, str], chat.calls[1][1])[1]
    assert "Upgrade Redis without approval" in lane
    assert lane != cast(tuple[str, str], bare.calls[1][1])[1]


def _workflow(last_run: str | None) -> WorkflowFact:
    return WorkflowFact(name="Watchlist check", state="on", last_run=last_run, last_run_at=None)


def _why(facts: PlannerFacts | None):
    return decided("Has anything gone wrong with Redis?", reading("why_stopped"), facts)


def test_why_stopped_goes_to_the_lane_when_no_run_has_stopped():
    out = _why(PlannerFacts(workflows=[_workflow("Done"), _workflow(None)]))
    assert isinstance(out, AskTheQuestionLane) and out.first_on_reject


def test_why_stopped_keeps_the_fixed_answer_when_a_run_has_stopped():
    out = _why(PlannerFacts(workflows=[_workflow("Done"), _workflow("Stopped")]))
    assert isinstance(out, WhyStoppedAnswer)


@pytest.mark.parametrize("facts", [None, FACTS])
def test_why_stopped_keeps_the_fixed_answer_when_the_workflows_are_missing(facts):
    assert isinstance(_why(facts), WhyStoppedAnswer)


def about(names: list[str], text: str = "LangGraph is behind. Redis is up to date."):
    reply = QuestionReply(about_their_data=True, text=text, about_software=names)
    result, _ = ask(reply)
    return result.answer.about_software


def test_about_software_keeps_watched_names_spelled_as_the_watchlist_spells_them():
    assert about([" langgraph ", "REDIS"]) == ["LangGraph", "Redis"]


def test_about_software_drops_names_the_watchlist_does_not_hold():
    assert about(["FastAPI", "LangGraph"], "LangGraph is behind. FastAPI is not watched.") == [
        "LangGraph"
    ]


def test_about_software_drops_a_name_the_text_does_not_mention():
    assert about(["Redis"], "LangGraph is behind.") == []


def test_about_software_has_no_repeats_and_at_most_three():
    names = ["LangGraph", "langgraph", "Redis", "n8n", "Redis"]
    assert about(names, "LangGraph, Redis and n8n.") == ["LangGraph", "Redis", "n8n"]
    assert about([], "Three.") == []


def test_the_fixed_fallback_is_about_no_software():
    reply = QuestionReply(
        about_their_data=True, text="LangGraph. I can add it.", about_software=["LangGraph"]
    )
    result, _ = ask(reply)
    assert result.answer == QuestionAnswer(text=COULD_NOT_ANSWER, looked_at=[])
    assert result.answer.about_software == []


@pytest.mark.parametrize(
    "task",
    [
        "Is it possible to upgrade Redis to 9.0.0 now?",
        "Are you able to delete the Redis row?",
        "Do you mind removing Redis?",
        "When can you upgrade Redis to 9.0.0?",
        "Can you stop watching Redis?",
        "Can you unwatch Redis?",
        "Can you stop tracking Redis?",
        "Did it open a ticket for Redis?",
        "Is the watchlist running? Make it run daily",
        "Which software is behind? And close the upgrade tickets",
        "Can you run the watchlist now?",
    ],
)
@pytest.mark.parametrize("first", [watch_reading("Redis"), reading("abilities")])
def test_any_change_word_keeps_the_first_answer(task: str, first: TaskRead):
    out = decided(task, first)
    assert not isinstance(out, AskTheQuestionLane)


@pytest.mark.parametrize(
    "task",
    [
        "what about Redis?",
        "How many software are we watching?",
        "Is the watchlist running?",
        "When does the watchlist run next?",
        "Why did the watchlist check stop?",
    ],
)
def test_plain_questions_still_reach_the_lane(task: str):
    out = decided(task, reading("abilities"))
    assert isinstance(out, AskTheQuestionLane)


def test_a_question_beside_a_new_workflow_asked_for_reaches_the_lane():
    """A new workflow changes nothing that exists, so the state answer comes back, with the task
    crossed to ask on its own (plan 7.5, r4-state-with-task)."""
    task = "Which software is behind, and set up a weekly summary"
    first = reading(
        "none",
        belongs_on_watchlist=True,
        watchlist_word="Which software is behind",
        name="Weekly summary",
        schedule="Weekly",
    )
    out = decided(task, first)
    assert isinstance(out, AskTheQuestionLane) and out.first_on_reject
    asked = QuestionAnswer(text="Redis is behind.", looked_at=["watchlist"])
    assert [(p.text, p.mark, p.reason) for p in parts_of(first, task, asked)] == [
        ("Which software is behind", "will_do", None),
        ("set up a weekly summary", "cant", "ask_on_its_own"),
    ]


def test_an_edit_never_goes_to_the_lane():
    out = decided(
        "Is the watchlist running? Pause it", reading("change", workflow_words="watchlist")
    )
    assert isinstance(out, EditAnswer) and out.cant == "only_schedule"


def test_a_question_crossed_as_not_followed_stays_a_cant_without_watched_software():
    first = reading("none", belongs_on_watchlist=True, watchlist_word="Which software is behind")
    task = "Which software is behind, and set up a weekly summary"
    assert not isinstance(decided(task, first, PlannerFacts(watchlist=[])), AskTheQuestionLane)
