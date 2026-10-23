from pydantic import Field

from agent_runtime.summary import (
    MAX_SUMMARY_LENGTH,
    SUMMARY_TIMEOUT_SECONDS,
    summary_prompt,
    usable_summary,
)
from evals.checks import (
    Check,
    check,
    no_invented,
    no_jargon,
    no_themed_names,
    no_write_claim,
    versions_in,
)
from evals.jobs import Answer, Case, Job


class SummariseCase(Case):
    repo: str
    last_known_tag: str
    new_tags: list[str] = Field(min_length=1)


def prompt(case: SummariseCase) -> str:
    return summary_prompt(case.repo, case.last_known_tag, case.new_tags)


def score(case: SummariseCase, answer: Answer) -> list[Check]:
    text = answer.text
    source = " ".join([case.repo, case.last_known_tag, *case.new_tags, "GitHub"])
    said = versions_in(text)
    wanted = sorted(set().union(*(versions_in(tag) for tag in case.new_tags)))
    return [
        check("answered", [] if text else ["no answer"]),
        check(
            "usable_by_product",
            []
            if usable_summary(text)
            else [f"empty, several lines or over {MAX_SUMMARY_LENGTH} characters"],
        ),
        check("every_new_version", [v for v in wanted if v not in said]),
        *no_invented(text, source),
        no_jargon(text, allowed=case.repo),
        no_themed_names(text),
        no_write_claim(text, source),
    ]


SUMMARISE = Job(
    name="summarise",
    title="Summarise a release finding",
    case_type=SummariseCase,
    prompt=prompt,
    schema=None,
    score=score,
    judged=True,
    time_limit_s=SUMMARY_TIMEOUT_SECONDS,
)
