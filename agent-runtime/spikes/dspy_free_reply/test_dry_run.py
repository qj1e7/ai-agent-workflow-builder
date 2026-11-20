"""The paid steps run end to end on fake models, so a real run fails only on the model's words.

Run with `uv run --group spike pytest spikes/dspy_free_reply`. No key, no network."""

import json
from pathlib import Path
from typing import Any

import dspy
import pytest
from dspy.utils.dummies import DummyLM
from evals.runner import Verdict as Judged
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

from agent_runtime.answers import TaskRead
from agent_runtime.contract import ReplyEnvelope
from agent_runtime.questions import QuestionReply
from agent_runtime.reading import SkipRead
from agent_runtime.reply_verifier import Verdict as Verifier
from spikes.dspy_free_reply import run, scoring
from spikes.dspy_free_reply.cases import all_cases
from spikes.dspy_free_reply.wrapper import FreeReply, ProductAdapter

HELPFUL = ReplyEnvelope(form="answer", text="Hi. Type what you want done in the box on Home.")
CLAIMS_DONE = ReplyEnvelope(form="answer", text="I created the workflow for you.")


class ByShape(BaseChatModel):
    """Answers each structured call with the answer held for its shape, and records the shapes."""

    answers: dict[Any, Any]
    asked: list[str] = Field(default_factory=list[str])

    @property
    def _llm_type(self) -> str:
        return "by-shape"

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise AssertionError("the spike makes structured calls only")

    def with_structured_output(  # type: ignore[override]
        self, schema: Any, include_raw: bool = False, **kwargs: Any
    ) -> Runnable[Any, Any]:
        def answer(_: Any) -> Any:
            self.asked.append(f"{schema.__module__.split('.')[-1]}.{schema.__name__}")
            parsed = self.answers[schema]
            if include_raw:
                return {"raw": AIMessage(""), "parsed": parsed, "parsing_error": None}
            return parsed

        return RunnableLambda(answer)


def fake(envelope: ReplyEnvelope, judged: int = 5) -> ByShape:
    return ByShape(
        answers={
            TaskRead: TaskRead(skips_the_yes=SkipRead(whose="nobody"), asks_about="abilities"),
            QuestionReply: QuestionReply(about_their_data=False),
            ReplyEnvelope: envelope,
            Verifier: Verifier(says_it_happened=False, skips_a_yes=False, claims_unbuilt=False),
            Judged: Judged(score=judged),
        }
    )


def use_dspy(model: ByShape) -> None:
    """The wrapper on the fake model; DSPy's own LM must never be called."""
    dspy.configure(lm=DummyLM([]), adapter=ProductAdapter(model))


def test_both_paths_show_the_same_reply_from_one_reading() -> None:
    case = all_cases()["reply:chat-01"]
    model = fake(HELPFUL)
    use_dspy(model)
    frozen, by_eval = run.eval_path(model, model, case)
    assert by_eval is not None
    by_wrapper = run.wrapper_path(FreeReply(), model, model, case, frozen)
    assert by_wrapper is not None
    assert (by_eval.kind, by_eval.fell_back, by_eval.judge) == ("reply:answer", None, 5)
    assert (by_wrapper.kind, by_wrapper.shown, by_wrapper.judge) == (
        by_eval.kind,
        by_eval.shown,
        5,
    )
    assert by_eval.score == by_wrapper.score == 1.0
    assert model.asked == [
        "reading.TaskRead",
        "contract.ReplyEnvelope",
        "reply_verifier.Verdict",
        "runner.Verdict",
        "contract.ReplyEnvelope",
        "reply_verifier.Verdict",
        "runner.Verdict",
    ]
    assert scoring.Frozen.of(frozen.record()).gap(case) == frozen.gap(case)


@pytest.mark.parametrize("case_id", ["reply:chat-01", "reply:approver-13", "anything:hi"])
def test_the_baseline_reads_and_routes_as_the_eval_path_does(case_id: str) -> None:
    case = all_cases()[case_id]
    model = fake(HELPFUL)
    use_dspy(model)
    by_eval, _ = run.eval_path(model, model, case)
    model.asked.clear()
    by_baseline = scoring.read_and_route(model, case)
    lane = ["questions.QuestionReply"] if by_eval.lane_asked else []
    assert model.asked == ["reading.TaskRead", *lane]
    assert by_baseline == by_eval
    assert by_baseline.gap(case) is not None


def test_a_reply_the_guard_stops_falls_back_scores_0_and_skips_the_verifier() -> None:
    case = all_cases()["reply:chat-01"]
    model = fake(HELPFUL, judged=2)
    use_dspy(model)
    frozen, _ = run.eval_path(model, model, case)
    model.answers[ReplyEnvelope] = CLAIMS_DONE
    model.asked.clear()
    shown = run.wrapper_path(FreeReply(), model, model, case, frozen)
    assert shown is not None
    assert (shown.guard, shown.fell_back, shown.kind, shown.score) == (
        "claims_done",
        "claims_done",
        "didnt_follow",
        0.0,
    )
    assert model.asked == ["contract.ReplyEnvelope", "runner.Verdict"]


def test_a_judge_1_scores_0() -> None:
    case = all_cases()["reply:chat-01"]
    model = fake(HELPFUL, judged=1)
    use_dspy(model)
    frozen, _ = run.eval_path(model, model, case)
    shown = run.wrapper_path(FreeReply(), model, model, case, frozen)
    assert shown is not None and shown.fell_back is None and shown.score == 0.0


def test_the_meter_stops_before_a_case_would_pass_the_round_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "spend.json"
    monkeypatch.setattr(scoring, "LEDGER", ledger)
    assert scoring.Meter("first").stop_reason() is None
    earlier = {"round": 1, "step": "earlier", "started": "x", "usd": 3.05}
    ledger.write_text(json.dumps({"runs": [earlier]}))
    assert scoring.Meter("next").stop_reason() is None
    spent = {"round": 4, "step": "earlier", "started": "y", "usd": 1.1}
    ledger.write_text(json.dumps({"runs": [earlier, spent]}))
    assert scoring.Meter("next").stop_reason() == "round 4's cap of $1.20"
    saved = scoring.Meter("next").save()
    assert saved["usd"] == 0 and json.loads(ledger.read_text())["total_usd"] == 4.15


def test_labels_spread_across_groups_and_drop_the_kind() -> None:
    rows = [
        {"case": f"{g}-{n}", "group": g, "shown": f"[reply:answer] reply {g} {n}"}
        for g in ("a", "b", "c")
        for n in range(5)
    ]
    picked = run._spread(rows, 6)  # pyright: ignore[reportPrivateUsage]
    assert sorted(r["group"] for r in picked) == ["a", "a", "b", "b", "c", "c"]
    assert run.shown_words(rows[0]) == "reply a 0"


def test_rejudge_only_judges_and_writes_set_b_blind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = fake(HELPFUL, judged=4)
    monkeypatch.setattr(scoring, "LEDGER", tmp_path / "spend.json")
    monkeypatch.setattr(run, "REJUDGE", tmp_path / "rejudge.json")
    monkeypatch.setattr(run, "BATCH2", tmp_path / "labels-batch2.json")
    monkeypatch.setattr(run, "planner", lambda: model)
    monkeypatch.setattr(run, "report", lambda title, summary: None)
    run.rejudge()
    assert model.asked == ["runner.Verdict"] * 100
    made = json.loads((tmp_path / "rejudge.json").read_text())
    assert [r["set"] for r in made] == ["A"] * 30 + ["B"] * 20
    assert all((r["v1"], r["v2"]) == (4, 4) for r in made)
    blind = json.loads((tmp_path / "labels-batch2.json").read_text())
    assert [set(r) for r in blind] == [{"id", "message", "reply"}] * 20
    assert sorted(r["id"] for r in blind) == sorted(r["id"] for r in made if r["set"] == "B")
    assert [r["id"] for r in blind] != [r["id"] for r in made if r["set"] == "B"]
    ledger = json.loads((tmp_path / "spend.json").read_text())
    assert [(r["round"], r["step"]) for r in ledger["runs"]] == [(scoring.ROUND, "rejudge")]


def test_rejudge3_judges_the_same_50_three_times_with_v3_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = fake(HELPFUL, judged=3)
    monkeypatch.setattr(scoring, "LEDGER", tmp_path / "spend.json")
    monkeypatch.setattr(run, "REJUDGE3", tmp_path / "rejudge3.json")
    monkeypatch.setattr(run, "planner", lambda: model)
    monkeypatch.setattr(run, "report", lambda title, summary: None)
    read: list[str] = []

    def v3(case: Any, words: str) -> str:
        read.append(words)
        return words

    monkeypatch.setattr(run, "judge_question_v3", v3)
    run.rejudge3()
    assert model.asked == ["runner.Verdict"] * 150
    made = json.loads((tmp_path / "rejudge3.json").read_text())
    before = json.loads(run.REJUDGE.read_text())
    assert sorted((r["id"], r["set"]) for r in made) == sorted((r["id"], r["set"]) for r in before)
    assert [r["id"] for r in made if r["set"] == "B"] == [
        r["id"] for r in json.loads(run.BATCH2.read_text())
    ]
    assert all(r["v3"] == [3, 3, 3] and r["v3_median"] == 3 for r in made)
    assert len(read) == 150 and all(w.startswith("[") for w in read)
    ledger = json.loads((tmp_path / "spend.json").read_text())
    assert [(r["round"], r["step"]) for r in ledger["runs"]] == [(4, "rejudge3")]


def test_parity2_runs_both_paths_twice_on_frozen_readings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = fake(HELPFUL)
    case_ids = ["reply:chat-01", "reply:approver-13"]
    store: dict[str, Any] = {}
    for case_id in case_ids:
        frozen, _ = run.eval_path(model, model, all_cases()[case_id])
        store[case_id] = frozen.record()
    model.asked.clear()
    monkeypatch.setattr(scoring, "LEDGER", tmp_path / "spend.json")
    monkeypatch.setattr(scoring, "RUNS", tmp_path)
    monkeypatch.setattr(run, "planner", lambda: model)
    monkeypatch.setattr(run, "frozen_store", lambda: store)
    monkeypatch.setattr(run, "load", lambda: {"score": [{"id": i} for i in case_ids]})
    monkeypatch.setattr(
        run, "write_run", lambda name, made: scoring.write_json(tmp_path / f"{name}.json", made)
    )
    monkeypatch.setattr(run, "report", lambda title, summary: None)
    run.parity2()
    made = json.loads((tmp_path / "parity2.json").read_text())
    summary = made["summary"]
    assert summary["cases"] == 2 and summary["passes"]
    assert summary["kind_agrees_across_paths"] == summary["kind_agrees_eval_with_itself"] == 2
    assert summary["useful_eval_per_run"] == summary["useful_wrapper_per_run"] == [2, 2]
    assert "reading.TaskRead" not in model.asked
    assert model.asked.count("contract.ReplyEnvelope") == 8
