# End to end harness

This harness is the definition of done for the whole product. It starts the real stack (postgres, n8n, agent runtime, platform-api) with a fake GitHub, then acts like the Portal: plain HTTP calls as the dev users `alice` (Operator and Approver) and `bob` (Approver). It never imports platform code and never reads a database.

## Run it

From the repository root, with Docker running and `deploy/.env` generated:

```sh
scripts/e2e.sh
```

The script brings up `deploy/compose.yaml` plus `deploy/compose.e2e.yaml` as its own compose project, `wab-e2e`, so it never touches a stack that `scripts/up.sh` started. It waits until every service is healthy and runs two suites on that one stack. First the API tests, inside the compose network against `http://platform-api:8000`. Then the browser suite, which drives the real Portal in a Playwright container (see "The browser suite" below). It prints PASS or FAIL for each suite and tears everything down with its volumes.

The browser suite runs in a runner image that `portal/e2e/runner-image.sh` builds from `portal/package-lock.json`. The host needs Docker and nothing else, and a `portal/node_modules` on the host is never used.

| Setting | Effect |
|---|---|
| `E2E_PROJECT=<name>` | Use another compose project name, so two stacks can run side by side. Give each its own host ports in `deploy/.env`. The default is `wab-e2e`. |
| `E2E_SUITES="api"` or `"ui"` | Run one suite. The default is `api ui`. `ui` alone on a fresh stack also takes the empty first screen shot, which the full run skips because the API tests have already made runs. |
| `KEEP=1` | Leave the stack running afterwards, for debugging. |
| `E2E_WAIT_SECONDS=90` | Longest any single wait may take. The failure message names the state the run was stuck in. |
| `WAIT_TIMEOUT=300` | Longest the stack may take to become healthy. |
| `PLATFORM_API_HOST_PORT=18000` | Needed when port 8000 is taken on your machine. `PORTAL_HOST_PORT` and `N8N_HOST_PORT` move the other two host ports. |
| `E2E_AUTH=oidc` | Run the stack with real sign-in against a mock identity provider (`deploy/compose.oidc.yaml`) and run only the oidc browser spec. The default project is then `wab-e2e-oidc`, the default suite is `ui`, and the stack publishes no host ports. The `api` suite signs in with `X-Dev-User`, so it runs only with the default, `E2E_AUTH=dev`. |
| `WAB_IMAGE_TAG=<tag>`, `E2E_RUNNER_IMAGE=<name>` | Tag the images this run builds, so a second checkout testing other code never replaces the images a running stack uses. The defaults are `dev` and `portal-e2e-runner:local`. `portal/e2e/run.sh` reads `PORTAL_E2E_IMAGE` the same way. |

Output lands in `e2e/out/` (gitignored). `up.log` is the stack start, `e2e.log` is the API test run, `ui.log` is the browser run, `compose.log` is `docker compose logs` for every service. Exit code 0 means all tests passed, 1 means a test failed, 2 means the stack never became healthy.

To run the tests from your machine against a stack that is already up:

```sh
cd e2e
PLATFORM_API_URL=http://localhost:18000 MOCK_GITHUB_URL=http://localhost:8200 uv run pytest
```

`mock-github` has no host port by default, so add one in a local override if you do this.

## What each test proves

| Test | Proves |
|---|---|
| `test_happy_path` | Alice saves a release check from the template and starts a run. The same `Idempotency-Key` returns the same run. The event stream (SSE) has no gaps from `seq` 1 up to `approval_requested`. The Teams stub holds the request with a link to the approval. Alice cannot decide (`own_work`, 403). Bob approves with the digest he was shown, and repeating it returns 200 and the same decision. The run succeeds with exactly one Jira ticket titled "New LangGraph releases: 1.2.16, 1.2.15". The event kinds, in order, equal `contracts/fixtures/runs/success.json`. Reconnecting with `Last-Event-ID` returns only later events. |
| `test_rejected` | When Bob declines, the run ends `rejected`, no ticket is written, and the event kinds equal `contracts/fixtures/runs/rejected.json`. |
| `test_failure_retry` | With GitHub down, the run fails with reason `AgentError`, retryable. The troubleshoot route suggests a retry. After GitHub recovers, Alice retries, the run reaches the approval gate again, Bob approves, and exactly one ticket is written. |
| `test_safety` | An unknown or missing `X-Dev-User` gets 401. Bob deciding with a stale digest is refused, the step stays open, and nothing is written. |
| `test_watchlist` | Alice adds three software to the team's watchlist: LangGraph at 1.2.14 (behind), Redis at 8.2.1 (up to date) and a repository the mock GitHub does not know. Adding a repository twice is 409, Bob cannot add (403), and a bad version is 422. One check sends one approval request with exactly one ticket, "Upgrade LangGraph from 1.2.14 to 1.2.16", and the Teams message names it. While it waits, the Software page shows LangGraph awaiting approval with the approval id, Redis up to date and the unknown repository as cannot check with the 404 in its problem, rows that need a person first. Bob approves, the ticket is written as To Do and LangGraph shows it as open. Bob cannot mark it Done (403); Alice marks it Done, twice with the same answer, and our version moves to 1.2.16 with source `ticket_done` and the ticket key. Removing software answers the list that is left. |
| `test_schedule` | Bootstrap reports the `schedule_tick` workflow as loaded and active. A tick with the wrong step key is 401, and a tick with nothing due answers 200 `{"started": []}` and starts no run. Slot timing is covered by the platform-api unit tests, which control the clock. |

Each test makes its own use case, so order does not matter. There is one watchlist per team, so `test_watchlist` first removes whatever a kept stack still watches. Tests count tickets by `run_id`, so a ticket from another test never counts. `test_rejected` also checks the total ticket count did not move.

## The browser suite

`portal/e2e/live/` holds Playwright specs that act as people, in a real browser, against the Portal, which talks to the real platform-api, n8n, agent runtime and PostgreSQL. They run in the runner image (pinned Playwright, locked dependencies) inside the Portal container's network namespace, so the page is at `http://localhost:8080`, `http://portal:8080` is the plain HTTP address, and `mock-github` still resolves. `portal/e2e/live/run.sh <portal-container>` runs them by hand against a stack that is already up.

| Spec | Proves |
|---|---|
| `02-release-check` | Alice opens the builder, plans the example, saves it and starts it with Run now. The run page draws the run as a line of stops, and the run pauses at the approval stop with nothing written. Alice sees why she cannot decide and has no Approve button. The Teams card for that approval is on the Teams page. It names the run, says the approval is waiting, and its link opens the approval page, where Alice is refused with the backend's own-work message. Back on the run page, Bob sees the exact ticket at the approval stop and approves it there with one click. The run ends with one ticket `MOCK-<n>` that mock Jira lists once, and the Teams card then says Bob approved it. The total ticket count goes up by exactly one. |
| `03-failure` | With mock-github `unavailable`, a run fails. The line breaks at the stop where the work was, and the AI troubleshooter's panel under it shows the backend's advice and Retry run. After mock-github is back and the platform's retry delay has passed, Retry run on the run page sends the run to the approval pause. Nothing is written. |
| `04-plain-http-origin` | Opens the Portal as `http://portal:8080`, a plain HTTP host name that is not localhost, so the browser has no `crypto.randomUUID`. Run now on a saved use case still opens the run page with no page error. `PLAIN_HTTP_URL` changes the address. |
| `05-proxy` | A trailing-slash request to `/api/v1/runs/` through the Portal gets a plain 404 and no redirect. The API used to redirect to `http://platform-api:8000/...`, which names the internal host and a browser cannot reach. |
| `06-oidc-sign-in` (`.oidc.ts`, runs only with `E2E_AUTH=oidc`) | Alice opens the Portal, is sent to the mock identity provider's form, signs in, and comes back with her name and both roles in the header and no user switcher. `GET /api/v1/me` with her token answers her id and roles. She starts a run, sees why she cannot approve it, and the backend refuses her own token with `own_work`. `X-Dev-User` alone gets 401. The Portal renews her token with the refresh token before it expires, and the new token still works. Bob signs in on a link to the run, comes back to that run, and approves it with one click. Exactly one ticket is written. Bob signs out and sees the sign-in page, not a redirect. The backend checks use the tokens the Portal itself received. |
| `01-first-screen` | On a stack with no runs, the first screen shows the example's line of stops, Run the example and Describe your own task, with no serious accessibility finding in either theme. One click starts one run that waits at the approval with nothing written. It skips when runs exist, so run it on a fresh stack with `E2E_SUITES=ui`. |

The specs pick elements by accessible role and name, by the backend's own strings and by URL. They do not read animation timing.

Evidence lands in `portal/e2e/out/live/` (gitignored). `shots/` has a 1440 by 900 screenshot per step and 390 by 844 shots of the run page and the first screen. `video/success-path.webm` records the whole success path.

## Mock GitHub

`e2e/mock_github/` is a small server with no dependencies. It answers `GET /repos/{owner}/{name}/releases` in GitHub's shape for two repositories. `langchain-ai/langgraph` has 30 releases, newest first, with 1.2.16, 1.2.15 and 1.2.14 at the top and other tag families (`cli==...`, `sdk==...`) below them. `redis/redis` has six, newest 8.2.1. Any other repository answers 404, as GitHub does. `per_page` and `page` work. `POST /_admin/mode` with `{"mode": "unavailable"}` makes every releases route answer 503, and `{"mode": "ok"}` restores it. Every test starts and ends with the mode set to `ok`.

Its own tests run in its container:

```sh
docker build --target test -t mock-github:test e2e/mock_github && docker run --rm mock-github:test
```

## What the harness assumes

These points are not spelled out in `contracts/`. If the real API differs, change the contract or the harness on purpose.

- The release check's last seen tag is the use case param `last_seen_tag` (`params` values are strings). The tests set it to `1.2.14`.
- Starting a run again with the same `Idempotency-Key` answers 200 or 201 with the same `run_id`.
- A missing `X-Dev-User` gets 401, the same as an unknown one.
- A stale digest is refused with 403, 409 or 422, and does not close the step.
- After a retry, the next event is `run_retried` with `seq` continuing from the failed run's last `seq`.
- A watchlist check's ticket is titled `Upgrade {name} from {our version} to {newest}`, and the problem of a software the mock GitHub does not know names the 404.

## Checks

```sh
cd e2e
uv run ruff check . && uv run ruff format --check .
uv run pyright
python -m unittest discover -s mock_github
```
