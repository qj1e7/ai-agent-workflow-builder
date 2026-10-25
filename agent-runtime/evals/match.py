import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, create_model

from evals.checks import Check, check
from evals.jobs import Answer, Case, Job

TEMPLATES = (
    Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "builder" / "templates.json"
)

# The builder's parameter rules, mirrored from platform-api builder/templates.py validate_params.
# The agent runtime may not import another context, so a test pins it to the published templates.
TAG_PATTERN = r"^\d+\.\d+\.\d+$"
REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/(?!\.\.?$)[A-Za-z0-9._-]{1,100}$")
RULES: dict[str, dict[str, re.Pattern[str]]] = {
    "release_check": {
        "repo": REPO,
        "ticket_project": re.compile(r"^[A-Z][A-Z0-9]{0,9}$"),
        "tag_pattern": re.compile(re.escape(TAG_PATTERN) + "$"),
        "last_seen_tag": re.compile(TAG_PATTERN),
    }
}
FIXED = {"tag_pattern": TAG_PATTERN}
# Published for the live view, but the builder never suggests it: a watchlist is made by adding
# software on the Software page.
NOT_OFFERED = frozenset({"software_watchlist", "agent_cards"})


def catalog() -> list[dict[str, Any]]:
    published: list[dict[str, Any]] = json.loads(TEMPLATES.read_text())["templates"]
    return [t for t in published if t["key"] not in NOT_OFFERED]


def schema() -> type[BaseModel]:
    fields: dict[str, Any] = {
        p["name"]: (str | None, Field(default=None, description=p["description"]))
        for t in catalog()
        for p in t["params"]
    }
    params = create_model("Params", **fields)
    return create_model(
        "TemplateMatch",
        template=(
            str | None,
            Field(
                description="The key of the template that fits the request, or null if none fits."
            ),
        ),
        params=(params, Field(description="Values taken from the request. Null when not stated.")),
    )


class MatchCase(Case):
    text: str
    template: str | None
    params: dict[str, str] = {}
    may_also: dict[str, list[str]] = {}


def prompt(case: MatchCase) -> str:
    templates = [{k: t[k] for k in ("key", "name", "description", "params")} for t in catalog()]
    return (
        "You help a non-technical support person set up an automated task. Choose the template "
        "that fits their request and fill in only the parameters the request states. Leave a "
        "parameter null when the request does not say it. Never guess a value. If no template "
        "fits, set template to null and leave every parameter null.\n\n"
        f"Templates:\n{json.dumps(templates, indent=2)}\n\nRequest: {case.text}"
    )


def _given(value: BaseModel) -> tuple[str | None, dict[str, str]]:
    data = value.model_dump()
    template = data["template"] or None
    if template and template.strip().lower() in {"none", "null"}:
        template = None
    params = {k: v.strip() for k, v in data["params"].items() if v and v.strip()}
    return template, params


def score(case: MatchCase, answer: Answer) -> list[Check]:
    if not isinstance(answer.value, BaseModel):
        return [check("answered", ["no structured answer"])]
    template, params = _given(answer.value)
    rules = RULES.get(template or "", {})
    invalid = [
        f"{name}={value!r}"
        for name, value in params.items()
        if name not in rules or not rules[name].match(value)
    ]
    missing = [
        f"{name}={want!r}"
        for name, want in case.params.items()
        if params.get(name, "").casefold() != want.casefold()
    ]
    invented = [
        f"{name}={value!r}"
        for name, value in params.items()
        if name not in case.params
        and value not in case.may_also.get(name, [])
        and FIXED.get(name) != value
    ]
    return [
        check("answered", []),
        check(
            "right_template",
            [] if template == case.template else [f"chose {template}, truth {case.template}"],
        ),
        check("params_valid", invalid),
        check("required_params", missing),
        check("no_invented_params", invented),
    ]


MATCH = Job(
    name="match",
    title="Match a task to a template",
    case_type=MatchCase,
    prompt=prompt,
    schema=schema,
    score=score,
    judged=False,
)
