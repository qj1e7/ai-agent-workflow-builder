from datetime import UTC, datetime

from platform_api.orchestration.decisions_http import DecisionsView, PastDecisionView
from platform_api.shared import RunId, UseCaseId, UserId
from platform_api.wire import WireModel

BOB = UserId("bob")
ALICE = UserId("alice")

DECLINED = PastDecisionView(
    run_id=RunId("run_01JBC"),
    use_case_id=UseCaseId("uc_01JBW"),
    use_case_name="Keep our software up to date",
    verdict="decline",
    reason="Wrong version",
    at=datetime(2026, 11, 13, 1, 10, tzinfo=UTC),
    run_state="rejected",
    written=0,
    tickets=True,
    connector="jira",
    approved_before=[],
    declined_by=BOB,
)
APPROVED = PastDecisionView(
    run_id=RunId("run_01JB8"),
    use_case_id=UseCaseId("uc_01JB8"),
    use_case_name="Morning new-ticket check",
    verdict="approve",
    reason=None,
    at=datetime(2026, 10, 26, 0, 0, tzinfo=UTC),
    run_state="succeeded",
    written=1,
    tickets=True,
    connector="jira",
    approved_before=[],
    declined_by=None,
)
FIRST_YES = PastDecisionView(
    run_id=RunId("run_01JBD"),
    use_case_id=UseCaseId("uc_01JBS"),
    use_case_name="Weekly closed-ticket summary",
    verdict="approve",
    reason=None,
    at=datetime(2026, 10, 16, 8, 0, tzinfo=UTC),
    run_state="rejected",
    written=0,
    tickets=True,
    connector="jira",
    approved_before=[BOB],
    declined_by=ALICE,
)


def decisions_fixtures() -> dict[str, WireModel]:
    return {
        "approvals/decisions.bob.json": DecisionsView(
            decisions=[DECLINED, APPROVED, FIRST_YES], total=3
        ),
        "approvals/decisions.none.json": DecisionsView(decisions=[], total=0),
    }
