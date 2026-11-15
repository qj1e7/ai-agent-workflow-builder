"""A hard cap on what one run spends, and a stop the moment a gateway says its budget is used up.

`Spend` sees every model call made while it is `metered`, the judge's and those inside the
product's own code path too, through LangChain's callbacks rather than any one model object."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.tracers.context import register_configure_hook

from evals.providers import Env

BUDGET_USED_UP: Final = "The model gateway's budget is used up"
DEFAULT_MAX_CALLS: Final = 300
DEFAULT_MAX_DOLLARS: Final = 5.0
_SPENT_WORDS: Final = ("budget", "quota", "credit")


def budget_spent(error: BaseException) -> bool:
    """Whether a provider answered that its budget, quota or credit is used up, so no later call
    can work. A plain rate limit is not this."""
    status = getattr(error, "status_code", None)
    text = str(error).casefold()
    return status in (402, 422, 429) and any(word in text for word in _SPENT_WORDS)


class Spend(BaseCallbackHandler):
    """Counts the run's model calls and their cost at `pricing.json`'s price per model."""

    def __init__(
        self, max_calls: int, max_dollars: float, prices: Mapping[str, Mapping[str, Any]]
    ) -> None:
        self.max_calls = max_calls
        self.max_dollars = max_dollars
        self.prices = prices
        self.calls = 0
        self.dollars = 0.0
        self.unpriced: set[str] = set()
        self.gateway_out = False
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
        asked = kwargs.get("invocation_params") or {}
        named = (kwargs.get("metadata") or {}).get("ls_model_name") or asked.get("model")
        self._models[run_id] = str(named or "")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        model = self._models.pop(run_id, "")
        for row in response.generations:
            for generation in row:
                if isinstance(generation, ChatGeneration):
                    self._add(model, generation.message)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._models.pop(run_id, None)
        if budget_spent(error):
            self.gateway_out = True

    def _add(self, model: str, message: BaseMessage) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        price = self.prices.get(model)
        if price is None:
            self.unpriced.add(model or "an unnamed model")
            return
        self.dollars += (
            usage.get("input_tokens", 0) * price["input_usd_per_mtok"]
            + usage.get("output_tokens", 0) * price["output_usd_per_mtok"]
        ) / 1_000_000

    def stop_reason(self, calls_ahead: int) -> str | None:
        """Why the run must stop before it makes `calls_ahead` more calls, or None. The call cap is
        never passed. The dollar cap stops the next case once it is reached."""
        if self.gateway_out:
            return BUDGET_USED_UP
        if self.calls + calls_ahead > self.max_calls:
            return f"the cap of {self.max_calls} model calls"
        if self.dollars >= self.max_dollars:
            return f"the cap of ${self.max_dollars:.2f}"
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "dollars": round(self.dollars, 4),
            "max_calls": self.max_calls,
            "max_dollars": self.max_dollars,
            "unpriced": sorted(self.unpriced),
        }


def spent_words(spend: Mapping[str, Any]) -> str:
    """What the run spent and, when it stopped early, why. Models with no price are named, since
    the dollar cap can't count them."""
    words = f"Spent {spend['calls']} model calls, about ${spend['dollars']:.2f}"
    words += f" (caps: {spend['max_calls']} calls, ${spend['max_dollars']:.2f})."
    if spend["stopped"]:
        words += f" Stopped early: {spend['stopped']}. Only the cases above ran."
    if spend["unpriced"]:
        words += f" No price for {', '.join(spend['unpriced'])}, so its cost isn't counted."
    return words


def spend_for(env: Env, pricing: Mapping[str, Any]) -> Spend:
    """The caps from EVAL_MAX_CALLS and EVAL_MAX_DOLLARS, and a price for each model by its name."""
    prices = {key.partition(":")[2]: price for key, price in pricing.items()}
    return Spend(
        int(env.get("EVAL_MAX_CALLS") or DEFAULT_MAX_CALLS),
        float(env.get("EVAL_MAX_DOLLARS") or DEFAULT_MAX_DOLLARS),
        prices,
    )


_METERED: ContextVar[Spend | None] = ContextVar("eval_spend", default=None)
register_configure_hook(_METERED, inheritable=True)


@contextmanager
def metered(spend: Spend) -> Iterator[Spend]:
    token = _METERED.set(spend)
    try:
        yield spend
    finally:
        _METERED.reset(token)
