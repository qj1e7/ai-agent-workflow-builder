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

On the team's dev machine port 8000 is taken, so set `PLATFORM_API_HOST_PORT=18000` in `deploy/.env`.

The activity log's readers read a copy in the Cosmos DB emulator, service `cosmos` (ADR 0031). Its image is about 600 MB to download and 1.6 GB on disk. It has no host port. To see one run's events, run:

```sh
docker compose -f deploy/compose.yaml exec cosmos cosmoshell.sh -c \
  "query \"SELECT * FROM c WHERE c.runId = '<run id>' ORDER BY c.seq\" --database=activity --container=run_events"
```

Set `ACTIVITY_READER=postgres` in `deploy/.env` to read from PostgreSQL instead, as a DevNet without Cosmos DB would. The copy goes on either way. `docker compose stop cosmos` and `start` keep its data, and `down` deletes it. PostgreSQL keeps every event, so after a `down` without `-v` the copier fills the new emulator again from the start.

The copier checks the copy every 5 seconds, even when nothing new is logged. If the emulator, its database or its container is made again while platform-api runs, the copier fills it again within seconds. Until it has, readiness says the copy is behind, and the live view and the AI troubleshooter read PostgreSQL.

At each start, the emulator's own start script upgrades its packages from packages.microsoft.com (`tdnf distro-sync`). That needs the internet, which DevNet does not have. It also writes about 585 MB into the container, and it means the image digest no longer pins what runs. So compose points packages.microsoft.com at 127.0.0.1 for the `cosmos` service (`extra_hosts`). The upgrade then finds nothing to do, and the emulator runs exactly the pinned image. CI's emulator gets the same mapping.

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
