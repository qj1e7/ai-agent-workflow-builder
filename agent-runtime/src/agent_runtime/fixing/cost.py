"""The cost count of one fix (ADR 0055, section 5). Code keeps it, never the model.

`FixCost` sees every model call made while the fix is `counted`, the coordinator's and those of
the sub-agents it hands work to, through LangChain's callbacks, as `evals/budget.py` sees an eval
run's. It prices each call by its model's name from prices in `evals/pricing.json`'s shape. A
call it can't price breaks the cap, since the cap can't be held without the price."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.tracers.context import register_configure_hook

from agent_runtime.model_cost import cached_tokens, dollars_for

type Price = Mapping[str, Any]


def prices_by_model(pricing: Mapping[str, Price]) -> dict[str, Price]:
    """`pricing.json`'s prices by model name alone, as a model names itself on a call. An entry
    for every model of a provider, as ollama:*, names no model."""
    return {
        key.partition(":")[2]: price
        for key, price in pricing.items()
        if key.partition(":")[2] not in ("", "*")
    }


class FixCost(BaseCallbackHandler):
    def __init__(self, prices: Mapping[str, Price]) -> None:
        self.prices = prices
        self.calls = 0
        self.dollars = 0.0
        self.unpriced: set[str] = set()
        self.counted_at_start: list[float] = []
        """What the fix had spent when each call started, so a test can show none started over
        the cap."""
        self._models: dict[UUID, str] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self.calls += 1
        self.counted_at_start.append(self.dollars)
        asked = cast(Mapping[str, Any], kwargs.get("invocation_params") or {})
        metadata = cast(Mapping[str, Any], kwargs.get("metadata") or {})
        self._models[run_id] = str(metadata.get("ls_model_name") or asked.get("model") or "")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        model = self._models.pop(run_id, "")
        for row in response.generations:
            for generation in row:
                if isinstance(generation, ChatGeneration):
                    self._add(model, generation.message)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._models.pop(run_id, None)

    def _add(self, model: str, message: BaseMessage) -> None:
        price = self.prices.get(model)
        if price is None:
            self.unpriced.add(model or "an unnamed model")
            return
        usage: Mapping[str, Any] = getattr(message, "usage_metadata", None) or {}
        read, written = cached_tokens(usage)
        tokens_in, tokens_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        self.dollars += dollars_for(tokens_in, tokens_out, read, written, price)

    def over(self, cap: float) -> bool:
        return bool(self.unpriced) or self.dollars >= cap


_COUNTED: ContextVar[FixCost | None] = ContextVar("fix_cost", default=None)
register_configure_hook(_COUNTED, inheritable=True)


@contextmanager
def counted(cost: FixCost) -> Generator[FixCost]:
    token = _COUNTED.set(cost)
    try:
        yield cost
    finally:
        _COUNTED.reset(token)
