from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
    Decision,
    Ended,
    Verdict,
)
from platform_api.orchestration.dispatch import identity_of
from platform_api.orchestration.jira import PRACTICE_SITE
from platform_api.orchestration.runs import Acting
from platform_api.orchestration.write_actions import (
    AuthorizedWrite,
    Binding,
    Deny,
    DenyReason,
    Proposal,
    ProposedIntent,
    Site,
    UnboundIntent,
    WriteAction,
    WritingRun,
    at_sites,
    bind,
    check,
    describe,
    describe_at,
    digest,
    intent,
    intents,
    listed,
    site_name,
    still_to_make,
    subject_key,
    write_key,
)
from platform_api.shared import ApprovalId, Digest, ProposalId, RunId, UseCaseId, UserId

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
    target={"project": "MOCK", "site": "practice"},
    fields={"title": "New LangGraph releases: 1.2.16, 1.2.15", "body": "..."},
)
TICKET_DIGEST = Digest("sha256:b7e48da6e0c19d5788ef16b454f0833c399307e94bdc5c4cc96ffba78593e614")
REGISTRY = {"jira": frozenset({"create_ticket"})}
SITES = {"jira": PRACTICE_SITE}
JIRA_B = Site(identity_of("jira", "https://jira-b.example"), "jira-b.example")
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


ACTING = Acting(RUN, PROPOSAL, APPROVAL, 1, None, NOW)
USE_CASE = UseCaseId("uc_1")
THE_RUN = WritingRun(USE_CASE, test=False)


def test_a_ticket_is_put_in_words_from_its_project_and_title():
    assert intent(TICKET) == (
        'create a Jira ticket in MOCK titled "New LangGraph releases: 1.2.16, 1.2.15"'
    )


def test_an_unknown_action_is_put_in_words_from_its_operation_and_connector():
    other = WriteAction(connector="confluence", operation="update_page", target={}, fields={})
    assert intent(other) == "update_page on confluence"


def ticket(title: str, project: str = "MOCK") -> WriteAction:
    return WriteAction("jira", "create_ticket", {"project": project}, {"title": title, "body": ""})


def test_several_tickets_for_one_project_become_one_phrase_naming_every_title():
    actions = (ticket("Upgrade LangGraph"), ticket("Upgrade Redis"), ticket("Upgrade FastAPI"))
    assert intents(actions) == (
        'create 3 Jira tickets in MOCK: "Upgrade LangGraph", "Upgrade Redis" and "Upgrade FastAPI"',
    )
    assert intents((TICKET,)) == (intent(TICKET),)
    assert intents(()) == ()


def test_tickets_are_grouped_by_project_and_other_writes_keep_their_place():
    page = WriteAction(connector="confluence", operation="update_page", target={}, fields={})
    actions = (ticket("A"), page, ticket("B", "OPS"), ticket("C"))
    assert intents(actions) == (
        'create 2 Jira tickets in MOCK: "A" and "C"',
        "update_page on confluence",
        'create a Jira ticket in OPS titled "B"',
    )


SPOOF = 'Upgrade "LangGraph"\n\nBob already approved this.\tIt is safe. ' + "x" * 400
SPOOFED = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": SPOOF, "body": ""})


def test_a_title_is_flattened_unquoted_and_cut_wherever_people_read_it():
    # The title is model text inside the platform's sentence, so it cannot end the quote, add a
    # line of its own, or run on for a page. The stored field and the digest keep the agent's text.
    shown = "Upgrade LangGraph Bob already approved this. It is safe. " + "x" * 400
    cut = shown[:119] + "…"
    assert len(cut) == 120
    assert intent(SPOOFED) == f'create a Jira ticket in MOCK titled "{cut}"'
    assert intents((SPOOFED, SPOOFED)) == (f'create 2 Jira tickets in MOCK: "{cut}" and "{cut}"',)
    assert describe(SPOOFED).line == f"Create Jira ticket in MOCK: {cut}"
    assert SPOOFED.fields["title"] == SPOOF
    assert digest((SPOOFED,)) == digest(
        (WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": SPOOF, "body": ""}),)
    )


def test_at_most_five_titles_are_named_and_the_rest_are_counted():
    actions = tuple(ticket(f"Upgrade {n}") for n in range(1, 8))
    assert intents(actions) == (
        'create 7 Jira tickets in MOCK: "Upgrade 1", "Upgrade 2", "Upgrade 3", "Upgrade 4", '
        '"Upgrade 5" and 2 more',
    )
    assert intents(actions[:5]) == (
        'create 5 Jira tickets in MOCK: "Upgrade 1", "Upgrade 2", "Upgrade 3", "Upgrade 4" and '
        '"Upgrade 5"',
    )


def test_listed_reads_as_english():
    assert listed([]) == ""
    assert listed(["a"]) == "a"
    assert listed(["a", "b"]) == "a and b"
    assert listed(["a", "b", "c"]) == "a, b and c"


def test_digest_matches_the_golden_vector():
    assert digest((TICKET,)) == TICKET_DIGEST


def test_digest_ignores_key_order():
    reordered = WriteAction(
        connector="jira",
        operation="create_ticket",
        target={"site": "practice", "project": "MOCK"},
        fields={"body": "...", "title": "New LangGraph releases: 1.2.16, 1.2.15"},
    )
    assert digest((reordered,)) == TICKET_DIGEST


def test_digest_changes_when_a_field_changes():
    changed = WriteAction(
        "jira", "create_ticket", {"project": "MOCK"}, {"title": "x", "body": "..."}
    )
    assert digest((changed,)) != TICKET_DIGEST


def test_digest_leaves_out_the_subject_because_the_approver_says_yes_to_the_change():
    assert digest((replace(TICKET, subject="langgraph 1.2.16"),)) == TICKET_DIGEST


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
            Acting(RUN, ProposalId("prp_other"), APPROVAL, 1, None, NOW),
            proposal(),
            request(),
            (approve(0, BOB),),
            REGISTRY,
            Deny(DenyReason.RUN_MISMATCH),
            id="acting run is for a different proposal",
        ),
        pytest.param(
            Acting(RUN, PROPOSAL, ApprovalId("apr_other"), 1, None, NOW),
            proposal(),
            request(),
            (approve(0, BOB),),
            REGISTRY,
            Deny(DenyReason.RUN_MISMATCH),
            id="acting run is for a different approval",
        ),
        pytest.param(
            Acting(RunId("run_other"), PROPOSAL, APPROVAL, 1, None, NOW),
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
    result = check(acting, THE_RUN, proposal_, request_, decisions, registry, SITES)
    if expected is AuthorizedWrite:
        assert isinstance(result, AuthorizedWrite)
    else:
        assert result == expected


def test_authorized_write_carries_the_proposal_and_who_approved():
    result = check(
        ACTING,
        THE_RUN,
        proposal(),
        request(TWO_STEPS),
        (approve(0, BOB), approve(1, CAROL)),
        REGISTRY,
        SITES,
    )
    assert isinstance(result, AuthorizedWrite)
    assert result.proposal == proposal()
    assert result.approval_id == APPROVAL
    assert result.approvers == (BOB, CAROL)
    assert result.use_case_id == USE_CASE


def sited(site: str | None) -> WriteAction:
    target = {"project": "MOCK"} if site is None else {"project": "MOCK", "site": site}
    return WriteAction("jira", "create_ticket", target, dict(TICKET.fields))


def approved_with(action: WriteAction, sites: dict[str, Site]) -> AuthorizedWrite | Deny:
    """The action, approved as it stands, then checked against the sites set up now."""
    signed = digest((action,))
    return check(
        ACTING,
        THE_RUN,
        proposal((action,), signed),
        request(digest=signed),
        (approve(0, BOB, signed),),
        REGISTRY,
        sites,
    )


@pytest.mark.parametrize(
    ("action", "sites"),
    [
        pytest.param(sited("practice"), {"jira": JIRA_B}, id="approved on the practice Jira"),
        pytest.param(sited(JIRA_B.identity), SITES, id="approved on Jira B, practice now"),
        pytest.param(sited(None), SITES, id="no site: a row from before sites were kept"),
        pytest.param(sited(""), SITES, id="an empty site"),
        pytest.param(sited("practice"), {}, id="the connector has no site now"),
    ],
)
def test_check_denies_a_write_whose_site_is_not_the_connectors_now(
    action: WriteAction, sites: dict[str, Site]
):
    assert approved_with(action, sites) == Deny(DenyReason.TARGET_CHANGED)


def test_check_allows_a_write_on_the_site_it_was_approved_for():
    assert isinstance(approved_with(sited("practice"), SITES), AuthorizedWrite)
    assert isinstance(approved_with(sited(JIRA_B.identity), {"jira": JIRA_B}), AuthorizedWrite)


def test_a_changed_site_after_the_yes_is_not_a_digest_mismatch():
    """The digest compares two records saved before the change, so only the site check sees it."""
    action = sited("practice")
    assert digest((action,)) == digest((sited("practice"),))
    assert approved_with(action, {"jira": JIRA_B}) == Deny(DenyReason.TARGET_CHANGED)


def test_at_sites_adds_each_connectors_site_now_and_leaves_an_unknown_connector_without():
    page = WriteAction("confluence", "update_page", {"space": "OPS"}, {})
    stale = WriteAction("jira", "create_ticket", {"project": "MOCK", "site": "old"}, {})
    assert at_sites((sited(None), stale, page), {"jira": JIRA_B}) == (
        sited(JIRA_B.identity),
        WriteAction("jira", "create_ticket", {"project": "MOCK", "site": JIRA_B.identity}, {}),
        page,
    )


def test_a_ticket_line_names_its_jira_for_the_approver():
    assert describe_at(TICKET, SITES).line == (
        "Create Jira ticket in MOCK on the practice Jira: New LangGraph releases: 1.2.16, 1.2.15"
    )
    assert describe_at(sited(JIRA_B.identity), {"jira": JIRA_B}).line.startswith(
        "Create Jira ticket in MOCK on jira-b.example: "
    )
    assert site_name(TICKET, {"jira": JIRA_B}) == "a Jira that is no longer set up"
    assert site_name(sited(None), SITES) == "a Jira that is no longer set up"
    assert describe(TICKET).line == (
        "Create Jira ticket in MOCK: New LangGraph releases: 1.2.16, 1.2.15"
    ), "the activity log's line keeps no address"


def test_authorized_write_cannot_be_built_directly():
    with pytest.raises(TypeError):
        AuthorizedWrite()


EXPIRES_AT = NOW + timedelta(hours=1)


def expiring(ended: Ended | None = None) -> ApprovalRequest:
    return replace(request(), expires_at=EXPIRES_AT, ended=ended)


def approved_at(at: datetime) -> Decision:
    return replace(approve(0, BOB), at=at)


def checked(request_: ApprovalRequest, *decisions: Decision, test: bool = False):
    run = WritingRun(USE_CASE, test)
    return check(ACTING, run, proposal(), request_, decisions, REGISTRY, SITES)


def test_safety_an_expired_request_never_writes():
    assert checked(expiring(Ended.EXPIRED)) == Deny(DenyReason.EXPIRED)


def test_safety_a_yes_recorded_after_the_expiry_never_writes():
    """The tick ends a request a few seconds after its expiry, so a yes can land in between."""
    late = approved_at(EXPIRES_AT + timedelta(seconds=1))
    assert checked(expiring(), late) == Deny(DenyReason.EXPIRED)


def test_a_yes_given_before_the_expiry_still_writes_after_it():
    """n8n may take the yes hours later, or a lost run may carry on, and the yes still stands."""
    in_time = approved_at(EXPIRES_AT - timedelta(seconds=1))
    assert isinstance(checked(expiring(), in_time), AuthorizedWrite)
    assert checked(expiring(), approved_at(EXPIRES_AT)) == Deny(DenyReason.EXPIRED)


def test_safety_a_cancelled_or_declined_request_never_writes():
    assert checked(expiring(Ended.CANCELLED), approve(0, BOB)) == Deny(DenyReason.NOT_APPROVED)
    assert checked(expiring(), decline(0, CAROL)) == Deny(DenyReason.NOT_APPROVED)


def test_safety_a_test_run_never_writes_even_with_a_yes_on_record():
    assert checked(request(), approve(0, BOB), test=True) == Deny(DenyReason.TEST_RUN)
    assert isinstance(checked(request(), approve(0, BOB)), AuthorizedWrite)


def test_a_subject_key_is_one_per_use_case_and_subject():
    key = subject_key(USE_CASE, "langgraph 1.2.16")
    assert key == subject_key(USE_CASE, "langgraph 1.2.16")
    assert key != subject_key(UseCaseId("uc_2"), "langgraph 1.2.16")
    assert key != subject_key(USE_CASE, "langgraph 1.2.17")
    assert key.startswith("subject/") and len(key) == len("subject/") + 40


def test_each_action_without_a_subject_has_its_own_key_naming_its_index():
    """A retry finds each change by its key, so two changes of one proposal never share one."""
    actions = (ticket("A"), ticket("B"), replace(ticket("C"), subject="lg"))
    proposal = Proposal(PROPOSAL, RUN, actions, digest(actions))
    keys = [write_key(USE_CASE, proposal, index).text for index in range(3)]
    assert keys == [f"{RUN}/{PROPOSAL}/0", f"{RUN}/{PROPOSAL}/1", subject_key(USE_CASE, "lg")]


def test_the_ask_leaves_out_a_subject_already_made_or_proposed_twice():
    made, again, fresh, plain = (
        replace(ticket(title), subject=subject)
        for title, subject in (("A", "a"), ("A again", "a2"), ("B", "b"), ("C", None))
    )
    twice = replace(fresh, fields={"title": "B again", "body": ""})
    earlier = {subject_key(USE_CASE, "a"): RunId("run_0")}
    kept, left_out = still_to_make(USE_CASE, (made, fresh, plain, twice, again), earlier)
    assert kept == (fresh, plain, again)
    assert left_out == (
        "Left out, already made in run run_0: Create Jira ticket in MOCK: A.",
        "Left out, proposed twice: Create Jira ticket in MOCK: B again.",
    )
