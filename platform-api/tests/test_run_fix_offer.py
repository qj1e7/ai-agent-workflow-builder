"""The run read's fix offer (ADR 0055, section 1): a failed run carries whether Fix it for me can
start, and an offer that breaks never breaks the read."""

import json
from pathlib import Path
from typing import Any

import pytest

from platform_api.orchestration.http import FailedView, run_view_adapter, with_fix_offer
from platform_api.shared import RunId
from platform_api.wire import FixOffer

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "views"
RUN = RunId("run_01JB9")


def view(name: str) -> Any:
    return run_view_adapter.validate_python(json.loads((FIXTURES / f"{name}.json").read_text()))


class Fixes:
    def __init__(self, answer: FixOffer | Exception) -> None:
        self.answer = answer
        self.asked: list[str] = []

    async def offer(self, run_id: str) -> FixOffer:
        self.asked.append(run_id)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_a_failed_run_carries_the_offer():
    fixes = Fixes(FixOffer(can=True, why_not=None))
    shown = await with_fix_offer(view("failure.final"), fixes, RUN)
    assert isinstance(shown, FailedView)
    assert shown.fix_offer == FixOffer(can=True, why_not=None)
    assert fixes.asked == [RUN]


async def test_a_reason_a_fix_can_t_start_is_carried_in_the_platform_s_words():
    why = "It's open in n8n, so it can't be fixed now."
    shown = await with_fix_offer(view("failure.final"), Fixes(FixOffer(can=False, why_not=why)), RUN)
    assert isinstance(shown, FailedView)
    assert (shown.fix_offer.can, shown.fix_offer.why_not) == (False, why)  # type: ignore[union-attr]


@pytest.mark.parametrize("name", ["success.final", "failure.working", "rejected.final"])
async def test_a_run_that_isn_t_failed_is_left_as_it_was_and_never_asks(name: str):
    fixes = Fixes(FixOffer(can=True, why_not=None))
    original = view(name)
    assert await with_fix_offer(original, fixes, RUN) == original
    assert fixes.asked == []


async def test_an_app_without_fixes_leaves_the_offer_null():
    shown = await with_fix_offer(view("failure.final"), None, RUN)
    assert isinstance(shown, FailedView)
    assert shown.fix_offer is None


async def test_an_offer_that_raises_says_it_can_t_tell_and_the_read_goes_on():
    shown = await with_fix_offer(view("failure.final"), Fixes(RuntimeError("down")), RUN)
    assert isinstance(shown, FailedView)
    assert shown.fix_offer == FixOffer(
        can=False, why_not="The platform couldn't tell whether a fix can start. Try again soon."
    )
