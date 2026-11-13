import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from evals.answer import ANSWER, AnswerCase, _cant_checks, _card_checks, dropped, flipped
from evals.checks import Check, jargon, mentions, write_claims
from evals.choose import CHOOSE, ChooseCase
from evals.draft import DRAFT, DraftCase
from evals.explain import EXPLAIN, ExplainCase, Explanation
from evals.jobs import Answer, _structured_answer, marked
from evals.providers import Target, plan
from evals.runner import (
    JOBS,
    Outcome,
    jobs_chosen,
    main,
    model_for,
    redact,
    run_case,
    summarise_job,
)
from evals.summarise import SUMMARISE, SummariseCase, checked
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent_runtime.answers import TaskRead, answer_of
from agent_runtime.contract import CantRow, PartAnswer, RequestPart, SetupCardAnswer, UnderstoodRow
from agent_runtime.summary import SUMMARY_TIMEOUT_SECONDS, ModelSummarizer, template_check_summary


def failed(checks: list[Any]) -> set[str]:
    return {c.name for c in checks if not c.passed}


def text(value: str) -> Answer:
    return Answer(value, value, None)


LANGGRAPH_BEHIND = {
    "name": "LangGraph",
    "state": "behind",
    "newest": "1.2.16",
    "new_versions": ["1.2.16", "1.2.15"],
}


def summarise_case(*software: dict[str, Any]) -> SummariseCase:
    return SummariseCase.model_validate(
        {"id": "t", "note": "", "software": list(software) or [LANGGRAPH_BEHIND]}
    )


def explain_case(name: str) -> ExplainCase:
    return next(c for c in EXPLAIN.cases() if c.id == name)


@pytest.mark.parametrize(
    ("job", "most"), [(SUMMARISE, 15), (EXPLAIN, 15), (DRAFT, 15), (CHOOSE, 15)]
)
def test_each_job_has_a_small_golden_set_with_unique_ids(job: Any, most: int) -> None:
    ids = [case.id for case in job.cases()]
    assert 10 <= len(ids) <= most
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("case", SUMMARISE.cases(), ids=lambda c: c.id)
def test_the_runtime_template_summary_passes_every_summary_case(case: SummariseCase) -> None:
    assert failed(SUMMARISE.score(case, text(template_check_summary(checked(case))))) == set()


def test_the_eval_asks_exactly_what_the_product_asks() -> None:
    case = next(c for c in SUMMARISE.cases() if c.id == "fixture-six-mixed")
    sent: list[str] = []

    class Recording(GenericFakeChatModel):
        def invoke(self, prompt: Any, *args: Any, **kwargs: Any) -> Any:
            sent.append(prompt)
            return super().invoke(prompt, *args, **kwargs)

    model = Recording(messages=iter([AIMessage(content="LangGraph has a new release.")]))
    ModelSummarizer("any:model", factory=lambda name: model).summarise_check(checked(case))
    assert sent == [SUMMARISE.prompt(case)]


@pytest.mark.parametrize("case", EXPLAIN.cases(), ids=lambda c: c.id)
def test_each_explain_reference_passes_its_own_case(case: ExplainCase) -> None:
    answer = Answer(case.reference, case.reference.model_dump_json(), None)
    assert failed(EXPLAIN.score(case, answer)) == set()


@pytest.mark.parametrize(
    ("answer", "broken"),
    [
        ("LangGraph has new releases.", {"every_newest_version"}),
        ("There is a new release: 1.2.16.", {"names_behind_and_unchecked"}),
        ("LangGraph has new releases: 1.2.16 and 1.2.17.", {"no_invented_version"}),
        ("LangGraph on PyPI has 1.2.16.", {"no_invented_system"}),
        ("I created a Jira ticket for LangGraph 1.2.16.", {"no_write_claim", "no_invented_system"}),
        ("New releases:\nLangGraph 1.2.16", {"usable_by_product"}),
        ("The Scout found LangGraph 1.2.16.", {"no_themed_names"}),
        ("The API lists LangGraph 1.2.16.", {"no_jargon"}),
    ],
)
def test_a_flawed_summary_fails_the_check_that_names_its_flaw(
    answer: str, broken: set[str]
) -> None:
    assert failed(SUMMARISE.score(summarise_case(), text(answer))) == broken


def test_a_prefixed_tag_counts_by_its_version_number() -> None:
    case = summarise_case(
        {"name": "Terraform", "state": "behind", "newest": "v1.10.1", "new_versions": ["v1.10.1"]}
    )
    answer = text("Terraform has a new release, 1.10.1.")
    assert failed(SUMMARISE.score(case, answer)) == set()


def test_a_software_name_is_not_jargon_in_a_summary() -> None:
    case = summarise_case(
        {"name": "n8n", "state": "behind", "newest": "n8n@1.71.0", "new_versions": ["n8n@1.71.0"]}
    )
    assert failed(SUMMARISE.score(case, text("n8n has a new release, 1.71.0."))) == set()


def test_a_summary_must_name_the_software_that_could_not_be_checked() -> None:
    case = summarise_case(LANGGRAPH_BEHIND, {"name": "FastAPI", "state": "cant_check"})
    answer = text("LangGraph has a new release: 1.2.16.")
    assert failed(SUMMARISE.score(case, answer)) == {"names_behind_and_unchecked"}


@pytest.mark.parametrize(
    ("explanation", "retry_safe", "broken"),
    [
        (
            "Bob approved it, but Jira was down, so no ticket was made. Retry.",
            False,
            {"retry_safe_matches"},
        ),
        (
            "Bob approved it and the Jira ticket was created. Retry to be sure.",
            True,
            {"no_write_claim"},
        ),
        ("Bob approved it, but Jira returned 503 at the API. Retry.", True, {"no_jargon"}),
        ("Something went wrong. Retry.", True, {"required_facts"}),
        (
            "Bob approved it, but Jira was down, so MOCK-142 was never filed. " * 8,
            True,
            {"length_cap"},
        ),
    ],
)
def test_a_flawed_explanation_fails_the_check_that_names_its_flaw(
    explanation: str, retry_safe: bool, broken: set[str]
) -> None:
    value = Explanation(explanation=explanation, retry_safe=retry_safe)
    answer = Answer(value, value.model_dump_json(), None)
    result = failed(EXPLAIN.score(explain_case("jira-503-after-approval"), answer))
    assert broken <= result


def test_an_unparsed_answer_fails_as_not_answered() -> None:
    assert failed(EXPLAIN.score(explain_case("declined"), text("{not json"))) == {"answered"}


def test_a_reading_that_did_not_parse_is_kept_from_the_models_tool_call() -> None:
    """The run file shows what the model gave, so the next check can read why it failed."""
    raw = AIMessage(
        content="", tool_calls=[{"name": "TaskRead", "args": {"rows": [], "x": 1}, "id": "c1"}]
    )
    answer = _structured_answer({"raw": raw, "parsed": None, "parsing_error": ValueError()})
    assert answer.value is None
    assert json.loads(answer.text) == {"rows": [], "x": 1}
    plain = AIMessage(content="not a call")
    assert _structured_answer({"raw": plain, "parsed": None}).text == "not a call"


@pytest.mark.parametrize(
    "sentence",
    [
        "No ticket was created.",
        "The ticket was not created.",
        "Jira wasn't able to create the ticket, so nothing was written.",
        "Once approved, a ticket will be created.",
    ],
)
def test_a_denied_or_future_write_is_not_a_write_claim(sentence: str) -> None:
    assert write_claims(sentence) == []


@pytest.mark.parametrize(
    "sentence",
    ["The ticket was created in Jira.", "I have opened a new Jira ticket.", "We filed the issue."],
)
def test_a_past_write_is_a_write_claim(sentence: str) -> None:
    assert write_claims(sentence) != []


def test_jargon_finds_codes_identifiers_and_enum_names() -> None:
    found = jargon("GitHub gave 503 in run_agents, an AgentError, version 1.2.503")
    assert found == ["AgentError", "503", "run_agents"]


def test_a_model_that_raises_is_scored_as_not_answered_without_leaking_the_key() -> None:
    class Boom(GenericFakeChatModel):
        def invoke(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("401 bad key sk-ant-abc123def456ghi")

    model = Boom(messages=iter([AIMessage(content="")]))
    outcome = run_case(model, SUMMARISE, summarise_case(), {"ANTHROPIC_API_KEY": "abc"})
    assert not outcome.passed
    assert "sk-ant" not in outcome.checks[0].detail


def test_redact_removes_a_configured_key_value() -> None:
    assert redact("key=s3cr3t-value", {"GOOGLE_API_KEY": "s3cr3t-value"}) == "key=[redacted]"


def test_endpoints_and_keys_never_reach_the_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama = "http://bakeoff-user:ollama-pass-9@ollama-box.private.example:11434"
    endpoint = "https://bakeoff-private-9.openai.azure.com/"
    key = "azure-key-value-9"

    def unreachable(url: str, **kwargs: Any) -> Any:
        raise httpx.ConnectError(f"cannot connect to {url}")

    class Down(GenericFakeChatModel):
        def invoke(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(f"Connection error at {endpoint}openai/deployments/d1 with {key}")

    monkeypatch.setattr("evals.providers.httpx.get", unreachable)
    monkeypatch.setattr(Target, "build", lambda self: Down(messages=iter([])))
    env = {
        "OLLAMA_BASE_URL": ollama,
        "AZURE_OPENAI_API_KEY": key,
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_API_VERSION": "2026-01-01",
        "AZURE_OPENAI_DEPLOYMENTS": "d1",
    }
    out = tmp_path / "results.json"

    assert main(out, env) == 0

    report = json.loads(out.read_text())
    assert {(n["provider"], n["model"]) for n in report["not_run"]} >= {
        ("ollama", "gemma:2b"),
        ("azure_openai", "d1"),
    }
    written = out.read_text() + capsys.readouterr().out
    for value in (ollama, endpoint, key, "ollama-pass-9", "ollama-box", "bakeoff-private-9"):
        assert value not in written


def test_a_provider_without_its_key_is_planned_as_not_run() -> None:
    targets, not_run = plan({"ANTHROPIC_MODELS": "claude-haiku-5-5"})
    assert targets == []
    assert {n.provider for n in not_run} == {
        "ollama",
        "azure_openai",
        "anthropic",
        "google_genai",
        "gateway",
    }
    assert all(n.reason.startswith("not set:") for n in not_run)


def test_a_cloud_provider_with_a_key_runs_its_default_models() -> None:
    targets, _ = plan({"ANTHROPIC_API_KEY": "x"})
    assert [t.label for t in targets] == [
        "anthropic:claude-haiku-5-5",
        "anthropic:claude-sonnet-5-5",
    ]
    assert all("temperature" not in t.kwargs for t in targets)


def test_every_job_is_registered_once() -> None:
    assert [job.name for job in JOBS] == [
        "summarise",
        "explain",
        "draft",
        "choose",
        "answer",
    ]


@pytest.mark.parametrize(
    ("text", "term", "found"),
    [
        ("Here is the report.", "repo", False),
        ("Check the repo name.", "repo", True),
        ("The download failed.", "down", False),
        ("GitHub was down.", "down", True),
        ("Bob approved it.", "approv*", True),
        ("Bob disapproved it.", "approv*", False),
        ("It wasn't set up.", "wasn't set up", True),
    ],
)
def test_a_fact_term_matches_whole_words_or_a_marked_stem(
    text: str, term: str, found: bool
) -> None:
    assert mentions(text, term) is found


STOCK = "The run failed and stopped. Nothing was changed or written."


@pytest.mark.parametrize("case", EXPLAIN.cases(), ids=lambda c: c.id)
def test_no_fact_term_is_satisfied_by_a_stock_phrase(case: ExplainCase) -> None:
    assert [t for group in case.must_mention for t in group if mentions(STOCK, t)] == []


def explanation(text: str, retry_safe: bool) -> Answer:
    value = Explanation(explanation=text, retry_safe=retry_safe)
    return Answer(value, value.model_dump_json(), None)


def test_nothing_was_changed_is_not_the_fact_that_the_approved_ticket_changed() -> None:
    answer = explanation("The safety checker blocked the write. Nothing was changed.", False)
    assert "required_facts" in failed(EXPLAIN.score(explain_case("safety-denied"), answer))


def test_no_connector_counts_as_saying_the_use_case_cannot_do_it() -> None:
    answer = explanation("The run stopped because there is no connector for that step.", False)
    assert "required_facts" not in failed(EXPLAIN.score(explain_case("unbound-intent"), answer))


@pytest.mark.parametrize(
    "text",
    ["Two endpoints failed.", "The APIs are down.", "A Rest-API call failed.", "Run_agents broke."],
)
def test_jargon_catches_plurals_hyphens_and_identifiers_in_any_case(text: str) -> None:
    assert jargon(text) != []


def outcome(latency_ms: float | None, tokens: tuple[int, int] = (100, 10)) -> Outcome:
    answered = latency_ms is not None
    return Outcome("c", [Check("answered", answered)], latency_ms, *tokens, "x" if answered else "")


def test_the_summary_job_has_the_products_time_limit() -> None:
    assert SUMMARISE.time_limit_s == SUMMARY_TIMEOUT_SECONDS
    assert EXPLAIN.time_limit_s is None


def test_a_summary_row_counts_answers_over_the_products_time_limit() -> None:
    outcomes = [outcome(9_000), outcome(10_000), outcome(12_000), outcome(None, (0, 0))]
    row = summarise_job(Target("anthropic", "m", {}), SUMMARISE, outcomes, {})
    assert [o["within_product_limit"] for o in row["outcomes"]] == [True, True, False, False]
    assert row["over_product_limit"] == 2


def test_errored_cases_do_not_lower_the_token_and_cost_means() -> None:
    pricing = {"anthropic:m": {"input_usd_per_mtok": 1, "output_usd_per_mtok": 1, "source": "t"}}
    outcomes = [outcome(1_000, (100, 10)), outcome(1_000, (300, 30)), outcome(None, (0, 0))]
    row = summarise_job(Target("anthropic", "m", {}), EXPLAIN, outcomes, pricing)
    assert (row["tokens"]["input_mean"], row["tokens"]["output_mean"]) == (200, 20)
    assert row["cost_per_100_runs_usd"] == round(220 / 1_000_000 * 100, 4)
    assert row["over_product_limit"] is None


def test_the_summary_job_gets_no_retries_like_the_product(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []

    def build(self: Target, **overrides: Any) -> Any:
        built.append(overrides)
        return f"built {overrides}"

    monkeypatch.setattr(Target, "build", build)
    cloud = Target("anthropic", "m", {"timeout": 120, "max_retries": 2})
    local = Target("ollama", "g", {"seed": 7})
    shared: Any = "shared"
    assert model_for(SUMMARISE, cloud, shared) == "built {'max_retries': 0}"
    assert model_for(EXPLAIN, cloud, shared) == "shared"
    assert model_for(SUMMARISE, local, shared) == "shared"
    assert built == [{"max_retries": 0}]


@pytest.mark.parametrize("case", DRAFT.cases(), ids=lambda c: c.id)
def test_each_draft_reference_passes_its_own_case(case: DraftCase) -> None:
    answer = Answer(case.reference, case.reference.model_dump_json(), None)
    assert failed(DRAFT.score(case, answer)) == set()


@pytest.mark.parametrize("case", CHOOSE.cases(), ids=lambda c: c.id)
def test_each_choose_reference_passes_its_own_case(case: ChooseCase) -> None:
    answer = Answer(case.reference, case.reference.model_dump_json(), None)
    assert failed(CHOOSE.score(case, answer)) == set()


def draft_case(name: str) -> DraftCase:
    return next(c for c in DRAFT.cases() if c.id == name)


def choose_case(name: str) -> ChooseCase:
    return next(c for c in CHOOSE.cases() if c.id == name)


def draft_answer(case: DraftCase, **changes: Any) -> Answer:
    value = case.reference.model_copy(update=changes)
    return Answer(value, value.model_dump_json(), None)


def test_a_draft_with_an_unlisted_tool_or_no_target_input_fails_those_checks() -> None:
    case = draft_case("release-and-ticket")
    blocks = [*case.reference.blocks]
    blocks[0] = blocks[0].model_copy(update={"tool": "github.delete_repo"})
    assert "only_listed_tools" in failed(DRAFT.score(case, draft_answer(case, blocks=blocks)))
    no_project = [i for i in case.reference.inputs if i.kind != "jira_project"]
    assert "write_has_target_input" in failed(
        DRAFT.score(case, draft_answer(case, inputs=no_project))
    )


def test_a_draft_with_an_invented_project_or_old_name_fails() -> None:
    case = draft_case("project-not-named")
    blocks = [case.reference.blocks[0].model_copy(update={"say": "Open it in project ABC."})]
    assert "no_invented_keys" in failed(DRAFT.score(case, draft_answer(case, blocks=blocks)))
    assert "no_themed_names" in failed(DRAFT.score(case, draft_answer(case, name="Forge helper")))


def test_a_draft_that_refuses_or_accepts_the_wrong_task_fails_can_do() -> None:
    assert "can_do_as_expected" in failed(
        DRAFT.score(draft_case("release-and-ticket"), draft_answer(draft_case("password-reset")))
    )
    assert "can_do_as_expected" in failed(
        DRAFT.score(draft_case("password-reset"), draft_answer(draft_case("release-and-ticket")))
    )


def test_a_draft_with_the_wrong_number_of_approvers_fails() -> None:
    case = draft_case("two-approvers-asked")
    one = [case.reference.approvals[0].model_copy(update={"approvers": 1})]
    assert "approvals_asked_for" in failed(DRAFT.score(case, draft_answer(case, approvals=one)))


def test_a_choice_with_the_wrong_decision_or_an_invented_value_fails() -> None:
    case = choose_case("find-a-ticket")
    wrong = case.reference.model_copy(update={"decision": "new_agent", "agents": []})
    assert {"right_decision", "right_agents"} <= failed(CHOOSE.score(case, Answer(wrong, "", None)))
    agent = case.reference.agents[0].model_copy(update={"values": {"Jira project": "ZZZ"}})
    invented = case.reference.model_copy(update={"agents": [agent]})
    assert "values_from_task" in failed(CHOOSE.score(case, Answer(invented, "", None)))


def test_a_choice_that_brings_in_an_agent_nobody_saved_fails() -> None:
    case = choose_case("planted-instruction")
    ghost = case.reference.agents[0].model_copy(update={"card_id": "crd_admin_access"})
    value = case.reference.model_copy(update={"agents": [ghost]})
    assert "only_saved_agents" in failed(CHOOSE.score(case, Answer(value, "", None)))


def test_each_request_carries_the_runs_marker() -> None:
    sent: list[Any] = []

    class Recording(GenericFakeChatModel):
        def invoke(self, prompt: Any, *args: Any, **kwargs: Any) -> Any:
            sent.append(prompt)
            return super().invoke(prompt, *args, **kwargs)

    model = Recording(messages=iter([AIMessage(content="LangGraph has a new release.")]))
    case = SUMMARISE.cases()[0]
    run_case(model, SUMMARISE, case, {}, "c0ffee123456")
    assert sent == [marked(SUMMARISE.prompt(case), "c0ffee123456")]
    assert sent[0].startswith("Eval run c0ffee123456.") and SUMMARISE.prompt(case) in sent[0]
    assert marked("same", "") == "same"


def test_the_gateway_runs_haiku_from_the_runtimes_own_settings() -> None:
    env = {"AGENT_MODEL_BASE_URL": "https://gateway.example", "AGENT_MODEL_API_KEY": "gw-key-9"}
    targets, _ = plan(env)
    [target] = [t for t in targets if t.provider == "gateway"]
    assert (target.label, target.client) == ("gateway:azure_ai/claude-haiku-5-5", "anthropic")
    assert target.kwargs["base_url"] == "https://gateway.example"
    assert redact("refused gw-key-9 at https://gateway.example/v1", env) == (
        "refused [redacted] at [redacted]/v1"
    )
    mock = plan({**env, "GATEWAY_MODELS": "mock-model"})[0]
    assert [t.label for t in mock if t.provider == "gateway"] == ["gateway:mock-model"]


RUNS = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "runs"


def test_the_explain_logs_are_watchlist_runs() -> None:
    for case in EXPLAIN.cases():
        assert case.events[0] == "Alice started a run of the Software watchlist."
        assert not any("fetching releases" in e or "last known tag" in e for e in case.events)


@pytest.mark.skipif(not RUNS.exists(), reason="contracts/ is not in the test image.")
@pytest.mark.parametrize(
    ("case_id", "story"), [("github-503-fixture", "failure"), ("declined", "rejected")]
)
def test_the_recorded_explain_cases_replay_their_recorded_run(case_id: str, story: str) -> None:
    recorded = [e["summary"] for e in json.loads((RUNS / f"{story}.json").read_text())]
    assert explain_case(case_id).events == recorded[:-1]


def answer_case(name: str) -> AnswerCase:
    return next(c for c in ANSWER.cases() if c.id == name)


def read_answer(**fields: Any) -> Answer:
    read = TaskRead.model_validate({"skips_the_yes": {"whose": "nobody"}, **fields})
    return Answer(read, read.model_dump_json(), None)


EMAIL_READ = {
    "name": "Stale ticket list",
    "schedule": "weekly",
    "search": {"updated": {"how": "before", "days": 14}, "said": "stale tickets"},
}


def test_every_answer_case_names_a_kind_or_a_kind_to_avoid():
    cases = ANSWER.cases()
    assert len(cases) >= 40
    assert all(c.kind or c.not_kind for c in cases)


def test_the_answer_job_scores_the_decided_answer_not_the_reading():
    case = answer_case("email-stale-list")
    assert failed(ANSWER.score(case, read_answer(**EMAIL_READ))) == set()
    claimed = {**EMAIL_READ, "ticket": {"creates": False, "says": "list", "said": "list"}}
    assert failed(ANSWER.score(case, read_answer(**claimed))) == set()
    bare = {"name": "Stale ticket list"}
    checks = ANSWER.score(case, read_answer(**bare))
    assert failed(checks) == {"offers_alternative", "reads_the_parts"}


def test_a_guessed_time_and_an_invented_key_fail_the_card():
    read = {
        "name": "Weekly summary",
        "schedule": "Every Friday at 5pm",
        "search": {"status": "done", "done": {"how": "within", "days": 7}, "said": "closed"},
        "ticket": {"creates": True, "says": "summary", "said": "sum up"},
        "place": {"project": "SUP", "said": "SUP"},
    }
    case = answer_case("day-one-weekly-summary")
    checks = ANSWER.score(case, read_answer(**read))
    assert failed(checks) == {"reads_the_parts", "schedule_state"}
    shown = answer_of(
        TaskRead.model_validate({"skips_the_yes": {"whose": "nobody"}, **read}), case.task
    )
    assert isinstance(shown, SetupCardAnswer) and shown.rows[0].state == "missing"
    assert shown.rows[0].note == 'Your words said "Every Friday" but not a time. Please choose one.'
    assert shown.rows[3].state == "missing"
    guessed = shown.model_copy(
        update={
            "rows": [
                shown.rows[0].model_copy(
                    update={"text": "Every Monday at 5pm", "state": "changed"}
                ),
                shown.rows[1],
                shown.rows[2],
                shown.rows[3].model_copy(
                    update={"text": "Jira project SUP", "state": "understood"}
                ),
            ]
        }
    )
    checks = _card_checks(case, guessed)
    assert next(c.detail for c in checks if c.name == "no_guessed_time") == "5"
    assert next(c.detail for c in checks if c.name == "no_invented_keys") == "SUP"


@pytest.mark.parametrize(
    ("case_id", "offered"),
    [
        ("filter-by-component", "Bug tickets in MOCK from every components"),
        ("filter-by-priority", "Tickets in MOCK of all priorities"),
    ],
)
def test_a_card_that_offers_the_field_in_any_word_form_fails_keeps_out(case_id: str, offered: str):
    case = answer_case(case_id)
    cant = [
        CantRow(kind="look_for", text=case.task, note="Can't.", needs="new_tool", system="Jira")
    ]
    rows = [
        UnderstoodRow(kind="schedule", text="", state="missing", note="Not said."),
        UnderstoodRow(kind="look_for", text=offered, state="changed", note="Suggested."),
        UnderstoodRow(kind="do", text="List them", state="understood"),
        UnderstoodRow(kind="where", text="", state="missing", note="Not said."),
    ]
    shown = PartAnswer(name="Bug list", rows=rows, cant=cant)
    assert failed(_cant_checks(case, shown)) == {"keeps_out"}
    clean = shown.model_copy(
        update={
            "rows": [rows[0], rows[1].model_copy(update={"text": "Bug tickets in MOCK"}), *rows[2:]]
        }
    )
    assert failed(_cant_checks(case, clean)) == set()


def test_a_refusal_and_a_question_are_scored_on_their_kind_and_words():
    checks = ANSWER.score(answer_case("without-approval"), read_answer())
    assert failed(checks) == set()
    checks = ANSWER.score(answer_case("by-itself"), read_answer(asks_about="abilities"))
    assert failed(checks) == set()
    said = read_answer(asks_about="why_stopped", workflow_words="Morning new-ticket check")
    assert failed(ANSWER.score(answer_case("why-did-it-stop"), said)) == set()
    wrong = read_answer(asks_about="why_stopped", workflow_words="Weekly summary")
    assert failed(ANSWER.score(answer_case("why-did-it-stop"), wrong)) == {"names_the_workflow"}


def test_a_mixed_request_is_scored_on_the_watchlist_and_the_rest():
    read = {
        "belongs_on_watchlist": True,
        "watchlist_word": "releases",
        "software": "React",
        "name": "Stale bug list",
        "schedule": "Every Friday",
        "search": {
            "issue_types": ["bug"],
            "updated": {"how": "before", "days": 14},
            "said": "stale bug tickets",
        },
        "ticket": {"creates": False, "says": "list", "said": "list"},
    }
    assert failed(ANSWER.score(answer_case("mixed-watch-and-list"), read_answer(**read))) == set()
    alone = read_answer(belongs_on_watchlist=True, watchlist_word="releases", software="React")
    assert failed(ANSWER.score(answer_case("mixed-watch-and-list"), alone)) == {
        "carries_the_rest",
        "reads_the_parts",
        "right_kind",
    }


def test_only_the_jobs_named_in_eval_jobs_run():
    assert [j.name for j in jobs_chosen({"EVAL_JOBS": "answer"})] == ["answer"]
    assert [j.name for j in jobs_chosen({"EVAL_JOBS": " choose, answer "})] == ["choose", "answer"]
    assert jobs_chosen({}) == JOBS
    with pytest.raises(ValueError, match="no job: nope"):
        jobs_chosen({"EVAL_JOBS": "nope"})


def test_a_word_rule_refusal_scores_as_the_product_answers_even_when_the_reading_did_not_parse():
    """The product refuses before the model is asked, so a reading that does not parse never
    reaches the person on such a case; the scorer scores the refusal, not the parse."""
    case = answer_case("no-need-to-sign-off")
    checks = ANSWER.score(case, Answer(None, "<not json", None))
    assert failed(checks) == set()
    case = answer_case("find-bugs-in-mock")
    checks = ANSWER.score(case, Answer(None, "<not json", None))
    assert failed(checks) == {"answered"}


SUMMARY_READ = {
    "schedule": "Every Friday",
    "search": {"status": "done", "done": {"how": "within", "days": 7}, "said": "closed"},
    "ticket": {"creates": False, "says": "summary", "said": "sum up"},
}


def test_a_clause_left_out_of_the_reading_must_come_back_as_a_cross():
    case = answer_case("r4-not-followed-colour")
    assert failed(ANSWER.score(case, read_answer(**SUMMARY_READ))) == set()


@pytest.mark.parametrize("how", ["before", "within"])
def test_a_negated_update_passes_as_no_update_or_as_a_cross_never_as_a_tick(how: str):
    search = {"issue_types": ["bug"], "updated": {"how": how, "days": 10}, "said": "bug tickets"}
    reading = read_answer(schedule="Every Friday", search=search, ticket=SUMMARY_READ["ticket"])
    assert failed(ANSWER.score(answer_case("r4-stale-havent"), reading)) == set()


def test_a_clash_is_scored_on_the_schedule_and_its_reason():
    case = answer_case("r4-clash-days")
    assert (
        failed(ANSWER.score(case, read_answer(**{**SUMMARY_READ, "schedule": "Every Monday at 9"})))
        == set()
    )


def test_a_refusal_keeps_the_question_asked_with_it_without_any_reading():
    case = answer_case("r4-question-with-skip")
    assert failed(ANSWER.score(case, Answer(None, "", None))) == set()


def test_a_clause_with_no_part_fails_keeps_or_flags_each_part():
    task = "Every Friday, sum up the closed tickets and colour them by team"
    kept = [
        RequestPart(text="Every Friday", mark="will_do"),
        RequestPart(text="sum up the closed tickets", mark="will_do"),
    ]
    assert dropped(task, kept) == ["dropped: colour them by team"]
    crossed = RequestPart(text="colour them", mark="cant", reason="not_followed")
    assert dropped(task, [*kept, crossed]) == []
    assert dropped("Every Friday, list the open bugs, thanks", kept[:1]) == [
        "dropped: list the open bugs"
    ]


def test_a_request_that_says_no_update_fails_on_an_update_within_some_days():
    row = UnderstoodRow(
        kind="look_for", text="Bug tickets, updated in the last 10 days", state="understood"
    )
    far = "Every Friday, list bugs in MOCK that nobody on the duty team has updated for 10 days"
    assert flipped(far, [row]) == ["flipped: Bug tickets, updated in the last 10 days"]
    assert flipped("Every Friday, list bugs updated in the last 10 days", [row]) == []


@pytest.mark.parametrize(
    ("case_id", "read"),
    [
        ("r7-edit-mondays", {"asks_about": "change", "workflow_words": "morning new-ticket check"}),
        ("r7-edit-instead", {"asks_about": "change", "workflow_words": "the weekly summary"}),
        ("r7-edit-react", {"asks_about": "change", "workflow_words": "React check"}),
        ("r7-edit-rename", {"asks_about": "change", "workflow_words": "morning check"}),
        ("r7-edit-monthly", {"asks_about": "change", "workflow_words": "morning check"}),
        ("r7-edit-two-days", {"asks_about": "change"}),
        ("r7-command-pause", {"asks_about": "needs_me"}),
        ("r7-command-daily", {"asks_about": "my_workflows", "workflow_words": "weekly summary"}),
        ("r7-name-next-run", {"asks_about": "my_workflows", "workflow_words": "weekly summary"}),
        ("r7-name-holds-weekly", {"asks_about": "my_workflows"}),
        (
            "c6-pause-react",
            {"asks_about": "change", "workflow_words": "React check", "software": "React"},
        ),
        (
            "c6-resume-react",
            {"asks_about": "change", "workflow_words": "React check", "software": "React"},
        ),
        (
            "c6-watch-and-email",
            {"belongs_on_watchlist": True, "watchlist_word": "watch", "software": "Kubernetes"},
        ),
        ("c6-teams-channel", {}),
        ("c6-delete-mock", {}),
    ],
)
def test_each_edit_case_passes_on_a_good_reading(case_id: str, read: dict[str, Any]) -> None:
    assert failed(ANSWER.score(answer_case(case_id), read_answer(**read))) == set()


def test_a_cant_in_its_own_words_fails_the_one_liner_check() -> None:
    case = answer_case("c6-teams-channel").model_copy(update={"one_liner": "I can’t do that."})
    assert "says_the_one_liner" in failed(ANSWER.score(case, read_answer()))


def test_an_edit_with_the_wrong_schedule_or_cant_fails_the_check_that_names_it() -> None:
    wrong = read_answer(asks_about="change", workflow_words="morning new-ticket check")
    case = answer_case("r7-edit-mondays").model_copy(
        update={"task": "Make the morning new-ticket check run on Tuesdays"}
    )
    assert failed(ANSWER.score(case, wrong)) == {"reads_the_new_schedule"}
    case = answer_case("r7-edit-rename").model_copy(
        update={"task": "Make the morning check run daily"}
    )
    assert failed(ANSWER.score(case, wrong)) >= {"names_the_change_it_cant_make"}
