# Load test on the rebuilt app: k6 against the running stack

**Date.** 31 Oct 2026, 10:36 and 10:37 Singapore time (02:36 and 02:37 UTC), and one extra run at 10:53.
**Code.** Commit `22da245` on branch `rebuild/p15-evidence`. Its app code is `main` at `8ee417d`, after P1 to P14 of the rebuild plan.
**Command.** `E2E_PROJECT=p15-scan WAB_IMAGE_TAG=p15 scripts/load.sh`, twice in a row, each from a clean start: the stack started fresh and was taken down with its volumes. Each run took 95 seconds in total, with a 60 second measured part.
**Tool.** k6 2.3.0, image `grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34`, and the script `load/team.js`, the same as on 22 Oct.
**Result.** PASS both times. Every threshold held, all 3,317 checks passed in each run, and no request failed.

## What it does

The same load as on 22 Oct. All requests go through the Portal's nginx as Alice. Before the measured minute, the script starts 30 runs and waits until all of them reach the approval gate, so the history holds 31 runs. Since P2, every run is a Software watchlist check of LangGraph against a fake GitHub (`scripts/lib/seed.py`), where on 22 Oct each was a release check.

| Path | Rate | Route |
|---|---|---|
| List runs | 10 per second | `GET /api/v1/runs` |
| Get one run | 10 per second | `GET /api/v1/runs/{run_id}` |
| Read a run's events page | 10 per second | `GET /api/v1/runs/{run_id}/events?after=0`, as JSON |
| List approvals | 5 per second | `GET /api/v1/teams-stub/messages`, what the practice Teams panel reads |
| Portal static files | 10 per second, 2 requests each | the page and one script or style file |
| Start a run | 1 every 5 seconds | `POST /api/v1/use-cases/{use_case_id}/runs` |

The machine is the same as on 22 Oct: an Apple M3 Max laptop with 16 cores, and a Docker VM with 16 CPUs and 7.65 GiB of memory, shared with about 30 other containers of the team lead's projects.

## The 95th percentile of each route, against 22 Oct

The 22 Oct report (`docs/evidence/load-test/README.md`) is the baseline, because the routes and the seeded runs changed in P2.

| Path | p95 limit | 22 Oct, old app | Run 1 | Run 2 | Median, run 1 and 2 | Requests, failed |
|---|---|---|---|---|---|---|
| List runs | 250 ms | 27.5 ms | 8.09 ms | 8.23 ms | 6.77 and 6.75 ms | 601 and 600, 0 failed |
| Get one run | 100 ms | 7.5 ms | 6.97 ms | 7.17 ms | 5.65 and 5.68 ms | 600 and 601, 0 failed |
| Events page | 100 ms | 6.4 ms | 11.02 ms | 11.23 ms | 9.35 and 9.41 ms | 601 and 601, 0 failed |
| List approvals | 100 ms | 5.8 ms | 5.17 ms | 5.04 ms | 3.63 and 3.73 ms | 300 and 301, 0 failed |
| Portal static | 100 ms | 0.56 ms | 0.47 ms | 0.49 ms | 0.23 and 0.23 ms | 1,202 and 1,202, 0 failed |
| Start a run | 500 ms | 11.2 ms | 19.58 ms | 16.30 ms | 13.05 and 12.98 ms | 13 and 12, 0 failed |

Each run sent 3,355 requests, about 50 per second. k6 dropped no iteration. Every route stayed far under its threshold: the slowest, the events page, used 11 percent of its limit.

## What changed, and why

- **List runs is about 3 times faster.** The 23 Oct fix reads each run's last event, proposal, approval and decisions for all runs at once, in 5 queries (commit `8f156d4`). The 22 Oct number was before that fix.
- **The events page is about 5 ms slower.** On the rebuilt app it reads Cosmos DB (ADR 0031). It asks PostgreSQL for the run's last event number, then reads the items up to it from the emulator. To check that this is the cause, we ran the same test once more with `ACTIVITY_READER=postgres`, which reads PostgreSQL only. The events page's p95 went back to 7.0 ms, with a median of 5.3 ms, and every other read stayed within half a millisecond of runs 1 and 2 (`k6-postgres-reader.log`). So about 4 ms is the read from the emulator. The emulator is not Azure, so this says nothing about Cosmos DB's speed on Azure.
- **Start a run is about 5 to 8 ms slower.** It has only 12 or 13 requests, so its p95 is close to the second slowest request and moves between runs, as on 23 Oct. Starting a watchlist check also builds the run's task from the watchlist (`Builder.run_spec_for`), where a release check had its repository in the use case. We did not measure which part costs more.
- **The other reads did not change much,** within about 1 ms of 22 Oct.

## CPU and memory

From `stats-run1.log` and `stats-run2.log`, a sample every few seconds during each run. platform-api's median CPU was 8 percent of one core, with a peak of 24 percent. The Cosmos DB emulator used 4 percent and up to 490 MiB of memory. PostgreSQL's median was under 2 percent. n8n and the agent runtime were idle between run starts. The stack is nowhere near a limit at this load. We did not repeat the 22 Oct runs that look for the knee at 3, 6 and 12 times this load.

## Files

| File | What it is |
|---|---|
| `k6-run1.log`, `k6-run2.log` | k6's output, with each threshold and check |
| `summary-run1.json`, `summary-run2.json` | k6's metrics export |
| `stats-run1.log`, `stats-run2.log` | CPU and memory of each container during the run |
| `load-run1.txt`, `load-run2.txt` | What `scripts/load.sh` printed |
| `k6-postgres-reader.log`, `summary-postgres-reader.json`, `stats-postgres-reader.log`, `load-postgres-reader.txt` | The extra run with `ACTIVITY_READER=postgres` |

## What this test does not cover

- The live event stream under many viewers. The test reads the events page as JSON.
- The browser. Page rendering and the run page's motion are not measured. P14's perf lane measures Home's paint and the stream's delay on Azure.
- Run completion, approvals under load, and retries.
- Azure, a real Cosmos DB account, TLS, DevNet, and a real Jira, Teams or GitHub.
- A larger history. List runs still returns every run, with no paging.
- Long runs. Each test lasts one minute.
