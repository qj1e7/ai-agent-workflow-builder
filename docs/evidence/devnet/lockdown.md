# The lock-down test: the app with no way out but a proxy

**Date.** 31 Oct 2026, 11:07 Singapore time (03:07 UTC).
**Code.** Commit `0166495` on branch `rebuild/p15-evidence`, with `deploy/compose.lockdown.yaml` and the scripts in this folder as committed next. Its app code is `main` at `8ee417d`, after P1 to P14 of the rebuild plan.
**Command.** `LOCKDOWN_PROJECT=p15-lock WAB_IMAGE_TAG=p15 docs/evidence/devnet/lockdown-run.sh`, from a clean start. It took 37 seconds, with the images already built, and took the stack down with its volumes at the end.
**Result.** The Software watchlist check ran to Done through the proxy. Every call to a host off the allow list was refused. Connecting the AI model broke, even though its address is on the list.

[The DevNet move](../../design/devnet-move.md) asks for this test before we have DevNet access. NCS has not yet said whether DevNet has a proxy out to the internet, or what it allows (question 5 there). This test assumes the strictest likely answer: no route out at all, except a proxy that lets through a short list of hosts.

## How the test locks the stack

`deploy/compose.lockdown.yaml` is laid over `deploy/compose.yaml`. It does three things.

- **It cuts the route out.** The stack's network becomes an internal Docker network. Docker gives a container on it no route outside the network and no answer for an outside name, and nothing on it can be published on the host.
- **It adds one way out.** A Squid proxy, `egress-proxy` (`ubuntu/squid:6.6-24.04_edge`, Squid 6.14, pinned by digest), joins both the locked network and one that reaches the internet. It lets through only these hosts, the ones the app calls today:
  - `login.microsoftonline.com`, for Entra ID sign-in;
  - `api.github.com`, for the watchlist's releases;
  - `llm-gateway.aisg.sg`, the AI model's address (ADR 0021).
  
  It refuses everything else with 403 and writes every request, allowed or refused, to its access log.
- **It tells each service to use the proxy.** platform-api, the agent runtime, n8n, bootstrap and the Cosmos DB emulator get `HTTPS_PROXY` and `HTTP_PROXY`, and `NO_PROXY` for the stack's own service names.

The test uses no fake GitHub, so the Version checker reads the real LangGraph releases through the proxy. People sign in with dev sign-in (`X-Dev-User`), because there is no host port for a browser.

`lockdown-run.sh` then does three things, and saves what each printed in `2026-10-31/`:

1. **Probes the way out** from inside the agent runtime and platform-api (`lockdown-probe.py`), and from n8n with Node.
2. **Runs a watchlist check to Done** (`lockdown-check.py`, inside platform-api): Alice adds LangGraph 1.2.14 to the Software watchlist and presses Check now, Bob approves the proposal, and the run writes its ticket to the practice Jira.
3. **Connects the AI model** in Settings, as an Operator would, with a key that is not real.

## What was refused, and where it was logged

The proxy's access log, `2026-10-31/proxy-access.log`, has one line for each request. `addresses.txt` names the container behind each address: `172.25.0.5` is the agent runtime, `172.25.0.6` is n8n and `172.25.0.7` is platform-api. The lines from `127.0.0.1` are the proxy's own health check.

| From | Host | Through the proxy | Logged as |
|---|---|---|---|
| agent runtime, platform-api | `api.github.com` | allowed, HTTP 200 | `TCP_TUNNEL/200` |
| agent runtime, platform-api | `login.microsoftonline.com` | allowed, HTTP 200 for Entra's sign-in settings | `TCP_TUNNEL/200` |
| agent runtime, platform-api | `llm-gateway.aisg.sg` | allowed. The gateway itself answered 502 at `/`, as it does from the open internet | `TCP_TUNNEL/200` |
| agent runtime, platform-api | `api.openai.com`, `pypi.org`, `registry.npmjs.org`, `example.com` | **refused**, 403 | `TCP_DENIED/403 CONNECT` |
| agent runtime, platform-api | `http://example.com/`, plain http | **refused**, 403 and the proxy's refusal page | `TCP_DENIED/403 GET` |
| n8n, on its own | `api.n8n.io` | **refused**, 403 | `TCP_DENIED/403 CONNECT` |
| agent runtime, the watchlist check | `api.github.com` | allowed, 15,597 bytes of releases | `TCP_TUNNEL/200`, written when the agent runtime closed the connection |

Around the proxy, nothing gets out, from any container we tried:

| From | What | Result |
|---|---|---|
| agent runtime, platform-api | HTTPS to `api.github.com` without the proxy | refused at once: "Temporary failure in name resolution" |
| agent runtime, platform-api | look up `api.github.com` | no answer: Docker gives no outside names on this network |
| agent runtime, platform-api | TCP to `1.1.1.1:443` and to GitHub's address `140.82.112.6:443` | refused at once: "Network is unreachable" |
| n8n | HTTPS to `api.github.com` with Node, which ignores the proxy settings | no answer in 5 seconds, then given up |

Docker itself logs nothing for a call around the proxy. Only the caller sees its error. So a call that skips the proxy shows up in the proxy's log only by its absence. Inside DevNet, NCS's firewall would be the place that logs it.

## The watchlist check ran to Done

`2026-10-31/check.txt` has the whole run. Alice added LangGraph 1.2.14 and pressed Check now. One second later the run waited at the approval gate: the Version checker had read 5 newer releases on GitHub, through the proxy, and proposed one ticket, "Upgrade LangGraph from 1.2.14 to 1.2.19". The request was posted to the practice Teams channel. Bob approved it, and the act leg created `MOCK-1` in the practice Jira. The run ended `succeeded` after 2 seconds in all, with 21 activity events, the same kinds in the same order as the recorded run in `contracts/fixtures/runs/success.json`.

So n8n's two legs, the approval gate, the write gateway, the practice Jira and Teams, and PostgreSQL all work with no way out. They only talk to each other.

This run did not check the activity log's copy in the Cosmos DB emulator. The P15 checker's rerun of this test did, on commit `719bc22`. `monitoring.run_events` reached event 21, the copier's mark `run_events_copied` was 21, and the emulator held 21 items in the run's partition, plus the copier's own item (`2026-10-31/cosmos-copy-checker.txt`). So the copy to Cosmos DB works with no way out too.

## What broke

Issue [#86](https://github.com/qj1e7/ai-agent-workflow-builder/issues/86) tracks all three.

1. **Connecting the AI model.** In Settings, Connect for the AI Singapore gateway answered "Nobody answers for llm-gateway.aisg.sg. Check the address.", though the host is on the allow list and the proxy reached it in the probe. The proxy's log has no line for it. The address guard (ADR 0022) looks up the model's name itself and connects straight to the address it checked, so it never uses the proxy, and on the locked network the lookup fails. `docs/design/devnet-move.md` expected this. Without a model, the app falls back where it can: New workflow offers the starter workflows instead of the Planner's reading, summaries use their template, and the AI troubleshooter keeps its rule table. A workflow made of agent cards cannot start a run at all, because no model can be connected and its agents need one. The Software watchlist needs no model, which is why the check above still ran. A fix is needed only if the model DevNet uses is reached through the proxy. If NCS's model is inside DevNet, with a direct route, the guard works as it is (question 2 says which model, question 5 whether there is a proxy). If it is reached through the proxy, the guard must check the address and then connect through the proxy. That changes ADR 0022's guard, so it waits for NCS's answers.
2. **n8n's list of MCP servers.** n8n asks `api.n8n.io` for it on its own, through the proxy. The proxy refuses it, and n8n logs "Error fetching from Strapi API" and "A system task run failed" each time the task runs. Nothing in our runs depends on it. We have not found the n8n setting that turns this task off.
3. **n8n's health check, until the overlay changed it.** n8n's image checks its health with BusyBox `wget`, which ignores `NO_PROXY` and asked the proxy for `localhost`. The proxy refused, n8n was marked unhealthy, and the stack did not start. `deploy/compose.lockdown.yaml` now runs the check with `wget -Y off`. Inside DevNet, the same change is needed wherever n8n is given a proxy.

**Since then, 1 Nov 2026.** Items 2 and 3 are fixed in `deploy/compose.yaml`, so every stack built on it has them, not only this overlay.

- `N8N_DISABLED_MODULES=mcp-registry` turns off the n8n module that fetches the list from `https://api.n8n.io/api/mcp-servers`. In the pinned n8n 2.42.6 image, `@n8n/backend-common` reads the setting (`dist/modules/modules.config.js`, where `mcp-registry` is one of the allowed names), and the call is in n8n's `dist/modules/mcp-registry/`. We use no MCP servers in n8n.
- n8n's health check in `deploy/compose.yaml` now runs `wget -Y off` itself, so the overlay no longer changes it.

`n8n-proxy.test.sh` in this folder checks both without starting the stack. It starts one n8n container from the compose settings, with no network and a proxy that never answers. The whole lock-down test has not been run again since. Item 1 still waits for NCS's answers.

Nothing else broke. The agent runtime's GitHub client and Python's own HTTP library in the health checks honour `NO_PROXY`, so the services still reach each other directly.

## What this test does not show

- **Entra ID sign-in.** The test used dev sign-in. The proxy lets `login.microsoftonline.com` through. Reading the code, platform-api fetches Entra's signing keys with a client that uses the proxy settings, but no token was checked here.
- **The Portal in a browser.** Nothing is published on the host, so no browser loaded the Portal. The Portal serves its own fonts and code (ADR 0014), so it should need no outside host, but this test did not prove it.
- **Building the images.** They were built before the stack was locked. Inside DevNet the builds need NCS's registry and package mirror (question 6).
- **A real Jira, Teams or Cosmos DB account.** The practice copies and the emulator run inside the stack.
- **DevNet itself.** This is a model of the strictest likely DevNet, on a laptop. NCS's real proxy, firewall and name service may behave differently.

## Run it again

```sh
docs/evidence/devnet/lockdown-run.sh
```

It needs Docker, room on the Docker disk for the stack's images, and the internet for the proxy. `LOCKDOWN_PROJECT` names the compose project (default `wab-lockdown`), and `KEEP=1` leaves the stack running. Its output lands in `docs/evidence/devnet/out/`, which git ignores. The proxy writes a tunnel's log line only when the connection closes, so the script stops the callers before it reads the log.

`docs/evidence/devnet/n8n-proxy.test.sh` checks only n8n's two settings. It takes about a minute and needs only the n8n image on the machine.
