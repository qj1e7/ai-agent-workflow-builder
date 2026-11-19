"""The reply and anything golden sets as one kind of case, so the reply job's own functions
(`request_of`, `shown_for`, `score`, `words_of`, `judge_question`) score both."""

from functools import cache
from typing import Literal

from evals.anything import ANYTHING, FREE_REPLY_FITS, AnythingCase
from evals.reply import REPLY, ReplyCase

type Source = Literal["reply", "anything"]


class SpikeCase(ReplyCase):
    group: str  # pyright: ignore[reportIncompatibleVariableOverride]
    """The reply case's group, or "anything/<category>" for an anything case."""
    source: Source


def _of_reply(case: ReplyCase) -> SpikeCase:
    return SpikeCase(**{**case.model_dump(), "id": f"reply:{case.id}", "source": "reply"})


def _of_anything(case: AnythingCase) -> SpikeCase:
    fits = bool(FREE_REPLY_FITS & set(case.kinds))
    return SpikeCase(
        id=f"anything:{case.id}",
        note=case.note,
        task=case.task,
        group=f"anything/{case.category}",
        kinds=[*case.kinds, *(["reply"] if fits else [])],
        must_refuse=case.refuse,
        facts=case.facts,
        previous=case.previous,
        changes_workflows=case.changes_workflows,
        source="anything",
    )


@cache
def all_cases() -> dict[str, SpikeCase]:
    found = [_of_reply(c) for c in REPLY.cases()] + [_of_anything(c) for c in ANYTHING.cases()]
    return {c.id: c for c in found}


def text_key(task: str) -> str:
    return " ".join(task.casefold().split())
