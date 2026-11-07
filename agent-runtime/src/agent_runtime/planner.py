import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Final, Protocol

from agent_runtime.abilities import (
    RELEASE_ROOTS,
    VULNERABILITY_ROOTS,
    vulnerability_phrase,
    why_not,
)
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
    RowKind,
    TaskError,
    TaskFailed,
    TaskFinished,
    TaskOutput,
    TaskRequest,
    TaskResult,
    UnderstoodRow,
    WatchlistInputs,
)
from agent_runtime.events import Draft, EventLog
from agent_runtime.release_source import tag_list
from agent_runtime.summary import ChatFor
from agent_runtime.version_checker import CHECKER, VersionChecker
from agent_runtime.watchlist import NothingChecked

log = logging.getLogger(__name__)

MAX_NAMES = 10
PLANNER = AgentRef(id="planner", display="Planner")
TO_CHECKER = AgentAddressee(id=CHECKER.id, display=CHECKER.display)
UNEXPECTED_AGENT = TaskError(
    type="AgentError",
    message="An agent stopped because of an unexpected error",
    retryable=False,
)
UNEXPECTED = TaskError(
    type="AgentError",
    message="The Version checker stopped because of an unexpected error",
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


class Planner(Protocol):
    def staff(self, request: TaskRequest) -> Staffing: ...

    def staff_agent(self, agent: CardToRun, earlier: int, total: int) -> Staffing: ...

    def reply(self, output: TaskOutput) -> Reply: ...


class FixedPlanner:
    def staff(self, request: TaskRequest) -> Staffing:
        match request.inputs:
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
            joined_summary=f"Planner brought in {name}."
            if total == 1
            else f"Planner brought in {name} ({earlier + 1} of {total}).",
            reason=agent.card.purpose,
            ask_summary=f"Planner asked {name} to do its part of the task.",
            ask_text=text,
        )

    def _staff_watchlist(self, inputs: WatchlistInputs) -> Staffing:
        names = [item.name for item in inputs.software]
        count = len(names)
        if count == 1:
            return Staffing(
                joined_summary=f"Planner brought in {CHECKER.display} to read the source of "
                f"{names[0]}.",
                reason=f"The task asks about new releases of {names[0]}.",
                ask_summary=f"Planner asked {CHECKER.display} to check {names[0]} for new "
                "releases.",
                ask_text=f"Please check {names[0]} for new releases.",
            )
        shown = names if count <= MAX_NAMES else [*names[:MAX_NAMES], f"{count - MAX_NAMES} more"]
        return Staffing(
            joined_summary=f"Planner brought in {CHECKER.display} to read the sources of "
            f"{count} watched software.",
            reason="The task asks about releases of several watched software.",
            ask_summary=f"Planner asked {CHECKER.display} to check {count} watched software "
            "for new releases.",
            ask_text=f"Please check these for new releases: {tag_list(shown)}.",
        )

    def reply(self, output: TaskOutput) -> Reply:
        tickets = len(output.proposed)
        if tickets > 1:
            return Reply(
                summary=f"Planner agreed and will propose {tickets} tickets for approval.",
                text=f"Agreed. I'll draft {tickets} tickets for an Approver to check together.",
            )
        if tickets:
            return Reply(
                summary="Planner agreed and will propose the ticket for approval.",
                text="Agreed. I'll draft one ticket for an Approver to check.",
            )
        return Reply(
            summary="Planner noted that there is nothing to propose.",
            text="Understood. There is nothing to propose, so no approval is needed.",
        )


def run_task(
    request: TaskRequest, planner: Planner, checker: VersionChecker, events: EventLog
) -> TaskResult:
    staffing = planner.staff(request)
    events.add(
        Draft(
            agent=PLANNER,
            summary=staffing.joined_summary,
            data=AgentJoinedData(agent=CHECKER, reason=staffing.reason),
        )
    )
    events.add(
        Draft(
            agent=PLANNER,
            summary=staffing.ask_summary,
            data=AgentMessageData(speaker=PLANNER, addressee=TO_CHECKER, text=staffing.ask_text),
        )
    )
    try:
        outcome = _check(request, checker, events)
    except Exception:
        log.exception("version checker crashed on task %s", request.task_id)
        events.add(
            Draft(
                agent=CHECKER,
                summary="Version checker failed: an unexpected error stopped it.",
                data=AgentFailedData(
                    step=None,
                    error_type=UNEXPECTED.type,
                    message=UNEXPECTED.message,
                    retryable=False,
                ),
            )
        )
        return TaskFailed(task_id=request.task_id, error=UNEXPECTED, events=events.events)
    if isinstance(outcome, NothingChecked):
        return TaskFailed(
            task_id=request.task_id,
            error=outcome.error,
            events=events.events,
            findings=outcome.findings,
        )
    reply = planner.reply(outcome)
    events.add(
        Draft(
            agent=PLANNER,
            summary=reply.summary,
            data=AgentMessageData(speaker=PLANNER, addressee=TO_CHECKER, text=reply.text),
        )
    )
    return TaskFinished(task_id=request.task_id, output=outcome, events=events.events)


def _check(
    request: TaskRequest, checker: VersionChecker, events: EventLog
) -> TaskOutput | NothingChecked:
    match request.inputs:
        case WatchlistInputs():
            return checker.check_watchlist(request.inputs, events.add)
        case CardsInputs():
            raise ValueError("a card task runs through run_cards")


def run_cards(
    request: TaskRequest,
    inputs: CardsInputs,
    planner: Planner,
    runner: CardRunner,
    chat_for: ChatFor,
    today: date,
    events: EventLog,
) -> TaskResult:
    """Brings in each agent in turn. An agent sees the reports of the ones before it."""
    task = runner.start(request, chat_for, today)
    reports: list[str] = []
    ref = PLANNER
    total = len(inputs.agents)
    for position, agent in enumerate(inputs.agents):
        ref = agent_ref(agent)
        staffing = planner.staff_agent(agent, position, total)
        events.add(
            Draft(
                agent=PLANNER,
                summary=staffing.joined_summary,
                data=AgentJoinedData(agent=ref, reason=staffing.reason),
            )
        )
        events.add(
            Draft(
                agent=PLANNER,
                summary=staffing.ask_summary,
                data=AgentMessageData(
                    speaker=PLANNER,
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
    reply = planner.reply(output)
    events.add(
        Draft(
            agent=PLANNER,
            summary=reply.summary,
            data=AgentMessageData(
                speaker=PLANNER,
                addressee=AgentAddressee(id=ref.id, display=ref.display),
                text=reply.text,
            ),
        )
    )
    return TaskFinished(task_id=request.task_id, output=output, events=events.events)


ORDER: Final[tuple[RowKind, ...]] = ("schedule", "look_for", "do", "where")
MAX_ROWS: Final = 8
TEXT_LIMIT: Final = 200
NOTE_LIMIT: Final = 300
WORD_LIMIT: Final = 80
WATCHLIST_ROOTS: Final = RELEASE_ROOTS | VULNERABILITY_ROOTS
NOT_SAID: Final = "I couldn't tell from your words."
READ_IN: Final = "I read this into your words. Please check it."
CANT_YET: Final = "I can't do this yet."
CONTROL, FORMAT, SURROGATE = "Cc", "Cf", "Cs"
INVISIBLE: Final = frozenset(
    "\u034f\u115f\u1160\u17b4\u17b5\u180b\u180c\u180d\u180f\u2800\u3164\uffa0"
    + "".join(map(chr, range(0xFE00, 0xFE10)))
    + "".join(map(chr, range(0xE0100, 0xE01F0)))
)
QUOTES: Final = "\"'“”‘’"


def visible_words(text: str | None) -> str:
    hidden = (CONTROL, FORMAT, SURROGATE)
    kept = (
        c
        for c in text or ""
        if c.isspace() or (unicodedata.category(c) not in hidden and c not in INVISIBLE)
    )
    return " ".join("".join(kept).split())


def plain(text: str | None, limit: int) -> str:
    flat = visible_words(text)
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def missing_row(kind: RowKind, note: str = NOT_SAID) -> UnderstoodRow:
    return UnderstoodRow(kind=kind, text="", state="missing", note=note)


def why_no_tool(kind: RowKind, text: str) -> str | None:
    """Why the platform can't do this part, or None when it can. Hidden characters do not count."""
    return why_not(kind, visible_words(text))


def _cant_do_first(row: UnderstoodRow) -> bool:
    return row.state != "cant_do"


def arrange(rows: list[UnderstoodRow]) -> list[UnderstoodRow]:
    groups = [[row for row in rows if row.kind == kind] or [missing_row(kind)] for kind in ORDER]
    groups[0] = groups[0][:1]
    firsts = [group[0] for group in groups]
    extras = sorted((row for group in groups for row in group[1:]), key=_cant_do_first)
    kept = firsts + extras[: MAX_ROWS - len(firsts)]
    return sorted(kept, key=lambda row: ORDER.index(row.kind))


def said_in(word: str, text: str) -> bool:
    """Whole words, with a number allowed inside a token such as "3pm"."""
    edge = r"\d" if word.isdigit() else r"\w"
    return re.search(rf"(?<!{edge}){re.escape(word)}(?!{edge})", text, re.IGNORECASE) is not None


def whole_word_of(task: str, said: str | None) -> str | None:
    wanted = visible_words(said).strip(QUOTES)
    if not wanted or len(wanted) > WORD_LIMIT:
        return None
    found = re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", task, re.IGNORECASE)
    return None if found is None else found.group(0)


def task_form_of(task: str, said: str | None) -> str | None:
    wanted = visible_words(said).strip(QUOTES).casefold()
    if vulnerability_phrase(wanted) is not None:
        return vulnerability_phrase(task)
    task_words = re.findall(r"\w+", task)
    for said_word in re.findall(r"\w+", wanted):
        root = WATCHLIST_ROOTS.get(said_word)
        forms = [w for w in task_words if WATCHLIST_ROOTS.get(w.casefold()) == root]
        if root is not None and forms:
            return next((w for w in forms if w.casefold() == said_word), forms[0])
    return None
