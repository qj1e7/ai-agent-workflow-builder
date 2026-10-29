from pydantic import BaseModel, ConfigDict, Field

from agent_runtime.contract import Finding, FindingState
from agent_runtime.summary import (
    MAX_SUMMARY_LENGTH,
    SUMMARY_TIMEOUT_SECONDS,
    Checked,
    check_prompt,
    usable_summary,
)
from evals.checks import (
    Check,
    check,
    mentions,
    no_invented,
    no_jargon,
    no_themed_names,
    no_write_claim,
    versions_in,
)
from evals.jobs import Answer, Case, Job


class Watched(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    state: FindingState
    newest: str | None = None
    new_versions: list[str] = Field(default_factory=list[str])


class SummariseCase(Case):
    software: list[Watched] = Field(min_length=1)


def checked(case: SummariseCase) -> list[Checked]:
    return [
        Checked(
            w.name,
            Finding(
                software_id=f"sw_{n}",
                state=w.state,
                newest=w.newest,
                new_versions=w.new_versions,
                detail="",
            ),
        )
        for n, w in enumerate(case.software, start=1)
    ]


def prompt(case: SummariseCase) -> str:
    return check_prompt(checked(case))


def score(case: SummariseCase, answer: Answer) -> list[Check]:
    text = answer.text
    source = f"{prompt(case)} GitHub"
    said = versions_in(text)
    behind = [w for w in case.software if w.state == "behind"]
    wanted = sorted(set().union(*(versions_in(w.newest or "") for w in behind)))
    named = [w.name for w in case.software if w.state in ("behind", "cant_check")]
    return [
        check("answered", [] if text else ["no answer"]),
        check(
            "usable_by_product",
            []
            if usable_summary(text)
            else [f"empty, several lines or over {MAX_SUMMARY_LENGTH} characters"],
        ),
        check("every_newest_version", [v for v in wanted if v not in said]),
        check("names_behind_and_unchecked", [n for n in named if not mentions(text, n)]),
        *no_invented(text, source),
        no_jargon(text, allowed=" ".join(w.name for w in case.software)),
        no_themed_names(text),
        no_write_claim(text, source),
    ]


SUMMARISE = Job(
    name="summarise",
    title="Summarise a watchlist check",
    case_type=SummariseCase,
    prompt=prompt,
    schema=None,
    score=score,
    judged=True,
    time_limit_s=SUMMARY_TIMEOUT_SECONDS,
)
