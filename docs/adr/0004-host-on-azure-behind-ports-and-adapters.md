---
status: proposed
---

# Host on Azure first, behind ports and adapters

We host on Azure: Container Apps, Static Web Apps, PostgreSQL, Key Vault and Application Insights, plus Azure OpenAI if the model tests pick it. The team has Azure for Students credits, and the sponsor already works in Microsoft's stack through Teams. NCS may still want the platform on AWS later, so domain code never calls an Azure SDK directly. Each cloud service sits behind a port that our code owns, and an adapter for that port talks to Azure.

## Considered options

- **AWS first.** We have no AWS credits, and Teams approvals keep us in Microsoft's stack anyway.
- **Cloud-neutral Kubernetes.** It is portable, but a five-person part-time team would spend its time running clusters instead of building the product.

## Consequences

- A move to AWS means new adapters, not changes to domain code.
- Tests run against local or fake adapters, so they need no cloud account.
- The infrastructure-as-code tool (Terraform or Bicep) is still open and gets its own ADR.
