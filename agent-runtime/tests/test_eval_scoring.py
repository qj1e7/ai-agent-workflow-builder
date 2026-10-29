import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from evals.checks import Check, jargon, mentions, write_claims
from evals.choose import CHOOSE, ChooseCase
from evals.draft import DRAFT, DraftCase
from evals.explain import EXPLAIN, ExplainCase, Explanation
from evals.jobs import Answer
from evals.providers import Target, plan
from evals.runner import JOBS, Outcome, main, model_for, redact, run_case, summarise_job
from evals.summarise import SUMMARISE, SummariseCase, template_summary
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent_runtime.summary import SUMMARY_TIMEOUT_SECONDS


def failed(checks: list[Any]) -> set[str]:
    return {c.name for c in checks if not c.passed}


def text(value: str) -> Answer:
    return Answer(value, value, None)


def summarise_case(**overrides: Any) -> SummariseCase:
    fields = {
        "id": "t",
        "note": "",
        "repo": "langchain-ai/langgraph",
        "last_known_tag": "1.2.14",
        "new_tags": ["1.2.16", "1.2.15"],
    }
    return SummariseCase.model_validate(fields | overrides)


def explain_case(name: str) -> ExplainCase:
    return next(c for c in EXPLAIN.cases() if c.id == name)


@pytest.mark.parametrize("job", [SUMMARISE, EXPLAIN, DRAFT, CHOOSE])
def test_each_job_has_10_to_15_cases_with_unique_ids(job: Any) -> None:
    ids = [case.id for case in job.cases()]
    assert 10 <= len(ids) <= 15
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("case", SUMMARISE.cases(), ids=lambda c: c.id)
def test_the_runtime_template_summary_passes_every_summary_case(case: SummariseCase) -> None:
    assert failed(SUMMARISE.score(case, text(template_summary(case.new_tags)))) == set()


@pytest.mark.parametrize("case", EXPLAIN.cases(), ids=lambda c: c.id)
def test_each_explain_reference_passes_its_own_case(case: ExplainCase) -> None:
    answer = Answer(case.reference, case.reference.model_dump_json(), None)
    assert failed(EXPLAIN.score(case, answer)) == set()


@pytest.mark.parametrize(
    ("answer", "broken"),
    [
        ("2 new releases: 1.2.16", {"every_new_version"}),
        ("2 new releases: 1.2.16, 1.2.15 and 1.2.17", {"no_invented_version"}),
        ("LangGraph on PyPI has 1.2.16 and 1.2.15", {"no_invented_system"}),
        ("I created a Jira ticket for 1.2.16 and 1.2.15", {"no_write_claim", "no_invented_system"}),
        ("New releases:\n1.2.16\n1.2.15", {"usable_by_product"}),
        ("The Scout found 1.2.16 and 1.2.15", {"no_themed_names"}),
        ("The API lists 1.2.16 and 1.2.15", {"no_jargon"}),
    ],
)
def test_a_flawed_summary_fails_the_check_that_names_its_flaw(
    answer: str, broken: set[str]
) -> None:
    assert failed(SUMMARISE.score(summarise_case(), text(answer))) == broken


def test_a_prefixed_tag_counts_by_its_version_number() -> None:
    case = summarise_case(last_known_tag="v1.9.8", new_tags=["v1.10.1", "v1.10.0"])
    answer = text("Terraform has two new releases after 1.9.8: 1.10.1 and 1.10.0.")
    assert failed(SUMMARISE.score(case, answer)) == set()


def test_a_word_from_the_repo_name_is_not_jargon_in_a_summary() -> None:
    case = summarise_case(repo="n8n-io/n8n", last_known_tag="n8n@1.70.0", new_tags=["n8n@1.71.0"])
    assert failed(SUMMARISE.score(case, text("n8n has a new release, 1.71.0."))) == set()


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
    assert {n.provider for n in not_run} == {"ollama", "azure_openai", "anthropic", "google_genai"}
    assert all(n.reason.startswith("not set:") for n in not_run)


def test_a_cloud_provider_with_a_key_runs_its_default_models() -> None:
    targets, _ = plan({"ANTHROPIC_API_KEY": "x"})
    assert [t.label for t in targets] == [
        "anthropic:claude-haiku-5-5",
        "anthropic:claude-sonnet-5-5",
    ]
    assert all("temperature" not in t.kwargs for t in targets)


def test_every_job_is_registered_once() -> None:
    assert [job.name for job in JOBS] == ["summarise", "explain", "draft", "choose"]


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
