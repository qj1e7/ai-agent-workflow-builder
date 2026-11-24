"""The Fix drafter (ADR 0055, section 2): ADR 0051's workflow drafter, given the stopped version as
the current plan and asked to change only the blocks the coordinator names.

It works through the drafter's own three tools, and code checks each plan against the catalogue
as it checks any draft. The coordinator's scope check then holds it to the blocks named. The ask
is code's, not a person's: it names the blocks, the cause as code confirmed it and the scenarios
that failed, each as data. It never holds a key: platform-api sends the stopped version with each
key kept out (`KEPT_KEY`), and the drafter refuses to read anything shaped like one.

It stops by the seconds the coordinator gives it, and before a turn once the fix's cost cap is
spent."""

import json
import time
from collections.abc import Callable
from typing import Final

from agent_runtime.catalogue import Catalogue
from agent_runtime.contract import (
    DrafterFacts,
    ModelAccess,
    WorkflowDrafted,
    WorkflowDraftRequest,
    WorkflowNotDrafted,
    WorkflowPlan,
)
from agent_runtime.fixing.ports import FixDraftRequest, NotDrafted
from agent_runtime.monitoring.masking import KEPT_KEY
from agent_runtime.summary import ChatFor
from agent_runtime.workflow_drafter import drafting

WORDS: Final = "Change only the blocks named, so the workflow runs again."
"""The words the drafter's settings are read against. They name no value, so every setting keeps
the value and the mark it had."""


def fix_ask(request: FixDraftRequest, facts: DrafterFacts) -> str:
    """What the Fix drafter reads after its fixed part: the facts, the stopped version, the
    blocks it may change, the cause and the scenarios that failed, each marked as data."""
    failed = [result.model_dump(exclude={"verdict"}) for result in request.failed]
    sections = [
        f"The team's facts, as data:\n{facts.model_dump_json(exclude_defaults=True) or '{}'}",
        "The current plan, as data. A run of it stopped, and the platform asks for the smallest "
        "fix. Submit a whole new plan that changes only the blocks named below, and only as much "
        "as the run needs. Keep every other block, every wire, every setting with its id, kind, "
        "value and mark, and the workflow's name, exactly as they are. Never add a block, a "
        f"write, a system or a key. Leave each {KEPT_KEY} where it stands: the platform keeps a "
        f"key there.\n{request.stopped.model_dump_json()}",
        f"The blocks you may change, as data:\n{_json(list(request.change_only))}",
        "Why the run stopped, as the platform confirmed it, as data:\n"
        + request.cause.model_dump_json(exclude={"kind"}),
        "The scenarios that failed in the round before, where and why, as data:\n"
        + (_json(failed) if failed else "None: this is the first round."),
    ]
    return "\n\n".join(sections)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class ModelFixDrafter:
    """The Fix drafter behind the coordinator's `FixDrafter` port."""

    def __init__(
        self,
        chat_for: ChatFor,
        catalogue: Catalogue,
        facts: DrafterFacts,
        model: ModelAccess,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._chat_for = chat_for
        self._catalogue = catalogue
        self._facts = facts
        self._model = model
        self._clock = clock

    def draft(
        self, request: FixDraftRequest, seconds: float, dollars_left: Callable[[], float]
    ) -> WorkflowPlan | NotDrafted:
        """The fixed plan, once code's catalogue check passed it. not_in_catalogue when no plan
        passed it after it went back three times, and no_answer for anything else: no tool call,
        out of turns, time or cost, a model that failed, or a key in what it would read."""
        asked = WorkflowDraftRequest(
            words=WORDS, facts=self._facts, current=request.stopped, model=self._model
        )
        result, _ = drafting(
            asked,
            self._chat_for,
            self._catalogue,
            self._clock,
            asked=fix_ask(request, self._facts),
            most_seconds=seconds,
            go_on=lambda: dollars_left() > 0,
        )
        match result:
            case WorkflowDrafted(plan=plan):
                return plan
            case WorkflowNotDrafted(why="gave_up"):
                return "not_in_catalogue"
            case _:
                return "no_answer"
