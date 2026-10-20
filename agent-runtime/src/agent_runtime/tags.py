import re
from collections.abc import Iterable
from dataclasses import dataclass

_TAG = re.compile(
    r"^(?P<family>.*?)(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)

type PreIdentifier = tuple[int, int, str]
type SortKey = tuple[int, int, int, int, tuple[PreIdentifier, ...]]


class UnparseableTag(ValueError):
    pass


@dataclass(frozen=True)
class ParsedTag:
    tag: str
    family: str
    key: SortKey


def _pre_identifier(part: str) -> PreIdentifier:
    return (0, int(part), "") if part.isdecimal() else (1, 0, part)


def parse_tag(tag: str) -> ParsedTag | None:
    match = _TAG.match(tag)
    if match is None:
        return None
    pre = match["pre"]
    identifiers = tuple(_pre_identifier(part) for part in pre.split(".")) if pre else ()
    key: SortKey = (
        int(match["major"]),
        int(match["minor"]),
        int(match["patch"]),
        0 if pre else 1,
        identifiers,
    )
    return ParsedTag(tag=tag, family=match["family"], key=key)


def family_of(tag: str) -> str | None:
    parsed = parse_tag(tag)
    return parsed.family if parsed else None


def newer_than(last: str, tags: Iterable[str]) -> list[str]:
    anchor = parse_tag(last)
    if anchor is None:
        raise UnparseableTag(f"{last!r} is not a version tag")
    found = {
        parsed.tag: parsed
        for parsed in map(parse_tag, tags)
        if parsed and parsed.family == anchor.family and parsed.key > anchor.key
    }
    return [p.tag for p in sorted(found.values(), key=lambda p: p.key, reverse=True)]


def highest(tags: Iterable[str]) -> str | None:
    parsed = [p for p in map(parse_tag, tags) if p]
    return max(parsed, key=lambda p: p.key).tag if parsed else None
