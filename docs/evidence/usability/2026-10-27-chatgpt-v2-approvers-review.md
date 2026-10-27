# Independent regression review of named Approvers (ChatGPT)

- Date: 27 Oct 2026
- Evaluator: ChatGPT, testing the public prototype link directly
- Version tested: prototype v2 with named Approvers, artifact version 9. The fixes that followed are listed in [`2026-10-27-v2-changes.md`](2026-10-27-v2-changes.md).
- The report below is copied as the team received it. The team has not edited it.

---

# Approval escalation regression review

I tested the latest public prototype directly. This pass focused on the newly added named Approvers, backup escalation and no-response behavior.

## Verdict

The previous high-priority approval-ownership issue is **fixed**.

The new flow gives each request a responsible person, a backup, a clear escalation time and a firm stopping point. Most importantly, the system never treats silence as approval.

Overall assessment: **4.5/5 — strong enough for operator usability testing.**

## Tested scenario

I created:

> Every Friday at 4pm, summarize open Jira tickets older than 14 days and post the summary to CODESparks Support in Teams.

Approval configuration:

- Primary Approver: Bob
- Backup Approver: Siti
- Ask backup after: 4 working hours
- Stop waiting after: 2 working days
- Working hours: Monday–Friday, 09:00–18:00 SGT

I then ran a test and simulated:

1. Bob receiving the approval request.
2. Bob not answering for four working hours.
3. Siti receiving the backup request.
4. Neither Bob nor Siti answering before the deadline.
5. The run stopping without posting anything.
6. The operator opening the recovery path to change the Approvers.

## Results

| Behavior | Result | Evidence |
|---|---|---|
| Self-approval prevention | Pass | Alice was excluded from the available Approvers because she owned the routine. |
| Named primary Approver | Pass | Bob was explicitly identified as the person asked first. |
| Named backup | Pass | Siti was explicitly identified as the backup. |
| Duplicate-person prevention | Pass | After choosing Bob, he disappeared from the backup choices. |
| Escalation timing | Pass | The interface stated that Siti would be asked after four working hours without an answer. |
| Expiry behavior | Pass | The request stopped after two working days without approval. |
| Fail-safe behavior | Pass | “Post in Teams” became “Not needed,” and the run stated that nothing was written. |
| Operator visibility | Pass | Home displayed “Nobody answered on your test run,” named Bob and Siti, and offered recovery actions. |
| Recovery | Pass | “Do a test run again” and “Change who approves” were immediately available. |
| Future configuration | Pass | The routine page showed Bob, Siti, the escalation delay and the expiry rule together. |
| Existing software approval | Pass | Home now explained that Bob was asked first, Alice was being asked as backup, and when the request would stop. |

## What works particularly well

- The setup explains the business rule rather than only presenting fields.
- Primary and backup responsibility are unambiguous.
- The operator can choose “Nobody else” when no backup is appropriate.
- Escalation and expiry use working hours rather than unexplained elapsed time.
- The interface explicitly says: “A request never says yes by itself.”
- Both Bob and Siti remain able to respond after escalation, which matches the displayed explanation.
- The final setup review summarizes the complete approval policy before activation.
- The run activity records when the backup was contacted.
- The stopped run clearly separates “No answer” from technical failure or rejection.
- The routine remains scheduled after the test-run failure, while the failed test remains visible in recent runs.

## Remaining findings

### S2 — High: the pending approval contains a false “Posted” statement

While the run was still waiting for approval, the detail panel said:

> Posted in CODESparks Support. This is exactly what will be written, and nothing else.

This contradicts the surrounding evidence:

- the heading said the summary “will be posted”;
- the agent log said nothing was posted yet;
- the approval gate was still waiting;
- the deadline explanation said nothing would be written without approval.

For a safety-focused product, past-tense wording can make the operator believe the protected action has already occurred.

**Recommendation:** change it to:

> To be posted in CODESparks Support. This is exactly what will be written, and nothing else.

This should be corrected before showing the prototype to operators.

### S3 — Medium: approval configuration is cognitively dense

The screen presents:

- primary Approver;
- backup;
- optional two-person sequential approval;
- backup delay;
- expiry deadline;
- working-hour rules.

The explanation is good, but a first-time operator must understand several related concepts at once.

**Recommendation:** offer a clear default preset:

> Bob approves. If Bob does not answer within four working hours, ask Siti. Stop after two working days.

Place advanced options such as sequential two-person approval behind “More approval options.”

### S3 — Medium: the routine’s work still cannot be edited after activation

Schedule and Approvers can now be changed, but ticket criteria, action and destination still cannot.

**Recommendation:** add “Edit what it does,” rerun the understanding check and show a change comparison before replacing the active definition.

### S3 — Medium: software approval remains all-or-nothing

The software check still requires Bob or the backup to approve or decline every proposed ticket together.

**Recommendation:** allow individual tickets to be excluded while recording one approval event for the selected set.

### S4 — Low: recovery helper text can describe a request that no longer exists

After the request had already stopped, “Change who approves” displayed:

> The request that’s waiting now keeps the people it was sent to. Your change starts with the next run.

There was no longer a waiting request.

**Recommendation:** make this state-sensitive:

> This change starts with the next run. The stopped test run is not restarted automatically.

### S4 — Low: channel wording remains repetitive

The review says Bob is asked “in CODESparks Support” before the result is posted “in CODESparks Support.” This is accurate but easy to skim incorrectly.

**Recommendation:** state separately:

- Approval request channel: CODESparks Support
- Result destination: CODESparks Support

## Updated assessment

| Dimension | Rating |
|---|---:|
| Learnability | 4.5/5 |
| Efficiency | 4.5/5 |
| Workflow suitability | 4.5/5 |
| Information architecture | 4.5/5 |
| Error prevention and recovery | 4.5/5 |
| Operational productivity | 4/5 |
| Visibility and feedback | 4.5/5 |
| Completeness | 4/5 |

## Recommendation

The named-Approver design is a meaningful improvement and resolves the largest remaining accountability gap.

Before the next operator session:

1. Correct “Posted” to “To be posted.”
2. Simplify the approval configuration with a default summary and advanced options.
3. Make the recovery helper text respond to whether a request is waiting or already stopped.

After those corrections, the main question should move from “Does the interface prevent unsafe approval behavior?” to “Do real support operators find the escalation rules natural for their team?”
