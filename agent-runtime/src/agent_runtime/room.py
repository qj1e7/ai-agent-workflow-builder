import logging
from dataclasses import dataclass
from typing import Protocol

from agent_runtime.contract import (
    AgentAddressee,
    AgentFailedData,
    AgentJoinedData,
    AgentMessageData,
    AgentRef,
    TaskError,
    TaskFailed,
    TaskFinished,
    TaskOutput,
    TaskRequest,
    TaskResult,
)
from agent_runtime.events import Draft, EventLog
from agent_runtime.release_checker import CHECKER, ReleaseChecker
from agent_runtime.tags import family_of

log = logging.getLogger(__name__)

ROOM_LEAD = AgentRef(id="room_lead", display="Room lead")
TO_CHECKER = AgentAddressee(id=CHECKER.id, display=CHECKER.display)
UNEXPECTED = TaskError(
    type="AgentError",
    message="The Release checker stopped because of an unexpected error",
    retryable=False,
)


@dataclass(frozen=True)
class Staffing:
    reason: str
    ask_summary: str
    ask_text: str


@dataclass(frozen=True)
class Reply:
    summary: str
    text: str


class RoomLead(Protocol):
    def staff(self, request: TaskRequest) -> Staffing: ...

    def reply(self, output: TaskOutput) -> Reply: ...


class FixedRoomLead:
    def staff(self, request: TaskRequest) -> Staffing:
        repo, last = request.inputs.repo, request.carry_forward.last_known_tag
        if last is None:
            return Staffing(
                reason="The task asks about releases of a GitHub repo.",
                ask_summary="Room lead asked Release checker for a starting point.",
                ask_text=f"Please check {repo} for its latest release. There is no last known tag "
                "yet.",
            )
        family = family_of(last)
        kind = "plain version" if family == "" else f"{family} tag"
        return Staffing(
            reason="The task asks about releases of a GitHub repo.",
            ask_summary=f"Room lead asked Release checker to look for releases newer than {last}.",
            ask_text=f"Please check {repo} for releases newer than {last} that match the "
            f"{kind} pattern.",
        )

    def reply(self, output: TaskOutput) -> Reply:
        if output.proposed:
            return Reply(
                summary="Room lead agreed and will propose the ticket for approval.",
                text="Agreed. I will propose the ticket. The platform asks an Approver before "
                "anything is written.",
            )
        return Reply(
            summary="Room lead noted that there is nothing to propose.",
            text="Understood. There is nothing to propose, so no approval is needed.",
        )


def run_task(
    request: TaskRequest, lead: RoomLead, checker: ReleaseChecker, events: EventLog
) -> TaskResult:
    staffing = lead.staff(request)
    events.add(
        Draft(
            agent=ROOM_LEAD,
            summary=f"Room lead brought in {CHECKER.display} to read the GitHub releases.",
            data=AgentJoinedData(agent=CHECKER, reason=staffing.reason),
        )
    )
    events.add(
        Draft(
            agent=ROOM_LEAD,
            summary=staffing.ask_summary,
            data=AgentMessageData(speaker=ROOM_LEAD, addressee=TO_CHECKER, text=staffing.ask_text),
        )
    )
    try:
        outcome = checker.check(request.inputs, request.carry_forward.last_known_tag, events.add)
    except Exception:
        log.exception("release checker crashed on task %s", request.task_id)
        events.add(
            Draft(
                agent=CHECKER,
                summary="Release checker failed: an unexpected error stopped it.",
                data=AgentFailedData(
                    step=None,
                    error_type=UNEXPECTED.type,
                    message=UNEXPECTED.message,
                    retryable=False,
                ),
            )
        )
        return TaskFailed(task_id=request.task_id, error=UNEXPECTED, events=events.events)
    if isinstance(outcome, TaskError):
        return TaskFailed(task_id=request.task_id, error=outcome, events=events.events)
    reply = lead.reply(outcome)
    events.add(
        Draft(
            agent=ROOM_LEAD,
            summary=reply.summary,
            data=AgentMessageData(speaker=ROOM_LEAD, addressee=TO_CHECKER, text=reply.text),
        )
    )
    return TaskFinished(task_id=request.task_id, output=outcome, events=events.events)
