from collections.abc import Iterable
from dataclasses import dataclass, field

from platform_api.orchestration.runs import Leg
from platform_api.orchestration.service import Orchestrator, RetryLater
from platform_api.orchestration.workflows import WorkflowDefinition
from platform_api.shared import N8nExecutionId, RunId


@dataclass(frozen=True)
class QueuedLeg:
    workflow: str
    leg: Leg
    run_id: RunId
    execution: N8nExecutionId


@dataclass
class Execution:
    id: N8nExecutionId
    workflow: str
    leg: Leg
    run_id: RunId
    steps: list[tuple[str, bool, str]] = field(default_factory=list)
    status: str = "running"


class FakeWorkflowEngine:
    def __init__(self, definitions: Iterable[WorkflowDefinition]) -> None:
        self._definitions = {d.name: d for d in definitions}
        self._orchestrator: Orchestrator | None = None
        self._queue: list[QueuedLeg] = []
        self._next = 41
        self.executions: list[Execution] = []

    def bind(self, orchestrator: Orchestrator) -> FakeWorkflowEngine:
        self._orchestrator = orchestrator
        return self

    async def start_leg(self, workflow: str, leg: Leg, run_id: RunId) -> N8nExecutionId:
        execution = N8nExecutionId(str(self._next))
        self._next += 1
        self._queue.append(QueuedLeg(workflow, leg, run_id, execution))
        return execution

    async def drain(self) -> None:
        assert self._orchestrator is not None
        while True:
            await self._orchestrator.tick()
            if not self._queue:
                return
            queued = self._queue.pop(0)
            await self._run_leg(queued)

    async def _run_leg(self, queued: QueuedLeg) -> None:
        assert self._orchestrator is not None
        record = Execution(queued.execution, queued.workflow, queued.leg, queued.run_id)
        self.executions.append(record)
        definition = self._definitions[queued.workflow]
        for node in definition.steps(queued.leg):
            reply = None
            for _ in range(node.tries):
                try:
                    reply = await self._orchestrator.on_step(
                        queued.run_id, node.step, queued.execution
                    )
                    break
                except RetryLater:
                    continue
            if reply is None:
                record.status = "error"
                await self._orchestrator.on_workflow_failure(
                    queued.execution,
                    queued.workflow,
                    node.node_name,
                    "The service answered 503 on every try",
                )
                return
            record.steps.append((node.step.value, reply.proceed, reply.outcome))
            if not reply.proceed:
                break
        record.status = "success"
