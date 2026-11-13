# Implementation plan for the AI-native redesign

Status: second round, 11 Nov 2026. The first round, N0 to N22, turned version 4 of the prototype into the built app between 7 and 9 Nov (section 6.1). ADR 0043 (accepted 12 Nov) then redrew the prototype as a chat with a rail. This round says what it takes to rebuild the Portal to the redrawn prototype, and what the backend needs for it. By 12 Nov these have landed: R1 (#211), R2 (#214), R3 (#216), R9 (#212), R10 (#209), R11 (#217), R17 (#215), and R0, which accepts ADR 0043. The rest of this round is not built yet. Sections 1 to 4 still describe the code before this round.

The reader is a developer on the team. Every path below was checked against `main` at commit `98961ef` on 11 Nov 2026. A file that does not exist yet is marked **(new)**. Anything I could not confirm in the code is in section 11.

The plan keeps three layers apart, as the spec does:

- **Built** means code in `portal/`, `platform-api/` or `agent-runtime/` today.
- **Prototype** means the clickable design in `prototype.html`. It is scripted and connected to nothing. Its scenario ids (`SHELL-pinned`, `APPR-ask` and so on) are in `checks/paths-v4.cjs`, and `checks/results/v4-roles.md` lists all 171.
- **Planned** means a proposed ADR or a "Later" item. Nothing implements it.

All four steps of the redraw are merged, the last on 12 Nov, with its follow-up (#207 and #208, roles: the Approver's question-only box, read-only pages for Approvers, deny by default, and n8n views only for people with n8n access). On 11 Nov the team lead dropped the phone layout from step 4. The Portal is a responsive web view, from a narrow browser window to a wide screen, and an Approver on a phone decides in Teams. This plan adds no phone-only work.

## 1. Starting point

What the built app has for each spec section today, and what the redrawn prototype adds.

| Spec section | Built today | The redrawn prototype adds |
|---|---|---|
| 3. Rail and pages | A menu of Home, Workflows, Software watchlist and Agent library, with a bottom tab bar under 900 px (`portal/src/shell/routes.tsx`, `PAGES` and `menuFor`; `Menu.tsx`, `Menu` and `TabBar`; `Menu.module.css`). One Needs you count, from `needsTotal` in `portal/src/screens/home/home.ts`, which `Menu.tsx` puts on Workflows for an Operator and on Home for an Approver. Settings is reached by the header's gear. Every item opens as a page. | A rail of Chat, Workflows and Watchlist, each with a count. The Agent library moves into Settings as How it works. The side panel for items opened from the chat, and Back to the chat. The pinned Needs you line. Needs you grouped Do now and Set up. |
| 5. Home | The Planner box, chips, the thread and the answer cards (`portal/src/screens/home/HomePage.tsx`, `PlannerBox.tsx`, `threadState.ts`, `AnswerCards.tsx`, `StateAnswers.tsx`). Needs you shows only while the thread is empty, at most 3 rows (`home.ts`, `HOME_NEEDS_SHOWN`). The offline Home and the Approver-only Home without a box. The thread lives in a reducer and is never saved. | The box docks at the bottom after the first message. The conversation survives a trip to Workflows and back. New chat keeps an unfinished card as a draft. |
| 6. Planner's answers | `POST /api/v1/planner/answer` with 13 reply kinds (`platform-api/src/platform_api/builder/planner.py`, `PlannerReply`), including question answers (ADR 0042). | Part marks on every answer that reads a request, one question at a time, the edit card, commands that fail closed, live cards, and the panel opening by itself while the Planner builds. |
| 7. Set-up card | `SetupCard.tsx` with What will happen, When, What needs a yes, How this workflow works and the footer. Marks are chip styles only (`SetupCard.tsx`, `data-state`). | A row per part with a tick, a cross or a question. "Set up the part I can". The Left out line after turning it on. |
| 8. Workflows | Needs you in full, Drafts, Waiting on others, Following up and All workflows (`portal/src/screens/workflows/WorkflowsPage.tsx`, `Sections.tsx`). A row's last run is only a pill, and a succeeded or declined run has none (`workflow.ts`, `rowsOf`; `Status.tsx`). | Each workflow's last run on one line, the same words as the chat's check card. Needs you grouped. A last row that leads to the chat. |
| 9. Workflow page | Banner, Pause, More actions, schedule editor, approval line, recent runs and Technical details (`WorkflowPage.tsx`). The schedule editor overwrites the schedule (`PUT /api/v1/use-cases/{use_case_id}/schedule`). No versions. | Versions, with each change and who made it. The Left out line. |
| 10. Run page | Two levels, the station strip (`portal/src/screens/run/RunLine.tsx`), the troubleshooter's four answers (`Outcome.tsx`), Retry and Report to support, and the approval panel (`ApprovalGate.tsx`). Decline is one press, with no reason (`decision.ts`). | The run line as flow. Three answers ending in Safe to retry. Not checked, Ask the requester and an optional decline reason on the approval. One declined record everywhere. |
| 11. Software watchlist | Needs attention, Software we watch and How it's checked, add by name, Use the new address (`portal/src/screens/software/SoftwarePage.tsx`). | A count line under the title, what checks each row, and the declined record on each row. |
| 12 and 13. How it works and Settings | The Agent library page (`portal/src/screens/agents/AgentsPage.tsx`) and Settings with Connections, People and roles, and AI model (`portal/src/screens/settings/settings.ts`). | How it works as a Settings tab for Operators. People and roles renamed People and permissions. |
| 5.3 and 13. Roles | An Approver-only Home with no box (`HomePage.tsx`, `ApproverHome`). `POST /api/v1/planner/answer` is for Operators only. Each change route declares its own role (4.10). No n8n access. | The box for questions only, read-only pages with one note each, every action closed to anyone but an Operator unless a table opens it, each person's own chat, and n8n access on the People list (Planned). |
| 14. Teams drawer | The card and its outcome. A declined card gets a red "Declined by X" block (`platform-api/src/platform_api/orchestration/teams.py`, `approval_card`). | The declined record with its reason. |

## 2. Frontend, screen by screen

Each screen lists the files to change, what to reuse, what is new, and how state moves. New components are listed at the end of this section. Every screen keeps reading the routes it reads today unless section 3 names a change.

### 2.1 The rail and Settings (spec 3, 12, 13)

- **New.** `portal/src/shell/Rail.tsx` **(new)** replaces `Menu` and `TabBar` in `portal/src/shell/Menu.tsx`. It has three items, Chat, Workflows and Watchlist, each a link with its count in the accessible name (", 5 need you"). Wider than 900 px it is a column on the left. At 900 px and narrower it is a bar across the top, as the prototype draws it.
- **Change.** `portal/src/shell/routes.tsx`.
  - `PAGES` becomes chat (`/`), workflows and software in the rail. Settings stays out of the rail, reached by the gear.
  - `/agents/:agentId?` redirects to `/settings?tab=how`, keeping the agent id, for Operators. Others go to `/`.
  - The count rule: Workflows shows `needsTotal(home)` for an Operator, Chat shows it for anyone else, and Watchlist shows what needs action on the watchlist (2.9).
- **Change.** `portal/src/screens/settings/settings.ts`, `SETTINGS_TABS`: Connections, People and permissions (renamed from People and roles), AI model, and How it works for Operators only.
- **Move.** The Agent library's tabs (`AgentsPage.tsx`, `CapabilitiesTab`, `ToolsTab`, `AgentCard.tsx`) render inside the How it works tab. The page shell `AgentsPage` goes.
- **Change.** `portal/src/shell/Header.tsx` keeps the brand, Teams, the gear and `PersonChip`, and loses `Menu`.
- **State.** The rail reads `['home', user]` through `useHome`, as `Menu` does now, and the watchlist count from `['watchlist', user]`.
- **Must match.** `SHELL-rail`, `T14`.

### 2.2 Home, the chat (spec 5)

- **Change.** `portal/src/screens/home/HomePage.tsx`. Before the first message nothing changes. After it, the box docks at the bottom with "Ask for something else", and Needs you gives way to the pinned line (2.3).
- **Move.** The thread's state (`threadReducer` in `threadState.ts`) moves from `OperatorHome` to a provider above the routes, `portal/src/screens/home/ChatProvider.tsx` **(new)**, so leaving for Workflows or the Watchlist and coming back returns the conversation and its scroll position. It is still never saved, because the chat is not the record.
- **Change.** New chat clears the thread and closes the side panel. A set-up card she hadn't finished is saved through `useSaveDraft` first, with the message "Your draft is saved. Find it on Workflows."
- **Change.** `portal/src/screens/home/home.ts`. `groupOf(need)` **(new)** gives Do now or Set up, from the need's kind. Stops, approvals, questions to answer and declined test runs are Do now. Connections, moved addresses and confirmations are Set up. `needsOf` keeps its urgency order inside each group. Home's three rows, the pinned line and the Workflows section all read it.
- **Reuse.** `PlannerBox`, `NeedsSection`, `NeedItem`, `RetryButton`, `PlannerBot`.
- **State.** `['home', user]` for Needs you and the pinned line. Nothing new.
- **Must match.** `B-home`, `SHELL-pinned`, `ASK-needs`, `OFFLINE`, `KEYS-A`.

### 2.3 The pinned line, the side panel and Back to the chat (spec 3.2 to 3.5)

- **New.** `portal/src/screens/home/PinnedLine.tsx` **(new)**. It shows the first of the grouped needs, with Open and "N more". Open opens the item in the side panel. "N more" opens `/workflows` with Back to the chat. It shows while the thread has messages and `needsTotal(home)` is above 0, whatever the last answer was.
- **New.** `portal/src/screens/home/SidePanel.tsx` **(new)**. It shows one item at a time. The chat's provider holds it, never the address. Its bar has the title, More details and Close. Escape closes it and returns focus. At 900 px and narrower it is a full-window dialog with the chat made inert behind it, and it opens only when the person presses Open.
- **New.** Panel views, each built from the components the pages already use, so a panel and its page can't disagree:
  - `WorkflowPanel` from `WorkflowRow` facts, `Troubleshooting` and the Pause and Resume buttons;
  - `RunPanel` from `RunLine` (small and upright, 2.8) and `Troubleshooting`;
  - `ApprovalPanel` from `ApprovalGate`, without Why, Who asked and Your part (spec 10.4);
  - `SoftwarePanel` from the watchlist row.
- **Change.** Every link a chat card or the panel renders passes `state: { fromChat: true }`. A page opened that way shows "Back to the chat" in place of its own Back, and the panel is still open on return.
- **Change.** An action in the panel (Approve, Decline, Ask, Retry, Pause, Resume) keeps the panel open, scrolls it to the top and focuses its heading (`useFocusAfterReread` in `portal/src/ui/focus.ts`).
- **Change.** While an item is open in the panel, the card that opened it hides its own Open button and its steps.
- **State.** The panel holds an `{ kind, id }` pair. Each view reads its own query keys (`['use-case', user, id]`, `['run', user, id]`, `['approval', user, id]`, `['watchlist', user]`).
- **Must match.** `SHELL-panel`, `SHELL-more`, `APPR-panel`, `RUN-retry-panel`, `RUN-retry-from-chat`, `RUN-line-panel`.

### 2.4 The Planner's answers (spec 6)

- **Change.** `portal/src/screens/home/answers.ts` and `AnswerCards.tsx`.
  - **Part marks.** One `PartsList` **(new)** draws every answer's parts as a tick, a cross with its reason, or a question. It reads the parts the runtime returns (4.1). Until R4 lands, it draws today's rows as ticks, today's can't rows as crosses, and a missing row as a question.
  - **Leftover crosses.** The part, can't, check, why, what needs me and question answers draw the clauses they didn't read above their card, from the same list.
  - **Live cards.** Each card's sentence is fixed text worked out at render from the queries the pages read, as the state answers already do (`StateAnswers.tsx`). The confirmation after Turn it on reads the workflow's state, so a pause on its page shows in the chat.
- **New.** `EditCard.tsx` **(new)** draws the `edit` answer (4.2). It shows "Change <name>", When it runs with Before and After, Save change and Never mind. Save calls the schedule route (3.2). The saved card shows "Saved as version N." with Undo, which calls the undo route.
- **Change.** While the Planner builds a set-up card and the window is wider than 900 px, the side panel opens by itself on the draft's steps, and turns into the workflow's panel after Turn it on. Focus stays on the card's heading.
- **State.** `usePlannerAnswer` stays a mutation. The edit card's Save and Undo invalidate `['use-case', user, id]` and `['use-cases', user]`.
- **Must match.** `ASK-status`, `ASK-why`, `ANS-status`, `ANS-status-commands`, `ANS-name-words`, `ANS-questions`, `ANS-live`, `ANS-live-done`, `ANS-panel`, `ANS-panel-focus`, `ANS-narrow-cards`, and every `ANS-edit-*` scenario.

### 2.5 The set-up card (spec 7)

- **Change.** `portal/src/screens/home/SetupCard.tsx`. The parts list replaces the What will happen sentence and the When section. Each row has its mark (2.4). Chips stay green for her words, blue for her choice, and grey for "Filled in by me".
- **Change.** `portal/src/screens/home/card.ts`. `nextQuestion(card)` **(new)** gives the one question to ask now, in the spec's order: how often, the day for a weekly run, the time, which tickets, the Jira project, what it does. A bare hour asks "At 9:00 or 21:00?". Two days or two times come back from the runtime as a clash (4.1) and ask which one. `setupLeft` stays the one source for the footer, the button and the draft's line on Workflows.
- **Change.** While any part has a cross, the button says "Set up the part I can" and the footer says what is left out. `createBody` sends the crossed parts as `left_out`, so the workflow keeps them (4.6).
- **Change.** The tag on a new agent says "New agent, saved under How it works, in Settings, when you turn this on".
- **Must match.** `A`, `E`, `T2`, `T3`, `C-self`, `ANS-cross`, `ANS-left-out`, `ANS-verbs`, `ANS-whole-clause`, `ANS-stale`, `ANS-none-hers`, `ANS-one-question`, `ANS-no-time`, `ANS-clash-day`, `ANS-clash-time`, `ANS-watch-parts`, `ANS-asks`.

### 2.6 Workflows (spec 8)

- **Change.** `portal/src/screens/workflows/WorkflowsPage.tsx`. Needs you is grouped with `groupOf` (2.2). A last row, "Ask the Planner for a new one", goes to the chat, for Operators.
- **Change.** `portal/src/screens/workflows/workflow.ts`. `lastRunLine(useCase)` **(new)** gives one line, such as "Last run Mon 26 Oct · Declined by Bob" or "No runs yet". It reads the use case's `last_run` (4.5). `WorkflowRow` and the chat's check card (`StateAnswers.tsx`) both call it.
- **Change.** The row pill set becomes On, Waiting for a yes, Stopped and Paused, with Test run.
- **Must match.** `WF-last-run`, `B`, `H2`, `T6`, `T9`, `T10`, `T11`.

### 2.7 Workflow page (spec 9)

- **Change.** `portal/src/screens/workflows/WorkflowPage.tsx`.
  - The Left out line under the purpose, from the use case's `left_out` (4.6).
  - A Versions list, once there is more than one, from `GET /api/v1/use-cases/{use_case_id}/versions` (3.2).
  - The banner words follow the spec, such as "On. Next run ..." and "... it's answering again now".
  - The approval line adds "Every Approver is asked in Teams. The request waits until one of them decides, and nothing changes before that."
- **Change.** `ScheduleChangePanel` saves through the same route as today. That route now publishes a version (4.4). The message after saving stays "Saved. Next run ...", as in the prototype and spec 9, and the Versions list names the version.
- **Must match.** `H`, `T12`, `ANS-left-out`, `ANS-edit-save`, `DECLINED-test-run`.

**n8n views.** Only someone with n8n access sees n8n, and only an Operator can hold it. The Portal has no n8n link today, and n8n views are Planned (ADR 0026, 0027), so this round builds none. R18 stores the access when the first n8n view is built (4.11).

### 2.8 Run page (spec 10)

- **Change.** `portal/src/screens/run/RunLine.tsx`. Each link between two steps takes the state of the step it leads into: marching dashes into the step at work, slower amber dashes into a step waiting for a yes, red into a stop, faint dots into skipped steps, and solid once the next step is done. Reduced motion stops the march and keeps the look (`motionAllowed` in `portal/src/ui/motion.ts`). A `small` variant draws it upright without faces for the side panel.
- **Change.** `portal/src/screens/run/Outcome.tsx`, `Troubleshooting`. Three `dt` and `dd` pairs: What happened, What was affected, Safe to retry. Retry or Report to support sits under them. Someone who isn't an Operator sees the answers with a note, such as "An Operator can retry the run.", and no buttons.
- **Change.** `portal/src/screens/run/ApprovalGate.tsx` and `decision.ts`.
  - **Not checked** comes after What will change. It reads the approval's `not_checked` and the capabilities its workflow uses that aren't Ready (4.8).
  - **Questions.** "Not sure yet? Ask Carol a question" opens a question box. Sending keeps the request waiting. The thread shows on the request, read only once it is decided.
  - **Decline reason.** Decline opens "Why are you declining? Optional." with a few quick reasons, then Decline and Back. `decisionFor` sends `reason` with a decline.
- **Change.** `portal/src/screens/run/words.ts` and `RunPage.tsx`. One `declinedRecord(run)` **(new)** gives "Declined by Bob. Nothing was written. Reason: ..." for the run page, the panel, the toast, Needs you, the watchlist row and the Workflows row. A declined run's write step says "Nothing written", its last step "Ended", and the pill is a grey Declined.
- **New.** `portal/src/screens/run/AnswerQuestion.tsx` **(new)**. The requester's answer box, opened from the Needs you item "Bob asked you about ...".
- **Must match.** `RUN-three`, `RUN-three-approver`, `RUN-line`, `RUN-line-panel`, `APPR-not-checked`, `APPR-not-checked-jira`, `APPR-ask`, `APPR-answer`, `APPR-thread-kept`, `APPR-decline`, `APPR-decline-none`, `APPR-decide-nav`, `KEYS-APPR`, `DECLINED-sw`, `DECLINED-test-run`, `C`, `C-self`, `F`, `KEYS-C`.

### 2.9 Software watchlist (spec 11)

- **Change.** `portal/src/screens/software/SoftwarePage.tsx`. A count line under the title, such as "3 have a newer version · 4 can't be checked", from the rows. Each row names what checks it ("Checked on GitHub · langchain-ai/langgraph"). After a decline, each row with a new version shows the declined record.
- **New.** `watchAttention(view)` **(new)** in `portal/src/screens/software/software.ts` counts what needs action on the watchlist, for the rail.
- **Must match.** `G`, `T4`, `T5`, `DECLINED-sw`.

### 2.10 Teams drawer (spec 14)

- **No Portal change.** The drawer draws the card the server built. The declined block gains the reason on the server (4.7).
- **Change.** `portal/src/shell/TeamsCard.test.tsx`, so its fixture has the reason.

### 2.11 Roles (spec 3.1, 5.3, 13)

- **Change.** `portal/src/screens/home/HomePage.tsx`. `ApproverHome` gains the box, with the placeholder "Ask about your approvals, or how the workflows are doing" and three question suggestions. It reuses `PlannerBox`, the thread and the answer cards, plus two new cards: the person's decisions (`decided`) and the requests to open (`decide`). The refusal is the `operators` answer.
- **Change.** The pages an Approver reads (`WorkflowsPage.tsx`, `WorkflowPage.tsx`, `SoftwarePage.tsx`, Settings) show no control that changes anything and no dead button, and one note each, such as "Only Operators change workflows. Ask Alice or Carol." People and permissions shows each person's roles as text.
- **Change.** The watchlist count on the rail shows only for someone who can act on it.
- **Change.** `ChatProvider` (2.2) keeps one conversation per signed-in person, so a dev sign-in that changes person never shows another person's chat.
- **Change.** `portal/src/shell/Shell.module.css` and `Header.module.css`. On a wide screen the content keeps one column, at most 1180 px wide. The header spans the window, with the brand top left above the rail and the tools at the right edge (changed 13 Nov 2026, after the team lead found the centred header floating on a wide screen). The chat and its side panel share that column. A Workflows list with no row actions drops its empty action column.
- **Must match.** `ROLE-*`, `KEYS-ROLE`, `FIX-deny-default`, `FIX-bob-settings`, `FIX-rail-count`, `FIX-wide`.

### New components, all of them

1. `portal/src/shell/Rail.tsx` **(new)**
2. `portal/src/screens/home/ChatProvider.tsx` **(new)**
3. `portal/src/screens/home/PinnedLine.tsx` **(new)**
4. `portal/src/screens/home/SidePanel.tsx` **(new)**, with its four views
5. `portal/src/screens/home/PartsList.tsx` **(new)**
6. `portal/src/screens/home/EditCard.tsx` **(new)**
7. `portal/src/screens/run/AnswerQuestion.tsx` **(new)**

### 2.12 Shapes to carry over from the prototype review

Reviews of the prototype found that its worst bugs came from facts kept in more than one place. The Portal should not copy those splits.

- **Who can't decide.** One function gives the owner, the person who started the run and anyone who retried it, the same set `platform-api/src/platform_api/orchestration/service.py` refuses.
- **One state per workflow.** A workflow's status, its last run, its open request and its next action come from one place, keyed by its id. Needs you, the row, the panel, the rail count and the Planner's answers derive from it.
- **One declined record and one set of troubleshooter answers.** Every place reads the same function (spec 3.7).

## 3. API dependencies

The rules for ownership come from `platform-api/pyproject.toml`. The import-linter contracts layer the contexts as builder, then orchestration, then monitoring. A context reaches another only through its package `__init__`. Builder is the top layer, so builder routes may compose all three. Monitoring may import neither of the others. CI runs `uv run lint-imports` on every PR.

### 3.1 Routes by screen

| Screen | Existing routes it keeps using | New or changed routes |
|---|---|---|
| Rail and header | `GET /api/v1/me`, `GET /api/v1/home`, `GET /api/v1/watchlist`, `GET /api/v1/teams-stub/messages` | None |
| Chat and answers | `POST /api/v1/planner/answer`, `POST /api/v1/planner/check-part`, `GET /api/v1/capabilities`, the drafts routes, `POST /api/v1/agent-use-cases` | `POST /api/v1/planner/answer` (changed: parts, the edit answer, and Approvers' questions), `POST /api/v1/agent-use-cases` (changed: `left_out`), `GET /api/v1/decisions` (new) |
| Side panel | The routes of each page it summarises | None |
| Workflows | `GET /api/v1/home`, `GET /api/v1/use-cases`, `GET /api/v1/runs`, the drafts routes | `GET /api/v1/use-cases` (changed: `last_run`) |
| Workflow page | `GET /api/v1/use-cases/{use_case_id}`, the lifecycle routes, `POST /api/v1/runs/{run_id}/retry` | `PUT /api/v1/use-cases/{use_case_id}/schedule` (changed: publishes a version), `GET /api/v1/use-cases/{use_case_id}/versions` (new), `POST /api/v1/use-cases/{use_case_id}/versions/{version}/undo` (new) |
| Run page | `GET /api/v1/runs/{run_id}`, `GET /api/v1/runs/{run_id}/events`, `GET /api/v1/runs/{run_id}/troubleshoot`, `POST /api/v1/runs/{run_id}/retry`, `POST /api/v1/team-requests` | `GET /api/v1/runs/{run_id}/troubleshoot` (changed: wording), `GET /api/v1/approvals/{approval_id}` (changed), `POST /api/v1/approvals/{approval_id}/decisions` (changed), `POST /api/v1/approvals/{approval_id}/questions` (new), `POST /api/v1/approvals/{approval_id}/questions/{question_id}/answer` (new) |
| Needs you | `GET /api/v1/home` | `GET /api/v1/home` (changed: questions to answer, declined test runs) |
| Software watchlist | The watchlist routes | None |
| Settings and How it works | The settings, people, connections, capabilities, agent cards and tools routes | None |

### 3.2 New and changed routes, with sketches

Field names below are sketches. Each route gets contract stories in `platform-api/src/platform_api/contracts/`, which write the fixtures in `contracts/fixtures/` that the Portal's unit tests read.

**`POST /api/v1/planner/answer` (changed).** Owner builder. Operators only today (`builder/planner_http.py`, `operators_only`).
- Every answer that reads a request gains `parts`, one per clause, each with a mark and a reason (4.1). The existing `rows` and `cant` stay until the Portal reads `parts`.
- A new `edit` kind (4.2):

```json
{"answer": "edit", "use_case_id": "uc_01", "name": "Morning new-ticket check",
 "before": {"day": "weekdays", "at": "08:00"}, "after": {"day": "monday", "at": "08:00"},
 "parts": [{"clause": "run on Mondays only", "mark": "will_do"}], "holds_save": false}
{"answer": "edit", "use_case_id": null, "missing": "morning check"}
{"answer": "edit", "use_case_id": "uc_01", "cant": "only_schedule"}
```

ADR 0043 opens this route to an Approver who can't set up workflows, for questions only (R16). For someone who isn't an Operator, builder answers only the state questions, question answers and what the Planner can do, plus two new kinds: `decided`, their own decisions, and `decide`, the requests waiting for their yes. Anything else answers `operators`, which the Portal words as "Operators set up workflows. Ask Alice or Carol.", with the Operators' names from the People list. Each clause gets its own answer. A change alone gets `operators`. A question with a change beside it gets the question's own answer, with each change marked as a cross that carries the same words. Nothing changes state.

**`GET /api/v1/decisions` (new).** Owner orchestration. Signed in. This person's decisions, newest first, from `orchestration.approval_decisions`: the run, the workflow, the verdict, the reason and when. The `decided` answer and its filters read it.

**`POST /api/v1/agent-use-cases` (changed).** Owner builder. Takes `left_out`, the crossed parts in her words, and keeps them with the workflow. `GET /api/v1/use-cases/{use_case_id}` returns them.

**`GET /api/v1/use-cases` (changed).** Owner builder. Each workflow gains `last_run`, `null` when it has never run:

```json
{"last_run": {"run_id": "run_07", "state": "rejected", "at": "2026-10-26T01:41:00Z", "test": false,
 "declined_by": "bob", "proposed": 1, "written": 0, "tickets": true,
 "you_can_decide": false, "retryable": false, "reason": null}}
```

- `run_id`, `state` and `at` (when it started) name the newest run, whatever its state.
- `test` is true only when the run was started with Do a test run. Run now, a check of the watchlist and a scheduled run are never tests.
- `declined_by` is who declined it, and null for any other run. The decline reason is not in this shape. R12 adds it.
- `proposed` and `written` count the writes the run asked a yes for and the writes it made. `tickets` is true when each of them is a ticket, so the Portal can say tickets rather than changes.
- `you_can_decide`, `retryable` and `reason` let a row show its one action and the banner say why a run stopped without reading `GET /api/v1/runs`. `you_can_decide` is for the person who asked, so `GET /api/v1/use-cases/{use_case_id}` and every change route answer for their caller too.

One indexed query per call serves it: the newest run of each workflow asked for.

**`POST /api/v1/use-cases/{use_case_id}/runs` (changed).** Owner builder. Takes an optional body `{"test": true}`, which only Do a test run sends. With no body the run is not a test. The run keeps the flag, and a retry keeps it too.

**`PUT /api/v1/use-cases/{use_case_id}/schedule` (changed).** Owner builder. Saving publishes a new version of the workflow (4.4) and answers with it. The Portal's schedule editor and the edit card both call it.

**`GET /api/v1/use-cases/{use_case_id}/versions` (new).** Owner builder. Signed in. Newest first:

```json
{"versions": [{"version": 2, "at": "...", "by": "alice", "via": "chat", "change": {"schedule": {"from": {"day": "weekdays", "at": "08:00"}, "to": {"day": "monday", "at": "08:00"}}}, "undid": null, "running": true}]}
```

**`POST /api/v1/use-cases/{use_case_id}/versions/{version}/undo` (new).** Owner builder. Operators only. It is Undo for a schedule change, unlike the existing `POST /api/v1/use-cases/{use_case_id}/restore`, which brings back a deleted workflow. It publishes the schedule of the version before `version` as a new version, with `undid` set. It answers 409 when a later version exists, so Undo never throws away someone else's change.

**`POST /api/v1/approvals/{approval_id}/decisions` (changed).** Owner orchestration. `DecisionIn` (`orchestration/http.py`) gains an optional `reason`, up to 200 characters, accepted only with `"verdict": "decline"`. Today the model forbids extra fields (`wire.py`), so an old Portal sending none is unaffected.

**`POST /api/v1/approvals/{approval_id}/questions` (new).** Owner orchestration. Only someone who may decide the open step may ask. It takes `text` and an `Idempotency-Key`. The request stays waiting.

**`POST /api/v1/approvals/{approval_id}/questions/{question_id}/answer` (new).** Owner orchestration. Only the requester may answer: the person who started the run, or its owner for a scheduled run. An answer never decides anything.

**`GET /api/v1/approvals/{approval_id}` (changed).** Owner orchestration. `ApprovalView` gains:

```json
{"questions": [{"question_id": "q_01", "asked_by": "bob", "asked_at": "...", "text": "Is 1.3 tested?", "answer": null}],
 "not_checked": ["Grafana", "LangServe"],
 "steps": [{"index": 0, "status": "declined", "decided_by": "bob", "reason": "Wrong version"}]}
```

**`GET /api/v1/home` (changed).** Owner builder. Adds `questions_for_me` (questions on requests this person started or owns, not yet answered) and `declined` (this person's test runs declined since they last looked). Both count in Needs you.

**`GET /api/v1/runs/{run_id}/troubleshoot` (changed).** Owner monitoring. `answers.can_fix` becomes `answers.safe_to_retry`, worded as an answer to "Safe to retry" (4.3). The Portal and the contract change in the same PR.

**Agent runtime routes (changed, behind the runtime key).** `POST /v1/planner/answer` returns `parts` and the `edit` kind. Their types go in `agent-runtime/src/agent_runtime/contract.py` and `AgentApiSchema`, so `contracts/agent-api.schema.json` is regenerated.

Retry, Report to support, Pause and Resume in the side panel need no new route. They call the routes the pages call.

## 4. Backend changes

### 4.1 Every clause of a request is accounted for (agent runtime)

**Today.** Code checks the request clause by clause, word by word. `leftovers` in `agent-runtime/src/agent_runtime/reading.py` returns, for each clause, the run of words no filled structure explains. `answers.py` turns each into a can't part with "I can't do this part yet.", or a refusal when it names a yes or a person in a request that writes. Three gaps let a part through without a mark:

- **Negations are filler.** `FILLER` in `reading.py` holds "haven't", "not", "no" and "without". If the model reads "haven't been updated for 10 days" as updated within 10 days, every content word is explained, and the row says "updated in the last 10 days" as understood. The meaning flips, and nothing is marked.
- **The watchlist path covers whole clauses** that hold the release word or the software's name (`answers.py`), so a time or a destination in that clause goes unmarked.
- **A state question drops the task's spans.** When the model asks about her workflows, the leftover spans are computed and then dropped (`answers.py`).

**Change.**

- Every answer that reads a request returns `parts`: one entry per clause, marked `will_do`, `cant`, `question` or `asked_next`, with its reason. A clause no structure explains is a `cant` with the reason `not_followed`, which the Portal words as "I didn't follow this part."
- A negation in a clause must match the direction of the filled search. "No update for 10 days" and "haven't been updated for 10 days" must fill `updated_before`. A clause whose negation no structure explains is a cross, never a tick.
- The watchlist answer marks each clause, so a time or another destination gets its cross: "The Software watchlist checks all your software together, every Monday at 9:00. I can't give one software its own time yet."
- A state question keeps the crosses of any task words it didn't answer: "Ask this on its own, and I'll answer it."
- Two days or two times in one schedule come back as a clash, never the first one.

### 4.2 The edit answer (agent runtime and builder)

**Today.** No answer changes a workflow that already exists. `PlannerAnswer` has 11 kinds (`agent-runtime/src/agent_runtime/contract.py`) and none edits.

**Change.**

- The runtime returns `edit` when the request has a change word and names a workflow: its target words and the new schedule, with the parts of 4.1.
- Builder matches the target words to one of the person's workflows by whole words, works out before and after from the saved schedule, and answers `missing` when nothing matches.
- **Commands fail closed.** Code removes the question words and the workflow's name. If a change word is left, the request is an edit, never a status answer. A schedule word inside a workflow's own name is neither.
- In this first version the edit changes only the schedule. Any other change answers `only_schedule`, and monthly answers that it can't run things monthly yet.

### 4.3 The troubleshooter's three answers (monitoring)

**Today.** `platform-api/src/platform_api/monitoring/troubleshooter.py` already returns three text answers, `what_happened`, `what_affected` and `can_fix`, with `retry` and `next`. The Portal draws a fourth answer, "What should you do", from `next` (`Outcome.tsx`).

**Change.**

- `can_fix` becomes `safe_to_retry`. Its text answers the question: "Yes. A retry runs the work again, and any write still waits for a yes.", or "No. ..." where today it says "This kind of stop can't be retried."
- The Portal shows three answers, with Retry or Report to support under them.
- "Not yet" while a system is still down needs the connection's state. Monitoring may not import orchestration, so the Portal adds it from the connection state it already reads, as the workflow page's banner does.

The rest stays a fixed table, and it claims no cause it can't know.

### 4.4 A schedule change publishes a new version (builder and orchestration)

**Today.** `PUT /api/v1/use-cases/{use_case_id}/schedule` (`builder/lifecycle_http.py`) calls `Builder.save_schedule` (`builder/service.py`), which overwrites the row in `orchestration.schedules` through `ScheduleBook.save` (`orchestration/schedule_store.py`). It makes no version. It doesn't touch `builder.use_case_versions`, and only watchlist software changes bump a version (`builder/watchlist.py`). There is no versions list and no undo. A watchlist use case is refused with 409, because the watchlist has its own schedule route.

**Change.**

- `Builder.save_schedule` writes a new row in `builder.use_case_versions`, with who saved it, where (`page` or `chat`) and the schedule before and after in `builder.use_case_version_changes`, sets `current_version`, then saves the schedule as today. The builder can't write orchestration's schedules, so the schedule saves in its own transaction just before the version commits, and a version never names a schedule that didn't save. The migration is `platform-api/src/platform_api/migrations/builder/versions/0010_use_case_version_changes.py` **(new)**.
- Saving the same schedule again publishes no version. A take-over, the same schedule saved by a new owner, isn't a version either: each run records who started it, and the Schedule row's "Set by" shows the current owner.
- The watchlist's own `PUT /api/v1/watchlist/schedule` makes no version. Only its software changes do (`builder/watchlist.py`).
- The versions route and the undo route of 3.2.
- The edit card saves through the same route, with `via: "chat"`. There is one path for a schedule change.

### 4.5 Each workflow's last run (builder)

**Today.** No route gives it. The Portal works it out from `GET /api/v1/runs`, which takes no filter and returns every run with no limit (`orchestration/http.py`, `store.py`). Builder already works out each workflow's last run for the Planner's facts (`builder/planner_facts.py`).

**Change.** `UseCaseView` (`builder/models.py`) gains `last_run`, from the same query the Planner's facts use, so the Workflows rows, the check card and the Planner read one source. The index on `(use_case_id, started_at DESC)` in `migrations/orchestration/versions/0001_runs.py` serves it.

### 4.6 What was left out (builder)

`POST /api/v1/agent-use-cases` takes `left_out`, the crossed parts in her own words, and keeps them with the use case. The workflow page and the confirmation show them. They are text for people to read. Nothing runs from them.

### 4.7 The decline reason and the requester's question (orchestration)

**Today.** A decision has a step, a verdict and a digest, and nothing else (`DecisionIn` in `orchestration/http.py`). The table `orchestration.approval_decisions` has no column for a reason (`migrations/orchestration/versions/0001_runs.py`). No route lets an Approver ask the requester a question. Team requests can't stand in: they are about a capability or a run, never an approval (`builder/team_requests.py`).

**Change.**

- **The reason.** A nullable `reason` column on `approval_decisions`, written only with a decline. The `run_rejected` event (`orchestration/runs.py`) carries it, and the Teams outcome (`teams.py`) adds "Nothing was written. Reason: ...".
- **Questions.** A new table, `orchestration.approval_questions`: the approval, who asked, when, the text, and the answer with who and when. One migration holds both changes, `platform-api/src/platform_api/migrations/orchestration/versions/0017_approval_reasons_and_questions.py` **(new)**.
- **Needs you.** Builder's Home adds the questions waiting for this person's answer, and their declined test runs.
- **The gate does not change.** `Orchestrator.decide()` in `orchestration/service.py` and the decision rules in `orchestration/approvals.py` keep their behaviour. A question decides nothing and changes nothing on the request. A reason is a note on a decline that already happened. `test_approvals.py` and `test_write_actions.py` pass unchanged.

### 4.8 What wasn't checked (orchestration and builder)

`ApprovalView` gains `not_checked`, from the run's own record: for a software check, the software it couldn't read. The Version checker already marks each such finding `cant_check` (`agent-runtime/src/agent_runtime/watchlist.py`). The Portal adds the capabilities the workflow's system needs that aren't Ready, from `GET /api/v1/capabilities`, so the line names only what the registry and the run say.

### 4.9 What stays untouched, and what would need an ADR

No PR in this plan changes the approval gate or the safety checker. These files keep their behaviour, and their tests must pass unchanged:

- `platform-api/src/platform_api/orchestration/approvals.py`, the decision rules.
- `platform-api/src/platform_api/orchestration/write_actions.py`, the safety checker and the write gateway.
- `Orchestrator.decide()` in `platform-api/src/platform_api/orchestration/service.py`.

ADR 0043 is the decision behind 4.1 to 4.8. Its reason and questions add to the approval request's record, so AGENTS.md wants that ADR accepted before their code lands (R0).

### 4.10 Every change is an Operator's, on the server (builder and orchestration)

The prototype opens each action from one table, `OPEN_TO`, and every action it doesn't list needs an Operator. The Portal can only hide a control. The server is the check.

**Today.** Each route declares its own role. `platform-api/tests/test_auth_declared.py` makes every `/api/v1` route require sign-in and declare the 401, 503 and 403 it answers, but no test says which role a change needs. Most routes that change something declare the role twice. They take an Operator principal, and they list the `OPERATORS_ONLY` responses from `auth.py`. Builder's principals, `Operator` and `WorkflowOperator`, come from its helper `operators_only` in `builder/http.py`. That file's routes and those in `planner_http.py`, `lifecycle_http.py`, `drafts_http.py` and `watchlist_http.py` use them. Orchestration's `Operator`, in `orchestration/http.py`, comes from `require_operator`, and `people_http.py`, `settings_http.py` and the retry route use it. These are open to anyone signed in:

- `POST /api/v1/approvals/{approval_id}/decisions` and `POST /api/v1/confirmations/{id}/decisions`. The domain lets only an Approver decide (`orchestration/approvals.py`).
- `POST /api/v1/team-requests`, `POST /api/v1/team-requests/{id}/replies` and `POST /api/v1/team-requests/{id}/seen`. Only the asker marks a request seen, in the service. Anyone signed in can ask the team, report to support, or reply. That matches ADR 0038, which lets Approvers take part, and the prototype now opens Ask the team to anyone too. The prototype still shows an Approver no Report to support button, so the Portal hides it for them while the route stays open.
- `POST /api/v1/use-cases/suggest` and `POST /api/v1/agent-cards/check`, which read and answer. Whether they change anything is in section 11.

**Change.**

- A test walks the app's routes and lists every `/api/v1` route that changes something (POST, PUT and DELETE). Each must depend on one of the two Operator checks and list `OPERATORS_ONLY`, or be on one allow list that names who else may call it: anyone for team requests (ADR 0038), Approvers for decisions and questions on a request (R13), the asker for marking their own team request seen, and the routes that only read. A new route then fails CI until someone opens it, as the prototype's table does.
- The Portal reads the same roles from `GET /api/v1/me` to hide what the person can't do, and each read-only page shows one note naming the Operators, from `GET /api/v1/people`.

### 4.11 n8n access (orchestration, later)

n8n access is something a person holds, not a third role, and only an Operator can hold it. Its home is the People list: a column on `orchestration.people`, beside `is_operator` and `is_approver` (`migrations/orchestration/versions/0006_people.py`), with a check that it is set only with `is_operator`. Taking away someone's Operator role takes away their n8n access in the same change. The people routes gain a way to set it, the settings history records who did, and `GET /api/v1/me` returns it. Nothing reads it until the first n8n view, so it lands with that view (R18), after ADRs 0026 and 0027.

## 5. ADRs needed

1. **Accept ADR 0043.** Done on 12 Nov 2026 in R0. ADR 0037 now has a dated "Changes on 12 Nov 2026" section for the four places ADR 0043 names (spec 18.2).
2. **ADR 0039, Operators replace connection keys in Settings,** is still needed before "Replace the key" is built. It is outside this round.

Not needed, and why:

- **Versions of a workflow's schedule (4.4).** They use the table that already holds use case versions, and change no service, store or dependency.
- **The edit answer (4.2).** It changes the schedule through the route that already does. It writes only our own records, so it needs no approval gate.

## 6. Build order

### 6.1 The first round, landed

| PR | Title | Merged as |
|---|---|---|
| N0 | ADR 0037, ADR 0036 and the glossary | Inside #133 |
| N1 | ADR 0038, team requests | #135 |
| N2 | The abilities check and vulnerability words | #142 |
| N3 | One Planner answer for each request, with the golden set | #151 |
| N4 | Jira's last update, type and assignee, and the cut-off flag | #140 |
| N5 | Agents find tickets by those fields | #149 |
| N6 | The capability registry | #155 |
| N7 | The Planner on Home, check one part, capabilities | #169 |
| N8 | Drafts without a step number | #139 |
| N9 | One Needs you list | #141 |
| N10 | Home as the Planner's box | #170 |
| N11 | Set up a workflow from the card | #172 |
| N12 | The troubleshooter's answers | #138 |
| N13 | Who asked and what the agents found | #143 |
| N14 | Team requests | #147 |
| N15 | The run page in two levels | #157 |
| N16 | The workflow page by decision | #150 |
| N17 | The GitHub connection check | #137 |
| N18 | Connection checks | #148 |
| N19 | What the platform can do, in the Agent library and Settings | #171 |
| N20 | Find a software's GitHub project | #136 |
| N21 | Add software by name | #152 |
| N22 | Remove New workflow and the understand route | #179 |

The first round's design notes are in this file's history, at `git show 98961ef:docs/design/ai-native-redesign/IMPLEMENTATION-PLAN.md`.

### 6.2 This round

The order keeps `main` working after every PR. Frontend PRs that need no new route come first, so the redrawn shell is in people's hands early. Each backend change lands before the screen that needs it, and a screen that can start on today's API does, then switches.

Every PR runs the repo's standard checks:

- `uv run ruff check .`, `uv run pyright` and `uv run pytest` in each Python project;
- `uv run lint-imports` in `platform-api`;
- `npm run typecheck`, `npm run lint` and `npm test` in `portal`;
- the generated-contracts check from `.github/workflows/ci.yml`;
- `scripts/e2e.sh` for anything a person can see.

The table names each PR's own tests and the prototype scenarios its screen must match. A scenario "matches" when the live lane drives the same steps and asserts the same words.

| PR | Title | Depends on | Routes | Its own tests | Must match |
|---|---|---|---|---|---|
| R0 | `docs(builder): accept ADR 0043 and record its changes to ADR 0037` | None | None | A human accepts the ADR. `unslop` pass, no long dashes. | None |
| R1 | `feat(builder): replace the menu with a rail and move the Agent library into Settings`. Landed as #211. | None | Existing | `shell.test.tsx` (rail items, counts, roles), `SettingsTabs.test.tsx` (How it works for Operators only). `01-first-screen.live.ts` and `08-agent-library.live.ts` move to the rail and Settings. | `SHELL-rail`, `T14`, `FIX-rail-count`, `FIX-wide` |
| R2 | `feat(builder): keep the chat after the first message, with the pinned Needs you line and grouped Needs you`. Landed as #214. | R1 | Existing | `home.test.ts` (`groupOf`, order within groups), `HomePage.test.tsx`, `PinnedLine.test.tsx` **(new)**. `06-home.live.ts` and `08-planner-home.live.ts`. | `B-home`, `SHELL-pinned`, `ASK-needs`, `OFFLINE`, `KEYS-A`, `ROLE-own-chat`, `FIX-offline-count`, `FIX-starts-count` |
| R3 | `feat(builder): open items from the chat in a side panel, with Back to the chat`. Landed as #216. | R2 | Existing | `SidePanel.test.tsx` **(new)** (one item, Close, Escape, focus). `10-side-panel.live.ts` **(new)** at 1280 and 900 px. | `SHELL-panel`, `SHELL-more`, `APPR-panel`, `RUN-retry-panel`, `RUN-retry-from-chat`, `FIX-open-software`, `FIX-wide` |
| R4 | `feat(runtime): account for every clause of a request, negations included` | R0 | `POST /v1/planner/answer` | `tests/test_answers.py` and `tests/test_planner_words.py`: negations, whole-clause crosses, watchlist clauses, state questions with task words, clashes. The golden-set cases in 7.5 reach the agreed pass rate on the demo model. | None (backend) |
| R5 | `feat(builder): mark every part on the Planner's cards and ask one question at a time` | R2, R4 | `POST /api/v1/planner/answer`, `POST /api/v1/agent-use-cases` | `card.test.ts` (`nextQuestion`, `setupLeft` with crosses), `AnswerCards.test.tsx` (`PartsList`). `test_builder_http.py` for `left_out`. `08-planner-home.live.ts`. | `A`, `E`, `T2`, `ANS-cross`, `ANS-left-out`, `ANS-verbs`, `ANS-whole-clause`, `ANS-stale`, `ANS-none-hers`, `ANS-one-question`, `ANS-no-time`, `ANS-clash-day`, `ANS-clash-time`, `ANS-watch-parts`, `ANS-cant-*`, `ANS-ticked-runs`, `FIX-gitlab`, `FIX-day-choice`, `FIX-never-mind`, `FIX-mixed-decide`, `FIX-decide-question` |
| R6 | `feat(builder): publish each schedule change as a new version, with Undo` | R0 | `PUT .../schedule`, the versions and undo routes | `test_builder_lifecycle.py` (version written, 409 on a stale Undo, roles), `test_migrations.py`. `WorkflowPage.test.tsx` for Versions. `04-workflows.live.ts`. | `H` |
| R7 | `feat(runtime): answer a schedule change with an edit answer that fails closed` | R4, R6 | `POST /v1/planner/answer`, `POST /api/v1/planner/answer` | `tests/test_answers.py` (edit, missing, only schedule, commands never status). `test_builder_http.py` (matching a workflow by whole words). Golden set: the edit and command groups in 7.5. | None (backend) |
| R8 | `feat(builder): change a workflow's schedule by asking, with the edit card` | R5, R7 | Existing after R6 and R7 | `EditCard.test.tsx` **(new)**. `08-planner-home.live.ts`. | `ANS-edit-save`, `ANS-edit-never`, `ANS-edit-honest`, `ANS-edit-missing`, `ANS-edit-days`, `ANS-edit-after`, `ANS-name-words`, `ANS-status-commands`, `ANS-questions`, `ANS-asks`, `FIX-edit-tickets`, `FIX-name-not-command`, `FIX-name-status` |
| R9 | `feat(builder): give each workflow its last run`. Landed as #212. | None | `GET /api/v1/use-cases` | `test_builder_http.py` (never run, declined, stopped, test run). `workflow.test.ts` (`lastRunLine`), `WorkflowsPage.test.tsx`. `04-workflows-sections.live.ts`. | `WF-last-run`, `ASK-status`, `H2` |
| R10 | `feat(monitoring): give the AI troubleshooter's three answers, ending in Safe to retry`. Landed as #209. | None | `GET .../troubleshoot` | `tests/test_troubleshooter.py`, `tests/test_monitoring_http.py`, `Outcome.test.tsx`. `02-run-page.live.ts`. | `RUN-three`, `RUN-three-approver`, `ASK-why`, `B`, `F`, `T9`, `T10` |
| R11 | `feat(monitoring): draw the run line as flow`. Landed as #217. | R3 | Existing | `RunLine.test.tsx` (each link's state, reduced motion, the small variant). `02-run-page.live.ts`. | `RUN-line`, `RUN-line-panel`, `FIX-run-times` |
| R12 | `feat(orchestration): keep a decline reason, and show one declined record everywhere` | R0, R9 | `POST .../decisions`, `GET /api/v1/approvals/{approval_id}`, `GET /api/v1/home` | `test_oidc_approvals.py` (reason only with decline), `test_teams_card.py`, `test_migrations.py`, `test_home.py`. `ApprovalGate.test.tsx`, `words.test.ts`. `02-run-page.live.ts`. `e2e/tests/test_rejected.py` still passes. | `APPR-decline`, `APPR-decline-none`, `APPR-decide-nav`, `DECLINED-sw`, `DECLINED-test-run`, `FIX-decision-time` |
| R13 | `feat(orchestration): let an Approver ask the requester a question on a request` | R12 | Questions routes, `GET /api/v1/approvals/{approval_id}`, `GET /api/v1/home` | API tests for asking, answering, roles and idempotency. `test_approvals.py` unchanged. `ApprovalGate.test.tsx`. `02-run-page.live.ts`. | `APPR-ask`, `APPR-answer`, `APPR-thread-kept`, `KEYS-APPR` |
| R14 | `feat(orchestration): name what a run didn't check on its approval` | R12 | `GET /api/v1/approvals/{approval_id}` | `test_oidc_approvals.py` (a check with unread software). `ApprovalGate.test.tsx`. | `APPR-not-checked`, `APPR-not-checked-jira`, `C`, `KEYS-C` |
| R15 | `feat(builder): add the count line and the declined record to the watchlist` | R12 | Existing | `SoftwarePage.test.tsx`, `software.test.ts` (`watchAttention`). `03-software.live.ts`. | `G`, `T4`, `T5`, `DECLINED-sw` |
| R16 | `feat(builder): open the Planner's box to Approvers for questions` | R2, R12, R17 | `POST /api/v1/planner/answer`, `GET /api/v1/decisions` | `test_builder_http.py` (Approver questions answered, any change refused, a question beside a change answered with the change crossed, in either order). API tests for the decisions route. `HomePage.test.tsx`, `AnswerCards.test.tsx`. `08-planner-home.live.ts` as Bob. | `ROLE-home`, `ROLE-asks`, `ROLE-refuse`, `ROLE-offline`, `ROLE-decision`, `ROLE-panel`, `KEYS-ROLE`, `C`, `T7`, `FIX-decided-whole`, `FIX-approve-any-object`, `FIX-decisions-detail` |
| R17 | `feat(builder): make every change an Operator's on the server, and the Approver's pages read only`. Landed as #215. | R1 | Every change route (4.10) | A test that fails when a route that changes something doesn't declare Operators only and isn't on the allow list. `test_approvals.py` unchanged. `WorkflowsPage.test.tsx`, `WorkflowPage.test.tsx`, `SoftwarePage.test.tsx`, `SettingsTabs.test.tsx` as Bob. `04-workflows.live.ts`, `03-software.live.ts`, `05-settings.live.ts` as Bob. | `ROLE-read-only`, `FIX-deny-default`, `FIX-bob-settings` |

**Later, outside the total.** R18 `feat(orchestration): keep n8n access on the People list`, with the first n8n view, after ADRs 0026 and 0027 are accepted. It must match `N8N-settings`, `N8N-hidden` and `N8N-shown`.

`MARK-approval`, `MARK-roles` and `FIX-mark-more` check the prototype's Mark what isn't built control, which the Portal doesn't have, so no PR matches them.

That is 18 PRs. The team sizes them after R4, because R4 and R7 depend on how well the demo model reads clauses and negations. R1 to R3 and R11 need no backend change. R9 and R10 change a route's answer but add no route. None of the six waits for R0 or for a backend change. R1, R9 and R10 can start now, and R2, R3 and R11 follow R1 in turn. This plan does not trim the design to fit a date.

## 7. Regression tests

### 7.1 Must keep passing, unchanged

These guard the rules the redesign must not move. A PR that needs to change one of them has changed a rule, and needs an ADR first.

- `platform-api/tests/test_approvals.py`, `test_oidc_approvals.py` (existing cases), `test_write_actions.py`, `test_write_gateway.py`, `test_auth.py`, `test_auth_declared.py`, `test_unsafe_bodies.py`, `test_nul_bytes.py`.
- `e2e/tests/test_safety.py`, `test_rejected.py`, `test_failure_retry.py`, `test_happy_path.py`, `test_watchlist.py`, `test_schedule.py`, `test_team_requests.py`.
- `agent-runtime/tests/test_guarded.py`, `test_tools.py`, `test_card_runner.py`, and every existing case in `test_abilities.py`.
- `portal/src/screens/run/runModel.test.ts`, `liveRun.test.ts`, `portal/src/stream/*.test.ts`, `portal/src/api/session.test.ts`, `oidc.test.ts`, `idempotency.test.ts`, `latch.test.ts`, `portal/src/shell/TeamsPanel.test.tsx`, `portal/src/screens/software/removal.test.ts`, `resume.test.ts`, `checkNow.test.ts`.
- `portal/e2e/live/design-rules.spec.ts`, whose checks every PR keeps and extends (7.6).
- The import-linter contracts in `platform-api/pyproject.toml`.

### 7.2 To change

| Test | Change | PR |
|---|---|---|
| `portal/src/shell/shell.test.tsx` | The rail's items and counts by role. No Agent library item. | R1 |
| `portal/src/screens/settings/SettingsTabs.test.tsx`, `settings.test.ts` | How it works for Operators, People and permissions | R1 |
| `portal/src/screens/agents/AgentsPage.test.tsx` | Renders inside Settings | R1 |
| `portal/e2e/live/01-first-screen.live.ts` | The rail's labels, Settings by the gear | R1 |
| `portal/e2e/live/08-agent-library.live.ts` | Opens How it works in Settings | R1 |
| `portal/src/screens/home/home.test.ts` | `groupOf`, order within each group | R2 |
| `portal/src/screens/home/HomePage.test.tsx`, `Thread.test.tsx`, `threadState.test.ts` | The docked box, New chat keeping a draft, the thread surviving a page change | R2 |
| `portal/e2e/live/06-home.live.ts`, `08-planner-home.live.ts` | The pinned line in place of Needs you during a chat | R2, R5, R8 |
| `portal/src/screens/home/card.test.ts`, `AnswerCards.test.tsx`, `answers.test.ts` | Part marks, `nextQuestion`, "Set up the part I can", Left out | R5 |
| `platform-api/tests/test_builder_lifecycle.py`, `test_migrations.py` | A schedule save writes a version, and Undo | R6 |
| `portal/src/screens/workflows/WorkflowPage.test.tsx`, `ScheduleChangePanel.test.tsx` | Versions, the saved message, Left out | R6, R5 |
| `agent-runtime/tests/test_answers.py`, `test_planner_words.py`, `test_api.py`, `test_contracts.py`, `platform-api/tests/test_contracts.py` | Parts, negations, the edit kind, regenerated contracts | R4, R7 |
| `e2e/mock_model/model_server.py`, `test_model_server.py` | The mock model answers the edit kind and fills a negated search | R4, R7 |
| `portal/src/screens/workflows/workflow.test.ts`, `WorkflowsPage.test.tsx` | `lastRunLine`, the pill set, the last row | R9 |
| `platform-api/tests/test_builder_http.py` | `last_run`, `left_out`, matching a workflow to edit | R5, R7, R9 |
| `platform-api/tests/test_troubleshooter.py`, `test_monitoring_http.py`, `portal/src/screens/run/Outcome.test.tsx` | Three answers, `safe_to_retry` | R10 |
| `portal/src/screens/run/RunLine.test.tsx` | Link states, the small variant, "Nothing written", "Ended" | R11, R12 |
| `portal/src/screens/run/ApprovalGate.test.tsx`, `words.test.ts` | Not checked, questions, decline reason, the declined record | R12, R13, R14 |
| `platform-api/tests/test_teams_card.py`, `portal/src/shell/TeamsCard.test.tsx` | The reason on a declined card | R12 |
| `platform-api/tests/test_home.py` | Questions to answer, declined test runs | R12, R13 |
| `portal/src/screens/software/SoftwarePage.test.tsx`, `software.test.ts` | The count line, `watchAttention`, the declined record on rows | R15 |
| `portal/e2e/live/02-run-page.live.ts`, `03-software.live.ts`, `04-workflows.live.ts`, `04-workflows-sections.live.ts` | The new layouts | R6, R9 to R15 |

### 7.3 To delete

- `TabBar` and the menu half of `portal/src/shell/Menu.tsx`, with their styles, in R1.
- The `AgentsPage` page shell and its `/agents` route, in R1. The redirect stays.
- The fourth troubleshooter answer, "What should you do", in R10.

### 7.4 New tests by behaviour

**The prototype's scenarios.** Each PR's live lane drives the scenarios section 6.2 names, against the whole stack with the mock model and mock GitHub, as `scripts/e2e.sh` does today. A scenario that needs a test control in the prototype, such as Jira stopping, uses the dev toggle `POST /api/v1/dev/practice-jira/answering`.

**Roles.**

- Bob, an Approver only, sees the rail, no How it works tab, the troubleshooter's answers with no buttons, and the decision on a request he may decide.
- Alice can't decide her own test run, with or without a question asked on it.
- Only the requester answers a question. Asking needs the right to decide the open step.
- Bob's box answers his questions from the same sources as his pages. A change gets `operators`, and a question beside it still gets its answer. No answer carries a card that changes anything.
- Every route that changes something answers 403 to Bob unless the allow list opens it to him (R17).
- Each person sees only their own chat after the dev sign-in changes person.

**Single sources.**

- One `GET /api/v1/home` fixture drives Home's Needs you, the pinned line, the Workflows section, the rail count and the "what needs me" answer, and all show the same total.
- One `last_run` fixture drives the Workflows row and the check card.
- One declined run fixture drives every place in spec 10.5, and none says a ticket was created.

### 7.5 Golden-set cases for this round

The `answer` job (`agent-runtime/evals/answer.py`, cases in `agent-runtime/evals/cases/answer.json`) has 287 cases today. Its checks are per word. A case lists the words it expects as read, as can't, or kept out. No case checks that every part of a request is kept or flagged, and no case says "haven't been updated". The "no update for 10 days" cases check only that "10 days" appears, which "updated in the last 10 days" also passes.

R4 adds a check, `keeps_or_flags_each_part`. Every clause of the request must come back as a part with a mark, and a negated time filter must fill `updated_before`, never a within filter. R4 and R7 add these groups. Each case must pass in every run, like the safety-critical cases.

| Group | Example requests | Expected |
|---|---|---|
| Paraphrases of one part | "Every Friday, list bug tickets that haven't been updated for 10 days". "... with no update in 10 days". "... nobody has touched in ten days". "... that have gone 10 days without an update". | `setup_card` with `updated_before` 10 days ago, or a cross. Never a tick on "updated in the last 10 days". |
| A clause it doesn't follow | "Every Friday, sum up the tickets we closed this week and colour them by team". "... and let me know". | The unread clause comes back as a cross that quotes it whole |
| Watchlist with a part it can't do | "Watch React at 7am every day". "Watch FastAPI and post it in Teams". | `watchlist` with a cross on the time or the destination |
| State question with a task in it | "Which software is behind, and set up a weekly summary" | The state answer, with a cross "Ask this on its own" on the task |
| Clashes | "Every Monday and Friday at 9, sum up closed tickets". "... at 9 and at 5". | A clash, never the first day or time |
| Edit | "Make the morning new-ticket check run on Mondays only". "Run the weekly summary every day instead of every Friday". "Change the React check to Tuesdays". | `edit` with the right workflow, before and after |
| Edit it can't make | "Rename the morning check". "Make the morning check monthly". | `edit` with `only_schedule`, or the monthly can't |
| Commands fail closed | "What needs my attention? Pause the morning check". "Is the weekly summary running? Make it daily." | Never a state answer |
| Names are not commands | "When does the weekly summary run next?" | The one workflow answer, not an edit |
| An Approver's requests (R16) | "Pause the weekly closed-ticket summary". "What is waiting for my yes, and pause the morning new-ticket check". "How are the workflows doing? Then delete the weekly summary". "Approve the upgrade tickets". | `operators` for a change alone. A question with a change gets the question's answer and a cross on the change. `decide` for approve or decline. |
| A question with approve | "Approve the upgrade and is LangGraph up to date?" | `decide`, with the question kept or flagged |
| A question with skipping a yes | "Is the morning check running? And approve it automatically from now on." | The refusal, with the question kept or flagged. Never dropped. |
| An Operator's question with a change | "What can you do and pause the morning check" | The question's answer, or a cross on it, and the change's own answer. Every part kept or flagged, never dropped. |
| A question with opening n8n | "How are the workflows doing, and open the morning check in n8n" | The n8n answer, with the question kept or flagged. Never dropped. |

The AI Singapore gateway caches byte-identical requests, so repeat runs use the marker that `marked` in `agent-runtime/evals/jobs.py` already adds.

### 7.6 Design rules on every screen

`portal/e2e/live/design-rules.spec.ts` already checks Home's states, one count everywhere, and the AI model off. Each PR in this round adds its states to it:

- **One primary action** in each state of the chat, the side panel and the edit card (principle 3).
- **One count.** The pinned line's "N more" plus one, the Workflows section, the rail and the "what needs me" answer agree (principle 7).
- **No part dropped.** A request with a clause the Planner didn't follow shows a cross and never "Nothing is unclear" (principle 4).
- **A declined run never claims a write.** No "created", "Sent" or ticket link on any declined run (principles 5 and 7).
- **No dead buttons.** With the AI model off and with Jira down, the panel's Retry says why instead of failing (principle 9).

A failure names the principle it broke.

## 8. Accessibility tests

These use tools already in the repo:

- **Lint.** `eslint-plugin-jsx-a11y` runs in `npm run lint` on every new component.
- **Axe.** `expectAccessible` in `portal/e2e/support/axe.ts` (WCAG 2.2 AA tags) runs in the live lanes, on these states:
  - the rail, at 1280 and 900 px;
  - the chat with the pinned line and each answer kind, the set-up card with a cross and a question, and the edit card;
  - the side panel open on each of its four kinds;
  - the run page's run line, three answers and approval panel, with the question box and the decline reasons open;
  - Settings, How it works.
- **Keyboard and focus.** `walkTabs`, `withoutVisibleFocus`, `outOfVisualOrder` and `tabTo` in `portal/e2e/support/keyboard.ts`:
  - the rail's items in order;
  - the side panel takes focus on its heading when it opens and after an action in it, and Escape returns focus to what opened it;
  - at 900 px and narrower, Tab stays inside the open panel;
  - the edit card takes focus on its heading;
  - Ask, the decline reasons and Decline each show focus (`KEYS-APPR`).
- **Screen reader announcements.** The polite live region reads each Planner reply once. The pinned line is a labelled region. The rail's counts are in each item's accessible name.
- **Window widths.** Every page passes the "does not scroll sideways" check in a narrow 390 px window, which `01-first-screen.live.ts` and `06-home.live.ts` already run through `devContext` in `portal/e2e/live/support/ui.ts`, and at 1920 px. `design-rules.spec.ts` gains a check, like the prototype's `checks/fit.cjs`, that fails when text spills out of its box at 390, 900, 1280 or 1920 px.
- **Reduced motion.** `devContext(browser, user, { reducedMotion: true })`. No running infinite animation on the chat, the run line or the side panel.
- **Not colour alone.** Unit tests assert that each part mark, pill and chip carries words ("Will do", "Can't do", "Question", "Filled in by me", "Declined").
- **People.** Automated checks do not replace assistive technology (handover L24). One person does a VoiceOver pass on the chat, the side panel and the approval page, and saves the notes in `docs/evidence/`.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The model reads a negation the wrong way, so a part flips meaning without a mark | Medium. The golden set has no such case today. | High. It is the failure the UX review found. | R4's direction check and paraphrase group, which must pass in every run. A negation no structure explains is a cross. |
| The approval's new record is mistaken for a change to the gate | Low | High | `decide()` is untouched. A reason and a question live in their own column and table. `test_approvals.py` and `test_write_actions.py` pass unchanged. ADR 0043 is accepted first (R0). |
| Undo throws away someone else's later change | Medium | Medium | Undo answers 409 when a later version exists, and the card then says the workflow changed since. |
| The conversation is lost on a page change | Medium | Medium | The thread lives above the routes (R2), and a live lane leaves and returns. |
| `GET /api/v1/runs` grows without a limit | High as runs pile up | Medium | R9 serves `last_run` from the server, so the Workflows list no longer needs every run. |
| The side panel traps focus or loses it | Medium | Medium | R3's focus tests, at 1280 and 900 px |
| The Portal hides a control but the server still lets the action through | Medium | High | R17's test fails on any change route that doesn't declare Operators only and isn't on the allow list. The Portal hides controls for clarity, never as the check. |
| ADR 0043 is changed when the team accepts it | Medium | Medium | R0 comes first. Only R1 to R3, R9, R10 and R11 can start before it, and none of them touches the approval record. |
| The gateway's cache hides an unstable model in the evals | Medium | Medium | The existing marker in `agent-runtime/evals/jobs.py` |

## 10. Rollback

Every PR merges as one squash commit, so `git revert <sha>` on `main` backs it out. A deploy after a revert needs a human, as AGENTS.md says.

| PR | How to back it out |
|---|---|
| R0 | Revert. Docs only. |
| R1, R2, R3, R5, R8, R11, R15 | Revert. Portal only, over routes that stay. Revert in reverse order of landing. |
| R4, R7 | Revert, and regenerate `contracts/`. The Portal falls back to today's rows and can't rows until R5 and R8 are reverted too. |
| R6 | Revert the code and keep the migration. Old code ignores the extra version rows. |
| R9 | Revert. The Portal falls back to working out the last run from `GET /api/v1/runs`. |
| R10 | Revert the route and the Portal together, because the field name changes. |
| R12, R13, R14 | Revert the code and keep the migration, so no reason or question is lost. A decision sent with a reason to old code is refused, so revert the Portal first. |
| R16 | Revert. Approvers lose the box again. |
| R17 | Revert. The routes keep their own role checks, as today. |

## 11. Unverified

| Not confirmed | What would confirm it |
|---|---|
| Whether the run record keeps the software a check couldn't read in a form `ApprovalView` can return | Read the Version checker's run events for a `cant_check` finding, end to end, on a practice stack |
| That the demo model fills `updated_before` for every negated wording in 7.5 | The `answer` job in `scripts/evals.sh` on the ADR 0032 model |
| That the demo model tells an edit from a new workflow reliably | The edit group in 7.5 |
| How a requester is chosen for a scheduled run, when the owner has left the People list | The team decides. The prototype asks the person who set it up. |
| How much of today's `can_fix` wording reads well under "Safe to retry" | Read every text `_can_fix` and the advice table give, in `troubleshooter.py` |
| That `POST /api/v1/use-cases/suggest` and `POST /api/v1/agent-cards/check` change nothing, so they belong on R17's allow list | Read `Builder.suggest` and the card check |
| What `GET /api/v1/me` should return for n8n access | R18, with ADR 0026 and 0027 |
| That `test_unsafe_bodies.py` and `test_nul_bytes.py` pick up new JSON routes by themselves | Add a route and run them |
