"""The fix's parts that platform-api answers (ADR 0055, PR 5): the Scenario writer, the
simulation, the checker and the recorder of the fix's events.

The runtime holds no simulation secret and can't reach the simulation gateway, so each part is a
call to platform-api's routes for one fix on one stopped run, with the fix's own token. Each call
is told the seconds left, and ends by then. platform-api lays each plan out as any layout, so the
simulation and the checker see what an Approver would approve.

The Scenario writer and the explainer are paid calls that platform-api makes only with Simulation
mode's model turned on. Their calls run outside this thread, where the fix's cost count can't see
them, so a call that may ask the model is sent only when the fix can still pay for it at its
most, and counts at that most (`charge`). A call that didn't say whether it asked counts too.

The recorder tries an end event, a proposal or a hand-back, again when the log can't be reached
or fails, a few times over a few seconds, since a lost end leaves the fix open until its
deadline. An event the log refuses is never tried again."""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

import httpx
from pydantic import Field, ValidationError

from agent_runtime.contract import WireModel, WorkflowPlan
from agent_runtime.fixing.cost import charge
from agent_runtime.fixing.events import (
    FixData,
    FixHandedBackData,
    FixProposedData,
    FixRefusal,
    fix_kind,
)
from agent_runtime.fixing.ports import Scenario, ScenarioResult, Simulated
from agent_runtime.model_cost import dollars_for, packaged_prices
from agent_runtime.scenario_explaining import EXPLAIN_MOST_PROMPT_CHARS, EXPLAIN_MOST_TOKENS
from agent_runtime.scenario_writing import WRITE_MOST_PROMPT_CHARS, WRITE_MOST_TOKENS

log = logging.getLogger(__name__)

FIX_TOKEN_HEADER: Final = "X-Fix-Token"
MOST_SECONDS: Final = 20 * 60.0
EVENT_SECONDS: Final = 10.0
END_GAPS: Final = (0.5, 1.0, 2.0)
END_TRIES: Final = len(END_GAPS) + 1
CHARS_PER_TOKEN: Final = 3
"""A token for every three characters, which overcounts English, as the cost cap's test does."""


def most_for(prompt_chars: int, answer_tokens: int, prices: Mapping[str, Any]) -> float:
    """The most one call can cost, at the dearest model the runtime prices."""
    tokens_in = prompt_chars / CHARS_PER_TOKEN
    return max(dollars_for(tokens_in, answer_tokens, 0, 0, p) for p in prices.values())


WRITE_CHARGE: Final = most_for(WRITE_MOST_PROMPT_CHARS, WRITE_MOST_TOKENS, packaged_prices())
EXPLAIN_CHARGE: Final = most_for(EXPLAIN_MOST_PROMPT_CHARS, EXPLAIN_MOST_TOKENS, packaged_prices())


class _Written(WireModel):
    scenarios: list[Scenario] = Field(max_length=20)
    asked_model: bool


class _Ran(WireModel):
    results: list[ScenarioResult] = Field(max_length=100)
    not_reached: list[str] = Field(default_factory=list[str])
    named: list[str] = Field(default_factory=list[str])
    asked_model: bool


class _Checked(WireModel):
    passes: bool
    findings: list[str] = Field(default_factory=list[str])


class _Noted(WireModel):
    refused: FixRefusal | None


class PlatformParts:
    """The Scenario writer, the simulation, the checker and the recorder of one fix."""

    def __init__(
        self,
        base_url: str,
        run_id: str,
        fix_id: str,
        token: str,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base = f"{base_url.rstrip('/')}/internal/v1/runs/{run_id}/fixes/{fix_id}"
        self._token = token
        self._client = client or httpx.Client(follow_redirects=False)
        self._sleep = sleep

    def write(
        self,
        version: WorkflowPlan,
        cover: Sequence[str],
        seconds: float,
        dollars_left: Callable[[], float],
    ) -> list[Scenario] | None:
        may = dollars_left() >= WRITE_CHARGE
        body = {
            "version": version.model_dump(mode="json"),
            "cover": list(cover),
            "may_ask_model": may,
            "within_seconds": _within(seconds),
        }
        written = self._ask("scenarios", body, seconds, _Written)
        if written.asked_model if written is not None else may:
            charge(WRITE_CHARGE)
        return (written.scenarios or None) if written is not None else None

    def run(
        self,
        version: WorkflowPlan,
        scenarios: Sequence[Scenario],
        seconds: float,
        dollars_left: Callable[[], float],
    ) -> Simulated | None:
        may = dollars_left() >= EXPLAIN_CHARGE
        body = {
            "version": version.model_dump(mode="json"),
            "scenarios": [scenario.model_dump(mode="json") for scenario in scenarios],
            "may_ask_model": may,
            "within_seconds": _within(seconds),
        }
        ran = self._ask("simulations", body, seconds, _Ran)
        if ran.asked_model if ran is not None else may:
            charge(EXPLAIN_CHARGE)
        if ran is None:
            return None
        return Simulated(results=ran.results, not_reached=ran.not_reached, named=ran.named)

    def passes(
        self, version: WorkflowPlan, seconds: float, dollars_left: Callable[[], float]
    ) -> bool:
        """The checker asks no model, so `dollars_left` doesn't change what it does."""
        checked = self._ask(
            "checks", {"version": version.model_dump(mode="json")}, seconds, _Checked
        )
        return checked is not None and checked.passes

    def note(self, data: FixData) -> FixRefusal | None:
        """The log's refusal, or None when it took the event. Raises when the log couldn't be
        reached, after its tries for an end event."""
        body = {"kind": fix_kind(data), "data": data.model_dump(mode="json")}
        gaps = END_GAPS if isinstance(data, FixProposedData | FixHandedBackData) else ()
        for gap in (*gaps, None):
            try:
                answer = self._post("events", body, EVENT_SECONDS)
                if answer.status_code >= 500:
                    answer.raise_for_status()
            except httpx.HTTPError as error:
                if gap is None:
                    raise
                log.warning("the fix's log failed (%s), trying again", type(error).__name__)
                self._sleep(gap)
                continue
            answer.raise_for_status()
            return _Noted.model_validate_json(answer.content).refused
        return None

    def _ask[M: WireModel](
        self, route: str, body: Mapping[str, Any], seconds: float, shape: type[M]
    ) -> M | None:
        """platform-api's answer in its shape, or None for any other answer or none at all.
        Only the error's type is logged: an answer can quote the run."""
        if seconds <= 0:
            return None
        try:
            answer = self._post(route, body, min(seconds, MOST_SECONDS))
            answer.raise_for_status()
            return shape.model_validate_json(answer.content)
        except (httpx.HTTPError, ValidationError) as error:
            log.warning("platform-api gave the fix's %s no answer: %s", route, type(error).__name__)
            return None

    def _post(self, route: str, body: Mapping[str, Any], seconds: float) -> httpx.Response:
        return self._client.post(
            f"{self._base}/{route}",
            json=dict(body),
            headers={FIX_TOKEN_HEADER: self._token},
            timeout=seconds,
        )


def _within(seconds: float) -> float:
    return max(min(seconds, MOST_SECONDS), 0.001)
