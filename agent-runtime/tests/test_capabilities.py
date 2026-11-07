from collections import Counter

from fastapi.testclient import TestClient

from agent_runtime.abilities import (
    ABILITIES,
    ABILITY_OF,
    CAPABILITIES,
    EXAMPLES,
    VULNERABILITIES_PLANNED,
    why_not,
)
from agent_runtime.api import Settings, create_app
from agent_runtime.contract import CapabilityList
from agent_runtime.tools import TOOLS

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
    assert [c.id for c in READY if c.id not in ABILITY_OF] == ["teams.ask"]


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


def test_every_example_needs_only_ready_capabilities():
    for example in EXAMPLES:
        for needed in example.needs:
            assert BY_ID[needed].state == "ready", (example.text, needed)


def test_the_day_one_examples_are_one_of_each_kind():
    assert sorted(e.kind for e in EXAMPLES) == ["automate", "learn", "monitor"]


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
