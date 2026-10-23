from datetime import UTC, datetime

import pytest

from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
    Decision,
    Verdict,
)
from platform_api.orchestration.runs import Acting
from platform_api.orchestration.write_actions import (
    AuthorizedWrite,
    Binding,
    Deny,
    DenyReason,
    Proposal,
    ProposedIntent,
    UnboundIntent,
    WriteAction,
    bind,
    check,
    digest,
)
from platform_api.shared import ApprovalId, Digest, ProposalId, RunId, UserId

ALICE = UserId("alice")
BOB = UserId("bob")
CAROL = UserId("carol")
RUN = RunId("run_1")
PROPOSAL = ProposalId("prp_1")
APPROVAL = ApprovalId("apr_1")
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

TICKET = WriteAction(
    connector="jira",
    operation="create_ticket",
    target={"project": "MOCK"},
    fields={"title": "New LangGraph releases: 1.2.16, 1.2.15", "body": "..."},
)
TICKET_DIGEST = Digest("sha256:796204036c978912f71f411ea23c16e33df45b425e8d5c883f8889cd8d5cc24c")
REGISTRY = {"jira": frozenset({"create_ticket"})}
BINDINGS = {"create_ticket": Binding("jira", "create_ticket", {"project": "MOCK"})}

ONE_STEP = ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),))
TWO_STEPS = ApprovalPolicy(
    (
        ApprovalStep("Team approver", AnyApprover()),
        ApprovalStep("Access owner", AnyApprover()),
    )
)


def proposal(
    actions: tuple[WriteAction, ...] = (TICKET,),
    stored_digest: Digest = TICKET_DIGEST,
    id: ProposalId = PROPOSAL,
) -> Proposal:
    return Proposal(id, RUN, actions, stored_digest)


def request(
    policy: ApprovalPolicy = ONE_STEP,
    digest: Digest = TICKET_DIGEST,
) -> ApprovalRequest:
    return ApprovalRequest(APPROVAL, RUN, PROPOSAL, digest, policy, frozenset({ALICE}))


def approve(step: int, by: UserId, digest: Digest = TICKET_DIGEST) -> Decision:
    return Decision(APPROVAL, step, by, Verdict.APPROVE, digest, NOW)


def decline(step: int, by: UserId) -> Decision:
    return Decision(APPROVAL, step, by, Verdict.DECLINE, TICKET_DIGEST, NOW)


ACTING = Acting(RUN, PROPOSAL, APPROVAL)


def test_digest_matches_the_golden_vector():
    assert digest((TICKET,)) == TICKET_DIGEST


def test_digest_ignores_key_order():
    reordered = WriteAction(
        connector="jira",
        operation="create_ticket",
        target={"project": "MOCK"},
        fields={"body": "...", "title": "New LangGraph releases: 1.2.16, 1.2.15"},
    )
    assert digest((reordered,)) == TICKET_DIGEST


def test_digest_changes_when_a_field_changes():
    changed = WriteAction(
        "jira", "create_ticket", {"project": "MOCK"}, {"title": "x", "body": "..."}
    )
    assert digest((changed,)) != TICKET_DIGEST


@pytest.mark.parametrize(
    ("intents", "expected"),
    [
        pytest.param(
            (ProposedIntent("create_ticket", {"title": "t", "body": "b"}, "new releases"),),
            (
                WriteAction(
                    "jira", "create_ticket", {"project": "MOCK"}, {"title": "t", "body": "b"}
                ),
            ),
            id="a bound intent becomes an action with the table's target",
        ),
        pytest.param((), (), id="no intents bind to no actions"),
        pytest.param(
            (
                ProposedIntent("create_ticket", {}, "r"),
                ProposedIntent("delete_repo", {}, "r"),
                ProposedIntent("send_mail", {}, "r"),
                ProposedIntent("delete_repo", {}, "r"),
            ),
            UnboundIntent(("delete_repo", "send_mail")),
            id="unbound intents are reported once each, in order",
        ),
    ],
)
def test_bind(intents, expected):
    assert bind(intents, BINDINGS) == expected


@pytest.mark.parametrize(
    ("acting", "proposal_", "request_", "decisions", "registry", "expected"),
    [
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (approve(0, BOB),),
            REGISTRY,
            AuthorizedWrite,
            id="approved, digest intact, connector registered",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(TWO_STEPS),
            (approve(0, BOB), approve(1, CAROL)),
            REGISTRY,
            AuthorizedWrite,
            id="two-step approval complete",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (),
            REGISTRY,
            Deny(DenyReason.NOT_APPROVED),
            id="no decisions at all",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (decline(0, BOB),),
            REGISTRY,
            Deny(DenyReason.NOT_APPROVED),
            id="declined",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(TWO_STEPS),
            (approve(0, BOB),),
            REGISTRY,
            Deny(DenyReason.NOT_APPROVED),
            id="half of a two-step approval",
        ),
        pytest.param(
            ACTING,
            proposal(
                actions=(
                    WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "swapped"}),
                ),
            ),
            request(),
            (approve(0, BOB),),
            REGISTRY,
            Deny(DenyReason.DIGEST_MISMATCH),
            id="actions changed after approval, stored digest still claims the old one",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (approve(0, BOB),),
            {},
            Deny(DenyReason.UNREGISTERED_ACTION),
            id="unregistered connector",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (approve(0, BOB),),
            {"jira": frozenset({"comment"})},
            Deny(DenyReason.UNREGISTERED_ACTION),
            id="registered connector, unregistered operation",
        ),
        pytest.param(
            Acting(RUN, ProposalId("prp_other"), APPROVAL),
            proposal(),
            request(),
            (approve(0, BOB),),
            REGISTRY,
            Deny(DenyReason.RUN_MISMATCH),
            id="acting run is for a different proposal",
        ),
        pytest.param(
            Acting(RUN, PROPOSAL, ApprovalId("apr_other")),
            proposal(),
            request(),
            (approve(0, BOB),),
            REGISTRY,
            Deny(DenyReason.RUN_MISMATCH),
            id="acting run is for a different approval",
        ),
        pytest.param(
            Acting(RunId("run_other"), PROPOSAL, APPROVAL),
            proposal(),
            request(),
            (approve(0, BOB),),
            REGISTRY,
            Deny(DenyReason.RUN_MISMATCH),
            id="acting run is a different run",
        ),
        pytest.param(
            ACTING,
            proposal(id=ProposalId("prp_other")),
            request(),
            (approve(0, BOB),),
            REGISTRY,
            Deny(DenyReason.RUN_MISMATCH),
            id="the approval was opened for a different proposal",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (approve(0, BOB, Digest("sha256:old")),),
            REGISTRY,
            Deny(DenyReason.INVALID_DECISIONS),
            id="a stored decision with another digest",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (approve(0, BOB), decline(0, CAROL)),
            REGISTRY,
            Deny(DenyReason.INVALID_DECISIONS),
            id="conflicting decisions on one step, approve first",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (decline(0, CAROL), approve(0, BOB)),
            REGISTRY,
            Deny(DenyReason.INVALID_DECISIONS),
            id="conflicting decisions on one step, decline first",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(),
            (approve(0, ALICE),),
            REGISTRY,
            Deny(DenyReason.INVALID_DECISIONS),
            id="approved by a party to the run",
        ),
        pytest.param(
            ACTING,
            proposal(),
            request(TWO_STEPS),
            (approve(0, BOB), approve(1, BOB)),
            REGISTRY,
            Deny(DenyReason.INVALID_DECISIONS),
            id="one person approved both steps",
        ),
    ],
)
def test_check(acting, proposal_, request_, decisions, registry, expected):
    result = check(acting, proposal_, request_, decisions, registry)
    if expected is AuthorizedWrite:
        assert isinstance(result, AuthorizedWrite)
    else:
        assert result == expected


def test_authorized_write_carries_the_proposal_and_who_approved():
    result = check(
        ACTING, proposal(), request(TWO_STEPS), (approve(0, BOB), approve(1, CAROL)), REGISTRY
    )
    assert isinstance(result, AuthorizedWrite)
    assert result.proposal == proposal()
    assert result.approval_id == APPROVAL
    assert result.approvers == (BOB, CAROL)


def test_authorized_write_cannot_be_built_directly():
    with pytest.raises(TypeError):
        AuthorizedWrite()
