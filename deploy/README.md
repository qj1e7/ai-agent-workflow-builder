# Running the stack

Everything runs from this folder with Docker Compose.

```sh
deploy/make-env.sh                       # once: writes deploy/.env with random dev secrets
docker compose -f deploy/compose.yaml up --build --wait
docker compose -f deploy/compose.yaml down -v   # stop and delete the data
```

`make-env.sh` never changes a value in an existing `.env`, because `N8N_ENCRYPTION_KEY` must not change while the volumes exist. When a change adds a new key, run it again and it adds only the missing keys. After `down -v` you may run `make-env.sh --force` to replace the file.

To sign in for real against a mock identity provider instead of the dev user switcher, add `compose.oidc.yaml`. It runs `navikt/mock-oauth2-server` with the users alice, bob and carol, sets `AUTH_MODE=oidc`, and publishes no host ports, because the provider's address only resolves inside the compose network. It removes those ports with the `!reset` tag, so it needs Docker Compose 2.24.0 or later. `E2E_AUTH=oidc scripts/e2e.sh` uses it. [docs/auth/entra-setup.md](../docs/auth/entra-setup.md) covers the real provider in Azure.

| Service | Host port |
|---|---|
| platform-api | `PLATFORM_API_HOST_PORT`, default 8000 |
| n8n | `N8N_HOST_PORT`, default 5678 |
| Langfuse, with the `langfuse` profile | `LANGFUSE_HOST_PORT`, default 3000, on localhost only |

n8n runs our own image, `deploy/n8n/Dockerfile`: the pinned n8n with our node pack, `n8n-node-pack/`, built in. `scripts/pack-smoke.sh` checks that n8n loads it. The n8n editor is at http://localhost:5678. Sign in with `N8N_OWNER_EMAIL` and `N8N_OWNER_PASSWORD` from `deploy/.env`, once `bootstrap` has created the owner.

n8n loads every built-in block but those that reach its own secrets, disk or host, which `NODES_EXCLUDE` leaves out ([ADR 0051](../docs/adr/0051-a-workflow-drafter-may-propose-any-n8n-block-code-explains-every-workflow-and-an-approvers-yes-sets-up-a-flagged-workflow.md)). So its port is published on the laptop only, as anyone who reaches n8n can call a Webhook a member published. Code, AI Transform, the Code Tool, Sort and Item Lists run their code in `n8n-runners`, n8n's external task runner, which holds none of n8n's secrets and shares a network with n8n alone. n8n's broker listens only on its address on that network, so no other service reaches port 5679. Both read `N8N_RUNNERS_AUTH_TOKEN`, which `deploy/make-env.sh` adds to an older `deploy/.env`. To change the token, delete its line from `deploy/.env`, run `deploy/make-env.sh`, and run `docker compose -p <project> -f deploy/compose.yaml up -d n8n n8n-runners`. The block `x-n8n-guards` holds the settings that keep a workflow's code and files away from n8n's secrets. n8n and `bootstrap` both get it, and bootstrap fails the start unless each holds. `scripts/n8n-guards.sh` checks this file.

On the team's dev machine port 8000 is taken, so set `PLATFORM_API_HOST_PORT=18000` in `deploy/.env`.

The activity log's readers read a copy in the Cosmos DB emulator, service `cosmos` (ADR 0031). Its image is about 600 MB to download and 1.6 GB on disk. It has no host port. To see one run's events, run:

```sh
docker compose -f deploy/compose.yaml exec cosmos cosmoshell.sh -c \
  "query \"SELECT * FROM c WHERE c.runId = '<run id>' ORDER BY c.seq\" --database=activity --container=run_events"
```

Set `ACTIVITY_READER=postgres` in `deploy/.env` to read from PostgreSQL instead, as a DevNet without Cosmos DB would. The copy goes on either way. `docker compose stop cosmos` and `start` keep its data, and `down` deletes it. PostgreSQL keeps every event, so after a `down` without `-v` the copier fills the new emulator again from the start.

The copier checks the copy every 5 seconds, even when nothing new is logged. If the emulator, its database or its container is made again while platform-api runs, the copier fills it again within seconds. Until it has, readiness says the copy is behind, and the live view and the AI troubleshooter read PostgreSQL.

At each start, the emulator's own start script upgrades its packages from packages.microsoft.com (`tdnf distro-sync`). That needs the internet, which DevNet does not have. It also writes about 585 MB into the container, and it means the image digest no longer pins what runs. So compose points packages.microsoft.com at 127.0.0.1 for the `cosmos` service (`extra_hosts`). The upgrade then finds nothing to do, and the emulator runs exactly the pinned image. CI's emulator gets the same mapping.

## The simulation n8n

The simulation n8n (ADR 0054) is a second n8n where a workflow version will be tried against mock systems before its test run. `compose.simulation.yaml` runs it as a stack of its own, never as part of the platform's:

- its own PostgreSQL, in memory, so it keeps nothing after it stops;
- our n8n image and its task runner, with the platform n8n's guards and bootstrap, its own encryption key, node key and start secret, and only mock keys;
- the simulation gateway, which our blocks there call in place of platform-api;
- mock GitHub, and mock Slack under the name `slack.com`, as in `compose.e2e.yaml`.

Every network in it is internal and nothing publishes a port, so nothing in it reaches the internet, the host or the platform's stack. The gateway also sits on `link`, a network that only platform-api joins, and only when you link the two stacks (below). The platform's n8n can never reach the gateway.

```sh
scripts/simulation.sh up      # makes up every key, starts it and waits for bootstrap
scripts/simulation.sh check   # checks it holds no real key and reaches only the mocks
scripts/simulation.sh drive   # runs our blocks through the gateway, one scenario at a time
scripts/simulation.sh logs    # prints its logs
scripts/simulation.sh down    # removes its containers, networks and volumes
```

### The simulation gateway

Our blocks in the simulation n8n call `http://gateway:8600` (ADR 0054, section 3). The gateway is its own service. It runs platform-api's image, but only its own app (`platform_api.orchestration.simulation_gateway`), and mounts platform-api's own router for our blocks, so each block gets the same answers, refusals and checks as from platform-api. It answers them from the simulated run's scenario:

- Read gets recorded items, mock GitHub's releases, or a source that is not found or does not answer in time.
- Agent gets a recorded reply. The gateway calls no model.
- Ask for a yes gets the scenario's yes, no or no answer, and asks nobody. Only the simulation n8n is woken.
- Every write is refused with 403 "A simulation never writes.", as the write gateway refuses a test run's write. The gateway keeps how many of the changes proposed it would have made.
- Tell answers `would_have_sent` and sends nothing.

It holds only the simulation's node key and start secret, the simulation n8n's owner, and mock GitHub's address and mock Slack's made-up key. It has no database and no real Jira, Teams, Slack or model key. It keeps its simulated runs in memory, at most 200 and at most 256 KB of record each, so a restart forgets them, as the simulation's in-memory PostgreSQL forgets its n8n.

The simulation's driver uses four more routes, each signed with the simulation's start secret. `POST /simulation/v1/simulations` runs a whole simulation (ADR 0054, section 5): it takes a workflow version, and scenarios or none, which runs code's six templates, and recorded samples, which it scrubs first. It runs each scenario on a copy of its own, steers mock GitHub for it, grades it from the gateway's record and n8n's, then deletes the copy and sets mock GitHub back. It answers each verdict in plain words, what no scenario reached and what was not tried. `POST /simulation/v1/copies` takes a workflow version and makes its copy in the simulation n8n (ADR 0054, section 4): n8n's own GitHub and Slack blocks get mock keys that point at the mocks, Teams, Outlook, Gmail and (until a mock Jira runs here) Jira get pinned output, and a block the class file doesn't turn on is refused, with nothing made. It answers how each block runs, and lists the pinned ones as not tried. `POST /simulation/v1/starts` takes a workflow id and a scenario and answers the start item for n8n's run by hand. `GET /simulation/v1/runs/{nonce}` answers that run's record for the grader: each call in order, what was proposed, what Ask for a yes got, and how much the write would have made. The signature is in the module's docstring. `scripts/simulation_drive.py` uses all four, from inside the gateway's container. Its caller deletes a copy `/copies` made, as the drive does.

The simulation n8n's own environment holds the start secret too, because Start from the Portal checks a start with it. A workflow there can't read it: n8n keeps expressions from reading its environment, Code runs in the task runner, which holds none of n8n's settings, and the copies route refuses HTTP Request and Code.

platform-api drives the gateway only when `SIMULATION_URL` and `SIMULATION_START_SECRET` are set (ADR 0054, PR 7). Then it tries each drafted revision with nothing still needed, and the drafted card shows the result. `SIMULATION_MODEL=on` lets the model write the cases and explain each failure, which are paid calls, so it stays off until the team lead sets a budget. Only a stack linked to the simulation sets the first two (below). Anywhere else the card says simulation isn't available here.

`scripts/simulation.sh` makes up each key with `openssl` at every start and never writes one to a file. It reads `deploy/.env` only for the start secret of a linked simulation. The compose project is `wab-sim` unless `SIM_PROJECT` names another, and `SIM_BUILD=0` starts from the images an earlier start built. It builds the platform's images from the same sources under their own tag, `sim`, so starting it never replaces an image the platform's stack runs. Docker shares the layers that match, so the extra disk is mostly what differs between the two builds.

`scripts/simulation_isolation.py` is the check. It reads this file and `compose.simulation-link.yaml` as compose renders them, and, with `--project`, the running stack: each service's settings against an allow list, the keys n8n holds, the routes out of n8n and the gateway, and who sits on its networks. It compares every value with the platform's keys in `deploy/.env`. With `--platform` too, it probes the linked platform from inside both stacks' containers (below). CI runs it in the `checks` job, starts the stack, runs it and drives the gateway in the `simulation` job, and runs it on both linked stacks in the `simulation-link` job.

### Linking platform-api to the gateway

On a laptop and in CI, platform-api can drive the gateway, so the Check card shows a real result, such as "Tried 6 cases on practice systems: 6 passed." (ADR 0054, "What the link chose"). Azure stays unlinked.

- The simulation makes `link`, its network for the gateway alone. `compose.simulation-link.yaml` joins platform-api to it, gives platform-api `SIMULATION_URL=http://simulation-gateway:8600`, and changes nothing else. The platform's n8n, PostgreSQL and agent runtime never join it, and the simulation n8n never leaves its own networks.
- The start secret is the one value both stacks hold. `deploy/make-env.sh` adds `SIMULATION_START_SECRET` to `deploy/.env`, 64 characters long. The link file gives it to platform-api, and `SIM_LINK=<platform's project> scripts/simulation.sh up` gives the same value to the simulation n8n and the gateway. Nothing prints it. platform-api and the gateway refuse to start with a start secret shorter than 32 characters.
- `SIMULATION_MODEL` stays off, so code's six templates run and no model is asked.

To link the team lead's `wab` stack, run these from the checkout it runs from, once this change is in that checkout:

```sh
deploy/make-env.sh                         # adds SIMULATION_START_SECRET to deploy/.env, once
SIM_LINK=wab scripts/simulation.sh up      # starts wab-sim, with the link wab-sim_link
docker compose -p wab -f deploy/compose.yaml -f deploy/compose.simulation-link.yaml \
  up --detach --no-deps --build platform-api
SIM_LINK=wab scripts/simulation.sh check   # proves the link from inside both stacks
```

The third command builds platform-api from the checkout and starts it again on the link. The rest of `wab` keeps running. To unlink, start platform-api again without the link file first, because the simulation can't remove its link while platform-api sits on it. `scripts/simulation.sh down` stops and names this command when it finds platform-api still on the link:

```sh
docker compose -p wab -f deploy/compose.yaml up --detach --no-deps platform-api
scripts/simulation.sh down
```

`scripts/up.sh` also starts platform-api without the link, so run the third command again after it. To start the simulation again, unlink, then run the link commands again from the second. A simulation project other than `wab-sim` has the link `<project>_link`, which the link file reads from `SIMULATION_LINK_NETWORK`.

With `SIM_LINK` set, `check` adds `--platform`. From inside the simulation n8n it tries every address of the platform's platform-api, PostgreSQL, n8n and agent runtime, and from inside the gateway every address but platform-api's. Each must fail. platform-api must reach the gateway by its name on the link, and the platform's n8n and agent runtime must reach none of the gateway's addresses. Each container that probes must reach a service of its own stack, so a blind probe can't pass. It allows the start secret only as the start secret of the simulation n8n and the gateway, and only the named platform's platform-api on the link. Linked or not, `check` also tries the host from inside the simulation n8n and the gateway, at the address each simulation network gives it, on ports 8000, 5678 and 5432 and each port a linked platform publishes. Each must fail. The name `host.docker.internal` never resolves on an internal network, so that name alone proves nothing.

`E2E_SIMULATION=on scripts/e2e.sh` does all of this on stacks of its own, as the `simulation-link` CI job runs it: it starts the simulation, then the platform with the link file, drafts the release check with the mock model, waits for the card's result, runs the check on both stacks, and removes both, the platform first.

## Langfuse

The agent runtime traces each Planner turn and agent task in Langfuse, which we host ourselves (ADR 0050). Langfuse is off by default, behind the `langfuse` profile. Its images are about 2.6 GB on disk, and the profile peaked at 3.3 GiB of memory beside the stack's 1.3 GiB, so check `docker system df` first.

```sh
deploy/make-env.sh                       # adds the Langfuse passwords and keys to an old .env
# In deploy/.env, set LANGFUSE_BASE_URL=http://langfuse-web:3000
docker compose -f deploy/compose.yaml --profile langfuse up --build --wait
```

- Tracing stays off until `LANGFUSE_BASE_URL` is set. The project keys follow it, so the agent runtime and platform-api get all three Langfuse settings or none.
- Open http://localhost:3000 and sign in with `LANGFUSE_INIT_USER_EMAIL` and `LANGFUSE_INIT_USER_PASSWORD` from `deploy/.env`. On Azure only the team's Entra group can sign in.
- `langfuse-db` makes Langfuse's role and database in our PostgreSQL, on a new volume or an old one. It runs once per start and stops.
- Azurite stands in for Azure blob storage, as in Langfuse's own Azure setup. `langfuse/blob-container.js` makes the blob container, which Langfuse does not make itself.
- ClickHouse is capped at 1.5 GiB and uses `langfuse/clickhouse.xml`. The Azure VM uses the same cap and file, and `infra/scripts/check-langfuse-images.sh` fails when the VM's images or this file differ from here.
- Telemetry to Langfuse is off. Langfuse's update check, a GitHub badge and onboarding videos still reach the internet.
- `docker compose -f deploy/compose.yaml --profile langfuse down -v` deletes the traces with the rest.
