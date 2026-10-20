from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from platform_api.orchestration.approvals import ApprovalPolicy
from platform_api.orchestration.write_actions import Binding
from platform_api.shared import Principal, RunId, UseCaseId, UserId


@dataclass(frozen=True)
class RunSpec:
    use_case_id: UseCaseId
    use_case_version: int
    use_case_name: str
    owner: UserId
    workflow: str
    instruction: str
    repo: str
    tag_pattern: str
    last_known_tag: str | None
    bindings: Mapping[str, Binding]
    approval_policy: ApprovalPolicy


@dataclass(frozen=True)
class RunStarted:
    run_id: RunId
    created: bool


class RunStarter(Protocol):
    async def start_run(
        self, spec: RunSpec, principal: Principal, idempotency_key: str
    ) -> RunStarted: ...

    async def latest_carry_forward(self, use_case_id: UseCaseId) -> str | None: ...
