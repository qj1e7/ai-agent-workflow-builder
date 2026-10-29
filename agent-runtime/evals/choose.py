from pydantic import BaseModel

from agent_runtime.contract import LibraryCard, LibraryInput
from agent_runtime.drafting import CHOOSE_SYSTEM, ChoiceAnswer, library_text
from evals.checks import Check, check, no_jargon, no_themed_names
from evals.jobs import Answer, Case, Job

LIBRARY = [
    LibraryCard(
        card_id="crd_version_checker",
        name="Version checker",
        purpose="Checks a public GitHub repository for a new release and proposes a Jira "
        "ticket for it.",
        good_for=["Check a repository for new releases", "Raise a ticket for a new release"],
        inputs=[
            LibraryInput(name="GitHub repository", kind="github_repo"),
            LibraryInput(name="Jira project", kind="jira_project"),
        ],
        tools=["github.read_releases", "jira.search", "jira.create_ticket"],
    ),
    LibraryCard(
        card_id="crd_ticket_finder",
        name="Ticket finder",
        purpose="Finds Jira tickets in one project and reads them out. It never changes anything.",
        good_for=["Find tickets about a topic", "What is open in a project"],
        inputs=[LibraryInput(name="Jira project", kind="jira_project")],
        tools=["jira.search", "jira.read_ticket"],
    ),
    LibraryCard(
        card_id="crd_weekly_summary",
        name="Weekly finished tickets summary",
        purpose="Looks at the Jira tickets finished this week in one project and proposes a "
        "summary ticket for the team.",
        good_for=["Summarise what we finished this week", "Weekly report of closed tickets"],
        inputs=[LibraryInput(name="Jira project", kind="jira_project")],
        tools=["jira.search", "jira.create_ticket"],
    ),
]
SAVED = {card.card_id for card in LIBRARY}
INPUT_NAMES = {card.card_id: {i.name for i in card.inputs} for card in LIBRARY}


class ChooseCase(Case):
    task: str
    decision: str
    agents: list[str] = []
    ordered: bool = True
    values: dict[str, str] = {}
    may_also: dict[str, list[str]] = {}
    reference: ChoiceAnswer


def prompt(case: ChooseCase) -> str:
    return f"{CHOOSE_SYSTEM}\n\nSaved agents:\n{library_text(LIBRARY)}\n\nThe task:\n{case.task}"


def schema() -> type[BaseModel]:
    return ChoiceAnswer


def score(case: ChooseCase, answer: Answer) -> list[Check]:
    choice = answer.value
    if not isinstance(choice, ChoiceAnswer):
        return [check("answered", ["no structured answer"])]
    ids = [a.card_id for a in choice.agents]
    task = case.task.casefold()
    invented = [
        f"{name}={value!r}"
        for agent in choice.agents
        for name, value in agent.values.items()
        if value.strip()
        and value.casefold() not in task
        and value not in case.may_also.get(name, [])
    ]
    unknown_inputs = [
        f"{agent.card_id}: {name}"
        for agent in choice.agents
        if agent.card_id in SAVED
        for name in agent.values
        if name not in INPUT_NAMES[agent.card_id]
    ]
    right_agents = ids == case.agents if case.ordered else sorted(ids) == sorted(case.agents)
    stated = [
        f"{name}={want!r}"
        for name, want in case.values.items()
        if not any(a.values.get(name, "").casefold() == want.casefold() for a in choice.agents)
    ]
    text = f"{choice.reason} {' '.join(choice.questions)}"
    return [
        check("answered", []),
        check(
            "right_decision",
            [] if choice.decision == case.decision else [f"chose {choice.decision}"],
        ),
        check("right_agents", [] if right_agents else [f"brought in {ids}, wanted {case.agents}"]),
        check("only_saved_agents", sorted({i for i in ids if i not in SAVED})),
        check("inputs_exist", unknown_inputs),
        check("values_from_task", invented),
        check("states_given_values", stated),
        check(
            "describes_new_agent",
            []
            if choice.decision != "new_agent" or (choice.new_agent or "").strip()
            else ["no description of the new agent"],
        ),
        no_themed_names(text),
        no_jargon(text),
    ]


CHOOSE = Job(
    name="choose",
    title="Choose saved agents for a task",
    case_type=ChooseCase,
    prompt=prompt,
    schema=schema,
    score=score,
    judged=False,
)
