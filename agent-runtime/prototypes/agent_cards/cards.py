"""PROTOTYPE, throwaway. The part worth keeping if agent cards go ahead: the tool list, the card
and choice shapes, the two prompts, and the checks the platform would run on a drafted card."""

from typing import Any

# The fixed part: tools we would build and test. The model may only pick from these.
CATALOG: dict[str, tuple[str, str]] = {
    "github.read_releases": ("read", "Read the releases of a public GitHub repository"),
    "gitlab.list_members": ("read", "List who has access to a GitLab group or project, and at what level"),
    "gitlab.remove_member": ("write", "Remove a person's access from a GitLab group or project"),
    "entra.list_group_members": ("read", "List the members of a Microsoft Entra ID group, such as an admin group"),
    "admin_tool.list_accounts": ("read", "List the accounts in one of the team's admin tools"),
    "jira.search": ("read", "Find Jira tickets with a search"),
    "jira.read_ticket": ("read", "Read one Jira ticket and its comments"),
    "jira.create_ticket": ("write", "Create a Jira ticket"),
    "jira.comment": ("write", "Add a comment to a Jira ticket"),
    "jira.move_ticket": ("write", "Move a Jira ticket to another status, such as Done"),
    "confluence.search": ("read", "Find Confluence pages"),
    "confluence.read_page": ("read", "Read a Confluence page, including its tables"),
    "confluence.update_page": ("write", "Change a Confluence page"),
    "teams.post_message": ("write", "Post a message in a Teams chat or channel"),
    "teams.ask_person": ("write", "Ask one person a question in Teams and wait for their answer"),
}
ACCESS_CHANGING = {"gitlab.remove_member"}
OLD_NAMES = {"flint", "forge", "striker", "spark map", "scout", "analyst", "messenger", "clerk",
             "fixer", "kindling", "firebreak", "ember"}


def catalog_text() -> str:
    return "\n".join(f"- {tool} ({kind}): {what}" for tool, (kind, what) in CATALOG.items())


CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "can_do": {"type": "boolean", "description": "False when this platform should not take the task on."},
        "why_not": {"type": "string", "description": "When can_do is false, why, in one or two sentences."},
        "name": {"type": "string", "description": "2 to 4 plain words saying what the agent does."},
        "purpose": {"type": "string", "description": "One sentence. The Room lead matches new tasks against it."},
        "good_for": {"type": "array", "items": {"type": "string"},
                     "description": "3 short requests a staff member might type that this agent fits."},
        "inputs": {"type": "array", "description": "What the operator gives each time the agent runs.",
                   "items": {"type": "object", "properties": {
                       "name": {"type": "string"}, "what": {"type": "string"}, "example": {"type": "string"}},
                       "required": ["name", "what", "example"]}},
        "steps": {"type": "array", "description": "The plan, in order.",
                  "items": {"type": "object", "properties": {
                      "say": {"type": "string", "description": "The step in plain English."},
                      "tool": {"type": ["string", "null"], "description": "A tool id from the list, or null for a step that only thinks or sorts."}},
                      "required": ["say", "tool"]}},
        "approvals": {"type": "array",
                      "description": "One entry per write tool the steps use: how many approvers. The platform picks who.",
                      "items": {"type": "object", "properties": {
                          "tool": {"type": "string"},
                          "approvers": {"type": "integer", "minimum": 1, "maximum": 2},
                          "why": {"type": "string"}},
                          "required": ["tool", "approvers", "why"]}},
        "missing_tools": {"type": "array", "description": "What the task needs that the tool list lacks.",
                          "items": {"type": "object", "properties": {
                              "need": {"type": "string"}, "why": {"type": "string"}},
                              "required": ["need", "why"]}},
        "questions": {"type": "array", "items": {"type": "string"},
                      "description": "What you had to guess and should ask the operator before saving."},
    },
    "required": ["can_do", "name", "purpose", "good_for", "inputs", "steps", "approvals",
                 "missing_tools", "questions"],
}

CHOICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["use_one", "use_several", "new_agent", "cannot_do"]},
        "agents": {"type": "array", "description": "The saved agents brought in, in the order they work.",
                   "items": {"type": "object", "properties": {
                       "agent": {"type": "string", "description": "The saved agent's name, exactly."},
                       "part": {"type": "string", "description": "What this agent does in this task."},
                       "inputs": {"type": "object", "additionalProperties": {"type": "string"},
                                  "description": "Its inputs, filled from the task where the task says them."}},
                       "required": ["agent", "part", "inputs"]}},
        "new_agent": {"type": "string", "description": "When decision is new_agent, what the new agent should do."},
        "reason": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"},
                      "description": "What is still missing to start, to ask the staff member."},
    },
    "required": ["decision", "agents", "reason", "questions"],
}

DRAFT_SYSTEM = f"""You draft agent cards for a platform used by the support staff of CODESparks, a team in NCS.
The staff are not technical. They describe a repetitive task, and you draft one agent that does it.
An agent card is data, not code. The agent can only use these tools:

{catalog_text()}

Rules:
- Use only tool ids from the list. If the task needs something the list lacks, add it to missing_tools and plan the parts you can do.
- The platform asks for approval in Teams by itself before every write step runs, and waits for the answer.
  Never add a step that asks for approval, and never use a Teams tool to ask for approval.
- Under approvals, list each write tool the steps use and how many approvers it needs. Use 1 normally.
  Use 2, one after the other, when the write changes someone's access, or when the staff member asks for two.
  Do not say who approves. The platform picks the Approvers, and never the person who started the run.
- Set can_do to false when the task is critical or risky to automate, or is not Jira, Confluence, GitHub, GitLab, Entra ID or Teams work.
- Name the agent plainly by what it does, such as "Release checker". No made-up or themed names.
- inputs are what changes between runs, such as a repository or a Jira project. Do not list fixed things as inputs.
- Do not invent facts such as Jira project keys, page names or people. Make them inputs, or ask in questions.
- Write for non-technical staff: plain English, short sentences, no jargon."""

CHOOSE_SYSTEM = """You are the Room lead on a platform used by the support staff of CODESparks, a team in NCS.
A staff member describes a task. You see the agents the team has saved. Decide one of:
- use_one: one saved agent fits the task, even if the wording differs.
- use_several: the task has distinct parts, and different saved agents each do one part. List them in the order they work.
- new_agent: no saved agent fits well. Do not stretch an agent past its purpose. Say what the new agent should do.
- cannot_do: the task is critical or risky to automate, or is not Jira, Confluence, GitHub, GitLab, Entra ID or Teams work.
Fill each chosen agent's inputs from the task where the task says them. Never invent a value.
Put anything still missing in questions. Write in plain English for non-technical staff."""


def card_for_choice(card: dict[str, Any]) -> str:
    inputs = ", ".join(i["name"] for i in card.get("inputs", [])) or "none"
    tools = ", ".join(sorted({s["tool"] for s in card.get("steps", []) if s.get("tool")})) or "none"
    good = "; ".join(card.get("good_for", []))
    return f"- {card['name']}: {card['purpose']}\n  Good for: {good}\n  Inputs: {inputs}\n  Tools: {tools}"


def check_card(card: dict[str, Any]) -> list[str]:
    """What the platform would refuse or flag before an Operator could save the card."""
    if not card.get("can_do", True):
        return []
    problems = []
    used = [s.get("tool") for s in card.get("steps", []) if s.get("tool")]
    for tool in sorted(set(used) - CATALOG.keys()):
        problems.append(f"Uses a tool that does not exist: {tool}")
    writes = {t for t in used if CATALOG.get(t, ("",))[0] == "write"}
    approved = {a["tool"]: a for a in card.get("approvals", [])}
    for tool in sorted(writes - approved.keys()):
        problems.append(f"Writes with {tool} but names no approval for it")
    for tool in sorted(approved.keys() - writes):
        kind = CATALOG.get(tool, ("unknown",))[0]
        problems.append(f"Names an approval for {tool}, which the steps never use"
                        + (" (it only reads)" if kind == "read" else ""))
    for tool in sorted(writes & ACCESS_CHANGING):
        if tool in approved and approved[tool]["approvers"] < 2:
            problems.append(f"{tool} changes someone's access but has only 1 approver")
    for step in card.get("steps", []):
        if (step.get("tool") or "").startswith("teams.") and "approv" in step.get("say", "").lower():
            problems.append(f"Adds its own approval step with {step['tool']}; the platform asks for approval itself")
    if any(old in card.get("name", "").lower() for old in OLD_NAMES):
        problems.append(f"Uses an old themed name: {card['name']}")
    if not card.get("steps"):
        problems.append("Has no steps")
    return problems


def compare_cards(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """How two drafts of the same task differ in what matters: what it may touch and who must agree."""
    if a.get("can_do") != b.get("can_do"):
        return ["One run says it can do the task, the other says it can't"]
    if not a.get("can_do"):
        return []
    tools = lambda card: {s["tool"] for s in card.get("steps", []) if s.get("tool")}  # noqa: E731
    approvals = lambda card: {x["tool"]: x["approvers"] for x in card.get("approvals", [])}  # noqa: E731
    differences = []
    if only := sorted(tools(a) - tools(b)):
        differences.append(f"Only run 1 uses {', '.join(only)}")
    if only := sorted(tools(b) - tools(a)):
        differences.append(f"Only run 2 uses {', '.join(only)}")
    for tool in sorted(approvals(a).keys() & approvals(b).keys()):
        if approvals(a)[tool] != approvals(b)[tool]:
            differences.append(f"{tool}: {approvals(a)[tool]} approver(s) in run 1, {approvals(b)[tool]} in run 2")
    if len(a.get("inputs", [])) != len(b.get("inputs", [])):
        differences.append(f"{len(a['inputs'])} inputs in run 1, {len(b['inputs'])} in run 2")
    return differences


def compare_choices(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    differences = []
    if a["decision"] != b["decision"]:
        differences.append(f"Decided {a['decision']} in run 1, {b['decision']} in run 2")
    if len(a.get("agents", [])) != len(b.get("agents", [])):
        differences.append(f"{len(a['agents'])} agents in run 1, {len(b['agents'])} in run 2")
    return differences


def check_choice(choice: dict[str, Any], saved: list[str]) -> list[str]:
    problems = []
    named = [a["agent"] for a in choice.get("agents", [])]
    for name in named:
        if name not in saved:
            problems.append(f"Brings in an agent that is not saved: {name}")
    expected = {"use_one": 1, "cannot_do": 0, "new_agent": 0}.get(choice["decision"])
    if expected is not None and len(named) != expected:
        problems.append(f"Says {choice['decision']} but brings in {len(named)} agents")
    if choice["decision"] == "use_several" and len(named) < 2:
        problems.append("Says use_several but brings in fewer than 2 agents")
    return problems
