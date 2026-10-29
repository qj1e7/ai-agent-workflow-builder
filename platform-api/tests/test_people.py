from datetime import UTC, datetime, timedelta

import pytest

from platform_api.auth import DEV_PEOPLE
from platform_api.orchestration import people as rules
from platform_api.orchestration.confirmations import (
    Confirmation,
    ConfirmationId,
    DecideRefusal,
    DecideRefused,
    Decision,
    Kind,
    decide,
    digest_of,
    why_not,
)
from platform_api.orchestration.people import Added, Changed, PeopleRefusal, Person, Refused
from platform_api.shared import Principal, Role, UserId

NOW = datetime(2026, 11, 3, 2, 14, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)


def person(
    id: str, operator: bool = False, approver: bool = False, removed: bool = False
) -> Person:
    return Person(
        id=UserId(id),
        email=f"{id}@example.test",
        display=id.capitalize(),
        is_operator=operator,
        is_approver=approver,
        added_by=rules.DEPLOY,
        added_at=NOW,
        removed_at=NOW if removed else None,
    )


ALICE = person("alice", operator=True, approver=True)
BOB = person("bob", approver=True)
CAROL = person("carol", operator=True)
DAVE = person("dave", operator=True)
ERIN = person("erin", approver=True)
GONE = person("gone", removed=True)
TEAM = [ALICE, BOB, CAROL, DAVE, GONE]

next_id = iter(f"per_{n}" for n in range(1, 100))


def new_id() -> UserId:
    return UserId(next(next_id))


def refused(outcome: object) -> PeopleRefusal:
    assert isinstance(outcome, Refused), outcome
    return outcome.reason


def changed(outcome: object) -> Changed:
    assert isinstance(outcome, Changed), outcome
    return outcome


def test_the_dev_seed_is_alice_bob_and_carol_with_their_roles():
    seeded = rules.seed_people(DEV_PEOPLE, NOW)
    assert [(p.id, p.is_operator, p.is_approver, p.email) for p in seeded] == [
        ("alice", True, True, "alice@example.test"),
        ("bob", False, True, "bob@example.test"),
        ("carol", True, False, "carol@example.test"),
    ]
    assert all(p.added_by == rules.DEPLOY and p.added_at == NOW for p in seeded)
    assert rules.seed_summary(seeded) == (
        "The deploy put Alice (alice@example.test, Operator and Approver), "
        "Bob (bob@example.test, Approver) and Carol (carol@example.test, Operator) on the list."
    )


def test_the_first_people_may_overlap_and_get_names_from_their_emails():
    seeded = rules.first_people(
        "Jo.Tan@ncs.example", ["jo.tan@ncs.example", "mei_lin@ncs.example"], NOW, new_id
    )
    assert [(p.email, p.display, p.is_operator, p.is_approver) for p in seeded] == [
        ("Jo.Tan@ncs.example", "Jo Tan", True, True),
        ("mei_lin@ncs.example", "Mei Lin", False, True),
    ]
    assert len({p.id for p in seeded}) == 2


class TestAddPerson:
    def test_an_operator_adds_an_operator_at_once(self):
        outcome = rules.add_person(
            ALICE, TEAM, " Erin@example.test ", "Erin", True, False, NOW, new_id
        )
        assert isinstance(outcome, Added)
        assert (outcome.person.email, outcome.person.is_operator, outcome.person.is_approver) == (
            "Erin@example.test",
            True,
            False,
        )
        assert (outcome.person.added_by, outcome.ask_approver) == ("alice", False)
        assert outcome.summary == "Alice added Erin (Erin@example.test) as an Operator."

    def test_ticking_approver_asks_instead_of_granting(self):
        outcome = rules.add_person(
            ALICE, TEAM, "erin@example.test", "Erin", False, True, NOW, new_id
        )
        assert isinstance(outcome, Added)
        assert (outcome.person.is_approver, outcome.ask_approver) == (False, True)
        assert outcome.summary == (
            "Alice added Erin (erin@example.test), asked to make Erin an Approver. "
            "Another Approver must confirm."
        )

    def test_both_roles_grant_operator_and_ask_for_approver(self):
        outcome = rules.add_person(
            ALICE, TEAM, "erin@example.test", "Erin", True, True, NOW, new_id
        )
        assert isinstance(outcome, Added)
        assert (outcome.person.is_operator, outcome.ask_approver) == (True, True)
        assert "as an Operator and asked to make Erin an Approver" in outcome.summary

    def test_only_an_operator_adds(self):
        outcome = rules.add_person(BOB, TEAM, "erin@example.test", "Erin", True, False, NOW, new_id)
        assert refused(outcome) is PeopleRefusal.NOT_AN_OPERATOR

    @pytest.mark.parametrize("email", ["erin", "erin@", "@example.test", "erin @example.test", ""])
    def test_an_email_is_required(self, email: str):
        outcome = rules.add_person(ALICE, TEAM, email, "Erin", True, False, NOW, new_id)
        assert refused(outcome) is PeopleRefusal.BAD_EMAIL

    def test_a_name_and_at_least_one_role_are_required(self):
        no_role = rules.add_person(
            ALICE, TEAM, "erin@example.test", "Erin", False, False, NOW, new_id
        )
        no_name = rules.add_person(ALICE, TEAM, "erin@example.test", "  ", True, False, NOW, new_id)
        assert (refused(no_role), refused(no_name)) == (
            PeopleRefusal.NO_ROLE,
            PeopleRefusal.NO_ROLE,
        )

    def test_an_email_already_on_the_list_is_refused_ignoring_case(self):
        outcome = rules.add_person(
            ALICE, TEAM, "BOB@example.test", "Bobby", True, False, NOW, new_id
        )
        assert refused(outcome) is PeopleRefusal.ALREADY_ON_THE_LIST

    def test_a_removed_person_comes_back_under_the_same_id(self):
        outcome = rules.add_person(
            ALICE, TEAM, "gone@example.test", "Gone", True, False, LATER, new_id
        )
        assert isinstance(outcome, Added)
        assert (outcome.person.id, outcome.person.removed_at, outcome.person.is_operator) == (
            "gone",
            None,
            True,
        )
        assert outcome.person.added_at == LATER


class TestOperatorRole:
    def test_an_operator_grants_it_at_once(self):
        outcome = changed(rules.set_operator(ALICE, TEAM, BOB, True))
        assert outcome.person.is_operator is True
        assert outcome.summary == "Alice made Bob an Operator."

    def test_an_operator_removes_it_at_once(self):
        outcome = changed(rules.set_operator(CAROL, TEAM, ALICE, False))
        assert (outcome.person.is_operator, outcome.person.is_approver) == (False, True)
        assert outcome.summary == "Carol removed Alice's Operator role."

    def test_nobody_removes_their_own_operator_role(self):
        assert (
            refused(rules.set_operator(ALICE, TEAM, ALICE, False))
            is PeopleRefusal.OWN_OPERATOR_ROLE
        )

    def test_two_operators_cannot_strip_each_other_at_the_same_moment(self):
        fay = person("fay", operator=True, approver=True)
        team = [ALICE, BOB, fay]
        first = changed(rules.set_operator(ALICE, team, fay, False))
        after = [ALICE, BOB, first.person]
        assert rules.operators(after) == [ALICE]
        assert refused(rules.set_operator(first.person, after, ALICE, False)) is (
            PeopleRefusal.NOT_AN_OPERATOR
        )

    def test_everyone_keeps_at_least_one_role(self):
        assert refused(rules.set_operator(ALICE, TEAM, CAROL, False)) is PeopleRefusal.NO_ROLE

    def test_granting_a_role_someone_has_changes_nothing(self):
        assert changed(rules.set_operator(ALICE, TEAM, CAROL, True)).summary is None
        assert changed(rules.set_operator(ALICE, TEAM, BOB, False)).summary is None

    def test_only_an_operator_changes_it(self):
        assert refused(rules.set_operator(BOB, TEAM, CAROL, False)) is PeopleRefusal.NOT_AN_OPERATOR
        assert refused(rules.set_operator(GONE, TEAM, CAROL, True)) is PeopleRefusal.NOT_AN_OPERATOR


class TestApproverRole:
    def test_asking_opens_a_confirmation(self):
        outcome = changed(rules.ask_approver(ALICE, TEAM, DAVE, pending=()))
        assert outcome.person.is_approver is False
        assert outcome.summary == (
            "Alice asked to make Dave an Approver. Another Approver must confirm."
        )

    def test_asking_twice_or_for_an_approver_is_refused(self):
        assert refused(rules.ask_approver(ALICE, TEAM, DAVE, pending=[DAVE.id])) is (
            PeopleRefusal.ALREADY_ASKED
        )
        assert refused(rules.ask_approver(ALICE, TEAM, BOB, pending=())) is (
            PeopleRefusal.ALREADY_AN_APPROVER
        )
        assert refused(rules.ask_approver(BOB, TEAM, DAVE, pending=())) is (
            PeopleRefusal.NOT_AN_OPERATOR
        )

    def test_removing_keeps_two_confirmed_approvers(self):
        assert refused(rules.remove_approver(CAROL, TEAM, BOB, pending=())) is (
            PeopleRefusal.TWO_APPROVERS
        )
        three = [*TEAM, ERIN]
        outcome = changed(rules.remove_approver(CAROL, three, ALICE, pending=()))
        assert outcome.person.roles == frozenset({Role.OPERATOR})
        assert outcome.summary == "Carol removed Alice's Approver role."

    def test_a_pending_approver_does_not_count_towards_the_floor(self):
        three = [ALICE, BOB, CAROL, person("erin")]
        assert refused(rules.remove_approver(CAROL, three, BOB, pending=[UserId("erin")])) is (
            PeopleRefusal.TWO_APPROVERS
        )

    def test_removing_while_a_confirmation_waits_is_refused(self):
        assert refused(rules.remove_approver(ALICE, TEAM, DAVE, pending=[DAVE.id])) is (
            PeopleRefusal.CONFIRMATION_WAITING
        )

    def test_an_approver_only_person_cannot_lose_their_only_role(self):
        team = [ALICE, BOB, CAROL, ERIN]
        assert refused(rules.remove_approver(CAROL, team, BOB, pending=())) is PeopleRefusal.NO_ROLE
        assert changed(rules.remove_approver(CAROL, team, ALICE, pending=())).person.roles == (
            frozenset({Role.OPERATOR})
        )

    def test_removing_what_nobody_has_changes_nothing(self):
        assert changed(rules.remove_approver(ALICE, TEAM, CAROL, pending=())).summary is None

    def test_a_confirmed_grant_sets_the_flag(self):
        assert rules.grant_approver(DAVE).is_approver is True


class TestRemovePerson:
    def test_an_operator_removes_someone_softly(self):
        outcome = changed(rules.remove_person(ALICE, TEAM, DAVE, LATER))
        assert (outcome.person.removed_at, outcome.person.roles) == (LATER, frozenset())
        assert outcome.summary == "Alice removed Dave from the list."

    def test_nobody_removes_themselves(self):
        assert refused(rules.remove_person(ALICE, TEAM, ALICE, LATER)) is PeopleRefusal.YOURSELF

    def test_the_two_approver_floor_holds(self):
        assert refused(rules.remove_person(CAROL, TEAM, BOB, LATER)) is PeopleRefusal.TWO_APPROVERS
        assert (
            refused(rules.remove_person(CAROL, TEAM, ALICE, LATER)) is PeopleRefusal.TWO_APPROVERS
        )
        three = [*TEAM, ERIN]
        assert changed(rules.remove_person(CAROL, three, BOB, LATER)).person.removed_at == LATER

    def test_an_operator_who_is_not_the_last_can_go(self):
        team = [ALICE, BOB, DAVE]
        assert changed(rules.remove_person(ALICE, team, DAVE, LATER)).person.on_list is False

    def test_only_an_operator_removes(self):
        assert refused(rules.remove_person(BOB, TEAM, DAVE, LATER)) is PeopleRefusal.NOT_AN_OPERATOR


ASKED = Confirmation(
    id=ConfirmationId("cfm_1"),
    kind=Kind.APPROVER,
    about=DAVE.id,
    change={"person_id": "dave", "role": "approver"},
    digest=digest_of(
        Kind.APPROVER, DAVE.id, ALICE.id, NOW, {"person_id": "dave", "role": "approver"}
    ),
    asked_by=ALICE.id,
    asked_at=NOW,
)


class TestDecideConfirmation:
    def test_another_approver_confirms_once(self):
        decided = decide(ASKED, BOB.principal, Decision.CONFIRMED, ASKED.digest, LATER)
        assert isinstance(decided, Confirmation)
        assert (decided.decided_by, decided.decision, decided.decided_at) == (
            "bob",
            Decision.CONFIRMED,
            LATER,
        )
        again = decide(decided, ERIN.principal, Decision.CONFIRMED, ASKED.digest, LATER)
        assert isinstance(again, DecideRefused)
        assert again.reason is DecideRefusal.ALREADY_DECIDED

    def test_the_asker_and_the_person_it_is_about_cannot_decide(self):
        asker = decide(ASKED, ALICE.principal, Decision.CONFIRMED, ASKED.digest, LATER)
        about = decide(ASKED, DAVE.principal, Decision.CONFIRMED, ASKED.digest, LATER)
        assert isinstance(asker, DecideRefused) and asker.reason is DecideRefusal.YOU_ASKED
        assert isinstance(about, DecideRefused) and about.reason is DecideRefusal.NOT_AN_APPROVER
        dave_approver = Principal(DAVE.id, frozenset({Role.APPROVER}), "Dave")
        about = decide(ASKED, dave_approver, Decision.CONFIRMED, ASKED.digest, LATER)
        assert isinstance(about, DecideRefused) and about.reason is DecideRefusal.ABOUT_YOU

    def test_only_an_approver_decides(self):
        outcome = decide(ASKED, CAROL.principal, Decision.NOT_NOW, ASKED.digest, LATER)
        assert isinstance(outcome, DecideRefused)
        assert outcome.reason is DecideRefusal.NOT_AN_APPROVER

    def test_a_changed_digest_is_refused(self):
        outcome = decide(ASKED, BOB.principal, Decision.CONFIRMED, "sha256:" + "0" * 64, LATER)
        assert isinstance(outcome, DecideRefused)
        assert outcome.reason is DecideRefusal.DIGEST_CHANGED

    def test_a_removed_person_is_not_made_an_approver(self):
        outcome = decide(ASKED, BOB.principal, Decision.CONFIRMED, ASKED.digest, LATER, False)
        assert isinstance(outcome, DecideRefused)
        assert outcome.reason is DecideRefusal.PERSON_REMOVED

    def test_why_not_matches_the_decision(self):
        assert why_not(ASKED, BOB.principal) is None
        assert why_not(ASKED, ALICE.principal) is DecideRefusal.YOU_ASKED
        assert why_not(ASKED, CAROL.principal) is DecideRefusal.NOT_AN_APPROVER

    def test_the_digest_names_this_request_only(self):
        other = digest_of(Kind.APPROVER, DAVE.id, ALICE.id, LATER, dict(ASKED.change))
        assert other != ASKED.digest
        assert ASKED.digest.startswith("sha256:")
