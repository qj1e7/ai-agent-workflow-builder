---
status: proposed
---

# Keep the activity log in Azure Cosmos DB for NoSQL

The rubric asks for a relational database and a NoSQL database, and the first presentation must show the NoSQL design and its collections. ADR 0011 kept the activity log in PostgreSQL, behind a port, until the team picked a store, and named the log as the first candidate. No store has been compared or tried. The log fits a document store well:

- Each activity event is a small document with a kind, an actor and a data block that differs by kind. Today that data block is already a `jsonb` column.
- Events are only ever added, never changed.
- Almost every read asks for one run's events in order, after a given number.
- `AGENTS.md` requires a record of every agent action with who approved it, so the log only grows.

So the activity log's readers move to **Azure Cosmos DB for NoSQL**, behind the same port, and PostgreSQL keeps the write side:

- **One container, `run_events`, in a database `activity`, partitioned by run id.** Each item is one activity event, with the run id, its sequence number, the time, the actor, the kind, the summary, the data and the dedupe key. These are today's `monitoring.run_events` columns. The item id is the sequence number written as text, and queries sort on the number field `seq`, not on the id. Reading a run's events after a number is a query inside one partition.
- **PostgreSQL still sets the order and catches repeats.** Orchestration keeps writing each event in the same transaction as the state change it reports. `ActivityLog.append` takes the next sequence number from the rows already in `monitoring.run_events`, and the table's unique dedupe key drops a repeated callback. Both depend on the rows staying, so PostgreSQL keeps every event. The table stays append-only, with the same grants as today.
- **One copier per run, in order.** Run monitoring copies each new event to Cosmos DB. For each run, one copier at a time holds a lock on that run, copies its events in sequence order, and records the highest number it has copied. The copy uses the run id and sequence number as the key, so copying an event twice writes the same item twice and changes nothing.
- **Readers read Cosmos DB.** The live view's stream, its replay from `Last-Event-ID`, the AI troubleshooter and the activity history all read Cosmos DB. After each copy, run monitoring wakes the stream with PostgreSQL's `NOTIFY`, naming the run and the highest number copied. A reader reads up to that number. If it finds a gap, it stops before the gap and waits for the next wake-up. The account uses Strong consistency, so a reader on any replica sees an item as soon as its copy is done. Strong consistency is offered for an account in one region. It doubles the cost of each read, and at our volume the free tier still covers it. That last point is an estimate, not a measurement.
- **Run state and counts still come from PostgreSQL.** The runs list and a run's state read orchestration's tables, as today. The stream catches up within the copier's delay.
- **Locally, Compose runs the Cosmos DB emulator.** We use the Linux emulator image `vnext`, pinned by digest. It runs on Apple Silicon and on CI's x86 runners, and it supports change feed and TTL.
- **On Azure, Terraform creates the account** with `azurerm_cosmosdb_account` and `free_tier_enabled`. The free tier covers 1000 RU/s and 25 GB for the life of the account, one account per subscription. Serverless has no free tier, but in Southeast Asia it costs about $0.285 for each million request units. By our estimate, a few thousand events a day comes to under a dollar a month either way. platform-api reaches the account with its managed identity and a Cosmos DB data role, as it reaches Key Vault today. Locally it uses the emulator's fixed key.

Facts above were checked on 29 Oct 2026 against Microsoft's pages for [the free tier](https://learn.microsoft.com/en-us/azure/cosmos-db/free-tier), [serverless](https://learn.microsoft.com/en-us/azure/cosmos-db/serverless), [the Linux emulator](https://learn.microsoft.com/en-us/azure/cosmos-db/emulator-linux) and [Terraform's account resource](https://github.com/hashicorp/terraform-provider-azurerm/blob/main/website/docs/r/cosmosdb_account.html.markdown), and against the Azure retail prices API.

## Considered options

- **Keep the log in PostgreSQL only (ADR 0011).** It is the simplest option, but the rubric requires a NoSQL store.
- **Delete each event from PostgreSQL once it is copied,** so Cosmos DB holds the only copy. Less duplicate data. But the next sequence number and the dedupe check both read the rows in PostgreSQL. A run that waits more than the pruning delay for a yes would start again at 1, overwrite its own history in Cosmos DB, and let a repeated callback through. Keeping a separate counter and key table would fix that, at the cost of more code in the path that every event takes.
- **Move the whole log, writes included, to Cosmos DB.** No copier would be needed. But a run's state change and its events would commit in two stores, so a crash between them could show a run as waiting with no event saying why.
- **Azure DocumentDB, the MongoDB-compatible service once called Cosmos DB for MongoDB vCore.** A move to AWS would need only a new connection string, to Amazon DocumentDB or MongoDB Atlas, and its local image runs on Apple Silicon. But its free tier is not offered in Southeast Asia, and the cheapest paid size costs about $18 a month, most of a student's $100 yearly credit.
- **Cosmos DB for MongoDB, the request-unit version.** The free tier applies. But the only emulator with the MongoDB API does not run on Apple Silicon. A plain `mongo` container would hide the features this version lacks, such as multi-collection transactions.
- **MongoDB Atlas's free cluster.** It is not offered on Azure in Singapore, only on AWS in Singapore or on Azure in Hong Kong. It is limited to 0.5 GB and 100 operations a second, and it adds a second cloud account and vendor.
- **Put other data in the NoSQL store as well,** such as agent card versions or the copies of published n8n workflow versions (ADR 0027). Both may move later. The log alone shows the design the rubric asks for, with the least to change.

## Consequences

- **This changes ADR 0011.** The `ActivityLog` port stays, so orchestration and the live view do not change how they call it. A new adapter reads Cosmos DB, and the copier runs inside run monitoring. The copier needs a small table of its own for the highest number copied per run. It needs no new rights on `monitoring.run_events`.
- **Check the student subscription first.** Community answers on Microsoft Q&A report that Azure for Students subscriptions can only deploy to a short list of regions, sometimes without Southeast Asia. No Microsoft page says whether the free tier applies to them. Before the deploy PR, the team reads the subscription's "Allowed resource deployment regions" policy and creates one free-tier account by hand to confirm it.
- **The emulator is not Azure.** The `vnext` emulator is still labelled preview. It supports only the NoSQL API, does not check keys, does not count request units, and runs as one replica, so it can't show a stale read. CI tests the adapter against the emulator, and the deploy PR checks the same reads against Azure.
- **The PostgreSQL reader stays.** A setting picks whether readers use Cosmos DB or PostgreSQL, and CI tests both. A place without Cosmos DB, such as a DevNet that does not allow it, still runs, because PostgreSQL keeps every event ([the DevNet move](../design/devnet-move.md)).
- **AWS needs a new adapter.** Cosmos DB for NoSQL has no AWS twin that speaks the same protocol. A move to AWS would add a DynamoDB adapter behind the same port. ADR 0004 keeps that move possible but does not plan it.
- **A new dependency enters platform-api,** the `azure-cosmos` Python package, pinned at a version at least two weeks old.
- **Run monitoring is the cheapest context to move into its own container** (ADR 0010), now that it owns the copier and reads another store. That split also answers the rubric's microservices question, and it can wait until after the first presentation.
- **The first presentation shows the container, its partition key and an example item.** [The domain model](../design/rebuild-domain-model.md) draws them.
