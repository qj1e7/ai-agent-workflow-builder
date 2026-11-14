# Monthly progress report, November 2026 (draft)

**Status.** A draft for the team lead to edit before it goes into the Internship Tracking System. The headings follow the school's progress report format (brief, slide 15). Everything in it comes from the repository and GitHub, up to 14 Nov 2026. The hours are left for the team to fill in.

**Period.** This draft covers 11 Oct to 14 Nov 2026. If this is the report for the 10 Nov slot, drop the "Since 10 Nov" part, or move it to the December report.

---

## Project title

AI Workflow Builder for CODESparks (NCS)

## Date

`<date of submission>`

## Summary of work done

This month we built the platform end to end, put it on Azure, and then reshaped it around a chat and around n8n as the engine. 153 pull requests were merged between 11 Oct and 10 Nov, and 54 more from 11 to 14 Nov. Each one is listed by sprint in `docs/evidence/fyp/sprint-data.md`.

**Sprint 4, 19 Oct to 1 Nov.**

- Set up the team repository, the CI pipeline and the main design decisions (ADRs 0002 to 0013).
- Built a walking skeleton: a request goes from the Portal through n8n to an agent, waits for approval, and creates a ticket in a practice Jira.
- Tested n8n, LangGraph and Terraform against Bicep with small prototypes before choosing them.
- Rebuilt the Portal from our clickable prototype in 15 planned steps. This added roles (Operator and Approver), the run page with the approval gate, the Software watchlist, Workflows, Settings and Home.
- Copied the activity log to Azure Cosmos DB, our NoSQL store.
- Deployed the app to Azure with Terraform and GitHub Actions on 31 Oct, and passed all our live checks there.
- Ran the security and load scans again on the new app: no High or Medium finding from OWASP ZAP, and k6 load tests passed.

**Sprint 5, 2 Nov to 10 Nov.**

- Wrote the AI-native design principles and redesigned the Portal around them.
- Narrowed Phase 1 to the sponsor's software versioning use case, and froze the general builder.
- Added the Planner's answers on Home, setting up a workflow from the Planner's card, team requests (Ask the team, Report to support), and a check of each connection.
- Made an approved Jira write happen only in the Jira site it was approved for (ADR 0041).
- Decided to turn Home into a chat with a side rail (ADR 0043).

**Since 10 Nov, to 14 Nov.**

- Built the chat-first Portal: the chat, the side panel, the edit card for schedule changes with Undo, decline reasons, and questions from an Approver to the requester.
- Made n8n the engine behind every new workflow. Each workflow is now its own n8n workflow, built from our own n8n blocks. n8n holds the wait for approval, and our API still checks every write at the moment it is made.
- Added Tell (a result posted to Teams and sent by email through one Power Automate flow) and a read-only Confluence reader.
- Each engine pull request had a separate security review before merge.
- Saved an app-wide SAST report: Semgrep found 0 open findings in 625 files.

## Effort expended

Hours spent by each member since the last report. Copy them from `docs/evidence/fyp/hours-log.md`.

| Member | Hours, 11 Oct to `<end date>` | Main work |
|---|---|---|
| `<team lead>` | | |
| `<member 2>` | | |
| `<member 3>` | | |
| `<member 4>` | | |
| `<member 5>` | | |
| Total | | |

## Problems encountered

These are the problems we found. The ones marked "ISS" are where advice from the lecturers would help. Edit or drop any of them.

1. **Sprint records (ISS).** We did not keep sprint plans, burndowns or retros while we worked. We have rebuilt them from git and GitHub (`docs/evidence/fyp/sprints.md`), with the parts we inferred marked. Is evidence rebuilt this way acceptable, if we keep proper records from now on?
2. **The design changed twice in one week.** The design target moved to a new prototype on 7 Nov and to a chat-first sketch on 13 Nov. The second move followed a UX review on 10 Nov that tested both designs with eight operator tasks (ADR 0043). Each move cost rework. We now treat the chat-first sketch as fixed for Phase 1.
3. **Code ownership (ISS).** We are still waiting for the sponsor to confirm in writing who owns the code and whether NCS may reuse it.
4. **Moving into DevNet.** The app must later run inside NCS's private network. We tested a locked-down copy on a laptop. Nine questions to NCS are still open, such as which AI model DevNet may call.
5. **The AI model.** The demo runs on Claude Haiku 5.5 through AI Singapore's gateway (ADR 0032, still proposed). The evaluation that should confirm the choice has not been run yet.
6. **Safety work still to finish.** n8n's node allow list is built and tested in CI, but not yet switched on in the deployed app. The new engine has not been deployed to Azure yet.

## Plan for the next reporting period

11 Nov to 10 Dec 2026.

1. Finish the engine steps the demo needs, and switch the node allow list on.
2. Freeze features a few days before the presentation.
3. Refresh the evidence: diagrams, unit tests, SAST, DAST, load and stress tests.
4. Prepare and rehearse the first presentation (27 Nov to 5 Dec): slides, live demo and a backup recording.
5. Start the interim report, and record the app and CI/CD demo videos for the 15 Dec submission.
6. Fill in the hours log, and write the sprint reviews and retros for sprints 1 to 6.
7. Follow up with the sponsor on code ownership and the DevNet questions.

---

## Notes for the team lead, not for the report

- **Who did the work.** 206 of the 207 merged pull requests came from your GitHub account. Peer assessment is 20% of the grade, and assessors look for evidence. Make sure the hours log and the "Main work" column show each member's work outside GitHub, such as testing, reviews, research, documents and sponsor meetings.
- **The 10 Oct and 10 Nov reports.** The readiness audit could not find copies in the repository. If they were submitted, keep a copy beside this file.
- **Numbers to check before sending.** The pull request counts come from `python3 scripts/sprint-stats.py`. The Azure checks are in `docs/evidence/deploy/p14-summary.txt`. The scan results are in `docs/evidence/dast/2026-11-rebuild/` and `docs/evidence/sast/`.
