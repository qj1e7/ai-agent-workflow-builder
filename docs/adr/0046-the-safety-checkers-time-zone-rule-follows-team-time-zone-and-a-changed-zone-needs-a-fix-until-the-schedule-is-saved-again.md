---
status: proposed
---

# The safety checker's time zone rule follows TEAM_TIME_ZONE, and a changed zone needs a fix until the schedule is saved again

ADR 0027 made every n8n workflow run on Singapore time, and the safety checker grades Needs a fix any workflow whose own zone differs. Issue #165 made the team time zone a setting, `TEAM_TIME_ZONE`, so a deploy outside Singapore shows its times, keeps its schedules and gives the agents their today in its own zone. We decided that the checker's rule follows the setting: the Planner lays every workflow out on the team time zone, the platform's daily self-test runs on it, n8n's `GENERIC_TIMEZONE` is set to it, and a workflow on any other zone, n8n's `DEFAULT` included, grades Needs a fix. The rule is the same rule with a setting in place of a constant, so it changes the safety checker and needs this record (`AGENTS.md`).

## Consequences

- The versions sweep marks each grade with the zone it was made under, so changing the setting grades every workflow again.
- After a change, each workflow laid out on the old zone grades Needs a fix. n8n still fires its Schedule Trigger on the old zone, and our API refuses each run at its first block, before it reads anything. The finding says what to do: "Save its schedule again, or change its time zone in n8n." On the workflow's page the banner offers Save the schedule again. Saving lays the workflow out again on the new zone from its agent cards.
- A schedule saved before the change keeps the zone it was saved in, and the Portal names that zone next to its times.
- Set the zone before the first workflow is made, as `infra/README.md` says.

## Considered options

- **Lay every workflow out again when the zone changes.** Rejected. Laying out again replaces the n8n workflow with the Planner's layout, so it would throw away changes staff made in n8n without anyone choosing to. It would also move every schedule to a new clock without telling the people who own them. A person who saves the schedule again does both on purpose, with the owner warning in front of them.
- **Grade a workflow on its old zone as Safe.** Rejected. The Portal's times, the agents' today and the working hours behind request timeouts would then disagree with when the workflow really runs, which is the mismatch ADR 0027's rule exists to stop.
