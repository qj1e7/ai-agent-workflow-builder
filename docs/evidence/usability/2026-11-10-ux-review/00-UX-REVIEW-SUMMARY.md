# 00. UX review summary

An independent UX review, done on 10 Nov 2026, of:
- **prototype version 4 (v4):** the build target, `docs/design/ai-native-redesign/prototype.html` on `origin/main`;
- **the chat-first desktop sketch.**

Both were tested hands-on in Chrome with eight operator scenarios. Nothing in either prototype was changed.

**The answer:** for the daily software-versioning routine, v4 is already easier than the manual process. For requests typed in the operator's own words, it isn't trustworthy yet, because the AI silently drops or misreads parts of them. The chat-first sketch has the better daily layout, but no real understanding behind it.

## The five most important findings

1. **The AI drops parts of a request without saying so (P0, UX-01).**
   - **Scenario A:** "haven't been updated for 10 days" was dropped. The card said "Nothing is unclear" and turned on a summary of all open tickets (`shots/v4/v4-A-04-card-filled.png`).
   - **Scenarios F and H:** "important", "my" and "security issues" were dropped the same way.
2. **A declined approval's record says the tickets were created (P0, UX-02).** It shows a green "Done" pill and "Created MOCK-14, MOCK-15 and MOCK-16" after Bob declined (`shots/v4/v4-D-07-bob-after-decline-end.png`). Verified in source, line 2178.
3. **Ordinary questions are refused, and the answer to them is hidden (P1, UX-06, UX-12).** "Tell me what needs my attention today." gets "I can't help with that here.", and Needs you disappears (`shots/v4/v4-B-02-reply.png`). The sketch's pinned strip solves the hiding.
4. **You can't change a workflow by saying so (P1, UX-08, UX-09).** "Make it daily" creates new drafts. The page edit takes 5 interactions and leaves it called "Weekly… every Friday" (`shots/v4/v4-E-05-after-save-daily.png`).
5. **What's strong should stay as it is.** The troubleshooter's four answers and Report to support (Scenario C), the honest "can't" answers (Scenario G), the five-part approval page with no way round it (Scenario D), and 0 axe violations. Fixing the AI's understanding matters more than redesigning screens.

## Documents

| File | What it holds |
|---|---|
| [01-EXECUTIVE-UX-REVIEW.md](01-EXECUTIVE-UX-REVIEW.md) | Verdict, strengths, weaknesses, top recommendations, answer to the final question |
| [02-SCREEN-BY-SCREEN-AUDIT.md](02-SCREEN-BY-SCREEN-AUDIT.md) | Every screen of both prototypes, plus the visual and usability review |
| [03-USER-JOURNEY-TESTING.md](03-USER-JOURNEY-TESTING.md) | Scenarios A to H, measured for both prototypes |
| [04-AI-NATIVE-UX-ASSESSMENT.md](04-AI-NATIVE-UX-ASSESSMENT.md) | Eight AI-native dimensions scored, unnecessary effort, and what not to simplify |
| [05-REDESIGN-RECOMMENDATIONS.md](05-REDESIGN-RECOMMENDATIONS.md) | Navigation, Home, interaction patterns, and before-and-after journeys |
| [06-PRIORITIZED-IMPROVEMENT-BACKLOG.md](06-PRIORITIZED-IMPROVEMENT-BACKLOG.md) | 26 deduplicated items, P0 to P3, with effort |
| [07-UX-SCORECARD.md](07-UX-SCORECARD.md) | Scores with evidence, and the final verdict |
| [evidence/v4-hands-on.md](evidence/v4-hands-on.md) | The v4 test log: screen inventory, scenario steps, accessibility, 25 broken or misleading items |
| [evidence/chat-first-hands-on.md](evidence/chat-first-hands-on.md) | The sketch test log |

Screenshots are in `shots/v4/` (136) and `shots/chat/` (19). They aren't annotated. Each finding names its screenshot.

**Limits:** one tester and no real users. Requests in both prototypes are read by word rules, not a model. No screen reader was used. These results describe the prototypes, not the built Portal.
