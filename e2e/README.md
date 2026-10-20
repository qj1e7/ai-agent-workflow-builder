# End to end harness

This harness is the definition of done for the whole product. It starts the real stack (postgres, n8n, agent runtime, platform-api) with a fake GitHub, then acts like the Portal: plain HTTP calls as the dev users `alice` (Operator and Approver) and `bob` (Approver). It never imports platform code and never reads a database.

## Run it

From the repository root, with Docker running and `deploy/.env` generated:

```sh
scripts/e2e.sh
```

The script brings up `deploy/compose.yaml` plus `deploy/compose.e2e.yaml`, waits until every service is healthy, runs the tests inside the compose network against `http://platform-api:8000`, prints PASS or FAIL, and tears everything down with its volumes.

| Setting | Effect |
|---|---|
| `KEEP=1` | Leave the stack running afterwards, for debugging. |
| `E2E_WAIT_SECONDS=90` | Longest any single wait may take. The failure message names the state the run was stuck in. |
| `WAIT_TIMEOUT=300` | Longest the stack may take to become healthy. |
| `PLATFORM_API_HOST_PORT=18000` | Needed when port 8000 is taken on your machine. |

Output lands in `e2e/out/` (gitignored). `up.log` is the stack start, `e2e.log` is the test run, `compose.log` is `docker compose logs` for every service. Exit code 0 means all tests passed, 1 means a test failed, 2 means the stack never became healthy.

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

Each test makes its own use case, so order does not matter. Tests count tickets by `run_id`, so a ticket from another test never counts. `test_rejected` also checks the total ticket count did not move.

## Mock GitHub

`e2e/mock_github/` is a small server with no dependencies. It answers `GET /repos/langchain-ai/langgraph/releases` in GitHub's shape: 30 releases, newest first, with 1.2.16, 1.2.15 and 1.2.14 at the top and other tag families (`cli==...`, `sdk==...`) below them. `per_page` and `page` work. `POST /_admin/mode` with `{"mode": "unavailable"}` makes the releases route answer 503, and `{"mode": "ok"}` restores it. Every test starts and ends with the mode set to `ok`.

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

## Checks

```sh
cd e2e
uv run ruff check . && uv run ruff format --check .
uv run pyright
python -m unittest discover -s mock_github
```
