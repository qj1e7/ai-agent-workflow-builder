"""A drafted workflow's one-time check is a Needs you row for the Approvers who can say yes, and
the chat counts it as Home does (ADR 0053, item 3)."""

from datetime import UTC, datetime

from platform_api.builder.drafted_workflows import CHANGED
from platform_api.builder.home import SetUpApprovalItem
from platform_api.builder.planner_facts import needs_you_fact
from platform_api.contracts.home_stories import DAY_ONE

CHECK = SetUpApprovalItem(
    approval_id="apr_01JDRAFTRELEASE",
    drafted_id="dw_01JDRAFTRELEASE",
    name="Release check",
    sent_by_name="Carol",
    sent_at=datetime(2026, 11, 17, 1, 3, tzinfo=UTC),
    link="/setup-approvals/apr_01JDRAFTRELEASE",
)


def test_the_chat_counts_a_one_time_check_as_home_does():
    quiet = needs_you_fact(DAY_ONE)
    fact = needs_you_fact(DAY_ONE.model_copy(update={"setup_approvals": [CHECK]}))
    assert fact.setups == 1
    assert fact.total == quiet.total + 1
    parts = fact.model_dump(exclude={"total"})
    assert sum(parts.values()) == fact.total, f"every part of the total is named: {parts}"


def test_a_version_changed_after_the_check_names_the_button_beside_it():
    assert CHANGED == "Changed since it was approved. Press Turn on to ask for the check again."
