# Evidence log: chat-first desktop sketch

**What was tested:** the chat-first desktop sketch, published as https://claude.ai/artifact/76LFBEeXhPxGKYdwB6EsRg (version 2, 10 Nov 2026). The source is a single HTML file in a session scratchpad. It's a throwaway design sketch, not a repo prototype.

**How:** Playwright 1.55.1 driving Chrome at 1440 × 1000 px and 390 × 844 px, speed set to Instant, on 10 Nov 2026. Every result below was seen on the page. Anything read from the code is marked "(from code)". Screenshots are in `../shots/chat/`.

**What the sketch is:** one screen with no tabs. It opens on a centred Planner hero (box, three chips, Needs you rows). After the first message the box moves to the bottom and Needs you becomes a pinned strip. Answers are live cards. Opening a card shows a workflow, a run or an approval in a side panel. n8n appears as an "In n8n" tab and a mock editor. A demo bar outside the app plays 5 scripted tasks.

**What is simulated:** everything. Typed requests are routed by keyword rules (from code: `respond()`): "what can|help", then "workflows|running|list", then "stop|fix|why|broke|fail|retry", then "approv|needs me", then any of "release|watch|check|every|version|track|new". The last rule builds the same LangGraph sample card every time. Anything else gets a fallback line. There's one sample world: 3 workflows (FastAPI stopped, React running, LangGraph after task 1).

## Screen inventory

| Surface | How you reach it | Controls | Status |
|---|---|---|---|
| Home hero | Load, or Start over | Box, Send, chips "My workflows", "Needs me", "What can you do?", Needs you row "Open", Settings link | Works. Settings shows a toast only |
| Chat thread | After the first message or chip | Same box and chips at the bottom, pinned Needs you strip with Open | Works |
| Set-up card | A typed request that hits the last keyword rule | "Turn it on" (disabled until the build finishes) | Works, but the card is always the LangGraph sample |
| Workflow list card | "My workflows" chip, or typing "workflows" | Each row opens the workflow panel | Works, live |
| Run card | Needs you row, "Needs me" chip, or typing "why…stop" | "Open live view", "Retry the run" | Works, live |
| Approval card (Bob) | Demo task 4 only | "See the full change", "Reject", "Approve" | Works. There's no way to reach Bob's view without the demo bar |
| Side panel: workflow | Click a workflow row | Summary or In n8n tabs, banner action, "Change" (toast only), Pause or Resume (works), Run now (toast), Roll back (works), Open in n8n editor (works) | Partly simulated |
| Side panel: live activity | "Open live view" | Line or In n8n tabs, Retry | Works |
| Side panel: approval | "See the full change" | Reject, Approve | Works |
| Side panel: building in n8n | Build in side-panel mode | None | Works (watch only) |
| Mock n8n editor | "Open in n8n editor" | Block palette (read-only list), select a block, schedule time select (7:30, 8:00, 9:00, FastAPI and React only), Delete "Ask for a yes", Publish, Back to the app | Works for those edits only |
| "Changed in n8n" card | After Publish | Undo, Add the yes back, Open | Works |

## Scenario results

### A. First-time operator: "Every Friday at 9 AM, find Jira tickets that haven't been updated for 10 days and prepare a summary."
- **Typed:** that exact sentence, then Enter.
- **What appeared:** the Planner answered "Here it is. Check it, then turn it on." with a **LangGraph release check** set-up card ("Every Monday at 9:00, check LangGraph on GitHub…"). The side panel opened "Building in n8n" for LangGraph (`chat-A-02-reply.png`).
- **Result:** **Fail.** The answer has nothing to do with the request. The word "every" triggered the release-check rule. Nothing said that stale-ticket filtering isn't possible. In version 4's registry, filtering by update date is Planned.

| Metric | Assessment |
|---|---|
| Task success | Fail |
| Interactions | 2 (type, Enter) |
| Screens | 1 |
| Manual inputs | 1 |
| Decisions | 0 |
| Friction | A confident, wrong card. A first-time user could turn on the wrong workflow |
| AI assistance | None useful |
| Confidence | Low, once noticed. Dangerous if not noticed |

### B. Daily operations: "Tell me what needs my attention today."
- **Without typing:** Home showed one Needs you row, "FastAPI release check stopped today at 8:00", with Open (`chat-A-01-home.png`). That's 0 interactions to see the one item.
- **Typed the sentence:** the fallback reply, "This sketch only knows a few things…" (`chat-B-01-typed.png`). The phrase "needs my attention" doesn't match "needs me".
- **"Needs me" chip:** a run card plus the live activity panel (`chat-B-02-needs-chip.png`).
- **Result:** **Partial.** It's proactive with no typing. The natural sentence fails, and the chip works.

| Metric | Assessment |
|---|---|
| Task success | Partial (Pass by looking, Fail by asking) |
| Interactions | 0 to see; 1 chip to act |
| Screens | 1 |
| Manual inputs | 0 (or 1 typed, which failed) |
| Decisions | 0 |
| Friction | The typed version of the most common question isn't understood |
| AI assistance | Proactive row and strip |
| Confidence | High for the row, low for the typed answer |

### C. Investigating a failed workflow
- **Clicks:** Needs you "Open" (1), then a run card in the chat and the live activity panel opened by themselves (`chat-C-01-open.png`). "Retry the run" (2).
- **Shown:** the step line with the red stop at "Read release", and the troubleshooter's line "GitHub didn't answer at 8:00 when the Version checker read FastAPI's releases. It's answering again now, so a retry should work."
- **After Retry:** the line moved to "Ask for a yes", the status became "Waiting for a yes", the troubleshooter said "The retry worked. Found 0.121.0…", the strip changed to "Nothing needs you right now", and the chat card changed at the same time (`chat-C-02-retried.png`).
- **Missing:** "What was affected?" is never answered (version 4's troubleshooter has this as one of its four answers). There's no "Report to support" path for a fault Alice can't fix.

| Metric | Assessment |
|---|---|
| Task success | Pass (what went wrong, and what to do). Partial on "what was affected" |
| Interactions | 2 |
| Screens | 1 (chat plus panel) |
| Manual inputs | 0 |
| Decisions | 1 (Retry) |
| Friction | No "what was affected", no escalation path |
| AI assistance | Explained the cause in plain words and offered the fix |
| Confidence | High |

### D. Human approval (Bob)
- **Start:** demo task 4 (there's no in-product way to switch to Bob). Bob's chat opens on an approval card with "See the full change", "Reject" and "Approve", and the strip says "1 change needs your yes" (`chat-D-01-bob.png`).
- **Full change panel:** Where, Type, Summary, Description (with the GitHub source address as text), Priority, Labels. "Summary by AI" is labelled and says to check the change above. It says "Alice can't approve her own work, so it came to you." The buttons are Close, Reject and Approve (`chat-D-02-full-change.png`).
- **Missing:**
  - no way to ask a question or request clarification;
  - no link to the actual release notes, only text;
  - no "what happens if I reject";
  - no statement that nothing is written before the yes.
- **Bypass attempt as Alice:** after the retry put a request in "Waiting for a yes", Alice typed "approve the FastAPI ticket". The reply was "Nothing needs you right now" and 0 Approve buttons were visible to her (`chat-D-03-alice-tries.png`). From code, `approve()` also refuses when the user isn't Bob.

| Metric | Assessment |
|---|---|
| Task success | Partial: understands what and why, but can't ask a question, and consequences aren't stated |
| Interactions | 2 (See the full change, Approve) |
| Screens | 1 |
| Manual inputs | 0 |
| Decisions | 1 |
| Friction | No clarification path. Reject has no reason box |
| AI assistance | Summary clearly labelled as AI help, not the check |
| Confidence | Medium to High |

### E. Change a weekly workflow to daily
- **Typed:** "Change the LangGraph release check to run every day instead of weekly". The reply was **a second, new LangGraph set-up card**, not a change (`chat-E-01-typed.png`).
- **UI path:** My workflows chip, the LangGraph row, the workflow panel, then "Change" next to "When it runs". That only gives a toast: "A time picker would open here. You can also ask in the chat, or change it in n8n." (`chat-E-02-change-link.png`).
- **n8n editor path:** "Open in n8n editor", then the Schedule block. LangGraph's schedule is read-only text: "Runs every Monday at 9:00, Singapore time." For daily workflows the select only offers a time (7:30, 8:00, 9:00), never a frequency (`chat-E-03-n8n-schedule.png`).
- **Result:** **Fail / Blocked.** There's no working path to change how often a workflow runs. The typed path creates a duplicate, which is worse than failing.

### F. Ambiguous: "Monitor my important Jira issues."
- **Reply:** the fallback line (`chat-F-01.png`). No clarifying question, no "which project", no "what makes an issue important", and no statement that the platform can only read the newest 50 tickets.
- **Result:** **Fail.**

### G. Unsupported capability
- **"Post a summary in our Teams channel every morning":** a LangGraph release check card (`chat-G-01-teams.png`). It never says Teams posting isn't possible. **Fail, and misleading.**
- **"Close Jira tickets that are done":** the fallback line (`chat-G-02-close.png`). It doesn't say this is deliberately unsupported. **Fail.**
- **"What can you do?" chip:** the I can list plus "Not yet: posting in Teams channels, or updating Confluence." (`chat-G-03-caps.png`). That's honest, but only if the person asks.

### H. Software monitoring: "Monitor Kubernetes releases and identify potentially relevant security issues."
- **Reply:** a LangGraph release check card, with the build panel for LangGraph (`chat-H-01.png`). Kubernetes isn't used. The security part is dropped silently, which breaks principle 4.
- **Result:** **Fail.** The sketch has no software watchlist at all.

## Accessibility and responsiveness

- **axe-core 4.x, run on `#app` at 1440 px:**
  - **Home:** 1 serious. Color contrast on the "AI" brand mark, white on #02a7e1, 2.75:1 at 11.2 px bold. It needs 4.5:1.
  - **Run panel and workflow panel:** the same contrast issue, plus 1 moderate heading-order issue (an h3 inside the panel follows the app's h2 out of order).
  - **n8n editor:** 1 serious nested-interactive. The canvas `svg role="img"` contains focusable block buttons, so screen readers announce an image and miss the controls.
- **Keyboard:** Home's Tab order is Settings, then the 3 chips, then the box, then Send, then the Needs you row. On the hero the chips sit visually below the box but come before it in Tab order, which goes against WCAG 2.4.3 Focus Order. Enter in the box sends.
- **390 px:** no horizontal overflow on the page (0 px). The side panel covers the chat as a sheet with Close (`chat-phone-02-run.png`). The n8n editor stacks, and its canvas scrolls sideways inside its own box.
- **Console:** no errors in any run.

## Broken or misleading

1. The keyword router sends unrelated requests (stale Jira tickets, Teams posting, Kubernetes security, change a schedule) to the same LangGraph card. It's a sketch shortcut, but it shows what happens when a chat-first design has no "can't" or "part I can do" answers: the person gets a confident wrong card.
2. The "Change" link for a schedule and "Run now" are toasts.
3. Roles can only be switched from the demo bar. There's no in-app sign-in switch.
4. The n8n editor shows the internal word "n8n" to operators by design. Version 4 hid n8n from operators on purpose.
