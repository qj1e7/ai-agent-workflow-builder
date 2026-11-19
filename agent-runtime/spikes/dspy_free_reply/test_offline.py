"""Offline checks, no model: run with `uv run --group spike pytest spikes/dspy_free_reply`."""

from evals.reply import request_of

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
    ROLE_FROM_FIELD,
    ROLE_LINE,
    fields_of,
    product_text,
)


def test_the_wrapper_carries_exactly_what_the_product_sends() -> None:
    cases = all_cases()
    for row in [*load()["score"], *load()["train"]]:
        case = cases[row["id"]]
        request = request_of(case)
        for gap in (DeadEnd(), DeadEnd((CATCH_ALL, *_found_in(case.task)))):
            assert product_text(fields_of(request, gap)) == reply_messages(request, gap), case.id


def test_only_the_role_line_changes() -> None:
    assert SYSTEM.count(ROLE_LINE) == 1
    assert INSTRUCTIONS.count(ROLE_FROM_FIELD) == 1
    assert INSTRUCTIONS.replace(ROLE_FROM_FIELD, ROLE_LINE) == SYSTEM


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
