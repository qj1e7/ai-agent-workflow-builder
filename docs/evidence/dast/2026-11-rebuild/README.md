# DAST on the rebuilt app: OWASP ZAP against the running stack

**Date.** 31 Oct 2026, 10:29 and 10:32 Singapore time (02:29 and 02:32 UTC).
**Code.** Commit `22da245` on branch `rebuild/p15-evidence`. That is `main` at `8ee417d`, after P1 to P14 of the rebuild plan, plus the fix to `scripts/dast.sh` for issue #79. No app code differs from `main`.
**Command.** `E2E_PROJECT=p15-scan WAB_IMAGE_TAG=p15 scripts/dast.sh`, twice in a row, each from a clean start: the stack started fresh and was taken down with its volumes. The first run took 116 seconds and the second 101 seconds, images already built. The second run kept its stack for a few minutes (`KEEP=1`) so we could read what the scan had changed, and was then taken down.
**Tool.** OWASP ZAP 2.17.0, image `zaproxy/zap-stable:20260807@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef` (built 7 Aug 2026), the same as the 22 Oct scan.
**Result.** PASS both times. No finding at High or Medium on any target.

## What ran

`scripts/dast.sh` starts the real stack (PostgreSQL, the Cosmos DB emulator, n8n, the agent runtime, platform-api and the Portal) with a fake GitHub and a fake AI model, as its own compose project. Nothing is published on the host. It adds LangGraph to the Software watchlist and runs a check that waits at the approval gate, so ZAP calls real ids. Then ZAP joins the project's own network and scans three targets. Every request carries `X-Dev-User: alice`, who is an Operator and an Approver.

| Scan | Target | Kind | Run 1 | Run 2 |
|---|---|---|---|---|
| `api` | platform-api, from its OpenAPI document: 53 routes, 63 operations | Active scan | 112 rules pass, 0 warn, 0 fail | the same |
| `api-via-portal` | The 45 `/api/` routes (55 operations) through the Portal's nginx | Active scan | 112 pass, 0 warn, 0 fail, 1 ignored | the same |
| `portal` | The Portal's page, scripts and styles through nginx | Passive baseline | 60 pass, 0 warn, 0 fail, 1 ignored | the same |

platform-api answered 34,802 requests in run 1 and 34,800 in run 2, nearly all of them from ZAP (`access-counts-run1.txt`, `access-counts-run2.txt`). On 22 Oct the old app had 21 routes and the scans sent about 7,000.

## Findings by risk

From the JSON reports of run 1. Run 2 raised the same alerts.

| Risk | Rule | Where | Count | What it is |
|---|---|---|---|---|
| High | none | | 0 | |
| Medium | none | | 0 | |
| Low | 100001 Unexpected Content-Type was returned | `api-via-portal` only | 93 | **False positive, recorded in `dast/zap-rules-via-portal.conf`.** ZAP probes paths outside the API document, such as `/.env`. nginx answers each with the Portal's `index.html`, as a single-page app does. The direct scan keeps the rule on and found nothing |
| Informational | 100000 A Client Error response code was returned | both API scans | 655 and 456 | **Recorded in `dast/zap-rules.conf`.** ZAP sends bad input on purpose, and the API refuses it with 4xx |
| Informational | 10104 User Agent Fuzzer | both API scans | 5 each | ZAP's note that answers did not change with the user agent. Not a weakness, and it fails no run |
| Informational | 10109 Modern Web Application | `portal` | 3 | **Recorded.** ZAP's hint that the Portal is a single-page app, so its plain spider sees little |

Against the old app on 22 Oct (`docs/evidence/dast/`): the same rules raised the same alerts, with no High, no Medium and one recorded Low. So the rebuilt app has no more Medium or High findings than the old one. The checker's lane 1 runs `scripts/dast.sh` at `a55fb84` too, for a comparison on the same day.

## What the scan shows

**Where these figures come from.** The request counts come from each run's compose log, the stack's own log that `scripts/dast.sh` writes to `dast/out/compose.log`. The logs are 8 MB each, so they are not saved here. `access-counts.py` recounts the figures from them, and its output is saved as `access-counts-run1.txt` and `access-counts-run2.txt`. The row counts come from psql queries on run 2's kept stack, before it was taken down. Their output was not saved, and that stack is gone, so they cannot be read again. The next scan run with `KEEP=1` should save them.

- **The approval gate held.** From the compose log: in run 1, 1,226 of ZAP's requests went to the decision route. 432 were well formed enough to reach the check, and all 432 got 403, because Alice started the seeded run, and nobody approves their own work. 788 were malformed and got 422, 2 got 404 and 4 got 405. None was accepted.
- **Nothing was written.** From psql, not saved: after run 2, before the stack was taken down, `orchestration.approval_decisions`, `write_executions`, `mock_jira_tickets` and `confirmations` had 0 rows, and `builder.cards` and `builder.drafts` had 0 rows. The People list still held only the three seeded people.
- **The People and roles routes refused every change.** From the compose log: ZAP's requests to add a person, change a role, ask for an Approver or decide a confirmation got 404, 405, 409 or 422. Only the two read routes, `GET /api/v1/people` and `GET /api/v1/confirmations`, answered 200.
- **No AI model setting was saved.** From the compose log, `PUT /api/v1/settings/model` answered 200 to 1,188 requests. That route answers 200 with the model test's result, and each test failed, because no address ZAP sent is a model service. From psql, not saved: `orchestration.model_setting` had 0 rows after run 2.
- **The activity log reached Cosmos DB.** The scan's two runs wrote 26 events to `monitoring.run_events` (from psql, not saved), and the copier copied all 26 to the emulator, 15 and 11 items in two partitions (saved in `docs/evidence/diagrams/cosmos-2026-10-31.txt`). The events route ZAP read was served from that copy.

## Issue #79: ZAP's proxy port

Main's CI run 41098264253 failed the scan through nginx with "no summary". ZAP had stopped before scanning, because it could not bind its proxy port. ZAP's scan scripts pick a random port from 32768 to 61000 (`get_free_port` in `zap_common.py`), the range Linux also gives every outgoing connection, so something in the container can hold it at the moment ZAP binds. `scripts/dast.sh` now starts every scan with `-P 8090`, outside that range. If ZAP still cannot start its proxy, the script runs that scan once more, prints ZAP's error, and its summary says nothing was scanned instead of "no summary".

Neither run here hit the bind failure. `zap-port-retry-test.sh` runs the script's own `run_zap` and `summary_line` with `docker` replaced by a stub. Part 1 of `zap-port-retry-test.txt` shows the three cases: a bind failure once (retried, then pass), a bind failure twice (exit 3, "ZAP did not start its proxy, so nothing was scanned"), and a real alert (exit 1, no retry). Every call passed `-P 8090`. The retry writes the same log file, so the second try's log replaces the first. The first try's error lines stay in the job's output.

**After the P15 review.** The closing line used to call any failed scan an alert, even one where ZAP never started. Now `scripts/dast.sh` sorts each failed scan three ways. If ZAP did not start, it says "FAIL: ZAP did not start for N scan(s), so nothing was scanned there. Run the job again." and exits with 3. If ZAP stopped with an error before its summary, it says so and exits with 1. The alert sentence is kept for a real alert, which also exits with 1 and wins over a scan that only needs running again. Part 2 of `zap-port-retry-test.txt` runs the script's own closing lines on made-up logs for six cases, including a crash alone (exit 3, no alert sentence) and a crash with an alert (both sentences, exit 1). The two runs above used the script before this change. Both passed every scan, so the new closing lines would print the same thing for them.

**The wait for ZAP to start is now 3 minutes, not 10.** ZAP's `-T` sets how long its scan script waits for ZAP to start, and then for the passive scan to finish. When the proxy cannot start, ZAP stops, but the script still waits the whole `-T` before it gives up. In run 41098264253 that cost 600 seconds for one try. That run's own log shows a normal start is fast: ZAP reached its proxy 5 seconds after Java started, and the direct API scan, passive wait included, took 48 seconds from loading the API document to the next scan starting. 3 minutes keeps a wide margin over both, and a scan that never starts now costs at most 6 minutes over its two tries, not 20, inside the CI job's 35-minute limit.

## Files

| File | What it is |
|---|---|
| `api.html`, `api.json` | ZAP's report of the direct API scan, run 1 |
| `api-via-portal.html`, `api-via-portal.json` | The scan through nginx, run 1 |
| `portal.html`, `portal.json` | The Portal baseline, run 1 |
| `*-run1.log`, `*-run2.log` | ZAP's rule list and summary line for each scan in each run |
| `dast-run1.txt`, `dast-run2.txt` | What `scripts/dast.sh` printed |
| `access-counts.py`, `access-counts-run1.txt`, `access-counts-run2.txt` | The count of platform-api's answers by route and status, from each run's compose log. Run it as `python3 -I access-counts.py dast/out/compose.log` |
| `zap-port-retry-test.sh`, `zap-port-retry-test.txt` | The stub test of the retry and of the closing lines, and its output. Run it as `bash docs/evidence/dast/2026-11-rebuild/zap-port-retry-test.sh scripts/dast.sh` |

## What this scan does not cover

- **Other people.** Only Alice. ZAP does not check that Bob or Carol are kept out of what they should not see. The unit and end-to-end tests cover the roles.
- **Real sign-in.** The scan uses dev sign-in. Entra ID sign-in and its token check are not scanned here. P14's lane 10 runs ZAP's baseline against the Portal on Azure.
- **The internal routes past their key.** ZAP has no step key or callback token. Its requests to `/internal/v1` got 401, 404, 405 or 422. The only answers of 200 and 202 there were n8n's and the agent runtime's own calls for the seeded run.
- **The live event stream.** ZAP read the events route as one JSON page.
- **The Portal's screens.** The baseline reads the page shell, scripts, styles and headers. It does not run the app. The DOM-based cross-site scripting rule stays off (`dast/zap-rules.conf`), because it ran the scan out of memory on this machine on 22 Oct.
- **n8n, PostgreSQL and the Cosmos DB emulator.** They are not targets.
- **Transport.** Everything runs over plain HTTP inside Docker.
