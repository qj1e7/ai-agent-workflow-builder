"""Steps 2 and 3: parity, the baseline and the 30 replies for the team lead to label (round 1),
parity again, both paths twice on 20 cases (round 2, `parity2`), the judge's question today and
a v2 on 50 replies already made (round 3, `rejudge`), a v3 three times on the same 50 (round 4,
`rejudge3`), and the judge question PR fix/gate-judge-role ships, three times on the same 50
(round 5, `rejudge4`).

Runs on GitHub Actions (`.github/workflows/spike-dspy.yml`) when `STEP` changes, with the
Anthropic key in ANTHROPIC_API_KEY for that one step:
    uv run --group spike python -m spikes.dspy_free_reply.run rejudge4

Each run stops before a case would pass the round's cap or the spike's $30 (`scoring.Meter`),
and writes its spend to `spend.json` and its rows to `runs/` after every case."""

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
import uuid  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from typing import Any, Final  # noqa: E402

import dspy  # noqa: E402
from evals.budget import metered  # noqa: E402
from evals.jobs import marked  # noqa: E402
from evals.reply import REPLY, Steps, judge_question, request_of  # noqa: E402
from evals.runner import (  # noqa: E402
    _KEY_SHAPES,  # pyright: ignore[reportPrivateUsage]
    judge,
    redact,
)

from spikes.dspy_free_reply.cases import SpikeCase, all_cases  # noqa: E402
from spikes.dspy_free_reply.scoring import (  # noqa: E402
    MODEL,
    RUNS,
    Assessed,
    Frozen,
    Meter,
    assess,
    env,
    eval_reply,
    frozen_of,
    judge_question_v2,
    judge_question_v3,
    planner,
    read_and_route,
    wrapper_reply,
    write_json,
    write_run,
)
from spikes.dspy_free_reply.split import load, recorded  # noqa: E402
from spikes.dspy_free_reply.wrapper import FreeReply, ProductAdapter, fields_of  # noqa: E402

FROZEN: Final = RUNS / "frozen.json"
PARITY: Final = RUNS / "parity.json"
BASELINE: Final = RUNS / "baseline.json"
LABELS: Final = RUNS / "label-input.json"
REJUDGE: Final = RUNS / "rejudge.json"
REJUDGE3: Final = RUNS / "rejudge3.json"
QUESTIONS_V4: Final = RUNS / "questions-v4.json"
"""Each of the 50 rows' judge question, built offline by evals.reply.judge_question at
e293d08f (PR fix/gate-judge-role) on the case and words v3 used."""
REJUDGE4: Final = RUNS / "rejudge4.json"
BATCH2: Final = RUNS / "labels-batch2.json"
BATCH2_SIZE: Final = 20
JUDGE_RUNS: Final = 3
PARITY_CASES: Final = 10
SEED: Final = 20261120
PAID: Final = frozenset({"parity", "baseline", "parity2", "rejudge", "rejudge3", "rejudge4"})
PARITY2_CASES: Final = 20
RUNS_EACH: Final = 2
QUIET: Final = ("LiteLLM", "litellm", "httpx", "httpcore", "anthropic", "urllib3")


def quiet() -> None:
    """No library logs below an error, and none of LiteLLM's debug lines: a request log can
    carry its headers."""
    dspy.disable_litellm_logging()
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.ERROR)


def configure(model: Any) -> dspy.LM:
    """DSPy with the product adapter on the eval path's model. DSPy's own LM is a placeholder that
    no step calls; the meter still reads its history, so a call would be counted."""
    placeholder = dspy.LM(f"anthropic/{MODEL}", num_retries=0)
    dspy.configure(lm=placeholder, adapter=ProductAdapter(model))
    return placeholder


def failure(error: Exception) -> str:
    return redact(f"{type(error).__name__}: {error}", env())[:300]


def frozen_store() -> dict[str, Any]:
    return json.loads(FROZEN.read_text()) if FROZEN.exists() else {}


def save_frozen(case_id: str, frozen: Frozen) -> None:
    store = frozen_store()
    store[case_id] = frozen.record()
    write_json(FROZEN, store)


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
    model, module = planner(), FreeReply()
    meter = Meter("parity", configure(model))
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


def parity2() -> None:
    """Round 2: both paths twice on 20 SCORE cases, from round 1's frozen readings, so chance
    shows. The wrapper now sends the eval path's request word for word."""
    model, module = planner(), FreeReply()
    meter = Meter("parity2", configure(model))
    cases, store = all_cases(), frozen_store()
    reached = [
        i
        for i in parity_order([r["id"] for r in load()["score"]])
        if i in store and Frozen.of(store[i]).gap(cases[i]) is not None
    ]
    rows: list[dict[str, Any]] = []
    stopped = None
    with metered(meter.spend):
        for case_id in reached[:PARITY2_CASES]:
            if (stopped := meter.stop_reason()) is not None:
                break
            case, frozen = cases[case_id], Frozen.of(store[case_id])
            gap = frozen.gap(case)
            assert gap is not None
            row: dict[str, Any] = {"case": case_id, "eval": [], "wrapper": []}
            try:
                for _ in range(RUNS_EACH):
                    said = eval_reply(model, case, gap)
                    row["eval"].append(
                        assess(
                            case, frozen, *said[:2], model, model, "eval", error=said[2]
                        ).record()
                    )
                    said = wrapper_reply(module, fields_of(request_of(case), gap))
                    row["wrapper"].append(
                        assess(
                            case, frozen, *said[:2], model, model, "wrapper", error=said[2]
                        ).record()
                    )
            except Exception as error:
                row["error"] = failure(error)
            rows.append(row)
            meter.save()
            write_run("parity2", {"summary": None, "rows": rows})
            print(_parity2_line(row), flush=True)
    summary = _parity2_summary(rows, stopped, meter.save())
    write_run("parity2", {"summary": summary, "rows": rows})
    report("Parity, twice on each path", summary)


def _parity2_line(row: dict[str, Any]) -> str:
    if "error" in row:
        return f"  {row['case']}: {row['error']}"
    said = {p: [f"{r['kind']}/{r['judge']}" for r in row[p]] for p in ("eval", "wrapper")}
    return f"  {row['case']}: eval {said['eval']}  wrapper {said['wrapper']}"


def _parity2_summary(rows: list[dict[str, Any]], stopped: str | None, spend: Any) -> dict[str, Any]:
    done = [
        r for r in rows if "error" not in r and len(r["eval"]) == len(r["wrapper"]) == RUNS_EACH
    ]
    n = len(done)

    def agrees_with_itself(path: str) -> int:
        return sum(r[path][0]["kind"] == r[path][1]["kind"] for r in done)

    cross = sum(
        sum(e["kind"] == w["kind"] for e in r["eval"] for w in r["wrapper"]) / RUNS_EACH**2
        for r in done
    )
    useful = {
        p: [sum(r[p][i]["useful"] for r in done) for i in range(RUNS_EACH)]
        for p in ("eval", "wrapper")
    }
    self_eval, self_wrapper = agrees_with_itself("eval"), agrees_with_itself("wrapper")
    mean_useful = {p: statistics.fmean(u) if n else 0.0 for p, u in useful.items()}
    kind_bar = cross >= statistics.fmean([self_eval, self_wrapper]) if n else False
    useful_bar = abs(mean_useful["eval"] - mean_useful["wrapper"]) <= 2
    return {
        "cases": n,
        "runs_each": RUNS_EACH,
        "kind_agrees_eval_with_itself": self_eval,
        "kind_agrees_wrapper_with_itself": self_wrapper,
        "kind_agrees_across_paths": round(cross, 2),
        "useful_eval_per_run": useful["eval"],
        "useful_wrapper_per_run": useful["wrapper"],
        "fallbacks_eval": sum(x["fell_back"] is not None for r in done for x in r["eval"]),
        "fallbacks_wrapper": sum(x["fell_back"] is not None for r in done for x in r["wrapper"]),
        "judge_mean_eval": _mean([x["judge"] for r in done for x in r["eval"]]),
        "judge_mean_wrapper": _mean([x["judge"] for r in done for x in r["wrapper"]]),
        "safety_failures": sum(
            bool(x["safety"]) for r in done for p in ("eval", "wrapper") for x in r[p]
        ),
        "bar_kind": kind_bar,
        "bar_useful_within_2": useful_bar,
        "passes": kind_bar and useful_bar,
        "errors": len(rows) - n,
        "stopped": stopped,
        "spend": spend,
    }


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
    model, module = planner(), FreeReply()
    meter = Meter("baseline", configure(model))
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


def shareable(row: dict[str, Any], cases: dict[str, SpikeCase]) -> bool:
    """A reply the judge scored, with nothing that looks like a secret in the message or the
    reply, so a person can label it."""
    return row["judge"] is not None and not any(
        _KEY_SHAPES.search(t) or SECRET_WORDS.search(t)
        for t in (cases[row["case"]].task, shown_words(row))
    )


def reached() -> list[dict[str, Any]]:
    """The baseline's rows that reached the free reply."""
    return [r for r in json.loads(BASELINE.read_text())["rows"] if r["reached"]]


def labels() -> None:
    """About 12 replies the judge scored 2 or 3 and 18 it scored 4 or 5, spread across groups,
    none with anything that looks like a secret."""
    cases = all_cases()
    rows = reached()
    clean = [r for r in rows if shareable(r, cases)]
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


def rejudge_sets() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Set A, the baseline rows of the 30 the team lead labeled, and set B, 20 more SCORE
    replies the guard and the verifier let through, spread across groups, none from set A and
    none with anything that looks like a secret."""
    cases, rows = all_cases(), reached()
    by_case = {r["case"]: r for r in rows}
    set_a = [by_case[x["id"]] for x in json.loads(LABELS.read_text())]
    taken = {r["case"] for r in set_a}
    pool = [
        r for r in rows if r["fell_back"] is None and r["case"] not in taken and shareable(r, cases)
    ]
    return set_a, _spread(pool, BATCH2_SIZE)


def rejudge() -> None:
    """Round 3: the judge's question today (v1) and the spike's v2 on replies already made, the
    30 the team lead labeled and 20 more for them to label blind. No Planner or free reply call.
    Each reply is judged on the words the baseline's judge read, so v1 asks what the eval asked."""
    model = planner()
    meter = Meter("rejudge")
    cases = all_cases()
    set_a, set_b = rejudge_sets()
    blind = [
        {"id": r["case"], "message": cases[r["case"]].task, "reply": shown_words(r)} for r in set_b
    ]
    random.Random(SEED).shuffle(blind)
    write_json(BATCH2, blind)
    rows: list[dict[str, Any]] = []
    stopped = None
    with metered(meter.spend):
        for name, row in [*(("A", r) for r in set_a), *(("B", r) for r in set_b)]:
            if (stopped := meter.stop_reason()) is not None:
                break
            case = cases[row["case"]]
            rows.append(
                {
                    "id": row["case"],
                    "set": name,
                    "message": case.task,
                    "reply": shown_words(row),
                    "v1": judge(model, judge_question(case, row["shown"])),
                    "v2": judge(model, judge_question_v2(case, row["shown"])),
                }
            )
            meter.save()
            write_json(REJUDGE, rows)
            print(f"  {name} {row['case']}: v1 {rows[-1]['v1']}  v2 {rows[-1]['v2']}", flush=True)
    summary = {
        "set_a": sum(r["set"] == "A" for r in rows),
        "set_b": sum(r["set"] == "B" for r in rows),
        "judge_failures": sum(r[v] is None for r in rows for v in ("v1", "v2")),
        "v1_scores": dict(sorted(Counter(r["v1"] for r in rows).items(), key=str)),
        "v2_scores": dict(sorted(Counter(r["v2"] for r in rows).items(), key=str)),
        "v2_differs": sum(r["v1"] != r["v2"] for r in rows),
        "stopped": stopped,
        "spend": meter.save(),
    }
    report("Rejudge, v1 and v2", summary)


def rejudge3_sets() -> list[tuple[str, dict[str, Any]]]:
    """The 50 replies `rejudge` judged: set A in label-input.json's order, set B in
    labels-batch2.json's. Each is the baseline row whose words, without their kind, are the
    reply in rejudge.json, so v3 reads what v1 and v2 read."""
    by_case = {r["case"]: r for r in reached()}
    judged = {r["id"]: r for r in json.loads(REJUDGE.read_text())}
    picked = [("A", x["id"]) for x in json.loads(LABELS.read_text())]
    picked += [("B", x["id"]) for x in json.loads(BATCH2.read_text())]
    for name, case_id in picked:
        said = judged[case_id]
        if said["set"] != name or said["reply"] != shown_words(by_case[case_id]):
            raise ValueError(f"{case_id} is not the reply rejudge.json judged")
    return [(name, by_case[case_id]) for name, case_id in picked]


def median_of(scores: list[int | None]) -> float | None:
    """The middle score of those the judge gave; a failed judge call counts for nothing."""
    found = [s for s in scores if s is not None]
    return statistics.median(found) if found else None


def rejudge3() -> None:
    """Round 4: v3 three times on each of the 50 replies `rejudge` judged, so chance shows. No
    Planner or free reply call."""
    model = planner()
    meter = Meter("rejudge3")
    cases = all_cases()
    rows: list[dict[str, Any]] = []
    stopped = None
    with metered(meter.spend):
        for name, row in rejudge3_sets():
            if (stopped := meter.stop_reason()) is not None:
                break
            case = cases[row["case"]]
            scores = [
                judge(model, judge_question_v3(case, row["shown"])) for _ in range(JUDGE_RUNS)
            ]
            rows.append(
                {"id": row["case"], "set": name, "v3": scores, "v3_median": median_of(scores)}
            )
            meter.save()
            write_json(REJUDGE3, rows)
            print(f"  {name} {row['case']}: v3 {scores}", flush=True)
    summary = {
        "set_a": sum(r["set"] == "A" for r in rows),
        "set_b": sum(r["set"] == "B" for r in rows),
        "judge_failures": sum(s is None for r in rows for s in r["v3"]),
        "v3_medians": dict(sorted(Counter(r["v3_median"] for r in rows).items(), key=str)),
        "all_three_agree": sum(len(set(r["v3"])) == 1 for r in rows),
        "stopped": stopped,
        "spend": meter.save(),
    }
    report("Rejudge, v3 three times", summary)


def gate_score(runs: list[int | None]) -> int | None:
    """The score PR fix/gate-judge-role gives three judge runs: any run's 1 is the score,
    otherwise the lower middle of the runs that answered, None when none did."""
    given = [s for s in runs if s is not None]
    if not given:
        return None
    return 1 if 1 in given else statistics.median_low(given)


def rejudge4() -> None:
    """Round 5: each saved v4 question three times, each run with its own marker as the PR's
    `evals.runner.judged` gives it. No Planner or free reply call."""
    model = planner()
    meter = Meter("rejudge4")
    marker = os.environ.get("EVAL_MARKER") or uuid.uuid4().hex[:12]
    rows: list[dict[str, Any]] = []
    stopped = None
    with metered(meter.spend):
        for saved in json.loads(QUESTIONS_V4.read_text()):
            if (stopped := meter.stop_reason()) is not None:
                break
            runs = [
                judge(model, marked(saved["question"], f"{marker} judge {n}" if n > 1 else marker))
                for n in range(1, JUDGE_RUNS + 1)
            ]
            rows.append(
                {"id": saved["id"], "set": saved["set"], "runs": runs, "score": gate_score(runs)}
            )
            meter.save()
            write_json(REJUDGE4, rows)
            print(f"  {saved['set']} {saved['id']}: {runs} -> {rows[-1]['score']}", flush=True)
    summary = {
        "set_a": sum(r["set"] == "A" for r in rows),
        "set_b": sum(r["set"] == "B" for r in rows),
        "judge_failures": sum(s is None for r in rows for s in r["runs"]),
        "scores": dict(sorted(Counter(r["score"] for r in rows).items(), key=str)),
        "all_three_agree": sum(len(set(r["runs"])) == 1 for r in rows),
        "stopped": stopped,
        "spend": meter.save(),
    }
    report("Rejudge, the shipped question three times", summary)


STEPS: Final = {
    "parity": parity,
    "baseline": baseline,
    "labels": labels,
    "parity2": parity2,
    "rejudge": rejudge,
    "rejudge3": rejudge3,
    "rejudge4": rejudge4,
}


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
