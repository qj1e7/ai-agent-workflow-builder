"""The report of one run or several, in Markdown: the models side by side on each job, on each
category of the `anything` job with the judge's view, on speed and cost, and then every failure
with what the person typed and what they were shown.

`python -m evals.report out.md results.json [more.json ...]` writes it again from saved runs."""

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.anything import ANYTHING, CATEGORY_TITLES, HOME_FACTS, result_of, words_of
from evals.jobs import Case

type Cases = Mapping[str, Mapping[str, Case]]
type Row = dict[str, Any]

USEFUL = 4
"""The lowest judge score that counts as a useful reply."""


def _rate(passed: int, total: int) -> str:
    return f"{passed}/{total} ({passed / total:.0%})" if total else "-"


def _useful(outcomes: list[dict[str, Any]]) -> str:
    judged = [o["judge"] for o in outcomes if "judge" in o]
    return _rate(sum(s >= USEFUL for s in judged), len(judged)) if judged else "-"


def _seconds(ms: float | None) -> str:
    return "-" if ms is None else f"{ms / 1000:.1f}"


def _per_thousand(row: Row) -> str:
    cost = row["cost_per_100_runs_usd"]
    return "unknown" if cost is None else f"${cost * 10:.2f}"


def _said(case: Case | None) -> str:
    return str(getattr(case, "task", None) or getattr(case, "note", "")) if case else ""


def _quoted(text: str) -> list[str]:
    return [f"    > {line}" if line else "    >" for line in text.splitlines() or [""]]


def _table(head: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def _models(rows: list[Row]) -> list[str]:
    return list(dict.fromkeys(r["model"] for r in rows))


def _cell(rows: list[Row], model: str, job: str) -> Row | None:
    return next((r for r in rows if r["model"] == model and r["job"] == job), None)


def _by_job(rows: list[Row]) -> list[str]:
    models = _models(rows)
    found: list[list[str]] = []
    for job in dict.fromkeys(r["job"] for r in rows):
        cells = [_cell(rows, m, job) for m in models]
        found.append([job, *(_rate(c["passed"], c["cases"]) if c else "-" for c in cells)])
    return _table(["Job", *(f"`{m}`" for m in models)], found)


def _category(outcomes: list[dict[str, Any]]) -> str:
    passed = sum(o["passed"] for o in outcomes)
    useful = _useful(outcomes)
    return _rate(passed, len(outcomes)) + ("" if useful == "-" else f", useful {useful}")


def _by_category(rows: list[Row], cases: Mapping[str, Case]) -> list[str]:
    models = [m for m in _models(rows) if _cell(rows, m, ANYTHING.name)]
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for model in models:
        row = _cell(rows, model, ANYTHING.name)
        assert row is not None
        groups: dict[str, list[dict[str, Any]]] = {name: [] for name in CATEGORY_TITLES}
        for outcome in row["outcomes"]:
            groups[getattr(cases.get(outcome["case"]), "category", "")].append(outcome)
        groups["overall"] = row["outcomes"]
        grouped[model] = groups
    titles = {**CATEGORY_TITLES, "overall": "**Overall**"}
    body = [
        [
            f"{title} ({len(grouped[models[0]][name])})",
            *(_category(grouped[m][name]) for m in models),
        ]
        for name, title in titles.items()
    ]
    return _table(["Category (cases)", *(f"`{m}`" for m in models)], body)


def _speed_and_cost(rows: list[Row]) -> list[str]:
    body = [
        [
            f"`{r['model']}`",
            r["job"],
            _seconds(r["latency_ms"].get("mean")),
            _seconds(r["latency_ms"]["p95"]),
            f"{r['tokens']['input_mean']}/{r['tokens']['output_mean']}",
            _per_thousand(r),
        ]
        for r in rows
    ]
    head = ["Model", "Job", "Mean s", "p95 s", "Tokens in/out", "Cost per 1,000 messages"]
    return _table(head, body)


def _failure(job: str, outcome: dict[str, Any], case: Case | None) -> list[str]:
    category = getattr(case, "category", None)
    head = f"- **{outcome['case']}**" + (f" ({category})" if category else "")
    lines = [f"{head}: “{_said(case)}”"]
    failed = "; ".join(f"`{name}` {detail}".rstrip() for name, detail in outcome["failed"].items())
    if job == ANYTHING.name:
        result = result_of(outcome["answer"])
        kind = getattr(getattr(result, "answer", None), "kind", "offline")
        judge = f" Judge: {outcome['judge']}." if "judge" in outcome else ""
        lines.append(f"  - Kind `{kind}`.{judge}" + (f" Failed: {failed}." if failed else ""))
        lines += _quoted(words_of(result, getattr(case, "facts", HOME_FACTS)))
    else:
        lines.append(f"  - Failed: {failed}.")
        lines += _quoted(outcome["answer"][:400])
    return lines


def _failures(row: Row, cases: Cases) -> list[str]:
    failed = [o for o in row["outcomes"] if not o["passed"]]
    unhelpful = [o for o in row["outcomes"] if o["passed"] and o.get("judge", USEFUL) < USEFUL]
    if not failed and not unhelpful:
        return []
    job_cases = cases.get(row["job"], {})
    lines = ["", f"### `{row['model']}`, {row['job']}", ""]
    for outcome in failed:
        lines += _failure(row["job"], outcome, job_cases.get(outcome["case"]))
    if unhelpful:
        lines += ["", "Passed every code check, but the judge scored it below 4:", ""]
        for outcome in unhelpful:
            lines += _failure(row["job"], outcome, job_cases.get(outcome["case"]))
    return lines


def report(runs: list[dict[str, Any]], cases: Cases) -> str:
    rows: list[Row] = [r for run in runs for r in run["results"]]
    lines = ["# Eval results", ""]
    lines += [
        f"- Run at {run['generated_at']}, marker `{run['marker']}`, judge "
        f"`{run['judge'] or 'none'}`, models "
        + ", ".join(f"`{m['model']}`" for m in run["models"])
        + "."
        for run in runs
    ]
    lines += [
        f"- Not run: {n['provider']} {n['model'] or ''} ({n['reason']})."
        for run in runs
        for n in run["not_run"]
        if n["provider"] == "gateway" or n["reason"].startswith("judge")
    ]
    lines += [
        "",
        "The AI Singapore gateway answers a byte-identical request from its store. Every job "
        f"but `{ANYTHING.name}` puts the run's marker before its prompt. `{ANYTHING.name}` sends "
        "the product's exact messages, so a rerun of the same code on the same model can get "
        "the same readings back.",
        "",
        "## Pass rate by job",
        "",
        *_by_job(rows),
    ]
    if any(r["job"] == ANYTHING.name for r in rows):
        lines += [
            "",
            "## Anything a person types, by category",
            "",
            "Each cell is the pass rate on the code checks, then the share the judge scored 4 or "
            "5 out of 5 for being proper, logical and useful.",
            "",
            *_by_category(rows, cases.get(ANYTHING.name, {})),
        ]
    lines += ["", "## Speed and cost per answer", "", *_speed_and_cost(rows)]
    failures = [line for row in rows for line in _failures(row, cases)]
    if failures:
        lines += ["", "## Failures", *failures]
    return "\n".join(lines) + "\n"


def main() -> None:
    from evals.runner import JOBS

    parser = argparse.ArgumentParser(description="Write the Markdown report of saved runs.")
    parser.add_argument("out", type=Path)
    parser.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    runs = [json.loads(path.read_text()) for path in args.results]
    cases = {job.name: {c.id: c for c in job.cases()} for job in JOBS}
    args.out.write_text(report(runs, cases))


if __name__ == "__main__":
    main()
