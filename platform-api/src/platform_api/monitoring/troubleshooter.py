import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol

from pydantic import Field

from platform_api.monitoring.events import RunFailedData
from platform_api.monitoring.source_stops import CAUSES, Delay, SourceStop, headline, read_stop
from platform_api.shared import JIRA_SITE_CHANGED, NO_START_BLOCK, WRITE_STOP_ADVICE, RunId
from platform_api.wire import FailureReason, WireModel

type SuggestedAction = Literal[
    "retry", "check_workflow_engine", "reload_workflow", "ask_maintainer", "start_again"
]


class Advice(WireModel):
    explanation: str
    likely_cause: str
    suggested_action: SuggestedAction
    suggestion: str


ADVICE: Mapping[FailureReason, Advice] = {
    "AgentError": Advice(
        explanation="An agent could not finish its work.",
        likely_cause="A service the agent reads from was unavailable or answered with an error.",
        suggested_action="retry",
        suggestion="Retry the run. If it fails again, check whether that service is up.",
    ),
    "WorkflowNodeError": Advice(
        explanation="A step in the workflow engine failed.",
        likely_cause="A workflow node could not reach the platform, or the workflow was "
        "changed in a way that breaks it.",
        suggested_action="retry",
        suggestion="Retry the run. If it fails on the same step, ask a maintainer to "
        "look at the workflow engine's execution log.",
    ),
    "TimedOut": Advice(
        explanation="The run waited too long for the workflow engine and gave up.",
        likely_cause="The workflow engine was down or stuck, or it could not reach the platform.",
        suggested_action="retry",
        suggestion="Retry the run. If it times out again, check that the workflow engine "
        "is running.",
    ),
    "DispatchFailed": Advice(
        explanation="The platform could not hand the run to the workflow engine.",
        likely_cause="The workflow engine was unreachable for several minutes.",
        suggested_action="check_workflow_engine",
        suggestion="Check that the workflow engine is running and reachable, then retry the run.",
    ),
    "WriteFailed": Advice(
        explanation="The approved write action could not be completed.",
        likely_cause="The target system, such as Jira, rejected the write or was unavailable.",
        suggested_action="retry",
        suggestion="Retry the run. It carries on after the approval, so nobody has to "
        "approve again.",
    ),
    "SafetyDenied": Advice(
        explanation="The safety checker blocked the write action.",
        likely_cause="The approval no longer matches the proposal, or the action is not "
        "a registered connector operation.",
        suggested_action="ask_maintainer",
        suggestion=f"{WRITE_STOP_ADVICE} If this happens again, ask a maintainer to check "
        "the approval records.",
    ),
    "UnboundIntent": Advice(
        explanation="The agents proposed an action this workflow cannot carry out.",
        likely_cause="The template has no connector binding for that kind of action.",
        suggested_action="ask_maintainer",
        suggestion="Ask a maintainer to add the binding to the template, then start a new run.",
    ),
    "OutOfOrderStep": Advice(
        explanation="The workflow called a step out of order, so the run stopped.",
        likely_cause="The workflow was edited in the workflow engine's editor.",
        suggested_action="reload_workflow",
        suggestion="Ask a maintainer to reload the workflow from git, then start a new "
        "run. Retrying would run the same edited workflow.",
    ),
    "StoppedByUpdate": Advice(
        explanation="The platform was updated while this run was on the old shared workflow, "
        "which the update removed, so the run could not carry on.",
        likely_cause="The run started before the update.",
        suggested_action="start_again",
        suggestion="Start the workflow again. It runs on its own n8n workflow now.",
    ),
}


AGENTS_STOPPED = Advice(
    explanation="The agents couldn't finish this step.",
    likely_cause="The run's activity shows the error they stopped with.",
    suggested_action="ask_maintainer",
    suggestion="Ask a maintainer to look at the error in the run's activity and fix what it "
    "names, then start a new run.",
)


LOOK_AT_THE_AGENT = (
    "Ask a maintainer to look at what the agent did in the run's activity, then start a new run."
)


# Agent error types whose meaning is certain. UpstreamRejected is not one: a watchlist check also
# gives it when it finds no plain version, which nothing refused.
RATE_LIMITED = Advice(
    explanation="An agent could not finish its work.",
    likely_cause="A service the agent reads from is limiting how often it can be asked.",
    suggested_action="retry",
    suggestion="Wait a few minutes, then retry the run. Retrying at once is likely to hit the "
    "same limit.",
)
RATE_LIMIT_WORDS = "limiting how often"


KNOWN_AGENT_STOPS: Mapping[str, Advice] = {
    "ModelNeeded": Advice(
        explanation="No AI model is connected, so the agents couldn't start.",
        likely_cause="Agents need an AI model, and none is connected in Settings.",
        suggested_action="ask_maintainer",
        suggestion="Ask an Operator to connect an AI model in Settings, then start a new run.",
    ),
    "JiraNotConnected": Advice(
        explanation="Jira is not connected, so an agent couldn't read it.",
        likely_cause="An agent needs Jira, and none is connected in Settings.",
        suggested_action="ask_maintainer",
        suggestion="Ask an Operator to connect Jira in Settings, then start a new run.",
    ),
    "JiraRefused": Advice(
        explanation="Jira refused an agent's request, so it couldn't read Jira.",
        likely_cause="The Jira connection in Settings may be wrong, or it may lack the right "
        "to read that project. Trying again is refused the same way.",
        suggested_action="ask_maintainer",
        suggestion="Ask an Operator to check the Jira connection in Settings, then start a "
        "new run.",
    ),
    "AgentTooSlow": Advice(
        explanation="An agent ran out of time before it finished.",
        likely_cause="An agent's task has a time limit, and this one went over it.",
        suggested_action="ask_maintainer",
        suggestion=LOOK_AT_THE_AGENT,
    ),
    "AgentTooLong": Advice(
        explanation="An agent used all its steps without finishing.",
        likely_cause="An agent's task has a limit on its steps, and this one reached it.",
        suggested_action="ask_maintainer",
        suggestion=LOOK_AT_THE_AGENT,
    ),
}


WRITE_REFUSED = Advice(
    explanation="The approved write was refused.",
    likely_cause="Either Jira refused the write and made nothing, or the platform found a "
    "ticket it can't prove it made. The failure text says which one happened.",
    suggested_action="ask_maintainer",
    suggestion=f"Read the failure text. {WRITE_STOP_ADVICE} If Jira refused the write, ask a "
    "maintainer to fix the Jira settings or the project.",
)


SITE_CHANGED = Advice(
    explanation=JIRA_SITE_CHANGED,
    likely_cause="The platform now uses another Jira than the one the Approvers approved, so "
    "the safety checker stopped the write.",
    suggested_action="ask_maintainer",
    suggestion=f"{WRITE_STOP_ADVICE} Ask a maintainer to check Jira's settings, so a new run "
    "proposes the ticket for the Jira the team means to use.",
)


STOPPED_WHILE_WRITING = Advice(
    explanation=ADVICE["StoppedByUpdate"].explanation,
    likely_cause="The run started before the update and was making its changes.",
    suggested_action="ask_maintainer",
    suggestion=WRITE_STOP_ADVICE,
)


MISSING_START = Advice(
    explanation="The workflow has no Start from the Portal block, so the Portal couldn't start it.",
    likely_cause="It was made or changed in n8n without that block.",
    suggested_action="ask_maintainer",
    suggestion="Ask someone with n8n access to add Start from the Portal to it in n8n, then "
    "start a new run.",
)


def inside_the_workflow(failure: RunFailedData) -> bool:
    """Whether the stop's cause can be in the workflow itself (ADR 0055, section 1): a block that
    failed in n8n, and not an outage of a source it read. It is an allow-list, so any other stop
    gets no fix: a key, n8n, the platform's own code, a write that failed, a timeout, an outage."""
    return (
        failure.reason == "WorkflowNodeError"
        and _source_stop(failure) is None
        and not failure.retryable
    )


def explain(reason: FailureReason) -> Advice:
    return ADVICE[reason]


def _source_stop(failure: RunFailedData) -> SourceStop | None:
    if failure.reason != "WorkflowNodeError" or not failure.retryable:
        return None
    return read_stop(failure.message)


def source_advice(stop: SourceStop) -> Advice:
    """What a block that got no usable answer from its source tells, from the stop's own facts."""
    source = stop.source or "the source"
    return Advice(
        explanation=headline(stop),
        likely_cause=CAUSES[stop.delay],
        suggested_action="retry",
        suggestion="Retry the run in a few minutes. If it stops here again, check that "
        f"{source} is up and that n8n can reach it.",
    )


def explain_failure(failure: RunFailedData) -> Advice:
    stop = _source_stop(failure)
    if stop is not None:
        return source_advice(stop)
    if failure.reason == "AgentError" and not failure.retryable:
        # The work leg's failure message starts with the agent's error type, as "ModelNeeded: ...".
        return KNOWN_AGENT_STOPS.get(failure.message.partition(": ")[0], AGENTS_STOPPED)
    if failure.reason == "AgentError" and failure.retryable and RATE_LIMIT_WORDS in failure.message:
        return RATE_LIMITED
    if failure.reason == "WriteFailed" and not failure.retryable:
        return WRITE_REFUSED
    if failure.reason == "SafetyDenied" and failure.message == JIRA_SITE_CHANGED:
        return SITE_CHANGED
    if failure.reason == "StoppedByUpdate" and failure.stage == "acting":
        return STOPPED_WHILE_WRITING
    if (
        failure.reason == "DispatchFailed"
        and not failure.retryable
        and NO_START_BLOCK in failure.message
    ):
        return MISSING_START
    return ADVICE[failure.reason]


type CauseSystem = Literal[
    "github",
    "gitlab",
    "bitbucket",
    "jira",
    "confluence",
    "teams",
    "slack",
    "entra",
    "azure",
    "aws",
    "docker",
    "pypi",
    "npm",
    "servicenow",
    "outlook",
    "zendesk",
    "gmail",
]
type FailureKind = Literal[
    "not_found",
    "refused",
    "no_answer",
    "wrong_value",
    "changed_field",
    "permission",
    "limit",
    "unknown",
]

SYSTEM_NAMES: Final[Mapping[CauseSystem, str]] = {
    "github": "GitHub",
    "gitlab": "GitLab",
    "bitbucket": "Bitbucket",
    "jira": "Jira",
    "confluence": "Confluence",
    "teams": "Teams",
    "slack": "Slack",
    "entra": "Entra",
    "azure": "Azure",
    "aws": "AWS",
    "docker": "Docker",
    "pypi": "PyPI",
    "npm": "npm",
    "servicenow": "ServiceNow",
    "outlook": "Outlook",
    "zendesk": "Zendesk",
    "gmail": "Gmail",
}
CAUSE_WORDS: Final[Mapping[FailureKind, tuple[str, str]]] = {
    "not_found": ("{who} can't find {detail}", "{who} can't find what was asked for"),
    "refused": ("{who} refuses the request for {detail}", "{who} refuses the request"),
    "no_answer": ("{who} doesn't answer the request for {detail}", "{who} doesn't answer"),
    "wrong_value": (
        "{who} sends a value for {detail} that {block} can't use",
        "{who} sends a value {block} can't use",
    ),
    "changed_field": (
        "the answer from {who} is missing the field {detail}",
        "the answer from {who} is missing a field",
    ),
    "permission": (
        "{who} doesn't give {block} access to {detail}",
        "{who} doesn't give {block} access",
    ),
    "limit": (
        "{who} is limiting requests for {detail}",
        "{who} is limiting how often it can be asked",
    ),
}
"""Why the failed part stopped, for each kind of failure but unknown, with a detail and without.
The cause only says what the run met, and the rule table beside it says what to do."""

SOURCE_KINDS: Final[Mapping[Delay, FailureKind]] = {
    "no_answer": "no_answer",
    "cut_off": "no_answer",
    "unreachable": "no_answer",
    "refused": "refused",
}
"""The one kind each of ADR 0056's source stops shows."""


def stop_kind(kind: FailureKind, message: str) -> FailureKind:
    """The model's kind, held to a source stop's own facts (ADR 0056). When the stop's words say
    how the source failed, a kind they don't show is shown as unknown."""
    stop = read_stop(message)
    if stop is None or kind == SOURCE_KINDS[stop.delay]:
        return kind
    return "unknown"


def cause_words(
    failed_part: Sequence[str],
    system: CauseSystem | None,
    kind: FailureKind,
    detail: str | None,
) -> str:
    """The cause people see, in one sentence code writes from the model's checked fields. No
    words of the model's are in it: a block's name and the detail are copied from the run."""
    *before, last = failed_part
    names = f"{', '.join(before)} and {last}" if before else last
    blocks = f"The {names} block{'s' if before else ''} stopped"
    if kind == "unknown":
        source = f" from {SYSTEM_NAMES[system]}" if system else ""
        about = f" about {detail}" if detail else ""
        return f"{blocks} on an error{source}{about}."
    with_detail, without = CAUSE_WORDS[kind]
    why = (with_detail if detail else without).format(
        who=SYSTEM_NAMES[system] if system else "a service",
        detail=detail,
        block="the blocks" if before else "the block",
    )
    return f"{blocks} because {why}."


class FoundCause(WireModel):
    """The AI model's cause and failed part (ADR 0055, section 10). The model only picked fields
    from the run's facts, code checked each one, and code wrote the cause from them, so no words
    of the model's are shown. Each block is in the version that ran and is where the run stopped.
    The rule table's answer stays beside it, unchanged."""

    cause: str = Field(
        description="Why the run stopped, in one sentence code wrote from the model's checked "
        "picks: the failed part, the system, the kind of failure and one name from the run."
    )
    failed_part: list[str] = Field(
        min_length=1, description="The blocks the cause is in, each one where the run stopped."
    )


@dataclass(frozen=True)
class AskedCause:
    """One stop, for the model to name its cause."""

    run_id: RunId
    seq: int
    """The run_failed event's sequence number, so a later stop of the same run is a new one."""
    failure: RunFailedData
    events: Sequence[str]
    """The run's activity, each event's plain summary, oldest first."""
    seconds: float
    """How long the finder has before the rule table answers alone."""


class CauseFinder(Protocol):
    """The troubleshooter's model version. None whenever it has no checked answer, and the rule
    table answers alone."""

    async def find(self, asked: AskedCause) -> FoundCause | None: ...


def asks_the_model(failure: RunFailedData) -> bool:
    """Whether the rule table knows no cause for this stop, so the model may name one: an agent's
    stop of a kind the table doesn't know, or a block that failed in n8n. Every other stop keeps
    the cause the table knows."""
    advice = explain_failure(failure)
    return advice is AGENTS_STOPPED or advice is ADVICE["WorkflowNodeError"]


class RetryAnswer(WireModel):
    possible: bool
    asks_again: bool
    """True only when a retry runs the work again, so any write waits for a new yes. A retry at
    the write step carries on from the approved write."""


class Answers(WireModel):
    what_happened: str
    """One sentence. The advice's likely cause and the failure text are the details behind it."""
    what_affected: str
    safe_to_retry: str
    retry: RetryAnswer
    next: Literal["retry", "report"]


NOTHING_WRITTEN = "Nothing. No ticket was written."
# The log holds a write's done event only once the whole write step succeeds, and Jira can make a
# ticket and lose its answer, so at the write step nobody can say from the log what was written.
MAYBE_WRITTEN = "The approved write may or may not have reached Jira."


def _wait_first(advice: Advice) -> str:
    if advice is RATE_LIMITED:
        return "Wait a few minutes first. Retrying at once is likely to hit the same limit. "
    if advice.suggested_action == "check_workflow_engine":
        return "Check that the workflow engine is running first. "
    return ""


def _safe_to_retry(failure: RunFailedData, retry: RetryAnswer) -> str:
    """The answer to "Safe to retry?". It starts with Yes or No, then says why."""
    if not retry.possible:
        return f"No. This kind of stop can't be retried. {explain_failure(failure).suggestion}"
    if not retry.asks_again:
        return (
            "Yes. A retry carries on from the write that was already approved, so nobody has to "
            "approve again. It checks the approval before it writes, and it finds a ticket an "
            "earlier try made instead of making a second one."
        )
    wait = _wait_first(explain_failure(failure))
    return f"Yes. {wait}Nothing was written, so a retry is safe."


RUNTIME_SOURCES: Final = ("GitHub", "Jira", "Confluence")
"""The sources the agent runtime reads for an agent, as its fixed sentences name them
(agent_runtime's github.py, jira.py, confluence.py and release_source.py)."""
DIDNT_ANSWER: Final = re.compile(
    rf"(?:^|: |\. )(?P<source>{'|'.join(RUNTIME_SOURCES)}) "
    r"(?:returned 5\d\d|could not be reached)\b"
)
"""The runtime's sentence when one of those sources gave no usable answer, every try, at the
start of the message or of one of its sentences."""


def what_happened(failure: RunFailedData, at: datetime | None = None) -> str:
    """One sentence: the source that didn't answer, with the time it stopped when that is known,
    or the advice's explanation. Every place that names a stop says this sentence. A place that
    shows the time beside it leaves `at` out."""
    found = DIDNT_ANSWER.search(failure.message)
    if failure.reason == "AgentError" and failure.retryable and found is not None:
        when = "" if at is None else f" at {at.hour}:{at.minute:02d}"
        return f"{found.group('source')} didn't answer{when}."
    return explain_failure(failure).explanation


def answers(failure: RunFailedData, at: datetime | None = None) -> Answers:
    """The three answers to a stop. `at` is when it stopped, in the team's time zone."""
    at_the_write = failure.stage == "acting"
    retry = RetryAnswer(
        possible=failure.retryable, asks_again=failure.retryable and not at_the_write
    )
    return Answers(
        what_happened=what_happened(failure, at),
        what_affected=MAYBE_WRITTEN if at_the_write else NOTHING_WRITTEN,
        safe_to_retry=_safe_to_retry(failure, retry),
        retry=retry,
        next="retry" if retry.possible else "report",
    )
