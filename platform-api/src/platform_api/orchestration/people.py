"""People and their roles (ADR 0029). The rules are pure; the store applies them under a lock."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from platform_api.shared import Principal, Role, SeedPerson, UserId

DEPLOY = UserId("deploy")
MIN_OPERATORS = 1
MIN_APPROVERS = 2
MAX_EMAIL_CHARS = 254
MAX_DISPLAY_CHARS = 120


def roles_from(is_operator: bool, is_approver: bool) -> frozenset[Role]:
    """The roles that a person's two flags on the People list give them."""
    flags = ((Role.OPERATOR, is_operator), (Role.APPROVER, is_approver))
    return frozenset(role for role, on in flags if on)


@dataclass(frozen=True)
class Person:
    id: UserId
    email: str
    display: str
    is_operator: bool
    is_approver: bool
    added_by: UserId
    added_at: datetime
    entra_oid: str | None = None
    bound_at: datetime | None = None
    removed_at: datetime | None = None

    @property
    def on_list(self) -> bool:
        return self.removed_at is None

    @property
    def roles(self) -> frozenset[Role]:
        return roles_from(self.is_operator, self.is_approver)

    @property
    def principal(self) -> Principal:
        return Principal(self.id, self.roles, self.display)


class PeopleRefusal(Enum):
    NOT_AN_OPERATOR = "not_an_operator"
    BAD_EMAIL = "bad_email"
    ALREADY_ON_THE_LIST = "already_on_the_list"
    NO_ROLE = "no_role"
    OWN_OPERATOR_ROLE = "own_operator_role"
    LAST_OPERATOR = "last_operator"
    TWO_APPROVERS = "two_approvers"
    ALREADY_AN_APPROVER = "already_an_approver"
    ALREADY_ASKED = "already_asked"
    CONFIRMATION_WAITING = "confirmation_waiting"
    YOURSELF = "yourself"


REFUSAL_MESSAGES: dict[PeopleRefusal, str] = {
    PeopleRefusal.NOT_AN_OPERATOR: "Only an Operator can change people and roles.",
    PeopleRefusal.BAD_EMAIL: "Enter a work email address.",
    PeopleRefusal.ALREADY_ON_THE_LIST: "Someone with this email is already on the list.",
    PeopleRefusal.NO_ROLE: "Everyone needs at least one role.",
    PeopleRefusal.OWN_OPERATOR_ROLE: "You cannot remove your own Operator role.",
    PeopleRefusal.LAST_OPERATOR: "At least one person must stay an Operator.",
    PeopleRefusal.TWO_APPROVERS: (
        "At least two people must stay Approvers, so nobody approves their own work."
    ),
    PeopleRefusal.ALREADY_AN_APPROVER: "This person is already an Approver.",
    PeopleRefusal.ALREADY_ASKED: "An Approver has already been asked to confirm this person.",
    PeopleRefusal.CONFIRMATION_WAITING: (
        "An Approver is still deciding this person's Approver role. Ask them to say not now first."
    ),
    PeopleRefusal.YOURSELF: "You cannot remove yourself from the list.",
}


@dataclass(frozen=True)
class Refused:
    reason: PeopleRefusal

    @property
    def message(self) -> str:
        return REFUSAL_MESSAGES[self.reason]


@dataclass(frozen=True)
class Changed:
    person: Person
    summary: str | None
    """None when nothing changed, so the history gets no line."""


@dataclass(frozen=True)
class Added:
    person: Person
    summary: str
    ask_approver: bool


def on_list(people: Iterable[Person]) -> list[Person]:
    return [p for p in people if p.on_list]


def operators(people: Iterable[Person]) -> list[Person]:
    return [p for p in on_list(people) if p.is_operator]


def approvers(people: Iterable[Person]) -> list[Person]:
    return [p for p in on_list(people) if p.is_approver]


def valid_email(email: str) -> bool:
    local, at, domain = email.partition("@")
    return (
        bool(at)
        and bool(local)
        and "." in domain
        and not domain.startswith(".")
        and not domain.endswith(".")
        and " " not in email
        and len(email) <= MAX_EMAIL_CHARS
    )


def _same_email(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _an_operator(actor: Person) -> Refused | None:
    if not (actor.on_list and actor.is_operator):
        return Refused(PeopleRefusal.NOT_AN_OPERATOR)
    return None


def _role_words(operator: bool, approver: bool) -> str:
    match (operator, approver):
        case (True, True):
            return "Operator and Approver"
        case (True, False):
            return "Operator"
        case _:
            return "Approver"


def add_person(
    actor: Person,
    people: Sequence[Person],
    email: str,
    display: str,
    operator: bool,
    approver: bool,
    now: datetime,
    new_person_id: Callable[[], UserId],
) -> Added | Refused:
    if (refused := _an_operator(actor)) is not None:
        return refused
    email = email.strip()
    display = display.strip()[:MAX_DISPLAY_CHARS]
    if not valid_email(email):
        return Refused(PeopleRefusal.BAD_EMAIL)
    if not display or not (operator or approver):
        return Refused(PeopleRefusal.NO_ROLE)
    existing = next((p for p in people if _same_email(p.email, email)), None)
    if existing is not None and existing.on_list:
        return Refused(PeopleRefusal.ALREADY_ON_THE_LIST)
    if existing is not None:
        person = _restored(existing, email, display, operator, actor, now)
    else:
        person = Person(
            id=new_person_id(),
            email=email,
            display=display,
            is_operator=operator,
            is_approver=False,
            added_by=actor.id,
            added_at=now,
        )
    summary = f"{actor.display} added {display} ({email})"
    if operator:
        summary += " as an Operator"
    if approver:
        summary += (
            f"{' and' if operator else ','} asked to make {display} an Approver. "
            "Another Approver must confirm."
        )
    else:
        summary += "."
    return Added(person, summary, ask_approver=approver)


def _restored(
    removed: Person, email: str, display: str, operator: bool, actor: Person, now: datetime
) -> Person:
    """A removed person back on the list under the same id, unbound, so they sign in afresh."""
    return replace(
        removed,
        email=email,
        display=display,
        is_operator=operator,
        is_approver=False,
        added_by=actor.id,
        added_at=now,
        entra_oid=None,
        bound_at=None,
        removed_at=None,
    )


def set_operator(
    actor: Person, people: Sequence[Person], person: Person, on: bool
) -> Changed | Refused:
    if (refused := _an_operator(actor)) is not None:
        return refused
    if on:
        if person.is_operator:
            return Changed(person, None)
        return Changed(
            replace(person, is_operator=True), f"{actor.display} made {person.display} an Operator."
        )
    if person.id == actor.id:
        return Refused(PeopleRefusal.OWN_OPERATOR_ROLE)
    if not person.is_operator:
        return Changed(person, None)
    if len(operators(people)) - 1 < MIN_OPERATORS:
        return Refused(PeopleRefusal.LAST_OPERATOR)
    if not person.is_approver:
        return Refused(PeopleRefusal.NO_ROLE)
    return Changed(
        replace(person, is_operator=False),
        f"{actor.display} removed {person.display}'s Operator role.",
    )


def ask_approver(
    actor: Person, people: Sequence[Person], person: Person, pending: Iterable[UserId]
) -> Changed | Refused:
    if (refused := _an_operator(actor)) is not None:
        return refused
    if person.is_approver:
        return Refused(PeopleRefusal.ALREADY_AN_APPROVER)
    if person.id in set(pending):
        return Refused(PeopleRefusal.ALREADY_ASKED)
    return Changed(
        person,
        f"{actor.display} asked to make {person.display} an Approver. "
        "Another Approver must confirm.",
    )


def remove_approver(
    actor: Person, people: Sequence[Person], person: Person, pending: Iterable[UserId]
) -> Changed | Refused:
    if (refused := _an_operator(actor)) is not None:
        return refused
    if person.id in set(pending):
        return Refused(PeopleRefusal.CONFIRMATION_WAITING)
    if not person.is_approver:
        return Changed(person, None)
    if len(approvers(people)) - 1 < MIN_APPROVERS:
        return Refused(PeopleRefusal.TWO_APPROVERS)
    if not person.is_operator:
        return Refused(PeopleRefusal.NO_ROLE)
    return Changed(
        replace(person, is_approver=False),
        f"{actor.display} removed {person.display}'s Approver role.",
    )


def remove_person(
    actor: Person, people: Sequence[Person], person: Person, now: datetime
) -> Changed | Refused:
    if (refused := _an_operator(actor)) is not None:
        return refused
    if person.id == actor.id:
        return Refused(PeopleRefusal.YOURSELF)
    if person.is_operator and len(operators(people)) - 1 < MIN_OPERATORS:
        return Refused(PeopleRefusal.LAST_OPERATOR)
    if person.is_approver and len(approvers(people)) - 1 < MIN_APPROVERS:
        return Refused(PeopleRefusal.TWO_APPROVERS)
    return Changed(
        _removed(person, now), f"{actor.display} removed {person.display} from the list."
    )


def drop_if_roleless(person: Person, pending: Iterable[UserId], now: datetime) -> Changed | None:
    if person.roles or not person.on_list or person.id in set(pending):
        return None
    return Changed(
        _removed(person, now),
        f"{person.display} was removed from the list, because {person.display} has no other role.",
    )


def _removed(person: Person, now: datetime) -> Person:
    return replace(
        person,
        is_operator=False,
        is_approver=False,
        entra_oid=None,
        bound_at=None,
        removed_at=now,
    )


def grant_approver(person: Person) -> Person:
    return replace(person, is_approver=True)


def seed_people(seed: Iterable[SeedPerson], now: datetime) -> list[Person]:
    return [
        Person(
            id=s.id,
            email=s.email,
            display=s.display,
            is_operator=Role.OPERATOR in s.roles,
            is_approver=Role.APPROVER in s.roles,
            added_by=DEPLOY,
            added_at=now,
        )
        for s in seed
    ]


def first_people(
    operator: str,
    approvers_named: Sequence[str],
    now: datetime,
    new_person_id: Callable[[], UserId],
) -> list[Person]:
    """The first deploy's people (ADR 0030): one Operator and two different Approvers."""
    emails: list[str] = []
    for email in (operator, *approvers_named):
        if not any(_same_email(email, seen) for seen in emails):
            emails.append(email.strip())
    return [
        Person(
            id=new_person_id(),
            email=email,
            display=display_from_email(email),
            is_operator=_same_email(email, operator),
            is_approver=any(_same_email(email, a) for a in approvers_named),
            added_by=DEPLOY,
            added_at=now,
        )
        for email in emails
    ]


def display_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    words = [w for w in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or email


def seed_summary(people: Sequence[Person]) -> str:
    named = [
        f"{p.display} ({p.email}, {_role_words(p.is_operator, p.is_approver)})" for p in people
    ]
    listed = " and ".join(filter(None, [", ".join(named[:-1]), named[-1]])) if named else ""
    return f"The deploy put {listed} on the list."
