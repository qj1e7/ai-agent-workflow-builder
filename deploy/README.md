# Running the stack

Everything runs from this folder with Docker Compose.

```sh
deploy/make-env.sh                       # once: writes deploy/.env with random dev secrets
docker compose -f deploy/compose.yaml up --build --wait
docker compose -f deploy/compose.yaml down -v   # stop and delete the data
```

`make-env.sh` refuses to overwrite an existing `.env`. Keep it while the volumes exist, because `N8N_ENCRYPTION_KEY` must not change. After `down -v` you may run `make-env.sh --force`.

To sign in for real against a mock identity provider instead of the dev user switcher, add `compose.oidc.yaml`. It runs `navikt/mock-oauth2-server` with the users alice, bob and carol, sets `AUTH_MODE=oidc`, and publishes no host ports, because the provider's address only resolves inside the compose network. It removes those ports with the `!reset` tag, so it needs Docker Compose 2.24.0 or later. `E2E_AUTH=oidc scripts/e2e.sh` uses it. [docs/auth/entra-setup.md](../docs/auth/entra-setup.md) covers the real provider in Azure.

| Service | Host port |
|---|---|
| platform-api | `PLATFORM_API_HOST_PORT`, default 8000 |
| n8n | `N8N_HOST_PORT`, default 5678 |

The n8n editor is at http://localhost:5678. Sign in with `N8N_OWNER_EMAIL` and `N8N_OWNER_PASSWORD` from `deploy/.env`, once `bootstrap` has created the owner.

On the team's dev machine port 8000 is taken, so set `PLATFORM_API_HOST_PORT=18000` in `deploy/.env`.

The activity log's readers read a copy in the Cosmos DB emulator, service `cosmos` (ADR 0031). Its image is about 600 MB to download and 1.6 GB on disk. It has no host port. To see one run's events, run:

```sh
docker compose -f deploy/compose.yaml exec cosmos cosmoshell.sh -c \
  "query \"SELECT * FROM c WHERE c.runId = '<run id>' ORDER BY c.seq\" --database=activity --container=run_events"
```

Set `ACTIVITY_READER=postgres` in `deploy/.env` to read from PostgreSQL instead, as a DevNet without Cosmos DB would. The copy goes on either way. `docker compose stop cosmos` and `start` keep its data, and `down` deletes it. PostgreSQL keeps every event, so after a `down` without `-v` the copier fills the new emulator again from the start.

The copier checks the copy every 5 seconds, even when nothing new is logged. If the emulator, its database or its container is made again while platform-api runs, the copier fills it again within seconds. Until it has, readiness says the copy is behind, and the live view and the AI troubleshooter read PostgreSQL.

At each start, the emulator's own start script upgrades its packages from packages.microsoft.com (`tdnf distro-sync`). That needs the internet, which DevNet does not have. It also writes about 585 MB into the container, and it means the image digest no longer pins what runs. So compose points packages.microsoft.com at 127.0.0.1 for the `cosmos` service (`extra_hosts`). The upgrade then finds nothing to do, and the emulator runs exactly the pinned image. CI's emulator gets the same mapping.
