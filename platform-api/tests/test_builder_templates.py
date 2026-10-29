from platform_api.builder import TEMPLATES
from platform_api.builder.templates import suggest_template


def test_only_the_watchlist_and_agent_cards_templates_remain_and_neither_is_offered():
    assert [t.key for t in TEMPLATES.values()] == ["software_watchlist", "agent_cards"]
    assert all(not t.offered for t in TEMPLATES.values())


def test_every_template_runs_the_one_n8n_workflow():
    assert {t.workflow for t in TEMPLATES.values()} == {"run"}


def test_the_watchlist_template_is_listed_but_never_suggested():
    watchlist = TEMPLATES["software_watchlist"]
    assert [p.name for p in watchlist.params] == ["ticket_project"]
    assert [b.kind for b in watchlist.blocks] == ["agent", "approval", "write_action"]
    found, terms = suggest_template("watch the software watchlist for releases and open a ticket")
    assert (found, terms) == (None, [])


def test_the_ticket_project_comes_from_the_params_into_the_binding():
    binding = TEMPLATES["software_watchlist"].bindings_for({"ticket_project": "OPS"})[
        "create_ticket"
    ]
    assert (binding.connector, binding.operation) == ("jira", "create_ticket")
    assert dict(binding.target) == {"project": "OPS"}
