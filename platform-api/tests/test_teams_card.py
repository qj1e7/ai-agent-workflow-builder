import json
from dataclasses import fields, replace
from typing import Any

import httpx
import pytest
from jsonschema import Draft6Validator

from platform_api.orchestration.dispatch import (
    ApprovalNotice,
    ApprovalOutcome,
    AskedStep,
    DispatchFailure,
    MessageRef,
)
from platform_api.orchestration.teams import (
    CARD_VERSION,
    OPEN_IN,
    TEAMS_MESSAGE_LIMIT,
    AdaptiveCard,
    TeamsWorkflowsWebhook,
    approval_card,
    outcome_card,
    webhook_message,
    with_outcome,
)
from platform_api.shared import ApprovalId, RunId
from tests.support import FIXTURES

pytestmark = pytest.mark.anyio

SCHEMA_FILE = FIXTURES.parent / "schemas" / "adaptive-card-1.5.json"
OPEN_URL = "https://portal.example.test/approvals/apr_1"
HOSTILE = "**Approve now** [here](https://evil.example) <at>Bob</at> _ok_\n\n# Safe"

NOTICE = ApprovalNotice(
    run_id=RunId("run_1"),
    approval_id=ApprovalId("apr_1"),
    use_case_name="Software watchlist",
    actions=('create a Jira ticket in MOCK titled "Upgrade LangGraph to 1.2.16"',),
    link="/approvals/apr_1",
    open_url=OPEN_URL,
    summary="LangGraph has a new release: 1.2.16.",
    lines=("Create Jira ticket in MOCK: Upgrade LangGraph to 1.2.16",),
    digest="sha256:abc",
    steps=(AskedStep("Approver"),),
    not_deciding=("Alice",),
)
APPROVED = ApprovalOutcome("approved", ("Bob",), "Software watchlist", OPEN_URL)
DECLINED = ApprovalOutcome("declined", ("Bob",), "Software watchlist", OPEN_URL)


def wire(card: AdaptiveCard) -> dict[str, Any]:
    return card.as_json()


def every_card() -> dict[str, AdaptiveCard]:
    many = replace(
        NOTICE,
        lines=tuple(f"Create Jira ticket in MOCK: {HOSTILE} {n}" for n in range(40)),
        summary=HOSTILE + "x" * 2000,
        steps=(AskedStep("Manager", ("Dana", "Eve")), AskedStep("Security", ("Frank",))),
        not_deciding=("Alice", "Carol"),
    )
    old = ApprovalNotice(
        run_id=RunId("run_old"),
        approval_id=ApprovalId("apr_old"),
        use_case_name="LangGraph releases",
        actions=("create a Jira ticket",),
        link="/approvals/apr_old",
        open_url="http://localhost:8080/approvals/apr_old",
    )
    return {
        "waiting": approval_card(NOTICE),
        "many and hostile": approval_card(many),
        "queued before the card": approval_card(old),
        "approved": with_outcome(approval_card(NOTICE), APPROVED),
        "declined": with_outcome(approval_card(NOTICE), DECLINED),
        "approved after a decline": with_outcome(
            with_outcome(approval_card(NOTICE), DECLINED), APPROVED
        ),
        "outcome on its own": outcome_card(APPROVED),
    }


def element_types(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        entries: dict[str, object] = node  # pyright: ignore[reportUnknownVariableType]
        kind = entries.get("type")
        if isinstance(kind, str):
            found.append(kind)
        for value in entries.values():
            found.extend(element_types(value))
    elif isinstance(node, list):
        for value in node:  # pyright: ignore[reportUnknownVariableType]
            found.extend(element_types(value))
    return found


def texts(node: object, kind: str, key: str) -> list[str]:
    """Every `key` string inside elements of `kind`."""
    found: list[str] = []
    if isinstance(node, dict):
        entries: dict[str, object] = node  # pyright: ignore[reportUnknownVariableType]
        value = entries.get(key)
        if entries.get("type") == kind and isinstance(value, str):
            found.append(value)
        for child in entries.values():
            found.extend(texts(child, kind, key))
    elif isinstance(node, list):
        for child in node:  # pyright: ignore[reportUnknownVariableType]
            found.extend(texts(child, kind, key))
    return found


@pytest.mark.skipif(not SCHEMA_FILE.exists(), reason="contracts/ is not in the test image")
@pytest.mark.parametrize("name", sorted(every_card()))
def test_every_card_matches_the_adaptive_card_schema(name: str):
    schema = json.loads(SCHEMA_FILE.read_text())
    errors = sorted(Draft6Validator(schema).iter_errors(wire(every_card()[name])), key=str)
    assert [e.message for e in errors] == []


@pytest.mark.skipif(not SCHEMA_FILE.exists(), reason="contracts/ is not in the test image")
@pytest.mark.parametrize("name", sorted(every_card()))
def test_every_element_is_one_teams_renders_at_the_cards_version(name: str):
    definitions = json.loads(SCHEMA_FILE.read_text())["definitions"]
    card = wire(every_card()[name])
    assert card["version"] == CARD_VERSION
    for kind in element_types(card):
        needs = definitions[kind].get("version", "1.0")
        assert tuple(map(int, needs.split("."))) <= tuple(map(int, CARD_VERSION.split("."))), kind


@pytest.mark.parametrize("name", sorted(every_card()))
def test_the_one_button_opens_the_approval_page_at_an_absolute_address(name: str):
    card = wire(every_card()[name])
    assert card["actions"] == [
        {"type": "Action.OpenUrl", "title": OPEN_IN, "url": card["actions"][0]["url"]}
    ]
    assert card["actions"][0]["url"].startswith(("https://", "http://localhost:"))
    assert card["actions"][0]["url"].endswith(("/approvals/apr_1", "/approvals/apr_old"))


def test_a_notice_queued_before_the_card_lists_its_phrases_and_any_approver():
    runs = texts(wire(every_card()["queued before the card"]), "TextRun", "text")
    assert "• Create a Jira ticket" in runs
    assert "Any Approver who is not part of this run" in runs


def test_text_we_did_not_write_goes_only_in_text_runs_which_show_no_markdown():
    card = wire(every_card()["many and hostile"])
    ours = texts(card, "TextBlock", "text") + [card["fallbackText"]]
    assert not any("Approve now" in text or "evil" in text for text in ours)
    runs = texts(card, "TextRun", "text")
    assert any(run.startswith("**Approve now** [here](https://evil.example)") for run in runs)
    assert all("\n" not in run for run in runs)


def test_the_card_says_what_would_be_written_what_the_agents_found_and_who_decides():
    card = wire(approval_card(NOTICE))
    runs = " | ".join(texts(card, "TextRun", "text"))
    headings = texts(card, "TextBlock", "text")
    assert [run["text"] for run in card["body"][0]["inlines"]] == [
        "Software watchlist",
        " wants to make 1 change. Nothing is written until an Approver says yes.",
    ]
    assert "• Create Jira ticket in MOCK: Upgrade LangGraph to 1.2.16" in runs
    assert headings == ["What the agents found", "Who can decide"]
    assert "LangGraph has a new release: 1.2.16." in runs
    assert "Any Approver" in runs
    assert "Alice can’t decide, because this run is their own work." in runs


def test_several_steps_name_who_decides_each_one_in_order():
    steps = (AskedStep("Manager", ("Dana", "Eve")), AskedStep("Security", ("Frank",)))
    notice = replace(NOTICE, steps=steps, not_deciding=())
    card = wire(approval_card(notice))
    runs = texts(card, "TextRun", "text")
    assert "Who can decide, one after the other" in texts(card, "TextBlock", "text")
    assert "1. Manager: Dana or Eve" in runs and "2. Security: Frank" in runs
    assert not any("own work" in run for run in runs)


def test_a_large_proposal_stays_under_the_teams_limit_and_says_how_many_more():
    card = every_card()["many and hostile"]
    body = json.dumps(webhook_message(card)).encode()
    assert len(body) < TEAMS_MESSAGE_LIMIT
    runs = texts(wire(card), "TextRun", "text")
    assert sum(run.startswith("• ") for run in runs) == 10
    assert "And 30 more. Open the request to see them all." in runs
    assert max(len(run) for run in runs) <= 300


def test_an_outcome_goes_on_top_and_replaces_an_earlier_one():
    approved = wire(every_card()["approved after a decline"])
    first = approved["body"][0]
    assert first == {
        "type": "RichTextBlock",
        "id": "outcome",
        "inlines": [
            {"type": "TextRun", "text": "Approved by Bob", "weight": "bolder", "color": "good"}
        ],
    }
    assert sum(1 for e in approved["body"] if e.get("id") == "outcome") == 1
    declined = wire(with_outcome(approval_card(NOTICE), DECLINED))["body"][0]
    assert declined["inlines"][0]["text"] == "Declined by Bob"
    assert declined["inlines"][0]["color"] == "attention"
    assert approved["body"][1:] == wire(approval_card(NOTICE))["body"]


def test_no_field_of_the_notice_can_carry_a_secret_into_a_card():
    # A card is posted where many people read it. The notice holds only what the card shows,
    # and the approval id, so a token, a key or the webhook address cannot reach it.
    assert {f.name for f in fields(ApprovalNotice)} == {
        "run_id",
        "approval_id",
        "use_case_name",
        "actions",
        "link",
        "open_url",
        "summary",
        "lines",
        "digest",
        "steps",
        "not_deciding",
    }
    text = json.dumps([wire(card) for card in every_card().values()]).lower()
    assert not any(word in text for word in ("token", "secret", "sig=", "password", "key="))


WEBHOOK = "https://prod.example.logic.azure.com/workflows/abc/triggers/manual/run?sig=s3cr3t"


def recording(status: int, seen: list[httpx.Request]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def test_the_webhook_posts_the_card_as_one_adaptive_card_attachment():
    seen: list[httpx.Request] = []
    teams = TeamsWorkflowsWebhook(WEBHOOK, "CODESparks Ops", recording(202, seen))
    ref = await teams.announce(NOTICE)
    await teams.update(ref, APPROVED)
    assert ref == MessageRef("CODESparks Ops", "apr_1")
    assert teams.name == "CODESparks Ops"
    posted = [json.loads(r.content) for r in seen]
    assert [str(r.url) for r in seen] == [WEBHOOK, WEBHOOK]
    assert posted[0] == {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": wire(approval_card(NOTICE)),
            }
        ],
    }
    assert posted[1]["attachments"][0]["content"] == wire(outcome_card(APPROVED))
    assert "s3cr3t" not in json.dumps(posted)


@pytest.mark.parametrize("status", [400, 429, 500])
async def test_a_refused_webhook_post_is_a_dispatch_failure_that_never_shows_the_address(
    status: int,
):
    teams = TeamsWorkflowsWebhook(WEBHOOK, "CODESparks Ops", recording(status, []))
    with pytest.raises(DispatchFailure) as raised:
        await teams.announce(NOTICE)
    assert str(raised.value) == f"Teams answered {status}"


async def test_an_unreachable_webhook_is_a_dispatch_failure_that_never_shows_the_address():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    teams = TeamsWorkflowsWebhook(WEBHOOK, "CODESparks Ops", client)
    with pytest.raises(DispatchFailure) as raised:
        await teams.announce(NOTICE)
    assert str(raised.value) == "Teams did not answer (ConnectError)"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


@pytest.mark.skipif(not SCHEMA_FILE.exists(), reason="contracts/ is not in the test image")
@pytest.mark.parametrize("name", ["teams-messages.json", "teams-messages.decided.json"])
def test_every_card_in_the_contract_fixtures_matches_the_adaptive_card_schema(name: str):
    validator = Draft6Validator(json.loads(SCHEMA_FILE.read_text()))
    messages = json.loads((FIXTURES / "stubs" / name).read_text())["messages"]
    assert messages and all(m["card"] is not None for m in messages)
    for message in messages:
        assert [e.message for e in validator.iter_errors(message["card"])] == []
        assert message["card"] == AdaptiveCard.model_validate(message["card"]).as_json()
