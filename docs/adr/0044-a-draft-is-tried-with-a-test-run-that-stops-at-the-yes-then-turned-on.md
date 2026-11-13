---
status: proposed
---

# A draft is tried with a test run that stops at the yes, then turned on

From the chat-first build plan (13 Nov 2026), item E2 and risk 3.5. The design target is the chat-first sketch, `docs/design/chat-first/prototype.html`.

This changes what a run does at the approval gate, so `AGENTS.md` requires an ADR.

In the sketch, `Set up` builds the workflow as a draft, the Tester does a test run along it, and only then does the Operator press `Turn it on`. Today `POST /api/v1/agent-use-cases` makes the workflow already on, and a test run is a real run: it proposes a write and waits for an Approver's yes, then writes. If the set-up card waited for that test run to finish, the Operator would sit waiting for an Approver before the workflow is even on. The sketch's `Test run passed on practice Jira.` reads as a write made with no yes, which would be the only write in the platform without an Approver.

## Decision

**A workflow can start as a draft.** `POST /api/v1/agent-use-cases` takes `on`, true when left out. With `on: false` the workflow is made with its version 1 and its schedule, in the state `draft`. A draft never runs on its schedule: the schedule tick is told it is not on, and its slots are used up as for a paused workflow. Run now on a draft is refused (409). Its versions list is empty, because nothing is published yet. Saving its schedule changes the draft and publishes no version. Pause and resume leave a draft a draft. Delete and restore work as for any workflow.

**A test run of a draft stops at the approval gate.** The builder marks the run's spec `stops_at_gate` when the workflow is a draft at the moment the run starts, read under the workflow's lock. The work leg runs as usual: the agents run, and a write they propose is recorded with its digest. The run's events show what it would have written (`write_action_proposed`). The run view does not carry the proposal. When n8n calls the approval step, orchestration opens no approval request, posts nothing to Teams and asks nobody for a yes. The step finishes with the outcome `test_passed`, and the run succeeds with the outcome `test_passed`: "Test run passed up to the yes. Nothing was written." No act leg is queued. A test run that finds nothing to write ends `nothing_to_write`, as any run does. The mark is fixed when the run starts, so turning the draft on while its test run goes changes nothing for that run.

**The safety checker is unchanged.** A test run of a draft never has an approval, so it can never reach the write step. If the write step is called for it anyway, the referee refuses it before the checker runs, and the run log says the safety checker blocked a write action, as for any write called out of order. The checker still denies by default, and it is still the only code that can issue an `AuthorizedWrite`.

**Turn it on publishes version 1.** `POST /api/v1/use-cases/{use_case_id}/turn-on` turns a draft on. Version 1 is saved when the draft is set up. Turning it on makes it the published version, so the versions list is empty before and shows version 1 after. Its next run is the next slot of its schedule, and a slot that fell while it was a draft never starts. Turning on a workflow that is on, or one that was turned on and paused since, changes nothing and answers the same view. Only an Operator may turn a workflow on. It is not a write to Jira or Teams, so it needs no approval.

## What stays the same

- Every write waits for an Approver's yes. An Approver never approves their own work, and a rule that asks for two Approvers asks them in turn.
- A test run of a workflow that is on still asks for a yes and writes like any other run.
- The referee table, the safety checker, the digest, and the approval request and its Teams card.

## Considered options

- **Let the test run write to the practice Jira without a yes.** It matches the sketch's words, but it is a write with no Approver, which `AGENTS.md` forbids. Rejected.
- **Approve the test run automatically.** Same problem: the yes would come from no person. Rejected.
- **Stop the test run when the agents finish, before the approval step.** Simpler, but the run line would never reach the gate, and the n8n approval node would not be tried. Rejected.
- **Make every test run stop at the gate.** It would change Do a test run on workflows that are on, which the team relies on to try a real write with a real yes. Rejected for now.
- **End the test run as `nothing_to_write`.** It needs no new outcome, but it is untrue: there was something to write. Rejected.

## Consequences

- The Portal's set-up card can build, test and turn on a workflow without waiting for an Approver, and its words say what was and wasn't done.
- The Workflows page and the Planner see a fourth workflow state, `draft`.
- `RunOutcome` and `StepOutcome` gain `test_passed`, so the Portal labels it.
