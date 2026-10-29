---
status: proposed
---

# Rebuild the Portal from the prototype, and reshape the backend in place

On 29 Oct the team lead decided that the app follows the workflow builder prototype, [`docs/design/portal-routines/prototype.html`](../design/portal-routines/prototype.html), and will be rebuilt from it. The prototype changes what people see: the menu, the names, and the flow from Home to a run. It does not change the safety rules underneath. A check of today's code on 29 Oct found two very different halves:

- **The Portal.** About 15,300 lines of TypeScript, built around the old menu (Runs, Builder, Software, Approvals, Teams, Jira) and the old names. Its screens, tracker, tour and in-browser mock follow that shape. Only sign-in, the API client, the event stream reader, nginx, the colour tokens, the agent faces and the font fit the prototype.
- **The backend.** About 12,100 lines of app code in platform-api and 3,900 in the agent runtime, with 1,541 unit tests. On 29 Oct, 737 platform-api tests and 566 agent runtime tests passed on a laptop without a database. The other 238 need PostgreSQL, and they pass in CI, where the latest run on `main` succeeded. The approval rules, the safety checker, the write gateway, sign-in, the live event stream, the watchlist rules and the agent tools do not depend on any screen. They hold the October lessons and the evidence from the DAST scan and the load test.

So we rebuild the Portal and reshape the backend:

- **The Portal is written again from the prototype, in `portal/`,** on the same stack: React 19, Vite, TanStack Query, React Router and `oidc-client-ts`. It keeps `src/api`, `src/stream`, the nginx setup, the tokens, the agent faces and the font, with their tests. The first Portal PR deletes the old screens, the tracker, the tour, the mock platform and the demo Playwright specs. The old Portal does not run beside the new one.
- **The backend keeps its services and its four contexts.** Pure rule modules move as they are, with their tests. The rest is reshaped to the prototype's model, listed in [the domain model](../design/rebuild-domain-model.md). Two parts are written again because they are scripted today. For release and watchlist runs the Planner always brings in the Release checker (`agent-runtime/src/agent_runtime/room.py`), and the AI troubleshooter is a lookup table (`platform-api/src/platform_api/monitoring/troubleshooter.py`).
- **Retired names go.** Room lead becomes Planner and Release checker becomes Version checker, in code, contracts and events. The n8n workflow `release_check` carries every run today, the watchlist's and the agent cards' included, so it is renamed `run` and kept. The release-check template goes, because release checks now live only on the Software watchlist.
- **Code keeps "use case".** The glossary already says that Operators see a use case as a workflow. Renaming it in code would clash with the n8n workflow code in `orchestration/workflows.py`, and it would change every route, table and contract for no change in behaviour.
- **The first demo runs on ADR 0007's path.** n8n carries each run in two legs and our API decides every pause. That path holds the 13 end-to-end tests, the DAST scan and the load test. ADRs 0026 and 0027 have one throwaway prototype run against a stub, and their prototype P7 has not run. The node pack starts after prototype P7 passes and after the first presentation. Until then, Open in n8n stays in the prototype.
- **New routes are declared first.** Each PR adds its routes to the contract stories, which generate `contracts/openapi.json`, which generates the Portal's types. CI already fails when they drift.

[The rebuild plan](../design/rebuild-plan.md) lists the PRs in order, with how each one is checked.

## Considered options

- **Write everything again, in a new repo.** A clean start, but it throws away 1,541 tests, the CI with its SAST, DAST and load-test jobs, the Terraform, and the history that the graders read. The approval rules are the hard part, and they already work.
- **Write everything again, in this repo.** CI and history stay, but the tested rules would be written a second time in the four weeks before the first presentation.
- **Change the old Portal screen by screen.** No big switch-over day. But the prototype has a different menu, different pages and different names. Changing 15,000 lines into another shape costs more than writing the screens from the prototype, and old names would leak through.
- **Build the new Portal in a new folder beside the old one.** Both would run until the new one caught up. CI, the scans and the deploy would carry two Portals, and the old one would stop being maintained long before it was deleted.
- **Build the node pack (ADRs 0026 and 0027) for the first demo.** The sponsor asked for it. But it has to earn the end-to-end, DAST and load-test evidence again on a new run path, at the same time as a new Portal, in four weeks.
- **Rename "use case" to "workflow" in code.** One name everywhere. But it clashes with n8n workflows inside our own orchestration code, and it touches every contract for no change in behaviour.

## Consequences

- **The scans and tests seed through the release-check routes.** `scripts/lib/seed.py`, `load/team.js` and the e2e harness call `/api/v1/use-cases` with the release-check template. The PR that retires the template moves them to the Software watchlist in the same change, so DAST, k6 and e2e never break on `main`.
- **Every diagram and scan in `docs/evidence/` describes the old app.** The plan's last PR runs them again on the new app and draws the diagrams the rubric still lacks: class, ER, NoSQL collections and CI/CD.
- **The Portal's demo mode goes.** The in-browser mock in `portal/src/mock` follows the old routes. The new Portal is tested against the real stack, as `portal/e2e/live` already does. A backup demo video replaces demo mode for the presentation.
- **Each Phase 2 piece still needs its own decision.** This covers named Approvers' timers (ADR 0024), the node pack (ADRs 0026 and 0027), Connections and AI usage in Settings, tool cards, report to support, approving inside a Teams message, and LangSmith tracing, which `AGENTS.md` names but nothing wires up.
- **Terraform catches up in the deploy PR.** platform-api on Azure gets no `SETTINGS_ENCRYPTION_KEY` today, so the AI model settings would be off there. The agent runtime gets no `PRACTICE_JIRA_URL`.
- **If this ADR is accepted,** `AGENTS.md` loses its line about the code still saying `room_lead` once the rename PR merges.
