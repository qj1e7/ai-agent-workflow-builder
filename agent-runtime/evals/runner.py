import base64
import json
import math
import os
import re
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from evals.checks import Check
from evals.explain import EXPLAIN
from evals.jobs import Answer, Case, Job
from evals.match import MATCH
from evals.providers import PROVIDERS, Env, NotRun, Target, plan
from evals.summarise import SUMMARISE

JOBS: tuple[Job[Any], ...] = (SUMMARISE, EXPLAIN, MATCH)
PRICING = Path(__file__).parent / "pricing.json"
# CI keeps the endpoints as secrets too. A URL can hold a password or a private host name.
URL_ENVS = ("AZURE_OPENAI_ENDPOINT", "OLLAMA_BASE_URL")
SECRET_ENVS = ("AZURE_OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", *URL_ENVS)
_KEY_SHAPES = re.compile(r"\b(?:sk-[\w*-]{8,}|AIza[\w-]{8,})")
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
    return text


def _failure(error: Exception, env: Env) -> str:
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

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _usage(answer: Answer) -> tuple[int, int]:
    usage = getattr(answer.raw, "usage_metadata", None) or {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def run_case(model: BaseChatModel, job: Job[Any], case: Case, env: Env) -> Outcome:
    started = time.perf_counter()
    try:
        answer = job.ask(model, case)
    except Exception as error:
        return Outcome(case.id, [Check("answered", False, _failure(error, env))], None, 0, 0, "")
    latency = (time.perf_counter() - started) * 1000
    tokens_in, tokens_out = _usage(answer)
    return Outcome(case.id, job.score(case, answer), latency, tokens_in, tokens_out, answer.text)


class Verdict(BaseModel):
    score: int = Field(
        ge=1,
        le=5,
        description="1 to 5. 5 means accurate to the input and clear to a non-technical reader.",
    )


def judge(model: BaseChatModel, prompt: str, answer: str) -> int | None:
    question = (
        "Rate this answer from 1 to 5. Judge only whether it is accurate to the task input and "
        f"clear to a non-technical support person.\n\nTask given to the assistant:\n{prompt}\n\n"
        f"Answer:\n{answer}"
    )
    try:
        verdict = model.with_structured_output(Verdict).invoke(question)
    except Exception:
        return None
    return verdict.score if isinstance(verdict, Verdict) else None


def judge_target(env: Env) -> Target | None:
    spec = env.get("EVAL_JUDGE", "")
    if ":" not in spec:
        return None
    provider_name, model = spec.split(":", 1)
    for provider in PROVIDERS:
        if provider.name == provider_name and all(env.get(n) for n in provider.needs):
            return Target(provider.name, model, provider.settings(env, model))
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
        per_call = (
            statistics.fmean(tokens_in) * price["input_usd_per_mtok"]
            + statistics.fmean(tokens_out) * price["output_usd_per_mtok"]
        ) / 1_000_000
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


def run_target(
    target: Target, env: Env, judge_model: BaseChatModel | None, pricing: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        # Building can fail on a malformed setting, and the error can quote it.
        model = target.build()
        started = time.perf_counter()
        model.invoke(WARM_UP)
        warm_up_ms = round((time.perf_counter() - started) * 1000)
        models = {job.name: model_for(job, target, model) for job in JOBS}
    except Exception as error:
        return {"error": _failure(error, env)}, []
    rows: list[dict[str, Any]] = []
    for job in JOBS:
        outcomes: list[Outcome] = []
        for case in job.cases():
            outcome = run_case(models[job.name], job, case, env)
            if judge_model is not None and job.judged and outcome.answer:
                outcome = replace(
                    outcome, judge=judge(judge_model, job.prompt(case), outcome.answer)
                )
            outcomes.append(outcome)
            mark = "pass" if outcome.passed else "FAIL"
            print(f"  {target.label} {job.name}/{case.id}: {mark}", flush=True)
        rows.append(summarise_job(target, job, outcomes, pricing))
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
    for target in targets:
        print(f"Running {target.label}", flush=True)
        status, rows = run_target(target, env, judge_model, pricing)
        if "error" in status:
            not_run.append(_redacted(NotRun(target.provider, target.model, status["error"]), env))
            continue
        models.append({"provider": target.provider, "model": target.model, **status})
        results.extend(rows)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": {job.name: len(job.cases()) for job in JOBS},
        "judge": judge_spec.label if judge_spec else None,
        "models": models,
        "not_run": [n.__dict__ for n in not_run],
        "results": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print()
    print(table(results, not_run))
    print(f"\nWrote {out}")
    return 0
