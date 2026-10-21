# Design diagram evidence

**Date.** 22 Oct 2026 (Singapore time).
**Code.** Drawn from commit `b07646d` on branch `ci/dast-and-load`.
**Command.** `scripts/render-diagrams.sh`. It printed `PASS`.
**Tool.** Mermaid CLI 11.17.1, image `minlag/mermaid-cli:11.17.1@sha256:7b18341ab7398a0cfd290fdbf066243151c0adb4cbf5b81d8cf074f82019ec6f` (published 24 Sep 2026).

The source of every diagram is a Mermaid block in [the design diagrams page](../../design/diagrams.md). GitHub renders those blocks directly. These PNGs are copies for the progress report and the slides.

| File | Diagram |
|---|---|
| `01-use-case-diagram.png` | Use cases, now and Phase 2 |
| `02-bounded-contexts-ddd-context-map.png` | The four bounded contexts, their schemas, ports and contracts |
| `03-deployment-now-docker-compose.png` | The Docker Compose stack as it runs today |
| `04-deployment-planned-azure.png` | The planned Azure shape, with the open decisions left open |
| `05-sequence-the-release-check-succeeds.png` | The release check from Run now to the Jira ticket |
| `06-sequence-the-run-fails-then-the-operator-retries.png` | An agent failure, the AI troubleshooter's advice, and Retry |

## What the script checks

- Each Mermaid block renders to a PNG, so each one parses.
- Each `/api/v1` and `/internal/v1` route in the page is in `contracts/openapi.json`.
- Each Agent API route is in `agent-runtime/src/agent_runtime/api.py`, and each n8n webhook path is in the workflow files.
- Each name shown as an activity event is one of the 21 kinds in `contracts/activity-event.schema.json`. Each other snake_case name in a diagram appears in the code or the contracts.
- The page has none of the old themed names and no long dashes.

To prove the check can fail, we planted four mistakes in the page and then restored it: an unknown event kind, a route that does not exist, a webhook path that does not exist, and a banned name. The script reported each one and printed `FAIL`.
