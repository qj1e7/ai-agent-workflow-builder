# 07. UX scorecard

Scores run from 1 (poor) to 5 (excellent). The evidence comes from the hands-on logs in `evidence/` and the journeys in `03-USER-JOURNEY-TESTING.md`. Version 4 (v4) is scored as the product it describes. The chat-first sketch is a one-day design sketch, so its scores are about its interaction model, and its understanding layer is a stub.

| Dimension | v4 | Sketch |
|---|---|---|
| First-time usability | 3/5 | 2/5 |
| Navigation clarity | 4/5 | 4/5 |
| Task completion efficiency | 3/5 | 3/5 |
| Cognitive load | 3/5 | 3/5 |
| AI-native interaction | 3/5 | 2/5 |
| Information hierarchy | 4/5 | 4/5 |
| Error recovery | 4/5 | 3/5 |
| Trust and transparency | 2/5 | 2/5 |
| Accessibility | 4/5 | 3/5 (partial evidence) |
| **Overall user experience** | **3/5** | **2/5** |

## Evidence by dimension

### First-time usability: v4 3, sketch 2
- **Evidence:**
  - **v4 day one** is calm and clear: "Which software should we keep up to date?", two chips and a short I can list.
  - **Scenario A failed in both.** v4 turned on the wrong workflow while saying "Nothing is unclear".
- **Main weakness:** a first-time user can't tell when the AI has dropped part of the request.
- **Most valuable improvement:** UX-01, showing every part's fate on the card.

### Navigation clarity: v4 4, sketch 4
- **Evidence:**
  - **v4:** 4 plain tabs plus Teams and Settings, a working skip link, and a bottom bar on phones. Bob's menu is shorter.
  - **Sketch:** one screen and a side panel. No scenario got lost in either.
- **Main weakness:**
  - **v4:** the Agent library is a daily tab for admin content, and Needs you is split between Home and Workflows.
  - **Sketch:** no way to browse the watchlist.
- **Most valuable improvement:** pin Needs you during conversations, and move the Agent library into Settings (UX-12, UX-20).

### Task completion efficiency: v4 3, sketch 3
- **Evidence:** both are fast on routine paths.
  - **v4:** Retry takes 1 click from Home, and Approve takes 2.
  - **Sketch:** 0 clicks to see what's stopped, 2 to fix it.
  - **Both fail E:** v4's Planner makes new drafts, and the page path takes 5 interactions with stale text. The sketch has no schedule editor.
- **Main weakness:** you can't change things by talking.
- **Most valuable improvement:** an edit answer with a before-and-after card (UX-08, UX-09).

### Cognitive load: v4 3, sketch 3
- **Evidence:**
  - **v4 set-up card:** shows only the open choices, and the footer names them.
  - **Internal words still show:** "Pick agents", "Approval gate", "Show what each agent did".
  - **Ambiguous requests:** they become a 4-choice form.
  - **Sketch:** fewer surfaces, but the n8n canvas (IF, blocks, "Our block") is shown to every Operator.
- **Main weakness:** configuration appears where one question would do.
- **Most valuable improvement:** ask one question for ambiguous requests (UX-10).

### AI-native interaction: v4 3, sketch 2
- **Evidence:**
  - **v4 works from intent:** H routed "Kubernetes releases" to the watchlist and found the GitHub project. C's four answers are a strong example.
  - **v4 fails on wording:** natural phrasings were refused (B) or misread (E, F).
  - **The sketch:** keyword rules only.
- **Main weakness:** understanding is brittle to wording.
- **Most valuable improvement:** UX-06 and UX-01, with paraphrase cases in the AI tests.

### Information hierarchy: v4 4, sketch 4
- **Evidence:**
  - **Decisions come first:** the status banner and its one action on the workflow page; the four answers on a stopped run; the five-part approval panel.
  - **Sketch:** puts Needs you at the top and keeps it there.
- **Main weakness:** the v4 approval leaves out what wasn't checked (UX-11), and Home's "Some things need you." doesn't say what.
- **Most valuable improvement:** a "Not checked" line on approvals, and the top item named on Home.

### Error recovery: v4 4, sketch 3
- **Evidence:**
  - **v4:** answers "What was affected?". It's honest when Jira is still down ("Not yet"), and it has a prefilled Report to support with a tracked case.
  - **Undo:** on Discard, Remove and other actions.
  - **Sketch:** live retry, but no "affected" answer and no escalation.
- **Main weakness:** small mixed signals, such as Retry shown while Jira is down.
- **Most valuable improvement:** UX-19 (disabled buttons with the reason next to them).

### Trust and transparency: v4 2, sketch 2
- **Evidence:**
  - **The design is excellent:** one capability registry, Planned features hidden and tagged, "Summary by AI" labelled, and "This is exactly what will be written".
  - **But the declined run's record says tickets were created** (`v4-D-07`).
  - **Parts of requests are dropped silently** (A, F, H).
  - **An unbuilt action works by default** (LangServe "Use the new address").
  - **Teams is described 3 ways.**
  - **The sketch** shows confident, unrelated cards.
- **Main weakness:** the four failures sit exactly where trust is earned: the audit record, the plan the AI made, and what the platform claims.
- **Most valuable improvement:** UX-02 and UX-01 before anything else.

### Accessibility: v4 4, sketch 3
- **Evidence:**
  - **v4:**
    - axe found 0 violations on 7 screens;
    - a visible focus ring on every Tab stop;
    - 3 key presses to the box with the skip link;
    - reduced motion stops every loop;
    - no sideways scroll at 390 px.
  - **v4's gap:** controls under 44 px on every screen.
  - **Sketch:**
    - 1 serious contrast failure (the brand mark, 2.75:1);
    - nested interactive controls in the n8n canvas;
    - Tab order that doesn't match the hero layout.
- **Not assessed in either:** a real screen reader.
- **Main weakness:** touch targets (v4).
- **Most valuable improvement:** UX-18.

### Overall: v4 3, sketch 2
- **v4** is a well-designed, honest product shell around an understanding layer that isn't reliable yet. Its routine paths (C, D, G) already beat manual work.
- **The sketch** has the better daily layout (pinned needs, live cards, side panel) but no understanding.
- **The most valuable single change:** never drop part of a request silently (UX-01), then fix the decline record (UX-02).

## Final verdict

**"If I were a real non-technical operator using this system every day, would I find it genuinely useful, intuitive, and easier than my existing manual processes?"**

**Not yet, but it's close for the routine job.**

**The routine software-versioning work: yes, it would beat my manual process.** On a normal morning:
- Home shows what's stopped and what waits for me.
- Retry takes 1 click and explains itself in plain words ("Jira didn't answer at 8:00… Nothing was written.").
- An Approver sees exactly what will be written before saying yes.

Today I'd be checking GitHub release pages and writing upgrade tickets by hand, so that's a real saving.

**Anything I'd type in my own words: no.** I wouldn't trust it yet, for two reasons I saw myself:
1. **It changed what I asked for without telling me.** I asked for tickets "that haven't been updated for 10 days". It built a summary of all open tickets and told me "Nothing is unclear". I'd only find out when the summaries were wrong. After that, I'd check every card it gave me, which takes away the point of asking.
2. **It couldn't do simple follow-ups.**
   - "Tell me what needs my attention today" was refused, and the list I needed disappeared.
   - "Make it daily" made a new workflow instead of changing mine.
   - Changing it on the page left it still called "Weekly".

**What specifically needs to change, in order:**
1. **Show me every part of my request,** and say which part you can't do. Never say "Nothing is unclear" when you dropped something (UX-01).
2. **Make the record match the decision.** "Declined" must never sit next to "Created MOCK-14…" (UX-02).
3. **Understand how I actually ask** about my day and my software, and never hide what needs me when you can't answer (UX-06, UX-07, UX-12).
4. **Let me change a workflow by saying so,** and show me before and after (UX-08, UX-09).
5. **Let an Approver ask a question,** and tell them what wasn't checked (UX-11).

With those five fixed, the chat-first layout (pinned needs, live cards, side panel) would make the daily routine faster still. Without them, a better layout would only make the wrong answers look more convincing.
