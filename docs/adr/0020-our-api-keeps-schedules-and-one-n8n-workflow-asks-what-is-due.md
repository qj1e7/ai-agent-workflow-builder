---
status: proposed
---

# Our API keeps each watchlist's schedule, and one n8n workflow asks it what is due

Operators want the watchlist checked on its own, for example every Monday at 9:00, and they want to change that time in the Portal. n8n's Schedule Trigger keeps its time inside the workflow, and our workflow files live in git and only bootstrap loads them (ADR 0012). The Portal could not change a schedule without editing n8n. So the schedule is part of the watchlist in our database. One workflow in git, `schedule_tick`, fires every 5 minutes and calls `POST /internal/v1/schedules/tick`. Our API starts a check for each schedule that is due, with an idempotency key made from the use case and the slot time, so a repeated or late tick never starts the same check twice. If ticks were missed, for example while the platform was down, the next tick starts one check for the latest missed slot, not one for each.

A scheduled check has no person pressing Start, but the approval gate needs to know whose work it is. `AGENTS.md` requires an ADR for any change to the gate, and this is one. A scheduled check is started by the schedule owner, the person who last saved the schedule. The run view says "Started by Alice's weekly schedule", and the schedule owner can never approve that check. With today's rule for the use case owner, a team needs at least one Approver who neither owns the watchlist nor last saved its schedule.

## Considered options

- **One Schedule Trigger per watchlist inside n8n.** The time would show in n8n's editor, but saving it from the Portal would mean writing a workflow outside bootstrap, past the lint that ADR 0012 relies on.
- **A timer inside platform-api, next to the outbox.** One fewer endpoint and workflow, and platform-api already wakes up for run deadlines. But triggers would move out of n8n, which ADR 0002 gives them to, and the sponsor's staff could no longer see in n8n when checks fired. A check needs n8n to run either way, so the timer would not keep checks working while n8n is down.
- **A system user starts scheduled checks.** No person would be kept from approving, but nobody would answer for the check, and the own-work rule would have a gap that grows with every schedule.

## Consequences

- The workflow lint accepts only calls to `/internal/v1/runs/{run_id}/steps/{step}` today. It needs a rule for the tick workflow, which has no run.
- The tick workflow should not save its successful executions, or n8n's execution list gains 288 entries a day. Its failures still reach the error workflow.
- A schedule keeps its time zone (Singapore for CODESparks), so a 9:00 check stays at 9:00.
- When the schedule owner leaves the team, another Operator saves the schedule again to take it over. The Portal shows the owner's name next to the schedule.
