import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


def check(name: str, problems: Iterable[str]) -> Check:
    found = list(problems)
    return Check(name, not found, "; ".join(found))


THEMED_NAMES = (
    "Flint",
    "Forge",
    "Striker",
    "Spark Map",
    "Scout",
    "Analyst",
    "Messenger",
    "Clerk",
    "Fixer",
    "Kindling",
    "Firebreak",
    "Ember",
)

SYSTEMS = (
    "GitHub",
    "GitLab",
    "Bitbucket",
    "Jira",
    "Confluence",
    "Teams",
    "Slack",
    "Entra",
    "Active Directory",
    "Azure",
    "AWS",
    "Docker",
    "Kubernetes",
    "PyPI",
    "npm",
    "ServiceNow",
    "Outlook",
    "Zendesk",
)

JARGON_WORDS = (
    "API",
    "HTTP",
    "endpoint",
    "exception",
    "stack trace",
    "traceback",
    "payload",
    "upstream",
    "webhook",
    "JSON",
    "regex",
    "semver",
    "idempotent",
    "retryable",
    "status code",
    "n8n",
    "AgentError",
    "WorkflowNodeError",
    "TimedOut",
    "DispatchFailed",
    "WriteFailed",
    "SafetyDenied",
    "UnboundIntent",
    "OutOfOrderStep",
    "UpstreamUnavailable",
    "UpstreamRejected",
    "InvalidTask",
)

_STATUS_CODE = re.compile(r"(?<![\w.])[45]\d\d(?![\w.])")
_IDENTIFIER = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", re.IGNORECASE)
_VERSION = re.compile(r"\d+(?:\.\d+)+")
_TICKET_KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
_WRITE_CLAIMS = (
    re.compile(
        r"\b(?:ticket|issue|page)\b[^.]{0,40}?\b(?:was|has been|have been|is|got)\s+"
        r"(?:now\s+|successfully\s+)?(?:created|opened|filed|raised|written|added|logged|"
        r"made|posted|updated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:I|we|it|they|agents?|platform|system|checker)\s+(?:have\s+|has\s+)?"
        r"(?:successfully\s+)?(?:created|opened|filed|raised|wrote|added|logged|posted)\s+"
        r"(?:a|an|the|one|your)?\s*(?:new\s+)?(?:jira\s+)?(?:ticket|issue)\b",
        re.IGNORECASE,
    ),
)
_HEDGE = re.compile(
    r"\b(?:not|no|nothing|nobody|none|never|without|would|could|will|should|can|cannot|before|until|once|if)\b"
    r"|n't\b",
    re.IGNORECASE,
)


def _word(term: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])", flags)


def _jargon_word(term: str) -> re.Pattern[str]:
    # A letter or digit must not touch the word, but a hyphen or underscore may ("Rest-API").
    # An "s" or "es" on the end still counts ("endpoints", "APIs").
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?:e?s)?(?![A-Za-z0-9])", re.IGNORECASE)


_THEMED = [_word(name, re.IGNORECASE) for name in THEMED_NAMES]
_SYSTEM = [(name, _word(name)) for name in SYSTEMS]
_JARGON = [(word, _jargon_word(word)) for word in JARGON_WORDS]


def mentions(text: str, term: str) -> bool:
    """Whole words only, so "repo" does not match "report". A trailing * marks a stem:
    "approv*" matches "approved" and "approval", but not "disapproved"."""
    stem = term.endswith("*")
    word = re.escape(term.removesuffix("*"))
    end = "" if stem else r"(?!\w)"
    return re.search(rf"(?<!\w){word}{end}", text, re.IGNORECASE) is not None


def versions_in(text: str) -> set[str]:
    return set(_VERSION.findall(text))


def systems_in(text: str) -> set[str]:
    return {name for name, pattern in _SYSTEM if pattern.search(text)}


def themed_names(text: str) -> list[str]:
    return [p.pattern for p in _THEMED if p.search(text)]


def jargon(text: str) -> list[str]:
    found = [word for word, pattern in _JARGON if pattern.search(text)]
    found += _STATUS_CODE.findall(text)
    found += _IDENTIFIER.findall(text)
    return found


def write_claims(text: str) -> list[str]:
    claims: list[str] = []
    for pattern in _WRITE_CLAIMS:
        for match in pattern.finditer(text):
            sentence_start = max(
                text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start())
            )
            context = text[sentence_start + 1 : match.end()]
            if not _HEDGE.search(context):
                claims.append(match.group(0))
    return claims


def ticket_keys(text: str) -> set[str]:
    return set(_TICKET_KEY.findall(text))


def length_cap(text: str, max_chars: int) -> Check:
    over = len(text) > max_chars
    return check("length_cap", [f"{len(text)} characters, cap {max_chars}"] if over else [])


def no_jargon(text: str, allowed: str = "") -> Check:
    return check(
        "no_jargon", [term for term in jargon(text) if term.lower() not in allowed.lower()]
    )


def no_themed_names(text: str) -> Check:
    return check("no_themed_names", themed_names(text))


def no_invented(text: str, source: str) -> list[Check]:
    allowed_versions = versions_in(source)
    allowed_systems = systems_in(source)
    return [
        check("no_invented_version", sorted(versions_in(text) - allowed_versions)),
        check("no_invented_system", sorted(systems_in(text) - allowed_systems)),
    ]


def no_write_claim(text: str, source: str) -> Check:
    return check(
        "no_write_claim",
        write_claims(text) + sorted(ticket_keys(text) - ticket_keys(source)),
    )
