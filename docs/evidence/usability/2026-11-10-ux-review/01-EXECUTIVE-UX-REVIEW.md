# 01. Executive UX review

**What was reviewed:**
- **Prototype version 4 (v4):** the team's build target, `docs/design/ai-native-redesign/prototype.html` on `origin/main`.
- **The chat-first desktop sketch:** made on 10 Nov.

**How:** hands-on in Chrome (Playwright) with the eight scenarios from the brief, 136 v4 screenshots and 19 sketch screenshots, axe-core, and keyboard and 390 px checks. I spot-checked the two most serious v4 findings against the screenshots and the source.

**Limits:**
- one tester, no real users, and no screen reader;
- both prototypes read requests with word rules, not a model, so this reviews the designed behaviour and the rules as written;
- nothing was edited in either prototype.

## Verdict

**v4 makes the routine software-versioning work easier than doing it by hand. It doesn't yet make typed, free-form work trustworthy.**
- **Its design is genuinely AI-native:**
  - intent first on Home;
  - one capability registry;
  - honest "can't" answers;
  - the troubleshooter's four answers;
  - a strong approval page.
- **Its weak point is understanding:** in 5 of 8 scenarios the AI dropped, refused or misread part of what was asked, and twice it said "Nothing is unclear" while doing so.

**The chat-first sketch has the better daily layout.** Needs you stays pinned during the conversation, cards update live, and things open beside the chat. But it has almost no understanding behind it, so it fails every typed scenario except the scripted ones.

**The recommendation:** keep v4's engine and rules, fix how it reads requests, and adopt three of the sketch's patterns. Don't move to chat-only.

## Strengths (with evidence)
1. **Failure recovery is excellent:**
   - plain answers to what happened, what was affected, whether it's safe to retry, and what to do;
   - an honest "Not yet" while Jira is still down;
   - a prefilled support report with a tracked case;
   - 1 click to retry from Home.

   (Scenario C)
2. **The approval page shows exactly what will be written.**
   - **Who:** who asked, and why this Approver may decide.
   - **What a decline means:** it's stated.
   - **No way round it:** no path let Alice approve her own work (Scenario D).
3. **Honest limits when the wording matches:** "I can write that summary, but I can't post messages in Teams yet", with a real alternative and Ask the team (Scenario G).
4. **Proactive Home:** stops, approvals and expiring keys appear without asking, each with one action. Bob's Home is just his approval.
5. **Accessibility basics are in place:**
   - 0 axe violations on 7 screens;
   - a visible focus ring;
   - reduced motion stops every loop;
   - no sideways scroll at 390 px.

## Weaknesses (with evidence)
1. **Parts of requests vanish silently.**
   - **Scenario A:** "haven't been updated for 10 days" became a summary of all open tickets, with "Nothing is unclear".
   - **Scenario F:** "important" and "my" were dropped.
   - **Scenario H:** "identify… security issues" was dropped.
2. **The approval record contradicts the decision.** After a decline, the run shows a green "Done" pill and "Created MOCK-14, MOCK-15 and MOCK-16" (`v4-D-07`).
3. **Natural questions are refused.**
   - "Tell me what needs my attention today." gets "I can't help with that here.", and the Needs you list disappears.
   - Home's own chip "Which software has a newer version?" answers only with a count.
4. **No editing by talking.**
   - "Make it daily" creates new drafts.
   - The page edit leaves the workflow still called and described as weekly.
5. **Approvers can only say yes or no.** They can't ask a question, can't give a reason, and aren't told what wasn't checked (security advisories, unread projects).
6. **Broken or misleading spots:**
   - the Tools tab crashes on its own suggested chip;
   - "Use the new address" works on a case the platform refuses;
   - one Operator could remove two other Approvers alone.

## Top recommendations
1. **Show every part of a request on the card** (✓ or ✗ with the reason), and never say "Nothing is unclear" while a part is unhandled. Back it with paraphrase cases in the AI tests (UX-01).
2. **Fix the decline record** (UX-02). Remove or guard the Tools request box (UX-03). Stop "Use the new address" from working where the platform refuses (UX-04).
3. **Understand status questions in any wording,** and pin Needs you during conversations (UX-06, UX-07, UX-12).
4. **Add an edit answer** with a before-and-after card, and keep names and ticket windows in step with schedule changes (UX-08, UX-09).
5. **On approvals, add "Ask a question",** a decline reason, a "Not checked" line, and a confirmed removal of Approvers (UX-11, UX-13).

The full list is in `06-PRIORITIZED-IMPROVEMENT-BACKLOG.md`. The navigation and interaction model is in `05-REDESIGN-RECOMMENDATIONS.md`.

## Answer to the final question

Would a non-technical operator find it useful, intuitive and easier than the manual process?
- **For the daily software-versioning routine: yes.** Checking what's stopped, retrying, and approving the weekly upgrade tickets takes 1 to 2 clicks and reads in plain words.
- **For anything typed in their own words: not yet.** The AI changes requests without saying so, refuses ordinary questions, and can't edit by talking. One silent drop is enough to make an operator check every card from then on, which removes the benefit.

The five changes above are what it takes. `07-UX-SCORECARD.md` gives the full verdict.
