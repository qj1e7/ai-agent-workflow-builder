import importlib.util
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from agent_runtime.api import create_app
from agent_runtime.contract import (
    ExplainFact,
    ExplainKept,
    ExplainKind,
    ExplainReworded,
    ExplainWordingRequest,
    explain_wording_result_adapter,
)
from agent_runtime.contracts import answer_request
from agent_runtime.explain_wording import (
    ExplainWording,
    explain_guard,
    fact_check,
    reword,
    wording_messages,
)
from agent_runtime.reply_verifier import Verdict
from tests.fakes import ScriptedChat
from tests.test_api import KEY, SETTINGS
from tests.test_free_reply import api_runtime, asked_shapes, prompt_of


def fact(kind: ExplainKind, *together: str, negated: bool = False) -> ExplainFact:
    return ExplainFact(kind=kind, together=list(together), negated=negated)


def request(wording: str, *facts: ExplainFact) -> ExplainWordingRequest:
    return ExplainWordingRequest(model=answer_request().model, wording=wording, facts=list(facts))


FASTAPI = request(
    "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
    "It can create Jira tickets in “MOCK”, each after a yes. It changes nothing else.",
    fact("runs", "day", "8:00"),
    fact("reads", "reads", "GitHub", "fastapi/fastapi"),
    fact("reads", "reads", "Jira", "MOCK"),
    fact("writes", "create", "Jira", "MOCK", "yes"),
    fact("changes", "changes", "nothing", "else", negated=True),
)
"""Code's In short for the FastAPI release check (platform-api's report tests)."""
SMOOTHED = (
    "Each day at 8:00 it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
    "It can create Jira tickets in “MOCK”, each after a yes. Nothing else changes."
)
READS_JIRA = request(
    "Every day at 8:00, it reads Jira “MOCK”. It changes nothing in Jira.",
    fact("runs", "day", "8:00"),
    fact("reads", "reads", "Jira", "MOCK"),
    fact("changes", "changes", "nothing", negated=True),
)
NOTHING_STARTS_IT = request(
    "Nothing starts it. When it runs, it reads Jira “MOCK”. It changes nothing.",
    fact("runs", "starts", negated=True),
    fact("reads", "reads", "Jira", "MOCK"),
    fact("changes", "changes", "nothing", negated=True),
)
BOARD = request(
    "Every Monday at 9:00, it reads Jira “MOCK”. "
    "It can change “Team page” in Jira, each after a yes. It changes nothing else.",
    fact("runs", "Monday", "9:00"),
    fact("reads", "reads", "Jira", "MOCK"),
    fact("writes", "change", "Jira", "Team page", "yes"),
    fact("changes", "changes", "nothing", "else", negated=True),
)


@pytest.mark.parametrize("asked", [FASTAPI, READS_JIRA, NOTHING_STARTS_IT, BOARD])
def test_codes_own_wording_passes(asked: ExplainWordingRequest):
    assert explain_guard(asked.wording, asked) is None


@pytest.mark.parametrize(
    ("asked", "text"),
    [
        (FASTAPI, SMOOTHED),
        (
            FASTAPI,
            "It reads GitHub “fastapi/fastapi” and Jira “MOCK” every day at 8:00. It can create "
            "Jira tickets in “MOCK”, but only after a yes. Nothing else changes.",
        ),
        (READS_JIRA, "Each day at 8:00 it reads Jira “MOCK”. It changes nothing in Jira."),
        (
            BOARD,
            'Each Monday at 9:00 it reads Jira "MOCK". It can change "Team page" in Jira, '
            "each after a yes. Nothing else changes.",
        ),
    ],
)
def test_a_smoothing_true_to_the_facts_passes(asked: ExplainWordingRequest, text: str):
    assert explain_guard(text, asked) is None


@pytest.mark.parametrize(
    ("asked", "text", "check"),
    [
        (READS_JIRA, "Each day at 8:00 it reads Jira “MOCK”. It changes Jira.", "together"),
        (
            READS_JIRA,
            "Each day at 8:00 it reads Jira “MOCK” and changes nothing. It changes Jira.",
            "together",
        ),
        (
            READS_JIRA,
            "Each day at 8:00 it never reads Jira “MOCK”. It changes nothing in Jira.",
            "negation",
        ),
        (
            READS_JIRA,
            "Each day at 8:00 it reads Jira “MOCK” without fail. It changes nothing in Jira.",
            "negation",
        ),
        (
            NOTHING_STARTS_IT,
            "Someone starts it. When it runs, it reads nothing but Jira “MOCK”. "
            "It changes nothing.",
            "negation",
        ),
    ],
    ids=["dropped", "dropped-beside-a-moved-one", "never-added", "without-added", "moved"],
)
def test_every_negation_is_kept_and_none_is_added(
    asked: ExplainWordingRequest, text: str, check: str
):
    assert explain_guard(text, asked) == check


@pytest.mark.parametrize(
    ("text", "check"),
    [
        (SMOOTHED.replace("“fastapi/fastapi”", "“fastapi”"), "quotes"),
        (SMOOTHED.replace("and Jira “MOCK”", "and Jira “MOCK” and “WEB”"), "quotes"),
        (SMOOTHED.replace("GitHub “fastapi/fastapi” and ", ""), "quotes"),
        (SMOOTHED.replace("“MOCK”.", "MOCK."), "quotes"),
        (SMOOTHED.replace("Each day at 8:00 it", "It"), "together"),
    ],
    ids=["changed", "added", "dropped-place", "unquoted", "dropped-time"],
)
def test_nothing_quoted_or_said_is_added_dropped_or_changed(text: str, check: str):
    assert explain_guard(text, FASTAPI) == check


def test_a_read_dropped_into_a_writes_sentence_is_refused():
    dropped = SMOOTHED.replace(" and Jira “MOCK”. It can", ". It can")
    assert explain_guard(dropped, FASTAPI) == "quotes"


@pytest.mark.parametrize("added", [" “MOCK”.", " “MOCK”"], ids=["with-a-stop", "without-one"])
def test_an_added_sentence_that_only_quotes_is_refused(added: str):
    assert explain_guard(SMOOTHED + added, FASTAPI) == "sentences"


def test_a_word_of_a_kind_of_fact_the_workflow_lacks_is_refused():
    shares = SMOOTHED.replace("it reads GitHub", "it reads and shares GitHub")
    assert explain_guard(shares, FASTAPI) == "words"


def test_the_text_is_judged_and_shown_as_the_person_sees_it():
    hidden = SMOOTHED.replace("Nothing", "Noth\u200bing")
    assert explain_guard(hidden, FASTAPI) is None
    shown, _ = asked_with(ExplainWording(text=hidden), CLEAN)
    assert shown == ExplainReworded(text=SMOOTHED)


WEEKLY = request(
    "Every Monday at 9:00, it reads GitHub “langchain-ai/langgraph” and Jira “MOCK”. "
    "It can create Jira tickets in “MOCK”, each after a yes. It changes nothing else.",
    fact("runs", "Monday", "9:00"),
    fact("reads", "reads", "GitHub", "langchain-ai/langgraph"),
    fact("reads", "reads", "Jira", "MOCK"),
    fact("writes", "create", "Jira", "MOCK", "yes"),
    fact("changes", "changes", "nothing", "else", negated=True),
)
"""Code's In short for platform-api's golden agent_cards.json."""
TICKETS_AND_A_POST = request(
    "Every day at 8:00, it reads GitHub “fastapi/fastapi”. "
    "It can create Jira tickets in “MOCK”, each after a yes. "
    "It posts “A newer release is out.” in Teams “Ops”. It changes nothing else.",
    fact("runs", "day", "8:00"),
    fact("reads", "reads", "GitHub", "fastapi/fastapi"),
    fact("writes", "create", "Jira", "MOCK", "yes"),
    fact("posts", "post", "Teams", "A newer release is out.", "Ops"),
    fact("changes", "changes", "nothing", "else", negated=True),
)
NO_YES_EACH_RUN = request(
    "Every day at 8:00, it reads GitHub “fastapi/fastapi”. "
    "It creates Jira tickets in “MOCK” with no yes on each run. It changes nothing else.",
    fact("runs", "day", "8:00"),
    fact("reads", "reads", "GitHub", "fastapi/fastapi"),
    fact("writes", "create", "Jira", "MOCK", negated=True),
    fact("changes", "changes", "nothing", "else", negated=True),
)


@pytest.mark.parametrize(
    ("asked", "text", "check"),
    [
        (
            WEEKLY,
            "Every day at 9:00 it reads GitHub “langchain-ai/langgraph” and Jira “MOCK”, and on "
            "Monday it can create Jira tickets in “MOCK”, each after a yes. "
            "It changes nothing else.",
            "sentences",
        ),
        (
            WEEKLY,
            "Every day at 9:00, it reads GitHub “langchain-ai/langgraph” and Jira “MOCK” each "
            "Monday. It can create Jira tickets in “MOCK”, each after a yes. Nothing else changes.",
            "words",
        ),
        (
            FASTAPI,
            "Every day at 8:00, it reads GitHub “MOCK” and Jira “fastapi/fastapi”. "
            "It can create Jira tickets in “MOCK”, each after a yes. It changes nothing else.",
            "places",
        ),
        (
            FASTAPI,
            "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. After a yes it "
            "reads Jira “MOCK”, and it can create Jira tickets in “MOCK” each day. "
            "It changes nothing else.",
            "together",
        ),
        (
            FASTAPI,
            "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. After a yes it "
            "looks at Jira “MOCK”, and it can create Jira tickets in “MOCK”. "
            "It changes nothing else.",
            "words",
        ),
        (
            FASTAPI,
            "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
            "It can create a Jira ticket in “MOCK” after a yes. It changes nothing else.",
            "words",
        ),
    ],
    ids=[
        "weekly-to-daily-merged",
        "weekly-to-daily",
        "places-swapped",
        "yes-moved-within-a-sentence",
        "yes-left-on-a-look",
        "tickets-to-one-ticket",
    ],
)
def test_a_fact_moved_or_changed_inside_the_paragraph_is_refused(
    asked: ExplainWordingRequest, text: str, check: str
):
    assert explain_guard(text, asked) == check


@pytest.mark.parametrize(
    ("asked", "text", "check"),
    [
        (
            TICKETS_AND_A_POST,
            "Every day at 8:00, it reads GitHub “fastapi/fastapi”. It can create Jira tickets in "
            "“MOCK”, each after a yes. After a yes it posts “A newer release is out.” in Teams "
            "“Ops”. It changes nothing else.",
            "words",
        ),
        (
            TICKETS_AND_A_POST,
            "Every day at 8:00, it reads GitHub “fastapi/fastapi”. It can create Jira tickets in "
            "“MOCK” and, after a yes, posts “A newer release is out.” in Teams “Ops”. "
            "It changes nothing else.",
            "sentences",
        ),
        (
            TICKETS_AND_A_POST,
            "Every day at 8:00, it reads GitHub “fastapi/fastapi”. It can create Jira tickets in "
            "“MOCK”, each after a yes. It posts “Ops” in Teams “A newer release is out.”. "
            "It changes nothing else.",
            "places",
        ),
        (
            NO_YES_EACH_RUN,
            "Every day at 8:00, it reads GitHub “fastapi/fastapi”. "
            "It creates no Jira tickets in “MOCK”, with a yes on each run. "
            "It changes nothing else.",
            "negation",
        ),
        (
            FASTAPI,
            "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”, creates nothing "
            "else and changes Jira tickets in “MOCK”, each after a yes.",
            "sentences",
        ),
    ],
    ids=[
        "yes-added-to-a-post",
        "yes-moved-to-a-post",
        "post-words-and-place-swapped",
        "no-moved",
        "negation-moved-by-merging",
    ],
)
def test_a_yes_or_a_negation_stays_on_the_fact_it_belongs_to(
    asked: ExplainWordingRequest, text: str, check: str
):
    assert fact_check(text, asked) == check


@pytest.mark.parametrize(
    ("asked", "text"),
    [
        (
            FASTAPI,
            "Every day at 8:00 it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
            "After a yes, it can create Jira tickets in “MOCK”. It changes nothing else.",
        ),
        (
            FASTAPI,
            "Each day at 8:00 it reads Jira “MOCK” and GitHub “fastapi/fastapi”. "
            "It can create Jira tickets in “MOCK”, but only after a yes. Nothing else changes.",
        ),
        (
            WEEKLY,
            "Each Monday at 9:00 it reads GitHub “langchain-ai/langgraph” and Jira “MOCK”. "
            "It can create Jira tickets in “MOCK”, each after a yes. Nothing else changes.",
        ),
        (
            FASTAPI,
            "Each day at 8:00 it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
            "It can create Jira tickets for “MOCK”, each after a yes. Nothing else changes.",
        ),
        (
            NOTHING_STARTS_IT,
            "Nothing starts it. When it runs, it reads Jira “MOCK”. Nothing changes.",
        ),
    ],
    ids=["yes-first", "reads-reordered", "each-monday", "for-a-place", "nothing-changes"],
)
def test_a_true_reword_of_each_sentence_still_passes(asked: ExplainWordingRequest, text: str):
    assert explain_guard(text, asked) is None


HELD = request(
    "Every Monday at 9:00, it reads GitHub “fastapi/fastapi”. It could change data in Jira "
    "through “Open an issue”, but it can't run on this platform yet. It changes nothing else.",
    fact("runs", "Monday", "9:00"),
    fact("reads", "reads", "GitHub", "fastapi/fastapi"),
    fact("writes", "change", "Jira", "Open an issue", negated=True),
    fact("changes", "changes", "nothing", "else", negated=True),
)


def test_a_block_that_can_t_run_never_reads_as_one_that_runs():
    ran = HELD.wording.replace(
        "but it can't run on this platform yet", "and it can run on this platform"
    )
    assert fact_check(HELD.wording, HELD) is None
    assert fact_check(ran, HELD) == "negation"


@pytest.mark.parametrize(
    ("asked", "text"),
    [
        (
            TICKETS_AND_A_POST,
            "Each day at 8:00 it reads GitHub “fastapi/fastapi”. After a yes, it can create Jira "
            "tickets in “MOCK”. It posts “A newer release is out.” in Teams “Ops”. "
            "Nothing else changes.",
        ),
        (
            NO_YES_EACH_RUN,
            "Each day at 8:00 it reads GitHub “fastapi/fastapi”. "
            "It creates Jira tickets in “MOCK”, with no yes on each run. Nothing else changes.",
        ),
    ],
    ids=["tickets-and-a-post", "no-yes-each-run"],
)
def test_a_true_reword_keeps_to_the_facts_of_a_paragraph_adr_0047_turns_down(
    asked: ExplainWordingRequest, text: str
):
    assert fact_check(asked.wording, asked) is None
    assert fact_check(text, asked) is None


def test_a_new_system_is_never_named():
    text = SMOOTHED.replace("and Jira “MOCK”.", "and Jira “MOCK” and Confluence.")
    assert explain_guard(text, FASTAPI) is not None


def test_a_yes_moved_onto_another_sentence_is_refused():
    moved = (
        "Each Monday at 9:00 it reads Jira “MOCK”, each after a yes. "
        "It can change “Team page” in Jira. Nothing else changes."
    )
    assert explain_guard(moved, BOARD) == "together"
    ticket = SMOOTHED.replace("“MOCK”, each after a yes.", "“MOCK”.").replace(
        "“MOCK”. It", "“MOCK”, each after a yes. It"
    )
    assert explain_guard(ticket, FASTAPI) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Each day at 8:00 it reads Jira “MOCK” and deletes it. It changes nothing in Jira.",
        "Each day before 8:00 it reads Jira “MOCK”. It changes nothing in Jira.",
        "Each day at 8:00 it always reads Jira “MOCK”. It changes nothing in Jira.",
        "Each day at 8:00 and 9:00 it reads Jira “MOCK”. It changes nothing in Jira.",
        "Each day at 8:00 it reads all of Jira “MOCK”. It changes nothing in Jira.",
    ],
    ids=["deletes", "before", "always", "a-new-time", "all"],
)
def test_a_word_outside_the_closed_lists_is_refused(text: str):
    assert explain_guard(text, READS_JIRA) == "words"


@pytest.mark.parametrize(
    "text",
    [
        "",
        SMOOTHED.replace("and Jira “MOCK”.", "and Jira “MOCK”" + " and Jira “MOCK”" * 12 + "."),
        ". ".join(["It reads Jira “MOCK”"] * 7) + ".",
    ],
    ids=["empty", "longer-than-twice", "seven-sentences"],
)
def test_a_text_of_the_wrong_shape_is_refused(text: str):
    assert explain_guard(text, FASTAPI) == "shape"


def test_adr_0047s_checks_run_first_and_name_their_own_check():
    claimed = SMOOTHED.replace("It can create", "It has created")
    assert explain_guard(claimed, FASTAPI) == "claims_done"


CLEAN = Verdict(says_it_happened=False, skips_a_yes=False, claims_unbuilt=False)


def asked_with(*script: object) -> tuple[ExplainReworded | ExplainKept, ScriptedChat]:
    chat = ScriptedChat(structured=list(script))
    return reword(FASTAPI, lambda timeout: chat), chat


def test_a_smoothing_that_passes_every_check_and_the_verifier_is_shown():
    shown, chat = asked_with(ExplainWording(text=SMOOTHED), CLEAN)
    assert shown == ExplainReworded(text=SMOOTHED)
    assert asked_shapes(chat) == ["ExplainWording", "Verdict"]


def test_the_model_gets_only_codes_wording_and_the_facts():
    _, chat = asked_with(ExplainWording(text=SMOOTHED), CLEAN)
    system, user = prompt_of(chat, 0)
    assert FASTAPI.wording in user
    assert all(item in user for f in FASTAPI.facts for item in f.together)
    assert FASTAPI.model.api_key not in system + user
    assert "data" in system


@pytest.mark.parametrize(
    ("script", "why"),
    [
        ((RuntimeError("the provider is down"),), "call"),
        ((None,), "call"),
        ((ExplainWording(text=SMOOTHED.replace("Nothing else", "It")),), "together"),
        (
            (ExplainWording(text=SMOOTHED), CLEAN.model_copy(update={"says_it_happened": True})),
            "verifier_says_it_happened",
        ),
        ((ExplainWording(text=SMOOTHED), RuntimeError("slow")), "verifier_call"),
    ],
    ids=["model-error", "unparsable", "guard", "verifier-yes", "verifier-error"],
)
def test_any_doubt_keeps_codes_wording_and_never_raises(script: tuple[object, ...], why: str):
    shown, _ = asked_with(*script)
    assert shown == ExplainKept(why=why)


def test_a_guard_failure_never_reaches_the_verifier():
    _, chat = asked_with(ExplainWording(text="It deletes Jira “MOCK”."))
    assert asked_shapes(chat) == ["ExplainWording"]


def test_the_log_holds_the_reply_id_and_the_check_never_the_words(
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.WARNING):
        asked_with(ExplainWording(text=SMOOTHED.replace("“MOCK”", "“SECRET-PLACE”", 1)))
    logged = caplog.text
    assert "Explain wording" in logged and "quotes" in logged
    assert "SECRET-PLACE" not in logged and "fastapi" not in logged


def client_with(chat: ScriptedChat | None) -> TestClient:
    runtime = replace(
        api_runtime(),
        chat_source=lambda access: None if chat is None else (lambda timeout: chat),
    )
    return TestClient(create_app(SETTINGS, runtime), headers={"X-Agent-Key": KEY})


def test_the_route_needs_the_key_and_says_when_no_model_is_connected():
    body = json.loads(FASTAPI.model_dump_json())
    answered = client_with(None).post("/v1/workflows/explain", json=body)
    assert answered.status_code == 200 and answered.json()["status"] == "problem"
    keyless = client_with(None)
    keyless.headers.pop("X-Agent-Key")
    assert keyless.post("/v1/workflows/explain", json=body).status_code == 401


@pytest.mark.parametrize(
    ("script", "kind"),
    [((ExplainWording(text=SMOOTHED), CLEAN), "reworded"), ((RuntimeError("down"),), "kept")],
)
def test_the_route_answers_in_the_contract(script: tuple[object, ...], kind: str):
    body = json.loads(FASTAPI.model_dump_json())
    answered = client_with(ScriptedChat(structured=list(script))).post(
        "/v1/workflows/explain", json=body
    )
    result = explain_wording_result_adapter.validate_python(answered.json())
    assert isinstance(result, ExplainReworded | ExplainKept) and result.kind == kind


def test_the_route_asks_the_verifier_on_the_model_the_setting_names():
    asked_for: list[str] = []
    writer = ScriptedChat(structured=[ExplainWording(text=SMOOTHED)])
    verifier = ScriptedChat(structured=[CLEAN])

    def chat_source(access: Any) -> Any:
        asked_for.append(access.model)
        chat = verifier if access.model == "the-verifier" else writer
        return lambda timeout: chat

    runtime = replace(api_runtime(), chat_source=chat_source)
    settings = replace(SETTINGS, verifier_model="the-verifier")
    client = TestClient(create_app(settings, runtime), headers={"X-Agent-Key": KEY})
    answered = client.post("/v1/workflows/explain", json=json.loads(FASTAPI.model_dump_json()))
    assert answered.json() == {"kind": "reworded", "text": SMOOTHED}
    assert asked_for == [FASTAPI.model.model, "the-verifier"]


MOCK_MODEL = Path(__file__).resolve().parents[2] / "e2e" / "mock_model" / "model_server.py"
REACT = request(
    "Every Monday at 9:00, it reads GitHub “facebook/react” and Jira “WEB”. "
    "It posts “A new React release is out.” in Slack “C0RELEASES”. It changes nothing.",
    fact("runs", "Monday", "9:00"),
    fact("reads", "reads", "GitHub", "facebook/react"),
    fact("reads", "reads", "Jira", "WEB"),
    fact("posts", "post", "Slack", "A new React release is out.", "C0RELEASES"),
    fact("changes", "changes", "nothing", negated=True),
)


def mock_reworded(asked: ExplainWordingRequest) -> str:
    spec = importlib.util.spec_from_file_location("mock_model_server", MOCK_MODEL)
    assert spec is not None and spec.loader is not None
    mock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock)
    system, user = wording_messages(asked)
    body = {
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "tools": [{"name": "ExplainWording"}],
        "tool_choice": {"type": "tool", "name": "ExplainWording"},
    }
    _, reply = mock.answer("POST", "/v1/messages", body)
    return cast(str, reply["content"][0]["input"]["text"])


@pytest.mark.skipif(not MOCK_MODEL.exists(), reason="e2e/ is not in the test image")
def test_the_mock_models_smoothing_passes_and_its_bad_one_is_refused():
    assert explain_guard(mock_reworded(FASTAPI), FASTAPI) is None
    assert explain_guard(mock_reworded(REACT), REACT) is not None
