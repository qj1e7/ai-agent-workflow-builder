from dataclasses import replace
from datetime import UTC, datetime, timedelta

from platform_api.orchestration.confirmations import (
    Confirmation,
    ConfirmationId,
    DecideRefusal,
    Decision,
    Kind,
    SettingsChange,
    digest_of,
)
from platform_api.orchestration.people import DEPLOY, Person
from platform_api.orchestration.people_http import (
    AddPersonIn,
    ConfirmationDecisionIn,
    ConfirmationsOut,
    DecideRefusalOut,
    PeopleOut,
    PeopleRefusalOut,
    confirmation_out,
    decided_out,
    history_out,
    person_out,
)
from platform_api.orchestration.people_store import ConfirmationRow, HistoryLine, PersonRow
from platform_api.shared import UserId
from platform_api.wire import WireModel

SEEDED = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
ADDED = datetime(2026, 11, 9, 3, 40, tzinfo=UTC)
ASKED = ADDED + timedelta(minutes=1)
CONFIRMED = ASKED + timedelta(hours=2)


def person(
    id: str,
    display: str,
    operator: bool,
    approver: bool,
    added_by: str = DEPLOY,
    added_at: datetime = SEEDED,
    signed_in: bool = True,
) -> Person:
    return Person(
        id=UserId(id),
        email=f"{id}@example.test",
        display=display,
        is_operator=operator,
        is_approver=approver,
        added_by=UserId(added_by),
        added_at=added_at,
        entra_oid=f"0000000{id[0]}-0000-4000-8000-00000000000{len(id)}" if signed_in else None,
        bound_at=added_at if signed_in else None,
    )


ALICE = person("alice", "Alice", True, True)
BOB = person("bob", "Bob", False, True)
CAROL = person("carol", "Carol", True, False)
DAVE = person("per_01JD4VE", "Dave", True, False, added_by="alice", added_at=ADDED, signed_in=False)
DAVE_CHANGE = {
    "person_id": DAVE.id,
    "email": DAVE.email,
    "display": DAVE.display,
    "role": "approver",
    "added_at": ADDED.isoformat(),
}
DAVE_ASKED = Confirmation(
    id=ConfirmationId("cfm_01JD4VE"),
    kind=Kind.APPROVER,
    about=DAVE.id,
    change=DAVE_CHANGE,
    digest=digest_of(Kind.APPROVER, DAVE.id, ALICE.id, ASKED, DAVE_CHANGE),
    asked_by=ALICE.id,
    asked_at=ASKED,
)
DAVE_CONFIRMED = replace(
    DAVE_ASKED, decided_by=BOB.id, decision=Decision.CONFIRMED, decided_at=CONFIRMED
)
ADDRESS_CHANGE = {
    "host": "ai-gateway.ncs.example",
    "base_url": "https://ai-gateway.ncs.example/v1",
    "model": "ncs-llm-small",
    "style": "openai",
    "key_hint": "q4",
}
ADDRESS_ASKED = Confirmation(
    id=ConfirmationId("cfm_01JADDR"),
    kind=Kind.MODEL_ADDRESS,
    about=None,
    change=ADDRESS_CHANGE,
    digest="sha256:" + "a1" * 32,
    asked_by=ALICE.id,
    asked_at=ASKED,
)


def _row(
    confirmation: Confirmation, about: Person | None, why_not: DecideRefusal | None
) -> ConfirmationRow:
    return ConfirmationRow(confirmation, "Alice", about, why_not)


HISTORY = [
    HistoryLine(
        SettingsChange(
            CONFIRMED,
            "people",
            ALICE.id,
            BOB.id,
            DAVE_ASKED.id,
            "Bob confirmed Dave as an Approver, as Alice asked.",
        ),
        "Alice",
        "Bob",
    ),
    HistoryLine(
        SettingsChange(
            ASKED,
            "people",
            ALICE.id,
            None,
            DAVE_ASKED.id,
            "Alice asked to make Dave an Approver. Another Approver must confirm.",
        ),
        "Alice",
        None,
    ),
    HistoryLine(
        SettingsChange(
            ADDED,
            "people",
            ALICE.id,
            None,
            None,
            "Alice added Dave (per_01JD4VE@example.test) as an Operator.",
        ),
        "Alice",
        None,
    ),
    HistoryLine(
        SettingsChange(
            SEEDED,
            "people",
            UserId(DEPLOY),
            None,
            None,
            "The deploy put Alice (alice@example.test, Operator and Approver), "
            "Bob (bob@example.test, Approver) and Carol (carol@example.test, Operator) "
            "on the list.",
        ),
        None,
        None,
    ),
]


def people_fixtures() -> dict[str, WireModel]:
    return {
        "people/list.json": PeopleOut(
            people=[
                person_out(PersonRow(ALICE, None)),
                person_out(PersonRow(BOB, None)),
                person_out(PersonRow(CAROL, None)),
                person_out(PersonRow(DAVE, DAVE_ASKED)),
            ]
        ),
        "people/add.in.json": AddPersonIn(
            email="dave@example.test", display="Dave", operator=True, approver=True
        ),
        "people/person.pending.json": person_out(PersonRow(DAVE, DAVE_ASKED)),
        "people/person.approver.json": person_out(PersonRow(replace(DAVE, is_approver=True), None)),
        "people/refusal.two_approvers.json": PeopleRefusalOut(
            refusal="two_approvers",
            message="At least two people must stay Approvers, so nobody approves their own work.",
        ),
        "people/refusal.own_operator_role.json": PeopleRefusalOut(
            refusal="own_operator_role", message="You cannot remove your own Operator role."
        ),
        "people/confirmations.alice.json": ConfirmationsOut(
            confirmations=[
                confirmation_out(_row(DAVE_ASKED, DAVE, DecideRefusal.YOU_ASKED)),
                confirmation_out(_row(ADDRESS_ASKED, None, DecideRefusal.YOU_ASKED)),
            ]
        ),
        "people/confirmations.bob.json": ConfirmationsOut(
            confirmations=[
                confirmation_out(_row(DAVE_ASKED, DAVE, None)),
                confirmation_out(_row(ADDRESS_ASKED, None, None)),
            ]
        ),
        "people/decision.in.json": ConfirmationDecisionIn(
            verdict="confirm", digest=DAVE_ASKED.digest
        ),
        "people/decision.confirmed.json": decided_out(DAVE_CONFIRMED),
        "people/decide-refusal.you_asked.json": DecideRefusalOut(
            refusal="you_asked",
            message="You asked for this change, so another Approver must confirm it.",
        ),
        "settings/history.json": history_out(HISTORY),
    }
