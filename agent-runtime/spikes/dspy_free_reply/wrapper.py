"""The free reply's model call as one DSPy module (step 1).

The inputs are the product's own sections, built with the product's own helpers: the guide (the
how-to notes), the capabilities (the registry), the person's read-only facts, the notes from the
rules, the turn before and the message. `product_text` joins them back into the exact user text
`free_reply.reply_messages` sends, which `test_offline.py` checks for every case. The output is
the same closed envelope, `ReplyEnvelope`. The starting instructions are today's `SYSTEM`, with
one change: its role line names an input field, because DSPy instructions are the same for every
case and the person's role is not. The guard and the verifier run on the output elsewhere,
exactly as in the product."""

from typing import Final

import dspy

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

ROLE_LINE: Final = "- {role}"
ROLE_FROM_FIELD: Final = "- The person's role is given in role. Follow it."
INSTRUCTIONS: Final = SYSTEM.replace(ROLE_LINE, ROLE_FROM_FIELD)
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


def product_text(fields: dict[str, str]) -> tuple[str, str]:
    """The system and user text the product would send for these inputs, so a test can hold the
    wrapper to `reply_messages`."""
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
    system = INSTRUCTIONS.replace(ROLE_FROM_FIELD, f"- {fields['role']}")
    return system, "\n\n".join(sections)
