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
- mock GitHub, and mock Slack under the name `slack.com`, as in `compose.e2e.yaml`.

Both of its networks are internal and nothing publishes a port, so nothing in it reaches the internet, the host or the platform's stack. Our blocks in it call `http://gateway:8600`, where the simulation gateway goes in ADR 0054's PR 3. Until then nothing answers there.

```sh
scripts/simulation.sh up      # makes up every key, starts it and waits for bootstrap
scripts/simulation.sh check   # checks it holds no real key and reaches only the mocks
scripts/simulation.sh down    # removes its containers, networks and volumes
```

`scripts/simulation.sh` makes up each key with `openssl` at every start and never writes one to a file. It never reads `deploy/.env`. The compose project is `wab-sim` unless `SIM_PROJECT` names another, and `SIM_BUILD=0` starts from the images an earlier start built. It builds the platform's images from the same sources under their own tag, `sim`, so starting it never replaces an image the platform's stack runs. Docker shares the layers that match, so the extra disk is mostly what differs between the two builds.

`scripts/simulation_isolation.py` is the check. It reads this file as compose renders it, and, with `--project`, the running stack: each service's settings against an allow list, the keys n8n holds, n8n's routes out, and who sits on its networks. It compares every value with the platform's keys in `deploy/.env`. CI runs it in the `checks` job, and starts the stack and runs it there in the `simulation` job.

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
