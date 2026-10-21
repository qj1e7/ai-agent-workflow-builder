# Load test evidence: k6 against the running stack

**Date.** 22 Oct 2026 (Singapore time).
**Code.** Commit `950e6cf` on branch `ci/dast-and-load`.
**Command.** `scripts/load.sh`, from a clean start (stack started fresh, torn down with its volumes). It passed twice in a row. Each run took 89 seconds in total, with a 60 second measured part.
**Tool.** k6 2.3.0, image `grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34`. The script is `load/team.js`.
**Files.** `k6.log` (the run's output), `summary.json` (k6's metrics export), `stats.log` (CPU and memory of each container every few seconds). The `probe-*` files are extra runs that look for the limit (see below).

## The machine and its state

- Apple M3 Max laptop, 16 cores. Docker Desktop runs a Linux VM with 16 CPUs and 7.65 GiB of memory. About 25 other containers (the team lead's own projects, mostly idle) ran in the same VM during the test.
- The stack was started from scratch for every run. Images were already built. The k6 generator ran in the same VM, on the stack's own Docker network.
- The state is warm for the images and cold for the processes. Before the measured minute the script starts 30 runs and waits until all of them reach the approval gate. That gives the database a history and exercises each route once. There is no other warm-up.

## What it does

All requests go through the Portal's nginx, as Alice, the way the browser sends them. Rates are requests per second and are held constant, whatever the answer time. The measured part lasts 60 seconds.

| Path | Rate | Why this rate |
|---|---|---|
| List runs | 10 per second | The runs page and its polling. |
| Get one run | 10 per second | A run page open in a tab polls about every 2 seconds. Five staff with a few tabs each is about 3 per second. This is a team several times busier. |
| Read a run's events page | 10 per second | Same reasoning. |
| List approvals | 5 per second | See the note below. |
| Portal static files | 10 per second, 2 requests each | The page and one script or style file. |
| Start a run | 1 every 5 seconds | See below. |

**List approvals.** platform-api has no route that lists approvals. The Teams stub lists every approval request, and that is what the Portal's Teams page reads, so the test calls `GET /api/v1/teams-stub/messages`.

**Run start rate.** One run every 5 seconds is 12 a minute. Starting a run costs n8n an execution, the agent a call, and mock GitHub a call. This test measures the reads, so the rate is low enough that those are not the limit. n8n used about 6 to 7 percent of one core when a run started and was idle between runs. Its one high reading (69 percent) was in the setup step, when 30 runs start together, before the measured minute.

## Limits we set, and the result

Each limit is at least 9 times the measured value, so a slower machine such as a CI runner still passes. Every path also needs fewer than 1 percent failed requests.

| Path | p95 limit | p95 measured | Failed |
|---|---|---|---|
| List runs | 250 ms | 27.5 ms | 0 of 601 |
| Get one run | 100 ms | 7.5 ms | 0 of 600 |
| Events page | 100 ms | 6.4 ms | 0 of 601 |
| List approvals | 100 ms | 5.8 ms | 0 of 301 |
| Portal static | 100 ms | 0.56 ms | 0 of 1202 |
| Start a run | 500 ms | 11.2 ms | 0 of 12 |

All 3,317 checks passed. The whole test sent 3,350 requests, about 55 per second.

## What the numbers mean

At this load the stack answers a read in a few milliseconds and the biggest read, list runs, in under 30 ms. The team's usage is far under what the stack can do. That is the useful message: a busy team will not notice the platform.

## What limits the numbers

We turned the rate up (`RATE_SCALE`) to find where it breaks. Same machine, same stack, 30 seconds each.

| Rate | Requests per second | list runs p95 | get run p95 | events p95 | platform-api CPU (peak) | Result |
|---|---|---|---|---|---|---|
| 1x (the test) | 55 | 27.5 ms | 7.5 ms | 6.4 ms | 36% | Pass |
| 3x | 160 | 24 ms | 5.2 ms | 4.6 ms | 63% | Pass |
| 6x | 315 | 313 ms | 183 ms | 8.5 ms | 114% | Fail, 26 requests dropped |
| 12x | 490 | 3.8 s | 3.7 s | 13 ms | 115% | Fail, 3,316 requests dropped |

- **platform-api saturates first.** It is one process. At 6x it uses about one core and a bit more, and PostgreSQL stays near 35 to 40 percent. n8n, the agent and mock GitHub are not near any limit. nginx and the static files stay under 1 ms at every rate.
- **The knee is between 3x and 6x** the test load. Failed requests stay at 0 percent even at 12x. The stack gets slow, it does not fail. The load generator drops iterations it cannot start in time, which shows as dropped iterations.
- **The events page stays fast** at 6x and 12x (13 ms), while get run and list approvals slow down. They use a different database pool. We did not separate the cost of Python work from the wait for a database connection. That split is a guess, not a measurement.
- **List runs grows with history.** It returns every run, with no paging. With 31 runs in the history it took 27.5 ms at p95. With 151 runs it took 74 ms (`probe-history-150.log`), about 0.4 ms for each extra run. Nothing was tested beyond 151.

## What this test does not cover

- One machine, one run of each rate. We did not repeat the probes, so the knee is a range, not a figure.
- The browser. This is HTTP only. Page rendering and the animated live view are not measured.
- The live event stream (SSE) under many viewers.
- Run completion. The test starts runs and measures the start. It does not wait for the work to finish.
- Approvals being decided under load, and retries.
- Azure, DevNet, a real database server, TLS, or any real Jira, Teams or GitHub. Numbers from Azure Container Apps will differ.
- Long runs. Each test lasts one minute, so memory growth over hours is not seen.
