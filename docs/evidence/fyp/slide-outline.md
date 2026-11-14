# Slide outline, first presentation (draft)

**Status.** The team lead's notes for the deck, to edit. Written on 14 Nov 2026 against `main` at `a7ba7673`.
**Follows.** The school's "1st Presentation Guidelines" (brief, slide 27), item by item, in its order and with its times. The brief skips item 14, so this outline does too. Slides 28 and 29 of the brief add this: show evidence for every claim, show functional elements packed into subsystems, and explain a design problem with diagrams, not only words.

Each slide lists its points and the evidence file it draws on. Paths are from the repository root. A slide marked **Gap** has no evidence yet, and says what the team must make.

**Before you build the deck.** Render the diagrams again on a machine with Docker (`scripts/render-diagrams.sh`). The PNGs in `docs/evidence/diagrams/` are from 31 Oct and show the old Home. The Mermaid sources in `docs/design/diagrams.md` are up to date.

Total: about 30 minutes, with the demo at 6 to 8.

---

## 1. Project overview and introduction (1 min)

- CODESparks, an NCS team, does repetitive Jira and Confluence work. Their support staff are not technical.
- Staff describe a task in plain words. A Planner agent brings in the agents it needs. Nothing is written until a person says yes in Teams.
- Phase 1 is the sponsor's software versioning use case. Phase 2 is the quarterly access review and patch housekeeping.
- The added value the brief asks for: agentic AI with a human approval gate, and staff who maintain each workflow in n8n.

Evidence: `AGENTS.md` ("The project"), `docs/proposal/MTech_SE_Project_Proposal_v0.2_reviewed (1).docx`, `GLOSSARY.md`.

## 2. Overall scope, as a use case diagram (1 min)

- Two roles, Operator and Approver. Use cases grouped by screen: Chat, Workflows, Watchlist, Run view, Approval view, Settings, Teams approvals, Practice Jira.
- Outside actors: the Planner and agents, the AI model, n8n, GitHub, Confluence, Jira, Teams.
- Say what is out of scope for Phase 1 (the list under the diagram).

Evidence: `docs/design/diagrams.md`, "Use case diagram", and its route table.

## 3. Project roadmap and key milestones (1 min)

- Phase 0 and Phase 1 dates from the brief, with our sprints on them.
- What we delivered by milestone: walking skeleton (23 Oct), first Azure deploy (31 Oct), AI-native redesign (7 Nov), chat-first Portal and n8n as the engine (13 and 14 Nov).
- What comes next: the rest of the engine steps, the final presentation in April 2027, Phase 2 and the move into DevNet.

Evidence: `docs/evidence/fyp/sprints.md` (sprint calendar), `CHECKPOINTS.html`, `docs/design/chat-first/ENGINE-PLAN.md` section 6, `docs/design/devnet-move.md`.

**Gap.** No updated product roadmap since the 8 Nov software versioning focus. Draw one slide-sized roadmap: Phase 1 to 15 Dec, then to April, then Phase 2 and DevNet.

## 4. The complete project backlog (1 min)

- The open GitHub issues (16 on 14 Nov), the engine steps not built yet (E3, E6 to E11, E15 to E17, with E18 deferred), and the Phase 2 use cases.
- How items are ordered: safety first, then what the demo needs.

Evidence: GitHub issues, `docs/evidence/fyp/sprint-data.md` ("Issues still open"), `ENGINE-PLAN.md` section 6.

**Gap.** No single prioritised backlog with user stories. Make one table: story, priority, status, issue or PR.

## 5. Overall sprint effort to date (1 min)

- Sprints 1 to 5 with their goal and what landed.
- Estimated against actual hours for every member, for every sprint.
- Pull requests merged per week, and the sprint 5 burndown.

Evidence: `docs/evidence/fyp/sprints.md`, `docs/evidence/fyp/sprint-data.md`, `docs/evidence/fyp/hours-log.md`.

**Gap.** The hours. Only each member can fill in the hours log. Without it, this slide cannot be marked (brief, slide 28).

## 6. Tech stack (1 min)

- Portal: React, served by nginx. Backend: Python, with platform-api and the agent runtime. Agents: LangChain and LangGraph, traced with LangSmith.
- n8n 2.42.6 as the engine, with our own node pack. PostgreSQL and Azure Cosmos DB for NoSQL.
- Azure Container Apps, Key Vault, Log Analytics. Terraform, kept working under OpenTofu. GitHub Actions.

Evidence: `AGENTS.md` ("Architecture"), ADRs 0002 to 0006, 0013 (Terraform), 0031 (Cosmos DB), 0032 (AI model), `deploy/compose.yaml`.

## 7. Architectural constraints and decisions (1 min)

- The sponsor's rules: no write without a yes, never approve your own work, two Approvers in turn for the access review, internet first and DevNet later.
- 44 ADRs in `docs/adr/`: 11 accepted, 30 proposed, 3 superseded. Pick three to show: 0026 (every write is checked when it is made, so n8n may hold the wait), 0043 (Home is a chat), 0045 (n8n's own nodes, classed by operation).

Evidence: `AGENTS.md` ("Product safety rules"), `docs/adr/`.

**Note.** Many ADRs whose design is built still say "proposed". Accept the built ones before the slides, or say why they are still open.

## 8. Logical and physical architecture (1 min)

- Logical: six subsystems and their functional elements. The Portal, the use case builder, orchestration, run monitoring, the agent runtime, and n8n with our node pack.
- Physical: what runs in which container, on Docker Compose and on Azure.
- Three rules across them: the Portal reads only our API, n8n reaches only our API, every write goes through the write gateway.

Evidence: `docs/design/diagrams.md`, "Logical architecture: functional elements and subsystems" and its table, and the two deployment diagrams.

## 9. Deployment diagram (1 min)

- The Azure shape that Terraform builds: Container Apps, PostgreSQL Flexible Server, Cosmos DB, Key Vault, Container Registry, Log Analytics.
- The deploy runs by hand from `main` only, through the `azure-dev` environment.
- Proof it ran: all P14 lanes passed on Azure.

Evidence: `docs/design/diagrams.md` ("Deployment on Azure"), `docs/evidence/deploy/first-deploy.md`, `docs/evidence/deploy/p14-summary.txt`.

## 10. Microservices and DDD (2 min)

- Four bounded contexts, each with its own schema and database role. Three ship in one container, platform-api (ADR 0010). The agent runtime is its own service.
- Ports and adapters: each outside system sits behind a port, which keeps the app portable to AWS.
- `import-linter` enforces the boundaries in CI.

Evidence: `docs/design/diagrams.md` ("Bounded contexts (DDD context map)" and the ports table), "Class diagram: the domain model", `docs/design/rebuild-domain-model.md`.

## 11. Analysis to design, for a key use case (1 min)

- The key use case: a run waits for a yes, Bob approves, and the ticket is made.
- From the use case, to the domain classes, to the sequence through n8n, our API, the safety checker and Jira.
- The design problem to explain with the diagrams: n8n holds the wait, but n8n never decides. The wake carries a `mac`, and the gateway checks our records again at the write.

Evidence: `docs/design/diagrams.md`, "Class diagram: deciding on a proposal" and "Sequence: a run waits for a yes in n8n, then the approved change is made". ADR 0026.

## 12. Relational ERD and NoSQL design (1 min)

- PostgreSQL: three schemas, builder, orchestration and monitoring, with 44 tables, counting the three Alembic version tables. The diagram check counts them against the migrations.
- Cosmos DB: the activity log's copy, container `run_events`, partitioned by run.

Evidence: `docs/design/diagrams.md`, the four ER diagrams and "NoSQL design: the activity log in Cosmos DB". `docs/evidence/diagrams/cosmos-2026-10-31.txt`.

## 13. CI/CD pipelines and the CI/CD diagram (2 min)

- One pipeline on every push to `main`: lint and unit tests, Semgrep, gitleaks, the node pack smoke, then the whole stack with browser tests, ZAP and k6. Seven jobs, all green on `a7ba7673`.
- The deploy is a separate workflow, started by a person.
- Artifacts of SAST, DAST and unit testing:
  - SAST: Semgrep, 0 open findings in 625 files.
  - DAST: ZAP, no High or Medium finding.
  - Unit tests: the saved reports of 31 Oct, and the green CI run.
- Artifacts of load and stress testing:
  - Load: k6, two passes.
  - Stress: 3x the test load passes. The stack slows between 3x and 6x. Even at 12x no request fails, but k6 drops the iterations it cannot start in time.

Evidence: `docs/design/diagrams.md` ("CI/CD pipeline"), `.github/workflows/ci.yml`, CI run [43590669307](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/43590669307), `docs/evidence/sast/README.md`, `docs/evidence/dast/2026-11-rebuild/`, `docs/evidence/unit-tests/2026-11-rebuild/`, `docs/evidence/load-test/2026-11-rebuild/`, `docs/evidence/load-test/README.md` (the 3x, 6x and 12x probes).

**Gap.** The unit test, DAST, load and stress reports in the repository are from 31 Oct and before, on the app before the chat and the engine. Save fresh copies from the latest green CI run's artifacts, and run the stress probes again.

## 15. Infrastructure as Code (1 min)

- Terraform for the whole Azure environment, checked by fmt, validate, OpenTofu validate, tflint and Checkov in the `infra` workflow.
- A guard refuses any plan that destroys or replaces a resource unless we say so.

Evidence: `infra/`, `docs/evidence/iac/README.md`, `docs/evidence/deploy/infra-checks/`, ADR 0013.

## 16. Security of the app and platform (2 min)

- How one write stays safe, in five steps.
- The controls that matter most: the approval gate, the write gateway, our n8n blocks with no address or key of their own, the signed start and the signed wake.
- The scans, and a security review on every engine pull request.
- Say the known gaps out loud, starting with the n8n allow list that is built but not yet on.

Evidence: `docs/evidence/fyp/security.md`.

## 17. Live demo of the app and CI/CD (6 to 8 min)

- Ask in plain words, build it in n8n, test run, turn it on. The release check runs to the yes. Bob approves, and the ticket is made. A stopped run, the troubleshooter, Retry. Then CI/CD.
- Backup: a recorded video and screenshots.

Evidence: `docs/evidence/fyp/demo-script.md` (run sheet, words, backup plan and pre-flight checklist).

**Gap.** Azure runs a build from 13 Nov. Redeploy `main` before the demo (a person starts the deploy). Record the backup video at the dry run.

## 18. Management concerns, issues and mitigations (2 min)

- Scope moved twice in one week (7 and 13 Nov). Mitigation: the chat-first sketch is now fixed for Phase 1, and Phase 1 is narrowed to software versioning.
- We kept no sprint records while we worked. Mitigation: rebuilt from git, and kept from now on.
- Work is uneven in git. Mitigation: the hours log shows work outside GitHub, and each member presents a part.
- Waiting on the sponsor: code ownership and reuse rights, and the DevNet questions to NCS.

Evidence: `docs/design/rebuild-plan.md` Appendix C (risks, 31 Oct), `docs/evidence/fyp/readiness.md` (top risks), `docs/evidence/fyp/progress-report-2026-11.md` ("Problems encountered").

**Gap.** Appendix C is from 31 Oct. Agree the list as a team.

## 19. Technical concerns, issues and mitigations (2 min)

- Two engines run side by side until E9 and E10 move the watchlist.
- The node allow list is built and tested, not yet switched on (E11).
- The engine is not on Azure yet.
- The AI model choice waits on an eval run (ADR 0032).
- DevNet: the model address guard does not use a proxy yet (issue #86).
- Semgrep cannot parse a few lines of newer Python syntax.

Evidence: `docs/evidence/fyp/security.md` ("Known gaps and open items"), `docs/design/chat-first/ENGINE-PLAN.md` section 7 (risks), `docs/evidence/devnet/lockdown.md`, `docs/evidence/sast/README.md`.

## 20. AOB (as needed)

- Questions for the lecturers, for example on sprint evidence rebuilt from git.
- Thanks to the sponsor.

---

## Who presents what

**Gap.** Peer assessment is 20% of the grade. Give each member a named part of the deck and the demo, and write it here.

| Slides | Presenter |
|---|---|
| 1 to 5 | |
| 6 to 12 | |
| 13 to 16 | |
| 17, the demo | |
| 18 to 20 | |
