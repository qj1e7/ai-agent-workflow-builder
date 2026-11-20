import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict

from evals.checks import Check

CASES = Path(__file__).parent / "cases"


class Case(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    note: str


@dataclass(frozen=True)
class Answer:
    value: object | None
    text: str
    raw: BaseMessage | None
    extra: object | None = None


@dataclass(frozen=True)
class Job[C: Case]:
    name: str
    title: str
    case_type: type[C]
    prompt: Callable[[C], str]
    schema: Callable[[], type[BaseModel]] | None
    score: Callable[[C, Answer], list[Check]]
    judged: bool
    time_limit_s: float | None = None
    follow_up: Callable[[BaseChatModel, C, Answer, str], Answer] | None = None
    product_call: Callable[[BaseChatModel, C], Answer] | None = None
    """The product's own code path, run in place of the prompt and the schema. It sends the
    product's exact messages, so the run's marker is not on them."""
    judge_question: Callable[[C, str], str] | None = None
    """What the judge is asked about a case's answer, in place of accuracy and clarity."""
    most_calls: int = 1
    """The most model calls one case makes, so a run stops before it passes its call cap."""
    judge_runs: int = 1
    """How many times the judge scores each answer. The score is their median, so one noisy run
    can't move it."""

    def cases(self) -> list[C]:
        rows = json.loads((CASES / f"{self.name}.json").read_text())
        return [self.case_type.model_validate(row) for row in rows]

    def ask(self, model: BaseChatModel, case: C, marker: str = "") -> Answer:
        if self.product_call is not None:
            return self.product_call(model, case)
        prompt = marked(self.prompt(case), marker)
        if self.schema is None:
            raw = model.invoke(prompt)
            text = raw.text.strip()
            return Answer(text, text, raw)
        structured = model.with_structured_output(self.schema(), include_raw=True)
        reply: dict[str, Any] = structured.invoke(prompt)  # type: ignore[assignment]
        answer = _structured_answer(reply)
        return self.follow_up(model, case, answer, marker) if self.follow_up else answer


def marked(prompt: str, marker: str) -> str:
    """The prompt with this run's marker before it. The AI Singapore gateway answers a request it
    has seen before from its store, so a rerun without a new marker would score that store."""
    if not marker:
        return prompt
    return f"Eval run {marker}. This line is not part of the task.\n\n{prompt}"


def _structured_answer(reply: dict[str, Any]) -> Answer:
    raw: BaseMessage = reply["raw"]
    parsed = reply["parsed"]
    if isinstance(parsed, BaseModel):
        return Answer(parsed, parsed.model_dump_json(), raw)
    calls = getattr(raw, "tool_calls", None) or []
    given = json.dumps(calls[0]["args"]) if calls and "args" in calls[0] else raw.text
    return Answer(None, given, raw)
