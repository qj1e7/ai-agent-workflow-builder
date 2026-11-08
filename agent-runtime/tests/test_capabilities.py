import inspect
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from agent_runtime import watchlist
from agent_runtime.abilities import (
    ABILITIES,
    ABILITY_OF,
    CAPABILITIES,
    EXAMPLES,
    UNSUPPORTED_WORDS,
    VULNERABILITIES_PLANNED,
    why_not,
)
from agent_runtime.api import Settings, create_app
from agent_runtime.contract import CapabilityList
from agent_runtime.tools import MODEL_FREE_TOOLS, TOOLS

READY = [c for c in CAPABILITIES if c.state == "ready"]
NOT_READY = [c for c in CAPABILITIES if c.state != "ready"]
BY_ID = {c.id: c for c in CAPABILITIES}
KEY = "test-agent-key-not-a-secret"


def client() -> TestClient:
    settings = Settings.from_env(
        {"AGENT_API_KEY": KEY, "CALLBACK_ALLOWED_ORIGINS": "http://platform-api:8000"}
    )
    return TestClient(create_app(settings))


def test_ids_are_unique():
    assert [i for i, n in Counter(c.id for c in CAPABILITIES).items() if n > 1] == []


def test_a_ready_capability_with_tools_is_backed_by_an_ability_and_by_each_tool():
    tool_ids = {t.id for t in TOOLS}
    line_names = {a.plain for a in ABILITIES}
    for entry in READY:
        if entry.tools:
            assert ABILITY_OF.get(entry.id) in line_names, entry.id
        assert set(entry.tools) <= tool_ids, entry.id


def test_every_ability_line_has_a_ready_capability():
    backed = {ABILITY_OF[c.id] for c in READY if c.id in ABILITY_OF}
    assert {a.plain for a in ABILITIES} - backed == set()


def test_only_a_ready_capability_has_tools_or_an_ability_line():
    for entry in NOT_READY:
        assert entry.tools == [], entry.id
        assert entry.id not in ABILITY_OF, entry.id


def test_every_tool_is_offered_by_a_ready_capability():
    offered = {tool for c in READY for tool in c.tools}
    assert {t.id for t in TOOLS} - offered == set()


def test_ability_lines_name_only_known_capabilities():
    assert set(ABILITY_OF) <= set(BY_ID)


def test_only_the_platform_duty_is_ready_without_an_ability_line():
    assert [c.id for c in READY if c.id not in ABILITY_OF] == [
        c.id for c in CAPABILITIES if c.platform
    ]
    assert [c.id for c in CAPABILITIES if c.platform] == ["teams.ask"]


def test_a_ready_entry_needs_the_model_when_a_tool_only_the_card_runner_calls_is_its_tool():
    for entry in READY:
        if entry.tools:
            assert entry.needs_model == bool(set(entry.tools) - MODEL_FREE_TOOLS), entry.id


def test_the_tools_that_need_no_model_are_the_ones_the_watchlist_reads_by_itself():
    source = inspect.getsource(watchlist)
    assert "read_releases" in source
    assert "jira" not in source.lower()
    assert sorted(MODEL_FREE_TOOLS) == ["github.read_releases"]


def test_the_model_does_the_summary_and_nothing_else_without_tools_does():
    assert [c.id for c in READY if not c.tools and c.needs_model] == ["summarise"]


def test_a_refusal_has_words_and_a_ready_entry_has_none():
    for entry in CAPABILITIES:
        assert (entry.cant is None) == (entry.state == "ready"), entry.id
        assert (entry.why is None) == (entry.state == "ready"), entry.id


def test_a_write_capability_that_is_ready_is_the_one_ticket_tool():
    writers = [c for c in READY if c.kind == "write"]
    assert [(c.id, c.tools) for c in writers] == [("jira.create", ["jira.create_ticket"])]


def test_the_jira_filters_n5_built_are_ready_and_older_tickets_are_not():
    assert BY_ID["jira.find_by_update"].state == "ready"
    assert BY_ID["jira.find_by_update"].tools == ["jira.search"]
    assert BY_ID["jira.find_older"].state == "planned"


def test_component_and_priority_are_named_as_something_the_agents_cannot_see():
    entry = BY_ID["jira.find_by_detail"]
    assert entry.state == "planned"
    assert entry.cant == "see a ticket's component or priority"


def test_every_example_needs_only_ready_capabilities():
    for example in EXAMPLES:
        for needed in example.needs:
            assert BY_ID[needed].state == "ready", (example.text, needed)


def test_the_day_one_examples_are_about_software_versioning():
    assert [(e.text, e.kind) for e in EXAMPLES] == [
        ("Keep track of the LangGraph version", "monitor"),
        ("What can you do?", "learn"),
    ]


def test_only_the_software_versioning_capabilities_are_marked_focus():
    assert {c.id for c in CAPABILITIES if c.focus} == {
        "github.releases",
        "jira.create",
        "teams.ask",
    }
    assert all(c.state == "ready" for c in CAPABILITIES if c.focus)


def test_a_request_for_email_is_still_refused_in_words_though_it_is_not_a_focus_capability():
    assert not BY_ID["email.send"].focus
    refusal = why_not("do", "Send email to the team")
    assert refusal is not None
    assert refusal.startswith("I can't send email to the team.")
    assert "yet" not in refusal.split(".")[0]


def test_the_vulnerability_pre_check_stays_while_its_capability_is_not_ready():
    entry = BY_ID["registries.check"]
    assert entry.state == "planned"
    assert why_not("do", "Check for known vulnerabilities") == VULNERABILITIES_PLANNED


def test_the_route_needs_the_key():
    assert client().get("/v1/capabilities").status_code == 401


def test_the_route_serves_the_registry_and_the_examples():
    response = client().get("/v1/capabilities", headers={"X-Agent-Key": KEY})
    assert response.status_code == 200
    served = CapabilityList.model_validate(response.json())
    assert served.capabilities == list(CAPABILITIES)
    assert served.examples == list(EXAMPLES)


@pytest.mark.parametrize("entry", NOT_READY, ids=lambda c: c.id)
def test_every_entry_that_is_not_ready_is_refused_when_its_own_words_are_asked_for(entry):
    assert any(why_not(kind, entry.plain) for kind in ("look_for", "do")), entry.id


def test_a_search_older_than_some_days_is_a_filter_and_past_the_newest_is_not():
    assert why_not("look_for", "Bug tickets older than 10 days") is None
    refused = why_not("look_for", "Tickets beyond the newest 50")
    assert refused is not None and refused.startswith(
        f"I can't {BY_ID['jira.find_older'].cant} yet."
    )


def test_a_refusal_ends_with_what_every_ready_focus_entry_says():
    refused = why_not("do", "Delete them") or ""
    for entry in (c for c in READY if c.focus):
        assert entry.plain[0].lower() + entry.plain[1:] in refused
    for entry in (c for c in READY if not c.focus):
        assert entry.plain[0].lower() + entry.plain[1:] not in refused


def test_a_refusal_says_yet_for_what_is_planned_and_not_for_what_the_registry_will_not_do():
    assert (why_not("do", "Post a message in Teams") or "").startswith(
        "I can't post a message in Teams yet."
    )
    for wont in ("Email the list to the team", "Delete every closed ticket"):
        said = why_not("do", wont) or ""
        assert said.startswith("I can't") and " yet." not in said.split(". I can only")[0]
    assert {c.id for c in CAPABILITIES if c.state == "unsupported"} == set(UNSUPPORTED_WORDS)


def test_teams_also_gets_outcomes_and_requests_for_the_team_so_post_is_not_approval_only():
    why = BY_ID["teams.post"].why or ""
    assert "approval requests only" not in why
    assert "outcome" in why and "team" in why
