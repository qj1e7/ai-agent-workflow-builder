"""Recorded samples (ADR 0054, section 6): answers from a system that a scenario replays or varies.
A sample comes from a real run's read (n8n's execution data), from a mock, or is made up here.
Code scrubs every answer before it keeps one, and code varies the samples. The model never sees
an answer before it is scrubbed.

Each kind of answer has an allow list: the fields kept, each with a rule for its value. A field
the list doesn't name is left out, whatever it holds, nested objects and lists included. So names,
emails, user and account ids, avatars and text people wrote are never kept. The rules:

- version: kept when it looks like a version or a tag, such as 1.2.16, v1.9.8, n8n@2.4.2 or
  cli==0.4.37. It has a dotted number, no space and no email. Anything else is left out.
- time: kept when it is an ISO 8601 date, with or without a time. Anything else is left out.
- flag: kept when it is true or false. Anything else is left out.
- count: kept when it is a whole number. Anything else is left out.
- issue key: kept when it is a Jira key, such as SUP-12. Anything else is left out.
- the tag again: a release's name is kept only when it is its tag. Any other name becomes the tag,
  since a title is text people wrote.
- one of: kept when it is one of a few fixed words, such as a Jira status. Anything else becomes
  the first of them.
- text: never kept. Any text becomes a fixed made-up value, since text people wrote may name
  anyone. A link is text too, and it is rebuilt on a made-up place, or becomes a fixed link.

A value longer than its field ever is, such as 80 characters for a version, is left out before
any pattern reads it, so no value can make a pattern take long.

A value kept that has the shape of a key, such as a long run of letters and digits or a known
key's prefix, is masked, as traces are (agent-runtime's monitoring/masking.py).

Until the DevNet move, samples come only from open-internet sources and the practice Jira, never
from NCS data (ADR 0050).
"""

import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

from platform_api.orchestration.write_actions import Json

type AnswerKind = Literal["github.release", "read.release", "read.page", "jira.issue"]
type Variation = Literal["suffix", "empty_field", "long_text"]
type Origin = Literal["made_up", "mock", "real_run"]

FAKE_LINK: Final = "https://sample.invalid/"
MASKED: Final = "[masked]"
RELEASE_NOTES: Final = "Release notes made up for a simulation."
PAGE_ID: Final = "100001"
PAGE_TITLE: Final = "A page made up for a simulation"
PAGE_TEXT: Final = "Page text made up for a simulation."
ISSUE_SUMMARY: Final = "An issue made up for a simulation"
SUFFIX: Final = "-rc.1"
"""What "suffix" adds to a version: a pre-release mark, as many tags carry one."""
LONG_TEXT_LENGTH: Final = 5000
"""How long "long_text" makes a field, in characters."""
SAMPLE_ITEMS: Final = 100
"""The most items a sample keeps, newest first, as the Read block passes on at most 100."""
SAMPLE_LIMIT: Final = 200
"""The most samples a store keeps besides the made-up ones. A new one forgets the oldest."""

_VERSION: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+=@-]*$")
_DOTTED: Final = re.compile(r"\d+\.\d+")
_EMAIL: Final = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_TIME: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
_ISSUE_KEY: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,19}-\d{1,9}$")
_KEY_SHAPE: Final = re.compile(
    r"[A-Za-z0-9+/=_-]{32,}"
    r"|(?<![A-Za-z0-9])"
    r"(?:sk-|gh[pousr]_|github_pat_|gl(?:pat|rt|dt)-|xox[abcdeprs]-|AKIA|ASIA|ATATT|AIza|eyJ)"
)
"""A long run of letters and digits, or the start of a key a vendor makes, as traces mask."""


@dataclass(frozen=True)
class Shaped:
    """Kept when the value is no longer than `longest` and has this shape, and holds `holds` when
    it names one, else left out. The length is checked first."""

    pattern: re.Pattern[str]
    longest: int
    holds: re.Pattern[str] | None = None


@dataclass(frozen=True)
class Flag:
    pass


@dataclass(frozen=True)
class Count:
    pass


@dataclass(frozen=True)
class SameAs:
    """Kept when it is the other field's value, else that value."""

    other: str


@dataclass(frozen=True)
class OneOf:
    words: tuple[str, ...]
    """Kept when it is one of these, else the first."""


@dataclass(frozen=True)
class Text:
    fake: str
    """What any text becomes."""


@dataclass(frozen=True)
class Rebuilt:
    """A link rebuilt from a kept field on a made-up place, else the fixed fake link."""

    link: str
    other: str


type Rule = Shaped | Flag | Count | SameAs | OneOf | Text | Rebuilt


@dataclass(frozen=True)
class AllowList:
    said: str
    """The answer as a person says it."""
    fields: Mapping[str, Rule]
    """Each field kept, by its dotted path, with its rule."""
    varies: Mapping[Variation, str]
    """For each variation it takes, the field it changes."""


ALLOW_LISTS: Final[Mapping[AnswerKind, AllowList]] = {
    "github.release": AllowList(
        "A GitHub release",
        {
            "tag_name": Shaped(_VERSION, 80, _DOTTED),
            "name": SameAs("tag_name"),
            "published_at": Shaped(_TIME, 32),
            "created_at": Shaped(_TIME, 32),
            "html_url": Rebuilt("https://github.com/sample/sample/releases/tag/{}", "tag_name"),
            "prerelease": Flag(),
            "draft": Flag(),
            "body": Text(RELEASE_NOTES),
        },
        {"suffix": "tag_name", "empty_field": "name", "long_text": "body"},
    ),
    "read.release": AllowList(
        "A release our Read block read",
        {
            "kind": OneOf(("release",)),
            "id": Shaped(_VERSION, 80, _DOTTED),
            "name": SameAs("id"),
            "published_at": Shaped(_TIME, 32),
        },
        {"suffix": "id", "empty_field": "published_at", "long_text": "name"},
    ),
    "read.page": AllowList(
        "A Confluence page",
        {
            "kind": OneOf(("page",)),
            "id": Text(PAGE_ID),
            "title": Text(PAGE_TITLE),
            "version": Count(),
            "url": Text(FAKE_LINK),
            "text": Text(PAGE_TEXT),
        },
        {"empty_field": "title", "long_text": "text"},
    ),
    "jira.issue": AllowList(
        "A Jira issue",
        {
            "key": Shaped(_ISSUE_KEY, 30),
            "fields.summary": Text(ISSUE_SUMMARY),
            "fields.status.name": OneOf(("To Do", "In Progress", "Done")),
            "fields.created": Shaped(_TIME, 32),
            "fields.updated": Shaped(_TIME, 32),
        },
        {"empty_field": "fields.status.name", "long_text": "fields.summary"},
    ),
}

_WHAT_VARIES: Final[Mapping[Variation, str]] = {
    "suffix": "version",
    "empty_field": "field to empty",
    "long_text": "text to make long",
}


def _masked(value: str) -> str:
    return MASKED if _KEY_SHAPE.search(value) else value


def _at(item: Mapping[str, Any], path: str) -> tuple[bool, object]:
    found: object = item
    for part in path.split("."):
        if not isinstance(found, dict) or part not in found:
            return False, None
        found = cast(dict[str, object], found)[part]
    return True, found


def _put(item: dict[str, Any], path: str, value: object) -> None:
    *parents, last = path.split(".")
    where = item
    for part in parents:
        where = where.setdefault(part, {})
    where[last] = value


def _kept(rule: Rule, value: object, item: Mapping[str, Any]) -> tuple[bool, object]:
    """Whether the field stays, and with what value. A rule that refers to another field reads
    it from what is already kept."""
    match rule:
        case Shaped(pattern, longest, holds):
            if not isinstance(value, str) or len(value) > longest:
                return False, None
            held = holds is None or holds.search(value) is not None
            if held and pattern.match(value) and not _EMAIL.search(value):
                return True, _masked(value)
            return False, None
        case Flag():
            return (True, value) if isinstance(value, bool) else (False, None)
        case Count():
            whole = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            return (True, value) if whole else (False, None)
        case SameAs(other):
            present, own = _at(item, other)
            return (True, own) if present else (False, None)
        case OneOf(words):
            return True, value if value in words else words[0]
        case Text(fake):
            return True, None if value is None else fake
        case Rebuilt(link, other):
            present, own = _at(item, other)
            ok = present and isinstance(own, str) and own != MASKED
            return True, link.format(own) if ok else FAKE_LINK


def scrub(answer: AnswerKind, items: Iterable[object]) -> tuple[dict[str, Json], ...]:
    """Each item as its allow list keeps it. Anything but an object is left out."""
    rules = ALLOW_LISTS[answer].fields
    scrubbed: list[dict[str, Json]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        given = cast(dict[str, Any], raw)
        kept: dict[str, Any] = {}
        # A rule that refers to another field comes after the rules that keep values as given.
        ordered = sorted(rules.items(), key=lambda pair: isinstance(pair[1], SameAs | Rebuilt))
        for path, rule in ordered:
            present, value = _at(given, path)
            if not present:
                continue
            stays, value = _kept(rule, value, kept)
            if stays:
                _put(kept, path, value)
        scrubbed.append({path: kept[path] for path in _order(rules, kept)})
    return tuple(scrubbed)


def _order(rules: Mapping[str, Rule], kept: Mapping[str, Any]) -> list[str]:
    """The kept top-level fields, in the allow list's order."""
    tops = dict.fromkeys(path.split(".")[0] for path in rules)
    return [top for top in tops if top in kept]


def vary(
    items: Sequence[Mapping[str, Json]], answer: AnswerKind, variations: Iterable[Variation]
) -> tuple[dict[str, Json], ...] | str:
    """The items with each variation made to the newest, which a release check reads first. The
    others stay as they are. Words when a variation can't be made."""
    allow = ALLOW_LISTS[answer]
    wanted = list(variations)
    copied = tuple(cast(dict[str, Json], json.loads(json.dumps(item))) for item in items)
    if not wanted:
        return copied
    if not copied:
        return "This sample has nothing to vary."
    first: dict[str, Any] = copied[0]
    for variation in wanted:
        path = allow.varies.get(variation)
        if path is None:
            what = _WHAT_VARIES[variation]
            return f'{allow.said} has no {what} to vary with "{variation}".'
        _, value = _at(first, path)
        match variation:
            case "suffix":
                _put(first, path, f"{value or ''}{SUFFIX}")
            case "empty_field":
                _put(first, path, "")
            case "long_text":
                start = f"{value} " if isinstance(value, str) and value else ""
                filler = "Long text made up for a simulation. "
                needed = LONG_TEXT_LENGTH - len(start)
                _put(first, path, (start + filler * (needed // len(filler) + 1))[:LONG_TEXT_LENGTH])
    return copied


OURS_READ = "CUSTOM.wabRead"
_READ_SOURCES: Final[Mapping[str, AnswerKind]] = {
    "github_releases": "read.release",
    "confluence_page": "read.page",
}


def answer_of(block: Mapping[str, Any]) -> AnswerKind | None:
    """What a read block gives, when an allow list covers it. None for anything else."""
    node_type = str(block.get("type"))
    parameters = cast(Mapping[str, object], block.get("parameters") or {})
    if node_type == OURS_READ:
        return _READ_SOURCES.get(str(parameters.get("source", "github_releases")))
    resource, operation = parameters.get("resource"), parameters.get("operation")
    if node_type == "n8n-nodes-base.github" and resource == "release":
        return "github.release"
    if node_type == "n8n-nodes-base.jira" and resource in (None, "issue"):
        return "jira.issue" if operation in ("get", "getAll") else None
    return None


@dataclass(frozen=True)
class Sample:
    id: str
    answer: AnswerKind
    items: tuple[Mapping[str, Json], ...] = field(repr=False)
    origin: Origin
    block: str | None = None
    """The block it was recorded from, when it was."""


def _made_up(answer: AnswerKind, *items: dict[str, Json]) -> Sample:
    return Sample(f"made_up.{answer}", answer, scrub(answer, items), "made_up")


MADE_UP: Final[Mapping[AnswerKind, Sample]] = {
    "github.release": _made_up(
        "github.release",
        {
            "tag_name": "1.2.16",
            "name": "1.2.16",
            "published_at": "2026-10-28T09:00:00Z",
            "created_at": "2026-10-28T08:00:00Z",
            "html_url": "https://github.com/sample/sample/releases/tag/1.2.16",
            "prerelease": False,
            "draft": False,
            "body": RELEASE_NOTES,
        },
        {
            "tag_name": "1.2.15",
            "name": "1.2.15",
            "published_at": "2026-10-27T02:00:00Z",
            "created_at": "2026-10-27T01:00:00Z",
            "html_url": "https://github.com/sample/sample/releases/tag/1.2.15",
            "prerelease": False,
            "draft": False,
            "body": RELEASE_NOTES,
        },
    ),
    "read.release": _made_up(
        "read.release",
        {"kind": "release", "id": "1.2.16", "name": "1.2.16", "published_at": "2026-10-28"},
        {"kind": "release", "id": "1.2.15", "name": "1.2.15", "published_at": "2026-10-27"},
    ),
    "read.page": _made_up(
        "read.page",
        {
            "kind": "page",
            "id": PAGE_ID,
            "title": PAGE_TITLE,
            "version": 3,
            "url": FAKE_LINK,
            "text": PAGE_TEXT,
        },
    ),
    "jira.issue": _made_up(
        "jira.issue",
        {
            "key": "SIM-1",
            "fields": {
                "summary": ISSUE_SUMMARY,
                "status": {"name": "To Do"},
                "created": "2026-10-28T09:00:00.000+0800",
                "updated": "2026-10-29T10:30:00.000+0800",
            },
        },
    ),
}
"""The samples a store starts with, made up to look like the mocks' own answers, so the templates
run before anything is recorded."""


class RecordedSamples:
    """The samples a simulation may serve: the made-up ones, and those recorded since, each
    scrubbed before it is kept. In memory, as the simulation gateway keeps everything."""

    def __init__(self, limit: int = SAMPLE_LIMIT) -> None:
        self._limit = limit
        self._recorded: OrderedDict[str, Sample] = OrderedDict()

    def record(
        self,
        answer: AnswerKind,
        items: Iterable[object],
        origin: Origin,
        *,
        block: str | None = None,
        sample_id: str | None = None,
    ) -> Sample:
        kept = scrub(answer, list(items)[:SAMPLE_ITEMS])
        if sample_id is None:
            text = json.dumps([answer, block, kept], sort_keys=True)
            sample_id = "smp_" + hashlib.sha256(text.encode()).hexdigest()[:16]
        sample = Sample(sample_id, answer, kept, origin, block)
        self._recorded.pop(sample_id, None)
        self._recorded[sample_id] = sample
        while len(self._recorded) > self._limit:
            self._recorded.popitem(last=False)
        return sample

    def get(self, sample_id: str) -> Sample | None:
        found = self._recorded.get(sample_id)
        if found is not None:
            return found
        return next((s for s in MADE_UP.values() if s.id == sample_id), None)

    def for_block(self, block: str, answer: AnswerKind) -> Sample:
        """The newest sample recorded from this block, else the newest of its kind, else the
        made-up one."""
        newest_first = list(reversed(self._recorded.values()))
        fits = [s for s in newest_first if s.answer == answer]
        own = [s for s in fits if s.block == block]
        return (own or fits or [MADE_UP[answer]])[0]


def record_run(
    samples: RecordedSamples, version: Mapping[str, Any], run_data: Mapping[str, Any]
) -> tuple[Sample, ...]:
    """Records what each read block of a version returned in a real run, from n8n's execution
    data (`resultData.runData`), scrubbed. A block that read nothing, or failed, records nothing."""
    kept: list[Sample] = []
    for node in cast(list[Mapping[str, Any]], version.get("nodes") or []):
        answer = answer_of(node)
        name = str(node.get("name"))
        tries = run_data.get(name)
        if answer is None or not isinstance(tries, list) or not tries:
            continue
        last: object = cast(list[Any], tries)[-1]
        main = _at(cast(dict[str, Any], last), "data.main")[1] if isinstance(last, dict) else None
        exits = cast(list[Any], main) if isinstance(main, list) else []
        first = cast(list[Any], exits[0]) if exits and isinstance(exits[0], list) else []
        items: list[object] = [
            cast(dict[str, object], i).get("json") for i in first if isinstance(i, dict)
        ]
        if items:
            kept.append(samples.record(answer, items, "real_run", block=name))
    return tuple(kept)
