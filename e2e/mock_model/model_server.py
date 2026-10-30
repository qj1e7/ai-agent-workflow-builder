"""A tiny stand-in for an Anthropic Messages API, for the end to end tests.

It answers by what a request asks for, so the real runtime, with its real prompts and schemas,
can be tested without a real model:

- GET /v1/models lists one model.
- A request that forces a tool is a draft, a choice or the Planner reading a task back. The canned
  answer follows the task's words. A release task belongs on the Software watchlist.
- A request with tools and no forced tool is a card run. The mock calls github_read_releases,
  then jira_search, then jira_create_ticket, then writes a report, by what the conversation holds.
- Anything else is a summary or a connection test and gets one plain sentence.

When a tool result tells it to use another Jira project (the planted instruction in a release
body), the mock obeys once, by adding a project to its first ticket. It plays a model that was
fooled, so the test can show that the platform still writes only to the card's own project.

POST /_admin/mode with {"mode": "slow"} makes every message answer wait 15 seconds, {"mode":
"broken"} makes every forced tool answer carry a cut-off JSON string in place of its rows, and
{"mode": "ok"} restores it.
"""

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

MODEL = "mock-model"
SENTENCE = "Two new releases came out after 1.2.14: 1.2.16 and 1.2.15."
PLANTED = re.compile(r"Jira project ([A-Z][A-Z0-9]{0,9})")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+")
PROJECT = re.compile(r"[A-Z][A-Z0-9]{0,9}")
VERSION = re.compile(r"\d+\.\d+\.\d+")
INPUT_LINE = re.compile(r"^- [^:\n]+: (.+)$", re.MULTILINE)
VERSION_CHECKER = "crd_version_checker"
STEPS = ("github_read_releases", "jira_search", "jira_create_ticket")
MODES = ("ok", "slow", "broken")
SLOW_SECONDS = 15.0
BROKEN: dict[str, Any] = {
    "belongs_on_watchlist": False,
    "rows": '[{"kind": "schedule", "text": "Every',
}
RELEASE_WORDS = re.compile(
    r"\b(?:releases?|versions?|upgrades?|patch(?:es)?|cves?|vulnerabilit\w*)\b", re.IGNORECASE
)
SOFTWARE = ("LangGraph", "Redis", "FastAPI", "PostgreSQL", "Terraform", "Log4j", "Kubernetes")
SCHEDULE = re.compile(
    r"\b(?:every|each)\s+(?:week ?day|day|morning|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|week|month)s?(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?"
    r"|\b(?:daily|weekly|monthly)\b",
    re.IGNORECASE,
)
FIND = re.compile(r"(?:find|look for|list|search for)\s+(.+?)(?:\s+and\s+(.+))?$", re.IGNORECASE)
FOUND = re.compile(r"\b(?:of|every|all)\s+(.+?tickets?)\b", re.IGNORECASE)
IN_PROJECT = re.compile(r"\bin ([A-Z][A-Z0-9]{1,9})\b")
SUMMARY_TO = re.compile(
    r"^(?:post|send|share)\s+(?:a|the)\s+summary\b.*?\b(?:in|to|on)\s+(teams|slack|confluence)\b",
    re.IGNORECASE,
)
FOOLING_ORDER = re.compile(
    r"\bignore (?:your|all|the|previous) (?:rules|instructions)\b", re.IGNORECASE
)
mode = "ok"

DRAFT: dict[str, Any] = {
    "can_do": True,
    "why_not": None,
    "name": "Finished tickets summary",
    "purpose": "Looks at the tickets finished in one Jira project and proposes a summary ticket.",
    "good_for": ["Summarise what we finished this week"],
    "inputs": [
        {
            "name": "Jira project",
            "kind": "jira_project",
            "what": "The project to summarise, and where the summary goes.",
            "example": "MOCK",
        }
    ],
    "blocks": [
        {"say": "Find the tickets finished since last Friday.", "tool": "jira.search"},
        {"say": "Propose one ticket that lists them.", "tool": "jira.create_ticket"},
    ],
    "approvals": [{"tool": "jira_create_ticket", "approvers": 1, "why": "It writes a ticket."}],
    "missing_tools": [],
    "questions": ["Which Jira project should it cover?"],
}


def text_of(content: Any) -> str:
    """All the text in a message's content, tool results included."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for item in cast("list[Any]", content):
            if isinstance(item, dict):
                block = cast("dict[str, Any]", item)
                kind = block.get("type")
                if kind == "text":
                    parts.append(str(block.get("text", "")))
                elif kind == "tool_result":
                    parts.append(text_of(block.get("content")))
    return "\n".join(parts)


def blocks_of(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []  # pyright: ignore[reportUnknownVariableType]


def message(content: list[dict[str, Any]], stop: str) -> dict[str, Any]:
    return {
        "id": "msg_mock",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def say(text: str) -> dict[str, Any]:
    return message([{"type": "text", "text": text}], "end_turn")


def call(name: str, arguments: dict[str, Any], number: int) -> dict[str, Any]:
    block = {"type": "tool_use", "id": f"toolu_mock{number}", "name": name, "input": arguments}
    return message([block], "tool_use")


def system_text(body: dict[str, Any]) -> str:
    return text_of(body.get("system", ""))


def user_text(body: dict[str, Any]) -> str:
    return "\n".join(
        text_of(m.get("content")) for m in body.get("messages", []) if m.get("role") == "user"
    )


def task_text(body: dict[str, Any]) -> str:
    """Only the staff member's task. The Planner's request also lists the saved agents, whose
    purposes must not steer the mock's choice."""
    return user_text(body).rpartition("The task:\n")[2]


def choice(task: str) -> dict[str, Any]:
    words = task.lower()
    if "book" in words and "room" in words:
        return {
            "decision": "cannot_do",
            "agents": [],
            "reason": "No calendar tool.",
            "questions": [],
        }
    if "summar" in words:
        return {
            "decision": "new_agent",
            "agents": [],
            "new_agent": "Summarise finished tickets.",
            "reason": "No saved agent summarises finished tickets.",
            "questions": [],
        }
    values: dict[str, str] = {}
    if (repo := REPO.search(task)) is not None:
        values["GitHub repository"] = repo.group(0)
    if (project := re.search(r"\bin ([A-Z][A-Z0-9]{0,9})\b", task)) is not None:
        values["Jira project"] = project.group(1)
    return {
        "decision": "use_one",
        "agents": [{"card_id": VERSION_CHECKER, "part": "Check the repository.", "values": values}],
        "reason": "The Version checker already does this.",
        "questions": [],
    }


def first_up(text: str) -> str:
    return text[:1].upper() + text[1:]


def where_row(task: str) -> dict[str, Any]:
    project = IN_PROJECT.search(task)
    if project is None:
        return {"kind": "where", "state": "missing", "note": "You didn't say which Jira project."}
    return {"kind": "where", "text": f"Jira project {project.group(1)}", "state": "understood"}


def look_row(look: str | None) -> dict[str, Any]:
    if look is None:
        return {"kind": "look_for", "state": "missing", "note": "You didn't say what to look for."}
    if "stale" in look.lower() and not re.search(r"\d+\s+days?", look):
        return {
            "kind": "look_for",
            "text": first_up(look.replace("stale ", "")) + " with no update for 14 days",
            "state": "changed",
            "note": 'You said "stale", so I used 14 days without an update.',
        }
    return {"kind": "look_for", "text": first_up(look), "state": "understood"}


def fooled_action_rows(act: str | None, task: str) -> list[dict[str, Any]]:
    if act is None:
        return [{"kind": "do", "state": "missing"}, where_row(task)]
    if (place := SUMMARY_TO.search(act)) is not None:
        return [
            {"kind": "do", "text": "Write a short summary", "state": "understood"},
            {
                "kind": "where",
                "text": f"Post it in {place.group(1).capitalize()}",
                "state": "understood",
            },
        ]
    return [{"kind": "do", "text": first_up(act), "state": "understood"}, where_row(task)]


def obey_fooling_orders(sentences: list[str]) -> list[dict[str, Any]]:
    orders = [s.rstrip(".!?").split(" and ", 1)[-1] for s in sentences if FOOLING_ORDER.search(s)]
    return [{"kind": "do", "text": first_up(order), "state": "understood"} for order in orders]


def understanding(task: str) -> dict[str, Any]:
    if (word := RELEASE_WORDS.search(task)) is not None:
        named = next((name for name in SOFTWARE if name.lower() in task.lower()), None)
        return {
            "belongs_on_watchlist": True,
            "watchlist_word": word.group(0),
            "software": named,
            "rows": [],
        }
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", task.strip()) if part]
    first = sentences[0].rstrip(".!?") if sentences else ""
    when = SCHEDULE.search(first)
    rows: list[dict[str, Any]] = [
        {"kind": "schedule", "text": first_up(when.group(0)), "state": "understood"}
        if when
        else {"kind": "schedule", "state": "missing", "note": "You didn't say when it runs."}
    ]
    words = (SCHEDULE.sub("", first) if when else first).strip(" ,")
    found = FIND.match(words)
    look, act = (found.group(1), found.group(2)) if found else (None, words or None)
    if look is None and act is not None and (of := FOUND.search(act)) is not None:
        look = of.group(1)
    rows += [look_row(look), *fooled_action_rows(act, task)]
    rows += obey_fooling_orders(sentences[1:])
    return {"belongs_on_watchlist": False, "rows": rows}


def forced(body: dict[str, Any], name: str) -> dict[str, Any]:
    lowered = name.lower()
    if mode == "broken":
        return call(name, BROKEN, 0)
    if "draft" in lowered:
        return call(name, DRAFT, 0)
    if "choice" in lowered:
        return call(name, choice(task_text(body)), 0)
    if "understand" in lowered:
        return call(name, understanding(task_text(body)), 0)
    return say(SENTENCE)


def history(body: dict[str, Any]) -> tuple[dict[str, int], str]:
    """How many times each tool was called, and all the text tools gave back."""
    calls: dict[str, int] = {}
    results: list[str] = []
    for item in body.get("messages", []):
        for block in blocks_of(item):
            if block.get("type") == "tool_use":
                calls[str(block.get("name"))] = calls.get(str(block.get("name")), 0) + 1
            elif block.get("type") == "tool_result":
                results.append(text_of(block.get("content")))
    return calls, "\n".join(results)


def run_step(body: dict[str, Any]) -> dict[str, Any]:
    """The next move of a card run: the offered steps in order, each once, and the ticket again
    if the first one was a fooled one."""
    system = system_text(body)
    values = INPUT_LINE.findall(system)
    repo = next((v for v in values if REPO.fullmatch(v)), "unknown/unknown")
    project = next((v for v in values if PROJECT.fullmatch(v)), "MOCK")
    offered = {str(tool.get("name")) for tool in body.get("tools", [])}
    calls, seen = history(body)
    planted = PLANTED.search(seen)
    tag = VERSION.search(seen)
    version = tag.group(0) if tag else "unknown"
    number = sum(calls.values())
    if "github_read_releases" in offered and "github_read_releases" not in calls:
        return call("github_read_releases", {"repo": repo}, number)
    if "jira_search" in offered and "jira_search" not in calls:
        return call("jira_search", {"project": project}, number)
    attempts = calls.get("jira_create_ticket", 0)
    fooled = planted is not None
    if "jira_create_ticket" in offered and (attempts == 0 or (fooled and attempts == 1)):
        title = (
            f"New release {version} of {repo}"
            if "github_read_releases" in offered
            else f"Summary of finished tickets in {project}"
        )
        ticket: dict[str, Any] = {"title": title, "body": f"Proposed for {project}."}
        if fooled and attempts == 0:
            ticket["project"] = planted.group(1)  # pyright: ignore[reportOptionalMemberAccess]
        return call("jira_create_ticket", ticket, number)
    return say(f"I finished my plan for {project}. I proposed one ticket for it.")


def set_mode(body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    global mode
    wanted = (body or {}).get("mode")
    if wanted not in MODES:
        return 400, {"error": f"mode must be one of {', '.join(MODES)}"}
    mode = str(wanted)
    return 200, {"mode": mode}


def delay(method: str, path: str) -> float:
    return SLOW_SECONDS if mode == "slow" and (method, path) == ("POST", "/v1/messages") else 0.0


def answer(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    """The mock's whole behaviour: no sockets, so tests can call it directly."""
    if method == "GET" and path == "/healthz":
        return 200, {"status": "ok"}
    if method == "POST" and path == "/_admin/mode":
        return set_mode(body)
    if method == "GET" and path == "/v1/models":
        return 200, {
            "data": [
                {
                    "type": "model",
                    "id": MODEL,
                    "display_name": "Mock model",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
            "has_more": False,
        }
    if method == "POST" and path == "/v1/messages" and body is not None:
        chosen = body.get("tool_choice")
        if isinstance(chosen, dict):
            wanted = cast("dict[str, Any]", chosen)
            if wanted.get("type") == "tool":
                return 200, forced(body, str(wanted.get("name", "")))
        if body.get("tools"):
            return 200, run_step(body)
        return 200, say(SENTENCE)
    return 404, {"type": "error", "error": {"type": "not_found_error", "message": "Not found"}}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.reply(*answer("GET", self.path, None))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            self.reply(400, {"type": "error", "error": {"type": "invalid_request_error"}})
            return
        time.sleep(delay("POST", self.path))
        self.reply(*answer("POST", self.path, body if isinstance(body, dict) else None))  # pyright: ignore[reportUnknownArgumentType]

    def log_message(self, format: str, *args: Any) -> None:
        return


def build_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    where = argparse.ArgumentParser(description="The mock model.")
    where.add_argument("--host", default="0.0.0.0")
    where.add_argument("--port", type=int, default=8300)
    listen = where.parse_args()
    build_server(listen.host, listen.port).serve_forever()
