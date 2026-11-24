"""Which source a failed block called, how long each try waited on it, and how many tries n8n
made, from the block as the execution ran it (ADR 0056). Nothing here is guessed: a source no
record names is None, and the words then say "The source".

Pure.
"""

from collections.abc import Mapping
from typing import Any, Final, cast
from urllib.parse import urlsplit

from platform_api.monitoring import REQUEST_LIMIT_SECONDS, SourceStop, delay_in
from platform_api.orchestration.node_classes import NODE_CLASSES, NodeClasses, OnType

HTTP_REQUEST: Final = "n8n-nodes-base.httpRequest"
OURS: Final = "CUSTOM."
"""Our blocks call only our platform, which reads each source with a limit of its own and answers
in its own words, so their failures keep those words."""


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
    """The host, only when the address writes it out whole before any expression: an expression
    right after it could still add to it."""
    if not isinstance(url, str):
        return None
    written, expression, _ = url.removeprefix("=").partition("{{")
    scheme, sep, rest = written.strip().partition("://")
    if scheme not in ("http", "https") or not sep or (expression and "/" not in rest):
        return None
    try:
        return urlsplit(written.strip()).hostname
    except ValueError:
        return None


def tries_of(block: Mapping[str, Any]) -> int:
    """The tries n8n 2.42.6 makes of a block that keeps failing: two to five with Retry On Fail,
    three when it names no number, and one without (WorkflowExecute.getRetryParams)."""
    if block.get("retryOnFail") is not True:
        return 1
    asked = block.get("maxTries")
    wanted = asked if isinstance(asked, int) and not isinstance(asked, bool) and asked else 3
    return min(5, max(2, wanted))


def limit_ms_of(block: Mapping[str, Any]) -> int:
    """How long each try waited: the block's own Timeout when it sets one as a number, as an HTTP
    Request block may, or else the limit n8n has for every block."""
    parameters = _parameters(block)
    for options in ("options", "requestOptions"):
        own = _mapping(parameters.get(options)).get("timeout")
        if isinstance(own, int | float) and not isinstance(own, bool) and own > 0:
            return int(own)
    return REQUEST_LIMIT_SECONDS * 1000


def source_stop(
    node: str | None, block: Mapping[str, Any] | None, message: str | None
) -> SourceStop | None:
    """The facts of a stop at one of n8n's own blocks whose source gave no usable answer, or None
    for any other failure, and for any failure of our own blocks."""
    delay = delay_in(message)
    named = node or (None if block is None else block.get("name"))
    if delay is None or not isinstance(named, str):
        return None
    if block is None:
        return SourceStop(None, delay, REQUEST_LIMIT_SECONDS * 1000, named, 1)
    if str(block.get("type")).startswith(OURS):
        return None
    return SourceStop(source_of(block), delay, limit_ms_of(block), named, tries_of(block))
