# 04. AI-native UX assessment

**The question:** is this genuinely AI-native, or a traditional app with a chatbot added?

**The answer:**
- **Version 4 (v4):** genuinely AI-native in its design and in its honesty rules. Its weak point is understanding: the AI layer silently drops or misreads parts of a request. When the words match its rules it reduces effort a lot. When they don't, it either refuses ("I can't help with that here.") or quietly builds something different from what was asked.
- **The chat-first sketch:** has the better interaction model (one screen, a pinned Needs you, live cards, a side panel), but it's a chat front end with almost no understanding behind it.

Scores are 1 (poor) to 5 (excellent). Evidence is from `03-USER-JOURNEY-TESTING.md` and the logs in `evidence/`.

## Scores

| Dimension | v4 | Sketch |
|---|---|---|
| Intent-driven interaction | 3 | 2 |
| Contextual UI | 4 | 4 |
| Progressive disclosure | 4 | 3 |
| AI autonomy (with human control) | 4 | 3 |
| Proactive assistance | 3 | 4 |
| Human-AI collaboration | 3 | 2 |
| Trust and transparency | 2 | 2 |
| Error recovery | 4 | 3 |

### Intent-driven interaction: v4 3, sketch 2
- **v4: for.**
  - People start by typing intent on Home, with no module to pick first.
  - "Every Friday at 9 AM" became Friday 9:00.
  - "Monitor Kubernetes releases" found kubernetes/kubernetes and moved the request to the watchlist without the person knowing the watchlist exists (`v4-H-01`).
- **v4: against.**
  - **Refuses natural wording:** "Tell me what needs my attention today." was refused (`v4-B-02`).
  - **Can't edit by talking:** "change X to daily" created new drafts (`v4-E-01`).
  - **Doesn't ask:** "Monitor my important Jira issues." got a form, not a question (`v4-F-02`).
- **Sketch.** The same front door, but 5 of 8 typed scenarios got an unrelated card or a fallback.

### Contextual UI: v4 4, sketch 4
- **v4.**
  - **Per state:** every state has its own answer kind and card. Bob gets no box, only his approval (`v4-home-05`).
  - **Per run state:** run pages lead with the troubleshooter when stopped and with the approval panel when waiting.
  - **Per guess:** the set-up card shows only the choices still open.
- **Sketch.**
  - **Cards in place:** cards appear in the chat, and opening one puts it beside the chat instead of navigating away.
  - **Live everywhere:** a retry updates every card at once (`chat-C-02`).
  - **Gaps:** no watchlist and no schedule editor.

### Progressive disclosure: v4 4, sketch 3
- **v4.**
  - **Folded until asked:** "How this workflow works", "Technical details" and "Show what each agent did" are collapsed but easy to find.
  - **Planned features:** hidden behind a test control and tagged when shown.
  - **Leaks:** some internal names, such as "Pick agents", "Approval gate" and the model ID (UX-17).
- **Sketch.** The "In n8n" tab and editor are one click away for every Operator, which shows blocks, IF branches and versions to people who don't need them (UX-24).

### AI autonomy with human control: v4 4, sketch 3
- **v4.**
  - **The AI does the routine work:** finds the GitHub project, fills the schedule, picks helpers, drafts tickets and explains stops.
  - **It never writes without a yes:** every bypass attempt was refused (Scenario D).
  - **Guesses that matter become choices:** the Jira project is one.
  - **A time is never guessed.**
- **Sketch.** The safety checker adds the yes step automatically, and n8n edits without one are flagged ("Writes refused"). Autonomy over understanding is missing, though.

### Proactive assistance: v4 3, sketch 4
- **v4.**
  - **Shown on Home:** Needs you shows stops, approvals and expiring keys with one action each.
  - **Hidden while you chat:** the list disappears during a conversation (UX-12).
  - **Not all shown:** 2 of 5 items appear only on Workflows.
  - **Chip doesn't answer:** the chip "Which software has a newer version?" answers with a count instead of the names (`v4-inv-07`).
- **Sketch.** Needs you stays pinned as a strip during the conversation. That's the one pattern v4 should copy as it is.

### Human-AI collaboration: v4 3, sketch 2
- **v4.**
  - **Checking guesses:** people can check and correct them. Guesses are grey and editable, and choices are chips.
  - **Asking about an approval:** an Approver can't ask the requester a question (UX-11).
  - **Follow-ups:** they start new cards instead of refining the open one (`v4-F-04`).
  - **Editing:** an existing workflow can only be edited through forms.
- **Sketch.** You can override by hand (Pause, Roll back, edit in n8n), but you can't correct the AI by talking.

### Trust and transparency: v4 2, sketch 2

The design intent here is excellent:
- one capability registry decides every claim;
- Planned features are hidden unless shown, and tagged;
- "Summary by AI" is labelled as help, never as the check;
- "This is exactly what will be written".

The execution breaks trust in the four places that matter most:
1. A declined run's record says tickets were created (`v4-D-07`).
2. Parts of requests are dropped while the card says "Nothing is unclear" (`v4-A-04`).
3. "Use the new address" works on a case the platform refuses (`v4-watchlist-04`).
4. What Teams does is described three ways.

The sketch builds confident wrong cards.

**Why a 2:** an operator who catches one silent drop will doubt every card after it. One wrong log line in an audit record matters more than many correct screens.

### Error recovery: v4 4, sketch 3
- **v4.**
  - **The four answers:** What happened, What was affected, Can it be fixed safely, What to do.
  - **An honest "not yet":** when Jira is still down.
  - **A prefilled Report to support**, with a case tracked under Following up.
  - **Undo:** on Discard, Remove and other actions.
- **Sketch.** Clear cause, and a live retry. It has no "affected" answer and no escalation path.

---

## Unnecessary user effort (spec section 9)

| Where | Effort today | What the system should do | Why |
|---|---|---|---|
| Ambiguous request (F) | 4 choices plus a time on a form | **Ask one clarification** (the biggest unknown first), then infer the rest | One question is less work than a form, and it doesn't hide the unsupported parts |
| Change a schedule (E) | Open the workflow, then Change, then a select, then Save (5 interactions), and fix the stale text by hand, which isn't possible | **Automate by talking** ("make it daily" leads to a before-and-after card), and **infer** the matching window change | The person stated the intent; the AI should do the edit |
| "What needs my attention" (B) | Typing is refused, so open Workflows | **Infer** the intent from any wording, and always show the list | It's the most frequent question |
| "Which software has a newer version?" | Read 14 rows on the watchlist | **Automate:** name the 3, with versions and the waiting approval | The chip promises it |
| Follow-up details (F) | Each message starts a new card | **Contextual control:** follow-ups fill the open card | Saves rework |
| The GitHub project for new software | One guess on Home, two choices on the watchlist page | **Infer** the default and show where it came from, as Home already does | Consistency |
| Picking agents and tools | Never asked of the Operator | **Keep automated** | Already right |
| Choosing the Jira project | A choice on the card | **Keep as a choice** (it changes what's written) | Spec rule 3, which is right |
| Turning a workflow on | One press of Turn it on | **Keep manual** | Starts real runs |
| Decline reason | None asked | **Add an optional box** | Gives the requester something to act on |

## Features that should NOT be simplified (spec section 10)

| Feature | Why keep the complexity | How to make it understandable |
|---|---|---|
| The approval page (What will change, Why, Who asked, What happens, Your part) | It's the one human check on every write. The AI summary must not replace it | Keep all five parts. Add a "Not checked" line and a way to ask a question. Never show only the AI summary |
| "Nobody approves their own work" and the 2-Approver floor | Separation of duties is the sponsor's rule | Keep the rule visible at the decision point ("You set this up, so another Approver must decide"). Make removing an Approver also need a second person |
| Turn it on, then Do a test run | Activation starts real runs | Keep one explicit press, and keep the test run marked "Test run" everywhere |
| Delete with confirm and Undo | Destructive | Keep the confirm, which names what's kept ("Its past runs and their records stay") |
| Every write waiting for a yes, including n8n edits | Safety lives where the keys are (ADR 0026) | Show "Writes refused" with a one-tap fix, as the sketch's n8n flow does |
| Roles and permissions in Settings | Changes who can approve | Keep it admin-only and logged. Confirm role removals |
| Capability honesty ("Not yet", Planned) | Stops people building on what doesn't exist | Keep one registry. Show the "Not yet" line inside the answer it affects, not only on a separate list |
| All-or-nothing weekly approval | ADR 0019 chose one approval per check | Don't add partial approval now. Add a decline reason so Bob can say which ticket worried him |
