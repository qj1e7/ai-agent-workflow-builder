from dataclasses import dataclass

from platform_api.shared import ApprovalId, ProposalId, RunId


@dataclass(frozen=True)
class Acting:
    run_id: RunId
    proposal_id: ProposalId
    approval_id: ApprovalId
