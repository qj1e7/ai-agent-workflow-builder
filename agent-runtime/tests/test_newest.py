"""A question about the newest version of one software, however it is asked, gets the software card:
Watch it for software the watchlist doesn't hold, and the watched software's own answer for one it
holds. Never the free reply, and never "I didn't follow that"."""

from typing import Any

import pytest
from evals.answer import ANSWER, AnswerCase
from evals.jobs import Answer

from agent_runtime.answers import AskTheQuestionLane, TaskRead, answer_of, answer_task, decide
from agent_runtime.contract import (
    Answered,
    AnswerRequest,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    WatchedFact,
    WatchlistAnswer,
)
from agent_runtime.contracts import answer_request
from agent_runtime.questions import QuestionReply
from tests.fakes import ScriptedChat

FACTS = PlannerFacts(
    watchlist=[
        WatchedFact(
            name="Redis",
            repo="redis/redis",
            our_version="8.0.2",
            newest_version="8.2.0",
            state="New version",
        )
    ]
)


def reading(software: str | None, about: str = "abilities", **fields: Any) -> TaskRead:
    return TaskRead.model_validate(
        {"skips_the_yes": {"whose": "nobody"}, "asks_about": about, "software": software, **fields}
    )


def readings(software: str | None, word: str) -> list[TaskRead]:
    """What a model may read for such a question: something it can't place, a task with no parts,
    or the watchlist with the request's own word for it."""
    return [
        reading(software),
        reading(software, "none"),
        reading(software, "none", belongs_on_watchlist=True, watchlist_word=word),
    ]


def request(task: str, facts: PlannerFacts | None = FACTS) -> AnswerRequest:
    return AnswerRequest(task=task, model=answer_request().model, facts=facts)


FAMILY = [
    ("what's new in node js?", "Node.js", "node js", "new"),
    ("what is the latest node js?", "Node.js", "node js", "latest"),
    ("latest version of redis", "Redis", "Redis", "version"),
    ("is there a new kafka release", "Kafka", "kafka", "release"),
    ("what's the newest python", "Python", "python", "newest"),
    ("any updates for langgraph", "LangGraph", "langgraph", "updates"),
    ("any update on langgraph?", "LangGraph", "langgraph", "update"),
    ("what version is node on", "Node", "node", "version"),
    ("what’s grafana’s most recent version?", "Grafana", "grafana", "version"),
    ("is terraform up to date?", "Terraform", "terraform", "up to date"),
    (
        "Can you tell me the current Kubernetes release please",
        "kubernetes",
        "Kubernetes",
        "release",
    ),
]


@pytest.mark.parametrize(("task", "read_as", "written", "word"), FAMILY)
def test_a_question_about_the_newest_version_offers_to_watch_the_software(
    task: str, read_as: str, written: str, word: str
) -> None:
    for read in readings(read_as, word):
        assert answer_of(read, task, FACTS) == WatchlistAnswer(word=word, software=written), read


@pytest.mark.parametrize(
    "task", ["what's new in node js?", "what is the latest node js?", "any updates for langgraph"]
)
def test_the_offer_is_the_whole_answer_with_one_model_call_and_every_part_ticked(task: str) -> None:
    chat = ScriptedChat(structured=[reading("Node.js" if "node" in task else "LangGraph")])
    result = answer_task(request(task), lambda timeout: chat)
    assert isinstance(result, Answered) and isinstance(result.answer, WatchlistAnswer)
    assert len(chat.calls) == 1
    assert result.parts and all(p.mark == "will_do" for p in result.parts)


def test_a_question_the_model_put_on_the_watchlist_is_never_crossed_as_a_change() -> None:
    read = reading("Redis", "none", belongs_on_watchlist=True, watchlist_word="version")
    shown = answer_of(read, "any updates on the latest redis version?", FACTS)
    assert shown == WatchlistAnswer(word="version", software="Redis")


def test_watched_software_spelled_another_way_is_named_as_the_watchlist_names_it() -> None:
    node = WatchedFact(
        name="Node.js", repo="nodejs/node", our_version=None, newest_version="25.1.0", state="New"
    )
    facts = PlannerFacts(watchlist=[node])
    first = reading("Node.js")
    asked = AnswerRequest(task="what's new in node js?", model=answer_request().model, facts=facts)
    assert decide(first, asked) == AskTheQuestionLane(
        otherwise=WatchlistAnswer(word="new", software="Node.js"), first_on_reject=True
    )
    twice = PlannerFacts(watchlist=[node, node.model_copy(update={"name": "NodeJS"})])
    shown = answer_of(first, "what's new in node js?", twice)
    assert shown == WatchlistAnswer(word="new", software="node js")


def test_keep_track_of_it_after_the_offer_watches_that_software() -> None:
    task = "what's new in node js?"
    first = answer_task(
        request(task), lambda timeout: ScriptedChat(structured=[reading("Node.js")])
    )
    assert isinstance(first, Answered) and isinstance(first.answer, WatchlistAnswer)
    before = PreviousTurn(request=task, software=first.answer.software, kind="watchlist")
    again = TaskRead.model_validate(
        {
            "skips_the_yes": {"whose": "nobody"},
            "belongs_on_watchlist": True,
            "watchlist_word": "keep track of",
        }
    )
    chat = ScriptedChat(structured=[again])
    later = AnswerRequest(task="keep track of it", model=answer_request().model, previous=before)
    out = answer_task(later, lambda timeout: chat)
    assert isinstance(out, Answered)
    assert out.answer == WatchlistAnswer(word="keep track of", software="node js")


def test_watched_software_goes_to_the_question_lane_and_keeps_its_card_when_the_lane_says_no() -> (
    None
):
    first = reading("Redis")
    decided = decide(first, request("what's new in redis?"))
    assert decided == AskTheQuestionLane(
        otherwise=WatchlistAnswer(word="new", software="Redis"), first_on_reject=True
    )
    no = QuestionReply(about_their_data=False)
    chat = ScriptedChat(structured=[first, no])
    result = answer_task(request("what's new in redis?"), lambda timeout: chat)
    assert isinstance(result, Answered)
    assert result.answer == WatchlistAnswer(word="new", software="Redis")
    yes = QuestionReply(about_their_data=True, text="8.2.0 is the newest. You run 8.0.2.")
    chat = ScriptedChat(structured=[first, yes])
    result = answer_task(request("what's the latest redis?"), lambda timeout: chat)
    assert isinstance(result, Answered) and isinstance(result.answer, QuestionAnswer)


@pytest.mark.parametrize(
    ("task", "software"),
    [
        ("what's new with the team", None),
        ("what's new with the team", "team"),
        ("latest news", None),
        ("what's the latest news on kafka?", "Kafka"),
        ("what's new", None),
        ("what's new in jira?", "Jira"),
        ("update langgraph", "LangGraph"),
        ("can you upgrade redis", "Redis"),
        ("what's new in node js and email me the list", "Node.js"),
        ("what's new in node 22?", "node"),
        ("tell me about node js", "Node.js"),
        ("what's new in LangGraph and Redis?", "LangGraph"),
        ("what is the latest node js and redis?", "node js and redis"),
        ("what is the latest node js and redis?", "node js"),
        ("is redis or kafka newer?", "redis"),
        ("what's the latest ticket in MOCK-12?", "MOCK-12"),
        (f"what is the latest {'x' * 90}?", "x" * 90),
        ("what's new in c++?", "c++"),
        ("what's the latest .NET version?", ".NET"),
    ],
)
def test_words_that_ask_for_more_or_name_no_software_are_not_this_question(
    task: str, software: str | None
) -> None:
    for read in (reading(software), reading(software, "none")):
        assert not isinstance(answer_of(read, task, FACTS), WatchlistAnswer), read


def test_a_reading_that_asks_to_skip_a_yes_gets_no_offer() -> None:
    read = TaskRead.model_validate(
        {
            "skips_the_yes": {"whose": "an_approver_or_anyone_else", "said": "no approval"},
            "asks_about": "abilities",
            "software": "Node.js",
        }
    )
    assert not isinstance(answer_of(read, "what's new in node js?", FACTS), WatchlistAnswer)


@pytest.mark.parametrize(
    "case", [c for c in ANSWER.cases() if c.id.startswith("nw-")], ids=lambda c: c.id
)
def test_the_golden_cases_pass_on_a_reading_that_names_only_the_software(case: AnswerCase) -> None:
    """The rules-mode golden set's cases, scored as the eval scores them, on the plainest reading a
    model gives: the software, if the request names one, and nothing else."""
    named = {"node js": "Node.js", None: "LangGraph" if case.facts else None}
    read = reading(named.get(case.software, case.software))
    lane = QuestionReply(about_their_data=False)
    checks = ANSWER.score(case, Answer(read, read.model_dump_json(), None, lane))
    assert [c.name for c in checks if not c.passed] == []
