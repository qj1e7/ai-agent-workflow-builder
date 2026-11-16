# Chat first, on the desktop

**Status:** the design target since 13 Nov 2026. The team lead chose it on that day, and the app is built from it.

`prototype.html` is the clickable sketch "Chat first, on the desktop", version 3. Its shared copy is https://claude.ai/artifact/76LFBEeXhPxGKYdwB6EsRg. Open the file in a browser. It needs no server.

## How to use it

- It is the source of truth for screens, flows, words and motion. Build what it shows, in its words.
- Use the controls above the app window:
  - "View as" switches between Alice, Alice with n8n access, and Bob, an Approver.
  - "Play" runs each flow: Morning check, Ask in my words, Change by talking, Something it can't do, Bob declines, Browse, Edit in n8n, Draft a workflow, Bob approves a draft, Second Approver, and Explain.
  - "Speed" set to Instant is best for screenshots.
  - "Report" switches the workflow report between two layouts for the team lead to choose from: one page with every section open, or a summary whose sections open on a click.
  - "Tracing" turns the thumbs under each Planner answer on or off, as the capability registry will (ADR 0050).
- The list under the window, "What's new in version 3", says what each flow is meant to show. Its second part covers the workflow drafter screens from ADR 0051, added on 16 Nov 2026.
- The sketch uses sample data only. The demo bar, Play, Speed, Report and Tracing are for the sketch, not the app.

## Where the sketch is silent

Settings, the Teams drawer, the Jira page and sign-in keep what the app has today.

## What it replaces

Prototype version 4 in `docs/design/ai-native-redesign/`, with its spec and build plan, is kept only as a record. So is version 3 of the earlier prototype in `docs/design/portal-routines/`.

## What still holds

- The product safety rules in `AGENTS.md`.
- The principles in `docs/design/ai-native-principles.md`.

Where following the sketch literally would break one of them, the rule wins, and the pull request says why.
