# Moving the app into DevNet

CODESparks works inside DevNet, NCS's private network, where the company's GitLab, Jira, Confluence and Azure live. We build and prove the app on the open internet first (ADR 0005), so the move into DevNet comes later. This note lists what each part of the app needs in DevNet, the questions only NCS can answer, the choices we hold to now so the move stays small, and how we test the move before we have DevNet access.

It was written on 29 Oct 2026 from a check of the repo at commit `9ab68f5`.

## What each part needs in DevNet

| Part | In DevNet | What it needs |
|---|---|---|
| Portal, platform-api, agent runtime, n8n, PostgreSQL | Moves as is | Each is a container pinned by digest (ADR 0006). The Portal serves its own fonts and code (ADR 0014). NCS needs an internal registry for our images, and https certificates, because sign-in needs https (ADR 0018). |
| Sign-in | Moves with settings | NCS IT registers our app in NCS's Entra tenant (ADR 0018). The rest is settings. |
| Jira and Confluence | Needs real adapters | The adapter slots exist (ADR 0005). If NCS runs the self-hosted editions, their API and keys differ from the cloud editions. |
| Azure | Needs Terraform work | Our Terraform opens PostgreSQL to the internet (`infra/modules/postgres/main.tf:15`) and gives Key Vault no firewall (`infra/modules/key_vault/main.tf:5`). NCS will very likely require a private network, with private endpoints for each service. |
| Cosmos DB | Likely fine, with a fallback | NCS's Azure must allow it on a private endpoint. If it does not, the app reads its activity log from PostgreSQL, which keeps every event (ADR 0031). |
| GitLab | New work | We have tools for GitHub only. The sponsor's real use cases need GitLab tools, and each new system needs its own ADR (ADR 0023). |
| AI model | Must change | The AI Singapore gateway is on the public internet (ADR 0021). Azure OpenAI in NCS's own Azure is the likely choice, and ADR 0032 already names it for handover. |
| Teams approvals | Half works | A Teams message that links to the run page needs only calls out from DevNet (ADR 0009). Approve buttons inside Teams need Microsoft's Bot Service to call into our app, which a private network may refuse. |
| Software watchlist sources | Needs a route out | GitHub, Maven Central, NVD, OSV, endoflife.date and CISA's list are public sites (ADR 0025). DevNet needs a proxy or an allow list. Our address guard ignores proxies today (ADR 0022). |
| LangSmith | Needs a decision | It is a hosted service, so traces would leave DevNet (ADR 0003). It is not wired up yet. |
| Code and CI | Moves at handover | The code is on GitHub with GitHub Actions. NCS uses GitLab, so the pipeline becomes GitLab CI. Every scan already runs in a container, so the jobs carry over. |

## What NCS needs to answer

Each answer settles one or more rows above. The sponsor can forward the questions to NCS IT.

1. Can we run containers in NCS's Azure inside DevNet? Does it allow PostgreSQL and Cosmos DB on private endpoints? This settles Azure and Cosmos DB.
2. Which AI model service may DevNet call, and with which data? This settles the AI model.
3. Are Jira and Confluence the self-hosted editions, and can a service account get a token for each? This settles Jira and Confluence.
4. Can an app in DevNet post messages to Teams? Can Microsoft's Bot Service reach an address inside DevNet? This settles Teams approvals.
5. Is there a proxy out to the internet, and could it allow the watchlist's sources? Does the proxy keep its own allow list? This settles the watchlist sources and the address guard.
6. Is there an internal container registry and a package mirror for Python and npm? This settles how images get into DevNet.
7. Who registers an Entra app for us, and can we have one group for the people who may sign in (ADR 0029)? This settles sign-in.
8. May traces go to a hosted service such as LangSmith? This settles LangSmith.
9. Where does the code live after handover, and who owns it? This is already open with the sponsor, and it settles code and CI.

## Choices we hold to now

These keep the move small, whatever NCS answers. [The rebuild plan](rebuild-plan.md) carries each one.

1. **A Teams message with a link is the baseline.** Every approval request in Teams links to the run page, where the Approver decides under their own sign-in (ADR 0009). Approve buttons inside Teams are an extra that can wait for NCS's answer to question 4.
2. **Every outside address is a setting.** New code reads each host from a setting and never writes one into the code. Today the agent runtime reads `GITHUB_API_BASE`, `AGENT_MODEL_BASE_URL` and `PRACTICE_JIRA_URL`, and sign-in reads the `OIDC_*` settings. Two places name a host on purpose. The known AI providers are a list in git that a PR reviews (ADR 0022). The watchlist links each row to its public GitHub releases page (`platform-api/src/platform_api/builder/watchlist.py:94`). Teaching the address guard to use a proxy waits for the answer to question 5, because a proxy with its own allow list needs a different guard from one without.
3. **The PostgreSQL reader keeps working.** A setting picks whether the activity log's readers use Cosmos DB or PostgreSQL. CI tests both.
4. **Every CI step runs in a pinned container.** Then each job carries over to GitLab CI unchanged.

## Test the move before we have DevNet access

The lock-down test runs the stack with no route to the internet except a proxy that allows only the listed hosts. Then it records what still works and what breaks. It needs no DevNet access, only room on the Docker disk. The rebuild plan's P15 runs it and saves the result in `docs/evidence/devnet/`.

The allow list starts with the hosts the app calls today:
- Entra ID sign-in;
- GitHub's API;
- the AI model's address.

The watchlist's other sources join when they are built.

## The move itself

Each step starts once NCS answers the question it depends on.

- Copy our images and n8n's into NCS's registry, and build from NCS's package mirror (question 6).
- Change the Terraform to a private network with private endpoints (question 1).
- Register the Entra app in NCS's tenant and get https certificates (question 7).
- Point the AI model at the service NCS allows (question 2).
- Build the real Jira and Confluence adapters, and the GitLab tools with their ADR (question 3).
- Set the proxy and the address guard for the watchlist's sources (question 5).
- Move the code to GitLab and the pipeline to GitLab CI (question 9).
