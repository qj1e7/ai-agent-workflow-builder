import json
import logging
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest
from evals.budget import BUDGET_USED_UP, Spend, budget_spent, metered
from evals.providers import Target
from evals.runner import main
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

OWNER = "someone.else@example.com.sg"
BODY = {
    "error": {
        "message": f"Budget has been exceeded! TeamMember={OWNER}:679dd472-884d "
        "Current cost: 33.28, Max budget: 32.0",
        "type": "budget_exceeded",
        "code": "422",
    }
}
SUMMARY = "LangGraph has a new release, 1.2.16."


def gateway_error(status: int = 422, body: dict[str, Any] = BODY) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://gateway.invalid/v1/messages")
    error_class = anthropic.UnprocessableEntityError if status == 422 else anthropic.APIStatusError
    response = httpx2.Response(status, request=request)
    return error_class(f"Error code: {status} - {body}", response=response, body=body)


class Gateway(BaseChatModel):
    """A chat model that answers through LangChain's own call path, so callbacks see each call."""

    model: str = "m"
    replies: list[Any] = Field(default_factory=list[Any])

    @property
    def _llm_type(self) -> str:
        return "gateway-fake"

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> ChatResult:
        step = self.replies.pop(0) if self.replies else AIMessage(SUMMARY)
        if isinstance(step, Exception):
            raise step
        return ChatResult(generations=[ChatGeneration(message=step)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        return self

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, **kw: Any) -> Any:
        return super().with_structured_output(schema, include_raw=include_raw)


@pytest.mark.parametrize(
    ("error", "spent"),
    [
        (gateway_error(), True),
        (gateway_error(429, {"error": {"message": "insufficient_quota"}}), True),
        (gateway_error(429, {"error": {"message": "rate limit, retry in 2 s"}}), False),
        (gateway_error(500, {"error": {"message": "budget service down"}}), False),
    ],
)
def test_a_spent_budget_is_told_apart_from_a_rate_limit(error: Exception, spent: bool) -> None:
    assert budget_spent(error) == spent


def test_every_model_call_counts_with_its_price() -> None:
    usage = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}
    model = Gateway(replies=[AIMessage("a", usage_metadata=usage), AIMessage("b")])
    price = {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 5.0}
    with metered(Spend(max_calls=10, max_dollars=1.0, prices={"m": price})) as spend:
        model.invoke("one")
        model.invoke("two")
    model.invoke("not metered")
    assert spend.calls == 2
    assert spend.dollars == pytest.approx(0.0015)
    assert spend.stop_reason(8) is None
    assert spend.stop_reason(9) == "the cap of 10 model calls"


def run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], model: BaseChatModel
) -> dict[str, Any]:
    monkeypatch.setattr("evals.runner.plan", lambda env: ([Target("gateway", "m", {})], []))
    monkeypatch.setattr(Target, "build", lambda self, **overrides: model)
    out = tmp_path / "results.json"
    assert main(out, env) == 0
    return json.loads(out.read_text())


def test_a_run_stops_before_it_passes_the_call_cap_and_says_what_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {"EVAL_JOBS": "summarise", "EVAL_MAX_CALLS": "4"}
    results = run(tmp_path, monkeypatch, env, Gateway())
    assert [(r["job"], r["cases"], r["of"]) for r in results["results"]] == [("summarise", 3, 15)]
    assert results["spend"]["calls"] == 4
    assert results["spend"]["stopped"] == "the cap of 4 model calls"
    printed = capsys.readouterr().out
    assert "Spent 4 model calls" in printed and "Stopped early: the cap of 4 model calls" in printed
    assert "/3 (" in (tmp_path / "results.md").read_text()
    assert "), of 15 |" in (tmp_path / "results.md").read_text()


def test_a_run_stops_at_the_dollar_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    usage = {"input_tokens": 400_000, "output_tokens": 0, "total_tokens": 400_000}
    replies: list[Any] = [AIMessage(SUMMARY, usage_metadata=usage) for _ in range(20)]
    env = {"EVAL_JOBS": "summarise", "EVAL_MAX_DOLLARS": "1"}
    monkeypatch.setattr("evals.runner.PRICING", tmp_path / "pricing.json", raising=True)
    (tmp_path / "pricing.json").write_text(
        json.dumps(
            {"gateway:m": {"input_usd_per_mtok": 1, "output_usd_per_mtok": 1, "source": "t"}}
        )
    )
    results = run(tmp_path, monkeypatch, env, Gateway(replies=replies))
    assert results["spend"]["stopped"] == "the cap of $1.00"
    assert results["results"][0]["cases"] == 2


@pytest.mark.parametrize("where", ["warm-up", "a case", "the judge"])
def test_a_spent_gateway_budget_stops_the_run_and_its_body_reaches_no_output_or_log(
    where: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    env = {"EVAL_JOBS": "anything", "EVAL_MARKER": "m"}
    if where == "warm-up":
        model = Gateway(replies=[gateway_error()])
    elif where == "a case":
        model = Gateway(replies=[AIMessage("ready"), gateway_error()])
    else:
        env = {"EVAL_JOBS": "summarise", "EVAL_MARKER": "m"}
        model = Gateway()
        judge = Gateway(replies=[gateway_error()])
        monkeypatch.setattr(
            "evals.runner.build_judge", lambda env: (judge, Target("gateway", "j", {}), None)
        )
    results = run(tmp_path, monkeypatch, env, model)

    assert results["spend"]["stopped"] == BUDGET_USED_UP
    assert results["results"] == []
    assert any(BUDGET_USED_UP in n["reason"] for n in results["not_run"])
    shown = capsys.readouterr()
    written = (
        (tmp_path / "results.json").read_text()
        + (tmp_path / "results.md").read_text()
        + shown.out
        + shown.err
        + caplog.text
    )
    assert BUDGET_USED_UP in shown.out
    for leaked in (OWNER, "example.com", "TeamMember", "Budget has been exceeded", "33.28"):
        assert leaked not in written


@pytest.mark.parametrize("where", ["warm-up", "a case", "the judge's build"])
def test_any_other_provider_error_keeps_no_email_in_any_output(
    where: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    refused = gateway_error(403, {"error": {"message": f"key of {OWNER} may not use model m"}})
    env = {"EVAL_JOBS": "summarise", "EVAL_MARKER": "m", "EVAL_MAX_CALLS": "3"}
    model = Gateway(replies=[refused] if where == "warm-up" else [AIMessage("ready"), refused])
    if where == "the judge's build":
        model = Gateway()
        env["EVAL_JUDGE"] = "gateway:j"

        def unbuildable(env: dict[str, str]) -> Any:
            raise refused

        monkeypatch.setattr("evals.runner.judge_target", unbuildable)
    run(tmp_path, monkeypatch, env, model)
    shown = capsys.readouterr()
    written = (
        (tmp_path / "results.json").read_text()
        + (tmp_path / "results.md").read_text()
        + shown.out
        + shown.err
        + caplog.text
    )
    assert "[redacted]" in written
    assert OWNER not in written and "example.com" not in written
