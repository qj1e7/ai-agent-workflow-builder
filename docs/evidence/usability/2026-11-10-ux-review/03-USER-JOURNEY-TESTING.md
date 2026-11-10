# 03. User journey testing

## How these results were gathered

Both prototypes were driven in Chrome by Playwright on 10 Nov 2026:
- **Prototype version 4 (v4):** tested by an AI agent acting as Alice (Operator) and Bob (Approver).
- **The chat-first sketch (sketch):** tested by me.

The texts typed are the exact scenario sentences. I spot-checked the v4 log's two most serious claims against the screenshots and source code (D-07, and the Tools crash), and both held. The full logs are in `evidence/`.

**What these numbers are not:** a usability study. No real users took part. Counts are one tester's path through a scripted prototype, in which requests are read by word rules, not a model.

**How actions are counted:** **Interactions** = clicks + Enter presses + typed fields + selects. Test-control presses don't count.

## Summary

| Scenario | v4 | Sketch | Who does better |
|---|---|---|---|
| A. First-time operator: "Every Friday at 9 AM, find Jira tickets that haven't been updated for 10 days and prepare a summary." | **Fail.** The update filter was dropped silently, and a workflow went on | **Fail.** An unrelated LangGraph card | Neither. v4 at least builds a Jira workflow |
| B. "Tell me what needs my attention today." | **Partial.** 1 click without typing. The typed sentence is refused | **Partial.** 0 clicks without typing. The typed sentence gets the fallback | Sketch, slightly (the strip stays during chat) |
| C. Failed workflow | **Pass** (3 interactions, or 1 from Home) | **Pass** (2 clicks), but no "what was affected" | v4 (four answers, a support path) |
| D. Human approval | **Pass, with flaws.** 2 clicks. The decline log is wrong | **Partial.** 2 clicks. Clear, but missing consequences | v4 (fuller panel) once the log is fixed |
| E. Weekly to daily | **Planner: Fail. Page: Partial** (5 interactions, stale text) | **Fail / Blocked** | v4 |
| F. "Monitor my important Jira issues." | **Fail.** A form, with no question asked | **Fail.** The fallback line | Neither |
| G. Unsupported capability | **Pass.** Honest, with an alternative | **Fail.** A wrong card, or the fallback | v4 |
| H. Kubernetes releases plus security | **Partial.** The watch is set up, and security is dropped silently | **Fail.** An unrelated card | v4 |

**What the results show:**
- **v4:** passes the routine paths (C, D, G) and fails where a sentence has to be understood carefully (A, B, E, F, H).
- **The sketch:** is faster on the routine paths but understands almost nothing typed.
- **Both:** fail the same way. **The AI drops or misreads part of the request without saying so.**

---

## Scenario A: first-time operator

**v4.** On day one, Alice typed the sentence. She got "Here's what I understood. I filled in what I could." and a "Friday summary" card: "Every Friday at 9:00, find [which tickets ▾] in [a Jira project ▾], [sum them up ▾]…" (`v4-A-02`). The words "haven't been updated for 10 days" appear nowhere. Next:
- she picked Open tickets and project MOCK;
- the footer said "Nothing is unclear. Turn it on when you're ready.";
- she turned it on;
- a test run proposed a summary of all 18 open tickets (`v4-A-07`).

A control phrasing, "with no update in 10 days", gave the honest answer: "I can't see when a ticket was last updated yet." From code: the rule doesn't match "haven't been updated for".

**Sketch.** It returned a LangGraph release check card (`chat-A-02`).

| Metric | v4 | Sketch |
|---|---|---|
| Task success | Fail | Fail |
| Interactions | 7 (5 to turn on) | 2 |
| Screens visited | 2 (Home, run) | 1 |
| Manual inputs | 1 field, 2 selects | 1 field |
| User decisions | 2 | 0 |
| Friction points | A dropped condition; "Nothing is unclear" claims it's complete; nothing close to "not updated" in the ticket choices | A confident, unrelated card |
| AI assistance | Parsed the schedule correctly and left 2 choices | None useful |
| Confidence | High, and wrongly so | Low once noticed |
| Recommended improvement | UX-01: account for every part of a request, and block "Nothing is unclear" while a part is unhandled | UX-05: v4's answer kinds before chat-first |

## Scenario B: daily operations

**v4.**
- **With no typing:** Home showed "Some things need you." and 3 of 5 Needs you rows. "See all on Workflows" showed all 5 in 1 click (`v4-B-01`, `v4-B-05`).
- **Typed:** the sentence got "I can't help with that here. I check software versions…", and Needs you was hidden (`v4-B-02`). "What needs me?" worked. From code: that rule only matches when it's the whole message.

**Sketch.** The one item showed on Home with 0 clicks. The typed sentence got the fallback (`chat-B-01`). The "Needs me" chip opened the run card and the live view (`chat-B-02`).

| Metric | v4 | Sketch |
|---|---|---|
| Task success | Partial | Partial |
| Interactions | 1 by looking, 4 on the typed path | 0 by looking, 1 by chip |
| Screens visited | 2 | 1 |
| Manual inputs | 0 or 1 | 0 or 1 |
| User decisions | 0 | 0 |
| Friction points | A refusal of the most common question; the refusal hides the list; 2 items only on Workflows | The typed question isn't understood |
| AI assistance | Proactive list | Proactive list and pinned strip |
| Confidence | High by looking, Low after the refusal | High by looking |
| Recommended improvement | UX-06, UX-12 | UX-06 |

## Scenario C: failed workflow

**v4.** "Why did the morning check stop?" got the four answers (`v4-C-01`):
- What happened: "Jira didn't answer at 8:00…"
- What was affected: "Today's check didn't run. Nothing was written."
- Can it be fixed safely: "Yes…"
- What to do: Retry the run.

Retry led to "Done, nothing new today" (`v4-C-03`). With Jira still down, the troubleshooter said "Not yet. A retry would stop in the same place" (`v4-C-07`). For a platform bug, Report to support was prefilled, and the case shows under Following up (`v4-C-09`, `v4-C-10`).

**Sketch.** Needs you, then Open, showed the run card and the live view with the red stop and the cause. Retry moved the line to "Waiting for a yes". Every card and the strip updated together (`chat-C-01`, `chat-C-02`). There's no "what was affected" and no support path.

| Metric | v4 | Sketch |
|---|---|---|
| Task success | Pass | Pass (what went wrong, what to do). Partial on what was affected |
| Interactions | 3 (1 from Home's Retry row); 4 for the support report | 2 |
| Screens visited | 2 | 1 |
| Manual inputs | 1 (0 from Home) | 0 |
| User decisions | 1 | 1 |
| Friction points | The "Yes." one-liner on Workflows; Retry shown while Jira is still down | No "affected"; no escalation |
| AI assistance | Four plain answers; honest "not yet" | Plain cause; live recovery |
| Confidence | High | High |
| Recommended improvement | UX-19 (small fixes) | Adopt v4's four answers and Report to support |

## Scenario D: human approval

**v4.** Bob: Review and decide, then the approval page (`v4-D-04`). It shows:
- **What will change:** one card per ticket with links, and "This is exactly what will be written, and nothing else.";
- **Why:**
- **Who asked:**
- **What happens:** "Nothing is written until you say yes… If you decline, the tickets are proposed again next Monday.";
- **Your part:** "You can decide because you didn't set this up."

Approve takes 2 clicks. Bob's Decline, though, left a green "Done" pill and the log line "Created MOCK-14, MOCK-15 and MOCK-16" (`v4-D-07`).

**Bypass attempts as Alice:** all blocked:
- self-approval of a test run;
- "without waiting for approval";
- "Let me approve my own workflow";
- the Teams card, which has no Approve button;
- taking over the schedule.

One exception: Alice alone could remove two other Approvers' roles, down to the floor of 2 (`v4-D-14`).

**Sketch.** Bob's approval card, then the full change panel: Where, Type, Summary, Description with the source, Priority, Labels, "Summary by AI" clearly labelled, and "Alice can't approve her own work, so it came to you." (`chat-D-02`). Alice typing "approve the FastAPI ticket" got "Nothing needs you right now", and she sees 0 Approve buttons.

| Metric | v4 | Sketch |
|---|---|---|
| Task success | Pass to decide; Partial to judge | Partial |
| Interactions | 2 to approve; 4 to decline with detail | 2 |
| Screens visited | 2 | 1 |
| Manual inputs | 0 | 0 |
| User decisions | 1 | 1 |
| Friction points | The decline record contradicts itself; no way to ask a question; no decline reason; "not checked" items unstated (security, 3 unread) | No consequences line; no way to ask a question; no evidence links |
| What will change / why / evidence / consequences / reject or clarify | Yes / Yes / Partly (links, but unread items unstated) / Yes / Reject only | Yes / Partly / Text only / No / Reject only |
| Bypass through the UI | Not possible to approve; Approver removal is one-sided | Not possible |
| Confidence | Medium | Medium |
| Recommended improvement | UX-02, UX-11, UX-13 | Use v4's panel, plus UX-11 |

## Scenario E: weekly to daily

**v4.**
- **The Planner:** three phrasings each started a new draft. One, "Run the software check every day instead of every Monday", became a Jira "Monday summary" card (`v4-E-01`, `v4-E-03`).
- **The workflow page:** Change, then How often = Every day, then Save took 5 interactions. The name, the purpose and the ticket window stayed weekly (`v4-E-05`, `v4-E-07`).

**Sketch.** The typed request built a second, new card. "Change" is a toast. The n8n editor only changes the time (`chat-E-01..03`).

| Metric | v4 | Sketch |
|---|---|---|
| Task success | Planner Fail; page Partial | Fail / Blocked |
| Interactions | 5 on the page | n/a |
| Screens visited | 3 | 1 |
| Manual inputs | 1 select | n/a |
| User decisions | 1 | n/a |
| Friction points | No edit by talking; drafts pile up; stale text; one request reversed | No schedule editor; a duplicate card |
| AI assistance | None | None |
| Confidence | Medium (page) | Low |
| Recommended improvement | UX-08, UX-09 | UX-08, UX-22 |

## Scenario F: ambiguous request

**v4.** "Monitor my important Jira issues." got a "Weekly summary" card with 4 choices left and no question (`v4-F-02`). The follow-up "Only high priority ones assigned to me" got an honest Part I can do answer. "Every morning" started another card (`v4-F-04`).

**Sketch.** The fallback line.

| Metric | v4 | Sketch |
|---|---|---|
| Task success | Fail | Fail |
| Interactions | 2 to the reply, about 7 more to finish | 2 |
| User decisions | 4 | 0 |
| Friction points | A form instead of one question; "important" and "my" dropped silently; follow-ups don't fill the open card | Nothing useful |
| Confidence | Low | Low |
| Recommended improvement | UX-10, UX-01 | UX-05 |

## Scenario G: unsupported capability

**v4.**
- **"Post a summary in our Teams channel every morning":** "I can write that summary, but I can't post messages in Teams yet…". It offers **Set that up** (the same summary into one Jira ticket) and **Ask the team** (`v4-G-01`).
- **"Close Jira tickets that are done":** "I can't close, edit, move or delete tickets. Only people do that here." It offers Ask the team, which is tracked only under Agent library > Tools (`v4-G-02`, `v4-G-07`).

**Sketch.** The Teams request got a LangGraph card. The close request got the fallback. The "What can you do?" chip lists "Not yet: posting in Teams channels, or updating Confluence."

| Metric | v4 | Sketch |
|---|---|---|
| Task success | Pass (both) | Fail (both) |
| Interactions | 2 to the answer, 3 to the alternative | 2 |
| Friction points | Teams described 3 ways; team requests are tracked in an admin tab | A misleading card |
| Confidence | High | Low |
| Recommended improvement | UX-15; show "Asked the team" items under Following up | UX-05 |

## Scenario H: software monitoring

**v4.**
- **From Home:** "You mentioned "releases", so this belongs on the Software watchlist…". The card added Kubernetes (kubernetes/kubernetes, version unknown, every Monday, any Approver except Carol) in 5 interactions. **Security isn't mentioned** (`v4-H-01`, `v4-H-03`). The control phrasing "check for vulnerabilities" got the honest "I can't check registries or security advisories yet."
- **From the watchlist page:** the whole sentence was saved as the software's name (`v4-H-05`). The sources list shows GitHub releases as Ready and security advisories as "Not yet", which is honest but static.

**Sketch.** A LangGraph card.

| Metric | v4 (Home) | v4 (watchlist page) | Sketch |
|---|---|---|---|
| Task success | Partial | Partial | Fail |
| Interactions | 5 | 5 | 2 |
| Manual inputs | 1 | 1 field, 1 select | 1 |
| User decisions | 2 | 1 | 0 |
| Friction points | Security dropped silently | A sentence becomes the name; Home and the page offer different matches | Wrong project, security dropped |
| Integrations shown accurately | Yes on the watchlist page; not in the reply | Yes | No |
| Confidence | High, and wrong about security | Medium | Low |
| Recommended improvement | UX-01 | UX-14 | UX-05 |
