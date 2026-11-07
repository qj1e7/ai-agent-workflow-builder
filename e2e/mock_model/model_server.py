"""A tiny stand-in for an Anthropic Messages API, for the end to end tests.

It answers by what a request asks for, so the real runtime, with its real prompts and schemas,
can be tested without a real model:

- GET /v1/models lists one model.
- A request that forces a tool is a draft, a choice, the Planner reading a task back, or the
  Planner reading a request typed on Home (TaskRead). The canned answer follows the task's words.
  A TaskRead fills the structures the real model is asked for: the ticket search (project, kinds
  of ticket, open or done, the days since an update), what happens with what was found (one new
  ticket that lists, counts or sums them up), the project it goes in, the schedule, and the skip
  question for a few plain phrasings, such as "no human in the loop". A detail the search can't
  filter by (a priority such as P1, a component, a reporter) is left out of the structures, as
  the real model is told to leave it, and so is an email. A task that names a GitHub repository
  picks the Version checker, any other gets a drafted agent (a follow-up one for a follow-up
  ticket task, else a summary one), and a release task belongs on the Software watchlist unless
  it also asks for
  known vulnerabilities. One named part, such as "Where it goes: Jira project MOCK", is read as
  that part alone, the others missing. When the Planner says before the task that the staff
  member already chose a new workflow, a release task is read back in parts like any other, as
  the real model does.
- A request with tools and no forced tool is a card run. The mock calls github_read_releases,
  then jira_search, then jira_create_ticket, then writes a report, by what the conversation holds.
  The ticket's title follows the card: a release, a follow-up or a summary. The follow-up card
  searches for bug tickets with no update for the days its plan names, working the day out from
  the date in the prompt, and its ticket body lists the tickets the search returned.
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
from datetime import date, timedelta
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
RELEASE_WORDS = re.compile(r"\b(?:releases?|versions?|upgrades?|patch(?:es)?)\b", re.IGNORECASE)
VULNERABILITY_WORDS = re.compile(
    r"\b(?:vulnerab\w*|cves?|nvd|advisor(?:y|ies)"
    r"|security (?:fix(?:es)?|patch(?:es)?|alerts?|bulletins?))\b",
    re.IGNORECASE,
)
EMAIL_WORDS = re.compile(r"\be-?mail\b", re.IGNORECASE)
TICKET_WORDS = re.compile(r"\b(?:tickets?|jira)\b", re.IGNORECASE)
SOFTWARE = (
    "LangGraph",
    "Redis",
    "FastAPI",
    "PostgreSQL",
    "Terraform",
    "Log4j",
    "Kubernetes",
    "React",
)
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
ONE_PART = re.compile(r"^(When|Looks for|Does|Where it goes): (.+)$", re.DOTALL)
CARRIED_ON = re.compile(r"\bset belongs_on_watchlist to false\b")
TASK_MARK = "The task:\n"
REQUEST_MARK = "The request:\n"
ABOUT = (
    (
        re.compile(
            r"\bwhy\b.*\b(?:stop|stopped|fail|failed|broke|broken|went wrong)\b"
            r"|^what (?:went wrong|happened)\b",
            re.IGNORECASE,
        ),
        "why_stopped",
    ),
    (
        re.compile(
            r"^(?:what needs me|what do i need to do|what(?:'s| is) (?:waiting|for me)"
            r"|(?:is )?(?:there )?anything (?:to approve|waiting|for me)"
            r"|my (?:to-?do|approvals?))\b",
            re.IGNORECASE,
        ),
        "needs_me",
    ),
    (
        re.compile(
            r"^(?:check|how are|show(?: me)?|see) (?:my |the |our |all )?workflows?\b"
            r"|^(?:is|are) .*\b(?:running|working|on|stopped|paused)\s*\?*$",
            re.IGNORECASE,
        ),
        "my_workflows",
    ),
    (
        re.compile(r"^what can you do|^what do you do|^help\b|\bweather\b|\bjoke\b", re.IGNORECASE),
        "abilities",
    ),
)
WORKFLOW_NAMED = re.compile(
    r"(?:why did|is|are)\s+(?:the\s+)?(.+?)\s+"
    r"(?:stop|stopped|fail|failed|running|working|on|paused)\b",
    re.IGNORECASE,
)
CLAUSE = re.compile(r"\s+and\s+|,\s*(?:then\s+)?")
SKIP_WORDS = re.compile(
    r"\b(?:no human in the loop|pre-approved|approvals? (?:turned )?off|approve it as me"
    r"|no need to ask me or anyone|don't ask me or \w+)\b",
    re.IGNORECASE,
)
ONLY_ME_WORDS = re.compile(
    r"\b(?:without asking me(?: each time)?|don't ping me|leave me out of it)\b", re.IGNORECASE
)
TYPE_WORDS = re.compile(
    r"\b(bugs?|tasks?|stor(?:y|ies)|epics?|sub-?tasks?|incidents?)\b", re.IGNORECASE
)
STATUS_WORDS = {"open": "open", "unresolved": "open", "closed": "done", "done": "done"}
NO_UPDATE = re.compile(r"\bno update for (\d+) days?\b", re.IGNORECASE)
CREATES = re.compile(
    r"\b(?:create|make|raise|file|open|propose|put)\b[^,;.]*?\b(?:ticket|tickets|one)\b",
    re.IGNORECASE,
)
SAYS = (
    (re.compile(r"\bcount\b", re.IGNORECASE), "count"),
    (re.compile(r"\bsum(?:mar\w*)?\b", re.IGNORECASE), "summary"),
)
OWNERS = re.compile(r"\b(?:owners?|assignees?|who owns)\b", re.IGNORECASE)
PART_KINDS = {"When": "schedule", "Looks for": "look_for", "Does": "do", "Where it goes": "where"}
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
FOLLOW_UP = re.compile(r"\bfollow[- ]?up\b", re.IGNORECASE)
FOLLOW_UP_DRAFT: dict[str, Any] = {
    **DRAFT,
    "name": "Stale bug follow-up",
    "purpose": "Finds bug tickets in one Jira project that have had no update for a while, and "
    "proposes one follow-up ticket that lists them.",
    "good_for": ["Follow up stale bug tickets"],
    "inputs": [
        {
            "name": "Jira project",
            "kind": "jira_project",
            "what": "The project to look in, and where the follow-up ticket goes.",
            "example": "MOCK",
        }
    ],
    "blocks": [
        {"say": "Find bug tickets with no recent update.", "tool": "jira.search"},
        {"say": "Propose one follow-up ticket that lists them.", "tool": "jira.create_ticket"},
    ],
}
CARD_NAME = re.compile(r"^Agent card: (.+)$", re.MULTILINE)
DAYS = re.compile(r"\b(\d+)\s+days?\b", re.IGNORECASE)
TODAY = re.compile(r"Today is [^(\n]*\((\d{4}-\d{2}-\d{2})\)")
LAST_RUN = re.compile(r"started on [^(\n]*\((\d{4}-\d{2}-\d{2})\)\. For tickets since the last run")
STALE_STEP = re.compile(r"no update for (\d+) days?", re.IGNORECASE)
FOUND_KEY = re.compile(r'"key": "([A-Z][A-Z0-9_]*-\d+)"')


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
    text = user_text(body)
    mark = REQUEST_MARK if REQUEST_MARK in text and TASK_MARK not in text else TASK_MARK
    return text.rpartition(mark)[2]


def says_carried_on(body: dict[str, Any]) -> bool:
    """Whether the Planner's note before the task says the staff member already chose a new
    workflow over the Software watchlist. Only the words before the first "The task:" line
    count, so a task that carries its own such line cannot set it."""
    return CARRIED_ON.search(user_text(body).partition(TASK_MARK)[0]) is not None


def choice(task: str) -> dict[str, Any]:
    words = task.lower()
    if "book" in words and "room" in words:
        return {
            "decision": "cannot_do",
            "agents": [],
            "reason": "No calendar tool.",
            "questions": [],
        }
    if "summar" in words or REPO.search(task) is None:
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


def parts(task: str) -> list[dict[str, Any]]:
    if (named := ONE_PART.match(task.strip())) is not None:
        kind = PART_KINDS[named.group(1)]
        return [
            {"kind": each, "text": named.group(2), "state": "understood"}
            if each == kind
            else {"kind": each, "state": "missing"}
            for each in PART_KINDS.values()
        ]
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
    return rows


def no_vulnerability_tool(row: dict[str, Any]) -> dict[str, Any]:
    text = row.get("text", "")
    if VULNERABILITY_WORDS.search(text) is None or TICKET_WORDS.search(text) is not None:
        return row
    return {**row, "state": "cant_do", "note": "No tool checks for known vulnerabilities yet."}


def understanding(task: str, carried_on: bool = False) -> dict[str, Any]:
    word = RELEASE_WORDS.search(task)
    if not carried_on and word is not None and VULNERABILITY_WORDS.search(task) is None:
        named = next((name for name in SOFTWARE if name.lower() in task.lower()), None)
        return {
            "belongs_on_watchlist": True,
            "watchlist_word": word.group(0),
            "software": named,
            "rows": [],
        }
    return {"belongs_on_watchlist": False, "rows": [no_vulnerability_tool(r) for r in parts(task)]}


def follow_up_draft(task: str) -> dict[str, Any]:
    """The follow-up card, with the days the staff member named in its search step."""
    named = DAYS.search(task)
    if named is None:
        return FOLLOW_UP_DRAFT
    first, *rest = FOLLOW_UP_DRAFT["blocks"]
    search = {**first, "say": f"Find bug tickets with no update for {named.group(1)} days."}
    return {**FOLLOW_UP_DRAFT, "blocks": [search, *rest]}


def stale_search(system: str, project: str) -> dict[str, Any]:
    """The search a follow-up card asks for: bug tickets last updated on or before the day that
    is N days before the date in the prompt, and, when the prompt names the last run's day, only
    tickets created since then."""
    arguments: dict[str, Any] = {"project": project}
    days = STALE_STEP.search(system)
    today = TODAY.search(system)
    if days is not None and today is not None:
        cutoff = date.fromisoformat(today.group(1)) - timedelta(days=int(days.group(1)))
        arguments |= {"issue_type": "Bug", "updated_before": cutoff.isoformat()}
    last_run = LAST_RUN.search(system)
    if last_run is not None:
        arguments["created_since"] = last_run.group(1)
    return arguments


def name_of(task: str) -> str:
    first = re.split(r"(?<=[.!?])\s+", task.strip())[0].rstrip(".!?")
    words = SCHEDULE.sub("", first).strip(" ,").split()
    return first_up(" ".join(words[:5]))[:60] or "New workflow"


def search_of(look: str | None, task: str) -> dict[str, Any] | None:
    """The ticket search the real model is asked to fill in, from the words that say what to
    look for: the project, the kinds of ticket, open or done, and the days since an update."""
    if look is None or TICKET_WORDS.search(task) is None and TYPE_WORDS.search(task) is None:
        return None
    project = IN_PROJECT.search(task)
    status = next((v for w, v in STATUS_WORDS.items() if re.search(rf"\b{w}\b", look, re.I)), None)
    days = NO_UPDATE.search(look)
    stale = "stale" in look.lower() and days is None
    return {
        "project": project.group(1) if project else None,
        "issue_types": sorted({m.group(1).lower() for m in TYPE_WORDS.finditer(look)}),
        "status": status,
        "assignee": None,
        "created": None,
        "updated": {"how": "before", "days": int(days.group(1))}
        if days
        else ({"how": "before", "days": 14} if stale else None),
        "done": None,
        "words": None,
        "said": look,
    }


def ticket_of(act: str | None, task: str) -> dict[str, Any] | None:
    """What happens with what was found, as the real model is asked to fill it in: a new ticket
    that lists, counts or sums up the tickets found. An email, a Teams post or a change to the
    tickets is no ticket, so it is left out and the platform shows it as a part it can't do."""
    if act is None or EMAIL_WORDS.search(act) or SUMMARY_TO.search(act):
        return None
    creates = CREATES.search(act) is not None
    says = next((name for pattern, name in SAYS if pattern.search(act)), "list")
    if not creates and FIND.match(act) is None and says == "list" and "list" not in act.lower():
        return None
    return {
        "creates": creates,
        "says": says,
        "shows": ["owner"] if OWNERS.search(task) else [],
        "said": act,
    }


def skip_read(task: str) -> dict[str, Any]:
    """Whose yes or attention the task asks to skip, as the real model is asked: an Approver's
    or anyone else's for a few plain phrasings, only the staff member's own for a few more."""
    found = SKIP_WORDS.search(task)
    if found is not None:
        return {"whose": "an_approver_or_anyone_else", "said": found.group(0)}
    found = ONLY_ME_WORDS.search(task)
    if found is not None:
        return {"whose": "only_me", "said": found.group(0)}
    return {"whose": "nobody", "said": None}


def structures(task: str) -> dict[str, Any]:
    """The task read into the structures the real model fills: schedule, search, ticket, place."""
    first = re.split(r"(?<=[.!?])\s+", task.strip())[0].rstrip(".!?") if task.strip() else ""
    when = SCHEDULE.search(first)
    words = (SCHEDULE.sub("", first) if when else first).strip(" ,")
    found = FIND.match(words)
    look, act = (found.group(1), found.group(2)) if found else (None, words or None)
    if look is None and act is not None and (of := FOUND.search(act)) is not None:
        look = of.group(1)
    if (
        look is None
        and act is not None
        and TICKET_WORDS.search(act)
        and CREATES.search(act) is None
    ):
        look, act = act, None
    project = IN_PROJECT.search(task)
    return {
        "schedule": first_up(when.group(0)) if when else None,
        "search": search_of(look, task),
        "ticket": ticket_of(act, task),
        "place": {"project": project.group(1), "said": project.group(0)} if project else None,
    }


def reading(task: str) -> dict[str, Any]:
    about = next((kind for pattern, kind in ABOUT if pattern.search(task.strip())), "none")
    if about != "none":
        named = WORKFLOW_NAMED.search(task) if about in ("why_stopped", "my_workflows") else None
        words = (
            named.group(1)
            if named and named.group(1).lower() not in ("my", "my workflow")
            else None
        )
        return {
            "asks_about": about,
            "workflow_words": words,
            "belongs_on_watchlist": False,
            "skips_the_yes": skip_read(task),
            "schedule": None,
            "search": None,
            "ticket": None,
            "place": None,
        }
    read: dict[str, Any] = {
        "asks_about": "none",
        "workflow_words": None,
        "skips_the_yes": skip_read(task),
        "schedule": None,
        "search": None,
        "ticket": None,
        "place": None,
    }
    understood = understanding(task)
    read["belongs_on_watchlist"] = understood["belongs_on_watchlist"]
    if read["belongs_on_watchlist"]:
        read["watchlist_word"] = understood["watchlist_word"]
        read["software"] = understood["software"]
        rest = " and ".join(c for c in CLAUSE.split(task) if not RELEASE_WORDS.search(c))
        if TICKET_WORDS.search(rest):
            read.update(structures(rest))
            read["name"] = name_of(rest)
        return read
    if VULNERABILITY_WORDS.search(task) and TICKET_WORDS.search(task) is None:
        read["name"] = name_of(task)
        return read
    read["name"] = name_of(task)
    read.update(structures(task))
    return read


def forced(body: dict[str, Any], name: str) -> dict[str, Any]:
    lowered = name.lower()
    if mode == "broken":
        return call(name, BROKEN, 0)
    if "draft" in lowered:
        return call(
            name,
            follow_up_draft(task_text(body)) if FOLLOW_UP.search(task_text(body)) else DRAFT,
            0,
        )
    if "choice" in lowered:
        return call(name, choice(task_text(body)), 0)
    if "taskread" in lowered:
        return call(name, reading(task_text(body)), 0)
    if "understand" in lowered:
        return call(name, understanding(task_text(body), says_carried_on(body)), 0)
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
    card = CARD_NAME.search(system)
    follow_up = card is not None and FOLLOW_UP.search(card.group(1)) is not None
    if "jira_search" in offered and "jira_search" not in calls:
        search = stale_search(system, project) if follow_up else {"project": project}
        return call("jira_search", search, number)
    attempts = calls.get("jira_create_ticket", 0)
    fooled = planted is not None
    if "jira_create_ticket" in offered and (attempts == 0 or (fooled and attempts == 1)):
        body_text = f"Proposed for {project}."
        if "github_read_releases" in offered:
            title = f"New release {version} of {repo}"
        elif follow_up:
            title = f"Bug tickets to follow up in {project}"
            body_text += " " + ", ".join(FOUND_KEY.findall(seen))
        else:
            title = f"Summary of finished tickets in {project}"
        ticket: dict[str, Any] = {"title": title, "body": body_text}
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
