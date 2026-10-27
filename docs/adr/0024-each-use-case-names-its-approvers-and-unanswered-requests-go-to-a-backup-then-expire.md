---
status: proposed
---

# Each use case names its Approvers, and an unanswered request goes to a backup, then expires

Today any Approver who is not a party to a run can decide its approval request, and the request waits until someone does. Nobody in particular is asked, so a request can sit unanswered. The sponsor's access review also needs two Approvers, one after the other, and its process says who they are. An independent usability test of the Portal prototype found the same gap: an Operator could not see who would approve, or what happens when that person is away ([report](../evidence/usability/2026-10-27-chatgpt-v1-evaluation.md)). This changes the approval gate, so `AGENTS.md` requires an ADR.

So each approval step on a use case names a first Approver and, if the Operator wants one, a backup. Only those two people can decide that step. The request goes to the first Approver. If they have not answered after a set wait, the platform asks the backup too and reminds the first Approver. If nobody answers by a second deadline, the request expires. Nothing is written, as when a request is declined, and the use case's owner is told. A request never approves itself.

- **Waits count working hours only:** Monday to Friday, 9am to 6pm, Singapore time. The proposed defaults are to ask the backup after 4 working hours and to expire after 2 working days. The Operator can change both on each use case. The sponsor needs to agree the defaults and the working hours.
- **Escalation changes who is asked, never who may decide.** The backup can decide as soon as the request is made. This keeps `decide()` free of the clock, so an Approver who opens the link a minute early is never refused.
- **The platform checks the names, and the model never chooses them.** ADR 0023 already says the model does not choose who approves. When a use case is saved, the platform checks that each named person holds the Approver role, is not the use case's owner, and is not named on another step of the same use case.
- **"Any Approver on the team" stays as a choice.** Every use case works this way today. Its request goes to the team's Teams channel, and it expires in the same way.

The rule that checks a decision already allows a list of people for a step (`OneOf` in `platform-api/src/platform_api/orchestration/approvals.py`), but nothing uses it yet. So the decision rules do not change. What is new is the names saved on the use case, the two waits, and the platform's timer that acts on them.

## Considered options

- **Keep "any Approver" and one Teams channel.** It is the simplest, and it works for a small team that watches the channel. But nobody owns a request, so each person can assume someone else will answer it. It also cannot express the access review, whose process names who approves each step.
- **Name one Approver with no backup.** It is clear who must answer, but one person on leave stops every run of that use case.
- **Let the backup decide only after escalation.** The first Approver stays in charge for longer. But the decision rule would then depend on the time, and there is no safety gain, because the Operator chose to trust both people.
- **Approve when time runs out.** Some workflow tools allow this. It breaks the rule that no write action runs without approval, so it is not an option.
- **After the backup, ask anyone on the team.** Fewer requests would expire, but more people could approve than the Operator chose. Instead the request expires, and the owner decides what to do next.
- **Let n8n's Wait node time out the request.** n8n carries runs and our API decides (ADR 0007). The pause between the two legs belongs to the platform, so its timer does too.

## Consequences

- **Use case builder.** A use case saves, for each approval step, its first Approver, its backup and the two waits. Changing any of them makes a new use case version. In the Portal redesign, the Operator sets them in the "When and who" step of New routine, and changes them on the routine's page.
- **Orchestration.**
  - An approval request keeps the names and waits it was made with, as it keeps the proposal's digest. Changing the use case changes the next run, never a request that is already waiting.
  - The platform's tick already finds runs past their deadline. It also finds requests that are due to go to the backup or to expire.
  - An expired run ends in a new state beside declined. It reads "No answer. Nothing was written." It is not a failure, so the AI troubleshooter does not explain it as one.
  - A request always expires before the same use case's next scheduled run starts, so two requests for one use case never wait at the same time. For the watchlist, an expired check proposes its tickets again at the next check, as a declined check does (ADR 0019).
- **A named person who can no longer decide is skipped.** That happens when they start or retry the run, which makes them a party to it, or when they lose the Approver role. The request then goes to the other person at once. If that leaves a step with nobody, the run stops before it asks anyone, with a reason the owner can fix by choosing someone else.
- **Run monitoring.** The activity log records who was asked, when the backup was asked and when a request expired, beside who decided. Home shows each person what is waiting for them. It shows the owner who has been asked, and when the backup will be asked.
- **Teams.** Each message names the person it asks. A real Teams mention needs the Teams bot that ADR 0009 leaves for later. Until then, the practice Teams copy shows the name in the message text.
- **The access review** names a first Approver and a backup for each of its two steps, and the two steps never share a person. The rule that one person cannot decide two steps still holds.
- **Leave calendars and public holidays are not covered.** Reading leave from Outlook or Entra ID would be a new external dependency, with its own ADR. Until then, the backup covers leave.
- **Existing use cases keep "any Approver".** Their requests start to expire after the default wait.
- **If this ADR is accepted,** the safety rules in `AGENTS.md` gain one line: a request that nobody answers expires, and never approves itself.
