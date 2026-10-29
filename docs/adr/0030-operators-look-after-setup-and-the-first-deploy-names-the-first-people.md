---
status: proposed
---

# Operators look after setup, and the first deploy names the first people

The platform needs setting up before anyone can use it: an AI model, keys for GitHub, Jira and Teams, and the people who use it. The team agreed on two roles only, Operator and Approver, and neither the glossary nor any ADR says who does setup. ADR 0022 lets Operators connect the AI model and asks an Approver to confirm a new address. The prototype goes further. Settings has four tabs, AI model, Connections, People and roles, and AI usage, and only Operators change them. Everyone can open Settings, and an Approver-only person sees it read-only. The sponsor's reason is in the October usability notes: a non-technical person should be able to fix an expired key, add a colleague and keep the AI cost in check.

Setup splits into two layers, and only one of them can be an Operator's job.

**Deploy-time setup needs cloud and tenant rights.** A technical person does it once per environment, following a runbook:
- registering the Entra apps (ADR 0018);
- creating the Azure resources with Terraform, and the secrets in Key Vault, `SETTINGS_ENCRYPTION_KEY` included;
- creating n8n's owner account;
- later, registering the Teams app.

This person needs no role in the app.

**In-app setup is the Operators' job.** Operators connect the AI model (ADR 0022), replace connection keys, add people and change roles (ADR 0029), and later set the AI usage limit. Approvers confirm the risky changes, which are a new Approver and a new AI model address. Tool approvals join them in Phase 2. Keys follow ADR 0022's pattern: they are write-only, encrypted with `SETTINGS_ENCRYPTION_KEY`, and the Portal shows only their last two characters. Every change is recorded with who made it.

**The first deploy names the first people.** An empty People list has no Operator to add anyone, and no Approver to confirm a new Approver. So two deploy settings, `FIRST_OPERATOR` (one email) and `FIRST_APPROVERS` (two emails), seed the list. platform-api applies them only while the People list is empty, in one transaction that holds a lock, so two replicas starting together seed once. It records them in the settings history as set by the deploy. After that it ignores them, so a later deploy can't hand out roles. `FIRST_APPROVERS` must name two different people, because the prototype requires at least two Approvers, so nobody has to approve their own work. The first Operator may also be one of them.

**One confirmation mechanism serves every setup change that needs a second person.** The prototype asks someone else to say yes in five places. Two are run approvals: a run's proposal, and a run of a workflow made in n8n before it names Approvers. They keep their own rules in `orchestration/approvals.py`. The other three are setup changes:
- a new Approver;
- a new AI model address;
- a new tool, in Phase 2.

Each of the three is one kind of record, a confirmation. It names what would change and who asked. Anyone with the Approver role may confirm it, except the asker and the person it is about. It is decided once, and the decision is recorded. ADR 0022's model address check becomes the first user of this record.

## Considered options

- **An Admin role.** It is clear who sets up. But it is a third role that the sponsor did not ask for, and one admin becomes the person everyone waits for. The prototype showed setup without one.
- **A technical person sets everything at deploy time.** No setup screens to build. But an expired Jira key would need a deploy, which is what ADR 0022 set out to avoid.
- **The first person to sign in becomes the Operator.** Nothing to configure. But after a fresh deploy, anyone in the tenant who signs in first takes over the platform.
- **A first-run setup page, protected by a one-time code from the deploy.** It is friendlier than settings. But it is a screen used once per environment, with its own security to test, and it gives the same result as the two settings.

## Consequences

- **The team keeps two roles.** If this ADR is accepted, the glossary's Operator entry adds "looks after Settings", and the Approver entry adds "confirms a new Approver and a new AI model address".
- **The deploy gains two settings,** `FIRST_OPERATOR` and `FIRST_APPROVERS`, as Terraform variables and in `deploy/make-env.sh` for local runs. Dev mode seeds today's dev users the same way (ADR 0029).
- **If no Approver can sign in,** for example because both have left, Operators can't make a new one. A person with database rights restores one by following the runbook, and the change is recorded in the settings history. This is the only role change made outside the Portal.
- **The support developer is not a user of the app.** This is the NCS developer who looks after the platform after handover (`docs/handover/PROTOTYPE_HANDOVER.md`). They work through git and the deploy.
- **The Planner and the AI troubleshooter stay platform agents.** Only a code change can alter them, as the prototype shows.
- **Connections and AI usage come in Phase 2.** The first demo needs only the AI model and People and roles. It uses GitHub's public API and the practice Jira, which need no keys from Operators.
