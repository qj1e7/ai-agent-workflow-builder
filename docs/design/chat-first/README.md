# Chat first, on the desktop

**Status:** the design target since 13 Nov 2026. The team lead chose it on that day, and the app is built from it.

`prototype.html` is the clickable sketch "Chat first, on the desktop", version 3. Its shared copy is https://claude.ai/artifact/76LFBEeXhPxGKYdwB6EsRg. Open the file in a browser. It needs no server.

## How to use it

- It is the source of truth for screens, flows, words and motion. Build what it shows, in its words.
- Use the controls above the app window:
  - "View as" switches between Alice, Alice with n8n access, and Bob, an Approver.
  - "Play" runs each flow: Morning check, Ask in my words, Change by talking, Something it can't do, Bob declines, Browse, Edit in n8n, Draft a workflow, Bob approves a draft, Second Approver, and Explain.
  - "Speed" set to Instant is best for screenshots.
  - "Tracing" turns the thumbs under each Planner answer on or off, as the capability registry will (ADR 0050).
- The list under the window, "What's new in version 3", says what each flow is meant to show. Its second part covers the workflow drafter screens from ADR 0051, added on 16 Nov 2026.
- The sketch uses sample data only. The demo bar, Play, Speed and Tracing are for the sketch, not the app.

## Calm look, 22 Nov 2026

The team lead found most screens heavy and wordy, with box drawn on box. Three reviews with the better-interface skills found the same causes on every screen. The team lead chose the "Calm look" and kept the typeface, Atkinson Hyperlegible Next, with its slashed zero. The sketch follows the six rules below. They are the Portal's style rules from now on, so the Portal pull requests that follow use them too.

1. **One type scale.** Use five sizes only, as tokens: `--text-14`, `--text-16`, `--text-18`, `--text-22` and `--text-28`. Body text is weight 400. Row labels, card titles, buttons and status words are 600. Page and panel titles are 700. Nothing is 800, and a small heading is never heavier than the page title.
2. **Controls.** Main buttons are 38 px tall and small ones are 32 px, both with 14 px text. A view or a card has one filled button at most. Other actions are outline buttons or quiet text buttons. A form field has an edge a person can see (`--edge`, 3:1 or more on white).
3. **Flat surfaces.** Group with space, not lines. An answer is one card, with no box inside it and no rule above its foot. Every card uses one radius (`--r-card`) and one border colour (`--hair`).
4. **Quiet status.** A status is a small dot and a word, such as On, Paused or Newer out. Only a real problem, such as Stopped or Can't find, gets a fill. The set-up approval's warning that some writes won't ask for a yes on each run also keeps its amber fill, because the Approver must not miss it. The pinned strip keeps a plain surface, and its dot and bold name carry the state. Each colour has one meaning. Green means done or on, so the chip that marks a person's own words is grey.
5. **One of each piece.** Use one pill style at one size, one tab bar style, and one press effect. A press scales to 0.97 over `--t-press` with the ease-out curve. A disabled button never scales, and no press scales under reduced motion.
6. **Readable for everyone.** A skipped step fades only its dot and face. Its label keeps a contrast of 4.5:1 or more. On a window 34rem tall or less, such as a laptop at 200% zoom, the chat page scrolls as a whole and the chat box stays at the bottom.

These rules change how the screens look, not what they say or do. Every screen in the sketch has the same words as before.

## Where the sketch is silent

Settings, the Teams drawer, the Jira page and sign-in keep what the app has today.

The workflow drafter screens don't yet show these parts of ADR 0051's first build step:

- the "Draft it as an n8n workflow" button on a can't answer;
- the sender's note on each flag;
- the Teams card for a set-up approval;
- adding a write key in Settings.

## Decisions for the workflow drafter screens

The team lead reviewed the drafter screens (ADR 0051) and the thumbs (ADR 0050) on 16 Nov 2026 and chose these. Build them as written.

1. **The report is a summary that opens.** In short comes first, then one row per section with a short gist, such as "3 for an Approver · 6 fixed for you · 6 passed". A row opens on a click, and Settings opens by itself while anything is still needed. The same layout serves the chat card, the side panel and the full page. We also considered one page with every section open. It was easy to read once, but in a chat card it ran to several screens.
2. **A reason takes the place of a button that can't work yet, never a disabled button** (principle 9). Send for approval shows "Answer 2 questions first", Approve shows "Accept 2 more flags first", the Planner's set-up card shows "Answer 1 question first", and a change card shows the same until its question is answered.
3. **Declining a set-up approval needs a reason,** picked from a short list, as ADR 0051 says. Declining a run keeps its optional reason, as before.
4. **The channel question uses Slack.** n8n's Microsoft Teams block can't run, because it posts only with a person's own sign-in (ADR 0051, section 2), and the ADR's examples use Slack.
5. **The draft card shows the workflow on the sketch's small step line,** not on an n8n canvas. "Start from the Portal" is a second trigger, so it appears only in the report's Step by step.
6. **A guess shows "I guessed" and Change,** as ADR 0051's settings table says, in place of principle 4's "Filled in by me".
7. **A key that the person asked an Operator for waits, and the next question comes up.** When only that key is left, the card says "Waiting for an Operator to add a key".
8. **A change asked for in the chat, or Done in n8n, makes a new revision card.** The older card settles into one line, so only the newest card asks anything. A new revision cancels a set-up approval that is still waiting.
9. **The optional reason under a thumbs down goes in the Langfuse score's comment,** masked as ADR 0050 masks traces. ADR 0050 itself writes only the rating. The drafter's own cards have no thumbs, because drafts have their own review queue (ADR 0051, section 10).
10. **Two new state words:** "Drafting" while the drafter works, and "In n8n" while a draft is open in the person's own n8n space. A sent draft is "Waiting for a yes", and an approved one is a "Draft" on Workflows until someone turns it on.
11. **In the sketch, Dan approves first and Bob second,** because "View as" has no second Approver. If Bob approves first, the card says "You approved it. A second Approver decides next."
12. **"What I can do" lists drafting and Explain,** because the sketch shows them working. In the Portal they stay Planned until their pull requests land (ADR 0051).
13. **The set-up approval in the side panel shows what the Approver decides on:** In short, the line about the steps that won't ask for a yes on each run, the flags to tick, and what it reads, writes and posts. More details adds the rest of the report.

## The n8n login line

Under every Open in n8n button the sketch says `Opens in n8n as {login}.`, with a made-up email. The Portal and n8n sign in separately, and Open in n8n moves the workflow into the n8n space of one account, so only that account can see it. The line names it. It shows nothing while the platform does not know the login. The sketch's Edit in n8n flow for a draft has no Open n8n button, and the Portal's has the same line under it.

## What it replaces

Prototype version 4 in `docs/design/ai-native-redesign/`, with its spec and build plan, is kept only as a record. So is version 3 of the earlier prototype in `docs/design/portal-routines/`.

## What still holds

- The product safety rules in `AGENTS.md`.
- The principles in `docs/design/ai-native-principles.md`.

Where following the sketch literally would break one of them, the rule wins, and the pull request says why.
