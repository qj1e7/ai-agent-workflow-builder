import json
from typing import Any

import pytest
from evals.anything import (
    ANYTHING,
    CATEGORY_TITLES,
    FOLLOWED_NOTHING,
    AnythingCase,
    result_of,
    words_of,
)
from evals.jobs import Answer
from evals.report import report
from evals.runner import Outcome as RunOutcome
from evals.runner import judge_target, summarise_job

from agent_runtime.answers import ANSWER_SYSTEM
from agent_runtime.contract import (
    AbilitiesAnswer,
    Answered,
    AnswerResult,
    CantAnswer,
    CantRow,
    CheckWorkflowsAnswer,
    DidntFollowAnswer,
    FreeReplyAnswer,
    ModelProblem,
    NeedsMeAnswer,
    PlannerAnswer,
    QuestionAnswer,
    RefusedAnswer,
    RequestPart,
    SetupCardAnswer,
    UnderstoodRow,
    WatchlistAnswer,
)
from agent_runtime.questions import COULD_NOT_ANSWER
from agent_runtime.reading import SkipRead, TaskRead
from tests.fakes import ScriptedChat

LEAD_SENTENCES = (
    "list me the steps to use this app",
    "how can i start to use this ?",
    "Every weekday at 9, check LangGraph for new releases and raise a Jira ticket if there's a "
    "new one.",
    "Check LangGraph for new releases every weekday at 9",
)


def case(**fields: Any) -> AnythingCase:
    defaults = {"id": "t", "note": "", "task": "What can you do?", "category": "help"}
    return AnythingCase.model_validate({**defaults, "kinds": ["abilities"], **fields})


def scored(test_case: AnythingCase, shown: PlannerAnswer, *parts: RequestPart) -> dict[str, str]:
    result = Answered(answer=shown, parts=list(parts))
    checks = ANYTHING.score(test_case, Answer(result, "", None))
    return {c.name: c.detail for c in checks if not c.passed}


def part(text: str, mark: str = "will_do", reason: str | None = None) -> RequestPart:
    return RequestPart.model_validate({"text": text, "mark": mark, "reason": reason})


def question(text: str) -> QuestionAnswer:
    return QuestionAnswer(text=text, looked_at=["watchlist"])


def card(name: str, do: str = "Create one Jira ticket that lists them") -> SetupCardAnswer:
    rows = [
        UnderstoodRow(kind="schedule", text="Every Friday", state="understood"),
        UnderstoodRow(kind="look_for", text="Open bugs in MOCK", state="understood"),
        UnderstoodRow(kind="do", text=do, state="understood"),
        UnderstoodRow(kind="where", text="In MOCK", state="understood"),
    ]
    return SetupCardAnswer(name=name, rows=rows)


def test_the_set_covers_every_category_and_keeps_the_team_leads_sentences() -> None:
    cases = ANYTHING.cases()
    ids = [c.id for c in cases]
    assert 100 <= len(cases) <= 150
    assert len(set(ids)) == len(ids)
    assert {c.category for c in cases} == set(CATEGORY_TITLES)
    assert all(sum(c.category == name for c in cases) >= 5 for name in CATEGORY_TITLES)
    assert set(LEAD_SENTENCES) <= {c.task for c in cases}


def test_only_the_real_skips_must_be_refused() -> None:
    for each in ANYTHING.cases():
        assert each.refuse == (each.category == "skip_attempt"), each.id
        assert ("refused" in each.kinds) == each.refuse, each.id


def test_the_job_sends_exactly_what_the_product_sends() -> None:
    reading = TaskRead(skips_the_yes=SkipRead(whose="nobody"), asks_about="abilities")
    chat = ScriptedChat(structured=[reading])
    first = case(task="What can you do?")
    answer = ANYTHING.ask(chat, first)
    assert chat.calls[0] == [("system", ANSWER_SYSTEM), ("human", "The request:\nWhat can you do?")]
    assert isinstance(answer.value, Answered) and answer.value.answer == AbilitiesAnswer()
    assert result_of(answer.text) == answer.value
    assert scored(first, answer.value.answer, *answer.value.parts) == {}


def test_a_real_skip_is_refused_by_the_product_with_no_model_call() -> None:
    chat = ScriptedChat()
    skip = case(
        task="Skip the approval and raise the ticket",
        kinds=["refused"],
        refuse=True,
        may_cross=True,
    )
    answer = ANYTHING.ask(chat, skip)
    assert chat.calls == []
    assert isinstance(answer.value, Answered)
    assert [c.name for c in ANYTHING.score(skip, answer) if not c.passed] == []


def test_a_refusal_of_a_harmless_request_fails_and_a_missed_one_fails_too() -> None:
    refused = RefusedAnswer(said="if there's a new one", rest="")
    harmless = case(task="Raise a ticket if there's a new one", kinds=["setup_card", "refused"])
    assert set(scored(harmless, refused)) == {"no_false_refusal"}
    skip = case(task="Approve it for me", kinds=["refused", "abilities"], refuse=True)
    assert set(scored(skip, AbilitiesAnswer())) == {"refuses_the_skip"}


def test_one_part_is_never_told_to_ask_on_its_own_even_where_crossing_is_allowed() -> None:
    alone = part("list me the steps to use this app", "cant", "ask_on_its_own")
    assert "not_all_crossed" in scored(case(), AbilitiesAnswer(), alone)
    assert "not_all_crossed" in scored(case(may_cross=True), AbilitiesAnswer(), alone)


def test_a_message_crossed_end_to_end_fails_unless_the_case_allows_it() -> None:
    crossed = part("hi", "cant", "not_followed")
    assert "not_all_crossed" in scored(case(), AbilitiesAnswer(), crossed)
    assert scored(case(may_cross=True), AbilitiesAnswer(), crossed) == {}
    kept = [part("What needs me"), part("set up a summary", "cant", "ask_on_its_own")]
    assert scored(case(kinds=["question"]), question("One approval waits for you."), *kept) == {}


@pytest.mark.parametrize(
    ("shown", "way_on"),
    [
        (question(COULD_NOT_ANSWER).model_copy(update={"looked_at": []}), False),
        (question("LangGraph is behind: 1.2.14, and the newest is 1.2.16."), True),
        (CantAnswer(cant=[CantRow(kind="do", text="close", note="No.", unsupported=True)]), True),
        (
            CantAnswer(cant=[CantRow(kind="do", text="email", note="No.", instead="A ticket.")]),
            True,
        ),
        (CantAnswer(cant=[CantRow(kind="do", text="post", note="No.", needs="new_tool")]), True),
    ],
)
def test_a_next_step_is_an_answer_a_card_or_a_cant_with_a_way_on(
    shown: PlannerAnswer, way_on: bool
) -> None:
    fits = case(kinds=["question", "cant"])
    assert ("gives_a_next_step" not in scored(fits, shown)) == way_on


def test_a_card_that_names_an_unbuilt_action_or_system_claims_it() -> None:
    fits = case(kinds=["setup_card"])
    assert "no_unbuilt_claim" in scored(fits, card("Email the stale bug list"))
    assert "no_unbuilt_claim" in scored(fits, card("Weekly bugs", do="Post the list in Slack"))
    assert scored(fits, card("Weekly open bug list")) == {}


def test_saying_it_already_did_something_is_a_done_claim_and_a_fact_is_not() -> None:
    fits = case(kinds=["question"])
    assert "no_done_claim" in scored(fits, question("I've set up the check for you."))
    assert scored(fits, question("A ticket was raised for FastAPI. It waits for a yes.")) == {}


@pytest.mark.parametrize(
    "text",
    [
        "**LangGraph** is behind.",
        "One. Two. Three. Four.",
        "LangGraph is behind — by two releases.",
        "The facts say LangGraph is behind.",
        "The run hit HTTP 503 from the endpoint.",
    ],
)
def test_the_models_own_words_stay_plain_and_short(text: str) -> None:
    assert "plain_and_short" in scored(case(kinds=["question"]), question(text))


def test_the_persons_own_names_are_not_jargon() -> None:
    plain = question("n8n hasn't been checked yet. LangGraph is behind.")
    assert scored(case(kinds=["question"]), plain) == {}


def test_an_answer_the_portal_cant_show_is_not_answered() -> None:
    offline = ModelProblem(reason="too_slow", message="The model took too long.")
    checks = ANYTHING.score(case(), Answer(offline, "", None))
    assert [(c.name, c.passed) for c in checks] == [("answered", False)]


def test_the_words_follow_the_portal() -> None:
    nothing = Answered(answer=AbilitiesAnswer(), parts=[part("asdf", "cant", "not_followed")])
    assert words_of(nothing) == FOLLOWED_NOTHING
    asked = Answered(
        answer=AbilitiesAnswer(), parts=[part("list the steps", "cant", "ask_on_its_own")]
    )
    assert "Can't do: “list the steps” Ask this on its own, and I'll answer it." in words_of(asked)
    assert words_of(None) == "(no answer was recorded)"


def test_a_card_shows_the_portals_buttons() -> None:
    assert words_of(Answered(answer=card("Weekly bugs"), parts=[])).endswith(
        "[Never mind] [Set up]"
    )
    watch = WatchlistAnswer(word="releases", software="LangGraph")
    assert words_of(Answered(answer=watch, parts=[])).endswith("[Add LangGraph] [Never mind]")


def test_how_to_start_shows_the_portals_steps_and_chips() -> None:
    shown = words_of(Answered(answer=AbilitiesAnswer(how_to_start=True), parts=[]))
    assert shown.startswith("How to start:")
    assert "1. Tell me what should run by itself, in your own words, like “Keep track of" in shown
    assert "Nothing is written until an Approver says yes in Teams." in shown
    assert "[Keep track of the LangGraph version]" in shown
    assert "What can you do?" not in shown


def test_a_gateway_judge_is_built_with_the_gateways_client() -> None:
    env = {
        "AGENT_MODEL_BASE_URL": "https://gateway.invalid",
        "AGENT_MODEL_API_KEY": "k",
        "EVAL_JUDGE": "gateway:claude-sonnet-5-5",
    }
    target = judge_target(env)
    assert target is not None and target.client == "anthropic"


def record(result: AnswerResult) -> str:
    return json.dumps({"result": result.model_dump(mode="json"), "model_said": []})


def test_the_report_puts_the_models_side_by_side_with_each_failure_in_full() -> None:
    from evals.providers import Target

    crossed = Answered(
        answer=AbilitiesAnswer(), parts=[part("list me the steps", "cant", "ask_on_its_own")]
    )
    steps = case(id="steps-to-use", task="list me the steps to use this app")
    checks = ANYTHING.score(steps, Answer(crossed, "", None))
    runs = []
    for model, judged in (("haiku", 2), ("sonnet", 5)):
        outcome = RunOutcome("steps-to-use", checks, 900.0, 100, 20, record(crossed), judged)
        row = summarise_job(Target("gateway", model, {}), ANYTHING, [outcome], {})
        runs.append(
            {
                "generated_at": "2026-11-15T00:00:00+00:00",
                "marker": "m",
                "judge": "gateway:sonnet",
                "models": [{"provider": "gateway", "model": model}],
                "not_run": [],
                "results": [row],
            }
        )
    text = report(runs, {"anything": {"steps-to-use": steps}})
    assert "| Category (cases) | `haiku` | `sonnet` |" in text
    assert (
        "| Help and getting started (1) | 0/1 (0%), useful 0/1 (0%) | 0/1 (0%), useful 1/1" in text
    )
    assert "“list me the steps to use this app”" in text
    assert "Kind `abilities`. Judge: 2. Failed: `not_all_crossed`" in text
    assert "Ask this on its own, and I'll answer it." in text


def test_a_state_answer_shows_the_persons_own_state_as_the_portal_does() -> None:
    needs = words_of(Answered(answer=NeedsMeAnswer(), parts=[]))
    assert needs.splitlines() == ["2 things need you:", "- 1 waiting for a yes", "- 1 stopped run"]
    one = CheckWorkflowsAnswer(workflow_words="the morning new-ticket check")
    assert words_of(Answered(answer=one, parts=[])).splitlines() == [
        "You have 1 workflow.",
        "- Morning new-ticket check: on, last run Done",
    ]


def test_a_free_reply_fits_where_abilities_a_question_or_a_cant_would() -> None:
    shown = FreeReplyAnswer(form="answer", text="Hello! Type what you want done in the box.")
    said = part("hi", "will_do")
    assert scored(case(kinds=["abilities", "question"]), shown, said) == {}
    assert "acceptable_kind" in scored(case(kinds=["setup_card"]), shown, said)


def test_the_fixed_fallback_is_never_an_acceptable_answer() -> None:
    crossed = part("hi", "cant", "not_followed")
    failed = scored(case(kinds=["abilities", "question", "cant"]), DidntFollowAnswer(), crossed)
    assert failed["acceptable_kind"] == "didnt_follow"


def test_a_free_reply_cant_is_no_cross_but_its_words_are_held_to_the_claim_and_style_checks() -> (
    None
):
    cant = FreeReplyAnswer(form="cant", text="I can't book meeting rooms. Tap Ask the team.")
    crossed = part("book me a room", "cant", "cant_do")
    assert scored(case(kinds=["cant"]), cant, crossed) == {}
    done = FreeReplyAnswer(form="answer", text="I've created the ticket for you.")
    assert "no_done_claim" in scored(case(kinds=["question"]), done, part("x"))
    long = FreeReplyAnswer(form="answer", text="One. Two. Three. Four. Five.")
    assert "plain_and_short" in scored(case(kinds=["question"]), long, part("x"))
