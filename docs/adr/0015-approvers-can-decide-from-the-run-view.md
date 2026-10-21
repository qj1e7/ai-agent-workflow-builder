---
status: proposed
---

# Approvers can decide from the run view

`AGENTS.md` asks for an ADR on any change to the approval gate. The gate's rules do not change. What changes is where an Approver can press Approve or Decline: the run view now shows the ticket and the two buttons at the approval stop, so the Approver decides with one click. The run view sends the same request as the approval page (`POST /api/v1/approvals/{id}/decisions` with the approval's digest), under the Approver's own sign-in, so the platform runs the same checks: not their own work, steps in order, and a refused decision when the ticket changed. The approval page stays, because the Teams card links to it.

## Consequences

- The buttons show only for a person the approval record says can decide (`you_can_decide`), and only while the run view shows the latest state of the run, never in a replay.
- The person who started the run sees why they cannot decide, in the platform's own words.
