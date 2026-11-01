---
status: proposed
---

# Reach Jira through one REST adapter, and let the practice Jira speak Jira's API

The operator asked on 1 Nov 2026 that every practice copy is built "as if it is linking with the actual app itself", so moving to the real one has no friction. Today the practice Jira is a table inside platform-api with our own routes and fields. Nothing speaks Jira's REST API, and there is no real adapter. So the move to a real Jira would mean new code that has never run, and the practice copy hides what a real Jira does: issue types, required fields, rate limits and its own errors. ADR 0005 asked for a mock adapter and a real adapter for every outside system. This ADR changes that for Jira: one real adapter, and two Jiras it can talk to.

The operator chose "Both, switchable". NCS may run Jira Data Center inside DevNet or use Jira Cloud (`docs/design/devnet-move.md`, question 3), so the platform speaks both.

## Decision

**One port, one adapter.** Orchestration gets a `JiraPort`. It can create an issue, read one, search, say which keys are Done, find an issue by our write key, and move an issue to Done. One adapter, `JiraRestAdapter`, speaks Jira's own REST API:

| | Data Center | Cloud |
|---|---|---|
| API | `/rest/api/2` | `/rest/api/3` |
| Search | `GET /rest/api/2/search?jql=` | `GET /rest/api/3/search/jql` (the old `/rest/api/3/search` is retired) |
| Description | wiki markup | Atlassian Document Format (ADF) |
| Sign-in | a personal access token, sent as `Bearer` | an email and an API token, sent as `Basic` |

The write gateway's Jira connector, the watchlist's Done check and the agents' Jira reads all go through the port.

**Settings.** Switching to a real Jira takes three settings and nothing else:

| Setting | Meaning | Default |
|---|---|---|
| `JIRA_BASE_URL` | the Jira's address, such as `https://jira.example.com` | empty, which means the practice Jira |
| `JIRA_API_FLAVOR` | `datacenter` or `cloud` | `datacenter` |
| `JIRA_API_TOKEN` | the token. A Key Vault secret on Azure, `.env` locally | empty |
| `JIRA_EMAIL` | the account's email, for Cloud only | empty |
| `JIRA_ISSUE_TYPE` | the issue type of each new ticket | `Task` |
| `JIRA_BROWSE_URL` | where people open a ticket, with `{key}` where the key goes | `{JIRA_BASE_URL}/browse/{key}`, or `/jira/{key}`, the Portal's Practice Jira page, for the practice Jira |
| `WATCHLIST_JIRA_PROJECT` | the project the watchlist raises tickets in | `MOCK` |
| `PRACTICE_SYSTEMS` | `on` mounts the practice Jira's routes. `off` is only for use together with a real Jira: with no `JIRA_BASE_URL` it refuses to start, because there would be no Jira | `on` |

**The practice Jira speaks the same API.** It becomes a small server that answers the part of Jira's REST API we use, for both flavors:
- create an issue, and read one;
- say which account a token is (`/myself`);
- search, with a subset of JQL: `project`, `key in`, `labels`, `text ~`, `statusCategory` and `resolutiondate`, joined by `AND`, with `OR` inside brackets;
- read a project;
- list an issue's transitions, and make one. This replaces "Mark done";
- `/browse/{key}`.

It checks the `Authorization` header, answers errors in Jira's own shape (`{"errorMessages": [...], "errors": {...}}`), and a test can tell it to answer 429 or 503. It lives in platform-api as its own package, `platform_api.practice_jira`, under `/practice-jira/rest/api/...`. It imports nothing from the bounded contexts, and none of them import it, which an import rule checks. The adapter calls it over HTTP at `PLATFORM_INTERNAL_URL` plus `/practice-jira`, exactly as it calls a real Jira. Its token is derived from `CALLBACK_SIGNING_KEY`, so it needs no new secret. Its tickets stay in the table `orchestration.mock_jira_tickets`. Its routes are mounted only while `PRACTICE_SYSTEMS` is `on` and `JIRA_BASE_URL` is empty. So Azure needs no new container, and a deploy with a real Jira serves no practice routes. On Azure, platform-api's ingress is external, so the practice Jira can be reached from outside, but every REST call needs its token.

**What the adapter does that the practice table hid.**
- **No duplicate after a retry, and no trust in Jira's labels.** Jira has no idempotency key. The gateway already records each write before and after it calls the connector (ADR 0008). The Jira connector keeps its own record too, in `orchestration.jira_writes`. Before it calls Jira, it notes that it has begun. After Jira's 201, it notes the ticket's key. A retry trusts that record and asks Jira nothing. If Jira answered with a 4xx, nothing was made, so the note is dropped and the next try starts fresh.
  - Our write key also goes on the ticket as a Jira label, but only as a hint for one case: a crash after Jira's 201 and before our note. Then the note says a try began and has no key, so the connector looks for the label.
  - Anyone who can edit tickets in the project can add a label. So a found ticket counts as this write's only when all of these hold:
    - Jira's `creator` field is the platform's own account. The reporter never counts, because anyone with Jira's "Modify Reporter" permission can change it, and a ticket with no creator is not ours. The platform learns its account from Jira's `/myself`, so this needs no setting.
    - It was made after the write began, allowing two minutes for clock drift.
    - Our record does not give it to another write.
    - It carries no other write's label.
    - Its summary is the one this write would send.
  - Any other ticket with the label stops the write for good, with a message that a person needs to check it. So neither a ticket someone planted, nor one of ours relabelled by hand, can stand in for an approved write.
- **Errors that can't be fixed by trying again stop.** Jira's 400, 403 and 404 mean the request is wrong: a missing project, a required field, no permission. The run fails with "Start a new run", the AI troubleshooter says to check Jira's settings, and the Portal says what Jira said. 401 means the token is wrong or expired, and 429 and 5xx mean Jira is busy or down. A read waits for `Retry-After`, at most 5 seconds, and tries twice more. A create is tried again only after a 429, because Jira did not act on it. After any other failure the run fails with "You can retry". A retry looks for the label first, and a retry after a new token needs no second approval.
- **Model text can't become markup.** A ticket's title is plain text in both flavors. Its body is model text, so the adapter never lets Jira read it as markup. For Cloud each paragraph is an ADF text node, which Jira shows as written. For Data Center the body goes inside a `{noformat}` block, and any `{noformat` inside the text is broken up first.
- **Jira's statuses vary.** The adapter reads `statusCategory`, not the status name. Done is the category `done`, and anything else counts as To Do for the agents.
- **Search means what it says.** The agents' text search matches any word of three or more letters or digits. The adapter writes that as `(text ~ "a" OR text ~ "b")`, because Jira's `text ~ "a b"` may need every word.
- **A key that no longer exists.** If Jira refuses a `key in (...)` search because a key is gone, the adapter reads those tickets one at a time and skips any that answer 404.

**Project and ticket keys take Jira's real shapes.** A project key is a capital letter, then 1 to 254 capital letters, digits or underscores, such as `MOCK` or `AB_1`. A ticket key is a project key, a dash and a number from 1. platform-api, the agent runtime's tools, the Portal and Terraform check the same shape.

**The agents still talk to our platform, not to Jira.** Agents stay reusable and hold no Jira key (ADR 0023). The agent runtime's setting is renamed from `PRACTICE_JIRA_URL` to `PLATFORM_JIRA_URL`, and its reads go to `/internal/v1/runs/{run_id}/jira/tickets`. The runtime refuses to start if that address is not one of `CALLBACK_ALLOWED_ORIGINS`, because it sends the task's callback token there. It also refuses the old name, so a stale setting can't turn the Jira tools off without a word. Behind that route, platform-api checks the token and the card's projects as today, then reads through the `JiraPort`.

**The watchlist's project is a setting.** `WATCHLIST_JIRA_PROJECT` names the project, `MOCK` for the practice Jira. When platform-api starts and the watchlist's current version names another project, it saves a new version with the setting's project, as a change to the list would. Until the Portal can set the project, the setting wins.

**Each ticket links to where it lives.** The `write_action_done` event keeps `external_reference`, the ticket key, and adds `url`, the ticket's browse address. For the practice Jira that address is the Portal's own Practice Jira page, `/jira/{key}`, a path the Portal opens in place. The Portal prefers this address. For a ticket key with no event behind it, such as the watchlist's open ticket, it uses its own `JIRA_BROWSE_URL`.

## What stays the same

The approval gate, the safety checker and `write_actions.check` do not change. Every write still needs its approval first, and only an `AuthorizedWrite` reaches the gateway. The gateway still records each write before and after it calls Jira. The `JiraPort` is reached only through the gateway's connector for writes, and through reads that need no approval. n8n still holds no Jira key (ADR 0026).

## Considered options

- **The practice Jira in its own container, like `mock-github`.** It would be the most like a real Jira, with its own address. But it is a new service: a new image, Terraform for a new Container App on Azure, and more of the tight Docker disk. Inside platform-api, it is reached over HTTP with the same paths and headers, so the adapter can't tell the difference.
- **Keep the table, and write the real adapter when DevNet access comes.** Less work now. But the adapter would first run against a real Jira during the move, which is the friction the operator asked us to remove.
- **One adapter for each flavor.** Each would be simpler. But most of the code is the same, and two adapters would drift apart.
- **The `jira` package from PyPI.** It knows both flavors. But it is a new dependency, it blocks while it waits, and the practice server would still be ours to write. `httpx` is already in platform-api.
- **Find our ticket by an issue property instead of a label.** A property is hidden from people. But JQL can search a property only when an app indexes it, and labels are searchable on every Jira.

## Consequences

- **A contract suite proves the switch.** One test suite runs the adapter against a target. In CI the target is always the practice server, in both flavors. When `JIRA_CONTRACT_URL` is set, with its flavor, token and project, the same tests run against a real sandbox. Sanitised real answers live in `contracts/fixtures/jira/`, and the practice server's answers are checked against them.
- **The deploy gains settings, not resources.** Compose and Terraform pass the new settings, and Key Vault gets a slot, `jira-api-token`, which is empty by default so the practice Jira is used. The Container Apps change in place.
- **NCS has to tell us** whether Jira is Data Center or Cloud and which version, how the service account signs in, the issue type and any required fields, whether labels are allowed, and which status means Done. These are question 3 in `docs/design/devnet-move.md`.
- **Jira Cloud's search can lag behind a create** for a few seconds. The gateway waits 30 seconds before it treats a write as lost, so the label search still finds a ticket created just before a crash.
- **A deploy with a real Jira and `PRACTICE_SYSTEMS` on** still serves the practice Teams, but not the practice Jira. The Portal learns nothing from `PRACTICE_SYSTEMS`. It hides its Practice Jira page when its own `JIRA_BROWSE_URL` is set, and Terraform sets that whenever `JIRA_BASE_URL` is set. Compose leaves it to the person who sets a real Jira.
- **The practice table stays in the orchestration schema,** so no database role changes. Its rows gain labels, an issue type and the account that made them, and its run columns may be empty for a ticket made by hand. The connector's record is a new table, `orchestration.jira_writes`, in the same schema.
- **Confluence can follow the same pattern** when it gets its ADR (ADR 0023): a port, one REST adapter, and a practice server that speaks its API.
