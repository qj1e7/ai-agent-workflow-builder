"""What step 7's safety review found (M2, S1, S2), through the routes with the drafter, n8n and
Teams faked: a block renamed in n8n keeps its settings, a placeholder no setting holds is never
sent, what n8n gave that didn't count is said on the card, and a channel question with nothing
to pick says why it waits."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from platform_api.builder.drafted_settings import ANY_APPROVER, APPROVERS, NO_CHANNEL
from platform_api.orchestration import KnownOptions, WorkflowPlan
from tests.test_drafted_layout import SLACK_KEY, release_check
from tests.test_drafted_read_back import renamed, with_slack
from tests.test_drafted_workflows import Lab, drafted, lab

pytestmark = pytest.mark.anyio

__all__ = ["lab"]


class FactsWithSlack:
    """The team's options with the platform's Slack key, so a Slack post isn't flagged."""

    async def known(self, adding: Mapping[str, Sequence[str]]) -> KnownOptions:
        repos = frozenset({"fastapi/fastapi", *adding.get("github_releases", ())})
        return KnownOptions(
            frozenset(),
            {"github_releases": repos},
            {"jira.create_ticket": frozenset({"MOCK"})},
            {},
            {SLACK_KEY: "slackApi"},
        )


async def opened(lab: Lab) -> dict[str, Any]:
    """Alice's release check with a Slack post whose channel is still needed, open in n8n."""
    lab.drafted._facts = FactsWithSlack()  # type: ignore[attr-defined]
    lab.drafter.answers = [drafted(with_slack(None))]
    view = await lab.start()
    view = await lab.answer(view, APPROVERS, choice=ANY_APPROVER)
    assert (view["needed"], view["flags"], view["question"]) == (1, 0, "channel_1"), view
    r = await lab.call(
        "alice",
        "POST",
        f"/api/v1/drafted-workflows/{view['drafted_id']}/n8n",
        {"revision": view["revision"]},
    )
    assert r.status_code == 200, r.text
    return view


async def done(lab: Lab, drafted_id: str) -> Any:
    return await lab.call("alice", "POST", f"/api/v1/drafted-workflows/{drafted_id}/n8n/done")


async def test_a_block_renamed_in_n8n_keeps_its_needed_channel_so_it_can_t_be_sent(lab: Lab):
    view = await opened(lab)
    renamed("Tell support", "Post to Slack")(lab.n8n.held["wf1"].document)

    r = await done(lab, view["drafted_id"])

    assert r.status_code == 200, r.text
    after = r.json()
    [channel] = [s for s in after["settings"] if s["kind"] == "channel"]
    assert (channel["id"], channel["mark"]) == ("channel_1", "needed")
    assert (after["needed"], after["question"], after["can_send"]) == (1, "channel_1", False)
    sent = await lab.send(after["drafted_id"], after["revision"])
    assert sent.status_code == 409


async def test_a_placeholder_nothing_fills_is_refused_on_read_back_and_never_kept(lab: Lab):
    view = await opened(lab)
    for node in lab.n8n.held["wf1"].document["nodes"]:
        if node["name"] == "Tell support":
            node["parameters"]["channelId"]["value"] = "<<somewhere_else>>"

    r = await done(lab, view["drafted_id"])

    assert r.status_code == 409
    assert "nothing fills" in r.json()["detail"]
    assert (await lab.read(view["drafted_id"]))["revision"] == view["revision"]


async def test_a_placeholder_that_reaches_a_revision_counts_as_needed_and_is_never_sent(lab: Lab):
    """Belt and braces: whatever made it, a placeholder no setting holds can't be sent."""
    plan = release_check().model_dump()
    plan["blocks"][2]["parameters"]["subject"] = "<<orphan>>"
    lab.drafter.answers = [drafted(WorkflowPlan.model_validate(plan))]
    view = await lab.start()

    assert view["needed"] >= 1 and view["can_send"] is False
    assert "“Propose a ticket”" in view["why_not_send"]
    assert (await lab.send(view["drafted_id"], view["revision"])).status_code == 409


async def test_a_channel_typed_in_n8n_that_doesn_t_count_is_said_on_the_card(lab: Lab):
    view = await opened(lab)
    for node in lab.n8n.held["wf1"].document["nodes"]:
        if node["name"] == "Tell support":
            node["parameters"]["channelId"]["value"] = "#random"

    r = await done(lab, view["drafted_id"])

    assert r.status_code == 200, r.text
    after = r.json()
    assert after["notes"] == [
        "You typed “#random” in n8n for “channel 1”, but that isn't a Slack channel the "
        "platform's key can see. So it's asked again."
    ]
    assert after["question"] == "channel_1"
    answered = await lab.answer(after, "channel_1", choice="#support")
    assert answered["notes"] == [], "the words belong to the read-back's own revision"


async def test_a_channel_question_with_nothing_to_pick_says_why_it_waits(lab: Lab):
    lab.drafted._channels.seen = []  # type: ignore[attr-defined]
    lab.drafted._facts = FactsWithSlack()  # type: ignore[attr-defined]
    lab.drafter.answers = [drafted(with_slack(None))]
    view = await lab.start()

    assert (view["question"], view["can_send"]) == (None, False)
    assert view["why_not_send"] == NO_CHANNEL


async def test_a_channel_list_slack_gave_before_it_stopped_answering_says_how_old_it_is(lab: Lab):
    since = datetime(2026, 11, 17, 2, 5, tzinfo=UTC)
    lab.drafted._channels.stale_since = since  # type: ignore[attr-defined]
    lab.drafted._facts = FactsWithSlack()  # type: ignore[attr-defined]
    lab.drafter.answers = [drafted(with_slack(None))]
    view = await lab.start()

    channel = next(s for s in view["settings"] if s["id"] == "channel_1")
    assert channel["question"] == (
        "Which Slack channel should it post in? Slack didn't answer just now, so these are the "
        "channels it listed at 10:05."
    )
    assert [c["value"] for c in channel["choices"]] == ["#support", "#eng-housekeeping"]


async def test_a_filled_setting_on_a_block_renamed_in_n8n_stays_with_where_it_came_from(lab: Lab):
    view = await opened(lab)
    document = lab.n8n.held["wf1"].document
    sent = {n["name"]: n["id"] for n in lab.n8n.sent[0]["nodes"]}
    kept = {n["name"]: n["id"] for n in document["nodes"]}
    assert kept == sent, "n8n keeps the ids the platform sent, as real n8n does"
    renamed("Propose a ticket", "Propose it")(document)

    r = await done(lab, view["drafted_id"])

    assert r.status_code == 200, r.text
    project = next(s for s in r.json()["settings"] if s["id"] == "jira_project")
    assert (project["value"], project["mark"], project["said"]) == (
        "MOCK",
        "filled",
        "From your words",
    )
    assert "Propose it" in [b["name"] for b in r.json()["blocks"]]
