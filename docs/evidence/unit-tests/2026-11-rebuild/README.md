# Unit tests on the rebuilt app

**Date.** 31 Oct 2026, 10:29 (agent runtime) and 10:40 (platform-api) Singapore time.
**Code.** Commit `22da245` on branch `rebuild/p15-evidence`. Its app code is `main` at `8ee417d`, after P1 to P14 of the rebuild plan.
**Result.** 2,195 tests, all passed. None failed, none errored and none was skipped.

| Project | Tests | Passed | Failed | Skipped | Time | Report |
|---|---|---|---|---|---|---|
| platform-api | 1,374 | 1,374 | 0 | 0 | 107.8 s | `platform-api.xml`, `platform-api.txt` |
| agent-runtime | 821 | 821 | 0 | 0 | 7.0 s | `agent-runtime.xml`, `agent-runtime.txt` |

The `.xml` files are pytest's JUnit reports, one `testcase` per test. The `.txt` files are what pytest printed. The machine's name is replaced with `laptop` in the reports.

## How they ran

On the team lead's laptop, with `uv` and the locked dependencies of each project: Python 3.14.3 and pytest 9.1.1.

```sh
cd agent-runtime
uv sync --locked
uv run pytest -p no:cacheprovider -q --junitxml=agent-runtime.xml

cd ../platform-api
uv sync --locked
PLATFORM_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:45032/postgres \
COSMOS_ENDPOINT=http://127.0.0.1:45081 COSMOS_REQUIRED=1 \
CONTRACT_FIXTURES=../contracts/fixtures MOCK_OIDC_CONFIG=../deploy/mock-oidc/config.json \
uv run pytest -p no:cacheprovider -q --junitxml=platform-api.xml
```

platform-api's tests ran against a throwaway PostgreSQL 17 and a throwaway Cosmos DB emulator, the same images and digests CI uses, started for this run and removed after it:

- `postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3` on `127.0.0.1:45032`;
- `mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-preview@sha256:db53613dae19d0a3d5ad50688d14aa6e957af082dafea56b52e1bd3a6b3f1406` on `127.0.0.1:45081`, with `packages.microsoft.com` sent nowhere, as in CI.

`COSMOS_REQUIRED=1` makes any Cosmos DB test that skips count as a failure. pytest printed `Cosmos DB tests: 63 passed, 0 failed, 0 skipped`.

CI's `checks` job runs the same tests inside each project's `test` image (`docker build --target test`), with the same PostgreSQL and emulator as services. We ran them on the laptop instead to save room on the shared Docker disk. The tests and their settings are the same.

## What changed since the old app

ADR 0028 counted 1,541 backend unit tests on 29 Oct, before the rebuild. The rebuilt app has 2,195. platform-api's 54 test modules include the new ones for people and roles (`test_people`), the workflow lifecycle (`test_builder_lifecycle`), the Software watchlist (`test_watch`), agent cards (`test_builder_cards`), sign-in (`test_oidc`) and the Cosmos DB copy.

## What these tests do not cover

- The Portal's own unit tests (Vitest). CI's `portal` job runs them on every pull request.
- The whole stack together. `scripts/e2e.sh` runs the API and browser tests on the real stack, and the checker's lane 4 runs it for this pull request.
- The AI model. The tests use a fake model or none. The model's quality is scored by the evals in `agent-runtime/evals/` (ADR 0032).
- Azure. The emulator is not Azure Cosmos DB (ADR 0031). P14's lanes check the same reads on Azure.
