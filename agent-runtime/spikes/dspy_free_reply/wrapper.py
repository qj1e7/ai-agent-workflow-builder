"""The free reply's model call as one DSPy module (step 1).

DSPy holds one thing: the instruction text, `SYSTEM` from `free_reply.py` to start with, `{role}`
placeholder and all. Everything else is the eval path's own call. `ProductAdapter` takes the
place of DSPy's chat format: it builds the system and user text exactly as
`free_reply.reply_messages` does and sends them through `evals.reply._structured`, the call the
reply job makes, so the request carries the same words, the same envelope schema as a tool, the
same model settings and the same retries. `test_offline.py` holds the request the wrapper sends to
the one the eval path sends, word for word, for every case.

The first wrapper used DSPy's ChatAdapter. Its own prompt format (field markers, field
descriptions, a preamble, the envelope as JSON in plain text instead of a tool call) changed the
replies, and the old test only checked the pieces, not the request."""

from typing import Any, Final

import dspy
from evals.reply import _Calls, _structured  # pyright: ignore[reportPrivateUsage]
from langchain_core.language_models import BaseChatModel

from agent_runtime.abilities import CAPABILITIES
from agent_runtime.contract import AnswerRequest, ReplyEnvelope
from agent_runtime.free_reply import (
    APPROVER,
    NO_FACTS,
    OPERATOR,
    SYSTEM,
    DeadEnd,
    _capability,  # pyright: ignore[reportPrivateUsage]
)
from agent_runtime.how_to import HOW_TO

ROLE: Final = "{role}"
INSTRUCTIONS: Final = SYSTEM
NONE: Final = "None."

GUIDE: Final = "The guide"
CAPABILITIES_HEAD: Final = "The capabilities"
FACTS: Final = "The facts"
NOTES: Final = "The notes, what the platform's rules found in the message"
TURN_BEFORE: Final = "The turn before, as context only"
MESSAGE: Final = "The message"


class FreeReplySignature(dspy.Signature):
    guide: str = dspy.InputField(desc=GUIDE)
    capabilities: str = dspy.InputField(desc=CAPABILITIES_HEAD)
    facts: str = dspy.InputField(desc=FACTS)
    notes: str = dspy.InputField(desc=NOTES)
    turn_before: str = dspy.InputField(desc=TURN_BEFORE)
    role: str = dspy.InputField(desc="Who the person is and what they can do")
    message: str = dspy.InputField(desc=MESSAGE)
    envelope: ReplyEnvelope = dspy.OutputField(desc="The reply the platform checks and shows")


SIGNATURE: Final = FreeReplySignature.with_instructions(INSTRUCTIONS)


class FreeReply(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.reply = dspy.Predict(SIGNATURE)

    def forward(self, **fields: str) -> dspy.Prediction:
        return self.reply(**fields)


class ProductAdapter(dspy.Adapter):
    """Sends the product's messages through the eval path's call, with the predictor's current
    instructions as the system text. DSPy's own LM is never called."""

    def __init__(self, model: BaseChatModel, marker: str = "") -> None:
        super().__init__()
        self.model = model
        self.marker = marker

    def __call__(
        self,
        lm: Any,
        lm_kwargs: dict[str, Any],
        signature: type[dspy.Signature],
        demos: list[dict[str, Any]],
        inputs: dict[str, Any],
    ) -> list[dict[str, Any]]:
        messages = messages_of(signature.instructions, inputs)
        envelope, _ = _structured(self.model, ReplyEnvelope, messages, self.marker, _Calls([]))
        if envelope is None:
            raise ValueError("the free reply's call failed or its answer did not parse")
        return [{"envelope": envelope}]


def fields_of(request: AnswerRequest, gap: DeadEnd) -> dict[str, str]:
    """The module's inputs for one dead end, from the same pieces `reply_messages` uses."""
    earlier = request.previous
    before = NONE
    if earlier is not None:
        before = earlier.request + (
            f"\nThe answer to it: {earlier.answer}" if earlier.answer else ""
        )
    return {
        "guide": "\n".join(f"- {line}" for line in HOW_TO),
        "capabilities": "\n".join(_capability(c) for c in CAPABILITIES),
        "facts": request.facts.model_dump_json(exclude_none=True) if request.facts else NO_FACTS,
        "notes": "\n".join(f"- {n}" for n in gap.notes) or NONE,
        "turn_before": before,
        "role": OPERATOR if request.changes_workflows else APPROVER,
        "message": request.task,
    }


def messages_of(instructions: str, fields: dict[str, str]) -> tuple[str, str]:
    """The system and user text for these instructions and inputs, as `reply_messages` builds
    them. Instructions that lost the `{role}` placeholder get the role as a last line, so a
    rewrite can't drop it."""
    sections = [
        f"{GUIDE}:\n{fields['guide']}",
        f"{CAPABILITIES_HEAD}:\n{fields['capabilities']}",
        f"{FACTS}:\n{fields['facts']}",
    ]
    if fields["notes"] != NONE:
        sections.append(f"{NOTES}:\n{fields['notes']}")
    if fields["turn_before"] != NONE:
        sections.append(f"{TURN_BEFORE}:\n{fields['turn_before']}")
    sections.append(f"{MESSAGE}:\n{fields['message']}")
    role = fields["role"]
    system = (
        instructions.replace(ROLE, role) if ROLE in instructions else f"{instructions}\n- {role}"
    )
    return system, "\n\n".join(sections)
