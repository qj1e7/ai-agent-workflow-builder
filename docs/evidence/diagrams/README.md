# Design diagram evidence

**Date.** 31 Oct 2026 (Singapore time).
**Code.** Drawn from `main` at commit `8ee417d`, the rebuilt app after P1 to P14 of the rebuild plan. The pull request that added these, P15, changes no app code.
**Command.** `scripts/render-diagrams.sh`. It printed `checked 17 diagrams, 21 event kinds, 31 tables and 8 jobs` and `PASS`.
**Tool.** Mermaid CLI 11.17.1, image `minlag/mermaid-cli:11.17.1@sha256:7b18341ab7398a0cfd290fdbf066243151c0adb4cbf5b81d8cf074f82019ec6f` (published 24 Sep 2026).

The source of every diagram is a Mermaid block in [the design diagrams page](../../design/diagrams.md). GitHub renders those blocks directly. These PNGs are copies for the progress report and the slides. The 22 Oct diagrams of the old app are in git history, at commit `8ee417d` and before.

| File | Diagram |
|---|---|
| `01-use-case-diagram.png` | Use cases, on the new Portal's pages: Home, Workflows, New workflow, Software watchlist, Agent library, the run page, Settings and Teams approvals |
| `02-bounded-contexts-ddd-context-map.png` | The four bounded contexts, their schemas, ports and contracts, and Cosmos DB |
| `03-class-diagram-the-domain-model.png` | The domain model's classes, from `docs/design/rebuild-domain-model.md` |
| `04-class-diagram-deciding-on-a-proposal.png` | The key use case at class level: an Approver's yes, from the Portal to the practice Jira |
| `05-er-diagram-the-builder-schema.png` | Every table and key of the `builder` schema |
| `06-er-diagram-orchestration-s-runs-and-approvals.png` | The `orchestration` tables that carry a run, its approval and its writes |
| `07-er-diagram-orchestration-s-watchlist-schedules-people-and-settings.png` | The other `orchestration` tables |
| `08-er-diagram-the-monitoring-schema.png` | The `monitoring` tables: the activity log and the copied marks |
| `09-nosql-design-the-activity-log-in-cosmos-db.png` | The Cosmos DB account, the `activity` database, the `run_events` container and `/runId`, and how the copier fills it |
| `10-nosql-design-the-activity-log-in-cosmos-db.png` | The shape of each item in the container |
| `11-deployment-now-docker-compose.png` | The Docker Compose stack |
| `12-deployment-on-azure.png` | The Azure shape that Terraform builds and `deploy.yml` deploys |
| `13-ci-cd-pipeline.png` | Every job in `.github/workflows/`, with its steps in order |
| `14-sequence-set-up-a-workflow.png` | New workflow's four steps, through the Planner and the AI model |
| `15-sequence-a-watchlist-check-runs-to-the-approval-gate-in-teams.png` | A Software watchlist check from Check now to the approval in Teams and the Jira tickets |
| `16-sequence-the-live-activity-view.png` | An activity event from PostgreSQL, through the copier and Cosmos DB, to the run page |
| `17-sequence-a-run-stops-then-the-operator-retries.png` | An agent failure, the AI troubleshooter's reason on Home, and Retry |

## Where the database diagrams come from

- `schema-2026-10-31.txt` is every table, column, primary key, unique key, foreign key and unique index in the `builder`, `orchestration` and `monitoring` schemas, read from a running database after its migrations. The ER diagrams show all 31 tables and every key in it, with the three Alembic `alembic_version` tables.
- `cosmos-2026-10-31.txt` is the Cosmos DB emulator's databases, its container's partition key, the items in each partition and one item, read from inside platform-api with `cosmos-items.py`. The two runs held 15 and 11 items, which matches the 26 rows in `monitoring.run_events`.

Both came from the stack of the second DAST run (`docs/evidence/dast/2026-11-rebuild/`), before it was taken down.

## What the script checks

- Each Mermaid block renders to a PNG, so each one parses.
- Each `/api/v1` and `/internal/v1` route in the page is in `contracts/openapi.json`.
- Each Agent API route, such as `/v1/planner/understand`, is in `agent-runtime/src/agent_runtime/api.py`, and each n8n webhook path is in the n8n workflow files.
- Each name shown as an activity event is one of the 21 kinds in `contracts/activity-event.schema.json`. Each other snake_case name in a diagram appears in the code, the contracts, `infra/` or `.github/workflows/`.
- Each table the migrations leave in place, and each schema's `alembic_version`, is in an ER diagram, and each table an ER diagram shows is a real one.
- Each job in `.github/workflows/` is in the CI/CD diagram, in its file's order.
- The page has none of the old themed names, none of the names the rebuild retired (Room lead, Release checker, the release-check workflow), and no long dashes.

`check-selftest.txt` shows that the new checks can fail. We planted four mistakes in copies of the page: a renamed table, jobs out of order, the retired name Room lead, and an Agent API route that does not exist. The check reported each one and exited 1. The page as committed passed.

## What the script does not check

- That each key in an ER diagram matches the database. We compared them by hand with `schema-2026-10-31.txt`.
- That a sequence diagram's order of calls matches the code. The two run diagrams follow the recorded runs in `contracts/fixtures/runs/`, and the other two were read from the code.
- The use case diagram against the running Portal. Its table names the page and the routes for each use case.
- Where Mermaid places each box. The job check reads the page's text, not the PNG. So the CI/CD diagram joins its trigger to the `ci.yml` box as a whole and chains that file's jobs with invisible links, which makes the PNG draw them left to right in the file's order.
