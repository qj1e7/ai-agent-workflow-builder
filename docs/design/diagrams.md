# Design diagrams

These diagrams show the platform as built at commit `b07646d` (branch `ci/dast-and-load`), for the school's design rubric and for a new teammate. Each one names the real services, routes, database schemas and activity event kinds. When the code and a diagram disagree, the code is right and the diagram needs a fix.

The diagrams are drawn from these sources:

- The walking skeleton design, `docs/design/walking-skeleton.md`, and its implementation reconciliation table. This file and ADRs 0002 to 0013 come from the open docs pull requests, so they are not on this branch yet.
- ADRs 0014 and 0015 in `docs/adr/`.
- `deploy/compose.yaml`, `deploy/make-env.sh` and `deploy/postgres/init.sh`.
- `platform-api/src/`, `agent-runtime/src/`, `portal/src/` and the n8n workflow files in `platform-api/src/platform_api/orchestration/workflows/`.
- `contracts/openapi.json`, `contracts/activity-event.schema.json`, `contracts/agent-api.schema.json` and the recorded runs in `contracts/fixtures/runs/`.

To check that every diagram still parses, run `scripts/render-diagrams.sh`. It renders each Mermaid block in this file with the Mermaid CLI in Docker, writes the PNGs to `docs/evidence/diagrams/`, and checks the routes and event kinds against the contracts. It also fails on any of the old themed names and on long dashes.

## Use case diagram

Two people use the platform. The Operator saves a use case, starts runs, watches them and retries a failed run. The Approver decides on the write action. Solid boxes exist now. Dashed boxes are Phase 2. Jira and Teams are a mock and a stub inside platform-api today, so the diagram marks them that way.

```mermaid
flowchart LR
    operator["Operator<br/>(person)"]
    approver["Approver<br/>(person)"]

    subgraph platform["AI workflow builder"]
        direction TB
        uc1(["Describe a task and save a use case"])
        uc2(["Run it now"])
        uc3(["Watch the run live"])
        uc4(["Approve or decline the write action<br/>never your own work, steps in order"])
        uc5(["Retry a failed run<br/>with the AI troubleshooter's advice"])
        uc6(["Check GitHub for new releases"])
        uc7(["Create the Jira ticket after approval"])
        p1(["Access review with two Approvers in order"])
        p2(["Patch housekeeping"])
        p3(["Start runs on a schedule"])
    end

    agents["Platform agents<br/>Room lead, Release checker<br/>(a specialist agent), AI troubleshooter"]
    github["GitHub<br/>(public API)"]
    jira["Jira<br/>(mock inside platform-api now)"]
    teams["Teams<br/>(stub inside platform-api now)"]

    operator --- uc1
    operator --- uc2
    operator --- uc3
    operator --- uc5
    approver --- uc3
    approver --- uc4
    uc2 -. "includes" .-> uc6
    uc4 -. "on approve, includes" .-> uc7
    uc6 --- agents
    uc6 --- github
    uc5 --- agents
    uc4 --- teams
    uc7 --- jira
    operator -.- p2
    operator -.- p3
    approver -.- p1

    classDef person fill:#e8f0fe,stroke:#1a56db,color:#111
    classDef system fill:#f3f4f6,stroke:#6b7280,color:#111
    classDef now fill:#ffffff,stroke:#111827,color:#111
    classDef phase2 fill:#ffffff,stroke:#9ca3af,stroke-dasharray:6 4,color:#6b7280
    class operator,approver person
    class agents,github,jira,teams system
    class uc1,uc2,uc3,uc4,uc5,uc6,uc7 now
    class p1,p2,p3 phase2
```

Each use case maps to code that exists now:

| Use case | Who | Route or code |
|---|---|---|
| Describe a task and save a use case | Operator | `POST /api/v1/use-cases/suggest` picks a template from the words, `POST /api/v1/use-cases` saves it |
| Run it now | Operator | `POST /api/v1/use-cases/{use_case_id}/runs` with an `Idempotency-Key` |
| Watch the run live | Operator, Approver | `GET /api/v1/runs/{run_id}/events` (server-sent events) |
| Approve or decline | Approver | `GET /api/v1/approvals/{approval_id}`, `POST /api/v1/approvals/{approval_id}/decisions`. A refusal for own work is `403 own_work` |
| Retry a failed run | Operator | `GET /api/v1/runs/{run_id}/troubleshoot`, then `POST /api/v1/runs/{run_id}/retry` |

The Phase 2 use cases need no new approval model. `ApprovalPolicy` already holds an ordered list of steps, and `decide()` already refuses a person who decided an earlier step. A schedule is one more caller of `Orchestrator.start_run`.

## Bounded contexts (DDD context map)

There are four contexts. Three of them ship in one container, `platform-api` (ADR 0010), and each has its own PostgreSQL schema and database role. The agent runtime is a separate Python project and container, so platform-api cannot import it. Solid arrows are code dependencies, pointing from the context that imports to the context it imports. `import-linter` enforces them in CI, and a context may import another only through its package `__init__`. Dashed arrows are HTTP calls.

```mermaid
---
config:
  flowchart:
    wrappingWidth: 420
---
flowchart TB
    portal["Portal<br/>(browser app)"]
    n8n["n8n<br/>(workflow engine)"]

    subgraph api["platform-api container"]
        direction TB
        builder["<b>Use case builder</b><br/>Owns: templates (in code), use cases and versions<br/>Schema: builder, role wab_builder<br/>Exposes: Builder, /api/v1/templates, /api/v1/use-cases"]
        orch["<b>Orchestration</b><br/>Owns: runs, leg attempts, proposals, approval requests and decisions,<br/>write executions, outbox, engine status, mock Jira tickets, Teams stub messages<br/>Schema: orchestration, role wab_orchestration<br/>Exposes: Orchestrator, RunStarter, /api/v1/runs, /api/v1/approvals/{approval_id},<br/>/internal/v1/runs/{run_id}/steps/{step}<br/>Safety checker: check(). Write gateway: WriteGateway"]
        mon["<b>Run monitoring</b><br/>Owns: the activity log<br/>Schema: monitoring, role wab_monitoring<br/>Exposes: ActivityLog, callback_for, the SSE route,<br/>/internal/v1/runs/{run_id}/agent-events, the AI troubleshooter"]
        shared["Shared kernel<br/>shared.py, wire.py, auth.py, db.py<br/>Authenticator port, DevAuth adapter"]
    end

    subgraph rt["agent-runtime container"]
        runtime["<b>Agent runtime</b><br/>Owns: agent working state, in memory per task<br/>No database. No write tools or write credentials<br/>Exposes: Agent API POST /v1/tasks, GET /v1/agents"]
    end

    builder -- "imports RunSpec, RunStarter<br/>(start_run, latest_carry_forward)" --> orch
    orch -- "imports ActivityLog, event types,<br/>callback_for (one transaction)" --> mon
    builder --> shared
    orch --> shared
    mon --> shared

    orch -. "Agent API POST /v1/tasks, X-Agent-Key<br/>contract: agent-api.schema.json" .-> runtime
    runtime -. "POST /internal/v1/runs/{run_id}/agent-events<br/>X-Callback-Token, to the URL it was given" .-> mon
    n8n -. "POST /internal/v1/runs/{run_id}/steps/{step}<br/>POST /internal/v1/workflow-failures, X-Step-Key" .-> orch
    orch -. "WorkflowEngine port: POST /webhook/release-check/work or act" .-> n8n
    portal -. "/api/v1, contract: openapi.json" .-> builder
    portal -. "/api/v1, contract: openapi.json" .-> orch
    portal -. "SSE events and troubleshoot<br/>contract: activity-event.schema.json" .-> mon

    classDef ctx fill:#ffffff,stroke:#111827,color:#111
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111
    class builder,orch,mon,runtime ctx
    class portal,n8n,shared ext
```

Each context reaches the outside world through ports that it owns. The adapters in the table run today. The right-hand column names what replaces each one later.

| Context | Port | Adapter now | Later |
|---|---|---|---|
| Use case builder | `RunStarter` (owned by orchestration) | `Orchestrator` | none needed |
| Orchestration | `WorkflowEngine` | `N8nWebhooks` | none needed |
| Orchestration | `AgentRuntime` | `HttpAgentRuntime`, which parses replies into `TaskFinished`, `TaskFailed`, `AgentRejected` or `AgentUnavailable` | none needed |
| Orchestration | `ApprovalChannel` | `TeamsStub` | a Teams message, later a Teams bot |
| Orchestration | `WriteConnector` | `MockJiraConnector` | a real Jira adapter |
| Orchestration | `ActivityLogPort` | run monitoring's `ActivityLog` | none needed |
| Run monitoring | `ActivityLog` | PostgreSQL table `monitoring.run_events`, with LISTEN and NOTIFY for the live activity view | an adapter for the NoSQL store, once the team picks one (ADR 0011) |
| Shared kernel | `Authenticator` | `DevAuth`, which reads `X-Dev-User` | Entra ID |
| Agent runtime | `RoomLead` | `FixedRoomLead`, which always brings in the Release checker | an LLM planner |
| Agent runtime | `ReleaseSource` | `GitHubReleaseSource`, or a fake GitHub in tests | none needed |
| Agent runtime | `Summarizer` | `TemplateSummarizer`, or `ModelSummarizer` when `AGENT_SUMMARY_MODEL` is set | the model the team picks |

The database holds the same boundaries as the code. Each role has grants on its own schema only. The one exception is that `wab_orchestration` may read and insert into `monitoring.run_events`, so a run's state change and its activity events commit in one transaction. n8n has its own database, `n8n`, and its own role, with no access to `platform`.

Three published contracts cross process boundaries. CI regenerates each one from the owner's models and fails on any difference.

| Contract | Owner | Readers |
|---|---|---|
| `contracts/openapi.json` | platform-api (all three contexts) | the Portal's typed client, the DAST scan |
| `contracts/activity-event.schema.json` | run monitoring | the Portal's live activity view, the AI troubleshooter |
| `contracts/agent-api.schema.json` | agent runtime | orchestration's `HttpAgentRuntime`, NCS's agent hub later |

## Deployment now: Docker Compose

One command starts the whole stack: `docker compose -f deploy/compose.yaml up --build`. Look at the published ports first. Only the Portal, platform-api and the n8n editor are reachable from the host, and PostgreSQL and the agent runtime are reachable only inside the Compose network. Secrets never live in git. `deploy/make-env.sh` writes random values to `deploy/.env` (mode 600), and Compose passes them to each service as environment variables.

```mermaid
flowchart LR
    browser["Browser<br/>Operator or Approver"]
    maint["Maintainer's browser"]
    gh["GitHub API<br/>api.github.com"]
    envfile[("deploy/.env<br/>written by deploy/make-env.sh<br/>mode 600, not in git")]

    subgraph host["Docker host, compose project wab"]
        direction LR
        portal["portal<br/>image wab/portal:dev<br/>node:22-alpine build, nginx:1.27-alpine serve<br/>internal 8080, published 8080"]
        api["platform-api<br/>image wab/platform-api:dev<br/>python:3.14-slim-bookworm<br/>internal 8000, published 8000<br/>builder, orchestration, run monitoring,<br/>mock Jira, Teams stub, tick loop"]
        boot["bootstrap (runs once)<br/>image wab/platform-api:dev<br/>python -m platform_api.bootstrap"]
        agent["agent-runtime<br/>image wab/agent-runtime:dev<br/>python:3.14-slim-bookworm<br/>internal 8100, not published"]
        n8n["n8n<br/>n8nio/n8n:2.42.6, pinned by digest<br/>internal 5678, published 5678"]
        pg[("postgres<br/>postgres:17, pinned by digest<br/>internal 5432, not published<br/>databases platform and n8n<br/>volume pgdata")]
        n8nvol[("volume n8ndata")]
    end

    browser -- "HTTP 8080" --> portal
    browser -. "HTTP 8000, also published" .-> api
    maint -- "n8n editor 5678" --> n8n
    portal -- "proxies /api/ to platform-api:8000" --> api
    api -- "POST /v1/tasks, X-Agent-Key" --> agent
    agent -- "POST /internal/v1/runs/.../agent-events" --> api
    agent -- "GET /repos/{owner}/{repo}/releases" --> gh
    api -- "POST /webhook/release-check/work or act" --> n8n
    n8n -- "POST /internal/v1/..., X-Step-Key" --> api
    api -- "roles wab_builder, wab_orchestration,<br/>wab_monitoring" --> pg
    n8n -- "role n8n, database n8n" --> pg
    n8n --- n8nvol
    boot -- "role wab_owner: migrations" --> pg
    boot -- "n8n REST API: owner, API key,<br/>step key credential, workflows" --> n8n
    envfile -. "environment variables" .-> host

    classDef ours fill:#e8f0fe,stroke:#1a56db,color:#111
    classDef theirs fill:#ffffff,stroke:#111827,color:#111
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111
    class portal,api,boot,agent ours
    class n8n,pg,n8nvol theirs
    class browser,maint,gh,envfile ext
```

Services start in this order. postgres becomes healthy, then n8n becomes ready, then bootstrap runs to completion. bootstrap runs the migrations, sets up n8n, lints the workflow files and loads them, error workflow first. platform-api starts after bootstrap succeeds and the agent runtime is healthy. The Portal starts last.

| Secret in `deploy/.env` | Read by |
|---|---|
| `POSTGRES_PASSWORD`, `N8N_DB_PASSWORD`, `WAB_*_PASSWORD` | postgres (to create the roles), n8n, bootstrap, platform-api |
| `N8N_ENCRYPTION_KEY` | n8n. Never change it while the `n8ndata` volume is kept |
| `N8N_OWNER_EMAIL`, `N8N_OWNER_PASSWORD` | bootstrap |
| `STEP_KEY` | bootstrap stores it in n8n as a credential. platform-api checks it on `/internal/v1` |
| `AGENT_API_KEY` | platform-api sends it, and the agent runtime checks it |
| `CALLBACK_SIGNING_KEY` | platform-api, to sign the agent's callback tokens |
| `GITHUB_TOKEN` (optional) | the agent runtime |

## Deployment planned: Azure

> **Planned. Nothing here is deployed yet.** The infrastructure-as-code tool is still an open decision, so this diagram does not name one.

This is the Azure shape from ADR 0004 and the walking skeleton design. Each Compose service becomes one Azure resource, and the code does not change, because every cloud service sits behind a port. Two slots are open on purpose. The team has not picked the NoSQL store or the AI model provider. Azure OpenAI is the candidate only if the model tests pick it.

```mermaid
flowchart LR
    browser["Browser<br/>Operator or Approver"]
    teams["Microsoft Teams<br/>(needs a tenant that allows custom apps)"]
    jira["Jira<br/>(real adapter later)"]
    gh["GitHub API"]
    entra["Entra ID<br/>(replaces dev sign-in)"]

    subgraph azure["Azure subscription (planned)"]
        direction LR
        swa["Static Web Apps<br/>Portal"]
        subgraph aca["Container Apps environment"]
            direction TB
            api["Container App: platform-api<br/>minimum 1 replica, so tick keeps running"]
            agent["Container App: agent-runtime<br/>internal ingress"]
            n8n["Container App: n8n<br/>exactly 1 replica, internal ingress"]
            job["Container Apps Job: bootstrap<br/>CI runs it after each deploy"]
        end
        pg[("Azure Database for PostgreSQL<br/>Flexible Server<br/>databases platform and n8n")]
        kv["Key Vault<br/>secrets reach containers as<br/>Container Apps secrets"]
        ai["App Insights"]
        nosql[("NoSQL store<br/>OPEN DECISION")]
        llm["AI model provider<br/>OPEN DECISION<br/>Azure OpenAI if the tests pick it"]
    end

    browser --> swa
    swa -- "/api/v1" --> api
    browser -. "sign-in" .-> entra
    api --> agent
    agent -- "callbacks" --> api
    api -- "webhooks" --> n8n
    n8n -- "/internal/v1" --> api
    job --> pg
    job --> n8n
    api --> pg
    n8n --> pg
    agent --> gh
    agent -.-> llm
    api -- "ApprovalChannel" --> teams
    api -- "WriteConnector" --> jira
    api -.-> nosql
    kv -. "secrets" .-> aca
    aca -. "logs and traces" .-> ai

    classDef planned fill:#ffffff,stroke:#111827,stroke-dasharray:4 3,color:#111
    classDef open fill:#fff7ed,stroke:#c2410c,stroke-dasharray:6 4,color:#9a3412
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111
    class swa,api,agent,n8n,job,pg,kv,ai planned
    class nosql,llm open
    class browser,teams,jira,gh,entra ext
```

The Azure shape keeps three rules from the design.

- n8n holds no write credential. Real Jira credentials reach platform-api only, from Key Vault.
- Our code never calls a Key Vault SDK. Secrets arrive as environment variables, as they do in Compose.
- If the NoSQL store is picked, it replaces the activity log's PostgreSQL adapter behind `ActivityLog`. Orchestration then needs an outbox for its events (ADR 0011).

## Sequence: the release check succeeds

This is the recorded run in `contracts/fixtures/runs/success.json`, drawn against the real routes. n8n carries the run in two legs. The work leg ends when the approval opens, and the act leg starts only after the Approver approves (ADR 0007). Each `events:` line names the activity events written in that transaction, and the live activity view receives them in `seq` order over server-sent events. The walking skeleton design has the same flow, with the declined branch, in "Sequence: an approved run, with the rejected branch". This diagram adds what the build added: `agent_message`, the Teams stub and the steps inside the write.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    actor Ap as Approver
    participant P as Portal
    box platform-api
        participant B as Use case builder
        participant M as Run monitoring
        participant O as Orchestration
        participant TS as Teams stub
        participant WG as Safety checker and write gateway
        participant J as Mock Jira
    end
    participant N as n8n
    participant AR as Agent runtime
    participant GH as GitHub

    Op->>P: Run now
    P->>B: POST /api/v1/use-cases/{use_case_id}/runs, Idempotency-Key
    B->>O: start_run(RunSpec)
    O->>M: one transaction: run Pending, outbox start_leg(work)<br/>events: run_created, leg_dispatched
    B-->>P: 201 {run_id, events_url}
    P->>M: GET /api/v1/runs/{run_id}/events (SSE stays open)
    M--)P: run_created, leg_dispatched

    Note over O,N: Work leg
    O->>N: tick sends the outbox row: POST /webhook/release-check/work {run_id}
    N-->>O: 202 {run_id, n8n_execution_id}
    N->>O: node "Run agents": POST /internal/v1/runs/{run_id}/steps/run_agents<br/>X-Step-Key, X-N8N-Execution
    O->>M: Pending to Working. events: step_started
    O->>AR: POST /v1/tasks, X-Agent-Key<br/>{task_id, instruction, inputs, carry_forward, callback}
    AR->>GH: GET /repos/langchain-ai/langgraph/releases
    GH-->>AR: 30 releases, latest 1.2.16
    AR--)M: POST /internal/v1/runs/{run_id}/agent-events, X-Callback-Token<br/>agent_joined, agent_message, agent_step_started, agent_step_finished
    M--)P: agent events as they arrive
    AR-->>O: 200 TaskFinished {summary, proposed create_ticket, carry_forward, events}
    O->>M: proposal with digest, Working to Proposed<br/>events: missed agent events, write_action_proposed, step_finished
    O-->>N: 200 {proceed: true, outcome: proposed}
    N->>O: node "Ask for approval": POST .../steps/ask_approval
    O->>M: approval request, Proposed to AwaitingApproval, outbox announce<br/>events: approval_requested, step_finished
    O-->>N: 200 {proceed: false, outcome: approval_opened}. The work leg ends
    O->>TS: tick sends the announcement with the approval link
    O->>M: events: approval_announced
    M--)P: write_action_proposed, approval_requested, approval_announced

    Note over Ap,O: Approval gate
    Ap->>P: open the Teams stub card's link, or the run view (ADR 0015)
    P->>O: GET /api/v1/approvals/{approval_id}
    O-->>P: actions, digest, steps, you_can_decide
    Ap->>P: Approve
    P->>O: POST /api/v1/approvals/{approval_id}/decisions<br/>{step: 0, verdict: approve, digest}
    Note over O: decide() checks the Approver role, not own work,<br/>the next step in order, and the digest the Approver saw
    O->>M: decision, AwaitingApproval to Acting, outbox start_leg(act)<br/>events: approval_decided, leg_dispatched
    O-->>P: 201 {status: approved}

    Note over O,N: Act leg
    O->>N: tick sends the outbox row: POST /webhook/release-check/act {run_id}
    N-->>O: 202 {run_id, n8n_execution_id}
    N->>O: node "Do write action": POST .../steps/write_action
    O->>M: events: step_started
    O->>WG: check(): run Acting for this proposal, approval folded to Approved,<br/>digest matches, connector and operation registered
    WG-->>O: AuthorizedWrite. Anything else is Deny, event write_action_denied
    O->>WG: WriteGateway.execute(AuthorizedWrite)
    WG->>J: create_ticket, one idempotency key per action
    J-->>WG: MOCK-142
    O->>M: Acting to Succeeded<br/>events: write_action_done, step_finished, run_succeeded
    O-->>N: 200 {proceed: true, outcome: written}
    M--)P: approval_decided, leg_dispatched, step_started, write_action_done, step_finished, run_succeeded
```

## Sequence: the run fails, then the Operator retries

This is the recorded run in `contracts/fixtures/runs/failure.json`. GitHub answers 503 three times, so the Release checker gives up and the run fails with reason `AgentError`, marked retryable. Look at where the failure is decided. The agent runtime reports it, and platform-api fails the run and still answers n8n with `200 {proceed: false}`, so n8n's error workflow does not fire for an agent failure. The second branch shows the other path, where an n8n node fails and the error workflow reports it.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant P as Portal
    box platform-api
        participant M as Run monitoring
        participant O as Orchestration
    end
    participant N as n8n
    participant AR as Agent runtime
    participant GH as GitHub

    Note over Op,GH: The run starts as in the success path. events: run_created, leg_dispatched, step_started
    N->>O: node "Run agents": POST /internal/v1/runs/{run_id}/steps/run_agents
    O->>AR: POST /v1/tasks {task_id: run_id/work/1, ...}
    alt the agent fails (the recorded run)
        loop 3 tries
            AR->>GH: GET /repos/langchain-ai/langgraph/releases
            GH-->>AR: 503 Service Unavailable
            AR--)M: agent-events: agent_message "GitHub answered 503 (try n of 3)"
        end
        AR--)M: agent-events: agent_failed
        AR-->>O: 200 TaskFailed {error: {type, message, retryable: true}, events}
        O->>M: Working to Failed(AgentError, retryable), cancel the outbox<br/>events: step_finished (outcome failed), run_failed
        O-->>N: 200 {proceed: false, outcome: failed}. n8n marks its execution a success
    else an n8n node fails
        N->>N: the Error Trigger starts the "Run failure reporter" workflow
        N->>O: node "Report failure": POST /internal/v1/workflow-failures<br/>{execution_id, workflow, last_node, message, execution_url}
        O->>M: map the execution to its run, Failed(WorkflowNodeError, retryable)<br/>events: run_failed
    end
    Note over O: If n8n never calls back, the state's deadline fails the run as TimedOut
    M--)P: SSE: agent_failed, step_finished, run_failed

    P->>M: GET /api/v1/runs/{run_id}/troubleshoot
    Note over M: The AI troubleshooter reads the latest run_failed event.<br/>It has one rule per failure reason
    M-->>P: 200 {failure, advice: {explanation, likely_cause, suggested_action: retry, suggestion}}
    P-->>Op: An agent could not finish its work. Retry the run.

    Op->>P: Retry run
    P->>O: POST /api/v1/runs/{run_id}/retry
    Note over O: Needs the Operator role and a retryable failure.<br/>The person who retries becomes a party, so they cannot approve this run
    O->>M: Failed to Pending, attempt 2, outbox start_leg(work) no sooner than 3 s<br/>events: run_retried, leg_dispatched
    O-->>P: 202 {state: pending}
    M--)P: run_retried, leg_dispatched
    O->>N: tick sends the outbox row: POST /webhook/release-check/work {run_id}
    N->>O: node "Run agents": POST .../steps/run_agents
    O->>AR: POST /v1/tasks {task_id: run_id/work/2, ...}
    Note over Op,GH: A new task_id means the agent really runs again. From here the run follows the success path
```

A failure in the act leg retries differently. `Failed.retry` sends the run back to `Acting`, not `Pending`, so nobody has to approve again. The write gateway then finds any write it already recorded as `done` and returns that write instead of calling Jira a second time.
