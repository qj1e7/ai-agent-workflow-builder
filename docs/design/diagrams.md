# Design diagrams

These diagrams show the rebuilt app as it is on `main` at commit `8ee417d`, after the rebuild plan's P1 to P14. They are for the school's design rubric, the first presentation and a new teammate. Each one names the real pages, services, routes, tables and activity event kinds. When the code and a diagram disagree, the code is right and the diagram needs a fix.

The diagrams are drawn from these sources:

- The Portal's pages and menu in `portal/src/shell/routes.tsx`, which follow the prototype `docs/design/portal-routines/prototype.html` and its design note `docs/design/portal-routines.md`.
- The domain model in `docs/design/rebuild-domain-model.md`, and ADRs 0028 to 0032.
- The migrations in `platform-api/src/platform_api/migrations/`, checked against `\d` of a running database on 31 Oct 2026 (`docs/evidence/diagrams/schema-2026-10-31.txt`).
- The Cosmos DB code in `platform-api/src/platform_api/monitoring/` (P4), and the items in a running emulator (`docs/evidence/diagrams/cosmos-2026-10-31.txt`).
- `deploy/compose.yaml`, `infra/envs/dev/main.tf` and the workflows in `.github/workflows/`.
- `contracts/openapi.json`, `contracts/activity-event.schema.json`, `contracts/agent-api.schema.json` and the recorded runs in `contracts/fixtures/runs/`.

To check every diagram, run `scripts/render-diagrams.sh`. It renders each Mermaid block with the Mermaid CLI in Docker and writes the PNGs to `docs/evidence/diagrams/`. It checks the routes and event kinds against the contracts, the ER diagrams' tables against the migrations, and the CI/CD diagram's jobs against the workflow files. It also fails on the old themed names, on the names the rebuild retired, and on long dashes.

"Use case" is the code's name for what people see in the app as a workflow (`GLOSSARY.md`). The diagrams use "workflow" for what people see, and "use case" for the code and the tables.

## Use case diagram

Two roles use the app, and one person may hold both. The Operator sets up workflows, looks after the Software watchlist and Settings, and retries a stopped workflow. The Approver says yes or no to a run's proposal and confirms the risky setup changes. Each use case sits on the page that does it. The pages are the Portal's menu (Home, Workflows, Software watchlist, Agent library and New workflow), the run page, Settings (the gear) and the practice Teams panel (the Teams button). Everyone signs in with Entra ID, and the People list gives them their roles.

```mermaid
flowchart LR
    operator["Operator<br/>(person)"]
    approver["Approver<br/>(person)"]

    subgraph app["AI Workflow Builder"]
        direction TB
        subgraph home["Home"]
            h1(["See what needs you now"])
            h2(["Retry a stopped workflow,<br/>with the AI troubleshooter's reason"])
        end
        subgraph workflows["Workflows"]
            w1(["See every workflow,<br/>its status and its last result"])
            w2(["Run a workflow now"])
            w3(["Pause, resume, delete<br/>or restore a workflow"])
        end
        subgraph newwf["New workflow"]
            n1(["Describe a task and check<br/>what the Planner understood"])
            n2(["Check the plan and its agents"])
            n3(["Choose when it runs"])
            n4(["Turn it on, or save a draft"])
        end
        subgraph software["Software watchlist"]
            s1(["Add, remove or restore<br/>watched software"])
            s2(["Set the check's schedule,<br/>or check now"])
        end
        subgraph agents["Agent library"]
            a1(["Read the agents and the tools they use"])
        end
        subgraph runpage["Run page"]
            r1(["Watch a run live"])
            r2(["Approve or decline the proposal,<br/>never for your own work"])
            r3(["Read why a run stopped"])
        end
        subgraph settings["Settings"]
            t1(["Connect the AI model"])
            t2(["Add people and set their roles"])
            t3(["Confirm a new Approver<br/>or a new AI model address"])
        end
        subgraph teamspanel["Teams approvals"]
            m1(["Read the approval request<br/>and open its run page"])
        end
    end

    planner["Planner and specialist agents<br/>(Version checker, agent cards)"]
    model["AI model<br/>(Claude Haiku 5.5, through a gateway)"]
    github["GitHub releases"]
    jira["Practice Jira<br/>(inside platform-api)"]
    teams["Practice Teams<br/>(inside platform-api)"]

    operator --- h1
    operator --- h2
    operator --- w1
    operator --- w2
    operator --- w3
    operator --- n1
    operator --- n2
    operator --- n3
    operator --- n4
    operator --- s1
    operator --- s2
    operator --- a1
    operator --- r1
    operator --- r3
    operator --- t1
    operator --- t2
    approver --- h1
    approver --- r1
    approver --- r2
    approver --- t3
    approver --- m1

    n1 --- planner
    n2 --- planner
    planner --- model
    s2 -. "includes" .-> planner
    planner --- github
    r2 -. "on approve, includes:<br/>create the Jira tickets" .-> jira
    m1 --- teams

    classDef person fill:#e8f0fe,stroke:#1a56db,color:#111
    classDef system fill:#f3f4f6,stroke:#6b7280,color:#111
    classDef page fill:#ffffff,stroke:#111827,color:#111
    class operator,approver person
    class planner,model,github,jira,teams system
    class h1,h2,w1,w2,w3,n1,n2,n3,n4,s1,s2,a1,r1,r2,r3,t1,t2,t3,m1 page
```

Each use case maps to a page that exists and to the routes it calls:

| Use case | Page | Who | Route |
|---|---|---|---|
| See what needs you now | Home, `/` | Both | `GET /api/v1/home` |
| Retry a stopped workflow | Home, `/` | Operator | `GET /api/v1/home` gives the reason, then `POST /api/v1/runs/{run_id}/retry` |
| See every workflow | Workflows, `/workflows` and `/workflows/{use_case_id}` | Both | `GET /api/v1/use-cases`, `GET /api/v1/use-cases/{use_case_id}`, `GET /api/v1/runs` |
| Run a workflow now | Workflows | Operator | `POST /api/v1/use-cases/{use_case_id}/runs`, with an `Idempotency-Key` |
| Pause, resume, delete or restore | Workflows | Operator | `POST /api/v1/use-cases/{use_case_id}/pause`, `.../resume`, `DELETE /api/v1/use-cases/{use_case_id}`, `.../restore` |
| Describe a task and check what the Planner understood | New workflow, `/new` | Operator | `POST /api/v1/builder/understand` |
| Check the plan and its agents | New workflow | Operator | `POST /api/v1/builder/plan`, and `POST /api/v1/agent-cards` when the Planner drafted a new agent |
| Choose when it runs, and turn it on | New workflow, then `/new/done/{use_case_id}` | Operator | `POST /api/v1/agent-use-cases`, with its schedule |
| Save a draft | New workflow | Operator | `PUT /api/v1/drafts/{draft_id}`, `GET /api/v1/drafts`, `DELETE /api/v1/drafts/{draft_id}` |
| Add, remove or restore watched software | Software watchlist, `/software` | Operator | `POST /api/v1/watchlist/software`, `DELETE /api/v1/watchlist/software/{software_id}`, `.../restore` |
| Set the check's schedule, or check now | Software watchlist | Operator | `PUT /api/v1/watchlist/schedule`, `DELETE /api/v1/watchlist/schedule`, `POST /api/v1/use-cases/{use_case_id}/runs` |
| Read the agents and their tools | Agent library, `/agents` | Both | `GET /api/v1/agent-cards`, `GET /api/v1/tools` |
| Watch a run live | Run page, `/runs/{run_id}` | Both | `GET /api/v1/runs/{run_id}`, `GET /api/v1/runs/{run_id}/events` (server-sent events) |
| Approve or decline the proposal | Run page, or `/approvals/{approval_id}` | Approver | `GET /api/v1/approvals/{approval_id}`, `POST /api/v1/approvals/{approval_id}/decisions`. Own work is refused with 403 |
| Read why a run stopped | Run page | Both | `GET /api/v1/runs/{run_id}/troubleshoot` |
| Connect the AI model | Settings, `/settings` | Operator | `POST /api/v1/settings/model/connect`, `PUT /api/v1/settings/model` |
| Add people and set their roles | Settings | Operator | `POST /api/v1/people`, `PUT /api/v1/people/{person_id}/operator`, `POST /api/v1/people/{person_id}/approver` |
| Confirm a new Approver or a new AI model address | Settings | Approver | `POST /api/v1/confirmations/{confirmation_id}/decisions`, `POST /api/v1/settings/model/address-decision` |
| Read the approval request and open its run page | Teams approvals, the Teams button | Approver | `GET /api/v1/teams-stub/messages` |

Some parts of the prototype wait for Phase 2, each with its own decision first. They have no page yet, so they are not in the diagram: Connections and AI usage in Settings, named Approvers with a backup and an expiry (ADR 0024), Approve buttons inside a Teams message, Report to support, Open in n8n (ADRs 0026 and 0027), the Vulnerability checker and the package registries (ADR 0025), and the sponsor's two real use cases, the quarterly access review with two Approvers in turn and patch housekeeping.

## Bounded contexts (DDD context map)

There are four contexts. Three of them ship in one container, `platform-api` (ADR 0010), and each has its own PostgreSQL schema and database role. The agent runtime is a separate Python project and container, so platform-api cannot import it. Solid arrows are code dependencies, pointing from the context that imports to the one it imports. `import-linter` enforces them in CI, and a context may import another only through its package `__init__`. Dashed arrows are calls over the network.

```mermaid
---
config:
  flowchart:
    wrappingWidth: 440
---
flowchart TB
    portal["Portal<br/>(React app, served by nginx)"]
    n8n["n8n<br/>(carries each run in two legs)"]
    entra["Entra ID<br/>(signs people in)"]
    cosmos[("Azure Cosmos DB for NoSQL<br/>database activity, container run_events")]

    subgraph api["platform-api container"]
        direction TB
        builder["<b>Use case builder</b><br/>Owns: use cases and their versions, agent cards and their versions,<br/>the agents on each use case, watched software, drafts<br/>Schema: builder, role wab_builder<br/>Exposes: Builder, Home, /api/v1/use-cases, /api/v1/agent-cards,<br/>/api/v1/builder/understand, /api/v1/watchlist, /api/v1/drafts, /api/v1/home"]
        orch["<b>Orchestration</b><br/>Owns: runs, leg attempts, proposals, approval requests and decisions,<br/>write executions, outbox, schedules, the watchlist's checks,<br/>people, confirmations, the AI model setting, the settings history,<br/>the practice Jira and the practice Teams<br/>Schema: orchestration, role wab_orchestration<br/>Exposes: Orchestrator, RunStarter, CardPlanning, /api/v1/runs,<br/>/api/v1/approvals/{approval_id}, /api/v1/people, /api/v1/settings/model,<br/>/internal/v1/runs/{run_id}/steps/{step}<br/>Safety checker: check(). Write gateway: WriteGateway"]
        mon["<b>Run monitoring</b><br/>Owns: the activity log, its copy in Cosmos DB and the copied marks<br/>Schema: monitoring, role wab_monitoring<br/>Exposes: ActivityLog, Copier, the event stream,<br/>/internal/v1/runs/{run_id}/agent-events, the AI troubleshooter"]
        shared["Shared kernel<br/>shared.py, wire.py, auth.py, oidc.py, db.py<br/>Authenticator port: DevAuth or OidcAuthenticator. PeopleDirectory port"]
    end

    subgraph rt["agent-runtime container"]
        runtime["<b>Agent runtime</b><br/>Owns: the Planner, the Version checker and each agent card's run,<br/>in memory per task. No database. No write keys<br/>Exposes: Agent API /v1/tasks, /v1/planner/understand, /v1/planner/choose,<br/>/v1/cards/draft, /v1/models/connect, /v1/models/test, /v1/tools, /v1/agents"]
    end

    builder -- "imports RunStarter, RunSpec, ScheduleBook,<br/>the Planner's answer types" --> orch
    builder -- "imports explain_failure, for Home" --> mon
    orch -- "imports ActivityLog, event types,<br/>callback_for (one transaction)" --> mon
    builder --> shared
    orch --> shared
    mon --> shared

    orch -. "Agent API /v1/tasks and the Planner's routes,<br/>X-Agent-Key. Contract: agent-api.schema.json" .-> runtime
    runtime -. "POST /internal/v1/runs/{run_id}/agent-events,<br/>X-Callback-Token, to the address it was given" .-> mon
    runtime -. "practice Jira reads:<br/>/internal/v1/runs/{run_id}/practice-jira/tickets" .-> orch
    n8n -. "POST /internal/v1/runs/{run_id}/steps/{step},<br/>/internal/v1/workflow-failures, /internal/v1/schedules/tick, X-Step-Key" .-> orch
    orch -. "WorkflowEngine port: POST /webhook/run/work or act" .-> n8n
    mon -. "the Copier writes items,<br/>the readers query one partition" .-> cosmos
    portal -. "/api/v1, contract: openapi.json" .-> builder
    portal -. "/api/v1, contract: openapi.json" .-> orch
    portal -. "event stream and troubleshoot,<br/>contract: activity-event.schema.json" .-> mon
    portal -. "sign-in (OpenID Connect)" .-> entra
    shared -. "checks each token's signature<br/>with Entra's published keys" .-> entra

    classDef ctx fill:#ffffff,stroke:#111827,color:#111
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111
    class builder,orch,mon,runtime ctx
    class portal,n8n,shared,entra,cosmos ext
```

Each context reaches the outside world through ports that it owns. The adapters in the table run today. The right-hand column names what replaces each one later.

| Context | Port | Adapter now | Later |
|---|---|---|---|
| Use case builder | `RunStarter` (owned by orchestration) | `Orchestrator` | none needed |
| Use case builder | `Planning` (owned by orchestration) | `CardPlanning`, which sends the connected AI model's settings to the agent runtime. Without a model, New workflow answers with the starter workflows | none needed |
| Orchestration | `WorkflowEngine` | `N8nWebhooks` | the node pack (ADRs 0026 and 0027) |
| Orchestration | `AgentRuntime` | `HttpAgentRuntime` | none needed |
| Orchestration | `ApprovalChannel` | `TeamsStub`, the practice Teams | a Teams message with a link, then Approve buttons in Teams |
| Orchestration | `WriteConnector` | `MockJiraConnector`, the practice Jira | a real Jira adapter |
| Orchestration | `ActivityLogPort` | run monitoring's `ActivityLog` | none needed |
| Run monitoring | `EventReader` | `CosmosEvents` when `ACTIVITY_READER` is `cosmos`, else `PostgresEvents` | a DynamoDB adapter for AWS (ADR 0031) |
| Run monitoring | `EventCopy` | `CosmosEvents`, filled by the `Copier` | none needed |
| Shared kernel | `Authenticator` | `DevAuth`, which reads `X-Dev-User` on localhost only, or `OidcAuthenticator` for Entra ID | none needed |
| Shared kernel | `PeopleDirectory` | `People`, the People list in PostgreSQL (ADR 0029) | none needed |
| Agent runtime | `Planner` | `FixedPlanner`, which brings in the Version checker for a watchlist check and each saved agent for a workflow. Reading a task in New workflow asks the AI model | a model for every run |
| Agent runtime | `ReleaseSource` | `GitHubReleaseSource`, or a fake GitHub in tests | the package registries (ADR 0025) |
| Agent runtime | `Summarizer` | `TemplateSummarizer`, or `ModelSummarizer` when a model is set | the model the eval picks (ADR 0032) |

The database holds the same boundaries as the code. Each role has grants on its own schema only. The one exception is that `wab_orchestration` may read and insert into `monitoring.run_events`, so a run's state change and its activity events commit in one transaction. n8n has its own database, `n8n`, and its own role, with no access to `platform`.

Three published contracts cross process boundaries. CI makes each one again from its owner's models and fails on any difference.

| Contract | Owner | Readers |
|---|---|---|
| `contracts/openapi.json` | platform-api (all three contexts) | the Portal's typed client, the DAST scan |
| `contracts/activity-event.schema.json` | run monitoring | the live activity view, the AI troubleshooter |
| `contracts/agent-api.schema.json` | agent runtime | orchestration's `HttpAgentRuntime`, NCS's agent hub later |

## Class diagram: the domain model

These are the things the app keeps, from the domain model's tables. Each class names its context. A class marked Phase 2 is designed but not built. The diagram shows meaning, not storage: the ER diagrams below show the tables.

```mermaid
classDiagram
    direction LR
    class Person {
        <<orchestration>>
        id
        entraObjectId
        email
        displayName
        isOperator
        isApprover
    }
    class Confirmation {
        <<orchestration>>
        kind : approver or model address
        change
        askedBy
        about
        decidedBy
        decision : confirmed, not now or closed
    }
    class ModelSetting {
        <<orchestration>>
        provider
        address
        model
        keyEnd : last two characters
        lastTest
    }
    class SettingsChange {
        <<orchestration>>
        area : people or model
        summary
        changedBy
        confirmedBy
    }
    class Connection {
        <<Phase 2>>
        system
        account
        keyEnd
        expires
    }
    class UseCase {
        <<builder>>
        name
        owner
        paused
        deleted
    }
    class Draft {
        <<builder>>
        step : 1 to 4
        content
        author
    }
    class Schedule {
        <<orchestration>>
        day : every day, weekdays or one weekday
        time : Singapore time
        owner
    }
    class ApprovalPolicy {
        <<orchestration>>
        steps : one or two
    }
    class ApprovalStep {
        <<orchestration>>
        label
        whoMayDecide
        backup : Phase 2
        waits : Phase 2
    }
    class AgentCard {
        <<builder>>
        name
        purpose
        owner
    }
    class AgentCardVersion {
        <<builder>>
        version
        plan : ordered blocks
        inputs
        approvalsNeeded
        createdBy
    }
    class Tool {
        <<runtime>>
        name
        readsOrWrites
        system
    }
    class WatchedSoftware {
        <<builder and orchestration>>
        name
        source : GitHub releases
        ourVersion
        newestVersion
        status
    }
    class Run {
        <<orchestration>>
        startedBy
        how : by hand, on a schedule or a test run
        state
        retriedBy
    }
    class ActivityEvent {
        <<monitoring>>
        seq
        kind
        actor
        summary
        data
    }
    class Proposal {
        <<orchestration>>
        digest
    }
    class WriteAction {
        <<orchestration>>
        target
        writeKey
    }
    class ApprovalRequest {
        <<orchestration>>
        step
        parties
        askedAt
    }
    class ApprovalDecision {
        <<orchestration>>
        decidedBy
        verdict : approve or decline
        digestSeen
    }
    class Diagnosis {
        <<monitoring>>
        whatHappened
        whatToDo
        operatorCanFix
    }

    Person "1" --> "*" UseCase : owns
    Person "1" --> "*" Draft : writes
    Person "1" --> "*" Confirmation : asks
    Confirmation --> "0..1" Person : about
    Person "1" --> "*" SettingsChange : made
    SettingsChange --> "0..1" Confirmation : confirmed by
    UseCase "1" --> "0..1" Schedule
    UseCase "1" --> "1" ApprovalPolicy
    ApprovalPolicy "1" --> "1..2" ApprovalStep
    UseCase "*" --> "*" AgentCardVersion : its agents
    AgentCard "1" --> "*" AgentCardVersion
    AgentCardVersion "*" --> "*" Tool : may use
    UseCase "1" --> "*" WatchedSoftware : the Software watchlist
    UseCase "1" --> "*" Run
    Run "*" --> "*" AgentCardVersion : runs with
    Run "1" --> "*" ActivityEvent
    Run "1" --> "0..1" Proposal
    Proposal "1" --> "*" WriteAction
    Proposal "1" --> "0..1" ApprovalRequest
    ApprovalRequest "1" --> "*" ApprovalDecision
    ApprovalDecision --> Person : decided by
    Run "1" --> "0..1" Diagnosis : when it stops
    Run ..> ModelSetting : asks the model through
    AgentCardVersion ..> Connection : reads through
```

Three rules sit on these classes. Nobody approves their own work: the parties of a run are the person who started it, the workflow's owner and anyone who retried it, and none of them may decide. Nothing is written without a yes: a write action runs only after the last step of its approval request says approve, for the digest the Approver saw. And a confirmation is decided by an Approver who is neither the person who asked nor the person it is about.

A diagnosis is worked out from the run's latest `run_failed` event. It is not stored. A use case's agents are stored as the card version each one was saved with, so a later change to a card does not change a workflow that is already on.

## Class diagram: deciding on a proposal

This is the design of the key use case, an Approver's yes on the run page, at class level. It shows how the Portal, platform-api and n8n carry it out. The Portal's `ApprovalGate` calls the API through `useDecide`. orchestration's `decide` route hands the request to `Orchestrator`, which checks the pure rules in `approvals.py` and writes the decision, the run's new state and its activity events in one transaction. The act leg then goes through the safety checker and the write gateway.

```mermaid
classDiagram
    direction LR
    class ApprovalGate {
        <<Portal component>>
        approval
        decision
    }
    class useDecide {
        <<Portal hook>>
        POST /api/v1/approvals/approval_id/decisions
    }
    class decideRoute {
        <<platform-api route>>
        approval_id
        step, verdict, digest
    }
    class Authenticator {
        <<port>>
        call(request) Identity
    }
    class PeopleDirectory {
        <<port>>
        person(user_id) Principal
    }
    class Principal {
        user_id
        roles
        display
    }
    class Orchestrator {
        decide(approval_id, principal, step_index, verdict, seen_digest)
        tick()
    }
    class approvals {
        <<rules>>
        decide(request, decisions, principal, step_index, verdict, seen_digest, now)
        why_not(request, decisions, principal)
    }
    class ApprovalRequest {
        id
        run_id
        proposal_id
        digest
        policy
        parties
    }
    class ApprovalPolicy {
        steps
    }
    class ApprovalStep {
        label
        eligible
    }
    class Decision {
        step_index
        by
        verdict
        seen_digest
    }
    class Store {
        load_approval()
    }
    class ActivityLog {
        append(uow, run_id, events)
    }
    class WorkflowEngine {
        <<port>>
        start_leg()
    }
    class N8nWebhooks {
        POST /webhook/run/work or act
    }
    class check {
        <<safety checker>>
        AuthorizedWrite or Deny
    }
    class WriteGateway {
        execute(AuthorizedWrite)
    }
    class WriteConnector {
        <<port>>
        execute(action, key)
    }
    class MockJiraConnector {
        the practice Jira
    }

    ApprovalGate --> useDecide : Approve or Decline
    useDecide ..> decideRoute : HTTP, JSON
    decideRoute --> Authenticator : who signed in
    decideRoute --> PeopleDirectory : their roles, from the People list
    PeopleDirectory --> Principal
    decideRoute --> Orchestrator
    Orchestrator --> Store
    Store --> ApprovalRequest : loads
    Orchestrator --> approvals : may this person decide?
    approvals --> ApprovalRequest
    approvals --> Decision : records
    ApprovalRequest --> ApprovalPolicy
    ApprovalPolicy "1" --> "1..2" ApprovalStep
    Orchestrator --> ActivityLog : approval_decided, leg_dispatched
    Orchestrator --> WorkflowEngine : act leg, from the outbox
    WorkflowEngine <|.. N8nWebhooks
    Orchestrator --> check : at the write_action step
    check --> WriteGateway : AuthorizedWrite only
    WriteGateway --> WriteConnector
    WriteConnector <|.. MockJiraConnector
```

`approvals.decide` refuses a person without the Approver role, a party to the run, a step out of order, a step already decided and a digest that is not the current proposal's. The route answers 403 with the reason. `check` builds an `AuthorizedWrite` only for a run in `Acting`, whose approval folds to approved for the same digest, with a registered connector and operation. Anything else is a `Deny` and the event `write_action_denied`.

## ER diagram: the builder schema

The use case builder's tables, from its migrations. PK is a primary key, FK a foreign key and UK part of a unique key. A solid line is a foreign key. A dashed line is a reference by id that has no foreign key.

```mermaid
erDiagram
    use_cases["builder.use_cases"] {
        text use_case_id PK
        text owner "a person's id"
        timestamptz created_at
        integer current_version
        timestamptz paused_at "null unless paused"
        text paused_by "set with paused_at"
        timestamptz deleted_at "null unless deleted"
        text deleted_by "set with deleted_at"
    }
    use_case_versions["builder.use_case_versions"] {
        text use_case_id PK, FK
        integer version PK
        text template
        text name
        text instruction
        jsonb params
        timestamptz created_at
    }
    watched_software["builder.watched_software"] {
        text use_case_id PK, FK, UK
        integer version PK, FK, UK
        text software_id PK
        integer position
        text name
        text source_kind UK "github only"
        text source_ref UK "unique as lower(source_ref)"
        text starting_version "null when not given"
        text added_by
        timestamptz added_at
    }
    cards["builder.cards"] {
        text card_id PK
        text owner
        timestamptz created_at
        integer current_version
    }
    card_versions["builder.card_versions"] {
        text card_id PK, FK
        integer version PK
        text name
        text purpose
        jsonb good_for
        jsonb inputs
        jsonb blocks
        jsonb approvals
        text created_by
        timestamptz created_at
    }
    use_case_cards["builder.use_case_cards"] {
        text use_case_id PK, FK, UK
        integer version PK, FK, UK
        integer position PK
        text card_id UK "a starter card lives in code, so no foreign key"
        integer card_version
        jsonb values
    }
    drafts["builder.drafts"] {
        text author PK
        text draft_id PK
        integer step "1 to 4"
        jsonb content
        timestamptz created_at
        timestamptz saved_at
    }
    builderVersions["builder.alembic_version"] {
        varchar version_num PK
    }

    use_cases ||--|{ use_case_versions : "has versions"
    use_case_versions ||--o{ watched_software : "watches"
    use_case_versions ||--o{ use_case_cards : "uses agents"
    cards ||--|{ card_versions : "has versions"
    card_versions |o..o{ use_case_cards : "card_id and card_version"
```

`builder.use_cases` keeps `deleted_at` instead of deleting a row, and `wab_builder` has no right to delete from it, so a deleted workflow's past runs stay readable and Restore can bring it back. `builder.watched_software` also has the unique index `watched_software_one_source_per_version` on `(use_case_id, version, source_kind, lower(source_ref))`, so one version of the watchlist names each GitHub project once.

## ER diagram: orchestration's runs and approvals

The tables that carry a run from start to the write. `runs.use_case_id` names a row in `builder.use_cases`, by id, with no foreign key across schemas. Every column that ends in `_by`, and `started_by` and `asked_by`, holds a person's id from `orchestration.people`, also with no foreign key, so a person who leaves keeps their name on past runs.

```mermaid
erDiagram
    runs["orchestration.runs"] {
        text run_id PK
        text use_case_id UK "builder.use_cases, by id"
        text idempotency_key UK
        jsonb spec
        text started_by
        timestamptz started_at
        timestamptz updated_at
        integer version "optimistic lock"
        text state
        jsonb state_data
        timestamptz deadline_at
        jsonb retried_by
        text carry_forward
    }
    leg_attempts["orchestration.leg_attempts"] {
        text run_id PK, FK
        text leg PK "work or act"
        integer attempt PK
        text n8n_execution_id
        timestamptz recorded_at
    }
    proposals["orchestration.proposals"] {
        text proposal_id PK
        text run_id FK
        jsonb actions
        text digest
        timestamptz created_at
    }
    approval_requests["orchestration.approval_requests"] {
        text approval_id PK
        text run_id FK
        text proposal_id FK
        text digest
        jsonb policy
        jsonb parties "who may not decide"
        timestamptz created_at
    }
    approval_decisions["orchestration.approval_decisions"] {
        text approval_id PK, FK
        integer step_index PK
        text decided_by
        text verdict
        text seen_digest
        timestamptz decided_at
    }
    write_executions["orchestration.write_executions"] {
        text proposal_id PK, FK
        integer action_index PK
        text run_id
        text idempotency_key UK
        text status "started or done"
        timestamptz started_at
        timestamptz done_at
        text external_reference
    }
    outbox["orchestration.outbox"] {
        bigint id PK
        text run_id FK
        text kind
        jsonb payload
        integer attempt
        timestamptz next_at
        text status "pending, sent, cancelled or given_up"
        text last_error
        timestamptz created_at
    }
    engine_status["orchestration.engine_status"] {
        integer id PK "always 1"
        timestamptz loaded_at
        boolean ready
        text detail
        jsonb workflows
    }
    mock_jira_tickets["orchestration.mock_jira_tickets"] {
        text key PK
        integer number UK
        text project
        text title
        text body
        timestamptz created_at
        text run_id
        text proposal_id
        text idempotency_key UK
        text status "To Do or Done"
        timestamptz done_at
    }
    teams_stub_messages["orchestration.teams_stub_messages"] {
        text id PK
        timestamptz ts
        text channel
        text text
        text link "the run page"
        text run_id
        text approval_id UK
    }

    runs ||--o{ leg_attempts : "tried in legs"
    runs ||--o{ proposals : "proposes"
    runs ||--o{ approval_requests : "asks"
    proposals ||--o{ approval_requests : "covered by"
    approval_requests ||--o{ approval_decisions : "decided in steps"
    proposals ||--o{ write_executions : "written as"
    runs ||--o{ outbox : "queues"
    approval_requests |o..o| teams_stub_messages : "announced as"
    proposals |o..o{ mock_jira_tickets : "practice Jira tickets"
```

`mock_jira_tickets` and `teams_stub_messages` are the practice Jira and the practice Teams. Their `run_id`, `proposal_id` and `approval_id` are copies, with no foreign keys, as a real Jira or Teams would hold them.

## ER diagram: orchestration's watchlist, schedules, people and settings

```mermaid
erDiagram
    software_checks["orchestration.software_checks"] {
        text use_case_id PK
        text software_id PK
        text run_id FK
        timestamptz checked_at
        text newest_version "or a problem"
        text problem
        timestamptz newest_at "set with newest_version"
    }
    our_versions["orchestration.our_versions"] {
        text use_case_id PK
        text software_id PK
        text version
        text source "first_check or ticket_done"
        timestamptz learned_at
        text ticket_key "set when the ticket is done"
    }
    proposed_tickets["orchestration.proposed_tickets"] {
        text proposal_id PK, FK
        integer action_index PK
        text run_id FK
        text use_case_id
        text software_id
        text version
        text status "proposed, written, done or dropped"
        text ticket_key
        timestamptz done_at
    }
    schedules["orchestration.schedules"] {
        text use_case_id PK "builder.use_cases, by id"
        text day "every_day, weekdays or a weekday"
        text at "HH:MM, on a 5 minute step"
        text time_zone
        text owner_id "the schedule owner"
        text owner_name
        timestamptz saved_at
        timestamptz last_slot_started
    }
    people["orchestration.people"] {
        text id PK
        text entra_oid UK "set at the first sign-in"
        text email UK "unique as lower(email)"
        text display
        boolean is_operator
        boolean is_approver
        text added_by
        timestamptz added_at
        timestamptz bound_at
        timestamptz removed_at
    }
    confirmations["orchestration.confirmations"] {
        text id PK
        text kind UK "approver or model_address"
        text about FK, UK
        jsonb change
        text digest
        text asked_by
        timestamptz asked_at
        text decided_by
        text decision "confirmed, not_now or closed"
        timestamptz decided_at
    }
    settings_changes["orchestration.settings_changes"] {
        bigint id PK
        timestamptz changed_at
        text area "people or model"
        text changed_by
        text confirmed_by
        text confirmation_id FK
        text summary
    }
    model_setting["orchestration.model_setting"] {
        text slot PK "active or pending"
        text provider
        text style
        text base_url
        text model
        text sealed_key "encrypted"
        text key_hint "last two characters"
        real test_seconds
        text saved_by
        text saved_by_name
        timestamptz saved_at
    }
    model_hosts["orchestration.model_hosts"] {
        text host PK "a confirmed model address"
        text confirmed_by
        timestamptz confirmed_at
    }
    orchestrationVersions["orchestration.alembic_version"] {
        varchar version_num PK
    }
    runsAgain["orchestration.runs"] {
        text run_id PK
    }
    proposalsAgain["orchestration.proposals"] {
        text proposal_id PK
    }

    runsAgain ||--o{ software_checks : "last read by"
    runsAgain ||--o{ proposed_tickets : "proposed in"
    proposalsAgain ||--o{ proposed_tickets : "one per write action"
    people |o--o{ confirmations : "about"
    confirmations |o--o{ settings_changes : "confirmed by"
    software_checks |o..o| our_versions : "same use_case_id and software_id"
```

The two `orchestration.runs` and `orchestration.proposals` boxes repeat the tables of the diagram above, to show their foreign keys. Two more unique indexes hold rules: `people_email_key` on `lower(email)`, so one email is one person, and `confirmations_one_open_key` on `(kind, coalesce(about, ''))` while `decided_at` is null, so only one confirmation of each kind waits for each person, and one for the AI model address.

## ER diagram: the monitoring schema

```mermaid
erDiagram
    run_events["monitoring.run_events"] {
        text run_id PK, UK "orchestration.runs, by id"
        integer seq PK "1, 2, 3 in each run"
        timestamptz ts
        jsonb actor
        text kind
        text summary
        jsonb data
        text dedupe_key UK
    }
    run_events_copied["monitoring.run_events_copied"] {
        text run_id PK
        text generation "the Cosmos DB container's"
        integer seq "the copied mark"
        timestamptz copied_at
    }
    monitoringVersions["monitoring.alembic_version"] {
        varchar version_num PK
    }

    run_events }|..o| run_events_copied : "copied up to seq"
```

`monitoring.run_events` only grows. Both roles that may write it, `wab_orchestration` and `wab_monitoring`, have `SELECT` and `INSERT` and nothing else. The unique `(run_id, dedupe_key)` drops a repeated callback. PostgreSQL keeps every event even though the readers use Cosmos DB, because the next `seq` and the repeat check both read these rows (ADR 0031).

## NoSQL design: the activity log in Cosmos DB

ADR 0031 keeps a copy of the activity log in Azure Cosmos DB for NoSQL. PostgreSQL writes each event and sets its order. The copier in run monitoring copies each run's new events, in order, to one container. The live activity view, its replay, the events page and the AI troubleshooter read that container.

```mermaid
flowchart LR
    orch["Orchestration and run monitoring<br/>ActivityLog.append, in the same<br/>transaction as the state change"]
    pg[("PostgreSQL<br/>monitoring.run_events<br/>keeps every event")]
    mark[("PostgreSQL<br/>monitoring.run_events_copied<br/>the copied mark of each run")]
    copier["Copier<br/>one copier per run at a time,<br/>under an advisory lock, in seq order"]

    subgraph account["Azure Cosmos DB for NoSQL account<br/>Strong consistency, one region, free tier, 1000 RU/s"]
        subgraph database["database activity"]
            subgraph container["container run_events, partition key /runId"]
                runa["partition of one run<br/>items 1, 2, 3 and on,<br/>one per activity event"]
                runb["partition of the next run<br/>its own items 1, 2, 3"]
                gen["partition copier<br/>one item, id generation"]
            end
        end
    end

    readers["Readers in run monitoring<br/>the live activity view's stream and its replay,<br/>the events page, the AI troubleshooter"]

    orch -- "INSERT, then NOTIFY run_events" --> pg
    pg -- "LISTEN run_events,<br/>read rows after the mark" --> copier
    copier -- "upsert item: id is seq as text" --> runa
    copier -- "record the new mark,<br/>then NOTIFY run_events_copied" --> mark
    copier -. "read at start: a new generation<br/>means copy every run again" .-> gen
    mark -. "LISTEN run_events_copied<br/>wakes the stream" .-> readers
    readers -- "SELECT * FROM c WHERE c.seq > @after<br/>ORDER BY c.seq, inside one partition" --> runa
    readers -. "while the copy is behind,<br/>read PostgreSQL instead" .-> pg
```

The item shapes, from `CosmosEvents.put` and `CosmosEvents.ensure`:

```mermaid
classDiagram
    direction LR
    class RunEventItem {
        <<item in run_events>>
        id : the seq, as text
        runId : the run, and the partition key
        seq : number, sorted on
        ts : time, ISO 8601
        actor : id, kind, display
        kind : one of the 21 event kinds
        summary : one plain sentence
        data : depends on the kind
        dedupeKey : text
    }
    class GenerationItem {
        <<item in run_events>>
        id : generation
        runId : copier
        generation : 32 random hex characters
    }
    class CopiedMark {
        <<row in PostgreSQL>>
        run_id
        generation
        seq
        copied_at
    }
    CopiedMark ..> RunEventItem : copied up to seq
    CopiedMark ..> GenerationItem : belongs to this generation
```

| Part | Value |
|---|---|
| Account | Azure Cosmos DB for NoSQL, Strong consistency, one region. Free tier with a 1000 RU/s cap, or serverless when the subscription refuses the free tier (`COSMOS_SERVERLESS`) |
| Database | `activity` |
| Container | `run_events`, 1000 RU/s on the free tier |
| Partition key | `/runId`, hash, version 2 |
| Item id | The event's `seq` in its run, as text. Copying the same event twice writes the same item twice and changes nothing |
| Main query | `SELECT * FROM c WHERE c.seq > @after ORDER BY c.seq`, with the run's id as the partition key. A reader stops before a gap and waits for the next copied notice |
| Other item | `id` `generation` in the partition `copier`. The copier writes a random generation into each new container. When the generation changes, every run is copied again from the start |
| Time to live | None. The log keeps every event |
| Who writes | Only the copier in platform-api. On Azure it signs in with the account key, read from Key Vault. That key may read and write items but may not create, change or delete a database or a container. platform-api's managed identity already holds the Cosmos DB Data Contributor role on `activity`, ready for when the key is turned off (CKV_AZURE_140 in `docs/evidence/iac/README.md`). Locally it uses the emulator's fixed key |

An item from the 31 Oct scan's run, as the emulator returned it, without Cosmos DB's own `_` fields:

```json
{
  "id": "13",
  "runId": "run_01M67WVHRG63X24F90AYT2GFZD",
  "seq": 13,
  "ts": "2026-10-31T02:33:10.301314+00:00",
  "actor": { "id": "platform", "kind": "platform", "display": "Platform" },
  "kind": "approval_requested",
  "summary": "Approval requested. Waiting for the Team approver.",
  "data": {
    "link": "/approvals/apr_01M67WVHWXETCD5ES3A31JGSHM",
    "steps": [{ "index": 0, "label": "Team approver", "status": "open", "decided_at": null, "decided_by": null }],
    "approval_id": "apr_01M67WVHWXETCD5ES3A31JGSHM"
  },
  "dedupeKey": "once:171dc915e723eb044af9ea29a0c2049c"
}
```

## Deployment now: Docker Compose

One command starts the whole stack: `scripts/up.sh`, which runs `docker compose -f deploy/compose.yaml up --build`. Only the Portal, platform-api and the n8n editor are published on the host. PostgreSQL, the Cosmos DB emulator and the agent runtime are reachable only inside the Compose network. Secrets never live in git. `deploy/make-env.sh` writes random values to `deploy/.env` (mode 600), and Compose passes them to each service as environment variables. For tests, `deploy/compose.e2e.yaml` adds a fake GitHub and a fake AI model, and `deploy/compose.scan.yaml` takes every published port away for the scans.

```mermaid
flowchart LR
    browser["Browser<br/>Operator or Approver"]
    maint["Maintainer's browser"]
    gh["GitHub API<br/>api.github.com"]
    model["AI model gateway<br/>(the address in Settings)"]
    envfile[("deploy/.env<br/>written by deploy/make-env.sh<br/>mode 600, not in git")]

    subgraph host["Docker host, compose project wab"]
        direction LR
        portal["portal<br/>image wab/portal:dev<br/>nginx serves the React app<br/>internal 8080, published 8080"]
        api["platform-api<br/>image wab/platform-api:dev<br/>python:3.14-slim-bookworm<br/>internal 8000, published 8000<br/>builder, orchestration, run monitoring,<br/>the copier, practice Jira, practice Teams"]
        boot["bootstrap (runs once)<br/>image wab/platform-api:dev<br/>python -m platform_api.bootstrap"]
        agent["agent-runtime<br/>image wab/agent-runtime:dev<br/>internal 8100, not published"]
        n8n["n8n<br/>n8nio/n8n:2.42.6, pinned by digest<br/>internal 5678, published 5678"]
        pg[("postgres<br/>postgres:17, pinned by digest<br/>internal 5432, not published<br/>databases platform and n8n<br/>volume pgdata")]
        cosmos[("cosmos<br/>Cosmos DB emulator vnext-preview,<br/>pinned by digest<br/>internal 8081, not published")]
        n8nvol[("volume n8ndata")]
    end

    browser -- "HTTP 8080" --> portal
    browser -. "HTTP 8000, also published" .-> api
    maint -- "n8n editor 5678" --> n8n
    portal -- "proxies /api/ to platform-api:8000" --> api
    api -- "Agent API, X-Agent-Key" --> agent
    agent -- "POST /internal/v1/runs/{run_id}/agent-events" --> api
    agent -- "GET /repos/{owner}/{repo}/releases" --> gh
    agent -. "only with a model connected" .-> model
    api -- "POST /webhook/run/work or act" --> n8n
    n8n -- "POST /internal/v1/..., X-Step-Key,<br/>and every 5 minutes /internal/v1/schedules/tick" --> api
    api -- "roles wab_builder, wab_orchestration,<br/>wab_monitoring" --> pg
    api -- "the copier writes,<br/>the readers read" --> cosmos
    n8n -- "role n8n, database n8n" --> pg
    n8n --- n8nvol
    boot -- "role wab_owner: migrations" --> pg
    boot -- "n8n REST API: owner, API key,<br/>step key credential, n8n workflows" --> n8n
    envfile -. "environment variables" .-> host

    classDef ours fill:#e8f0fe,stroke:#1a56db,color:#111
    classDef theirs fill:#ffffff,stroke:#111827,color:#111
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111
    class portal,api,boot,agent ours
    class n8n,pg,cosmos,n8nvol theirs
    class browser,maint,gh,model,envfile ext
```

Services start in this order. postgres and the Cosmos DB emulator become healthy, then n8n becomes ready, then bootstrap runs to completion. bootstrap runs the migrations, sets up n8n, lints the n8n workflow files and loads them, the error workflow first. platform-api starts after bootstrap succeeds and the agent runtime is healthy. The Portal starts last.

| Secret in `deploy/.env` | Read by |
|---|---|
| `POSTGRES_PASSWORD`, `N8N_DB_PASSWORD`, `WAB_*_PASSWORD` | postgres (to create the roles), n8n, bootstrap, platform-api |
| `N8N_ENCRYPTION_KEY` | n8n. Never change it while the `n8ndata` volume is kept |
| `N8N_OWNER_EMAIL`, `N8N_OWNER_PASSWORD` | bootstrap |
| `STEP_KEY` | bootstrap stores it in n8n as a credential. platform-api checks it on `/internal/v1` |
| `AGENT_API_KEY` | platform-api sends it, and the agent runtime checks it |
| `CALLBACK_SIGNING_KEY` | platform-api, to sign the agent's callback tokens |
| `SETTINGS_ENCRYPTION_KEY` | platform-api, to encrypt the AI model's key (ADR 0022) |

## Deployment on Azure

This is the shape that `infra/envs/dev/main.tf` builds and `.github/workflows/deploy.yml` deploys (P14). Each Compose service becomes one Container App, with the same images. The code does not change, because every cloud service sits behind a port, and secrets arrive as environment variables as they do in Compose.

```mermaid
flowchart LR
    browser["Browser<br/>Operator or Approver"]
    entra["Entra ID<br/>(sign-in, ADR 0018)"]
    gh["GitHub API"]
    model["AI model gateway<br/>(the address in Settings)"]
    actions["GitHub Actions<br/>deploy.yml, by hand, main only"]

    subgraph rg["Resource group rg-wab-dev"]
        direction LR
        subgraph aca["Container Apps environment"]
            direction TB
            portal["Container App portal<br/>external https, 0 to 1 replica"]
            api["Container App platform-api<br/>external https, 1 replica,<br/>so the copier and the outbox keep running"]
            agent["Container App agent-runtime<br/>internal ingress, 0 to 1 replica"]
            n8n["Container App n8n<br/>internal ingress, exactly 1 replica"]
            dbinit["Container Apps Job db-init<br/>creates the database roles"]
            boot["Container Apps Job bootstrap<br/>migrations and n8n setup,<br/>after each deploy"]
        end
        pg[("Azure Database for PostgreSQL<br/>Flexible Server, TLS only<br/>databases platform and n8n")]
        cosmos[("Azure Cosmos DB for NoSQL<br/>free tier, Strong consistency<br/>activity / run_events, /runId")]
        kv["Key Vault<br/>generated secrets and the Cosmos DB key,<br/>read by each app's managed identity"]
        acr["Container Registry, Basic<br/>our images and copies of n8n and postgres"]
        logs["Log Analytics and App Insights"]
    end

    browser -- "https" --> portal
    portal -- "proxies /api/ over https" --> api
    browser -. "sign-in" .-> entra
    api -. "token keys" .-> entra
    api --> agent
    agent -- "callbacks" --> api
    api -- "webhooks" --> n8n
    n8n -- "/internal/v1" --> api
    api --> pg
    n8n --> pg
    dbinit --> pg
    boot --> pg
    boot --> n8n
    api -- "the account key, from Key Vault" --> cosmos
    agent --> gh
    agent -.-> model
    kv -. "secrets" .-> aca
    acr -. "images" .-> aca
    aca -. "logs" .-> logs
    actions -- "Terraform apply,<br/>push images, run the jobs" --> rg

    classDef az fill:#ffffff,stroke:#111827,color:#111
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111
    class portal,api,agent,n8n,dbinit,boot,pg,cosmos,kv,acr,logs az
    class browser,entra,gh,model,actions ext
```

The Azure shape keeps three rules from the design.

- n8n holds no write key. The practice Jira lives inside platform-api, and a real Jira key would reach platform-api only, from Key Vault.
- Our code never calls a Key Vault SDK. Secrets arrive as Container Apps secrets that point at Key Vault.
- There is no virtual network yet, so PostgreSQL, Cosmos DB and Key Vault keep public endpoints behind keys, TLS and roles. Private endpoints come with the move to DevNet (ADR 0005, `docs/design/devnet-move.md`). `docs/evidence/iac/README.md` lists each accepted finding.

## CI/CD pipeline

Every job in `.github/workflows/`, in each file's order, with its steps in order. Each step runs in a container pinned by digest, or in the runner's own tools, so the jobs can move to GitLab CI. A person starts the deploy by hand, and the `azure-dev` environment accepts only `main`.

```mermaid
---
config:
  flowchart:
    wrappingWidth: 420
---
flowchart TB
    pr["A pull request,<br/>or a push to main"]
    push["A push to main, or by hand"]
    hand["By hand, on main"]
    daily["Every pull request, every push to main,<br/>and daily at 01:00 UTC"]

    subgraph ci["ci.yml"]
        direction LR
        checks["<b>job checks</b><br/>matrix: platform-api, agent-runtime, e2e<br/>1. uv sync<br/>2. ruff check and ruff format<br/>3. pyright<br/>4. lint-imports, platform-api only<br/>5. contracts are current<br/>6. unit tests in the image, with PostgreSQL<br/>and, for platform-api, the Cosmos DB emulator<br/>7. the emulator kept its pinned packages<br/>8. build the runtime image<br/>9. mock GitHub and mock model tests, e2e only"]
        portaljob["<b>job portal</b><br/>1. npm ci<br/>2. typecheck<br/>3. lint<br/>4. unit tests<br/>5. build<br/>6. nginx render test"]
        scans["<b>job scans</b><br/>1. SAST with Semgrep<br/>2. keep the Semgrep report<br/>3. secret scan with gitleaks"]
        e2e["<b>job e2e</b>, push or by hand only<br/>1. scripts/e2e.sh: API tests, then the browser suite<br/>2. keep the logs, screenshots and video<br/>3. DAST: scripts/dast.sh, OWASP ZAP<br/>4. keep the ZAP reports<br/>5. load test: scripts/load.sh, k6<br/>6. keep the k6 summary"]
    end

    subgraph deploywf["deploy.yml"]
        direction LR
        deploy["<b>job deploy</b>, environment azure-dev<br/>1. Terraform 1.16.5 and Azure sign-in with OIDC<br/>2. connect to the remote state<br/>3. create the registry<br/>4. copy the public images, build and push ours<br/>5. create the database roles: the db-init job<br/>6. plan, check and apply everything, guarded<br/>7. run the bootstrap job<br/>8. say where the Portal is"]
    end

    subgraph evalswf["evals.yml"]
        direction LR
        evals["<b>job evals</b>, environment evals<br/>1. score the configured AI models<br/>on the golden set: scripts/evals.sh<br/>2. keep the results"]
    end

    subgraph infrawf["infra.yml, only when infra/ or a deploy file changes"]
        direction LR
        infra["<b>job infra</b><br/>1. infra/scripts/check.sh: terraform fmt,<br/>validate under Terraform and OpenTofu,<br/>the variable cases, tflint, Checkov<br/>2. actionlint on every workflow<br/>3. keep the check output"]
    end

    subgraph pstackwf["pstack-playbooks.yml"]
        direction LR
        pstack["<b>job pstack-playbooks</b><br/>1. read the locked pstack version<br/>2. fetch it and check it is the reviewed commit<br/>3. check the team's playbooks against it"]
    end

    azure[("Azure: rg-wab-dev")]
    artifacts[("Run artifacts: Semgrep report, e2e logs,<br/>ZAP reports, k6 summary, infra checks, eval results")]

    pr --> checks
    pr --> portaljob
    pr --> scans
    push --> e2e
    pr --> infra
    hand --> deploy
    hand --> evals
    daily --> pstack
    deploy --> azure
    scans -.-> artifacts
    e2e -.-> artifacts
    infra -.-> artifacts
    evals -.-> artifacts

    classDef job fill:#ffffff,stroke:#111827,color:#111
    classDef trigger fill:#e8f0fe,stroke:#1a56db,color:#111
    classDef ext fill:#f3f4f6,stroke:#6b7280,color:#111
    class checks,portaljob,scans,e2e,deploy,evals,infra,pstack job
    class pr,push,hand,daily trigger
    class azure,artifacts ext
```

The private repository is billed per job, rounded up to a whole minute, so the stages of `ci.yml` are steps inside four jobs, not one job each. The four jobs of `ci.yml` run side by side. The pipeline's results for the rebuilt app are in `docs/evidence/dast/2026-11-rebuild/`, `docs/evidence/load-test/2026-11-rebuild/` and `docs/evidence/unit-tests/2026-11-rebuild/`.

## Sequence: set up a workflow

An Operator uses New workflow's four steps: describe it, check what the Planner understood, choose when it runs, and turn it on. The Planner reads the task through the AI model connected in Settings. Nothing is saved until Turn it on, except a draft the Operator chooses to keep.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant P as Portal, New workflow
    box platform-api
        participant B as Use case builder
        participant O as Orchestration
    end
    participant AR as Agent runtime, Planner
    participant AI as AI model gateway

    Note over Op,P: Step 1. Describe it
    Op->>P: types the task in plain English, presses Next
    P->>B: POST /api/v1/builder/understand {text}
    B->>O: CardPlanning.understand(task)
    O->>O: read the connected model and decrypt its key
    alt a model is connected
        O->>AR: POST /v1/planner/understand {task, model}, X-Agent-Key
        AR->>AI: one request: read the task back in parts
        AI-->>AR: the parts, each understood, missing or can't do
        AR-->>O: the parts, held to the tools that exist
        O-->>B: the parts
    else no model, or no answer in 10 seconds
        O-->>B: NoModel or RuntimeDown
        Note over B: falls back to the starter workflows
    end
    B-->>P: 200 the parts, or "belongs on the Software watchlist", or the starters

    Note over Op,P: Step 2. Check what I understood
    P-->>Op: one sentence of coloured parts, Next stays off while a part is unclear
    opt the Operator changes a part
        Op->>P: edits the part
        P->>B: POST /api/v1/builder/understand {text: that part}
        B-->>P: 200 the part, checked again
    end
    P->>B: POST /api/v1/builder/plan {task}
    B->>O: CardPlanning.choose(task, the agent library)
    O->>AR: POST /v1/planner/choose {task, library, model}
    AR->>AI: which saved agents fit the task
    AI-->>AR: use one, use several, a new agent, or can't do
    AR-->>O: the choice
    O-->>B: the choice
    opt no saved agent fits
        B->>O: CardPlanning.draft(task)
        O->>AR: POST /v1/cards/draft {task, model}
        AR->>AI: draft an agent card from the tools that exist
        AR-->>O: the drafted card
        O-->>B: the drafted card, checked against the tools
    end
    B-->>P: 200 the plan, each step marked reads, no system access, or changes data and waits for a yes

    Note over Op,P: Step 3. When and who
    Op->>P: picks the day and the time, Singapore time

    Note over Op,P: Step 4. Turn it on
    Op->>P: names it, presses Turn it on
    opt the Planner drafted a new agent
        P->>B: POST /api/v1/agent-cards {the card}
        B-->>P: 201 card_id
    end
    P->>B: POST /api/v1/agent-use-cases {name, instruction, agents, schedule}
    B->>B: check each agent and its values, then one transaction:<br/>builder.use_cases, use_case_versions and use_case_cards rows
    B->>O: ScheduleBook.save: orchestration.schedules, owner is the Operator
    B-->>P: 201 {use_case_id, version: 1}
    opt it was a draft
        P->>B: DELETE /api/v1/drafts/{draft_id}
    end
    P-->>Op: /new/done/{use_case_id}: "Your workflow is on", with the next run

    Note over Op,P: Save and close, at any step
    Op-)P: Save and close
    P-)B: PUT /api/v1/drafts/{draft_id} {step, content}
```

When the Planner reads a release check in step 1, it answers "belongs on the Software watchlist", and the page offers to open the Software watchlist instead of making a look-alike workflow (design note, section 4).

## Sequence: a watchlist check runs to the approval gate in Teams

This is the recorded run in `contracts/fixtures/runs/watchlist.json`, drawn against the real routes. n8n carries the run in two legs. The work leg ends when the approval request opens, and the act leg starts only after the Approver approves (ADR 0007). Each `events:` line names the activity events written in that transaction. The live activity view receives them in `seq` order, as the next diagram shows.

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
        participant TS as Practice Teams
        participant WG as Safety checker and write gateway
        participant J as Practice Jira
    end
    participant N as n8n
    participant AR as Agent runtime
    participant GH as GitHub

    Op->>P: Software watchlist, Check now
    P->>B: POST /api/v1/use-cases/{use_case_id}/runs, Idempotency-Key
    B->>O: start_run(RunSpec with the watched software)
    O->>M: one transaction: run Pending, outbox start_leg(work)<br/>events: run_created, leg_dispatched
    B-->>P: 201 {run_id, events_url}

    Note over O,N: Work leg
    O->>N: the outbox tick: POST /webhook/run/work {run_id}
    N-->>O: 202 {run_id, n8n_execution_id}
    N->>O: node "Run agents": POST /internal/v1/runs/{run_id}/steps/run_agents<br/>X-Step-Key, X-N8N-Execution
    O->>M: Pending to Working. events: step_started
    O->>AR: POST /v1/tasks, X-Agent-Key<br/>{task_id, instruction, inputs, callback}
    Note over AR: The Planner brings in the Version checker
    loop each watched software
        AR->>GH: GET /repos/{owner}/{repo}/releases
        GH-->>AR: releases
    end
    AR--)M: POST /internal/v1/runs/{run_id}/agent-events, X-Callback-Token<br/>agent_joined, agent_message, agent_step_started, agent_step_finished
    AR-->>O: 200 TaskFinished {summary, proposed tickets, events}
    O->>M: proposal with its digest, Working to Proposed<br/>events: write_action_proposed, step_finished
    O-->>N: 200 {proceed: true, outcome: proposed}
    N->>O: node "Ask for approval": POST .../steps/ask_approval
    O->>M: approval request with its parties, Proposed to AwaitingApproval,<br/>outbox announce. events: approval_requested, step_finished
    O-->>N: 200 {proceed: false, outcome: approval_opened}. The work leg ends

    Note over O,TS: Approval gate in Teams
    O->>TS: the outbox tick posts the message, with a link to the run page
    O->>M: events: approval_announced
    Ap->>P: Teams button: the message and its proposal
    P->>O: GET /api/v1/teams-stub/messages, then GET /api/v1/approvals/{approval_id}
    O-->>P: the actions, the digest, the steps, you_can_decide
    Ap->>P: opens the link to /runs/{run_id}, presses Approve
    P->>O: POST /api/v1/approvals/{approval_id}/decisions<br/>{step: 0, verdict: approve, digest}
    Note over O: decide() checks the Approver role, that they are not a party,<br/>the step in order, and the digest they saw
    O->>M: decision, AwaitingApproval to Acting, outbox start_leg(act)<br/>events: approval_decided, leg_dispatched
    O-->>P: 201 {status: approved}

    Note over O,N: Act leg
    O->>N: the outbox tick: POST /webhook/run/act {run_id}
    N->>O: node "Do write action": POST .../steps/write_action
    O->>M: events: step_started
    O->>WG: check(): Acting for this proposal, approval approved,<br/>digest matches, connector and operation registered
    WG-->>O: AuthorizedWrite. Anything else is Deny, event write_action_denied
    loop each proposed ticket
        O->>WG: WriteGateway.execute, one write key per action
        WG->>J: create the ticket
        J-->>WG: MOCK-143
        O->>M: events: write_action_done
    end
    O->>M: Acting to Succeeded. events: step_finished, run_succeeded
    O-->>N: 200 {proceed: true, outcome: written}
```

If the Approver started the run, owns the workflow or retried it, the run page shows a lock and the decision route answers 403. If an Approver declines, the run ends with nothing written, and the event is `run_rejected`.

## Sequence: the live activity view

How an activity event gets from the transaction that writes it to the run page. PostgreSQL sets the order and keeps every event. The copier copies to Cosmos DB, then wakes the stream. The stream reads Cosmos DB up to the copied mark and sends each event once, in order.

```mermaid
sequenceDiagram
    autonumber
    actor V as Operator or Approver
    participant P as Portal, run page
    box platform-api
        participant S as Run monitoring, event stream
        participant L as ActivityLog
        participant C as Copier
    end
    participant PG as PostgreSQL
    participant CD as Cosmos DB, run_events

    V->>P: opens /runs/{run_id}
    P->>S: GET /api/v1/runs/{run_id}/events, Accept text/event-stream
    S->>S: who is asking, from the People list,<br/>then wait for this run's wake-ups. platform-api listens on run_events_copied
    S->>CD: SELECT * FROM c WHERE c.seq > 0 ORDER BY c.seq, partition run_id
    CD-->>S: items 1 to n
    S-->>P: id: 1 ... id: n, one frame per event

    Note over L,PG: Somewhere else, a state change and its events
    L->>PG: one transaction: advisory lock on the run,<br/>INSERT monitoring.run_events seq n+1, NOTIFY run_events
    PG--)C: a notice on run_events, naming the run
    C->>PG: lock the run's copy, read rows after the copied mark
    C->>CD: upsert item id n+1, runId run_id
    C->>PG: monitoring.run_events_copied: seq n+1,<br/>NOTIFY run_events_copied with the run and n+1
    PG--)S: a notice on run_events_copied, naming the run and n+1
    S->>CD: items after n
    CD-->>S: item n+1
    S-->>P: id: n+1
    P-->>V: the next agent speaks, the run line moves on

    loop while the page is open
        S-->>P: a keep-alive comment when nothing happens
        S->>S: every minute: is this person still on the People list?
    end

    Note over P,S: The connection drops, or platform-api restarts
    P->>S: GET .../events with Last-Event-ID: n+1
    S->>CD: items after n+1
    S-->>P: only the events it missed
    Note over S,PG: While the copy is behind, the stream reads PostgreSQL,<br/>so the page never waits on Cosmos DB
```

The events page, `GET /api/v1/runs/{run_id}/events` with `Accept: application/json`, and the AI troubleshooter read the same way, once. With `ACTIVITY_READER=postgres`, for a place without Cosmos DB, every reader reads `monitoring.run_events` and wakes on `run_events` instead.

## Sequence: a run stops, then the Operator retries

This is the recorded run in `contracts/fixtures/runs/failure.json`. GitHub answers 503 three times, so the Version checker gives up and the run fails with a reason marked retryable. The agent runtime reports the failure, and platform-api fails the run and still answers n8n with `200 {proceed: false}`, so n8n's error workflow does not fire for an agent failure. The second branch shows the other path, where an n8n node fails and the error workflow reports it.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant P as Portal
    box platform-api
        participant B as Use case builder
        participant M as Run monitoring
        participant O as Orchestration
    end
    participant N as n8n
    participant AR as Agent runtime
    participant GH as GitHub

    Note over Op,GH: The run starts as in the watchlist check. events: run_created, leg_dispatched, step_started
    N->>O: node "Run agents": POST /internal/v1/runs/{run_id}/steps/run_agents
    O->>AR: POST /v1/tasks {task_id: run_id/work/1, ...}
    alt the agent fails (the recorded run)
        loop 3 tries
            AR->>GH: GET /repos/{owner}/{repo}/releases
            GH-->>AR: 503 Service Unavailable
            AR--)M: agent-events: agent_message
        end
        AR--)M: agent-events: agent_step_finished, agent_failed
        AR-->>O: 200 TaskFailed {error: {type, message, retryable: true}, events}
        O->>M: Working to Failed, retryable, cancel the outbox<br/>events: step_finished, run_failed
        O-->>N: 200 {proceed: false, outcome: failed}. n8n marks its execution a success
    else an n8n node fails
        N->>N: the Error Trigger starts the "run_failure_reporter" n8n workflow
        N->>O: node "Report failure": POST /internal/v1/workflow-failures<br/>{execution_id, workflow, last_node, message, execution_url}
        O->>M: map the execution to its run, Failed, retryable<br/>events: run_failed
    end
    Note over O: If n8n never calls back, the state's deadline fails the run as timed out

    Op->>P: opens Home
    P->>B: GET /api/v1/home
    Note over B,M: Home lists the stopped run with the reason in its run_failed event.<br/>The AI troubleshooter has one rule for each failure reason
    B-->>P: 200 a stopped row {reason, retryable, advice}
    P-->>Op: GitHub was unavailable. You can retry.
    opt the Operator opens the run page
        P->>M: GET /api/v1/runs/{run_id}/troubleshoot
        M-->>P: 200 {failure, advice: {explanation, likely_cause, suggested_action: retry}}
    end

    Op->>P: Retry
    P->>O: POST /api/v1/runs/{run_id}/retry
    Note over O: Needs the Operator role and a retryable failure.<br/>The person who retries becomes a party, so they cannot approve this run
    O->>M: Failed to Pending, attempt 2, outbox start_leg(work) no sooner than 3 s<br/>events: run_retried, leg_dispatched
    O-->>P: 202 {state: pending}
    P-->>Op: the run page, live
    O->>N: the outbox tick: POST /webhook/run/work {run_id}
    N->>O: node "Run agents": POST .../steps/run_agents
    O->>AR: POST /v1/tasks {task_id: run_id/work/2, ...}
    Note over Op,GH: A new task_id means the agents really run again. From here the run follows the watchlist check
```

A failure in the act leg retries differently. The run goes back to `Acting`, not `Pending`, so nobody has to approve again. The write gateway finds any write it already recorded as `done` and returns it instead of creating the ticket a second time.
