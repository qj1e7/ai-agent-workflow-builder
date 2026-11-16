"""The eval's changes for ADR 0049 (decision 6): every model call counted in both modes, each
answer drawn with the marks it carries, false ticks counted by code, and the AI-led twins."""

import json
from pathlib import Path
from typing import Any

import pytest
from evals.budget import PRICE_KEY, cached_tokens, dollars_for, metered, spend_for
from evals.checks import false_ticks
from evals.providers import Target
from evals.reply import REPLY, REPLY_LED, SPIKE_LED
from evals.runner import AI_LED, PRICING, jobs_chosen, planner_mode, run_case
from langchain_core.messages import AIMessage

from agent_runtime.contract import Answered, AnswerRequest, RequestPart, WatchlistAnswer
from agent_runtime.contracts import answer_request
from agent_runtime.planner_led import Led, Shown, clauses_in
from tests.fakes import ScriptedChat, asks, call
from tests.test_eval_budget import Gateway
from tests.test_planner_led import CLEAN
from tests.test_questions import reading

PRICE = {"input_usd_per_mtok": 2.0, "output_usd_per_mtok": 10.0}


def reply_case(case_id: str) -> Any:
    return next(c for c in REPLY_LED.cases() if c.id == case_id)


def spike_case(case_id: str) -> Any:
    return next(c for c in SPIKE_LED.cases() if c.id == case_id)


def test_cached_input_is_priced_at_the_models_cache_prices() -> None:
    cached = {**PRICE, "cache_read_usd_per_mtok": 0.2, "cache_write_usd_per_mtok": 2.5}

    assert dollars_for(10_000, 100, 0, 0, PRICE) == pytest.approx(0.021)
    assert dollars_for(10_000, 100, 8_000, 0, cached) == pytest.approx(
        2_000 * 2e-6 + 8_000 * 0.2e-6 + 100 * 1e-5
    )
    assert dollars_for(10_000, 100, 0, 8_000, cached) == pytest.approx(
        2_000 * 2e-6 + 8_000 * 2.5e-6 + 100 * 1e-5
    )
    assert dollars_for(10_000, 100, 8_000, 0, PRICE) == dollars_for(10_000, 100, 0, 0, PRICE)


def test_the_cache_counts_come_from_the_calls_usage() -> None:
    usage = {"input_token_details": {"cache_read": 7, "cache_creation": 3}}
    assert cached_tokens(usage) == (7, 3)
    assert cached_tokens({}) == (0, 0)


def test_opus_5_5_is_priced_with_its_source_for_the_judge() -> None:
    prices = json.loads(Path(PRICING).read_text())
    opus = prices["anthropic:claude-opus-5-5"]

    assert (opus["input_usd_per_mtok"], opus["output_usd_per_mtok"]) == (4.0, 20.0)
    assert opus["cache_read_usd_per_mtok"] == 0.2 and "Anthropic" in opus["source"]


def test_ai_led_mode_runs_the_planners_jobs_on_the_ai_led_planner() -> None:
    names = "answer,anything,reply,spike,red_team"
    rules = jobs_chosen({"EVAL_JOBS": names})
    led = jobs_chosen({"EVAL_JOBS": names, "EVAL_PLANNER_MODE": "ai_led"})

    assert [j.name for j in led] == [j.name for j in rules]
    assert {j.name: j is AI_LED.get(j.name) for j in led} == {
        "answer": True,
        "anything": True,
        "reply": True,
        "spike": True,
        "red_team": False,
    }
    assert planner_mode({}) == "rules"
    with pytest.raises(ValueError, match="EVAL_PLANNER_MODE"):
        jobs_chosen({"EVAL_PLANNER_MODE": "free"})


def test_rules_mode_counts_every_call_a_message_makes() -> None:
    usage = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
    first = AIMessage("", usage_metadata=usage)

    class Counted(ScriptedChat):
        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            runnable = super().with_structured_output(schema, **kwargs)
            return runnable | (lambda reply: {**reply, "raw": first})

    from agent_runtime.contract import ReplyEnvelope

    chat = Counted(
        structured=[
            reading(),
            ReplyEnvelope(form="answer", text="Type what you want done in the box on Home."),
            CLEAN,
        ]
    )
    case = next(c for c in REPLY.cases() if c.id == "chat-01")

    outcome = run_case(chat, REPLY, case, {})

    assert (outcome.input_tokens, outcome.output_tokens) == (300, 30)


def test_the_judge_reads_the_marks_the_answer_carries() -> None:
    chat = ScriptedChat(
        script=[asks(call("show", {"what": "how_to_start"}, "c1"))], structured=[reading()]
    )

    outcome = run_case(chat, REPLY_LED, reply_case("how_to-17"), {})

    assert outcome.answer.startswith("[how_to_start] How to start:")


def test_the_team_leads_sentence_scores_as_asking_which_software() -> None:
    chat = ScriptedChat(
        script=[asks(call("ask_which_software", {"word": "software"}, "c1"))],
        structured=[reading("none")],
    )

    outcome = run_case(chat, SPIKE_LED, spike_case("add-01"), {})

    assert outcome.passed, [c for c in outcome.checks if not c.passed]
    assert {"right_kind", "asks_for_the_detail", "ticks_reached"} <= {
        c.name for c in outcome.checks
    }


def test_a_fallback_is_a_failed_check_with_why() -> None:
    bad = {"form": "answer", "text": "I set up the workflow."}
    chat = ScriptedChat(
        script=[asks(call("reply", bad, "c1")), asks(call("reply", bad, "c2"))],
        structured=[reading(), CLEAN],
    )

    outcome = run_case(chat, SPIKE_LED, spike_case("chat-01"), {})

    failed = {c.name: c.detail for c in outcome.checks if not c.passed}
    assert "claims_done" in json.dumps(failed["led_answer_shown"])


def test_a_tick_on_a_clause_no_argument_reaches_is_counted_by_code() -> None:
    text = "Add Kubernetes to the watchlist and tell me what needs me"
    first, second = clauses_in(text)
    answer = WatchlistAnswer(word="Kubernetes", software="Kubernetes")
    ticks = [
        RequestPart(text="Add Kubernetes to the watchlist", mark="will_do"),
        RequestPart(text="tell me what needs me", mark="will_do"),
    ]
    request = AnswerRequest(task=text, model=answer_request().model)

    def led_with(reached: frozenset[tuple[int, int]] | None) -> Led:
        answered = Answered(answer=answer, parts=ticks)
        return Led(answered, ("watch_software",), shown=Shown(answered, text, reached))

    assert false_ticks(led_with(frozenset({first}))) == ["tell me what needs me"]
    assert false_ticks(led_with(frozenset({first, second}))) == []
    assert false_ticks(led_with(None)) == []
    assert false_ticks(Led(Answered(answer=answer, parts=ticks))) == []
    assert request.task == text


def test_a_model_named_by_two_providers_has_one_price_with_its_cache_prices() -> None:
    """The run's spend line finds a price by the model's name alone, so two entries for one name
    must agree, or the later one silently prices the run (a gateway entry with no cache prices
    once priced every cached token as fresh input)."""
    prices = json.loads(Path(PRICING).read_text())
    by_name: dict[str, list[dict[str, Any]]] = {}
    for key, price in prices.items():
        by_name.setdefault(key.partition(":")[2], []).append(
            {k: v for k, v in price.items() if k != "source"}
        )

    assert all(all(p == shared[0] for p in shared) for shared in by_name.values()), by_name


def test_the_spend_line_prices_a_call_by_the_provider_and_model_that_built_it() -> None:
    usage = {"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000}
    pricing = {
        "anthropic:m": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 0.0},
        "gateway:m": {"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 0.0},
    }
    model = Gateway(
        replies=[AIMessage("x", usage_metadata=usage)],
        metadata={PRICE_KEY: "anthropic:m"},
    )

    with metered(spend_for({}, pricing)) as spend:
        model.invoke("one")

    assert spend.dollars == pytest.approx(1.0)


def test_a_target_builds_a_model_that_names_its_price() -> None:
    built = Target("anthropic", "claude-sonnet-5-5", {"api_key": "not-a-key"}).build()

    assert (built.metadata or {})[PRICE_KEY] == "anthropic:claude-sonnet-5-5"
