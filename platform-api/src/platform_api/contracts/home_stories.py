"""What Home answers to bob, who may decide a run alice started, to alice, whose run waits and whose
other run stopped, and to someone on a team with no workflows yet."""

from datetime import UTC, datetime

from platform_api.builder.home import (
    ApprovalItem,
    ChangeLine,
    ComingUp,
    ConfirmationItem,
    DraftItem,
    HomeOut,
    StoppedItem,
    WaitingItem,
)
from platform_api.builder.templates import SOFTWARE_WATCHLIST
from platform_api.contracts.stories import (
    ALICE,
    FAILURE,
    SUCCESS,
    TICKET_TITLE,
    USE_CASE_ID,
    USE_CASE_NAME,
    Timeline,
    failure_events,
)
from platform_api.monitoring.troubleshooter import explain
from platform_api.orchestration import ConfirmationKind
from platform_api.wire import WireModel

CONFIRMATIONS_ASKED = datetime(2026, 11, 9, 3, 41, tzinfo=UTC)
COMING_UP = ComingUp(
    use_case_id=USE_CASE_ID,
    name=USE_CASE_NAME,
    template=SOFTWARE_WATCHLIST.key,
    next_run_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
    time_zone="Asia/Singapore",
    more=0,
)


def home_for_bob() -> HomeOut:
    return HomeOut(
        approvals=[
            ApprovalItem(
                run_id=SUCCESS.run_id,
                approval_id=SUCCESS.approval_id,
                use_case_id=USE_CASE_ID,
                use_case_name=USE_CASE_NAME,
                started_by=ALICE,
                started_by_name="Alice",
                trigger="person",
                started_at=SUCCESS.t0,
                step=0,
                steps=1,
                step_label="Team approver",
                changes=1,
                first_changes=[
                    ChangeLine(connector="jira", operation="create_ticket", title=TICKET_TITLE)
                ],
            )
        ],
        approvals_total=1,
        confirmations=[
            ConfirmationItem(
                confirmation_id="cfm_01JD4VE",
                kind=ConfirmationKind.APPROVER,
                summary="Make Dave an Approver",
                about_name="Dave",
                asked_by_name="Alice",
                asked_at=CONFIRMATIONS_ASKED,
            ),
            ConfirmationItem(
                confirmation_id="cfm_01JADDR",
                kind=ConfirmationKind.MODEL_ADDRESS,
                summary="Use ncs-llm-small at ai-gateway.ncs.example",
                about_name=None,
                asked_by_name="Alice",
                asked_at=CONFIRMATIONS_ASKED,
            ),
        ],
        stopped=[],
        stopped_total=0,
        waiting_on_others=[],
        waiting_on_others_total=0,
        drafts=[],
        coming_up=COMING_UP,
        workflows=1,
    )


def home_for_alice(failure: Timeline) -> HomeOut:
    failed = failure.last
    assert failed.kind == "run_failed"
    return HomeOut(
        approvals=[],
        approvals_total=0,
        confirmations=[],
        stopped=[
            StoppedItem(
                run_id=FAILURE.run_id,
                use_case_id=USE_CASE_ID,
                use_case_name=USE_CASE_NAME,
                started_at=FAILURE.t0,
                stopped_at=failed.ts,
                reason=failed.data.reason,
                retryable=failed.data.retryable,
                advice=explain(failed.data.reason),
            )
        ],
        stopped_total=1,
        waiting_on_others=[
            WaitingItem(
                run_id=SUCCESS.run_id,
                use_case_id=USE_CASE_ID,
                use_case_name=USE_CASE_NAME,
                trigger="person",
                started_at=SUCCESS.t0,
                step=0,
                steps=1,
                because="started",
            )
        ],
        waiting_on_others_total=1,
        drafts=[
            DraftItem(
                draft_id="drf-7f3a2c",
                name="Nudge stale tickets",
                step=2,
                saved_at=datetime(2026, 11, 4, 6, 24, tzinfo=UTC),
            )
        ],
        coming_up=COMING_UP,
        workflows=1,
    )


DAY_ONE = HomeOut(
    approvals=[],
    approvals_total=0,
    confirmations=[],
    stopped=[],
    stopped_total=0,
    waiting_on_others=[],
    waiting_on_others_total=0,
    drafts=[],
    coming_up=None,
    workflows=0,
)


def home_fixtures() -> dict[str, WireModel]:
    return {
        "builder/home.bob.json": home_for_bob(),
        "builder/home.alice.json": home_for_alice(failure_events()),
        "builder/home.day-one.json": DAY_ONE,
    }
