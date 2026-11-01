"""The part of JQL the practice Jira understands (ADR 0035).

Fields: project, key (or issuekey), labels, text, statusCategory and resolutiondate. Operators:
=, !=, in, not in, ~, >=, >, <=, <. Clauses join with AND, and OR inside brackets. One ORDER BY
on created or key. Anything else is refused the way Jira refuses it, with a message naming it.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from platform_api.practice_jira.store import PracticeTicket

type Predicate = Callable[[PracticeTicket], bool]


class JqlError(ValueError):
    """The query is not one the practice Jira understands. The message is Jira's own wording."""


@dataclass(frozen=True)
class Query:
    where: Predicate
    order: str
    descending: bool
    keys: tuple[str, ...]
    """Every key the query names with key = or key in, which must exist, as in Jira."""


_TOKEN = re.compile(
    r'\s*(?:(?P<string>"(?:[^"\\]|\\.)*")|(?P<op>!=|>=|<=|~|=|>|<|\(|\)|,)|(?P<word>[^\s"(),=!~<>]+))'
)
_CATEGORIES = {
    "done": "Done",
    "to do": "To Do",
    "new": "To Do",
    "in progress": "To Do",
    "indeterminate": "To Do",
}
_DAY = re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?: (\d{1,2}):(\d{2}))?$")


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    at = 0
    while at < len(text):
        if text[at:].strip() == "":
            break
        match = _TOKEN.match(text, at)
        if match is None or match.end() == at:
            raise JqlError(
                f"Error in the JQL Query: the character at position {at} is not allowed."
            )
        tokens.append(match.group(0).strip())
        at = match.end()
    return tokens


def _value(token: str) -> str:
    if token.startswith('"'):
        return re.sub(r"\\(.)", r"\1", token[1:-1])
    return token


def _when(text: str) -> datetime:
    match = _DAY.match(text)
    if match is None:
        raise JqlError(f"Date value '{text}' for field 'resolutiondate' is invalid.")
    year, month, day, hour, minute = match.groups()
    at = time(int(hour or 0), int(minute or 0))
    return datetime.combine(date(int(year), int(month), int(day)), at, UTC)


class _Parser:
    def __init__(self, text: str) -> None:
        self._tokens = _tokens(text)
        self._at = 0
        self.keys: list[str] = []

    def _peek(self) -> str | None:
        return self._tokens[self._at] if self._at < len(self._tokens) else None

    def _next(self) -> str:
        token = self._peek()
        if token is None:
            raise JqlError("Error in the JQL Query: Expecting more of the query.")
        self._at += 1
        return token

    def _keyword(self, word: str) -> bool:
        token = self._peek()
        if token is not None and token.lower() == word:
            self._at += 1
            return True
        return False

    def parse(self) -> Query:
        where: Predicate = lambda _: True  # noqa: E731
        if self._peek() is not None and (self._peek() or "").lower() != "order":
            where = self._and()
        order, descending = "created", True
        if self._keyword("order"):
            if not self._keyword("by"):
                raise JqlError("Error in the JQL Query: Expecting 'by' after 'order'.")
            order = self._next().lower()
            if order not in {"created", "key"}:
                raise JqlError(f"Not able to sort using field '{order}'.")
            descending = not self._keyword("asc")
            self._keyword("desc")
        if self._peek() is not None:
            raise JqlError(f"Error in the JQL Query: '{self._peek()}' was not expected here.")
        return Query(where, order, descending, tuple(self.keys))

    def _and(self) -> Predicate:
        parts = [self._term()]
        while self._keyword("and"):
            parts.append(self._term())
        return lambda ticket: all(part(ticket) for part in parts)

    def _term(self) -> Predicate:
        if self._peek() == "(":
            self._next()
            parts = [self._and()]
            while self._keyword("or"):
                parts.append(self._and())
            if self._next() != ")":
                raise JqlError("Error in the JQL Query: Expecting ')'.")
            return lambda ticket: any(part(ticket) for part in parts)
        return self._clause()

    def _list(self) -> list[str]:
        if self._next() != "(":
            raise JqlError("Error in the JQL Query: Expecting '(' after 'in'.")
        values = [_value(self._next())]
        while self._peek() == ",":
            self._next()
            values.append(_value(self._next()))
        if self._next() != ")":
            raise JqlError("Error in the JQL Query: Expecting ')'.")
        return values

    def _clause(self) -> Predicate:
        name = self._next().lower()
        negated = False
        if self._keyword("not"):
            negated = True
            if not self._keyword("in"):
                raise JqlError("Error in the JQL Query: Expecting 'in' after 'not'.")
            op = "in"
        elif self._keyword("in"):
            op = "in"
        else:
            op = self._next()
        values = self._list() if op == "in" else [_value(self._next())]
        match name, op:
            case "project", "=" | "!=" | "in":
                wanted = {value.upper() for value in values}
                test: Predicate = lambda t: t.project in wanted  # noqa: E731
            case (("key" | "issuekey"), "=" | "!=" | "in"):
                self.keys.extend(value.upper() for value in values)
                keys = {value.upper() for value in values}
                test = lambda t: t.key in keys  # noqa: E731
            case "labels", "=" | "!=" | "in":
                labels = set(values)
                test = lambda t: bool(labels.intersection(t.labels))  # noqa: E731
            case "text", "~":
                needle = values[0].casefold()
                test = lambda t: needle in t.title.casefold() or needle in t.body.casefold()  # noqa: E731
            case "statuscategory", "=" | "!=" | "in":
                try:
                    statuses = {_CATEGORIES[value.lower()] for value in values}
                except KeyError as unknown:
                    raise JqlError(
                        f"The value '{unknown.args[0]}' does not exist for the field "
                        "'statusCategory'."
                    ) from None
                test = lambda t: t.status in statuses  # noqa: E731
            case "resolutiondate", ">=" | ">" | "<=" | "<":
                return _dated(op, _when(values[0]))
            case (("project" | "key" | "issuekey" | "labels" | "text" | "statuscategory"), _):
                raise JqlError(f"The operator '{op}' is not supported by the '{name}' field.")
            case _:
                raise JqlError(
                    f"Field '{name}' does not exist or you do not have permission to view it."
                )
        if op == "!=" or negated:
            return lambda ticket: not test(ticket)
        return test


def _dated(op: str, at: datetime) -> Predicate:
    def test(ticket: PracticeTicket) -> bool:
        done = ticket.done_at
        if done is None:
            return False
        match op:
            case ">=":
                return done >= at
            case ">":
                return done > at
            case "<=":
                return done <= at
            case _:
                return done < at

    return test


def parse(text: str) -> Query:
    return _Parser(text).parse()


def ordered(tickets: Sequence[PracticeTicket], query: Query) -> list[PracticeTicket]:
    if query.order == "key":
        key: Callable[[PracticeTicket], tuple[object, ...]] = lambda t: (t.project, t.number)  # noqa: E731
    else:
        key = lambda t: (t.created_at, t.number)  # noqa: E731
    return sorted(tickets, key=key, reverse=query.descending)
