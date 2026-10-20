# Running the stack

Everything runs from this folder with Docker Compose.

```sh
deploy/make-env.sh                       # once: writes deploy/.env with random dev secrets
docker compose -f deploy/compose.yaml up --build --wait
docker compose -f deploy/compose.yaml down -v   # stop and delete the data
```

`make-env.sh` refuses to overwrite an existing `.env`. Keep it while the volumes exist, because `N8N_ENCRYPTION_KEY` must not change. After `down -v` you may run `make-env.sh --force`.

To run without the real agent, add the fake agent. It replays the contract fixtures, and `POST /_admin/mode` with `{"mode": "failed"}` switches it to the failure case.

```sh
docker compose -f deploy/compose.yaml -f deploy/compose.fake-agent.yaml up --build --wait
```

| Service | Host port |
|---|---|
| platform-api | `PLATFORM_API_HOST_PORT`, default 8000 |
| n8n | `N8N_HOST_PORT`, default 5678 |

The n8n editor is at http://localhost:5678. Sign in with `N8N_OWNER_EMAIL` and `N8N_OWNER_PASSWORD` from `deploy/.env`, once `bootstrap` has created the owner.

On the team's dev machine port 8000 is taken, so set `PLATFORM_API_HOST_PORT=18000` in `deploy/.env`.
