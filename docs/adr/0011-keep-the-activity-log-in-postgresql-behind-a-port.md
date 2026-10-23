---
status: proposed
---

# Keep the activity log in PostgreSQL behind a port until we pick the NoSQL store

The rubric wants a NoSQL database, and the activity log looks like a natural fit. But which NoSQL store to use is still an open decision, and the skeleton should not depend on it. The activity log lives in PostgreSQL behind the `ActivityLog` port. Orchestration appends its events in the same transaction as the state change they report. Its database role has insert rights on the activity log for this, and on nothing else in run monitoring's schema. Each event has a per-run sequence number with no gaps, and a dedupe key so a repeated append does nothing. The live view gets events over server-sent events, and PostgreSQL's `LISTEN/NOTIFY` wakes each server replica when new events commit, so no message broker is needed.

## Considered options

- **Pick a NoSQL store now for the log.** It would tick the rubric box early, but it would make an open decision by default and add infrastructure before the skeleton runs.
- **A message broker for live events.** It adds a dependency that `LISTEN/NOTIFY` on our existing database already covers at our scale.

## Consequences

- The NoSQL decision stays open. When the team picks a store, the log is the first candidate for it.
- Moving the log out of PostgreSQL will need an outbox in orchestration, because today the append shares orchestration's transaction.
- The AI troubleshooter reads the same log, and failure reasons are typed, so it never parses log text.
