"""The cert list parser: Qingtao's `n8n-project/scripts/parse-build.js`, ported line for line.

It reads the certificate list on a Confluence page: the first table with a VALIDITY END column,
each row's date read the way a person reads it, and the rows sorted into what the team must act on
and what a person must check first. It builds the Teams card and the email of the cert reminder.
The rules, the words, the knobs and the row caps are his. Only what the n8n Code node took from
its own settings is a parameter here: the page's address, who is emailed and the channel's name.

His rules are kept as he wrote them, quirks included, so a list reads the same before and after
the move. One example: a cell that has "na" anywhere in it, as in "pending finance", reads as a
certificate that never expires. `tests/test_cert_list.py` holds his test and compares this port
with his script's own output.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

WARN_DAYS: Final = 60
"""The "needs action" window, in days."""
NEAR_DAYS: Final = 30
"""The second band on the card."""
STALE_AFTER_DAYS: Final = 365
"""A certificate that ran out longer ago than this is a stale row, not a renewal task."""
TIME_ZONE: Final = ZoneInfo("Asia/Singapore")
MAX_LIST_PER_ENV: Final = 10
"""Rows per environment on the card."""
MAX_ROWS_PER_SECTION: Final = 20
"""Rows per section in the email."""
STALE_KEPT: Final = 20
"""Stale rows kept in the result, as his output keeps them."""
CELL_KEPT: Final = 140
NO_ENV: Final = "(no env)"
CHANNEL: Final = "cert-expiry-reminder"

ACTION_STEPS: Final = (
    "Book the renewal / re-certification before the validity end date.",
    "Once renewed, update the VALIDITY END cell on the Cert List page (write the new date, not "
    'just "renewed").',
    "If you cannot renew in time, reply in the Teams thread with the reason and a committed target "
    "date.",
    "Fill in ENV and remove duplicate rows so the next run can post them as confirmed.",
)

type Bucket = Literal["no-environment", "unreadable-date", "expired-long-ago", "duplicate-row"]
type Basis = Literal["renewal date", "last date in cell", "as written"]
type Undated = Literal["empty", "no-expiry", "stored-elsewhere", "unreadable"]


class CertListError(Exception):
    """The page holds no list the parser can read. The message is his."""


@dataclass(frozen=True)
class Where:
    """What the n8n Code node had in its own settings: the page's address for the card's button
    and the email's link, who the email goes to, in words, and the Teams channel's name."""

    page_url: str
    email_to: str = "the team's list"
    channel: str = CHANNEL


# ── Confluence storage format → rows of plain text cells ──────────────────────────────────────

_TIME: Final = re.compile(r'<time[^>]*datetime="([^"]+)"', re.IGNORECASE)
_BREAK: Final = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG: Final = re.compile(r"<[^>]+>")
_SPACES: Final = re.compile(r"\s+")
_TABLE: Final = re.compile(r"<table[^>]*>([\s\S]*?)</table>", re.IGNORECASE)
_ROW: Final = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
_CELL: Final = re.compile(r"<t[hd][^>]*>([\s\S]*?)</t[hd]>", re.IGNORECASE)


def decode_entities(text: str) -> str:
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
    )


def cell_text(cell_html: str) -> str:
    time = _TIME.search(cell_html)
    if time:
        return time.group(1).strip()
    plain = decode_entities(_TAG.sub(" ", _BREAK.sub(" ", cell_html)))
    return _SPACES.sub(" ", plain).strip()


def extract_tables(html: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for table in _TABLE.finditer(html):
        rows: list[list[str]] = []
        for row in _ROW.finditer(table.group(1)):
            cells = [cell_text(cell.group(1)) for cell in _CELL.finditer(row.group(1))]
            if any(cell != "" for cell in cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


# ── Dates ─────────────────────────────────────────────────────────────────────────────────────

MONTHS: Final = {
    **dict.fromkeys(("jan", "january"), 0),
    **dict.fromkeys(("feb", "february"), 1),
    **dict.fromkeys(("mar", "march"), 2),
    **dict.fromkeys(("apr", "april"), 3),
    "may": 4,
    **dict.fromkeys(("jun", "june"), 5),
    **dict.fromkeys(("jul", "july"), 6),
    **dict.fromkeys(("aug", "august"), 7),
    **dict.fromkeys(("sep", "sept", "september"), 8),
    **dict.fromkeys(("oct", "october"), 9),
    **dict.fromkeys(("nov", "november"), 10),
    **dict.fromkeys(("dec", "december"), 11),
}
SHORT_MONTHS: Final = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec",
)  # fmt: skip
"""Months as JavaScript's en-GB formatter writes them, September included."""


def _month(name: str) -> int | None:
    found = MONTHS.get(name.lower())
    return found if found is not None else MONTHS.get(name[:3].lower())


def _full_year(year: int) -> int:
    return 2000 + year if year < 100 else year


def utc_day(year: int, month: int, day: int) -> date | None:
    """A day as JavaScript's Date.UTC makes it: a year from 0 to 99 is in the 1900s, and a month
    or a day past its end runs on into the next one, so 31 February is 3 March."""
    if 0 <= year <= 99:
        year += 1900
    year += month // 12
    try:
        return date(year, month % 12 + 1, 1) + timedelta(days=day - 1)
    except ValueError, OverflowError:
        return None


_DATE_ALT: Final = "|".join(
    (
        r"[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}",
        r"[0-9]{1,2}\s*[/.-]\s*[0-9]{1,2}\s*[/.-]\s*[0-9]{2,4}",
        r"[0-9]{1,2}\s+[A-Za-z]{3,9}\.?,?\s+[0-9]{2,4}",
        r"[0-9]{1,2}\s*[/.-]\s*[A-Za-z]{3,9}\.?\s*[/.-]?\s*[0-9]{2,4}",
        r"[A-Za-z]{3,9}\.?\s+[0-9]{1,2},?\s+[0-9]{4}",
    )
)
_DATE: Final = re.compile(f"({_DATE_ALT})", re.IGNORECASE)
_RENEWED: Final = re.compile(
    rf"renew[A-Za-z0-9_]*\s*(?:on|:|-)?\s*(?:on\s*)?({_DATE_ALT})", re.IGNORECASE
)
_ISO: Final = re.compile(r"([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})")
_DAY_FIRST: Final = re.compile(r"([0-9]{1,2})\s*[/.-]\s*([0-9]{1,2})\s*[/.-]\s*([0-9]{2,4})")
_DAY_MONTH: Final = re.compile(
    r"([0-9]{1,2})\s*[/.-]?\s*([A-Za-z]{3,9})\.?\s*[/.-]?\s*([0-9]{2,4})"
)
_MONTH_DAY: Final = re.compile(r"([A-Za-z]{3,9})\.?\s+([0-9]{1,2}),?\s*([0-9]{4})")
_NO_EXPIRY: Final = re.compile(
    r"never\s*expir|no\s*expir|not\s*using\s*cert|no\s*cert|n/?a|not\s+applicable|permanent|"
    r"static\s*key|public\s*key",
    re.IGNORECASE,
)
_ELSEWHERE: Final = re.compile(
    r"ssm\s*param|parameter\s*store|keycloak|imperva|acm|vault|portal|store|dosarrest|"
    r"api\s*gateway",
    re.IGNORECASE,
)


def _one_spaced(text: str) -> str:
    return _SPACES.sub(" ", text)


def parse_one(raw: str) -> date | None:
    text = _one_spaced(raw).strip()
    if m := _ISO.fullmatch(text):
        return utc_day(int(m[1]), int(m[2]) - 1, int(m[3]))
    if m := _DAY_FIRST.fullmatch(text):
        return utc_day(_full_year(int(m[3])), int(m[2]) - 1, int(m[1]))
    if (m := _DAY_MONTH.fullmatch(text)) and (month := _month(m[2])) is not None:
        return utc_day(_full_year(int(m[3])), month, int(m[1]))
    if (m := _MONTH_DAY.fullmatch(text)) and (month := _month(m[1])) is not None:
        return utc_day(int(m[3]), month, int(m[2]))
    return None


@dataclass(frozen=True)
class Dated:
    day: date
    basis: Basis
    used: str


def read_validity_end(cell: str) -> Dated | Undated:
    """Reads the cell like a human: "renewed on X" wins, otherwise the last date written."""
    text = cell.strip()
    if not text:
        return "empty"
    if _NO_EXPIRY.search(text):
        return "no-expiry"
    dates = [
        (day, _one_spaced(m[0]).strip())
        for m in _DATE.finditer(text)
        if (day := parse_one(_one_spaced(m[0]))) is not None
    ]
    if not dates:
        return "stored-elsewhere" if _ELSEWHERE.search(text) else "unreadable"
    renewed = _RENEWED.search(text)
    if renewed and renewed[1]:
        day = parse_one(_one_spaced(renewed[1]))
        if day is not None:
            return Dated(day, "renewal date", _one_spaced(renewed[1]).strip())
    last_day, last_raw = dates[-1]
    return Dated(last_day, "last date in cell" if len(dates) > 1 else "as written", last_raw)


def short_date(day: date) -> str:
    return f"{day.day:02d} {SHORT_MONTHS[day.month - 1]} {day.year}"


def checked_words(now: datetime) -> str:
    """When the list was checked, as JavaScript's en-GB medium date and short time write it."""
    local = now.astimezone(TIME_ZONE)
    return f"{local.day} {SHORT_MONTHS[local.month - 1]} {local.year}, {local:%H:%M}"


def locale_order(text: str) -> tuple[tuple[tuple[int, str], ...], tuple[bool, ...]]:
    """A sort key close to JavaScript's localeCompare: marks before digits before letters, case
    ignored, then lower case before upper case."""
    first = tuple((2 if ch.isalpha() else 1 if ch.isdigit() else 0, ch.casefold()) for ch in text)
    return first, tuple(ch.isupper() for ch in text)


# ── The rows ──────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Untracked:
    """A row whose cell gives no date: no expiry, kept elsewhere, or unreadable."""

    env: str
    name: str
    raw_end: str


@dataclass(frozen=True)
class Cert:
    """A row with a date read from its cell."""

    env: str
    name: str
    validity_end: str
    days_left: int
    basis: Basis
    raw_end: str

    @property
    def marker(self) -> str:
        if self.days_left < 0:
            return "🔴"
        return "🟠" if self.days_left <= NEAR_DAYS else "🟡"

    @property
    def key(self) -> str:
        return f"{self.env}|{self.name}|{self.validity_end}"


@dataclass(frozen=True)
class NeedsRow:
    """One row for a person to look at, flat, for the optional AI step."""

    id: str
    bucket: Bucket
    env: str
    name: str
    cell: str


def _plain(item: Cert | Untracked) -> dict[str, Any]:
    if isinstance(item, Untracked):
        return {"env": item.env, "name": item.name, "raw_end": item.raw_end}
    return {
        "env": item.env,
        "name": item.name,
        "validity_end": item.validity_end,
        "days_left": item.days_left,
        "basis": item.basis,
        "raw_end": item.raw_end,
        "marker": item.marker,
    }


def _merged(items: Sequence[Cert], duplicates: list[Cert]) -> list[Cert]:
    """Merges identical rows, walking from the end as his keepFirst does. The removed ones go to
    `duplicates`, as evidence for a person to confirm."""
    seen: set[str] = set()
    kept: list[Cert] = []
    for item in reversed(items):
        if item.key in seen:
            duplicates.append(item)
        else:
            seen.add(item.key)
            kept.append(item)
    return sorted(reversed(kept), key=lambda item: item.days_left)


def _at(row: Sequence[str], index: int) -> str:
    return row[index] if 0 <= index < len(row) else ""


# ── The report ────────────────────────────────────────────────────────────────────────────────


def _esc(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cut(text: object, length: int) -> str:
    return _esc(str(text)[:length])


def _color_of(days: int) -> str:
    if days < 0:
        return "Attention"
    return "Warning" if days <= NEAR_DAYS else "Default"


def _chip_of(days: int) -> str:
    if days < 0:
        return f"{abs(days)}d overdue"
    return "today" if days == 0 else f"in {days}d"


def _stat_column(label: str, value: int, color: str) -> dict[str, Any]:
    return {
        "type": "Column",
        "width": 1,
        "horizontalAlignment": "Center",
        "items": [
            {
                "type": "TextBlock",
                "text": str(value),
                "size": "Large",
                "weight": "Bolder",
                "color": color,
                "horizontalAlignment": "Center",
            },
            {
                "type": "TextBlock",
                "text": label,
                "size": "Micro",
                "isSubtle": True,
                "horizontalAlignment": "Center",
                "wrap": True,
            },
        ],
    }


def _row_set(item: Cert) -> dict[str, Any]:
    return {
        "type": "ColumnSet",
        "spacing": "Small",
        "columns": [
            {
                "type": "Column",
                "width": "stretch",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": f"{item.marker} {item.name}",
                        "wrap": True,
                        "size": "Small",
                    }
                ],
            },
            {
                "type": "Column",
                "width": "auto",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": item.validity_end,
                        "size": "Small",
                        "isSubtle": True,
                        "horizontalAlignment": "Right",
                    }
                ],
            },
            {
                "type": "Column",
                "width": "auto",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": _chip_of(item.days_left),
                        "size": "Small",
                        "weight": "Bolder",
                        "color": _color_of(item.days_left),
                        "horizontalAlignment": "Right",
                    }
                ],
            },
        ],
    }


def _table_of[T](heads: Sequence[str], rows: Sequence[T], cells: Callable[[T], list[str]]) -> str:
    th = "".join(
        '<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #d2d0ce;'
        f'background:#f3f2f1;font-size:12px">{head}</th>'
        for head in heads
    )
    tr = "".join(
        "<tr>"
        + "".join(
            f'<td style="padding:6px 10px;border-bottom:1px solid #edebe9;font-size:13px">{c}</td>'
            for c in cells(row)
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<table style="border-collapse:collapse;width:100%;margin-bottom:4px">'
        f"<thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"
    )


def _block(title: str, note: str, inner: str) -> str:
    said = f'<p style="margin:0 0 8px;color:#605e5c;font-size:13px">{note}</p>' if note else ""
    return f'<h3 style="margin:18px 0 4px;font-size:14px">{title}</h3>{said}{inner}'


def _status(item: Cert) -> str:
    if item.days_left < 0:
        return f"overdue {abs(item.days_left)} days"
    return f"in {item.days_left} days"


@dataclass(frozen=True)
class CertReport:
    """What one read of the list found, and the card and email built from it."""

    where: Where
    checked_at: str
    rows_read: int
    confirmed: list[Cert]
    missing_env: list[Cert]
    unreadable: list[Untracked]
    stale: list[Cert]
    duplicates: list[Cert]
    no_expiry: list[Untracked]
    stored_elsewhere: list[Untracked]
    needs_rows: list[NeedsRow] = field(default_factory=list[NeedsRow])

    @property
    def needs_confirm_count(self) -> int:
        return len(self.missing_env) + len(self.unreadable) + len(self.stale) + len(self.duplicates)

    @property
    def has_alerts(self) -> bool:
        return bool(self.confirmed) or self.needs_confirm_count > 0

    @property
    def expired_count(self) -> int:
        return sum(1 for item in self.confirmed if item.days_left < 0)

    @property
    def soon_count(self) -> int:
        return sum(1 for item in self.confirmed if 0 <= item.days_left <= NEAR_DAYS)

    @property
    def later_count(self) -> int:
        return sum(1 for item in self.confirmed if item.days_left > NEAR_DAYS)

    @property
    def not_tracked_count(self) -> int:
        return len(self.no_expiry) + len(self.stored_elsewhere)

    @property
    def by_env(self) -> dict[str, list[Cert]]:
        grouped: dict[str, list[Cert]] = {}
        for item in self.confirmed:
            grouped.setdefault(item.env, []).append(item)
        return {env: grouped[env] for env in sorted(grouped, key=locale_order)}

    @property
    def subject(self) -> str:
        count = len(self.confirmed)
        if count:
            return f"⚠️ {count} certificate{'' if count == 1 else 's'} need action"
        return "✅ Nothing confirmed due in this window"

    @property
    def email_subject(self) -> str:
        count = self.needs_confirm_count
        if count:
            return f"Cert List · {count} item(s) to confirm · {len(self.confirmed)} posted to Teams"
        return f"Cert List · {len(self.confirmed)} expiring, nothing to confirm"

    @property
    def needs_note(self) -> str:
        if not self.needs_confirm_count:
            return "Everything on the page is confirmed and readable."
        parts = [
            f"{len(self.missing_env)} without ENV" if self.missing_env else "",
            f"{len(self.unreadable)} unreadable date" if self.unreadable else "",
            f"{len(self.stale)} stale row(s)" if self.stale else "",
            f"{len(self.duplicates)} duplicate(s)" if self.duplicates else "",
        ]
        listed = ", ".join(part for part in parts if part)
        return (
            f"{self.needs_confirm_count} item(s) need a human look and were emailed to "
            f"{self.where.email_to}: {listed}."
        )

    @property
    def card(self) -> dict[str, Any]:
        """The Teams card: confirmed rows only."""
        env_blocks: list[dict[str, Any]] = []
        for env, items in self.by_env.items():
            env_blocks.append(
                {
                    "type": "TextBlock",
                    "text": f"{env} ({len(items)})",
                    "size": "Small",
                    "weight": "Bolder",
                    "separator": True,
                }
            )
            env_blocks.extend(_row_set(item) for item in items[:MAX_LIST_PER_ENV])
            if len(items) > MAX_LIST_PER_ENV:
                env_blocks.append(
                    {
                        "type": "TextBlock",
                        "text": f"… and {len(items) - MAX_LIST_PER_ENV} more in {env}",
                        "size": "Small",
                        "isSubtle": True,
                    }
                )
        nothing = {
            "type": "TextBlock",
            "wrap": True,
            "text": "No certificate with a confirmed date and environment falls inside the "
            "reminder window.",
            "isSubtle": True,
        }
        body: list[dict[str, Any]] = [
            {
                "type": "Container",
                "style": "Attention",
                "bleed": True,
                "items": [
                    {
                        "type": "TextBlock",
                        "text": self.subject,
                        "size": "Medium",
                        "weight": "Bolder",
                        "wrap": True,
                    },
                    {
                        "type": "TextBlock",
                        "text": f"Cert List · {self.rows_read} rows read · checked "
                        f"{self.checked_at} ({TIME_ZONE.key})",
                        "size": "Small",
                        "isSubtle": True,
                        "wrap": True,
                    },
                ],
            },
            {
                "type": "ColumnSet",
                "spacing": "Small",
                "separator": True,
                "columns": [
                    _stat_column("OVERDUE", self.expired_count, "Attention"),
                    _stat_column(f"DUE ≤ {NEAR_DAYS}D", self.soon_count, "Warning"),
                    _stat_column(f"DUE ≤ {WARN_DAYS}D", self.later_count, "Default"),
                ],
            },
            *(env_blocks or [nothing]),
            {
                "type": "TextBlock",
                "text": self.needs_note,
                "size": "Small",
                "isSubtle": True,
                "wrap": True,
                "separator": True,
            },
            {
                "type": "ActionSet",
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "Open Cert List",
                        "url": self.where.page_url,
                    }
                ],
            },
        ]
        return {
            "type": "AdaptiveCard",
            "version": "1.4",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "msteams": {"width": "Full"},
            "body": body,
        }

    @property
    def email_html(self) -> str:
        """The email: the rows that need confirming. `<!--AI-->` is where the optional AI step
        puts what the model read, or says that no model answered."""
        blocks: list[str] = []
        if self.missing_env:
            blocks.append(
                _block(
                    f"No environment filled in ({len(self.missing_env)})",
                    "These look actionable but the page does not say where the certificate "
                    "lives, so they are not posted to Teams.",
                    _table_of(
                        ["Certificate", "Validity end", "Status"],
                        self.missing_env[:MAX_ROWS_PER_SECTION],
                        lambda r: [_esc(r.name), r.validity_end, _status(r)],
                    ),
                )
            )
        if self.unreadable:
            blocks.append(
                _block(
                    f"Cannot read a date ({len(self.unreadable)})",
                    "Write a real date in the VALIDITY END cell (e.g. 04 Dec 2026) - prose like "
                    '"renewed yearly" is not parseable.',
                    _table_of(
                        ["Environment", "Certificate", "Cell says"],
                        self.unreadable[:MAX_ROWS_PER_SECTION],
                        lambda r: [_esc(r.env), _esc(r.name), f"&quot;{_cut(r.raw_end, 90)}&quot;"],
                    ),
                )
            )
        if self.stale:
            months = int(STALE_AFTER_DAYS / 30 + 0.5)
            blocks.append(
                _block(
                    f"Expired more than {months} months ago ({len(self.stale)})",
                    "Almost certainly stale rows rather than renewal tasks - update the date or "
                    "mark the row retired.",
                    _table_of(
                        ["Environment", "Certificate", "Validity end"],
                        self.stale[:MAX_ROWS_PER_SECTION],
                        lambda r: [_esc(r.env), _esc(r.name), r.validity_end],
                    ),
                )
            )
        if self.duplicates:
            blocks.append(
                _block(
                    f"Duplicate rows on the page ({len(self.duplicates)})",
                    "The same environment + certificate + date appears more than once; merged "
                    "for this report.",
                    _table_of(
                        ["Environment", "Certificate", "Validity end"],
                        self.duplicates[:MAX_ROWS_PER_SECTION],
                        lambda r: [_esc(r.env), _esc(r.name), r.validity_end],
                    ),
                )
            )
        steps = "".join(f'<li style="margin-bottom:4px">{_esc(s)}</li>' for s in ACTION_STEPS)
        nothing = (
            "<p>Nothing needs confirming - every row has a readable date and an environment.</p>"
        )
        untracked = (
            [
                f'<p style="margin-top:14px;color:#605e5c;font-size:12px">{self.not_tracked_count} '
                "row(s) keep the key elsewhere (SSM / Keycloak / Imperva / non-expiring keys) - no "
                "expiry tracked on this page.</p>"
            ]
            if self.not_tracked_count
            else []
        )
        return "".join(
            [
                "<div style=\"font-family:'Segoe UI',Arial,sans-serif;color:#242424;"
                'max-width:820px">',
                f'<h2 style="margin:0 0 2px;font-size:18px">{_esc(self.email_subject)}</h2>',
                '<p style="margin:0 0 16px;color:#605e5c;font-size:13px">Teams channel '
                f"<em>{_esc(self.where.channel)}</em> gets only confirmed items "
                f"({len(self.confirmed)}). The {self.needs_confirm_count} below need a decision "
                "or a page fix before they "
                "can be posted.</p>",
                "<!--AI-->",
                *(blocks or [nothing]),
                '<h3 style="margin:18px 0 4px;font-size:14px">What to do</h3>'
                f'<ol style="margin:0;padding-left:20px;font-size:13px">{steps}</ol>',
                *untracked,
                f'<p style="margin-top:16px;font-size:12px"><a href="{_esc(self.where.page_url)}">'
                f"Open Cert List</a> · checked {_esc(self.checked_at)} ({TIME_ZONE.key})</p>",
                "</div>",
            ]
        )

    @property
    def payload(self) -> dict[str, Any]:
        """What his flow takes: the Teams message with the card, and the email beside it."""
        return {
            "type": "message",
            "emailSubject": self.email_subject,
            "emailHtml": self.email_html,
            "attachments": [
                {"contentType": "application/vnd.microsoft.card.adaptive", "content": self.card}
            ],
        }

    def item(self) -> dict[str, Any]:
        """The result as his Code node returned it, apart from the plain-text and HTML mirrors
        for the SMTP node he had turned off."""
        return {
            "has_alerts": self.has_alerts,
            "subject": self.subject,
            "email_subject": self.email_subject,
            "checked_at": self.checked_at,
            "page_url": self.where.page_url,
            "email_to": self.where.email_to,
            "rows_read": self.rows_read,
            "confirmed_count": len(self.confirmed),
            "needs_confirm_count": self.needs_confirm_count,
            "expired_count": self.expired_count,
            "soon_count": self.soon_count,
            "later_count": self.later_count,
            "missing_env_count": len(self.missing_env),
            "unreadable_count": len(self.unreadable),
            "stale_count": len(self.stale),
            "duplicate_count": len(self.duplicates),
            "not_tracked_count": self.not_tracked_count,
            "by_env_counts": {env: len(items) for env, items in self.by_env.items()},
            "confirmed": [_plain(i) for i in self.confirmed],
            "missing_env": [_plain(i) for i in self.missing_env],
            "unreadable": [_plain(i) for i in self.unreadable],
            "stale": [_plain(i) for i in self.stale[:STALE_KEPT]],
            "duplicates": [_plain(i) for i in self.duplicates],
            "needs_rows": [vars(row) for row in self.needs_rows],
            "card": self.card,
            "email_html": self.email_html,
        }


_END: Final = re.compile(r"validity\s*end|valid\s*end|expir", re.IGNORECASE)
_ENV: Final = re.compile(r"^env$|environment", re.IGNORECASE)
_NAME: Final = re.compile(r"\bname\b|holder|owner|system|service", re.IGNORECASE)


def _headers(tables: Sequence[Sequence[list[str]]]) -> tuple[list[str], Sequence[list[str]]]:
    for table in tables:
        at = next((i for i, row in enumerate(table) if any(_END.search(c) for c in row)), None)
        if at is not None:
            return table[at], table[at + 1 :]
    seen = " // ".join(" | ".join(table[0]) for table in tables)[:500]
    raise CertListError(f'No column matching "VALIDITY END". Headers seen: {seen}')


def _column(headers: Sequence[str], pattern: re.Pattern[str], fallback: int) -> int:
    return next((i for i, head in enumerate(headers) if pattern.search(head)), fallback)


def parse_cert_list(storage: str, now: datetime, where: Where) -> CertReport:
    """Reads the page's storage format, as Confluence sends it for expand=body.storage.

    Raises CertListError when the page has no body, no table, or no VALIDITY END column."""
    if not storage:
        raise CertListError(
            "No page body in the Confluence response - check the credential and page id."
        )
    tables = extract_tables(storage)
    if not tables:
        raise CertListError("No <table> found on the Cert List page.")
    headers, rows = _headers(tables)
    env_column = _column(headers, _ENV, -1)
    name_column = _column(headers, _NAME, 0)
    end_column = _column(headers, _END, -1)
    today = now.astimezone(TIME_ZONE).date()

    actionable: list[Cert] = []
    stale: list[Cert] = []
    no_expiry: list[Untracked] = []
    stored_elsewhere: list[Untracked] = []
    unreadable: list[Untracked] = []
    undated: Mapping[str, list[Untracked]] = {
        "no-expiry": no_expiry,
        "stored-elsewhere": stored_elsewhere,
        "unreadable": unreadable,
    }
    for number, row in enumerate(rows, start=1):
        raw_end = _at(row, end_column).strip()
        env = _at(row, env_column).strip() or NO_ENV
        name = _at(row, name_column).strip() or f"row {number}"
        match read_validity_end(raw_end):
            case "empty":
                continue
            case Dated(day=day, basis=basis):
                days_left = (day - today).days
                cert = Cert(env, name, short_date(day), days_left, basis, raw_end)
                (stale if days_left < -STALE_AFTER_DAYS else actionable).append(cert)
            case kind:
                undated[kind].append(Untracked(env, name, raw_end))

    duplicates: list[Cert] = []
    actionable = _merged(actionable, duplicates)
    stale = _merged(stale, duplicates)

    attention = [item for item in actionable if item.days_left <= WARN_DAYS]
    missing_env = [item for item in attention if item.env == NO_ENV]
    needs: list[NeedsRow] = []
    buckets: tuple[tuple[Bucket, Sequence[Cert | Untracked]], ...] = (
        ("no-environment", missing_env),
        ("unreadable-date", unreadable),
        ("expired-long-ago", stale),
        ("duplicate-row", duplicates),
    )
    for bucket, items in buckets:
        for item in items:
            cell = item.raw_end or (item.validity_end if isinstance(item, Cert) else "")
            needs.append(
                NeedsRow(f"n{len(needs) + 1}", bucket, item.env, item.name, cell[:CELL_KEPT])
            )
    return CertReport(
        where=where,
        checked_at=checked_words(now),
        rows_read=len(rows),
        confirmed=[item for item in attention if item.env != NO_ENV],
        missing_env=missing_env,
        unreadable=unreadable,
        stale=stale,
        duplicates=duplicates,
        no_expiry=no_expiry,
        stored_elsewhere=stored_elsewhere,
        needs_rows=needs,
    )
