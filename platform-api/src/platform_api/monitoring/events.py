"""Activity event wire contract.

One envelope for every event the live activity view receives. The `kind` field
selects the shape of `data`, so a kind cannot carry another kind's data. These
are wire models only. Domain types stay as frozen dataclasses in their own
context.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from platform_api.monitoring.agent_events import (
    AgentFailedData,
    AgentJoinedData,
    AgentMessageData,
    AgentStepFinishedData,
    AgentStepStartedData,
)
from platform_api.shared import ApprovalId, ProposalId, RunId, UserId
from platform_api.wire import WireModel

type ActorKind = Literal["user", "platform", "workflow", "agent", "safety_checker"]
type Leg = Literal["work", "act"]
type StepName = Literal["run_agents", "ask_approval", "write_action"]
type StepOutcome = Literal[
    "proposed",
    "nothing_to_write",
    "approval_opened",
    "written",
    "failed",
    "superseded",
    "refused",
    "replayed",
]
type FailureReason = Literal[
    "AgentError",
    "WorkflowNodeError",
    "TimedOut",
    "DispatchFailed",
    "WriteFailed",
    "SafetyDenied",
    "UnboundIntent",
    "OutOfOrderStep",
]
type FailureStage = Literal["pending", "working", "proposed", "acting"]
type DeniedReason = Literal[
    "run_mismatch",
    "not_approved",
    "invalid_decisions",
    "digest_mismatch",
    "unregistered_action",
    "out_of_order",
]
type ApprovalStepStatus = Literal["waiting", "open", "approved", "declined"]
type WireVerdict = Literal["approve", "decline"]
type RunOutcome = Literal["written", "nothing_to_write"]


class Actor(WireModel):
    kind: ActorKind
    id: str
    display: str


class ApprovalStepView(WireModel):
    index: int
    label: str
    status: ApprovalStepStatus
    decided_by: UserId | None = None
    decided_at: datetime | None = None


class ActionLine(WireModel):
    connector: str
    operation: str
    line: str


class RunCreatedData(WireModel):
    use_case_id: str
    use_case_version: int
    started_by: UserId


class LegDispatchedData(WireModel):
    leg: Leg
    attempt: int


class StepStartedData(WireModel):
    step: StepName
    n8n_execution_id: str
    try_number: int


class StepFinishedData(WireModel):
    step: StepName
    n8n_execution_id: str
    try_number: int
    outcome: StepOutcome
    detail: str


class StepRetriedData(WireModel):
    step: StepName
    n8n_execution_id: str
    try_number: int


class WriteActionProposedData(WireModel):
    proposal_id: ProposalId
    digest: str
    actions: list[ActionLine]


class ApprovalRequestedData(WireModel):
    approval_id: ApprovalId
    steps: list[ApprovalStepView]
    link: str


class ApprovalAnnouncedData(WireModel):
    approval_id: ApprovalId
    channel: str
    link: str


class ApprovalAnnounceFailedData(WireModel):
    approval_id: ApprovalId
    channel: str
    message: str


class ApprovalDecidedData(WireModel):
    approval_id: ApprovalId
    step: int
    verdict: WireVerdict
    by: UserId


class WriteActionDeniedData(WireModel):
    reason: DeniedReason
    detail: str


class WriteActionDoneData(WireModel):
    connector: str
    operation: str
    external_reference: str
    approved_by: list[UserId]


class RunSucceededData(WireModel):
    outcome: RunOutcome


class RunRejectedData(WireModel):
    by: UserId
    step: int


class RunFailedData(WireModel):
    stage: FailureStage
    reason: FailureReason
    retryable: bool
    message: str


class RunRetriedData(WireModel):
    leg: Leg
    attempt: int


class _Envelope(WireModel):
    run_id: RunId
    seq: int = Field(ge=1)
    ts: datetime
    actor: Actor
    summary: str


class RunCreated(_Envelope):
    kind: Literal["run_created"] = "run_created"
    data: RunCreatedData


class LegDispatched(_Envelope):
    kind: Literal["leg_dispatched"] = "leg_dispatched"
    data: LegDispatchedData


class StepStarted(_Envelope):
    kind: Literal["step_started"] = "step_started"
    data: StepStartedData


class StepFinished(_Envelope):
    kind: Literal["step_finished"] = "step_finished"
    data: StepFinishedData


class StepRetried(_Envelope):
    kind: Literal["step_retried"] = "step_retried"
    data: StepRetriedData


class AgentJoined(_Envelope):
    kind: Literal["agent_joined"] = "agent_joined"
    data: AgentJoinedData


class AgentStepStarted(_Envelope):
    kind: Literal["agent_step_started"] = "agent_step_started"
    data: AgentStepStartedData


class AgentStepFinished(_Envelope):
    kind: Literal["agent_step_finished"] = "agent_step_finished"
    data: AgentStepFinishedData


class AgentFailed(_Envelope):
    kind: Literal["agent_failed"] = "agent_failed"
    data: AgentFailedData


class AgentMessage(_Envelope):
    kind: Literal["agent_message"] = "agent_message"
    data: AgentMessageData


class WriteActionProposed(_Envelope):
    kind: Literal["write_action_proposed"] = "write_action_proposed"
    data: WriteActionProposedData


class ApprovalRequested(_Envelope):
    kind: Literal["approval_requested"] = "approval_requested"
    data: ApprovalRequestedData


class ApprovalAnnounced(_Envelope):
    kind: Literal["approval_announced"] = "approval_announced"
    data: ApprovalAnnouncedData


class ApprovalAnnounceFailed(_Envelope):
    kind: Literal["approval_announce_failed"] = "approval_announce_failed"
    data: ApprovalAnnounceFailedData


class ApprovalDecided(_Envelope):
    kind: Literal["approval_decided"] = "approval_decided"
    data: ApprovalDecidedData


class WriteActionDenied(_Envelope):
    kind: Literal["write_action_denied"] = "write_action_denied"
    data: WriteActionDeniedData


class WriteActionDone(_Envelope):
    kind: Literal["write_action_done"] = "write_action_done"
    data: WriteActionDoneData


class RunSucceeded(_Envelope):
    kind: Literal["run_succeeded"] = "run_succeeded"
    data: RunSucceededData


class RunRejected(_Envelope):
    kind: Literal["run_rejected"] = "run_rejected"
    data: RunRejectedData


class RunFailed(_Envelope):
    kind: Literal["run_failed"] = "run_failed"
    data: RunFailedData


class RunRetried(_Envelope):
    kind: Literal["run_retried"] = "run_retried"
    data: RunRetriedData


type ActivityEvent = Annotated[
    RunCreated
    | LegDispatched
    | StepStarted
    | StepFinished
    | StepRetried
    | AgentJoined
    | AgentStepStarted
    | AgentStepFinished
    | AgentFailed
    | AgentMessage
    | WriteActionProposed
    | ApprovalRequested
    | ApprovalAnnounced
    | ApprovalAnnounceFailed
    | ApprovalDecided
    | WriteActionDenied
    | WriteActionDone
    | RunSucceeded
    | RunRejected
    | RunFailed
    | RunRetried,
    Field(discriminator="kind"),
]

activity_event_adapter: TypeAdapter[ActivityEvent] = TypeAdapter(ActivityEvent)
activity_events_adapter: TypeAdapter[list[ActivityEvent]] = TypeAdapter(list[ActivityEvent])
