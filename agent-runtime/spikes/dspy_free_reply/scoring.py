"""The spike's model calls, its metric and its spend ledger.

Everything around the free reply is the product's or the reply job's own code: the reading and
the question lane as `evals.reply.follow_up` makes them, `dead_end`, the guard
(`answer_of_envelope`), the verifier's messages, `shown_for`, the reply job's `score`, its
`words_of` and its judge question. Only the free reply's own call changes path: the eval path's
LangChain call, or the DSPy wrapper.

The reading and the question lane run once per case and are frozen (`Frozen`), so later runs
vary only the free reply. The ledger counts every call: LangChain's through the evals' own
`Spend`, DSPy's from its history at `pricing.json`'s price, or LiteLLM's own cost when that is
higher. A cached DSPy answer costs nothing."""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from evals.budget import Spend
from evals.jobs import Answer, _structured_answer, marked  # pyright: ignore[reportPrivateUsage]
from evals.providers import Target, _cloud  # pyright: ignore[reportPrivateUsage]
from evals.reply import (
    Steps,
    _before_reply,  # pyright: ignore[reportPrivateUsage]
    _Calls,  # pyright: ignore[reportPrivateUsage]
    _kind,  # pyright: ignore[reportPrivateUsage]
    _structured,  # pyright: ignore[reportPrivateUsage]
    judge_question,
    prompt,
    request_of,
    score,
    shown_for,
    words_of,
)
from evals.runner import PRICING, judge, redact
from langchain_core.language_models import BaseChatModel

from agent_runtime.answers import AskTheQuestionLane, TaskRead, decide
from agent_runtime.contract import FreeReplyAnswer, PlannerAnswer, ReplyEnvelope
from agent_runtime.drafting import UNUSABLE
from agent_runtime.free_reply import STILL_UNCLEAR, DeadEnd, answer_of_envelope, dead_end
from agent_runtime.parts import parts_of
from agent_runtime.questions import QuestionReply, question_messages
from agent_runtime.reply_verifier import Verdict, flag_of, verify_messages
from spikes.dspy_free_reply.cases import SpikeCase

HERE: Final = Path(__file__).parent
RUNS: Final = HERE / "runs"
LEDGER: Final = HERE / "spend.json"
MODEL: Final = "claude-sonnet-5-5"
LABEL: Final = f"anthropic:{MODEL}"
ROUND: Final = 1
ROUND_CAP: Final = 4.0
SPIKE_CAP: Final = 30.0
RESERVE: Final = 0.08
"""More than one case can cost: the reading, the question lane, the free reply twice (DSPy's
JSON fallback), the verifier and the judge."""
SAFETY_CHECKS: Final = ("refuses_a_skip", "keeps_a_plain_write")
UNREPORTED_IN: Final = 8000
UNREPORTED_OUT: Final = 1000
"""What a billed DSPy call counts as when the engine reports no tokens: more than the free reply
ever takes, so a missing count can only overstate the spend."""


def env() -> dict[str, str]:
    return dict(os.environ)


def write_json(path: Path, data: Any) -> Path:
    """Every file the spike writes, with any key the process holds, any key shape and any email
    taken out first, as the eval runner does for its results."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(json.dumps(data, indent=2, ensure_ascii=False), env()) + "\n")
    return path


def price() -> dict[str, Any]:
    return json.loads(PRICING.read_text())[LABEL]


def planner() -> BaseChatModel:
    """The Planner and the judge, built as the eval runner builds them."""
    return Target("anthropic", MODEL, _cloud(env(), MODEL)).build()


# The ledger.


@dataclass
class Meter:
    """This run's spend, and the stop before a case would pass the round's or the spike's cap."""

    step: str
    lm: Any = None
    spend: Spend = field(
        default_factory=lambda: Spend(10**6, float("inf"), {}, json.loads(PRICING.read_text()))
    )
    started: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def __post_init__(self) -> None:
        ledger = self._ledger()
        self.before = sum(r["usd"] for r in ledger["runs"])
        self.before_round = sum(r["usd"] for r in ledger["runs"] if r["round"] == ROUND)

    @staticmethod
    def _ledger() -> dict[str, Any]:
        if LEDGER.exists():
            return json.loads(LEDGER.read_text())
        return {"round_cap": ROUND_CAP, "spike_cap": SPIKE_CAP, "runs": []}

    def dspy_spend(self) -> tuple[int, float, float]:
        """DSPy's billed calls, their cost at our price, and LiteLLM's own cost for them."""
        if self.lm is None:
            return 0, 0.0, 0.0
        cost = price()
        calls, ours, theirs = 0, 0.0, 0.0
        for entry in self.lm.history:
            if getattr(entry["response"], "cache_hit", False):
                continue
            usage = entry.get("usage") or {}
            calls += 1
            tokens_in = usage.get("prompt_tokens") or UNREPORTED_IN
            tokens_out = usage.get("completion_tokens") or UNREPORTED_OUT
            ours += (
                tokens_in * cost["input_usd_per_mtok"] + tokens_out * cost["output_usd_per_mtok"]
            ) / 1_000_000
            theirs += float(entry.get("cost") or 0.0)
        return calls, ours, theirs

    def usd(self) -> float:
        _, ours, theirs = self.dspy_spend()
        return self.spend.dollars + max(ours, theirs)

    def stop_reason(self) -> str | None:
        now = self.usd()
        if self.before_round + now + RESERVE > ROUND_CAP:
            return f"round {ROUND}'s cap of ${ROUND_CAP:.2f}"
        if self.before + now + RESERVE > SPIKE_CAP:
            return f"the spike's cap of ${SPIKE_CAP:.2f}"
        return None

    def save(self) -> dict[str, Any]:
        ledger = self._ledger()
        calls, ours, theirs = self.dspy_spend()
        run = {
            "round": ROUND,
            "step": self.step,
            "started": self.started,
            "langchain_calls": self.spend.calls,
            "langchain_usd": round(self.spend.dollars, 4),
            "dspy_calls": calls,
            "dspy_usd_at_our_price": round(ours, 4),
            "dspy_usd_litellm": round(theirs, 4),
            "usd": round(self.usd(), 4),
        }
        ledger["runs"] = [
            r for r in ledger["runs"] if (r["step"], r["started"]) != (self.step, self.started)
        ] + [run]
        ledger["total_usd"] = round(sum(r["usd"] for r in ledger["runs"]), 4)
        ledger["round_usd"] = {
            str(n): round(sum(r["usd"] for r in ledger["runs"] if r["round"] == n), 4)
            for n in sorted({r["round"] for r in ledger["runs"]})
        }
        write_json(LEDGER, ledger)
        return run


# The reading and the question lane, frozen per case.


@dataclass(frozen=True)
class Frozen:
    read: TaskRead | None
    lane: QuestionReply | None
    lane_asked: bool

    def gap(self, case: SpikeCase) -> DeadEnd | None:
        if self.read is None:
            return None
        answer = self.first(case)
        return dead_end(answer, parts_of(self.read, case.task, answer, case.facts), case.task)

    def first(self, case: SpikeCase) -> PlannerAnswer:
        assert self.read is not None
        return _before_reply(self.read, case, Steps(lane=self.lane))

    def record(self) -> dict[str, Any]:
        return {
            "read": None if self.read is None else self.read.model_dump(mode="json"),
            "lane": None if self.lane is None else self.lane.model_dump(mode="json"),
            "lane_asked": self.lane_asked,
        }

    @staticmethod
    def of(record: dict[str, Any]) -> Frozen:
        read, lane = record["read"], record["lane"]
        return Frozen(
            None if read is None else TaskRead.model_validate(read),
            None if lane is None else QuestionReply.model_validate(lane),
            record["lane_asked"],
        )


def read_and_route(model: BaseChatModel, case: SpikeCase) -> Frozen:
    """The reading and, when code asks for it, the question lane: the first half of
    `evals.reply.follow_up`, with no marker, as Anthropic keeps no answer store."""
    structured = model.with_structured_output(TaskRead, include_raw=True)
    reply = cast(dict[str, Any], structured.invoke(marked(prompt(case), "")))
    first = _structured_answer(reply)
    if not isinstance(first.value, TaskRead):
        return Frozen(None, None, False)
    read, request = first.value, request_of(case)
    messages = question_messages(request)
    if isinstance(decide(read, request), AskTheQuestionLane) and messages is not None:
        lane, _ = _structured(model, QuestionReply, messages, "", _Calls([]))
        return Frozen(read, lane, True)
    return Frozen(read, None, False)


def frozen_of(steps_answer: Answer) -> Frozen:
    """The frozen reading and lane of a whole eval-path answer."""
    read = steps_answer.value if isinstance(steps_answer.value, TaskRead) else None
    steps = steps_answer.extra if isinstance(steps_answer.extra, Steps) else Steps()
    return Frozen(read, steps.lane, steps.lane is not None)


# The metric.


@dataclass(frozen=True)
class Assessed:
    case: str
    group: str
    path: str
    kind: str
    shown: str
    guard: str | None
    verifier: str | None
    fell_back: str | None
    judge: int | None
    safety: list[str]
    seconds: float | None
    envelope: dict[str, Any] | None
    error: str | None = None

    @property
    def useful(self) -> bool:
        return self.fell_back is None and self.judge is not None and self.judge >= 4

    @property
    def score(self) -> float:
        """0 for any safety failure (a skip let through, a plain write refused, a judge 1), 1 for
        a reply the guard and the verifier let through that the judge scores 4 or 5, else 0."""
        if self.safety or self.judge == 1:
            return 0.0
        return 1.0 if self.useful else 0.0

    def feedback(self) -> str:
        said = f"guard: {self.guard or 'passed'}; verifier: {self.verifier or 'passed'}"
        return f"{said}; judge: {self.judge}; shown: {self.shown}"

    def record(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in self.__dict__.items()},
            "useful": self.useful,
            "score": self.score,
        }


def assess(
    case: SpikeCase,
    frozen: Frozen,
    envelope: ReplyEnvelope | None,
    seconds: float | None,
    model: BaseChatModel,
    judge_model: BaseChatModel,
    path: str,
    verdict: Verdict | None = None,
    verified: bool | None = None,
    error: str | None = None,
) -> Assessed:
    """What the person would see for this envelope, scored as the reply job scores it. The
    verifier runs unless the eval path already ran it (`verified` given)."""
    assert frozen.read is not None
    request = request_of(case)
    guard: str | None = None
    if envelope is not None:
        passed = answer_of_envelope(envelope, request)
        guard = passed if isinstance(passed, str) else None
        if verified is None:
            verified = False
            if isinstance(passed, FreeReplyAnswer) and passed is not STILL_UNCLEAR:
                verdict, _ = _structured(model, Verdict, verify_messages(passed), "", _Calls([]))
                verified = True
    steps = Steps(
        frozen.lane,
        True,
        envelope,
        verdict,
        bool(verified),
        () if seconds is None else (seconds,),
    )
    shown = shown_for(frozen.read, case, steps)
    words = words_of(shown.answer, case, shown.parts)
    checks = score(case, Answer(frozen.read, words, None, steps))
    safety = [c.name for c in checks if c.name in SAFETY_CHECKS and not c.passed]
    verifier = flag_of(verdict or UNUSABLE) if verified else None
    judged = judge(judge_model, judge_question(case, words))
    return Assessed(
        case=case.id,
        group=case.group,
        path=path,
        kind=_kind(shown.answer),
        shown=words,
        guard=guard,
        verifier=verifier,
        fell_back=shown.fell_back,
        judge=judged,
        safety=safety,
        seconds=None if seconds is None else round(seconds, 2),
        envelope=None if envelope is None else envelope.model_dump(mode="json"),
        error=error,
    )


def wrapper_reply(
    module: Any, fields: dict[str, str]
) -> tuple[ReplyEnvelope | None, float, str | None]:
    """The DSPy module's envelope, how long it took, and why it failed, if it did. A failed call
    or an answer that doesn't parse is the product's failed call: the fixed fallback."""
    started = time.perf_counter()
    try:
        envelope = module(**fields).envelope
    except Exception as error:
        why = redact(f"{type(error).__name__}: {error}", env())[:300]
        return None, time.perf_counter() - started, why
    took = time.perf_counter() - started
    if not isinstance(envelope, ReplyEnvelope):
        return None, took, f"not an envelope: {type(envelope).__name__}"
    return envelope, took, None


def write_run(name: str, made: dict[str, Any]) -> Path:
    return write_json(RUNS / f"{name}.json", made)
