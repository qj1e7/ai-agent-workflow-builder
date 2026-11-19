"""Step 0, offline: which cases reach the free reply, split into SCORE and TRAIN.

Run: uv run python -m spikes.dspy_free_reply.split

No model is called. Code alone settles one thing before any model call: the word rule refuses
a skipped yes, and those cases never reach the free reply. Whether any other case reaches it
depends on the reading, which is a model call, so the evidence is the recorded rules-mode run on
Claude Sonnet 5.5 (`docs/evidence/evals/2026-11-16-spike-rules.json`, every reply and anything
case of that day, inputs unchanged since). A case counts when that run asked for a free reply,
shown or fallen back. One dead end came after that run, a "how do I" question answered with the
workflows or Needs you (ADR 0047, amended 16 Nov), so a recorded answer of that kind to such a
question counts too. A case added since counts when its acceptable answers include a free reply.
The baseline runs the reading again and drops any case that no longer reaches it.

SCORE holds every gate case and every held-out case, every case whose words match one of them
(so a held-out message never trains under another case's name), and a seeded third of the rest.
TRAIN is the remainder."""

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Final

from agent_runtime.answers import word_rule_refusal
from agent_runtime.free_reply import HOW_DO_I
from spikes.dspy_free_reply.cases import SpikeCase, all_cases, text_key

HERE: Final = Path(__file__).parent
REPO: Final = HERE.parents[2]
RECORDED: Final = REPO / "docs/evidence/evals/2026-11-16-spike-rules.json"
SPLIT: Final = HERE / "split.json"
SEED: Final = 20261120
ASKS_HOW_KINDS: Final = frozenset({"check_workflows", "needs_me"})


def recorded() -> dict[str, dict[str, Any]]:
    """Each recorded outcome by the spike's case id."""
    run = json.loads(RECORDED.read_text())
    return {
        f"{row['job']}:{outcome['case']}": outcome
        for row in run["results"]
        if row["job"] in ("reply", "anything")
        for outcome in row["outcomes"]
    }


def recorded_kind(case: SpikeCase, outcome: dict[str, Any]) -> str:
    answer = str(outcome["answer"])
    if case.source == "reply":
        return answer[1 : answer.index("]")] if answer.startswith("[") else "?"
    return json.loads(answer)["result"].get("answer", {}).get("kind", "?")


def asked_free_reply(case: SpikeCase, outcome: dict[str, Any]) -> bool:
    """Whether the recorded run asked for a free reply: the reply job marks a fallback with
    `free_reply_shown`, and the anything job keeps every envelope the model filled."""
    if case.source == "reply":
        shown = str(outcome["answer"]).startswith(("[reply:", "[didnt_follow]"))
        return shown or "free_reply_shown" in outcome["failed"]
    said = json.loads(str(outcome["answer"])).get("model_said", [])
    return any(isinstance(m, dict) and {"form", "text"} <= m.keys() for m in said)


def evidence(case: SpikeCase, outcome: dict[str, Any] | None) -> str | None:
    """Why the case counts as reaching the free reply, or None when it doesn't."""
    if word_rule_refusal(case.task) is not None:
        return None
    if outcome is None:
        return "added since the run, a free reply is acceptable" if "reply" in case.kinds else None
    if asked_free_reply(case, outcome):
        return "asked in the 16 Nov run"
    if recorded_kind(case, outcome) in ASKS_HOW_KINDS and HOW_DO_I.match(case.task):
        return "a how-do-I question, a dead end since 16 Nov"
    return None


def split() -> dict[str, Any]:
    cases = all_cases()
    outcomes = recorded()
    refused = [c.id for c in cases.values() if word_rule_refusal(c.task) is not None]
    reached = {
        c.id: why for c in cases.values() if (why := evidence(c, outcomes.get(c.id))) is not None
    }
    kept_out = {
        text_key(c.task): "gate" if c.gate else "held_out"
        for c in cases.values()
        if c.gate or c.held_out
    }
    by_text: dict[str, list[str]] = defaultdict(list)
    for case_id in sorted(reached):
        by_text[text_key(cases[case_id].task)].append(case_id)
    why_score: dict[str, str] = {}
    rest: list[str] = []
    for text, ids in sorted(by_text.items()):
        if text in kept_out:
            for case_id in ids:
                own = cases[case_id]
                why_score[case_id] = (
                    "gate"
                    if own.gate
                    else ("held_out" if own.held_out else f"same words as a {kept_out[text]} case")
                )
        else:
            rest.append(text)
    third = sorted(random.Random(SEED).sample(rest, round(len(rest) / 3)))
    for text in third:
        for case_id in by_text[text]:
            why_score[case_id] = "seeded third"
    train = sorted(set(reached) - set(why_score))

    def row(case_id: str, why: str | None = None) -> dict[str, Any]:
        case = cases[case_id]
        found = {"id": case_id, "group": case.group, "evidence": reached[case_id]}
        return found | ({"why": why} if why else {})

    def count(ids: list[str], key: str) -> dict[str, int]:
        tally: dict[str, int] = defaultdict(int)
        for case_id in ids:
            tally[row(case_id, why_score.get(case_id))[key]] += 1
        return dict(sorted(tally.items()))

    score = sorted(why_score)
    return {
        "made_by": "spikes/dspy_free_reply/split.py, offline, no model calls",
        "evidence": str(RECORDED.relative_to(REPO)),
        "seed": SEED,
        "counts": {
            "cases": len(cases),
            "refused_by_the_word_rule": len(refused),
            "reach_the_free_reply": len(reached),
            "score": len(score),
            "train": len(train),
            "score_by_why": count(score, "why"),
            "score_by_source": {
                s: sum(cases[i].source == s for i in score) for s in ("reply", "anything")
            },
            "train_by_source": {
                s: sum(cases[i].source == s for i in train) for s in ("reply", "anything")
            },
            "by_evidence": count(sorted(reached), "evidence"),
        },
        "score": [row(i, why_score[i]) for i in score],
        "train": [row(i) for i in train],
    }


def load() -> dict[str, Any]:
    return json.loads(SPLIT.read_text())


def main() -> None:
    made = split()
    SPLIT.write_text(json.dumps(made, indent=2) + "\n")
    print(json.dumps(made["counts"], indent=2))


if __name__ == "__main__":
    main()
