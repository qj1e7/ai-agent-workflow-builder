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
    CantAnswer,
    CheckWorkflowsAnswer,
    EditAnswer,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    WatchedFact,
    WatchlistAnswer,
    WorkflowFact,
)
from agent_runtime.contracts import answer_request
from agent_runtime.questions import QuestionReply
from agent_runtime.reading import SearchRead
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
        ("what's new in node js? check now", "Node.js"),
        ("what's new in node js? tell me now", "Node.js"),
    ],
)
def test_words_that_ask_for_more_or_name_no_software_are_not_this_question(
    task: str, software: str | None
) -> None:
    for read in (reading(software), reading(software, "none")):
        assert not isinstance(answer_of(read, task, FACTS), WatchlistAnswer), read


@pytest.mark.parametrize(
    ("task", "software"),
    [
        ("can we update redis?", "Redis"),
        ("could we patch kafka?", "Kafka"),
        ("can I upgrade node js?", "Node.js"),
        ("please do update redis", "Redis"),
        ("do the redis update", "Redis"),
        ("run the latest redis update", "Redis"),
        ("run the update for kafka now", "Kafka"),
        ("use the latest node js", "Node.js"),
        ("we update redis to the latest", "Redis"),
    ],
)
def test_an_order_asked_as_a_question_keeps_its_answer_and_gets_no_card(
    task: str, software: str
) -> None:
    for read in (reading(software), reading(software, "none")):
        assert not isinstance(answer_of(read, task, FACTS), WatchlistAnswer), read


WORKFLOWS = PlannerFacts(
    watchlist=FACTS.watchlist,
    workflows=[
        WorkflowFact(name="Kafka check", state="on", last_run="Stopped", last_run_at=None),
        WorkflowFact(name="LangGraph release check", state="on", last_run="Done", last_run_at=None),
    ],
)


@pytest.mark.parametrize(
    ("task", "about", "words", "software"),
    [
        ("what's the latest on the kafka check?", "why_stopped", "kafka check", "kafka"),
        ("what's the latest on the kafka check?", "my_workflows", "kafka check", "kafka"),
        ("what's the latest on the kafka check?", "abilities", None, "kafka"),
        (
            "what's the latest run of the LangGraph release check?",
            "my_workflows",
            None,
            "LangGraph",
        ),
        ("is the LangGraph release check up to date?", "my_workflows", None, "LangGraph"),
        ("is the LangGraph release check up to date?", "none", None, "LangGraph"),
        ("is the watchlist up to date?", "my_workflows", None, None),
    ],
)
def test_a_question_about_their_own_workflow_keeps_its_answer(
    task: str, about: str, words: str | None, software: str | None
) -> None:
    read = reading(software, about, workflow_words=words)
    assert not isinstance(answer_of(read, task, WORKFLOWS), WatchlistAnswer)


@pytest.mark.parametrize(
    ("task", "software"),
    [
        ("anything new in my outlook?", "Outlook"),
        ("any updates in entra?", "Entra"),
        ("what's new in servicenow?", "ServiceNow"),
        ("anything new on sharepoint?", "SharePoint"),
        ("any new in slack?", "Slack"),
        ("what's the latest in gmail?", "Gmail"),
        ("any updates on azure?", "Azure"),
        ("what's new in my gitlab?", "GitLab"),
        ("what's new in jenkins?", "Jenkins"),
    ],
)
def test_a_system_the_platform_does_not_reach_keeps_its_cant(task: str, software: str) -> None:
    """Read as a task, the can't names the system. Read as something it can't place, the list of
    abilities leads to the free reply, which is told the system is one the platform can't reach."""
    shown = answer_of(reading(software, "none"), task, FACTS)
    assert isinstance(shown, CantAnswer) and shown.cant[0].system == software, shown
    assert not isinstance(answer_of(reading(software), task, FACTS), WatchlistAnswer)


@pytest.mark.parametrize(
    ("task", "software"),
    [
        ("what's new in the planner?", "Planner"),
        ("is the AI troubleshooter up to date?", "AI troubleshooter"),
        ("what's new in the live activity view?", "live activity view"),
        ("what's new in the agent api?", "Agent API"),
        ("any updates from the safety checker?", "safety checker"),
        ("what's new in the portal?", "Portal"),
        ("is the watchlist up to date?", "watchlist"),
        ("latest news", "news"),
        ("what's new with the team", "team"),
    ],
)
def test_the_platforms_own_names_and_plain_words_get_no_card(task: str, software: str) -> None:
    for read in (reading(software), reading(software, "none")):
        assert not isinstance(answer_of(read, task, FACTS), WatchlistAnswer), read


def test_a_reading_of_tickets_gets_no_card() -> None:
    tickets = SearchRead(project="MOCK", said="MOCK")
    read = reading("MOCK", "none", search=tickets)
    assert not isinstance(answer_of(read, "what's new in MOCK?", FACTS), WatchlistAnswer)


@pytest.mark.parametrize(
    "task",
    [
        "what's new in sk-ant-api03-AbCdEf1234567890XyZ?",
        "latest version of ghp_AbCdEf1234567890XyZaBcD",
    ],
)
def test_a_key_shaped_name_is_never_put_on_a_card(task: str) -> None:
    key = task.split()[-1].rstrip("?")
    for read in (reading(key), reading(key, "none")):
        assert not isinstance(answer_of(read, task, FACTS), WatchlistAnswer), read


@pytest.mark.parametrize(
    ("task", "read_as", "written", "word"),
    [
        ("what's new in node?", "Node.js", "node", "new"),
        ("what version is node on", "Node.js", "node", "version"),
        ("any updates for spring?", "Spring Boot", "spring", "updates"),
    ],
)
def test_a_short_name_matches_the_official_name_the_model_wrote(
    task: str, read_as: str, written: str, word: str
) -> None:
    for read in readings(read_as, word):
        assert answer_of(read, task, FACTS) == WatchlistAnswer(word=word, software=written), read


@pytest.mark.parametrize(
    ("task", "read_as", "written", "word"),
    [
        ("what's new in kafka?", "Apache Kafka", "kafka", "new"),
        ("is terraform up to date?", "HashiCorp Terraform", "terraform", "up to date"),
        ("what's the latest chrome?", "Google Chrome", "chrome", "latest"),
        ("any updates for openshift?", "Red Hat OpenShift", "openshift", "updates"),
        ("what's new in jetty?", "Eclipse Jetty", "jetty", "new"),
        ("latest version of corretto", "amazon corretto", "corretto", "version"),
        ("what's new in apache kafka?", "Apache Kafka", "apache kafka", "new"),
    ],
)
def test_a_vendor_before_the_official_name_lends_the_next_word(
    task: str, read_as: str, written: str, word: str
) -> None:
    """A maker's name the model writes first, as "Apache" in "Apache Kafka", is not the software.
    The word after it is, when the request writes it whole. A name the request writes whole is
    kept as it is."""
    for read in readings(read_as, word):
        assert answer_of(read, task, FACTS) == WatchlistAnswer(word=word, software=written), read


@pytest.mark.parametrize(
    ("task", "read_as", "vendor"),
    [
        ("what's new in apache?", "Apache Kafka", "apache"),
        ("what's new in apache?", "Apache HTTP Server", "apache"),
        ("what's new in apache kafka?", "Apache Kafka Streams", "apache"),
        ("any updates for apache airflow?", "Apache Airflow 2", "apache"),
        ("is google up to date?", "Google Chrome", "google"),
        ("any updates from hashicorp?", "HashiCorp Vault", "hashicorp"),
        ("what's new in red hat?", "Red Hat OpenShift", "red"),
    ],
)
def test_a_vendor_is_never_the_software_on_the_card(task: str, read_as: str, vendor: str) -> None:
    for read in (reading(read_as), reading(read_as, "none")):
        shown = answer_of(read, task, FACTS)
        assert not (isinstance(shown, WatchlistAnswer) and shown.software == vendor), read


@pytest.mark.parametrize(
    ("task", "software", "word"),
    [
        ("did we upgrade kafka?", "Kafka", "upgrade"),
        ("has kafka been patched?", "Kafka", "patched"),
        ("is node js out yet? any updates?", "Node.js", "updates"),
    ],
)
def test_a_question_about_what_was_done_or_asked_twice_still_gets_the_card(
    task: str, software: str, word: str
) -> None:
    shown = answer_of(reading(software), task, FACTS)
    assert isinstance(shown, WatchlistAnswer) and shown.word == word


@pytest.mark.parametrize(
    ("task", "read_as"),
    [
        ("is the server up to date?", "SQL Server"),
        ("is the server up to date?", "Microsoft SQL Server"),
        ("is our database up to date?", "Oracle Database"),
        ("is the sql current?", "Microsoft SQL Server"),
        ("is the ide current?", "Eclipse IDE"),
        ("is linux up to date?", "Amazon Linux"),
        ("is the database up to date?", "PostgreSQL Database"),
        ("is the browser up to date?", "Chrome Browser"),
        ("is the agent up to date?", "Datadog Agent"),
        ("is the runtime up to date?", "Node.js Runtime"),
        ("any updates for boot?", "Spring Boot"),
        ("is the version current?", "Current Version"),
        ("what's new in node?", "Node " + "x" * 90),
    ],
)
def test_a_longer_name_lends_only_its_leading_word_and_never_a_plain_one(
    task: str, read_as: str
) -> None:
    """A plain noun the model's name ends with, as "server" of "SQL Server", is not the software
    the person asked about. Nor is a word that asks what is newest, or the start of a name too long
    to be one."""
    for read in (reading(read_as), reading(read_as, "none")):
        assert not isinstance(answer_of(read, task, FACTS), WatchlistAnswer), read


@pytest.mark.parametrize(
    ("task", "software", "source"),
    [
        ("what's new on pypi?", "pypi", "pypi"),
        ("what's the latest in npm?", "npm", "npm"),
        ("what's new in docker hub?", "Docker Hub", "docker hub"),
    ],
)
def test_a_release_source_the_platform_does_not_read_keeps_its_cant_without_a_release_word(
    task: str, software: str, source: str
) -> None:
    for read in (reading(software), reading(software, "none")):
        shown = answer_of(read, task, FACTS)
        assert isinstance(shown, CantAnswer), shown
        assert (shown.cant[0].system or "").casefold() == source


def test_helm_is_software_as_well_as_a_source_so_it_keeps_its_card() -> None:
    shown = answer_of(reading("Helm"), "is helm up to date?", FACTS)
    assert shown == WatchlistAnswer(word="up to date", software="helm")


def test_a_question_about_a_workflow_with_no_facts_sent_keeps_its_answer() -> None:
    """With no facts, no workflow name can be matched, so only the reading says it is about one."""
    shown = answer_of(reading("kafka", "my_workflows"), "what's the latest on the kafka check?")
    assert isinstance(shown, CheckWorkflowsAnswer)


def test_the_check_comes_after_the_branches_that_answer_first() -> None:
    """A release source the platform doesn't read keeps its can't, and an edit stays an edit, so
    the check can't move above them."""
    npm = answer_of(reading("npm"), "latest npm release", FACTS)
    assert isinstance(npm, CantAnswer) and npm.cant[0].system == "npm"
    edit = answer_of(reading("Redis", "change"), "can we update redis?", FACTS)
    assert isinstance(edit, EditAnswer)


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
    model gives: the software, if the request names one, and nothing else. A case that must not
    get the card names a software too, so it can fail."""
    named = {
        "nw-whats-new-node": "Node.js",
        "nw-latest-node": "Node.js",
        "nw-whats-new-in-node": "Node.js",
        "nw-version-on": "Node.js",
        "nw-watched": "LangGraph",
        "nw-not-the-team": "team",
        "nw-not-news": "news",
    }
    read = reading(named.get(case.id, case.software))
    lane = QuestionReply(about_their_data=False)
    checks = ANSWER.score(case, Answer(read, read.model_dump_json(), None, lane))
    assert [c.name for c in checks if not c.passed] == []
