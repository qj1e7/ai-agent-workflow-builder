"""A ticket body in Jira's two formats (ADR 0035), as plain text in and plain text out.

A body is model-written text, so neither format may let Jira read it as markup:
- Cloud takes Atlassian Document Format. Each paragraph is a text node, which Jira shows as
  written, and a single line break is a hardBreak node.
- Data Center takes wiki markup. The body goes inside one {noformat} block, which Jira shows as
  written. Only "{noformat" could end the block early, so it is broken up first.

Both the adapter and the practice Jira use this module, which belongs to no bounded context.
"""

import re
from collections.abc import Mapping
from typing import Any, cast

type Adf = dict[str, Any]


def json_object(value: object) -> Mapping[str, object]:
    """value as a JSON object, or an empty one when it is anything else."""
    return cast(Mapping[str, object], value) if isinstance(value, dict) else {}


def json_list(value: object) -> list[object]:
    """value as a JSON list, or an empty one when it is anything else."""
    return cast(list[object], value) if isinstance(value, list) else []


NOFORMAT = "{noformat}"
_NOFORMAT_ANY_CASE = re.compile(r"\{noformat", re.IGNORECASE)
_PARAGRAPH_BREAK = re.compile(r"\n{2,}")


def _lines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def to_adf(text: str) -> Adf:
    content: list[Adf] = []
    for paragraph in _PARAGRAPH_BREAK.split(_lines(text).strip("\n")):
        if not paragraph:
            continue
        nodes: list[Adf] = []
        for index, line in enumerate(paragraph.split("\n")):
            if index:
                nodes.append({"type": "hardBreak"})
            if line:
                nodes.append({"type": "text", "text": line})
        content.append({"type": "paragraph", "content": nodes})
    return {"type": "doc", "version": 1, "content": content}


def _inline(nodes: list[object]) -> str:
    parts: list[str] = []
    for item in nodes:
        node = json_object(item)
        kind = node.get("type")
        if kind == "text":
            parts.append(str(node.get("text", "")))
        elif kind == "hardBreak":
            parts.append("\n")
        else:
            parts.append(_inline(json_list(node.get("content"))))
    return "".join(parts)


def from_adf(doc: object) -> str:
    """The text of a document. Each block becomes a paragraph, whatever its kind, and every mark
    is dropped, so a body written by hand in Jira still reads as text."""
    blocks = json_list(json_object(doc).get("content"))
    return "\n\n".join(_inline(json_list(json_object(block).get("content"))) for block in blocks)


def to_wiki(text: str) -> str:
    body = _lines(text)
    if not body:
        return ""
    return f"{NOFORMAT}\n{_NOFORMAT_ANY_CASE.sub('{ noformat', body)}\n{NOFORMAT}"


def from_wiki(markup: object) -> str:
    """The text inside our {noformat} block, or the markup as it is for a body written by hand."""
    if not isinstance(markup, str):
        return ""
    text = _lines(markup)
    opening, closing = f"{NOFORMAT}\n", f"\n{NOFORMAT}"
    if text.startswith(opening) and text.endswith(closing) and len(text) >= len(opening + closing):
        return text[len(opening) : -len(closing)]
    return text
