---
status: proposed
---

# Ship the builder, orchestration and run monitoring in one container for now

The rubric asks for microservices with DDD, and a reader may expect one service per bounded context. But an approval decision, the run's state change and the activity event that reports it must commit together, or the live view and the run can disagree. So for the walking skeleton, the use case builder, orchestration and run monitoring ship as one image, `platform-api`. The agent runtime ships as its own image, because it must run with no database and be reusable in NCS's agent hub. The boundaries are enforced, not just drawn. Each context has its own PostgreSQL schema and database role, so a query across contexts fails with a permission error. The one named exception lets orchestration's role insert into run monitoring's activity log, so a state change and its events commit together. Import-linter, a CI tool that fails the build on forbidden imports, stops one context from importing another's internals.

## Considered options

- **One service per context from the start.** It matches "microservices" most literally. It needs an outbox between every pair of services and gives up the single transaction between a decision and its state change, before the first demo.

## Consequences

- The skeleton has two images of our own, plus n8n, PostgreSQL and the Portal.
- Splitting a context out later means replacing an in-process call with HTTP and an outbox. Run monitoring is the cheapest to split first, because agents already reach it over HTTP.
- The professor may read one container as "not microservices". The design document names this risk.
