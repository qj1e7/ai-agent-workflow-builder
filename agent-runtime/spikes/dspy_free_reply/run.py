"""Steps 2 and 3: parity, the baseline and the 30 replies for the team lead to label.

Runs on GitHub Actions (`.github/workflows/spike-dspy.yml`) when `STEP` changes, with the
Anthropic key in ANTHROPIC_API_KEY for that one step:
    uv run --group spike python -m spikes.dspy_free_reply.run parity baseline labels

Each run stops before a case would pass round 1's $4 or the spike's $30 (`scoring.Meter`), and
writes its spend to `spend.json` and its rows to `runs/` after every case."""

import os
from pathlib import Path

HERE = Path(__file__).parent
os.environ.setdefault("DSPY_CACHEDIR", str(HERE / ".cache"))
os.environ.setdefault("LITELLM_LOG", "ERROR")

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import statistics  # noqa: E402
import sys  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from typing import Any, Final  # noqa: E402

import dspy  # noqa: E402
from evals.budget import metered  # noqa: E402
from evals.reply import REPLY, Steps, request_of  # noqa: E402
from evals.runner import _KEY_SHAPES, redact  # noqa: E402  # pyright: ignore[reportPrivateUsage]

from spikes.dspy_free_reply.cases import SpikeCase, all_cases  # noqa: E402
from spikes.dspy_free_reply.scoring import (  # noqa: E402
    MODEL,
    RUNS,
    Assessed,
    Frozen,
    Meter,
    assess,
    env,
    frozen_of,
    planner,
    read_and_route,
    wrapper_reply,
    write_json,
    write_run,
)
from spikes.dspy_free_reply.split import load, recorded  # noqa: E402
from spikes.dspy_free_reply.wrapper import FreeReply, fields_of  # noqa: E402

FROZEN: Final = RUNS / "frozen.json"
PARITY: Final = RUNS / "parity.json"
BASELINE: Final = RUNS / "baseline.json"
LABELS: Final = RUNS / "label-input.json"
PARITY_CASES: Final = 10
SEED: Final = 20261120
PAID: Final = frozenset({"smoke", "parity", "baseline"})
QUIET: Final = ("LiteLLM", "litellm", "httpx", "httpcore", "anthropic", "urllib3")


def quiet() -> None:
    """No library logs below an error, and none of LiteLLM's debug lines: a request log can
    carry its headers."""
    dspy.disable_litellm_logging()
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.ERROR)


def lm() -> dspy.LM:
    built = dspy.LM(f"anthropic/{MODEL}", max_tokens=2000, num_retries=2, timeout=120)
    dspy.configure(lm=built, adapter=dspy.ChatAdapter())
    return built


def failure(error: Exception) -> str:
    return redact(f"{type(error).__name__}: {error}", env())[:300]


def frozen_store() -> dict[str, Any]:
    return json.loads(FROZEN.read_text()) if FROZEN.exists() else {}


def save_frozen(case_id: str, frozen: Frozen) -> None:
    store = frozen_store()
    store[case_id] = frozen.record()
    write_json(FROZEN, store)


def smoke() -> None:
    """One tiny call, to see the engine, the history and the cost line before any case."""
    meter = Meter("smoke", lm())
    with metered(meter.spend):
        said = dspy.Predict("question -> answer")(question="Reply with the word ready.")
    entry = meter.lm.history[-1]
    print("answer:", said.answer)
    print(
        "usage:", entry["usage"], "litellm cost:", entry["cost"], "model:", entry["response_model"]
    )
    print("spend:", meter.save())


def recorded_form(case_id: str, outcome: dict[str, Any] | None) -> str:
    """The 16 Nov run's answer, as a bucket to spread the parity cases."""
    if outcome is None:
        return "new"
    answer = str(outcome["answer"])
    if case_id.startswith("reply:"):
        return answer[1 : answer.index("]")] if answer.startswith("[") else "?"
    shown = json.loads(answer)["result"].get("answer", {})
    return f"reply:{shown['form']}" if shown.get("kind") == "reply" else shown.get("kind", "?")


def parity_order(score_ids: list[str]) -> list[str]:
    """SCORE cases in a seeded order that takes each recorded form in turn and prefers a group
    not taken yet, so the first ten spread across answers, can'ts, questions and fallbacks."""
    cases, outcomes = all_cases(), recorded()
    buckets: dict[str, list[str]] = defaultdict(list)
    for case_id in score_ids:
        buckets[recorded_form(case_id, outcomes.get(case_id))].append(case_id)
    rng = random.Random(SEED)
    for ids in buckets.values():
        rng.shuffle(ids)
    order: list[str] = []
    groups: set[str] = set()
    while any(buckets.values()):
        for name in sorted(buckets):
            ids = buckets[name]
            if not ids:
                continue
            pick = next((i for i in ids if cases[i].group not in groups), ids[0])
            ids.remove(pick)
            order.append(pick)
            groups.add(cases[pick].group)
    return order


def eval_path(model: Any, judge_model: Any, case: SpikeCase) -> tuple[Frozen, Assessed | None]:
    """The reply job's own path for the case, today's prompt through LangChain."""
    answer = REPLY.ask(model, case, "")
    frozen = frozen_of(answer)
    steps = answer.extra if isinstance(answer.extra, Steps) else Steps()
    if frozen.read is None or not steps.reply_asked:
        return frozen, None
    reply_at = len(steps.seconds) - 1 - (1 if steps.verified else 0)
    seconds = steps.seconds[reply_at]
    return frozen, assess(
        case,
        frozen,
        steps.envelope,
        seconds,
        model,
        judge_model,
        "eval",
        verdict=steps.verdict,
        verified=steps.verified,
        error=None if steps.envelope is not None else "call",
    )


def wrapper_path(
    module: FreeReply, model: Any, judge_model: Any, case: SpikeCase, frozen: Frozen
) -> Assessed | None:
    gap = frozen.gap(case)
    if gap is None:
        return None
    envelope, seconds, error = wrapper_reply(module, fields_of(request_of(case), gap))
    return assess(case, frozen, envelope, seconds, model, judge_model, "wrapper", error=error)


def parity() -> None:
    meter = Meter("parity", lm())
    model, module = planner(), FreeReply()
    cases = all_cases()
    rows: list[dict[str, Any]] = []
    stopped = None
    with metered(meter.spend):
        for case_id in parity_order([r["id"] for r in load()["score"]]):
            if sum(r["reached"] for r in rows) >= PARITY_CASES:
                break
            if (stopped := meter.stop_reason()) is not None:
                break
            case = cases[case_id]
            try:
                frozen, by_eval = eval_path(model, model, case)
            except Exception as error:
                rows.append({"case": case_id, "reached": False, "error": failure(error)})
                meter.save()
                print(f"  {case_id}: {rows[-1]['error']}", flush=True)
                continue
            save_frozen(case_id, frozen)
            by_wrapper = (
                None if by_eval is None else wrapper_path(module, model, model, case, frozen)
            )
            rows.append(
                {
                    "case": case_id,
                    "reached": by_eval is not None,
                    "eval": None if by_eval is None else by_eval.record(),
                    "wrapper": None if by_wrapper is None else by_wrapper.record(),
                }
            )
            meter.save()
            write_run("parity", {"summary": None, "rows": rows})
            print(_parity_line(rows[-1]), flush=True)
    both = [r for r in rows if r["reached"]]
    kinds = sum(r["eval"]["kind"] == r["wrapper"]["kind"] for r in both)
    gaps = [
        abs(r["eval"]["judge"] - r["wrapper"]["judge"])
        for r in both
        if r["eval"]["judge"] is not None and r["wrapper"]["judge"] is not None
    ]
    summary = {
        "cases_tried": len(rows),
        "reached_the_free_reply": len(both),
        "same_kind": kinds,
        "same_form_family": sum(_family(r["eval"]) == _family(r["wrapper"]) for r in both),
        "judge_mean_eval": _mean([r["eval"]["judge"] for r in both]),
        "judge_mean_wrapper": _mean([r["wrapper"]["judge"] for r in both]),
        "judge_mean_abs_gap": _mean(gaps),
        "judge_within_1": sum(g <= 1 for g in gaps),
        "useful_eval": sum(r["eval"]["useful"] for r in both),
        "useful_wrapper": sum(r["wrapper"]["useful"] for r in both),
        "stopped": stopped,
        "spend": meter.save(),
    }
    write_run("parity", {"summary": summary, "rows": rows})
    report("Parity", summary)


def _family(row: dict[str, Any]) -> str:
    return "fallback" if row["fell_back"] else row["kind"]


def _mean(values: list[Any]) -> float | None:
    found = [v for v in values if v is not None]
    return round(statistics.fmean(found), 2) if found else None


def _parity_line(row: dict[str, Any]) -> str:
    if not row["reached"]:
        return f"  {row['case']}: no longer reaches the free reply"
    e, w = row["eval"], row["wrapper"]
    return (
        f"  {row['case']}: eval {e['kind']}/{e['fell_back']}/judge {e['judge']}  "
        f"wrapper {w['kind']}/{w['fell_back']}/judge {w['judge']}"
    )


def baseline() -> None:
    meter = Meter("baseline", lm())
    model, module = planner(), FreeReply()
    cases = all_cases()
    by_parity = {
        r["case"]: r["wrapper"] for r in json.loads(PARITY.read_text())["rows"] if r["wrapper"]
    }
    rows: list[dict[str, Any]] = []
    stopped = None
    with metered(meter.spend):
        for entry in load()["score"]:
            case_id = entry["id"]
            if case_id in by_parity:
                rows.append({**by_parity[case_id], "reached": True, "from": "parity"})
                continue
            if (stopped := meter.stop_reason()) is not None:
                break
            case = cases[case_id]
            store = frozen_store()
            if case_id in store:
                frozen = Frozen.of(store[case_id])
            else:
                try:
                    frozen = read_and_route(model, case)
                except Exception as error:
                    why = failure(error)
                    rows.append(
                        {"case": case_id, "group": case.group, "reached": False, "error": why}
                    )
                    meter.save()
                    print(f"  {case_id}: {why}", flush=True)
                    continue
                save_frozen(case_id, frozen)
            done = wrapper_path(module, model, model, case, frozen) if frozen.read else None
            rows.append(
                {"case": case_id, "group": case.group, "reached": False}
                if done is None
                else {**done.record(), "reached": True}
            )
            meter.save()
            write_run("baseline", {"summary": None, "rows": rows})
            print(_baseline_line(rows[-1]), flush=True)
    summary = _baseline_summary(rows, stopped, meter.save())
    write_run("baseline", {"summary": summary, "rows": rows})
    report("Baseline", summary)


def report(title: str, summary: dict[str, Any]) -> None:
    """The summary in the log and, on GitHub Actions, on the run's page."""
    text = json.dumps(summary, indent=2)
    print(text)
    page = os.environ.get("GITHUB_STEP_SUMMARY")
    if page:
        with open(page, "a") as out:
            out.write(f"### {title}\n\n```json\n{redact(text, env())}\n```\n\n")


def _baseline_line(row: dict[str, Any]) -> str:
    if not row["reached"]:
        return f"  {row['case']}: no longer reaches the free reply"
    return f"  {row['case']}: {row['kind']}/{row['fell_back']}/judge {row['judge']}"


def _baseline_summary(
    rows: list[dict[str, Any]], stopped: str | None, spend: Any
) -> dict[str, Any]:
    reached = [r for r in rows if r["reached"]]
    planted = [r for r in reached if str(r["group"]).startswith("planted_")]
    return {
        "score_cases": len(load()["score"]),
        "run": len(rows),
        "reached_the_free_reply": len(reached),
        "no_longer_reach_it": len(rows) - len(reached),
        "useful": sum(r["useful"] for r in reached),
        "judge_1": sum(r["judge"] == 1 for r in reached),
        "judge_scores": dict(sorted(Counter(r["judge"] for r in reached).items(), key=str)),
        "guard_rejections": dict(Counter(r["guard"] for r in reached if r["guard"])),
        "verifier_rejections": dict(Counter(r["verifier"] for r in reached if r["verifier"])),
        "call_failures": sum(r["envelope"] is None for r in reached),
        "fallbacks": sum(r["fell_back"] is not None for r in reached),
        "fallbacks_planted_aside": sum(r["fell_back"] is not None for r in reached)
        - sum(r["fell_back"] is not None for r in planted),
        "safety_failures": sum(bool(r["safety"]) for r in reached),
        "kinds": dict(Counter(r["kind"] for r in reached)),
        "useful_by_group": {
            g: f"{sum(r['useful'] for r in reached if r['group'] == g)} of "
            f"{sum(r['group'] == g for r in reached)}"
            for g in sorted({r["group"] for r in reached})
        },
        "stopped": stopped,
        "spend": spend,
    }


SECRET_WORDS: Final = re.compile(r"(?i)\b(?:password|passwd|token|secret|api[_ -]?key|bearer)\b")


def shown_words(row: dict[str, Any]) -> str:
    """The reply as the Portal draws it: the reply job's words without their leading kind."""
    return re.sub(r"^\[[^\]]+\]\s*", "", row["shown"], count=1)


def labels() -> None:
    """About 12 replies the judge scored 2 or 3 and 18 it scored 4 or 5, spread across groups,
    none with anything that looks like a secret."""
    cases = all_cases()
    rows = [r for r in json.loads(BASELINE.read_text())["rows"] if r["reached"]]
    clean = [
        r
        for r in rows
        if r["judge"] is not None
        and not any(
            _KEY_SHAPES.search(t) or SECRET_WORDS.search(t)
            for t in (cases[r["case"]].task, shown_words(r))
        )
    ]
    low = [r for r in clean if r["judge"] in (2, 3)]
    high = [r for r in clean if r["judge"] in (4, 5)]
    want_low = min(12, len(low))
    picked = _spread(low, want_low) + _spread(high, 30 - want_low)
    random.Random(SEED).shuffle(picked)
    out = [
        {
            "id": r["case"],
            "message": cases[r["case"]].task,
            "reply": shown_words(r),
            "judge": r["judge"],
        }
        for r in picked
    ]
    write_json(LABELS, out)
    print(
        f"Wrote {len(out)} to {LABELS}: {sum(o['judge'] <= 3 for o in out)} judged 2 or 3, "
        f"{sum(o['judge'] >= 4 for o in out)} judged 4 or 5, "
        f"{len({cases[o['id']].group for o in out})} groups; "
        f"{len(rows) - len(clean)} left out for a secret-like word or no score"
    )


def _spread(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """n rows, a group at a time in a seeded order, so no group crowds the rest."""
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["case"]):
        by_group[r["group"]].append(r)
    rng = random.Random(SEED)
    for group in by_group.values():
        rng.shuffle(group)
    picked: list[dict[str, Any]] = []
    while len(picked) < n and any(by_group.values()):
        for name in sorted(by_group):
            if by_group[name] and len(picked) < n:
                picked.append(by_group[name].pop())
    return picked


STEPS: Final = {"smoke": smoke, "parity": parity, "baseline": baseline, "labels": labels}


def main() -> int:
    """Each step in turn. Any error is printed as its type and a redacted message only, never a
    traceback, which could quote a request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("steps", nargs="+", choices=tuple(STEPS))
    steps = parser.parse_args().steps
    if PAID & set(steps) and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set, so no paid step can run.", file=sys.stderr)
        return 1
    quiet()
    for step in steps:
        print(f"== {step}", flush=True)
        try:
            STEPS[step]()
        except Exception as error:
            print(f"{step} failed: {failure(error)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
