"""The how-to notes the free reply reads beside the capability registry (ADR 0047).

Each line is one plain sentence about how to use the app. A test runs the free reply's own
checks on every line, so the notes never say that an unbuilt thing works, that anything was
done, or that a change can skip a yes."""

from typing import Final

HOW_TO: Final = (
    "To start, type what you want done in the box on Home, in your own words, such as Check "
    "LangGraph for new releases.",
    "A workflow is a task that runs again and again on a schedule, such as every Monday at 9am.",
    "The Planner is the assistant in the box on Home. You tell it a task your team does again "
    "and again, and it turns it into a workflow on a set-up card for you to check.",
    "Each part of the card has a tick, a cross, or a question for you to answer.",
    "An Operator can change any part of the card, then press Set up for a test run that writes "
    "nothing.",
    "If the test run passes, the Operator presses Turn it on.",
    "A card you leave stays as a draft by itself. It shows on Workflows marked Draft, and "
    "opening it brings the card back to the chat.",
    "Anything that writes data, such as a new Jira ticket, waits for an Approver's yes in Teams.",
    "The person who asked is never the Approver of their own request.",
    "Operators set up and change workflows, and Approvers say yes or no to requests.",
    "The rail on the left opens Chat, Workflows and the Watchlist.",
    "Needs you lists what waits for you, such as a request to approve or a run that stopped.",
    "The Watchlist holds the software your team runs, and it checks GitHub for new releases on "
    "one schedule.",
    "To add software to the Watchlist, open the Watchlist and fill in Add software, or type "
    "Check and its name in the box, such as Check LangGraph for new releases.",
    "To take software off the Watchlist, type Remove and its name in the box, such as Remove "
    "LangGraph from the Watchlist, or press Remove from watchlist on the Watchlist. Undo puts it "
    "back.",
    "To change when a workflow runs, say so in the box, such as Move the morning check to 10am.",
    "To pause a workflow, type Pause and its name, and type Resume and its name to turn it back "
    "on.",
    "To see what a workflow does, type Explain and its name in the box, such as Explain the "
    "morning check, or press Explain on its row in Workflows.",
    "When a run stops, the AI troubleshooter explains why, and an Operator can retry it.",
    "To report a problem, or to ask for something the Planner can't do yet, tap Ask the team.",
)
