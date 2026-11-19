"""Offline checks, no model: run with `uv run --group spike pytest spikes/dspy_free_reply`."""

from typing import Any

import dspy
from dspy.utils.dummies import DummyLM
from evals.reply import _Calls, _structured, request_of  # pyright: ignore[reportPrivateUsage]
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

from agent_runtime.contract import ReplyEnvelope
from agent_runtime.free_reply import (
    CATCH_ALL,
    SYSTEM,
    DeadEnd,
    _found_in,  # pyright: ignore[reportPrivateUsage]
    reply_messages,
)
from spikes.dspy_free_reply.cases import all_cases
from spikes.dspy_free_reply.split import load, split
from spikes.dspy_free_reply.wrapper import (
    INSTRUCTIONS,
    FreeReply,
    ProductAdapter,
    fields_of,
    messages_of,
)

ENVELOPE = ReplyEnvelope(form="answer", text="Type what you want done in the box on Home.")


class Recording(BaseChatModel):
    """Keeps every structured request exactly as it reaches the model: the shape, the settings
    and the prompt."""

    sent: list[tuple[Any, ...]] = Field(default_factory=list[tuple[Any, ...]])

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise AssertionError("the free reply makes a structured call only")

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:  # type: ignore[override]
        def answer(prompt: Any) -> dict[str, Any]:
            self.sent.append((schema, sorted(kwargs.items()), prompt))
            return {"raw": AIMessage(""), "parsed": ENVELOPE, "parsing_error": None}

        return RunnableLambda(answer)


def gaps(task: str) -> tuple[DeadEnd, DeadEnd]:
    return DeadEnd(), DeadEnd((CATCH_ALL, *_found_in(task)))


def test_the_wrapper_sends_the_eval_paths_request_word_for_word() -> None:
    """The check the first wrapper lacked: what reaches the model, not the pieces."""
    cases = all_cases()
    by_eval, by_wrapper = Recording(), Recording()
    dspy.configure(lm=DummyLM([]), adapter=ProductAdapter(by_wrapper))
    module = FreeReply()
    for row in [*load()["score"], *load()["train"]]:
        case = cases[row["id"]]
        request = request_of(case)
        for gap in gaps(case.task):
            _structured(by_eval, ReplyEnvelope, reply_messages(request, gap), "", _Calls([]))
            assert module(**fields_of(request, gap)).envelope == ENVELOPE
            assert by_wrapper.sent[-1] == by_eval.sent[-1], case.id
    assert len(by_wrapper.sent) == len(by_eval.sent) == 2 * 145


def test_the_instructions_are_todays_and_their_text_is_the_only_thing_dspy_holds() -> None:
    assert INSTRUCTIONS == SYSTEM
    case = all_cases()["reply:approver-13"]
    fields = fields_of(request_of(case), DeadEnd())
    system, user = messages_of("Be brief. {role}", fields)
    assert system == f"Be brief. {fields['role']}"
    assert user == reply_messages(request_of(case), DeadEnd())[1]
    lost, _ = messages_of("Be brief.", fields)
    assert lost == f"Be brief.\n- {fields['role']}"


def test_the_split_is_written_as_made_and_never_trains_on_kept_out_cases() -> None:
    made = load()
    assert split() == made
    cases = all_cases()
    kept_out = {" ".join(c.task.casefold().split()) for c in cases.values() if c.gate or c.held_out}
    for row in made["train"]:
        case = cases[row["id"]]
        assert not case.gate and not case.held_out
        assert " ".join(case.task.casefold().split()) not in kept_out
    assert not {r["id"] for r in made["train"]} & {r["id"] for r in made["score"]}
