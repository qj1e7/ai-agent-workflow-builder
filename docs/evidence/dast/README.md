# DAST evidence: OWASP ZAP against the running stack

**Date.** 22 Oct 2026 (Singapore time).
**Code.** Commit `950e6cf` on branch `ci/dast-and-load`.
**Command.** `scripts/dast.sh`, run from a clean start (stack started fresh, torn down with its volumes). It passed twice in a row. Each run took 67 seconds.
**Tool.** OWASP ZAP 2.17.0, image `zaproxy/zap-stable:20260807@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef` (built 7 Aug 2026).

## What the script does

It starts the real stack (PostgreSQL, n8n, agent runtime, platform-api, Portal) with a fake GitHub, as its own compose project. Nothing is published on the host. It makes one use case and one run that waits at the approval gate, so ZAP calls real ids. Then ZAP joins the project's own Docker network and scans three targets. It never targets anything outside that network.

| Scan | Target | Kind | Rules checked | Result |
|---|---|---|---|---|
| `api` | platform-api, from its OpenAPI document (21 routes) | Active scan | 112 pass, 0 warn, 0 fail | PASS |
| `api-via-portal` | The same `/api/` routes through the Portal's nginx | Active scan | 112 pass, 0 warn, 0 fail, 1 ignored | PASS |
| `portal` | The Portal's static files through nginx | Passive baseline | 60 pass, 0 warn, 0 fail, 1 ignored | PASS |

The reports are `api.html`, `api-via-portal.html` and `portal.html`, each with a `.json` beside it. The active scans sent about 7,000 requests to platform-api between them.

## Sign-in

Dev sign-in reads an `X-Dev-User` header. ZAP adds `X-Dev-User: alice` to every request it sends. Alice is both an Operator and an Approver, so ZAP reached every `/api/v1` route. The platform-api log shows 200 answers on all the read routes. ZAP also pinned `Accept: application/json`, so the events route returns one page instead of a stream that never ends.

## Findings and what we did

| Finding | Where | What we did |
|---|---|---|
| **X-Content-Type-Options header missing** (ZAP 10021, Low). Seen on 14 platform-api responses in the first scan. | platform-api | **Fixed at the cause.** A small middleware now sends `X-Content-Type-Options: nosniff` on every response, errors and event streams included. A test covers 200, 401 and 404 answers. Commit `21547d8`. The next scan had no alert. |
| **Redirect to the internal host name.** ZAP did not raise an alert. We saw it in the traffic of the scan through the Portal: a request for `/api/v1/runs/` (trailing slash) was redirected to `http://platform-api:8000/api/v1/runs`, which names the internal host and cannot be reached from a browser. | platform-api behind nginx | **Fixed at the cause.** FastAPI no longer redirects a trailing slash, so it answers 404. This removes the dependence on the Host header. A unit test and a browser spec (`portal/e2e/live/05-proxy.live.ts`) cover it. Commit `d84f83f`. |
| **A Client Error response code was returned** (ZAP 100000, Info). | Both API scans | **False positive, recorded.** ZAP sends bad input on purpose, so the API answers 4xx. That is the API refusing it. |
| **Unexpected Content-Type** (ZAP 100001, Low). 94 instances. | Scan through nginx only | **False positive, recorded.** ZAP probes paths such as `/.env` that are not in the API document. nginx answers every unknown path with the Portal's `index.html`, which is how a single-page app works. The page is public and holds no data. The direct scan keeps this rule on and found nothing. |
| **Cross Site Scripting (DOM Based)** (ZAP 40026). | Both API scans | **Not run, recorded.** This rule drives a headless browser. On this machine's 8 GB Docker VM it ran the scan container out of memory on 3 of 3 runs. The API only returns JSON, so there is no page for a browser to run script in. The Portal's DOM is a gap (see below). |
| **Modern Web Application** (ZAP 10109, Info). | Portal | **Not a weakness, recorded.** ZAP's hint that the Portal is a single-page app and its plain spider sees little. It is a coverage note. |

The rules and the reason for each are in `dast/zap-rules.conf` and `dast/zap-rules-via-portal.conf` in the repository. Nothing else is ignored. A rule that is not listed fails the run.

## What the scan shows

- No alert at Medium or High on any target.
- The approval gate held under attack. 434 of ZAP's requests to the decision route were well formed enough to reach the check. All 434 got 403, and none was accepted, so ZAP wrote no ticket. Another 788 were malformed and got 422.
- The internal routes (`/internal/v1/...`) are not reachable through the Portal. In an earlier, wider run through nginx (not saved) they answered 405 or 404 from nginx, not from platform-api. The saved scan through nginx covers `/api/` only.

## What this scan does not cover

- **Other people.** Only Alice. ZAP does not check that Bob or Carol are kept out of things they should not see.
- **The internal callback routes, past their key.** ZAP has no step key or callback token. It sent them malformed input and got 422. It did not test what happens after a valid key.
- **The live event stream.** ZAP read the events route as one JSON page. It did not scan the stream.
- **The Portal screens.** The Portal is a single-page app. The baseline scan reads the page shell, scripts, styles and headers. It does not run the app. ZAP's browser-based spider crashed in this image on this machine (it lost its connection to ZAP), so we did not use it. It may work on the CI runner, which we have not tried.
- **Real sign-in.** Dev sign-in is a local stub. Entra sign-in does not exist yet, so nothing about it is tested.
- **n8n.** Its editor and webhooks are not published and were not scanned.
- **Transport.** Everything runs over plain HTTP inside Docker. TLS is not tested.
- **Run in a different place.** DevNet, Azure and any real Jira, Teams or GitHub are not part of this.

## Notes on the run

- ZAP starts with `-silent`, so it makes no update check. Its add-ons come inside the image.
- ZAP keeps its home and temp folders in memory (`--tmpfs`). The Docker disk on this machine was close to full, and without this ZAP could not unpack its add-ons and wrote empty reports. In memory it leaves nothing behind.
- Re-run the scan with `scripts/dast.sh`. Reports land in `dast/out/` (not committed). `E2E_PROJECT=<name>` changes the compose project name.
