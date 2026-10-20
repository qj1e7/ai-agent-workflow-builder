---
status: proposed
---

# Approvers decide under their own sign-in, and Teams carries the request

This changes the approval gate, so `AGENTS.md` requires an ADR. The sponsor wants approvals in Teams. Our [prototypes](../evidence/prototypes/README.md) showed that n8n accepts any approver name on resume, so a decision must come from a person we have identified. The approval request goes out in Teams. The decision is recorded by one function in our API, under the Approver's own sign-in, which checks the rules (not their own work, steps in order, a different person for each step). For the skeleton, a stub stands in for Teams and links to the approval page in our Portal. Later, a Teams message links to the same page, and a Teams bot can call the same function with the identity Teams gives it.

## Considered options

- **A one-time link or token in the Teams message that identifies the Approver.** No sign-in is needed, but anyone who holds the link acts as that Approver.
- **Approval only inside a Teams bot.** It is the best experience, but it needs a Microsoft 365 tenant that allows custom apps. Developer sandboxes are hard to get in 2026, so the skeleton cannot depend on it.

## Consequences

- There are no approval tokens and no resume URLs. The rule "approval tokens key off our own request ID" holds because nothing keys off n8n at all.
- Our approval page stays as the fallback if NCS never allows a Teams bot.
- Approvers need a real sign-in before any shared deployment, so Entra ID moves earlier in the plan. The dev sign-in stub refuses to start on a non-local host.
- If this ADR is accepted, the wording "approval in Teams" changes in two places, the safety rules in `AGENTS.md` and the `Approval gate` entry in `GLOSSARY.md`. The new wording is that the request goes out in Teams and the Approver decides under their own sign-in.
- Anyone who started, owns or retried a run counts as a party to its approval, and cannot approve it.
