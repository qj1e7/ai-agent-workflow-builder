"""Two runs that n8n carries and that wait for a yes in n8n (ENGINE-PLAN 2.3): one nobody answers,
so it expires, and one Bob approves after n8n lost the execution."""

from datetime import UTC, datetime

from platform_api.contracts.stories import (
    ACTION_LINE,
    BOB,
    CHANNEL,
    DIGEST,
    PLATFORM,
    USE_CASE_ID,
    USE_CASE_NAME,
    USER_ALICE,
    USER_BOB,
    WORKFLOW,
    Story,
    Timeline,
    announced,
    open_step,
)
from platform_api.monitoring.events import (
    ApprovalAnnounced,
    ApprovalDecided,
    ApprovalDecidedData,
    ApprovalRequested,
    ApprovalRequestedData,
    ExecutionLinked,
    ExecutionLinkedData,
    RunCreated,
    RunCreatedData,
    RunExpired,
    RunExpiredData,
    RunLost,
    RunLostData,
    WriteActionProposed,
    WriteActionProposedData,
)
from platform_api.shared import RunId, UserId
from platform_api.wire import WireModel

EXPIRED = Story("expired", RunId("run_01JBE"), datetime(2026, 11, 3, 1, 0, tzinfo=UTC), "51")
LOST = Story("lost", RunId("run_01JBL"), datetime(2026, 11, 4, 1, 0, tzinfo=UTC), "52")
TWO_WORKING_DAYS = 2 * 24 * 3600.0
GONE = "the waiting execution was resumed by something else, or has finished"


def asked_in_n8n(tl: Timeline) -> None:
    tl.add(
        RunCreated,
        0.0,
        USER_ALICE,
        f"Alice's schedule started a check of the {USE_CASE_NAME}.",
        RunCreatedData(
            use_case_id=USE_CASE_ID,
            use_case_version=1,
            started_by=UserId("alice"),
            trigger="schedule",
        ),
    )
    tl.add(
        ExecutionLinked,
        0.004,
        WORKFLOW,
        f"n8n execution {tl.story.work_execution} is carrying the run (trigger).",
        ExecutionLinkedData(execution_id=tl.story.work_execution, mode="trigger"),
    )
    tl.add(
        WriteActionProposed,
        6.31,
        WORKFLOW,
        f"The workflow proposed 1 change: {ACTION_LINE.line}.",
        WriteActionProposedData(
            proposal_id=tl.story.proposal_id, digest=DIGEST, actions=[ACTION_LINE]
        ),
    )
    tl.add(
        ApprovalRequested,
        6.312,
        PLATFORM,
        "Approval requested. Waiting for the Team approver.",
        ApprovalRequestedData(
            approval_id=tl.story.approval_id, steps=[open_step()], link=tl.story.approval_link
        ),
    )
    tl.add(
        ApprovalAnnounced,
        8.7,
        PLATFORM,
        f"The approval request was posted to the Teams channel {CHANNEL}.",
        announced(tl, 8.7),
    )


def expired_events() -> Timeline:
    tl = Timeline(EXPIRED)
    asked_in_n8n(tl)
    tl.add(
        RunExpired,
        TWO_WORKING_DAYS + 3.2,
        PLATFORM,
        "No answer. Nothing was written.",
        RunExpiredData(approval_id=EXPIRED.approval_id),
    )
    return tl


def lost_events() -> Timeline:
    tl = Timeline(LOST)
    asked_in_n8n(tl)
    tl.add(
        ApprovalDecided,
        412.5,
        USER_BOB,
        "Bob approved the request (Team approver).",
        ApprovalDecidedData(
            approval_id=LOST.approval_id, step=0, verdict="approve", by=BOB, digest=DIGEST
        ),
    )
    tl.add(
        RunLost,
        413.1,
        PLATFORM,
        f"Approved, but n8n lost the run, because {GONE}. Nothing was written.",
        RunLostData(approval_id=LOST.approval_id, why=GONE),
    )
    return tl


def n8n_wait_fixtures() -> dict[str, WireModel | list[WireModel]]:
    return {
        "runs/expired.json": list(expired_events().events),
        "runs/lost.json": list(lost_events().events),
    }
