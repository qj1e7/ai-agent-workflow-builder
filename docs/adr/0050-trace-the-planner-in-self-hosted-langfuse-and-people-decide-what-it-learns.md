---
status: accepted
---

# Trace the Planner in self-hosted Langfuse, and people decide what it learns

On 16 Nov 2026 the team lead asked whether the Planner can learn from every message and notice when an answer is poor. A real example was "help me remove node js from watchlist". It got "From the chat I can only change when Software watchlist runs", because the Planner had no way to remove software from the watchlist.

The answer is yes, through a loop with a person as the gate. The AI never changes itself while it runs, for three reasons:

- People's messages could teach it bad habits, and the approval and safety rules must never drift.
- Small prompt changes have large effects. In the [16 Nov spike](../evidence/evals/2026-11-16-spike-ai-led-planner.md), one example sentence in the briefing cut useful answers to off-topic messages from 8 of 8 to 3 of 8.
- The sponsor needs a Planner they can trust and audit.

Nothing traces the Planner today. ADR 0003 and `AGENTS.md` name LangSmith, but `agent-runtime/tests/test_api.py` only checks that LangSmith tracing is off, and `CHECKPOINTS.html` lists "Agent tracing and monitoring" as a Must item with "Neither is wired up yet" (line 807). The project proposal, `docs/proposal/MTech_SE_Project_Proposal_v0.2_reviewed (1).docx`, named self-hosted Langfuse on Container Apps, set up with Terraform.

This amends ADR 0003. It changes no write, no approval gate and no safety checker.

## Decision

### Langfuse, self-hosted from day one

We run the free, MIT-licensed edition of [Langfuse][pricing] ourselves, so traces stay on our servers and can move into DevNet with the rest of the platform. Langfuse Cloud is never used. Fresh installs start on [Langfuse v4][v3-v4], because v3 gets only security patches, until the end of January 2027. Python SDK v5 needs server 4.59.0 or later ([compatibility][compat]).

Langfuse v4 is made of a web app, a worker, ClickHouse, a cache, blob storage and PostgreSQL ([overview][overview]). PR A pins each image by digest (ADR 0006), from Docker Hub rather than `docker.langfuse.com`, which only counts downloads ([telemetry][telemetry]).

| Part | Local | Azure | Version |
|---|---|---|---|
| Web and worker | `deploy/compose.yaml`, profile `langfuse` | The Langfuse VM | `langfuse/langfuse` and `langfuse/langfuse-worker` 4.80.0 |
| ClickHouse | Same profile | The Langfuse VM, on its managed disk | `clickhouse/clickhouse-server` 26.3.62.3, the version Langfuse's own compose file pins. v4 needs 25.12 or later ([ClickHouse][clickhouse]) |
| Valkey (the cache) | Same profile | The Langfuse VM | `valkey/valkey` 8.1.11, with `maxmemory-policy noeviction`. Langfuse supports Valkey 8 and later ([cache][cache]) |
| Blob storage | Azurite 3.37.0 | A storage account, with `LANGFUSE_USE_AZURE_BLOB=true` ([blob storage][blob]) | Langfuse's own [Azure development setup][azure-dev] uses Azurite the same way |
| PostgreSQL | Our `postgres` service, in a new `langfuse` database | Our flexible server, in a new `langfuse` database | Ours is 17. v4 needs 15 or later, in UTC ([PostgreSQL][postgres]) |
| HTTPS | None, it stays on localhost | Caddy 2.11.9 in front of web | |

**On Azure, Langfuse runs on one small Linux VM, not on Container Apps.** The VM runs the same compose profile as a laptop, with PostgreSQL and blob storage moved to Azure services. Terraform creates a `Standard_B2as_v2` VM with 2 vCPUs and 8 GiB of memory, a 32 GiB Standard SSD, a network security group and a managed identity that reads Langfuse's secrets from our Key Vault. Only Langfuse's web app is reachable from outside. Every other part listens on localhost, as in [Langfuse's compose file][compose-file].

The security group allows port 443 only from the Container Apps environment's outbound addresses and the team's own addresses. `infra/README.md` finds those outbound addresses the same way for n8n. They can be shared with other Azure customers, so Langfuse's keys and sign-in still guard the app. Port 80 stays open to everyone, because Let's Encrypt checks the certificate request there, and Caddy redirects everything else to 443 ([Caddy][caddy]).

There are three reasons for the VM:

- ClickHouse needs a real disk. Container Apps keeps files across restarts only on Azure Files, and NFS shares need a custom VNet, which our environment does not have ([storage mounts][aca-storage]). That leaves SMB, which [ClickHouse's tips page][ch-tips] does not mention. The page says NFS "is not the best idea".
- Container Apps bills the memory of every running replica, and ClickHouse must run all the time. Web, worker, ClickHouse and Valkey at 4.5 vCPUs and 9 GiB would cost about USD 140 a month at the idle rate and about USD 490 at the active rate in Southeast Asia, an estimate from the same price list as below.
- The VM costs about USD 75 a month while it runs (about USD 69 for the VM, USD 2.40 for the disk and USD 3.65 for the address), and about USD 6 a month while it is stopped. These are pay-as-you-go list prices for Southeast Asia from the [Azure Retail Prices API][prices], fetched on 16 Nov 2026. Against Azure for Students' USD 100 a year, the VM runs only in test weeks and demos, like the rest of the environment (`infra/README.md`). So day-to-day traces come from the team lead's laptop with the `langfuse` profile on, and Azure has traces only in test weeks and demos.

**The VM starts below Langfuse's size, on purpose.** Langfuse recommends at least 4 cores and 16 GiB for compose ([Docker Compose][compose]), and its [minimum table][scaling] adds up to 17.5 GiB without PostgreSQL. ClickHouse can run in 2 GB with tuning at a low ingest rate ([tips][ch-tips]), and we expect a few hundred turns a day at most (a guess). PR A caps ClickHouse's memory and measures the peak with `docker stats`. If the peak passes 6 GiB, the VM moves to `Standard_B4as_v2`, with 16 GiB, at about USD 138 a month for the VM alone. The B-series is burstable, and ClickHouse's background work can use up the VM's CPU credits. `docker stats` cannot see credits, so the `infra` pull request adds an alert on the VM's remaining CPU credits.

**ClickHouse in one container is what Langfuse calls fit for development only** ([ClickHouse][clickhouse]), and its compose setup has no high availability or backups ([Docker Compose][compose]). We accept that. Traces are a 60-day working record. What must last, the regression cases, lives in git.

**Locally, the `langfuse` profile is off by default.** The Docker VM has 8 GiB of memory, and its disk is 89% full with 6 GB free. The Langfuse, ClickHouse and Valkey images download as about 0.7 GB, without Azurite. PR A ships the profile only if the whole stack plus Langfuse runs inside that 8 GiB.

### Data stays inside

- **Telemetry is off.** `TELEMETRY_ENABLED=false` on web and worker. Otherwise Langfuse sends counts, never trace content, to `eu.posthog.com` every 12 hours ([telemetry][telemetry]). `LANGFUSE_DISABLE_SIGNUP_ONBOARDING=true` stops the newsletter step. Halo stays off, as it is by default, and Langfuse's AI gateway is not deployed.
- **What still leaves:**
  - the Planner's own model call, as today;
  - the judge's model call, which Langfuse's worker makes to Anthropic;
  - Langfuse's update check to `langfuse.com`, which carries no data and cannot be turned off;
  - a GitHub badge and onboarding videos that the browser loads.

  Langfuse keeps working when a proxy blocks the last two ([telemetry][telemetry]).
- **Secrets are masked before a trace leaves the process.** The Langfuse client gets a [`mask_otel_spans`][masking] hook. It replaces the exact value of every secret in the process's settings, and known key shapes such as `sk-ant-`, `ghp_` and `Bearer` tokens. A secret handed to a tool when it is called, such as a connection token from platform-api, is registered with the masker before the call. The docs do not say whether spans from the Python LangChain handler pass through this hook. So PR A's test plants a fake key in a message, in a trace's metadata, in a header in a tool call's input and in a tool result, and checks that the exported spans contain none of them. Tracing stays off in every environment until this test passes in CI. The test runs in CI on every change. The Langfuse adapter is not wired into the port until it passes, and a later failure blocks the merge.
- **The person is named by a pseudonymous id.** A trace names the person by an HMAC-SHA256 of their platform person id, keyed with a secret in Key Vault, never by their email or name. Langfuse's [user id][users] accepts any string. Message and reply text stay as typed. No NCS data enters traces before the DevNet move (ADR 0005). When Phase 2 data arrives, the sponsor decides how long traces are kept and who may sign in.
- **Traces are kept 60 days.** Retention policies need Langfuse's Enterprise edition when self-hosted ([data retention][retention]). So a nightly housekeeping job finds older traces through `GET /api/public/v2/observations` with `toStartTime`, and deletes them with `DELETE /api/public/traces` in batches. That also deletes their scores and observations. Deletion takes about 15 minutes and sends no confirmation, so the next night's run checks ([data deletion][deletion]). Langfuse keeps dataset items when their traces expire ([data retention][retention]), and PR B checks that deletion through the API does the same. Accepting this ADR is the team lead's yes to this standing deletion. Any other deletion still needs a person, as `AGENTS.md` says.
- **A stopped deletion job is noticed.** The job runs as a scheduled GitHub Actions workflow, so a failed run sends GitHub's failure email, which goes to whoever created the workflow or last changed its schedule ([GitHub notifications][gh-notify]). The team lead makes that change. The workflow reaches the VM through `az vm run-command`, so it needs no way in through the security group, and it skips with a note while the VM is stopped. Run-command runs as root. Today `id-wab-deploy` already has it on every VM in `rg-wab-dev`, because it is Contributor there (`infra/bootstrap/setup-azure.sh`). The `infra` PR adds a custom role with only run-command, assigned on the Langfuse VM. It limits the deploy identity to that VM once the team lead narrows its Contributor role. The job fails when the oldest trace is older than 62 days, and the VM has a disk alert at 80%. On a laptop, the profile runs the same script each time it starts.
- **Only the team signs in.** Langfuse signs people in with Entra ID through `AUTH_AZURE_AD_CLIENT_ID`, `AUTH_AZURE_AD_CLIENT_SECRET` and `AUTH_AZURE_AD_TENANT_ID`, with `AUTH_DISABLE_USERNAME_PASSWORD=true` ([authentication][auth]). The free edition includes Entra ID sign-in ([pricing][pricing]). Langfuse gets its own Entra app, with assignment required and only the team's group assigned, so nobody else can sign in at all. A person who signs in with SSO joins no organization by themselves. So `LANGFUSE_INIT_USER_EMAIL` creates the team lead's account as the organization's Owner at first start ([headless initialization][headless]). `AUTH_AZURE_AD_ALLOW_ACCOUNT_LINKING=true` links their Entra sign-in to that account while password sign-in is off. Langfuse warns that linking is safe only when emails are verified. Here only the team's group, whose emails our tenant sets, can sign in. The Owner then invites each teammate by email as a Member. `AUTH_DISABLE_SIGNUP` stays unset, because it also blocks invited people who have no account yet. Organization roles are free, and project roles need Enterprise ([RBAC][rbac], [pricing][pricing]). We have one project, so organization roles are enough.
- **The Portal never embeds Langfuse and never calls it.** Ratings and the typed-again flag go through platform-api, which holds the same project keys as the agent runtime.

### What the free edition covers

Every feature we need is in the free self-hosted edition, except the four marked below ([pricing][pricing], [license key][license]).

| Feature | Free self-hosted | How we use it |
|---|---|---|
| Tracing, sessions, users | Yes | Every Planner turn |
| Scores and user feedback | Yes | Code flags, judge scores, ratings |
| LLM-as-a-judge evaluators | Yes | The judge |
| Annotation queues | Yes | The review queue |
| Datasets | Yes | `planner-regressions` |
| Custom dashboards | Yes | % useful |
| Entra ID sign-in and SSO enforcement | Yes | Team-only sign-in |
| Organization roles | Yes | Owner and Members |
| Data retention | No | Our nightly deletion |
| Project roles | No | Not needed with one project |
| Audit logs | No | Dropped. The platform's own activity log keeps who approved what |
| Server-side masking | No | The client-side hook, which is free |

### What each trace carries

The agent runtime calls models through LangChain and LangGraph. Langfuse's [`CallbackHandler`][langchain] (`from langfuse.langchain import CallbackHandler`), passed in the graph's `config={"callbacks": [...]}`, records each model call. The SDK is [built on OpenTelemetry][sdk].

Each Planner turn is one trace, in a session that is the Portal's chat. It carries:

- the person's message and the reply they saw;
- the Planner's reading (`TaskRead`) and the answer kind (`PlannerAnswer`);
- the free reply, and whether the guard or the verifier rejected it;
- the parts crossed and each step's time;
- the model, the environment and the commit;
- the person's pseudonymous id.

Agent runs are traced too, with the run's id as the session. The learning loop covers the Planner only for now.

Run monitoring owns the trace shape, the score names and configs, the review queue and the housekeeping job. The agent runtime records a turn through a port with two adapters, Langfuse and off. Agent code never imports Langfuse. Only the API's start-up code adds the callback, so the agents stay reusable for NCS's agent hub (ADR 0003). Tracing is off unless `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` are set. The test that keeps LangSmith off stays, because `langsmith` comes with `langchain-core`.

### How good or bad is decided

Every signal is a Langfuse [score][scores], checked against a score config. The setup script creates each config.

| Score | Type | Values | Written by |
|---|---|---|---|
| `flag_didnt_follow` | Boolean | The answer was a "didn't follow" dead end | The agent runtime |
| `flag_fallback` | Boolean | The guard or the verifier rejected the free reply, and the turn fell back | The agent runtime |
| `flag_parts_crossed` | Boolean | Part of the message was crossed | The agent runtime |
| `flag_slow` | Boolean | The answer took over 13 s, ADR 0049's bar | The agent runtime |
| `flag_typed_again` | Boolean | The person sent another message in the same chat within 60 s | platform-api, from the earlier turn's trace id, which the Portal sends with `previous` |
| `judge_kind_ok` | Boolean | The answer kind is acceptable | The judge |
| `judge_useful` | Numeric | 1 to 5 | The judge |
| `judge_cause` | Categorical | Missing ability, wrong path, unclear can't, dropped part, other, none | The judge |
| `review` | Categorical | Real problem, fine | A teammate in the review queue |
| `review_useful` | Numeric | 1 to 5 | The team lead, in the review queue |
| `review_cause` | Categorical | The same as `judge_cause` | A teammate in the review queue |
| `rating` | Boolean | Thumbs up is 1, thumbs down is 0 | A person on Home, through platform-api |

A code flag is written only when it is true. When a flag is known at answer time, code also sets `flagged` in the trace's metadata, and the judge's rules filter on it. The answer kind goes in the metadata and the tags.

1. **Code flags.** Our code sets them through the Langfuse SDK. No model is involved.
2. **The judge.** Langfuse's [LLM-as-a-judge][judge] evaluators score the top observation of each new Planner turn on Claude Opus 5.5 (`claude-opus-5-5`). Trace-level evaluators give no results on v4 ([compatibility][compat]). The Planner runs on Claude Sonnet 5.5, so the judge is a different model, as ADR 0047 requires. ADR 0047's CI gate still names Claude Sonnet 5.5, the Planner's own model, as its judge, against that ADR's own rule. The 27 of 30 check below covers the Langfuse judge on Opus 5.5. This ADR leaves the gate as it is. The evaluators use the eval's rubric from `agent-runtime/evals/anything.py`. An evaluator returns one score, so there are three ([API reference][api]).
   - **The judge reads every flagged trace and one in four of the others.** Flagged traces get all three scores. The others get `judge_kind_ok` and `judge_useful`.
   - **Why a sample.** Each judge call costs up to 2.5 cents, a guess from about 1,000 tokens in and up to 1,000 out, thinking included, at Claude Opus 5.5's USD 4 and USD 20 per million. If one turn in seven is flagged (a guess), an average turn costs up to about 2 cents to judge, close to the Planner's own 1.5 cents (ADR 0048). Judging every turn with all three would cost up to five times the Planner. Misses gather in the flagged traces, and those need a cause. A quarter of the rest is enough to see the daily rate.
   - **The rate is one number in the rule**, and the team lead can raise it. The judge has its own Anthropic key, with a monthly spend limit in the Anthropic console. The key is stored in Langfuse's [LLM connection][llm-connection].
   - **The judge's model call leaves our server**, as the Planner's own call does.
3. **People decide, in the review queue.** The review queue is a Langfuse [annotation queue][queues] called "Planner review". The housekeeping job adds every trace that has a code flag, a `judge_useful` of 1 or 2, or a thumbs down, through `POST /api/public/annotation-queues/{queueId}/items`. It skips traces already in the queue. It also adds five judged turns a week at random, so the judge is checked on good answers too. A teammate marks each trace `review` and picks the cause. The team lead also gives `review_useful` on the turns they review. For a real problem, they choose [+ Add to dataset][datasets] and add the trace to the `planner-regressions` dataset, with the answer kinds that would be acceptable.
4. **The judge is checked against people.** Before the judge's score gates anything, it must agree with the team lead's own labels on at least 27 of 30 turns (ADR 0047). The 30 turns include the random ones from the queue, so agreement is not measured on misses only. A turn matches when both `judge_useful` and `review_useful` are 4 or more, or both are below 4. `evals.pull_regressions` (below) counts the matches. Langfuse's [Score Analytics][analytics] also shows correlation for those two scores, and Cohen's kappa and a confusion matrix for `judge_cause` against `review_cause`. It is in beta, and the pricing page does not list it, so PR B checks that it runs on the free edition.
5. **A Langfuse dashboard shows the trend.** A [custom dashboard][dashboards] shows the share of judged turns scored 4 or 5, per day, per answer kind and per model. Flagged turns and sampled turns are separate lines, so the sample does not skew the rate, and a fix shows as a step in the line. Widgets can filter by tags and metadata, so a widget that cannot split by answer kind filters on it.
6. **A thumbs up or down sits under each Planner answer on Home.** The team lead kept it on 16 Nov, because only the person knows when an answer missed them. It writes only the `rating` score. A changed vote replaces it, under the same score id, name and time, as [Langfuse requires][scores-sdk]. The thumbs show only when tracing is on, which the capability registry decides, so the Portal never shows a button that does nothing. The Portal gets no quality page.

### The AI only proposes

Nothing in the loop edits the Planner's briefing, the capability registry, the guards or the refusals. The judge only scores, and the queue only collects.

A real problem becomes an eval case. `python -m evals.pull_regressions` reads `planner-regressions` and writes its items as cases under `agent-runtime/evals/cases/`. It writes each message word for word and marks the case as a real message, so the reviewer reads it as untrusted input. A person commits the cases with the fix, and the team lead checks each case's acceptable answer kinds in the pull request. The gate runs these cases like every other, so the fix must pass them and the miss cannot return. The cases live in git, not in a live pull during CI. Then they show in the diff, a run can be repeated, CI does not need Langfuse to be up, and the cases outlive the 60-day deletion.

The fix goes through a normal pull request, from a person or from a coding agent (ADR 0040), with the normal review and CI. The team lead approves it.

### Setup is code

PR B's setup script creates the score configs, the evaluators and their rules, the queue and the dataset through Langfuse's public API (`score-configs`, `v2/evaluators`, `v2/evaluation-rules`, `annotation-queues` and `v2/datasets`). It reads what exists first and adds only what is missing, so a second run changes nothing. It also compares each evaluator's prompt in Langfuse with the one in git, and fails on a difference. Git is the source. The dashboard API is marked unstable. If it does not work, the runbook describes the dashboard and a person builds it once. The `LANGFUSE_INIT_*` settings create the organization, the project and its keys at first start.

## Considered options

- **LangSmith, hosted.** Nothing to run. But traces leave our network, Phase 2 traces will hold Jira and access-review details, and DevNet needs them to stay inside.
- **LangSmith, self-hosted.** It is an add-on to LangSmith's Enterprise plan ([LangSmith][langsmith]).
- **Langfuse Cloud.** The same tool with less work, but the traces leave, as with hosted LangSmith.
- **Our own turn log in Cosmos DB, with no tool.** We would have to build the trace viewer, the judge runner, the review queue and the dashboard, and that time belongs to the builder.
- **Langfuse on Container Apps,** as the proposal said. ClickHouse has no supported disk there without a VNet, and it would cost USD 140 to 490 a month against the VM's USD 75.
- **A "Planner quality" page in the Portal, with a weekly report and Approve and Dismiss.** It was the first answer on 16 Nov, and the team lead dropped it the same day. Langfuse's own screens do the review, and the Portal stays the product for support staff.

## Consequences

- **ADR 0003 is amended.** Agents are traced with self-hosted Langfuse, so its worry about traces leaving for DevNet ends. `AGENTS.md` changes in the same pull request as this ADR.
- **The DevNet move gains a VM.** Langfuse moves into DevNet with the rest. Question 8 in `docs/design/devnet-move.md` becomes two questions. Which model may the judge call (the same answer as question 2)? May we run a VM with a disk? PR A updates that note and the Must item in `CHECKPOINTS.html`.
- **After handover, the sponsor's owner would review in Langfuse,** a technical tool, not the Portal. We accept that for now and revisit it at handover.
- **We look after a VM.** Unattended security updates stay on, and image upgrades come through pull requests. A kernel update needs a reboot, so every service in the profile has `restart: unless-stopped` and comes back after one.
- **New secrets go into Key Vault.** They are:
  - the project keys that `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` and `LANGFUSE_INIT_PROJECT_SECRET_KEY` set;
  - Langfuse's `SALT`, `ENCRYPTION_KEY` and `NEXTAUTH_SECRET`;
  - the passwords for Langfuse's PostgreSQL role, ClickHouse and Valkey;
  - the init user's password, which is never used while password sign-in is off;
  - the storage account key;
  - the Entra app's secret, the judge's Anthropic key and the pseudonym key.

  The VM reads them from Key Vault through its managed identity into an env file that only root can read. Local passwords come from `deploy/make-env.sh` and are never reused on Azure. A person registers the Entra app, as for every Entra change.
- **The proposal's Must item changes shape.** It named Container Apps. Langfuse is still self-hosted and set up with Terraform, on a VM, for the reasons above.
- **The build order:**
  1. PR A puts Langfuse in the local stack, traces the Planner with masking, and writes the code flags.
  2. PR B adds the judge's evaluators as code where the API allows, the review queue, the dataset sync into the evals, and the dashboard.
  3. The thumbs are designed in the chat-first prototype (`docs/design/chat-first/prototype.html`). Then PR C builds them.
  4. An `infra` pull request brings the VM to Azure after PR A. It is applied only once the team lead approves the monthly cost.

[overview]: https://langfuse.com/self-hosting
[pricing]: https://langfuse.com/pricing-self-host
[license]: https://langfuse.com/self-hosting/license-key
[v3-v4]: https://langfuse.com/self-hosting/upgrade/upgrade-guides/upgrade-v3-to-v4
[compat]: https://langfuse.com/docs/compatibility
[compose]: https://langfuse.com/self-hosting/deployment/docker-compose
[compose-file]: https://github.com/langfuse/langfuse/blob/main/docker-compose.yml
[azure-dev]: https://github.com/langfuse/langfuse/blob/main/docker-compose.dev-azure.yml
[scaling]: https://langfuse.com/self-hosting/configuration/scaling
[clickhouse]: https://langfuse.com/self-hosting/deployment/infrastructure/clickhouse
[postgres]: https://langfuse.com/self-hosting/deployment/infrastructure/postgres
[cache]: https://langfuse.com/self-hosting/deployment/infrastructure/cache
[blob]: https://langfuse.com/self-hosting/deployment/infrastructure/blobstorage
[telemetry]: https://langfuse.com/self-hosting/security/telemetry
[auth]: https://langfuse.com/self-hosting/security/authentication-and-sso
[rbac]: https://langfuse.com/docs/administration/rbac
[retention]: https://langfuse.com/docs/administration/data-retention
[deletion]: https://langfuse.com/docs/administration/data-deletion
[masking]: https://langfuse.com/docs/observability/features/masking
[sdk]: https://langfuse.com/docs/observability/sdk/overview
[langchain]: https://langfuse.com/docs/integrations/langchain/tracing
[users]: https://langfuse.com/docs/observability/features/users
[scores]: https://langfuse.com/docs/evaluation/scores/data-model
[scores-sdk]: https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk
[judge]: https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge
[llm-connection]: https://langfuse.com/docs/administration/llm-connection
[queues]: https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues
[datasets]: https://langfuse.com/docs/evaluation/experiments/datasets
[analytics]: https://langfuse.com/docs/evaluation/evaluation-methods/score-analytics
[dashboards]: https://langfuse.com/docs/metrics/features/custom-dashboards
[api]: https://cloud.langfuse.com/generated/api/openapi.yml
[ch-tips]: https://clickhouse.com/docs/operations/tips
[aca-storage]: https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts
[prices]: https://prices.azure.com/api/retail/prices
[langsmith]: https://docs.langchain.com/langsmith/self-hosted
[caddy]: https://caddyserver.com/docs/automatic-https
[headless]: https://langfuse.com/self-hosting/administration/headless-initialization
[gh-notify]: https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs
