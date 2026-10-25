import logging
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from agent_runtime.card_runner import CardRunner, agent_ref, one_line
from agent_runtime.contract import (
    AgentAddressee,
    AgentFailedData,
    AgentJoinedData,
    AgentMessageData,
    AgentRef,
    CardsInputs,
    CardToRun,
    CarryForward,
    ReleaseCheckInputs,
    TaskError,
    TaskFailed,
    TaskFinished,
    TaskOutput,
    TaskRequest,
    TaskResult,
    WatchlistInputs,
)
from agent_runtime.events import Draft, EventLog
from agent_runtime.release_checker import CHECKER, ReleaseChecker
from agent_runtime.release_source import tag_list
from agent_runtime.summary import ChatFor

log = logging.getLogger(__name__)

MAX_NAMES = 10
ROOM_LEAD = AgentRef(id="room_lead", display="Room lead")
TO_CHECKER = AgentAddressee(id=CHECKER.id, display=CHECKER.display)
UNEXPECTED_AGENT = TaskError(
    type="AgentError",
    message="An agent stopped because of an unexpected error",
    retryable=False,
)
UNEXPECTED = TaskError(
    type="AgentError",
    message="The Release checker stopped because of an unexpected error",
    retryable=False,
)


@dataclass(frozen=True)
class Staffing:
    joined_summary: str
    reason: str
    ask_summary: str
    ask_text: str


@dataclass(frozen=True)
class Reply:
    summary: str
    text: str


class RoomLead(Protocol):
    def staff(self, request: TaskRequest) -> Staffing: ...

    def staff_agent(self, agent: CardToRun, earlier: int, total: int) -> Staffing: ...

    def reply(self, output: TaskOutput) -> Reply: ...


class FixedRoomLead:
    def staff(self, request: TaskRequest) -> Staffing:
        match request.inputs:
            case ReleaseCheckInputs():
                return self._staff_release_check(
                    request.inputs, request.carry_forward.last_known_tag
                )
            case WatchlistInputs():
                return self._staff_watchlist(request.inputs)
            case CardsInputs():
                raise ValueError("a card task is staffed one agent at a time")

    def staff_agent(self, agent: CardToRun, earlier: int, total: int) -> Staffing:
        name = agent.card.name
        values = "; ".join(f"{key}: {value}" for key, value in agent.values.items())
        text = (
            f"Please run your plan with these inputs. {values}."
            if values
            else "Please run your plan."
        )
        if earlier:
            text += " The reports of the agents before you are in the room."
        return Staffing(
            joined_summary=f"Room lead brought in {name}."
            if total == 1
            else f"Room lead brought in {name} ({earlier + 1} of {total}).",
            reason=agent.card.purpose,
            ask_summary=f"Room lead asked {name} to do its part of the task.",
            ask_text=text,
        )

    def _staff_release_check(self, inputs: ReleaseCheckInputs, last: str | None) -> Staffing:
        joined = f"Room lead brought in {CHECKER.display} to read the GitHub releases."
        reason = "The task asks about releases of a GitHub repo."
        if last is None:
            return Staffing(
                joined_summary=joined,
                reason=reason,
                ask_summary="Room lead asked Release checker for a starting point.",
                ask_text=f"Please check {inputs.repo} for its latest release. There is no last "
                "known tag yet.",
            )
        return Staffing(
            joined_summary=joined,
            reason=reason,
            ask_summary=f"Room lead asked Release checker to look for releases newer than {last}.",
            ask_text=f"Please check {inputs.repo} for releases newer than {last}.",
        )

    def _staff_watchlist(self, inputs: WatchlistInputs) -> Staffing:
        names = [item.name for item in inputs.software]
        count = len(names)
        shown = names if count <= MAX_NAMES else [*names[:MAX_NAMES], f"{count - MAX_NAMES} more"]
        return Staffing(
            joined_summary=f"Room lead brought in {CHECKER.display} to read the sources of "
            f"{count} watched software.",
            reason="The task asks about releases of several watched software.",
            ask_summary=f"Room lead asked Release checker to check {count} watched software "
            "for new releases.",
            ask_text=f"Please check these for new releases: {tag_list(shown)}.",
        )

    def reply(self, output: TaskOutput) -> Reply:
        tickets = len(output.proposed)
        if tickets > 1:
            return Reply(
                summary=f"Room lead agreed and will propose {tickets} tickets for approval.",
                text=f"Agreed. I'll draft {tickets} tickets for an Approver to check together.",
            )
        if tickets:
            return Reply(
                summary="Room lead agreed and will propose the ticket for approval.",
                text="Agreed. I'll draft one ticket for an Approver to check.",
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
            summary=staffing.joined_summary,
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
        outcome = _check(request, checker, events)
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


def _check(
    request: TaskRequest, checker: ReleaseChecker, events: EventLog
) -> TaskOutput | TaskError:
    match request.inputs:
        case ReleaseCheckInputs():
            return checker.check(request.inputs, request.carry_forward.last_known_tag, events.add)
        case WatchlistInputs():
            return checker.check_watchlist(request.inputs, events.add)
        case CardsInputs():
            raise ValueError("a card task runs through run_cards")


def run_cards(
    request: TaskRequest,
    inputs: CardsInputs,
    lead: RoomLead,
    runner: CardRunner,
    chat_for: ChatFor,
    today: date,
    events: EventLog,
) -> TaskResult:
    """Brings in each agent in turn. An agent sees the reports of the ones before it."""
    task = runner.start(request, chat_for, today)
    reports: list[str] = []
    ref = ROOM_LEAD
    total = len(inputs.agents)
    for position, agent in enumerate(inputs.agents):
        ref = agent_ref(agent)
        staffing = lead.staff_agent(agent, position, total)
        events.add(
            Draft(
                agent=ROOM_LEAD,
                summary=staffing.joined_summary,
                data=AgentJoinedData(agent=ref, reason=staffing.reason),
            )
        )
        events.add(
            Draft(
                agent=ROOM_LEAD,
                summary=staffing.ask_summary,
                data=AgentMessageData(
                    speaker=ROOM_LEAD,
                    addressee=AgentAddressee(id=ref.id, display=ref.display),
                    text=staffing.ask_text,
                ),
            )
        )
        try:
            outcome = task.run_agent(agent, reports, events.add)
        except Exception:
            log.exception("agent %s crashed on task %s", ref.id, request.task_id)
            events.add(
                Draft(
                    agent=ref,
                    summary=f"{ref.display} failed: an unexpected error stopped it.",
                    data=AgentFailedData(
                        step=None,
                        error_type=UNEXPECTED_AGENT.type,
                        message=UNEXPECTED_AGENT.message,
                        retryable=False,
                    ),
                )
            )
            return TaskFailed(task_id=request.task_id, error=UNEXPECTED_AGENT, events=events.events)
        if isinstance(outcome, TaskError):
            return TaskFailed(task_id=request.task_id, error=outcome, events=events.events)
        reports.append(outcome.text)
    output = TaskOutput(
        summary=one_line(reports[-1]) if reports[-1] else f"{ref.display} finished.",
        new_tags=[],
        proposed=task.proposed,
        carry_forward=CarryForward(),
    )
    reply = lead.reply(output)
    events.add(
        Draft(
            agent=ROOM_LEAD,
            summary=reply.summary,
            data=AgentMessageData(
                speaker=ROOM_LEAD,
                addressee=AgentAddressee(id=ref.id, display=ref.display),
                text=reply.text,
            ),
        )
    )
    return TaskFinished(task_id=request.task_id, output=output, events=events.events)
