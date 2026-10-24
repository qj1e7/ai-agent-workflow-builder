# Software watchlist: PR/FAQ

A one-page PR/FAQ, written from the Operator's side, for the software watchlist. The decisions behind it are in [ADR 0019](../adr/0019-watch-software-in-one-list-with-one-approval-per-check.md) and [ADR 0020](../adr/0020-our-api-keeps-schedules-and-one-n8n-workflow-asks-what-is-due.md).

## Press release (draft, internal)

**CODESparks keeps every tool up to date from one list**

*Support staff see what needs attention each week and approve all the week's upgrade tickets at once.*

CODESparks support staff look after dozens of tools. To find out which ones have a new release, they visit each project's page, compare versions by hand and raise a Jira ticket for each one. It is slow and easy to forget, and nobody can see at a glance where things stand.

The software watchlist does this for them. An Operator adds each tool once. Every Monday at 9:00 the platform checks all of them and sends one approval request to Teams, listing the tickets it wants to raise. An Approver approves the week's tickets with one click. When a ticket is marked Done, the list updates our version by itself.

The Portal's Software page shows what needs a person first: tools that are behind, checks that failed, and upgrades waiting to be confirmed. Everything up to date is folded away, so a list of 50 tools still shows only a handful of rows.

## FAQ for Operators and Approvers

**Do I still need the builder?**
For other tasks, yes. The watchlist replaces making one release check per tool.

**What if a tool can't be checked?**
It shows "Can't check" with the reason, for example GitHub's hourly limit. The other tools are still checked.

**Will I get a new ticket every week for the same update?**
No. While a tool has an open ticket, no second ticket is raised.

**Who can approve?**
Any Approver who neither owns the watchlist nor last saved its schedule. The request says who can't approve it and why.

**Can I approve only some of the tickets?**
Not in the first version. You approve or decline the whole check. Declined tickets are proposed again at the next check.

**Where does "our version" come from?**
You give it once when you add a tool, or leave it empty to start from the newest release. After that it changes when the tool's ticket is marked Done. Every version shows where it came from.

## FAQ for the team, the sponsor and the professor

**What is in the November MVP?**
The list, the schedule, one approval request per check, and our version updated from the closed ticket. All tools are read from GitHub releases, and tickets go to the practice Jira.

**What comes later?**
- Adding tools by name, with an AI model suggesting where each one publishes releases. This waits for the model decision.
- Package registries (PyPI, npm, Maven Central) and endoflife.date as sources.
- Security fixes from CVE databases such as OSV.dev.
- Reading our version from the running server, inside DevNet.

Each new source is an external dependency and gets an ADR first.

**Does this weaken the approval gate?**
No. Nothing is written without an Approver, and the request covers exactly the tickets it shows. A scheduled check counts as the schedule owner's work, so they can't approve it.

**Why not keep one use case per tool?**
40 tools would mean 40 use cases to maintain and up to 40 Teams cards a week.

**What could go wrong?**
- GitHub allows 60 calls an hour without a token, so a real list needs one.
- A wrong source gives wrong tickets, so the source shows on every row and in every ticket.
- If every Approver owns the watchlist or its schedule, nobody can approve. The Portal warns when that happens.

**How will we know it works?**
Targets to test with CODESparks staff:
- An Operator adds 10 tools and sees the first request in under 5 minutes.
- An Approver handles a week's updates with one decision.
- Nobody types a version after adding a tool.
