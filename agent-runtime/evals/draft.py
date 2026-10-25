import re
from typing import get_args

from pydantic import BaseModel

from agent_runtime.contract import InputKind
from agent_runtime.drafting import DRAFT_SYSTEM, DraftAnswer
from agent_runtime.tools import BY_ID, TOOL_IDS
from evals.checks import Check, check, no_jargon, no_themed_names
from evals.jobs import Answer, Case, Job

INPUT_KINDS = set(get_args(InputKind.__value__))
_TICKET_KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
_PROJECT_KEY = re.compile(r"\bproject\s+([A-Z][A-Z0-9]{1,9})\b")


class DraftCase(Case):
    task: str
    can_do: bool | None
    forbid_tools: list[str] = []
    approvers: int | None = None
    reference: DraftAnswer


def prompt(case: DraftCase) -> str:
    return f"{DRAFT_SYSTEM}\n\nThe task:\n{case.task}"


def schema() -> type[BaseModel]:
    return DraftAnswer


def _words(draft: DraftAnswer) -> list[str]:
    return [draft.name, draft.purpose, *draft.good_for, *(b.say for b in draft.blocks)]


def _invented_keys(draft: DraftAnswer, task: str) -> list[str]:
    found: set[str] = set()
    for text in _words(draft):
        found.update(_TICKET_KEY.findall(text))
        found.update(_PROJECT_KEY.findall(text))
    return sorted(key for key in found if key not in task)


def score(case: DraftCase, answer: Answer) -> list[Check]:
    draft = answer.value
    if not isinstance(draft, DraftAnswer):
        return [check("answered", ["no structured answer"])]
    if not draft.can_do:
        return [
            check("answered", []),
            check(
                "can_do_as_expected",
                [] if case.can_do is not True else ["said it cannot do a task that it can"],
            ),
            check("explains_why_not", [] if (draft.why_not or "").strip() else ["no reason given"]),
        ]
    used = [b.tool for b in draft.blocks if b.tool]
    writes = [t for t in set(used) if t in BY_ID and BY_ID[t].kind == "write"]
    kinds = [i.kind for i in draft.inputs]
    missing_target = [
        f"{tool} needs exactly one {BY_ID[tool].target_kind} input"
        for tool in writes
        if kinds.count(BY_ID[tool].target_kind or "") != 1
    ]
    approvals = {a.tool: a.approvers for a in draft.approvals}
    wrong_approvers = [
        f"{tool} has {approvals.get(tool)} approvers, wanted {case.approvers}"
        for tool in writes
        if case.approvers is not None and approvals.get(tool) != case.approvers
    ]
    text = " ".join(_words(draft))
    return [
        check("answered", []),
        check(
            "can_do_as_expected",
            [] if case.can_do is not False else ["said it can do a task that it cannot"],
        ),
        check("only_listed_tools", sorted({t for t in used if t not in TOOL_IDS})),
        check("avoids_forbidden_tools", sorted(set(used) & set(case.forbid_tools))),
        check("write_has_target_input", missing_target),
        check("input_kinds_valid", sorted({k for k in kinds if k not in INPUT_KINDS})),
        check("has_steps", [] if draft.blocks else ["no steps"]),
        check("approvals_asked_for", wrong_approvers),
        check("no_invented_keys", _invented_keys(draft, case.task)),
        no_themed_names(text),
        no_jargon(text),
    ]


DRAFT = Job(
    name="draft",
    title="Draft an agent card",
    case_type=DraftCase,
    prompt=prompt,
    schema=schema,
    score=score,
    judged=False,
)
