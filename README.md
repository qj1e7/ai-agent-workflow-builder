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
| Portal, the page a person opens | http://localhost:8080 |
| platform-api, with its OpenAPI page | http://localhost:8000/docs |
| n8n editor | http://localhost:5678 (sign in with `N8N_OWNER_EMAIL` and `N8N_OWNER_PASSWORD` from `deploy/.env`) |

`scripts/up.sh` prints these addresses when it is done, Portal first.

If a port is already taken on your machine, change it in `deploy/.env` and run `scripts/up.sh` again. The settings are `PORTAL_HOST_PORT`, `PLATFORM_API_HOST_PORT` (try `18000` when 8000 is taken) and `N8N_HOST_PORT`.

New to the Portal? Press the flag at the top right. A guided tour walks you through every part of the app, one step at a time, and each step ticks itself off when you really do it.

There is no sign-in yet. In the Portal, pick the user from the menu at the top right. For plain API calls, send the header `X-Dev-User` with one of the dev users: `alice` (Operator and Approver), `bob` (Approver) or `carol` (Operator). An Approver can never approve a run they started, so start runs as `alice` and approve them as `bob`.

The agent runtime reads the real GitHub API. Put a `GITHUB_TOKEN` in `deploy/.env` if you hit GitHub's rate limit.

To stop everything and delete its data:

```sh
scripts/down.sh
```

`scripts/e2e.sh` runs the end to end tests against the whole stack with a fake GitHub, first the API tests and then the same product in a real browser through the Portal. It tears everything down afterwards. See [e2e/README.md](e2e/README.md).

`scripts/dast.sh` scans the running stack with OWASP ZAP, and `scripts/load.sh` load tests it with k6. Each starts its own stack with no host ports, prints PASS or FAIL, and tears the stack down. The ZAP rules and their reasons are in `dast/`. The k6 script is `load/team.js`. The latest results are in `docs/evidence/dast/` and `docs/evidence/load-test/`.
