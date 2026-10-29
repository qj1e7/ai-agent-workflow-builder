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

    def cases(self) -> list[C]:
        rows = json.loads((CASES / f"{self.name}.json").read_text())
        return [self.case_type.model_validate(row) for row in rows]

    def ask(self, model: BaseChatModel, case: C, marker: str = "") -> Answer:
        prompt = marked(self.prompt(case), marker)
        if self.schema is None:
            raw = model.invoke(prompt)
            text = raw.text.strip()
            return Answer(text, text, raw)
        structured = model.with_structured_output(self.schema(), include_raw=True)
        reply: dict[str, Any] = structured.invoke(prompt)  # type: ignore[assignment]
        return _structured_answer(reply)


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
    return Answer(None, raw.text, raw)
