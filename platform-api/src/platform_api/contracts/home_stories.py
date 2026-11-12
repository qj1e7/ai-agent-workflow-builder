"""What Home answers to bob, who may decide a run alice started, to alice, whose run waits and whose
other run stopped, and to someone on a team with no workflows yet."""

from datetime import UTC, datetime

from platform_api.builder.home import (
    AddressItem,
    ApprovalItem,
    ChangeLine,
    ComingUp,
    ConfirmationItem,
    ConnectionItem,
    DeclinedItem,
    DraftItem,
    HomeOut,
    StoppedItem,
    WaitingItem,
)
from platform_api.builder.team_requests import FollowingUpItem, ReplyView
from platform_api.builder.templates import SOFTWARE_WATCHLIST
from platform_api.contracts.stories import (
    ALICE,
    BOB,
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
from platform_api.shared import RunId
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
        declined=[],
        declined_total=0,
        waiting_on_others=[],
        waiting_on_others_total=0,
        drafts=[],
        following_up=[],
        following_up_total=0,
        replied=[],
        coming_up=COMING_UP,
        workflows=1,
        addresses=[],
        connections=[],
    )


SUPPORT_REPORT = FollowingUpItem(
    request_id="trq_01JD5RP",
    kind="support",
    about={"run_id": FAILURE.run_id},
    note="It stopped again.",
    asked_at=datetime(2026, 11, 4, 7, 2, tzinfo=UTC),
    status="answered",
    latest_reply=ReplyView(
        replied_by="bob",
        replied_by_name="Bob",
        replied_at=datetime(2026, 11, 4, 8, 30, tzinfo=UTC),
        text="Looking into it.",
        status="answered",
    ),
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
        declined=[],
        declined_total=0,
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
        following_up=[SUPPORT_REPORT],
        following_up_total=1,
        replied=[SUPPORT_REPORT],
        coming_up=COMING_UP,
        workflows=1,
        addresses=[
            AddressItem(
                software_id="sw_01JC2A3B4C5D6E7F8G9H0J1K2M",
                name="FastAPI",
                repo="tiangolo/fastapi",
                moved_to="fastapi/fastapi",
                not_found=False,
                checked_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
            ),
            AddressItem(
                software_id="sw_01JC2A3B4C5D6E7F8G9H0J1K2N",
                name="LangServe",
                repo="langchain-ai/langserve",
                moved_to=None,
                not_found=True,
                checked_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
            ),
        ],
        connections=[
            ConnectionItem(
                id="jira",
                name="Jira",
                state="not_answering",
                problem="Jira is not answering.",
                fix="Nothing to change yet. Check again in a few minutes.",
                checked_at=datetime(2026, 11, 9, 2, 10, tzinfo=UTC),
                last_ok_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
                expires_at=None,
            ),
            ConnectionItem(
                id="github",
                name="GitHub",
                state="working",
                problem="The key runs out soon.",
                fix="Ask whoever set up GitHub for a new key before this one runs out.",
                checked_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
                last_ok_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
                expires_at=datetime(2026, 11, 18, 9, 0, tzinfo=UTC),
            ),
        ],
    )


DAY_ONE = HomeOut(
    approvals=[],
    approvals_total=0,
    confirmations=[],
    stopped=[],
    stopped_total=0,
    declined=[],
    declined_total=0,
    waiting_on_others=[],
    waiting_on_others_total=0,
    drafts=[],
    following_up=[],
    following_up_total=0,
    replied=[],
    coming_up=None,
    workflows=0,
    addresses=[],
    connections=[],
)


# Bob declined Alice's test run, and said why.
DECLINED_TEST = DAY_ONE.model_copy(
    update={
        "declined": [
            DeclinedItem(
                run_id=RunId("run_01JD7TS"),
                use_case_id="uc_01JD7TS",
                use_case_name="Weekly closed-ticket summary",
                started_at=datetime(2026, 11, 10, 1, 2, tzinfo=UTC),
                declined_at=datetime(2026, 11, 10, 1, 10, tzinfo=UTC),
                declined_by=BOB,
                declined_by_name="Bob",
                decline_reason="Something in it is wrong",
            )
        ],
        "declined_total": 1,
        "workflows": 1,
    }
)


def home_fixtures() -> dict[str, WireModel]:
    return {
        "builder/home.bob.json": home_for_bob(),
        "builder/home.alice.json": home_for_alice(failure_events()),
        "builder/home.alice.declined-test.json": DECLINED_TEST,
        "builder/home.day-one.json": DAY_ONE,
    }
