from collections.abc import Mapping
from typing import Literal

from platform_api.monitoring.events import RunFailedData
from platform_api.wire import FailureReason, WireModel

type SuggestedAction = Literal[
    "retry", "check_workflow_engine", "reload_workflow", "ask_maintainer"
]


class Advice(WireModel):
    explanation: str
    likely_cause: str
    suggested_action: SuggestedAction
    suggestion: str


ADVICE: Mapping[FailureReason, Advice] = {
    "AgentError": Advice(
        explanation="An agent could not finish its work.",
        likely_cause="A service the agent reads from, such as GitHub, was unavailable "
        "or answered with an error.",
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
        suggestion="Start a new run. If this happens again, ask a maintainer to check "
        "the approval records.",
    ),
    "UnboundIntent": Advice(
        explanation="The agents proposed an action this use case cannot carry out.",
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
KNOWN_AGENT_STOPS: Mapping[str, Advice] = {
    "ModelNeeded": Advice(
        explanation="No AI model is connected, so the agents couldn't start.",
        likely_cause="Agents need an AI model, and none is connected in Settings.",
        suggested_action="ask_maintainer",
        suggestion="Ask an Operator to connect an AI model in Settings, then start a new run.",
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
    likely_cause="Jira does not accept the ticket as it is: the project, the issue type or a "
    "required field is not what Jira expects, or the platform's Jira account may not write there.",
    suggested_action="ask_maintainer",
    suggestion="Read what Jira said in the run's failure, ask a maintainer to fix the Jira "
    "settings or the project, then start a new run.",
)


def explain(reason: FailureReason) -> Advice:
    return ADVICE[reason]


def explain_failure(failure: RunFailedData) -> Advice:
    if failure.reason == "AgentError" and not failure.retryable:
        # The work leg's failure message starts with the agent's error type, as "ModelNeeded: ...".
        return KNOWN_AGENT_STOPS.get(failure.message.partition(": ")[0], AGENTS_STOPPED)
    if failure.reason == "WriteFailed" and not failure.retryable:
        return WRITE_REFUSED
    return ADVICE[failure.reason]


class RetryAnswer(WireModel):
    possible: bool
    asks_again: bool
    """True only when a retry runs the work again, so any write waits for a new yes. A retry at
    the write step carries on from the approved write."""


class Answers(WireModel):
    what_happened: str
    what_affected: str
    can_fix: str
    retry: RetryAnswer
    next: Literal["retry", "report"]


NOTHING_WRITTEN = "Nothing was written."
# The log holds a write's done event only once the whole write step succeeds, and Jira can make a
# ticket and lose its answer, so at the write step nobody can say from the log what was written.
MAYBE_WRITTEN = "The approved write may or may not have reached Jira."


def _can_fix(retry: RetryAnswer) -> str:
    if not retry.possible:
        return "This kind of stop can't be retried."
    if retry.asks_again:
        return "Yes. A retry runs the work again, and any write still waits for a yes."
    return (
        "Yes. A retry carries on from the write that was already approved, so nobody has to "
        "approve again. It checks the approval before it writes, and it finds a ticket an "
        "earlier try made instead of making a second one."
    )


def answers(failure: RunFailedData) -> Answers:
    at_the_write = failure.stage == "acting"
    retry = RetryAnswer(
        possible=failure.retryable, asks_again=failure.retryable and not at_the_write
    )
    return Answers(
        what_happened=explain_failure(failure).explanation,
        what_affected=MAYBE_WRITTEN if at_the_write else NOTHING_WRITTEN,
        can_fix=_can_fix(retry),
        retry=retry,
        next="retry" if retry.possible else "report",
    )
