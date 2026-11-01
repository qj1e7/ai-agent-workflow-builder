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


AGENT_REFUSED = Advice(
    explanation="The agent was refused by the service it reads from, so retrying would "
    "get the same answer.",
    likely_cause="The use case names a repository that does not exist or that the token "
    "cannot read, or the task input was not valid.",
    suggested_action="ask_maintainer",
    suggestion="Check the repository name and the token in the use case, fix them, "
    "then start a new run.",
)


WRITE_REFUSED = Advice(
    explanation="The other system refused the approved write, so retrying would get the same "
    "answer.",
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
        return AGENT_REFUSED
    if failure.reason == "WriteFailed" and not failure.retryable:
        return WRITE_REFUSED
    return ADVICE[failure.reason]
