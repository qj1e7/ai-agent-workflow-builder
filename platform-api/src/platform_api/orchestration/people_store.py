import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from platform_api.db import Database, UnitOfWork
from platform_api.orchestration import people as rules
from platform_api.orchestration.confirmations import (
    Confirmation,
    ConfirmationDecision,
    ConfirmationId,
    ConfirmationKind,
    ConfirmationStore,
    DecideRefusal,
    DecideRefused,
    SettingsChange,
    decide,
    digest_of,
    why_not,
)
from platform_api.orchestration.people import Changed, Person, Refused
from platform_api.settings import FirstPeople
from platform_api.shared import (
    DevIdentity,
    ExternalIdentity,
    Identity,
    Principal,
    Role,
    SeedPerson,
    UserId,
    new_id,
)

log = logging.getLogger(__name__)

_COLUMNS = (
    "id, entra_oid, email, display, is_operator, is_approver, added_by, added_at, "
    "bound_at, removed_at"
)


def _person(row: Mapping[str, Any]) -> Person:
    return Person(
        id=UserId(row["id"]),
        email=row["email"],
        display=row["display"],
        is_operator=row["is_operator"],
        is_approver=row["is_approver"],
        added_by=UserId(row["added_by"]),
        added_at=row["added_at"],
        entra_oid=row["entra_oid"],
        bound_at=row["bound_at"],
        removed_at=row["removed_at"],
    )


def new_person_id() -> UserId:
    return UserId(new_id("per"))


class PeopleStore:
    async def lock(self, uow: UnitOfWork) -> None:
        """Serializes changes to people and roles. Plain reads, such as sign-in, are not held up."""
        await uow.conn.execute("LOCK TABLE orchestration.people IN SHARE ROW EXCLUSIVE MODE")

    async def all(self, uow: UnitOfWork) -> list[Person]:
        rows = await (
            await uow.conn.execute(
                f"SELECT {_COLUMNS} FROM orchestration.people ORDER BY added_at, id"
            )
        ).fetchall()
        return [_person(r) for r in rows]

    async def count(self, uow: UnitOfWork) -> int:
        row = await (await uow.conn.execute("SELECT count(*) FROM orchestration.people")).fetchone()
        assert row is not None
        return int(row["count"])

    async def get(self, uow: UnitOfWork, person_id: str) -> Person | None:
        row = await (
            await uow.conn.execute(
                f"SELECT {_COLUMNS} FROM orchestration.people WHERE id = %s", (person_id,)
            )
        ).fetchone()
        return _person(row) if row is not None else None

    async def by_oid(self, uow: UnitOfWork, oid: str) -> Person | None:
        row = await (
            await uow.conn.execute(
                f"SELECT {_COLUMNS} FROM orchestration.people WHERE entra_oid = %s", (oid,)
            )
        ).fetchone()
        return _person(row) if row is not None else None

    async def insert(self, uow: UnitOfWork, person: Person) -> None:
        await uow.conn.execute(
            "INSERT INTO orchestration.people (id, entra_oid, email, display, is_operator, "
            "is_approver, added_by, added_at, bound_at, removed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                person.id,
                person.entra_oid,
                person.email,
                person.display,
                person.is_operator,
                person.is_approver,
                person.added_by,
                person.added_at,
                person.bound_at,
                person.removed_at,
            ),
        )

    async def save(self, uow: UnitOfWork, person: Person) -> None:
        await uow.conn.execute(
            "UPDATE orchestration.people SET email = %s, display = %s, is_operator = %s, "
            "is_approver = %s, added_by = %s, added_at = %s, entra_oid = %s, bound_at = %s, "
            "removed_at = %s WHERE id = %s",
            (
                person.email,
                person.display,
                person.is_operator,
                person.is_approver,
                person.added_by,
                person.added_at,
                person.entra_oid,
                person.bound_at,
                person.removed_at,
                person.id,
            ),
        )

    async def bind(self, uow: UnitOfWork, identity: ExternalIdentity) -> Person | None:
        """First sign-in: binds the one unbound record whose email is the token's user name,
        ignoring case, or returns the record another request bound a moment ago. A bound record
        is never rebound, and the name the Operator entered stays (ADR 0029)."""
        try:
            async with uow.conn.transaction():
                row = await (
                    await uow.conn.execute(
                        "UPDATE orchestration.people SET entra_oid = %s, bound_at = %s "
                        "WHERE lower(email) = lower(%s) AND entra_oid IS NULL "
                        f"AND removed_at IS NULL RETURNING {_COLUMNS}",
                        (identity.subject, uow.now, identity.user_name),
                    )
                ).fetchone()
        except psycopg.errors.UniqueViolation:
            return await self.by_oid(uow, identity.subject)
        return _person(row) if row is not None else None

    async def mark_signed_in(self, uow: UnitOfWork, person_id: UserId) -> None:
        await uow.conn.execute(
            "UPDATE orchestration.people SET bound_at = %s WHERE id = %s AND bound_at IS NULL",
            (uow.now, person_id),
        )

    async def roles_now(self, uow: UnitOfWork, person_id: UserId) -> frozenset[Role] | None:
        """The person's roles at this moment, held against a change until the transaction ends.
        None when they are not on the list."""
        row = await (
            await uow.conn.execute(
                "SELECT is_operator, is_approver FROM orchestration.people "
                "WHERE id = %s AND removed_at IS NULL FOR SHARE",
                (person_id,),
            )
        ).fetchone()
        if row is None:
            return None
        roles: set[Role] = set()
        if row["is_operator"]:
            roles.add(Role.OPERATOR)
        if row["is_approver"]:
            roles.add(Role.APPROVER)
        return frozenset(roles)


@dataclass(frozen=True)
class NotFound:
    pass


@dataclass(frozen=True)
class ModelAddress:
    """The confirmation is about the AI model's address, which ModelSettings decides."""

    confirmation: Confirmation


@dataclass(frozen=True)
class PersonRow:
    person: Person
    pending: Confirmation | None


@dataclass(frozen=True)
class ConfirmationRow:
    confirmation: Confirmation
    asked_by_name: str
    about: Person | None
    why_not: DecideRefusal | None


@dataclass(frozen=True)
class Decided:
    confirmation: Confirmation
    person: Person


@dataclass(frozen=True)
class HistoryLine:
    change: SettingsChange
    changed_by_name: str | None
    confirmed_by_name: str | None


type ChangeResult = Person | Refused | NotFound
type Rule = Callable[
    [Person, Sequence[Person], Person, frozenset[UserId], datetime], Changed | Refused
]
type DecideResult = Decided | DecideRefused | ModelAddress | NotFound


class People:
    """The People list: who may sign in, and who holds which role (ADR 0029)."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._store = PeopleStore()
        self._confirmations = ConfirmationStore()

    async def resolve(self, identity: Identity) -> Principal | None:
        async with self._db.transaction("orchestration") as uow:
            match identity:
                case DevIdentity(person_id):
                    person = await self._store.get(uow, person_id)
                    if person is None or not person.on_list:
                        return None
                    if person.bound_at is None:
                        await self._store.mark_signed_in(uow, person.id)
                    return person.principal
                case ExternalIdentity():
                    person = await self._store.by_oid(uow, identity.subject)
                    if person is None and identity.user_name:
                        person = await self._store.bind(uow, identity)
                    if person is None or not person.on_list:
                        return None
                    return person.principal

    async def person(self, person_id: UserId) -> Principal | None:
        async with self._db.transaction("orchestration") as uow:
            person = await self._store.get(uow, person_id)
        return person.principal if person is not None and person.on_list else None

    async def listed(self) -> list[Principal]:
        async with self._db.transaction("orchestration") as uow:
            return [p.principal for p in rules.on_list(await self._store.all(uow))]

    async def roles_now(self, uow: UnitOfWork, person_id: UserId) -> frozenset[Role] | None:
        return await self._store.roles_now(uow, person_id)

    async def seed_dev(self, seed: Sequence[SeedPerson]) -> bool:
        return await self._seed(lambda now: rules.seed_people(seed, now))

    async def seed_first(self, first: FirstPeople | None) -> bool:
        if first is None:
            async with self._db.transaction("orchestration") as uow:
                empty = await self._store.count(uow) == 0
            if empty:
                log.warning(
                    "The People list is empty and FIRST_OPERATOR and FIRST_APPROVERS are not "
                    "set. Nobody can sign in until they are set and platform-api restarts."
                )
            return False
        return await self._seed(
            lambda now: rules.first_people(first.operator, first.approvers, now, new_person_id)
        )

    async def _seed(self, build: Callable[[datetime], list[Person]]) -> bool:
        async with self._db.transaction("orchestration") as uow:
            await self._store.lock(uow)
            if await self._store.count(uow) > 0:
                return False
            people = build(uow.now)
            for person in people:
                await self._store.insert(uow, person)
            await self._confirmations.record_change(
                uow, "people", rules.DEPLOY, rules.seed_summary(people)
            )
            log.info("Seeded the People list with %d people", len(people))
            return True

    async def list_people(self) -> list[PersonRow]:
        async with self._db.transaction("orchestration") as uow:
            people = rules.on_list(await self._store.all(uow))
            pending = {
                c.about: c
                for c in await self._confirmations.open_ones(uow)
                if c.kind is ConfirmationKind.APPROVER
            }
        return [PersonRow(p, pending.get(p.id)) for p in people]

    async def add(
        self, actor: Principal, email: str, display: str, operator: bool, approver: bool
    ) -> PersonRow | Refused:
        async with self._db.transaction("orchestration") as uow:
            await self._store.lock(uow)
            people = await self._store.all(uow)
            me = _actor(people, actor)
            outcome = rules.add_person(
                me, people, email, display, operator, approver, uow.now, new_person_id
            )
            if isinstance(outcome, Refused):
                return outcome
            person = outcome.person
            if any(p.id == person.id for p in people):
                await self._store.save(uow, person)
            else:
                await self._store.insert(uow, person)
            confirmation = None
            if outcome.ask_approver:
                confirmation = await self._ask(uow, me, person)
            await self._confirmations.record_change(
                uow,
                "people",
                me.id,
                outcome.summary,
                confirmation_id=confirmation.id if confirmation else None,
            )
            return PersonRow(person, confirmation)

    async def set_operator(self, actor: Principal, person_id: str, on: bool) -> ChangeResult:
        return await self._change(
            actor,
            person_id,
            lambda me, people, person, _, __: rules.set_operator(me, people, person, on),
        )

    async def ask_approver(
        self, actor: Principal, person_id: str
    ) -> PersonRow | Refused | NotFound:
        async with self._db.transaction("orchestration") as uow:
            await self._store.lock(uow)
            people = await self._store.all(uow)
            me = _actor(people, actor)
            person = _target(people, person_id)
            if person is None:
                return NotFound()
            outcome = rules.ask_approver(me, people, person, await self._pending(uow))
            if isinstance(outcome, Refused):
                return outcome
            confirmation = await self._ask(uow, me, person)
            assert outcome.summary is not None
            await self._confirmations.record_change(
                uow, "people", me.id, outcome.summary, confirmation_id=confirmation.id
            )
            return PersonRow(person, confirmation)

    async def remove_approver(self, actor: Principal, person_id: str) -> ChangeResult:
        return await self._change(
            actor,
            person_id,
            lambda me, people, person, pending, _: rules.remove_approver(
                me, people, person, pending
            ),
        )

    async def remove(self, actor: Principal, person_id: str) -> ChangeResult:
        async with self._db.transaction("orchestration") as uow:
            await self._store.lock(uow)
            people = await self._store.all(uow)
            me = _actor(people, actor)
            person = _target(people, person_id)
            if person is None:
                return NotFound()
            outcome = rules.remove_person(me, people, person, uow.now)
            if isinstance(outcome, Refused):
                return outcome
            assert outcome.summary is not None
            await self._store.save(uow, outcome.person)
            for closed in await self._confirmations.close_about(uow, person.id, me.id):
                await self._confirmations.record_change(
                    uow,
                    "people",
                    closed.asked_by,
                    f"The request to make {person.display} an Approver was closed, because "
                    f"{me.display} removed {person.display} from the list.",
                    confirmed_by=me.id,
                    confirmation_id=closed.id,
                )
            await self._confirmations.record_change(uow, "people", me.id, outcome.summary)
            return outcome.person

    async def _change(self, actor: Principal, person_id: str, rule: Rule) -> ChangeResult:
        async with self._db.transaction("orchestration") as uow:
            await self._store.lock(uow)
            people = await self._store.all(uow)
            me = _actor(people, actor)
            person = _target(people, person_id)
            if person is None:
                return NotFound()
            outcome = rule(me, people, person, await self._pending(uow), uow.now)
            if isinstance(outcome, Refused):
                return outcome
            if outcome.summary is None:
                return outcome.person
            await self._store.save(uow, outcome.person)
            await self._confirmations.record_change(uow, "people", me.id, outcome.summary)
            return outcome.person

    async def _pending(self, uow: UnitOfWork) -> frozenset[UserId]:
        return frozenset(
            c.about
            for c in await self._confirmations.open_ones(uow)
            if c.kind is ConfirmationKind.APPROVER and c.about is not None
        )

    async def _ask(self, uow: UnitOfWork, asker: Person, about: Person) -> Confirmation:
        change = {
            "person_id": about.id,
            "email": about.email,
            "display": about.display,
            "role": "approver",
            "added_at": about.added_at.isoformat(),
        }
        return await self._confirmations.ask(
            uow,
            Confirmation(
                id=ConfirmationId(new_id("cfm")),
                kind=ConfirmationKind.APPROVER,
                about=about.id,
                change=change,
                digest=digest_of(ConfirmationKind.APPROVER, about.id, asker.id, uow.now, change),
                asked_by=asker.id,
                asked_at=uow.now,
            ),
        )

    async def confirmations(self, viewer: Principal) -> list[ConfirmationRow]:
        async with self._db.transaction("orchestration") as uow:
            people = {p.id: p for p in await self._store.all(uow)}
            open_ones = await self._confirmations.open_ones(uow)
        rows: list[ConfirmationRow] = []
        for c in open_ones:
            about = people.get(c.about) if c.about is not None else None
            if c.about is not None and (about is None or not about.on_list):
                continue
            reason = why_not(
                c,
                viewer,
                about_added_at=about.added_at if about is not None else None,
                asker_is_operator=_asker_is_operator(people, c),
            )
            rows.append(ConfirmationRow(c, _name(people, c.asked_by), about, reason))
        return rows

    async def confirmation(self, confirmation_id: str) -> Confirmation | None:
        async with self._db.transaction("orchestration") as uow:
            return await self._confirmations.load(uow, confirmation_id)

    async def decide(
        self,
        decider: Principal,
        confirmation_id: str,
        decision: ConfirmationDecision,
        seen_digest: str,
    ) -> DecideResult:
        async with self._db.transaction("orchestration") as uow:
            await self._store.lock(uow)
            confirmation = await self._confirmations.load(uow, confirmation_id, lock=True)
            if confirmation is None:
                return NotFound()
            if confirmation.kind is ConfirmationKind.MODEL_ADDRESS:
                return ModelAddress(confirmation)
            people = await self._store.all(uow)
            me = _target(people, decider.user_id)
            fresh = (
                me.principal
                if me is not None
                else Principal(decider.user_id, frozenset(), decider.display)
            )
            about = next((p for p in people if p.id == confirmation.about), None)
            outcome = decide(
                confirmation,
                fresh,
                decision,
                seen_digest,
                uow.now,
                about_on_list=about is not None and about.on_list,
                about_added_at=about.added_at if about is not None else None,
                asker_is_operator=_asker_is_operator({p.id: p for p in people}, confirmation),
            )
            if isinstance(outcome, DecideRefused):
                return outcome
            assert about is not None
            if not await self._confirmations.record_decision(uow, outcome):
                return DecideRefused(DecideRefusal.ALREADY_DECIDED)
            asked_by = _name(dict((p.id, p) for p in people), confirmation.asked_by)
            if decision is ConfirmationDecision.CONFIRMED:
                about = rules.grant_approver(about)
                await self._store.save(uow, about)
                summary = (
                    f"{fresh.display} confirmed {about.display} as an Approver, "
                    f"as {asked_by} asked."
                )
            else:
                summary = (
                    f"{fresh.display} said not now to making {about.display} an Approver, "
                    f"as {asked_by} asked."
                )
            await self._confirmations.record_change(
                uow,
                "people",
                confirmation.asked_by,
                summary,
                confirmed_by=fresh.user_id,
                confirmation_id=confirmation.id,
            )
            return Decided(outcome, about)

    async def history(self, limit: int) -> list[HistoryLine]:
        async with self._db.transaction("orchestration") as uow:
            people = {p.id: p for p in await self._store.all(uow)}
            changes = await self._confirmations.changes(uow, limit=limit)
        return [
            HistoryLine(
                c,
                people[c.changed_by].display if c.changed_by in people else None,
                people[c.confirmed_by].display
                if c.confirmed_by is not None and c.confirmed_by in people
                else None,
            )
            for c in changes
        ]


def _actor(people: Sequence[Person], actor: Principal) -> Person:
    """The actor's row as it is now, so a role lost a moment ago counts. Someone no longer on the
    list is treated as having no role."""
    me = next((p for p in people if p.id == actor.user_id and p.on_list), None)
    if me is not None:
        return me
    return Person(
        id=actor.user_id,
        email="",
        display=actor.display,
        is_operator=False,
        is_approver=False,
        added_by=actor.user_id,
        added_at=datetime.min,
    )


def _target(people: Sequence[Person], person_id: str) -> Person | None:
    return next((p for p in people if p.id == person_id and p.on_list), None)


def _asker_is_operator(people: Mapping[UserId, Person], confirmation: Confirmation) -> bool:
    if confirmation.kind is not ConfirmationKind.APPROVER:
        return True
    asker = people.get(confirmation.asked_by)
    return asker is not None and asker.on_list and asker.is_operator


def _name(people: Mapping[UserId, Person], person_id: UserId) -> str:
    if person_id == rules.DEPLOY:
        return "the deploy"
    person = people.get(person_id)
    return person.display if person is not None else person_id
