# Interaction counts, v4

Prototype: `docs/design/ai-native-redesign/prototype.html`. Paths: `docs/design/ai-native-redesign/checks/paths-v4.cjs`.

Real scenarios: 41 passed, 7 failed, 0 not possible. Control (must fail): failed, as it should.

| Id | Width | Task | Passed | Clicks | Fields | Selects | Decisions | Screens | Notes |
|---|---|---|---|---|---|---|---|---|---|
| A | 1280 | First-time Operator sets up a weekly Jira summary and turns it on | NO | 2 | 2 | 1 | 3 | 1 | plannerQuestions 2 |
| A | 390 | First-time Operator sets up a weekly Jira summary and turns it on | NO | 2 | 2 | 1 | 3 | 1 | plannerQuestions 2 |
| B | 1280 | Experienced Operator finds what needs attention and fixes the stopped Morning new-ticket check | yes | 2 | 0 | 0 | 1 | 3 |  |
| B | 390 | Experienced Operator finds what needs attention and fixes the stopped Morning new-ticket check | yes | 2 | 0 | 0 | 1 | 3 |  |
| C | 1280 | Bob, an Approver only, opens the upgrade request, sees what changes and the evidence, and approves | yes | 2 | 0 | 0 | 1 | 2 |  |
| C | 390 | Bob, an Approver only, opens the upgrade request, sees what changes and the evidence, and approves | yes | 2 | 0 | 0 | 1 | 2 |  |
| C-self | 1280 | Alice turns on a workflow, does a test run, and cannot approve her own test run | NO | 1 | 0 | 0 | 0 | 1 |  |
| D | 1280 | An Operator asks to email a weekly list, and the limit is explained with a next step | yes | 1 | 1 | 0 | 0 | 1 |  |
| E | 1280 | The user corrects the Planner’s guess of project and schedule on the card, without starting again | yes | 3 | 1 | 2 | 2 | 1 |  |
| F | 1280 | Recover the stop the user can fix, and report the platform bug to support | yes | 6 | 0 | 0 | 2 | 3 |  |
| G | 1280 | Monitor Kubernetes releases from Home ends with Kubernetes on the Software watchlist | yes | 4 | 1 | 0 | 2 | 1 |  |
| H | 1280 | Pause a workflow, change its schedule, and delete one with its confirmation | yes | 10 | 1 | 2 | 5 | 3 |  |
| T1 | 1280 | Set up a workflow from example 1: example, time, Jira project, Turn it on | NO | 1 | 0 | 0 | 0 | 1 |  |
| T2 | 1280 | Set up a typed workflow with every part stated: type, Enter, Turn it on | yes | 2 | 1 | 0 | 1 | 1 |  |
| T3 | 1280 | Do a test run after turning one on | yes | 1 | 0 | 0 | 0 | 2 |  |
| T4 | 1280 | Add software from Home with example 3: example, Looks right, Start from the newest, Add React | NO | 1 | 0 | 0 | 0 | 1 |  |
| T5 | 1280 | Add software on the Software watchlist page | yes | 3 | 2 | 0 | 0 | 2 |  |
| T6 | 1280 | Approve from Workflows: Workflows, Review and decide, Approve 3 tickets | yes | 3 | 0 | 0 | 1 | 3 |  |
| T7 | 1280 | Approve from Home as an Approver only: Review and decide, Approve | yes | 2 | 0 | 0 | 1 | 2 |  |
| T8 | 1280 | Approve from the Teams drawer: Teams, Approve | yes | 3 | 0 | 0 | 1 | 2 |  |
| T9 | 1280 | Fix a stopped run the user can fix: Workflows, See why and fix it, retry | yes | 2 | 0 | 0 | 1 | 3 |  |
| T10 | 1280 | Report a platform bug: Workflows, Report to support, Send report, Done | yes | 4 | 0 | 0 | 1 | 2 |  |
| T11 | 1280 | Pause a workflow: Workflows, row, Pause | yes | 3 | 0 | 0 | 1 | 3 |  |
| T12 | 1280 | Delete a workflow: Workflows, row, Delete, Delete workflow | yes | 5 | 0 | 0 | 1 | 3 |  |
| T13 | 1280 | Change who approves: Workflows, row, Change who approves, Save | yes | 4 | 0 | 2 | 2 | 3 |  |
| T14 | 1280 | Change an agent in plain English: Settings, How it works, Details and changes, chip, Suggest a change, Save | yes | 7 | 0 | 0 | 1 | 2 |  |
| T15 | 1280 | Ask the team for a new system, after a "can’t" answer | yes | 1 | 0 | 0 | 1 | 1 |  |
| H2 | 1280 | Discard a draft set-up card from Workflows | yes | 2 | 0 | 0 | 1 | 2 |  |
| B-home | 1280 | Find and act on the stopped workflow from Home’s Needs you | yes | 1 | 0 | 0 | 1 | 2 |  |
| B-home | 390 | Find and act on the stopped workflow from Home’s Needs you | yes | 1 | 0 | 0 | 1 | 2 |  |
| ASK-status | 1280 | “Check my workflows” from the suggestions | NO | 1 | 0 | 0 | 0 | 1 |  |
| ASK-status | 390 | “Check my workflows” from the suggestions | NO | 1 | 0 | 0 | 0 | 1 |  |
| ASK-why | 1280 | “Why did Morning new-ticket check stop?” ending in a retry from the answer | yes | 2 | 1 | 0 | 1 | 2 |  |
| ASK-needs | 1280 | “What needs me?” | yes | 1 | 1 | 0 | 0 | 1 |  |
| OFFLINE | 1280 | No AI model: Home says so and offers Connect a model | yes | 1 | 0 | 0 | 0 | 2 |  |
| OFFLINE | 390 | No AI model: Home says so and offers Connect a model | yes | 1 | 0 | 0 | 0 | 2 |  |
| DOWN | 1280 | Jira stops answering: the Planner says so, then Jira works again | yes | 1 | 1 | 0 | 0 | 1 |  |
| PREVIEW | 1280 | Planned features shown: each planned item is tagged | yes | 3 | 0 | 0 | 0 | 4 |  |
| SHELL-pinned | 1280 | The pinned Needs you line shows after the first message, with Open and N more | yes | 2 | 1 | 0 | 0 | 2 |  |
| SHELL-pinned | 390 | The pinned Needs you line shows after the first message, with Open and N more | yes | 2 | 1 | 0 | 0 | 2 |  |
| SHELL-panel | 1280 | A card in the chat opens its workflow in a side panel, or full screen on a phone, and Close puts it back | yes | 3 | 1 | 0 | 0 | 1 |  |
| SHELL-panel | 390 | A card in the chat opens its workflow in a side panel, or full screen on a phone, and Close puts it back | yes | 3 | 1 | 0 | 0 | 1 |  |
| SHELL-more | 1280 | More details gives a full page with Back to the chat, and the panel is still there on return | yes | 4 | 1 | 0 | 0 | 2 |  |
| SHELL-more | 390 | More details gives a full page with Back to the chat, and the panel is still there on return | yes | 4 | 1 | 0 | 0 | 2 |  |
| SHELL-rail | 1280 | The rail returns to the chat as it was, scroll position included | yes | 4 | 2 | 0 | 0 | 2 |  |
| SHELL-rail | 390 | The rail returns to the chat as it was, scroll position included | yes | 4 | 2 | 0 | 0 | 2 |  |
| KEYS-A | 1280 | Scenario A with the keyboard only | yes | 20 | 2 | 0 | 3 | 1 |  |
| KEYS-C | 1280 | Scenario C with the keyboard only | yes | 12 | 0 | 0 | 1 | 2 |  |

A click includes a key press on a button. Menu steps and page changes are included. A decision is also counted as a click, a select or a field. Test controls are never counted.
