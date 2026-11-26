"""Which source a failed block called, how long each try waited on it, and how many tries n8n
made, from the block as the execution ran it (ADR 0056). Nothing here is guessed: a source no
record names is None, and the words then say "The source". A limit nothing shows is None, and
the words then say "in time".

Pure.
"""

import ipaddress
import re
from collections.abc import Mapping
from typing import Any, Final, cast

from platform_api.monitoring import REQUEST_LIMIT_SECONDS, SourceStop, delay_in, not_found_in
from platform_api.orchestration.node_classes import NODE_CLASSES, NodeClasses, OnType

HTTP_REQUEST: Final = "n8n-nodes-base.httpRequest"
OURS: Final = "CUSTOM."
"""Our blocks call only our platform, which reads each source with a limit of its own and answers
in its own words, so their failures keep those words."""

N8N_LIMIT_MS: Final = 300_000
"""n8n 2.42.6's limit for a try when a block sets none, or sets this same number, as HTTP Request
3 to 4.5 and a declarative block do. Our image cuts it to REQUEST_LIMIT_SECONDS for a read only
(deploy/n8n/request-limit.mjs)."""
OLD_HTTP_LIMIT_MS: Final = 3_600_000
"""HTTP Request 1 and 2 wait an hour when their Timeout is empty (HttpRequestV1.node.js)."""
READS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
POSTED_READS: Final[Mapping[str, frozenset[str]]] = {
    "n8n-nodes-base.jira": frozenset({"issue getAll"}),
}
"""Reads on the allow list that n8n-nodes-base 2.42.4 sends as a POST, so they keep n8n's 300 s:
a Jira search (Jira.node.js, /api/2/search/jql). Every other read on it is a GET."""

_LABEL: Final = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST: Final = re.compile(rf"(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*")
"""A host name or an IPv4 address, and nothing else."""
_AUTHORITY: Final = re.compile(r"(?P<host>\[[0-9a-f:.]+\]|[^\[\]:]+)(?::[0-9]{1,5})?")


def source_of(block: Mapping[str, Any], classes: NodeClasses = NODE_CLASSES) -> str | None:
    """The system the allow list names for one of n8n's own blocks, such as GitHub, or the host
    an HTTP Request block names in its written address."""
    node_type = str(block.get("type"))
    if node_type == HTTP_REQUEST:
        return _host(_parameters(block).get("url"))
    entry = classes.entry(node_type)
    return entry.system if isinstance(entry, OnType) else None


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _parameters(block: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(block.get("parameters"))


def _host(url: object) -> str | None:
    """The host, only when the address writes it out whole before any expression, and only when
    it is a plain host name or address. Anything else, such as a name and password before an @
    or a backslash, which parsers read in different ways, names no host."""
    if not isinstance(url, str):
        return None
    written, expression, _ = url.removeprefix("=").partition("{{")
    scheme, sep, rest = written.strip().partition("://")
    authority, *after = re.split(r"[/?#]", rest, maxsplit=1)
    if scheme.lower() not in ("http", "https") or not sep or (expression and not after):
        return None
    found = _AUTHORITY.fullmatch(authority.lower())
    if found is None:
        return None
    host = found.group("host")
    if host.startswith("["):
        try:
            return str(ipaddress.IPv6Address(host[1:-1]))
        except ValueError:
            return None
    return host if _HOST.fullmatch(host) else None


def tries_of(block: Mapping[str, Any]) -> int:
    """The tries n8n 2.42.6 makes of a block that keeps failing: two to five with Retry On Fail,
    three when it names no number, and one without (WorkflowExecute.getRetryParams)."""
    if block.get("retryOnFail") is not True:
        return 1
    asked = block.get("maxTries")
    wanted = asked if isinstance(asked, int) and not isinstance(asked, bool) and asked else 3
    return min(5, max(2, wanted))


def _number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value
    return None


def _cut(limit_ms: int, method: str) -> int:
    """What our image leaves of a limit: a read with n8n's 300 s waits our limit instead."""
    if limit_ms == N8N_LIMIT_MS and method.upper() in READS:
        return REQUEST_LIMIT_SECONDS * 1000
    return limit_ms


def _http_limit_ms(block: Mapping[str, Any]) -> int | None:
    """HTTP Request's limit for each try, by its version, method and Timeout. None when an
    expression sets the method or the Timeout."""
    parameters = _parameters(block)
    version = _number(block.get("typeVersion")) or 1
    old = version < 3
    method = parameters.get("requestMethod" if old else "method", "GET")
    if not isinstance(method, str) or method.startswith("="):
        return None
    own = _mapping(parameters.get("options")).get("timeout")
    if own is None or (not old and own in (0, "")):
        return _cut(OLD_HTTP_LIMIT_MS if old else N8N_LIMIT_MS, method)
    number = _number(own)
    if number is None or number <= 0:
        return None
    return _cut(int(number), method)


def limit_ms_of(block: Mapping[str, Any], classes: NodeClasses = NODE_CLASSES) -> int | None:
    """How long each try waited. For one of n8n's own blocks on the allow list it follows the
    method its operation sends: a read sent as a GET waits our limit, and a post or a read sent as
    a POST waits n8n's 300 s. None when nothing shows the method or the limit."""
    node_type = str(block.get("type"))
    if node_type == HTTP_REQUEST:
        return _http_limit_ms(block)
    doing = classes.doing(node_type, block.get("typeVersion"), _parameters(block))
    if doing is None:
        return None
    what, on = doing
    if on == "read" and what not in POSTED_READS.get(node_type, frozenset()):
        return _cut(N8N_LIMIT_MS, "GET")
    return N8N_LIMIT_MS if on in ("read", "notice") else None


def source_stop(
    node: str | None, block: Mapping[str, Any] | None, message: str | None
) -> SourceStop | None:
    """The facts of a stop at one of n8n's own blocks whose source gave no usable answer, or at
    one of ours whose source has no such place, in our platform's words for it. None for any
    other failure."""
    named = node or (None if block is None else block.get("name"))
    if not isinstance(named, str):
        return None
    if block is not None and str(block.get("type")).startswith(OURS):
        found = not_found_in(message)
        if found is None:
            return None
        source, place = found
        return SourceStop(source, "not_found", None, named, tries_of(block), place)
    delay = delay_in(message)
    if delay is None:
        return None
    if block is None:
        return SourceStop(None, delay, None, named, 1)
    return SourceStop(source_of(block), delay, limit_ms_of(block), named, tries_of(block))
