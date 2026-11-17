"""Which of n8n's blocks the platform's n8n loads, and which of those can't run on this platform
(ADR 0051, section 2, as spike P9 and build step 12 settled it).

n8n loads every built-in block of the packages in `SHIPPED`, except the two in `LEFT_OUT`, and no
community node. Our node pack's blocks load too. `HELD` names the blocks n8n loads that still can't
run here, each with why and what it waits for, and a tool n8n makes of a held block is held the
same way. The safety checker flags each of them, and the block catalogue marks each, so the
workflow drafter and the checker say the same.

Pure.
"""

from collections.abc import Mapping
from dataclasses import dataclass

OURS = "CUSTOM."
"""How n8n names the types of our node pack (P7 Q11)."""
SHIPPED = ("n8n-nodes-base", "@n8n/n8n-nodes-langchain")
"""The packages of blocks in n8n's image."""
LEFT_OUT = frozenset({"n8n-nodes-base.executeCommand", "n8n-nodes-base.localFileTrigger"})
"""n8n never loads these (NODES_EXCLUDE): either one opens n8n's own environment."""
TOOL_SUFFIXES = ("HitlTool", "Tool")
"""How n8n names an AI agent's tool it makes of a block."""


@dataclass(frozen=True)
class Hold:
    """Why a block n8n loads can't run on this platform, and what it waits for."""

    because: str
    waits_for: str

    def as_json(self) -> dict[str, str]:
        return {"because": self.because, "waits_for": self.waits_for}


A_NEW_ADR = "a new ADR"
IN_N8N = Hold(
    "It runs code inside n8n's own process, where n8n's secrets are, and n8n refuses it as "
    "deprecated.",
    A_NEW_ADR,
)
CALLS = Hold(
    "It runs another workflow, which its approval doesn't cover.",
    "an amendment that makes a version's approval cover the workflows it calls",
)
GIT = Hold(
    "It runs git on n8n's disk, and nobody has yet shown with a real repository that git's hooks "
    "and settings can't run code or reach n8n's own files.",
    "a probe of git with a real repository",
)
N8N_ITSELF = Hold("It changes n8n itself, and Settings refuses a key to n8n's own API.", A_NEW_ADR)

HELD: Mapping[str, Hold] = {
    "n8n-nodes-base.function": IN_N8N,
    "n8n-nodes-base.functionItem": IN_N8N,
    "@n8n/n8n-nodes-langchain.code": IN_N8N,
    "n8n-nodes-base.executeWorkflow": CALLS,
    "n8n-nodes-base.executeWorkflowTrigger": CALLS,
    "@n8n/n8n-nodes-langchain.toolWorkflow": CALLS,
    "@n8n/n8n-nodes-langchain.retrieverWorkflow": CALLS,
    "n8n-nodes-base.git": GIT,
    "n8n-nodes-base.n8n": N8N_ITSELF,
}
"""The blocks n8n loads that can't run on this platform. Code, AI Transform, the Code Tool, Sort,
Item Lists and Merge's SQL mode run (spike P9), because n8n runs the first five in its external
task runner, which holds none of n8n's secrets, and Merge's SQL in an isolate that reaches no file
or address. The disk blocks other than Git run, because n8n keeps them in `~/.n8n-files`."""


def package(node_type: str) -> str:
    return node_type.rpartition(".")[0]


def loads(node_type: str) -> bool:
    """Whether the platform's n8n loads this type: one of ours, or a built-in block it doesn't
    leave out."""
    if node_type.startswith(OURS):
        return True
    return package(node_type) in SHIPPED and node_type not in LEFT_OUT


def held(node_type: str) -> Hold | None:
    """Why n8n loads this type but it can't run here, or None. A tool n8n makes of a held block
    is held the same way."""
    if (hold := HELD.get(node_type)) is not None:
        return hold
    for suffix in TOOL_SUFFIXES:
        if node_type.endswith(suffix):
            return HELD.get(node_type.removesuffix(suffix))
    return None
