---
status: proposed
---

# Watch software in one list, with one run and one approval request per check

CODESparks staff keep many tools up to date. Today each tool needs its own use case, typed into the builder with its GitHub name and the last version seen, and each run sends its own approval request. With 40 tools that is 40 use cases to set up and up to 40 Teams cards a week. So a team keeps its tools in one watchlist instead. The watchlist is a use case of a new template, and a check is one run of it. The work leg reads the newest version of every watched software, and the proposal holds one ticket for each software that is behind and has no open ticket yet. The Approver approves all of a check's tickets with one decision, which is what the glossary already means by one request covering one proposal.

Our version is given once, when software is added. Left empty, the newest release at that moment counts as ours, as `last_seen_tag` works today. After that it moves only on evidence: when the ticket raised for a software is marked Done, our version becomes the version that ticket named. The platform keeps where each version came from, for example "From MOCK-7, marked Done on 23 Oct", so an Operator can trust the number without asking anyone. Reading the version from the running server or the build file is Phase 2, inside DevNet.

In the MVP every source is GitHub releases, read by the release checker we already have. Each watched software names its source as a kind and a reference (for now always `github` and `owner/name`), so package registries, endoflife.date and CVE databases can be added later. Each new source is a new external dependency and gets its own ADR. Matching a typed name to a source with an AI model waits for the model decision.

## Considered options

- **Keep one use case per tool and group their requests in the Portal.** The run model would not change, but one request would then cover proposals from several runs. That breaks the rule that an Approver approves exactly one proposal by quoting its digest (ADR 0008). Changing the schedule or the Jira project would also mean editing every use case.
- **One run per tool, all started together.** Each run stays small and fails alone, but an Approver gets one Teams card per tool, which is the noise the sponsor wants to avoid.
- **Let the Approver untick single tickets.** Useful, but the digest covers the whole proposal, so approving part of one changes the approval gate and needs its own ADR. For now an Approver approves or declines the whole check.

## Consequences

- A check that cannot read one tool does not fail. That tool shows "Can't check" with the reason, and the rest of the check carries on. A check fails only when it can read none of its tools.
- At most one ticket is open per watched software. A newer release found while a ticket is open does not raise a second ticket.
- Declining a check declines all its tickets. The next check proposes them again.
- The run spec and the release checker's task carry a list of watched software instead of one repository. The contract in `contracts/` changes, so platform-api, agent-runtime and the Portal change together.
- The list (what we watch and where we read it) is part of the use case, so adding or removing software makes a new use case version, and each check records the version it used. Our version, where it came from and the open ticket are facts the platform learns. They live in orchestration beside the runs and never make a new use case version.
- A check makes at least one GitHub call per tool. GitHub allows 60 calls an hour without a token, so a real list needs `GITHUB_TOKEN`.
- The practice Jira needs a ticket status and a way to mark a ticket Done, so the demo can show our version moving by itself. Reading a status is a read, so it needs no approval.
- As for any run today, the watchlist's owner and anyone who retries a check can never approve it. ADR 0020 says who starts a scheduled check.
