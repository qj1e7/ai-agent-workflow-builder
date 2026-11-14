# Readiness audit, 14 Nov 2026

Checked against "Project Requirements SE33+Admin v3" (all 22 pages) and `main` at `a7ba7673`, plus the evidence added on the branch `docs/school-evidence-pack`. It updates the audit of 13 Nov, which checked `main` at `2ea47c16`. Since then 22 pull requests merged on 13 and 14 Nov (#240 to #263): the chat-first Portal and the first engine pull requests, which make n8n the engine behind every new workflow.

**23 Done, 11 Partial, 8 Missing.** On 13 Nov it was 20 Done, 11 Partial and 11 Missing. Three items moved to Done: the logical architecture (21), the app-wide SAST report (27) and the security page (32). Three moved from Missing to Partial: the sprint plan and backlog (6), the burndown (7) and the progress report (15). The diagrams of item 13 now match the code, but their PNGs still need a render, so it stays Partial. What is left is mostly what only the team can supply: hours, reviews and retros, peer evidence, and the submission pack.

## What changed on 14 Nov

| New or changed | What it gives |
|---|---|
| [`docs/design/diagrams.md`](../../design/diagrams.md) | A new logical architecture view. The use case diagram, context map, deployment diagrams and three sequences now show the chat-first Portal, n8n with our node pack, Ask for a yes held in n8n, the write gateway, Tell and the Confluence reader. 13 new tables and the `n8n-node-pack` CI job. `scripts/render-diagrams.sh --check-only` passed. The PNGs were not rendered again |
| [`security.md`](security.md) | One page: each concern, its control and its proof, the security review on each engine PR, the DevNet notes, and 11 known gaps |
| [`../sast/`](../sast/README.md) | Semgrep over the whole app with CI's rules: 0 open findings in 625 files. `scripts/semgrep-local.sh` runs it again without Docker |
| [`sprints.md`](sprints.md), [`sprint-data.md`](sprint-data.md) | Sprints rebuilt from GitHub, with a proposed calendar, each sprint's goal and work, and the sprint 5 burndown. `scripts/sprint-stats.py` makes the numbers again |
| [`hours-log.md`](hours-log.md), [`sprint-review-template.md`](sprint-review-template.md) | Empty templates for the team |
| [`progress-report-2026-11.md`](progress-report-2026-11.md), [`slide-outline.md`](slide-outline.md), [`demo-script.md`](demo-script.md) | Drafts for the team lead to edit |

## Rubric items

| # | Item (rubric's words) | 13 Nov | 14 Nov | Evidence | What is left |
|---|---|---|---|---|---|
| 1 | Proposal | Done | Done | `docs/proposal/MTech_SE_Project_Proposal_v0.2_reviewed (1).docx` | |
| 2 | Product roadmap, initial and updated | Partial | Partial | Proposal phases; `CHECKPOINTS.html`; sprint calendar in `sprints.md` | Draw the updated roadmap since the 8 Nov software versioning focus (slide 3 of the outline) |
| 3 | Product backlog with user stories or use cases | Partial | Partial | 53 GitHub issues, 16 open, no labels or milestones; ENGINE-PLAN section 6; use case table in `diagrams.md` | One prioritised backlog with user stories |
| 4 | Solution architecture (initial), risks and mitigation | Done | Done | Proposal; `walking-skeleton.md`; `rebuild-plan.md` Appendix C | |
| 5 | Feasibility study and prototypes (optional) | Done | Done | `docs/evidence/prototypes/` P1 to P7; `model-bakeoff/` | |
| 6 | Sprint plan and sprint backlog | Missing | Partial | `sprints.md`: the plan documents behind sprints 4 and 5, and each sprint's merged PRs in `sprint-data.md` | Confirm the calendar and goals. Sprints 1 to 3 from the team's memory and notes |
| 7 | Burndown chart | Missing | Partial | Sprint 5 burndown from issues, in `sprints.md`, made by `scripts/sprint-stats.py` | The line rises, because most work went in without issues. Open an issue per planned item from sprint 6 |
| 8 | Sprint review and retrospective | Missing | Missing | Template in `sprint-review-template.md` | One review and retro per sprint, 1 to 5, by the team |
| 9 | Software design for critical user stories | Done | Done | Class 03, 04; the three updated sequences | |
| 10 | DevOps pipeline design | Done | Done | CI/CD diagram with the `n8n-node-pack` job; `ci.yml`, `deploy.yml`, `infra.yml` | |
| 11 | Test cases and results; unit testing artifacts | Done | Done | `unit-tests/2026-11-rebuild/` (31 Oct); CI run 43590669307 green on `a7ba7673`, 7 jobs | Save fresh reports from the latest CI run before 15 Dec |
| 12 | Codebase and repo URL | Done | Done | Public repo, 207 merged PRs | |
| 13 | Solution architecture (updated) | Partial | Partial | Mermaid sources match `a7ba7673` and pass the check. 44 ADRs | Render the PNGs with Docker (`scripts/render-diagrams.sh`) and update `docs/evidence/diagrams/README.md`'s table |
| 14 | Peer assessments | Missing | Missing | Peer Assessment System | Not due yet. All 5 submit after the presentation |
| 15 | Monthly progress report | Missing | Partial | November draft in `progress-report-2026-11.md` | Fill in the hours. Find and keep copies of the 10 Oct and 10 Nov reports |
| 16 | Hours expended by each member | Missing | Missing | Template in `hours-log.md` | Every member fills in every sprint |
| 17 | Overall scope using a use case diagram | Done | Done | Use case diagram, now the chat-first Portal | Render the PNG |
| 18 | Sprint effort, estimate versus actual, every member | Missing | Missing | Template in `hours-log.md` | Needs 16 |
| 19 | Tech stack | Done | Done | `AGENTS.md` Architecture; ADRs 0002 to 0006 | |
| 20 | Architectural constraints and decisions | Done | Done | 44 ADRs (11 accepted, 30 proposed, 3 superseded); safety rules in `AGENTS.md` | Accept the ADRs whose design is built |
| 21 | Logical and physical architecture | Partial | Done | New logical view: six subsystems and their functional elements, with code paths; context map 02; deployment diagrams | Render the PNG |
| 22 | Deployment diagram | Done | Done | Compose and Azure diagrams, with our n8n image; P14 lanes on Azure | |
| 23 | Microservices explained with a DDD diagram | Done | Done | Context map and ports table, domain model 03, import-linter | |
| 24 | Analysis to design transition, key use case | Done | Done | Domain 03, class 04, the new approval sequence | |
| 25 | Relational ERD and NoSQL design | Done | Done | Four ER diagrams with all 44 tables; Cosmos DB 09, 10 | The 13 new tables were drawn from the migrations, not a live database |
| 26 | CI/CD pipelines and CI/CD diagram | Done | Done | `ci.yml`, `deploy.yml`; CI/CD diagram | |
| 27 | Artifacts of SAST | Partial | Done | `docs/evidence/sast/2026-11-14/`: Semgrep 1.179.0, 0 open findings, 625 files | |
| 28 | Artifacts of DAST | Done | Done | `dast/2026-11-rebuild/` (31 Oct, 0 High or Medium); ZAP on every push to main | Save the latest run's `zap-reports` before 15 Dec |
| 29 | Artifacts of load testing | Done | Done | `load-test/2026-11-rebuild/` (k6, 2 passes); k6 on every push to main | Save the latest run's `k6-summary` |
| 30 | Artifacts of stress testing | Partial | Partial | 3x, 6x, 12x probes in `load-test/README.md` | Ran on the 22 Oct app only. Run again |
| 31 | Infrastructure as Code | Done | Done | Terraform in `infra/` (ADR 0013); `infra.yml` with tflint and Checkov; `docs/evidence/iac/` | |
| 32 | Security: concerns, mitigations, solutions | Partial | Done | `security.md` | Its 11 known gaps stay open |
| 33 | Live demo of the app and CI/CD | Partial | Partial | `demo-script.md`: a 6-minute run sheet, backup plan and pre-flight checklist | Azure runs the 13 Nov build. Redeploy, rehearse, record the backup |
| 34 | Management and technical concerns | Partial | Partial | Points in `slide-outline.md` 18 and 19; `security.md` gaps; progress report problems | Agree the list as a team. `rebuild-plan.md` Appendix C is from 31 Oct |
| 35 | Presentation slides | Missing | Missing | Outline in `slide-outline.md` | Due 27 Nov |
| 36 | Interim project report | Missing | Missing | None | Due 15 Dec |
| 37 | App demo video, 3 to 5 min | Missing | Missing | None. The browser tests record no video | Due 15 Dec. Record at the dry run |
| 38 | CI/CD demo video, 3 to 5 min | Missing | Missing | None | Due 15 Dec |
| 39 | Team item: NoSQL store | Done | Done | Cosmos DB holds the activity log; all 23 events landed on Azure (`p14-cosmos.json`) | |
| 40 | Team item: Terraform or Bicep | Done | Done | ADR 0013 accepted; `prototypes/p5-iac-terraform-vs-bicep` | |
| 41 | Team item: LLM evals in CI | Partial | Partial | Golden set in `agent-runtime/evals/cases/`; `evals.yml` | Runs only by hand, and has never run on GitHub |
| 42 | Team item: AI model chosen | Partial | Partial | ADR 0032 (proposed), Claude Haiku 5.5 for the demo; `decision-memo.md` | Accept after an eval run |

Item 13 stays Partial only because of the PNGs. Item 21 counts as Done because the rubric asks for the view, and its Mermaid source is checked against the code, but its PNG needs the same render.

## Top risks

1. **Hours and individual evidence (14, 16, 18).** Only the team can supply these, and slide 28 of the brief says assessors cannot mark claims without evidence. 206 of 207 merged PRs came from one GitHub account, and peer assessment is 20% of the grade. **Next step:** every member fills in `hours-log.md` for sprints 1 to 5 this week, with work outside GitHub named in "Main work".
2. **The submission pack (33, 35 to 38).** The presentation starts in 13 days. Slides, the interim report and two videos do not exist yet. **Next step:** build the deck from `slide-outline.md`, give each member a named part, and record both videos at the dry run, at 1920x1080.
3. **Azure is behind `main`.** The last deploy was on 13 Nov at `2ea47c16`. The engine and the set-up card's test run and Turn it on are not on Azure, and the node allow list is not on anywhere. **Next step:** a person redeploys `main` after the E11 allow list lands, then runs the P14 lanes again. A deploy always needs a human.
4. **Sprint records are rebuilt, not kept (6, 7, 8).** The rebuilt calendar and goals are proposals, and sprints 1 to 3 are empty. **Next step:** confirm `sprints.md` at the next team meeting, write the five reviews and retros, and from sprint 6 open an issue per planned item.
5. **Evidence older than the app (11, 13, 28 to 30).** The diagram PNGs, unit test, DAST, load and stress reports are from 31 Oct or before. The CI artifacts of `a7ba7673` expire on 12 Feb 2027. 30 of 44 ADRs say "proposed". **Next step:** after the feature freeze, render the diagrams, save the latest CI artifacts into `docs/evidence/`, rerun the stress probes, and accept the built ADRs.

## Strong and worth showing

- Every write still goes through one gateway that checks our own records at the moment of the write, now with n8n holding the wait. `security.md` maps each rule to a test.
- Each engine PR had a security review by a separate AI model before merge, and most proved that removing any safety guard makes a test fail.
- One CI run on every push to main runs unit tests, Semgrep, gitleaks, the node pack smoke, the browser suite, ZAP and k6. The run on `a7ba7673` passed all 7 jobs.
- An app-wide Semgrep scan found 0 open findings in 625 files.
- 18 diagrams cover every type the rubric names, including the logical view, and a script checks them against the routes, events, tables and CI jobs. `docs/evidence/diagrams/check-selftest.txt` shows that planted mistakes fail it.
- The app ran on Azure, built by Terraform, and passed 11 live checks, including Cosmos DB and a ZAP scan.
