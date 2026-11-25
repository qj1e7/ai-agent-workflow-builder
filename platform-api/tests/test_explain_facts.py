import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from platform_api.builder.explain import TooLongToSmooth, explain_facts, to_smooth, wording_of
from platform_api.builder.workflow_report import (
    Drafted,
    DraftSetting,
    Needed,
    WorkflowReport,
    workflow_report,
)
from platform_api.orchestration import CodeWording, ExplainFact
from tests.test_workflow_report import (
    CARDS,
    GOLDEN,
    OVERRIDES,
    TEAM,
    Doc,
    fastapi,
    made_in_n8n,
    node,
    react,
    report_of,
)

QUOTED = re.compile(r"“([^”]*)”")
NEGATIONS = frozenset({"not", "no", "never", "nothing", "none", "nor", "cannot", "without"})


def fact(kind: str, *together: str, negated: bool = False) -> ExplainFact:
    return ExplainFact.model_validate({"kind": kind, "together": together, "negated": negated})


def sentences(wording: str) -> list[str]:
    masked = QUOTED.sub(lambda m: "“" + "x" * len(m[1]) + "”", wording)
    ends = [m.end() for m in re.finditer(r"\.(?=\s|$)", masked)]
    bounds = zip([0, *ends], [*ends, len(wording)], strict=True)
    return [wording[a:b].strip() for a, b in bounds if wording[a:b].strip()]


def holds(sentence: str, item: str, quoted: set[str]) -> bool:
    if item in quoted:
        return f"“{item}”" in sentence
    words = QUOTED.sub(" ", sentence)
    return re.search(rf"(?<![\w']){re.escape(item)}(?:s|es)?(?![\w'])", words, re.I) is not None


def negated(sentence: str) -> bool:
    words = re.findall(r"[\w']+", QUOTED.sub(" ", sentence).lower())
    return any(w in NEGATIONS or w.endswith("n't") for w in words)


def test_the_fastapi_release_check_states_when_it_runs_what_it_reads_writes_and_changes():
    report = report_of(fastapi())
    assert wording_of(report.in_short) == (
        "Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. "
        "It can create Jira tickets in “MOCK”, each after approval. It changes nothing else."
    )
    assert explain_facts(report) == [
        fact("runs", "day", "8:00"),
        fact("reads", "reads", "GitHub", "fastapi/fastapi"),
        fact("reads", "reads", "Jira", "MOCK"),
        fact("writes", "create", "Jira", "MOCK", "approval"),
        fact("changes", "changes", "nothing", "else", negated=True),
    ]


def test_a_post_with_its_words_written_out_keeps_them_and_the_place():
    assert explain_facts(report_of(react())) == [
        fact("runs", "Monday", "9:00"),
        fact("reads", "reads", "GitHub", "facebook/react"),
        fact("reads", "reads", "Jira", "WEB"),
        fact("posts", "post", "Slack", "A new React release is out.", "C0RELEASES"),
        fact("changes", "changes", "nothing", negated=True),
    ]


def test_each_of_n8n_s_blocks_that_can_t_run_yet_is_a_negated_fact():
    assert explain_facts(report_of(made_in_n8n(), "n8n")) == [
        fact("runs", "Monday", "9:00"),
        fact("reads", "reads", "GitHub", "fastapi/fastapi"),
        fact("writes", "change", "Jira", "Open an issue", negated=True),
        fact("posts", "post", "Slack", "Read FastAPI", "C0TEAM", negated=True),
        fact("writes", "change", "send", "Call the hook", negated=True),
        fact("changes", "changes", "nothing", "else", negated=True),
    ]


def test_a_write_the_platform_refuses_says_nothing_asks_for_approval_before_it():
    document = fastapi()
    document["connections"]["Newer?"]["main"][0] = [
        {"node": "Create ticket", "type": "main", "index": 0}
    ]
    [write] = [f for f in explain_facts(report_of(document)) if f.kind == "writes"]
    assert write == fact("writes", "create", "Jira", "MOCK", negated=True)


def no_start() -> Doc:
    document = made_in_n8n()
    del document["connections"]["Every Monday"]
    document["nodes"] = [n for n in document["nodes"] if n["name"] != "Every Monday"]
    return document


def every_two_hours() -> Doc:
    document = made_in_n8n()
    node(document, "Every Monday")["parameters"]["rule"]["interval"] = [
        {"field": "hours", "hoursInterval": 2}
    ]
    return document


def from_the_portal() -> Doc:
    return {
        "name": "Ping the team",
        "nodes": [
            {"name": "Start", "type": "CUSTOM.wabStartFromPortal", "typeVersion": 1},
            {"name": "Tell", "type": "CUSTOM.wabTell", "typeVersion": 1, "parameters": {}},
        ],
        "connections": {"Start": {"main": [[{"node": "Tell", "type": "main", "index": 0}]]}},
        "settings": {},
    }


@pytest.mark.parametrize(
    ("document", "runs"),
    [
        pytest.param(no_start, fact("runs", "starts", negated=True), id="nothing-starts-it"),
        pytest.param(every_two_hours, fact("runs", "schedule", negated=True), id="unshown"),
        pytest.param(from_the_portal, fact("runs", "starts"), id="someone-starts-it"),
    ],
)
def test_a_start_that_is_not_a_day_and_a_time_is_its_one_word(
    document: Callable[[], Doc], runs: ExplainFact
):
    assert explain_facts(report_of(document(), "n8n"))[0] == runs


def test_an_in_short_longer_than_the_runtime_takes_is_never_sent():
    assert to_smooth(report_of(react("A new React release is out. " * 50))) == TooLongToSmooth()


def test_a_workflow_the_checker_can_t_read_states_no_fact():
    report = report_of({"name": "Broken", "nodes": "none"})
    assert explain_facts(report) == []


def golden(path: Path) -> Callable[[], WorkflowReport]:
    return lambda: report_of(json.loads(path.read_text()))


REPORTS = [
    pytest.param(lambda: report_of(fastapi()), id="fastapi"),
    pytest.param(lambda: report_of(react()), id="react"),
    pytest.param(lambda: report_of(made_in_n8n(), "n8n"), id="made-in-n8n"),
    pytest.param(lambda: report_of(made_in_n8n(), "n8n", OVERRIDES), id="made-in-n8n-overrides"),
    pytest.param(lambda: report_of(no_start(), "n8n"), id="nothing-starts-it"),
    pytest.param(lambda: report_of(every_two_hours(), "n8n"), id="unshown-schedule"),
    pytest.param(lambda: report_of(from_the_portal()), id="from-the-portal"),
    pytest.param(
        lambda: workflow_report(
            Drafted(fastapi(), CARDS, (DraftSetting("Run time", Needed()),)), TEAM
        ),
        id="drafted",
    ),
    *(
        pytest.param(golden(path), id=f"golden-{path.stem}")
        for path in sorted(GOLDEN.glob("*.json"))
        if path.stem != "served_types"
    ),
]


@pytest.mark.parametrize("make", REPORTS)
def test_each_fact_sits_in_one_sentence_of_code_s_wording_with_its_negation(make: Any):
    report = make()
    wording = wording_of(report.in_short)
    said = sentences(wording)
    quoted = set(QUOTED.findall(wording))
    facts = explain_facts(report)
    assert facts, "In short states something"
    for f in facts:
        holding = [s for s in said if all(holds(s, item, quoted) for item in f.together)]
        assert holding, (f, said)
        if f.negated:
            assert any(negated(s) for s in holding), (f, holding)
    assert to_smooth(report) == CodeWording(wording=wording, facts=facts), (
        "within what the agent runtime takes"
    )
