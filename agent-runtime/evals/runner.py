import base64
import json
import math
import os
import re
import statistics
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from agent_runtime.monitoring.masking import MASKED_SHAPES
from agent_runtime.planner_led import PLANNER_MODES, PlannerMode
from evals.answer import ANSWER, ANSWER_LED
from evals.anything import ANYTHING, ANYTHING_LED
from evals.budget import (
    BUDGET_USED_UP,
    Spend,
    budget_spent,
    cached_tokens,
    dollars_for,
    metered,
    spend_for,
    spent_words,
)
from evals.checks import Check
from evals.choose import CHOOSE
from evals.draft import DRAFT
from evals.explain import EXPLAIN
from evals.explain_wording import EXPLAIN_WORDING
from evals.jobs import Answer, Case, Job, marked
from evals.providers import PROVIDERS, Env, NotRun, Target, plan
from evals.red_team import RED_TEAM
from evals.reply import LED_TWINS, REPLY, REPLY_DEV, REPLY_GATE, SPIKE, SPIKE_DEV
from evals.report import report
from evals.scenario_explainer import SCENARIO_EXPLAINER
from evals.scenario_writer import SCENARIO_WRITER
from evals.summarise import SUMMARISE
from evals.troubleshoot import TROUBLESHOOT
from evals.workflow_draft import WORKFLOW_DRAFT

JOBS: tuple[Job[Any], ...] = (
    SUMMARISE,
    EXPLAIN,
    DRAFT,
    CHOOSE,
    ANSWER,
    ANYTHING,
    REPLY,
    REPLY_GATE,
    REPLY_DEV,
    RED_TEAM,
    SPIKE,
    SPIKE_DEV,
    EXPLAIN_WORDING,
    WORKFLOW_DRAFT,
    TROUBLESHOOT,
    SCENARIO_WRITER,
    SCENARIO_EXPLAINER,
)
PARTS_OF_REPLY: Final = frozenset({REPLY_GATE.name, REPLY_DEV.name, SPIKE_DEV.name})
"""Jobs that run part of the reply job's cases. A run of every job leaves them out, so it runs
each case once."""
ONLY_WHEN_NAMED: Final = frozenset({*PARTS_OF_REPLY, WORKFLOW_DRAFT.name})
"""Jobs a run of every job leaves out: the parts of the reply job, and the workflow drafter, whose
one draft costs as much as 17 to 33 Planner messages (ADR 0051, section 7)."""
PRICING = Path(__file__).parent / "pricing.json"
# CI keeps the endpoints as secrets too. A URL can hold a password or a private host name.
URL_ENVS = ("AZURE_OPENAI_ENDPOINT", "OLLAMA_BASE_URL", "AGENT_MODEL_BASE_URL")
SECRET_ENVS = (
    "AZURE_OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "AGENT_MODEL_API_KEY",
    *URL_ENVS,
)
# Every shape the masker knows, and a key a provider's error prints cut short, as "sk-****ab3d".
_KEY_SHAPES = re.compile("|".join([r"\b(?:sk-[\w*-]{8,}|AIza[\w-]{8,})", MASKED_SHAPES.pattern]))
# A gateway names the key's owner in its own errors, such as a spent budget.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?::[\w-]+)?")
WARM_UP = "Reply with the word ready."
# A host name, host label or user name shorter than this is not redacted on its own. Short ones
# such as "db", "a" or "host" are ordinary words in error text, so removing them would wreck the
# message. They are still removed inside the longer forms, such as the whole URL. A password is
# always redacted, however short: hiding a few stray letters is better than showing a credential.
MIN_FRAGMENT = 6
# Pydantic quotes the settings a model was built with, cut short, so a cut URL would not match.
_PYDANTIC_INPUT = re.compile(r"input_value=(?:(?!, input_type=).)*")


def _b64(text: str) -> set[str]:
    encoded = base64.b64encode(text.encode()).decode()
    return {encoded, encoded.rstrip("=")}


def _url_fragments(url: str) -> set[str]:
    rest = url.split("://", 1)[-1]
    netloc = re.split(r"[/?#]", rest, maxsplit=1)[0]
    userinfo, _, hostport = netloc.rpartition("@")
    host = hostport[1:].partition("]")[0] if hostport.startswith("[") else hostport
    host = re.sub(r":\d+$", "", host)
    # Not secret on their own, so only long enough ones are redacted. The first label of the host
    # is the Azure resource name.
    names = {host, host.split(".")[0]}
    # Secret, or holding a secret, so always redacted.
    secrets = {netloc, unquote(netloc), unquote(url)}
    if userinfo:
        user, _, password = userinfo.partition(":")
        plain_user, plain_password = unquote(user), unquote(password)
        names |= {user, plain_user}
        secrets |= {password, plain_password}
        # Basic auth sends base64 of "user:password" in a header.
        secrets |= _b64(f"{plain_user}:{plain_password}") | _b64(f"{user}:{password}")
    return {name for name in names if len(name) >= MIN_FRAGMENT} | secrets


def _secret_values(env: Env) -> list[str]:
    values: set[str] = set()
    for name in SECRET_ENVS:
        value = env.get(name, "").strip()
        if not value:
            continue
        # The whole value is always redacted, however short. Only pieces of it have a minimum.
        values |= {value, value.rstrip("/")}
        if name in URL_ENVS:
            values |= _url_fragments(value)
    # Longest first, so a whole URL is replaced before the host name inside it.
    return sorted(values - {""}, key=len, reverse=True)


def redact(text: str, env: Env) -> str:
    text = _PYDANTIC_INPUT.sub("input_value=[hidden]", text)
    text = _KEY_SHAPES.sub("[redacted]", text)
    for secret in _secret_values(env):
        text = text.replace(secret, "[redacted]")
    return _EMAIL.sub("[redacted]", text)


def _failure(error: Exception, env: Env) -> str:
    if budget_spent(error):
        return BUDGET_USED_UP
    # Redact before cutting, so a secret is never cut in half and left partly visible.
    return redact(f"{type(error).__name__}: {error}", env)[:500]


@dataclass(frozen=True)
class Outcome:
    case: str
    checks: list[Check]
    latency_ms: float | None
    input_tokens: int
    output_tokens: int
    answer: str
    judge: int | None = None
    cache_read: int = 0
    cache_written: int = 0
    judges: tuple[int | None, ...] = ()
    """Every judge run's score, None for a run that failed, when the job asks for more than one."""

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _usage(answer: Answer) -> tuple[int, int, int, int]:
    """Every call the case made: its input and output tokens, and the input the prompt cache read
    and wrote."""
    usage = getattr(answer.raw, "usage_metadata", None) or {}
    read, written = cached_tokens(usage)
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)), read, written


def run_case(
    model: BaseChatModel, job: Job[Any], case: Case, env: Env, marker: str = ""
) -> Outcome:
    started = time.perf_counter()
    try:
        answer = job.ask(model, case, marker)
    except Exception as error:
        return Outcome(case.id, [Check("answered", False, _failure(error, env))], None, 0, 0, "")
    latency = (time.perf_counter() - started) * 1000
    tokens_in, tokens_out, read, written = _usage(answer)
    checks = job.score(case, answer)
    return Outcome(
        case.id, checks, latency, tokens_in, tokens_out, answer.text, None, read, written
    )


class Verdict(BaseModel):
    score: int = Field(ge=1, le=5, description="1 to 5, where 5 is best, as the question says.")


def accuracy_question(prompt: str, answer: str) -> str:
    return (
        "Rate this answer from 1 to 5. Judge only whether it is accurate to the task input and "
        f"clear to a non-technical support person.\n\nTask given to the assistant:\n{prompt}\n\n"
        f"Answer:\n{answer}"
    )


def judge(model: BaseChatModel, question: str) -> int | None:
    try:
        verdict = model.with_structured_output(Verdict).invoke(question)
    except Exception:
        return None
    return verdict.score if isinstance(verdict, Verdict) else None


def judged(
    model: BaseChatModel, question: str, marker: str, runs: int
) -> tuple[int | None, tuple[int | None, ...]]:
    """The score of `runs` judge runs, and every run's score. Any run's 1 is the score, because
    each run is a chance to catch a claim, and none is thrown away. Otherwise the score is the
    median. Each run after the first has its own marker, so a gateway's store can't answer it
    with the first. A failed run is left out, and an even count takes the lower middle, so a
    failure can only lower the score."""
    scores = tuple(
        judge(model, marked(question, f"{marker} judge {n}" if marker and n > 1 else marker))
        for n in range(1, runs + 1)
    )
    given = [score for score in scores if score is not None]
    if not given:
        return None, scores
    return (1 if 1 in given else statistics.median_low(given)), scores


def judge_target(env: Env) -> Target | None:
    spec = env.get("EVAL_JUDGE", "")
    if ":" not in spec:
        return None
    provider_name, model = spec.split(":", 1)
    for provider in PROVIDERS:
        if provider.name == provider_name and all(env.get(n) for n in provider.needs):
            return Target(provider.name, model, provider.settings(env, model), provider.client)
    return None


def build_judge(env: Env) -> tuple[BaseChatModel | None, Target | None, NotRun | None]:
    spec = env.get("EVAL_JUDGE", "")
    try:
        target = judge_target(env)
        return (target.build() if target else None), target, None
    except Exception as error:
        provider, _, model = spec.partition(":")
        return None, None, NotRun(provider, model or None, f"judge: {_failure(error, env)}")


def percentile(values: Sequence[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def price_for(target: Target, pricing: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return pricing.get(target.label) or pricing.get(f"{target.provider}:*")


def summarise_job(
    target: Target, job: Job[Any], outcomes: list[Outcome], pricing: Mapping[str, Any]
) -> dict[str, Any]:
    answered = [o for o in outcomes if o.latency_ms is not None]
    latencies = [o.latency_ms for o in answered if o.latency_ms is not None]
    # A case that errored used no tokens. Counting it would make a failing provider look cheap.
    tokens_in = [o.input_tokens for o in answered]
    tokens_out = [o.output_tokens for o in answered]
    limit_ms = None if job.time_limit_s is None else job.time_limit_s * 1000
    within = (
        [o.latency_ms is not None and o.latency_ms <= limit_ms for o in outcomes]
        if limit_ms
        else []
    )
    price = price_for(target, pricing)
    cost = None
    if price is not None and answered:
        per_call = statistics.fmean(
            dollars_for(o.input_tokens, o.output_tokens, o.cache_read, o.cache_written, price)
            for o in answered
        )
        cost = round(per_call * 100, 4)
    names = list(dict.fromkeys(c.name for o in outcomes for c in o.checks))
    judged = [o.judge for o in outcomes if o.judge is not None]
    return {
        "provider": target.provider,
        "model": target.model,
        "job": job.name,
        "cases": len(outcomes),
        "passed": sum(o.passed for o in outcomes),
        "pass_rate": round(sum(o.passed for o in outcomes) / len(outcomes), 3),
        "checks_passed": {
            n: sum(any(c.name == n and c.passed for c in o.checks) for o in outcomes) for n in names
        },
        "latency_ms": {
            "mean": round(statistics.fmean(latencies)) if latencies else None,
            "median": round(statistics.median(latencies)) if latencies else None,
            "p95": round(percentile(latencies, 0.95) or 0) if latencies else None,
        },
        # Cases that took longer than the product waits, or errored. Their answer would be lost.
        "over_product_limit": within.count(False) if limit_ms else None,
        "tokens": {
            "input_mean": round(statistics.fmean(tokens_in)) if answered else None,
            "output_mean": round(statistics.fmean(tokens_out)) if answered else None,
            "input_total": sum(tokens_in),
            "output_total": sum(tokens_out),
            "cache_read_total": sum(o.cache_read for o in answered),
            "cache_written_total": sum(o.cache_written for o in answered),
        },
        "cost_per_100_runs_usd": cost,
        "price_source": price["source"] if price else "not known",
        "judge_mean": round(statistics.fmean(judged), 2) if judged else None,
        "outcomes": [
            {
                "case": o.case,
                "passed": o.passed,
                "failed": {c.name: c.detail for c in o.checks if not c.passed},
                "latency_ms": None if o.latency_ms is None else round(o.latency_ms),
                **({"within_product_limit": within[i]} if limit_ms else {}),
                "answer": o.answer,
                **({"judge": o.judge} if o.judge is not None else {}),
                **({"judges": list(o.judges)} if len(o.judges) > 1 else {}),
            }
            for i, o in enumerate(outcomes)
        ],
    }


def model_for(job: Job[Any], target: Target, shared: BaseChatModel) -> BaseChatModel:
    # The product calls the summary model once, with no retries. Keep the long timeout, so a slow
    # answer is still measured, and count it against the product's limit instead.
    if job.time_limit_s is not None and "max_retries" in target.kwargs:
        return target.build(max_retries=0)
    return shared


AI_LED: Final[dict[str, Job[Any]]] = {
    ANSWER_LED.name: ANSWER_LED,
    ANYTHING_LED.name: ANYTHING_LED,
    **LED_TWINS,
}
"""The jobs that run the Planner, on the AI-led Planner (ADR 0049). A job not here runs as it is:
red_team plays the verifier, which both modes share."""


def planner_mode(env: Env) -> PlannerMode:
    named = env.get("EVAL_PLANNER_MODE", "").strip() or "rules"
    for mode in PLANNER_MODES:
        if named == mode:
            return mode
    raise ValueError(f"EVAL_PLANNER_MODE must be one of {', '.join(PLANNER_MODES)}")


def jobs_chosen(env: Env) -> tuple[Job[Any], ...]:
    wanted = [name.strip() for name in env.get("EVAL_JOBS", "").split(",") if name.strip()]
    unknown = sorted(set(wanted) - {job.name for job in JOBS})
    if unknown:
        raise ValueError(f"EVAL_JOBS names no job: {', '.join(unknown)}")
    chosen = [
        job for job in JOBS if (job.name in wanted if wanted else job.name not in ONLY_WHEN_NAMED)
    ]
    if planner_mode(env) == "ai_led":
        chosen = [AI_LED.get(job.name, job) for job in chosen]
    return tuple(chosen)


def run_target(
    target: Target,
    env: Env,
    judge_model: BaseChatModel | None,
    pricing: Mapping[str, Any],
    marker: str = "",
    jobs: tuple[Job[Any], ...] = JOBS,
    spend: Spend | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The target's rows, case by case, until `spend` says to stop. A stop keeps what ran."""
    spend = spend or Spend(max_calls=10**9, max_dollars=float("inf"), prices={})
    stopped = spend.stop_reason(1)
    if stopped is not None:
        return {"stopped": stopped}, []
    try:
        # Building can fail on a malformed setting, and the error can quote it.
        model = target.build()
        started = time.perf_counter()
        model.invoke(marked(WARM_UP, marker))
        warm_up_ms = round((time.perf_counter() - started) * 1000)
        models = {job.name: model_for(job, target, model) for job in jobs}
    except Exception as error:
        status = {"error": _failure(error, env)}
        return ({**status, "stopped": BUDGET_USED_UP} if budget_spent(error) else status), []
    rows: list[dict[str, Any]] = []
    for job in jobs:
        outcomes: list[Outcome] = []
        cases = job.cases()
        ahead = job.most_calls + (job.judge_runs if judge_model is not None and job.judged else 0)
        stopped: str | None = None
        for case in cases:
            stopped = spend.stop_reason(ahead)
            if stopped is not None:
                break
            outcome = run_case(models[job.name], job, case, env, marker)
            if judge_model is not None and job.judged and outcome.answer:
                question = (
                    job.judge_question(case, outcome.answer)
                    if job.judge_question
                    else accuracy_question(job.prompt(case), outcome.answer)
                )
                score, scores = judged(judge_model, question, marker, job.judge_runs)
                outcome = replace(outcome, judge=score, judges=scores)
            if spend.gateway_out:
                # The case met the spent budget, so its score says nothing about the model.
                stopped = BUDGET_USED_UP
                break
            outcomes.append(outcome)
            mark = "pass" if outcome.passed else "FAIL"
            print(f"  {target.label} {job.name}/{case.id}: {mark}", flush=True)
        if outcomes:
            rows.append({**summarise_job(target, job, outcomes, pricing), "of": len(cases)})
        if stopped is not None:
            print(f"  {target.label}: stopped at {stopped}", flush=True)
            return {"warm_up_ms": warm_up_ms, "stopped": stopped}, rows
    return {"warm_up_ms": warm_up_ms}, rows


def _cell(value: object) -> str:
    return "-" if value is None else str(value)


def _seconds(ms: float | None) -> str:
    return "-" if ms is None else f"{ms / 1000:.1f}"


def table(results: list[dict[str, Any]], not_run: list[NotRun]) -> str:
    head = (
        "provider:model",
        "job",
        "pass",
        "median s",
        "p95 s",
        "over limit",
        "tokens in/out",
        "$/100 runs",
    )
    lines: list[tuple[str, ...]] = [head]
    for r in results:
        cost = r["cost_per_100_runs_usd"]
        lines.append(
            (
                f"{r['provider']}:{r['model']}",
                r["job"],
                f"{r['passed']}/{r['cases']} ({r['pass_rate']:.0%})",
                _seconds(r["latency_ms"]["median"]),
                _seconds(r["latency_ms"]["p95"]),
                _cell(r["over_product_limit"]),
                f"{_cell(r['tokens']['input_mean'])}/{_cell(r['tokens']['output_mean'])}",
                "unknown" if cost is None else f"{cost:.4f}",
            )
        )
    widths = [max(len(row[i]) for row in lines) for i in range(len(head))]
    out = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)) for row in lines]
    out += [f"not run  {n.provider}{':' + n.model if n.model else ''}  {n.reason}" for n in not_run]
    return "\n".join(out)


def _redacted(skipped: NotRun, env: Env) -> NotRun:
    return replace(skipped, reason=redact(skipped.reason, env))


def main(out: Path, env: Env | None = None) -> int:
    env = dict(os.environ) if env is None else env
    pricing = json.loads(PRICING.read_text())
    targets, planned_skips = plan(env)
    # Every reason is redacted before it is kept, because results.json is uploaded from CI.
    not_run = [_redacted(n, env) for n in planned_skips]
    judge_model, judge_spec, judge_skip = build_judge(env)
    if judge_skip is not None:
        not_run.append(judge_skip)
    results: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    marker = env.get("EVAL_MARKER") or uuid.uuid4().hex[:12]
    jobs = jobs_chosen(env)
    spend = spend_for(env, pricing)
    stopped: str | None = None
    with metered(spend):
        for target in targets:
            if stopped is not None:
                not_run.append(NotRun(target.provider, target.model, f"stopped at {stopped}"))
                continue
            print(f"Running {target.label}", flush=True)
            status, rows = run_target(target, env, judge_model, pricing, marker, jobs, spend)
            stopped = status.pop("stopped", None)
            if "error" in status:
                failed = NotRun(target.provider, target.model, status["error"])
                not_run.append(_redacted(failed, env))
            elif rows or stopped is None:
                models.append({"provider": target.provider, "model": target.model, **status})
            else:
                not_run.append(NotRun(target.provider, target.model, f"stopped at {stopped}"))
            results.extend(rows)
    results_file = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "marker": marker,
        "planner_mode": planner_mode(env),
        "cases": {job.name: len(job.cases()) for job in jobs},
        "judge": judge_spec.label if judge_spec else None,
        "models": models,
        "not_run": [n.__dict__ for n in not_run],
        "spend": {**spend.summary(), "stopped": stopped},
        "results": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results_file, indent=2) + "\n")
    cases = {job.name: {c.id: c for c in job.cases()} for job in jobs}
    out.with_suffix(".md").write_text(report([results_file], cases))
    print()
    print(table(results, not_run))
    print(f"\n{spent_words(results_file['spend'])}")
    print(f"Wrote {out} and its report, {out.with_suffix('.md').name}")
    return 0
