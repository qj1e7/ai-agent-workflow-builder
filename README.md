# AI agent workflow builder

NUS-ISS MTech SE final year project, sponsored by CODESparks (NCS).

Support staff describe a repetitive Jira or Confluence task in plain English. A Room lead agent brings in the specialist agents it needs, and the work runs with human approval in Microsoft Teams before any write action.

## Start here

- [CONTRIBUTING.md](CONTRIBUTING.md): set up your machine, and how we work day to day
- [AGENTS.md](AGENTS.md): team rules for humans and AI agents
- [GLOSSARY.md](GLOSSARY.md): the names we use
- [docs/adr/](docs/adr/): decisions we made, and why

## Run it locally

You need Docker Desktop running. Then, from the repository root:

```sh
scripts/up.sh
```

The first run writes `deploy/.env` with random dev secrets and builds the images, so it takes a few minutes. Later runs take under a minute. When it finishes you have:

| What | Where |
|---|---|
| platform-api, with its OpenAPI page | http://localhost:8000/docs |
| n8n editor | http://localhost:5678 (sign in with `N8N_OWNER_EMAIL` and `N8N_OWNER_PASSWORD` from `deploy/.env`) |
| Portal | http://localhost:8080, once it is built |

If port 8000 is already taken on your machine, set `PLATFORM_API_HOST_PORT=18000` in `deploy/.env` and run `scripts/up.sh` again.

There is no sign-in yet. Send the header `X-Dev-User` with one of the dev users: `alice` (Operator and Approver), `bob` (Approver) or `carol` (Operator). An Approver can never approve a run they started, so start runs as `alice` and approve them as `bob`.

The agent runtime reads the real GitHub API. Put a `GITHUB_TOKEN` in `deploy/.env` if you hit GitHub's rate limit.

To stop everything and delete its data:

```sh
scripts/down.sh
```

`scripts/e2e.sh` runs the end to end tests against the whole stack with a fake GitHub, and tears it down afterwards. See [e2e/README.md](e2e/README.md).
