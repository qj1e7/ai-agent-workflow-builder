# Version 3 against version 4

Counts are clicks / fields / selects / decisions / screens, from `v3.json` and `v4.json`. The change is in interactions: clicks plus fields plus selects. A decision is also a click, a field or a select. Test controls are never counted. Written by `validate-v4.cjs`.

Repeat run (`v4-second.json`): identical counts and results for all 40 scenarios.

| Id | Width | v3 | v4 | Change | v4 passed | Changed on purpose | v4 steps |
|---|---|---|---|---|---|---|---|
| A | 1280 | 2 / 2 / 1 / 3 / 1 | 2 / 2 / 1 / 3 / 1 | 0 | yes |  | Type: every Friday, sum up the tickets we closed this week; Press Enter to send; Choose the Jira project (decision); Choose the time (decision); Turn it on (decision) |
| A | 390 | 2 / 2 / 1 / 3 / 1 | 2 / 2 / 1 / 3 / 1 | 0 | yes |  | Type: every Friday, sum up the tickets we closed this week; Press Enter to send; Choose the Jira project (decision); Choose the time (decision); Turn it on (decision) |
| B | 1280 | 3 / 0 / 0 / 1 / 3 | 2 / 0 / 0 / 1 / 3 | -1 | yes | The sample stop is now Jira not answering (I2), fixed by a retry. The troubleshooter’s answer is on Workflows itself, so the run page is no longer a step. | Open Workflows; Retry the run (decision) |
| B | 390 | 3 / 0 / 0 / 1 / 3 | 2 / 0 / 0 / 1 / 3 | -1 | yes | The sample stop is now Jira not answering (I2), fixed by a retry. The troubleshooter’s answer is on Workflows itself, so the run page is no longer a step. | Open Workflows; Retry the run (decision) |
| C | 1280 | 2 / 0 / 0 / 1 / 2 | 2 / 0 / 0 / 1 / 2 | 0 | yes | The NVD and CISA evidence came from ADR 0025 sources, which are Planned and hidden by default (I9). The evidence is the GitHub release notes. | Review and decide; Approve (decision) |
| C | 390 | 2 / 0 / 0 / 1 / 2 | 2 / 0 / 0 / 1 / 2 | 0 | yes | The NVD and CISA evidence came from ADR 0025 sources, which are Planned and hidden by default (I9). The evidence is the GitHub release notes. | Review and decide; Approve (decision) |
| C-self | 1280 | 3 / 1 / 1 / 3 / 2 | 4 / 1 / 1 / 3 / 2 | +1 | yes | Normal-week Home suggests from state (spec 5.1). Set-up examples sit behind “Set up another workflow”, one tap more. | Tap Set up another workflow; Tap the first starting point; Choose the Jira project (decision); Choose the time (decision); Turn it on (decision); Do a test run |
| D | 1280 | 1 / 1 / 0 / 0 / 1 | 1 / 1 / 0 / 0 / 1 | 0 | yes | An alternative is offered only when it sets up cleanly (review item 2). “Open bugs” needs the ticket type, which agents can’t see, so the only next step is Ask the team. | Type: email me a list of open bugs every Monday; Press Enter to send |
| E | 1280 | 3 / 1 / 2 / 2 / 1 | 3 / 1 / 2 / 2 / 1 | 0 | yes |  | Type: a request the Planner reads as MOCK and Friday; Press Enter to send; Correct the Jira project (decision); Open the schedule; Correct the day (decision); Close the schedule |
| F | 1280 | 7 / 0 / 0 / 2 / 3 | 6 / 0 / 0 / 2 / 3 | -1 | yes | The fixable stop is a retry (I2), offered on Workflows, so the run page is no longer a step. | Open Workflows; Retry the run (decision); Back to Workflows; Report to support; Send report (decision); Done |
| G | 1280 | 4 / 1 / 0 / 2 / 1 | 4 / 1 / 0 / 2 / 1 | 0 | yes |  | Type: Monitor Kubernetes releases; Press Enter to send; Looks right (decision); Not sure? Start from the newest; Add Kubernetes (decision) |
| H | 1280 | 9 / 1 / 2 / 5 / 3 | 10 / 1 / 2 / 5 / 3 | +1 | yes | Delete moved into the More actions menu (spec 9), one tap more. Pause is a button beside it. | Open Workflows; Open Morning new-ticket check; Change schedule; How often (decision); Day (decision); Time (decision); Save the schedule; Pause (decision); Back to Workflows; Open Weekly closed-ticket summary; More actions; Delete; Delete workflow (decision) |
| T1 | 1280 | 2 / 1 / 1 / 3 / 1 | 3 / 1 / 1 / 3 / 1 | +1 | yes | Normal-week Home suggests from state. The examples sit behind “Set up another workflow” (spec 5.1). | Tap Set up another workflow; Tap the first starting point; Choose the Jira project (decision); Choose the time (decision); Turn it on (decision) |
| T2 | 1280 | 2 / 1 / 0 / 1 / 1 | 2 / 1 / 0 / 1 / 1 | 0 | yes | The v3 request needs a ticket’s update date, which the Jira tool can’t see (UX audit X2), so v4 answers “Part I can do”. The typed request is one the tools can do. | Type: a request with every part stated; Press Enter to send; Turn it on (decision) |
| T3 | 1280 | 1 / 0 / 0 / 0 / 2 | 1 / 0 / 0 / 0 / 2 | 0 | yes |  | Do a test run |
| T4 | 1280 | 4 / 0 / 0 / 2 / 1 | 5 / 0 / 0 / 2 / 1 | +1 | yes | The React example sits behind “Set up another workflow” on a normal week (spec 5.1). | Tap Set up another workflow; Tap Keep track of the React version; Looks right (decision); Not sure? Start from the newest; Add React (decision) |
| T5 | 1280 | 2 / 2 / 0 / 0 / 2 | 3 / 2 / 0 / 0 / 2 | +1 | yes | Add software takes plain words and looks the project up first (spec 11). Prometheus is not a known project, so it then asks for the repository. | Open Software watchlist; Name; Find it; GitHub repository; Add Prometheus |
| T6 | 1280 | 3 / 0 / 0 / 1 / 3 | 3 / 0 / 0 / 1 / 3 | 0 | yes |  | Open Workflows; Review and decide; Approve (decision) |
| T7 | 1280 | 2 / 0 / 0 / 1 / 2 | 2 / 0 / 0 / 1 / 2 | 0 | yes |  | Review and decide; Approve (decision) |
| T8 | 1280 | 2 / 0 / 0 / 1 / 1 | 3 / 0 / 0 / 1 / 2 | +1 | yes | ADR 0036: Teams carries the request and its one button opens the approval page. Nobody approves inside Teams. | Open Teams; Open in AI Workflow Builder; Approve (decision) |
| T9 | 1280 | 3 / 0 / 0 / 1 / 3 | 2 / 0 / 0 / 1 / 3 | -1 | yes | The user-fixable stop is Jira not answering, fixed by a retry offered on Workflows. The moved GitHub project is now a watchlist item (Use the new address). | Open Workflows; Retry the run (decision) |
| T10 | 1280 | 4 / 0 / 0 / 1 / 2 | 4 / 0 / 0 / 1 / 2 | 0 | yes |  | Open Workflows; Report to support; Send report (decision); Done |
| T11 | 1280 | 3 / 0 / 0 / 1 / 3 | 3 / 0 / 0 / 1 / 3 | 0 | yes | The quarterly access review is Planned and hidden by default (I2), so another workflow is paused. | Open Workflows; Open Morning new-ticket check; Pause (decision) |
| T12 | 1280 | 4 / 0 / 0 / 1 / 3 | 5 / 0 / 0 / 1 / 3 | +1 | yes | Delete is last in the More actions menu, after a divider (spec 9). | Open Workflows; Open Weekly closed-ticket summary; More actions; Delete; Delete workflow (decision) |
| T13 | 1280 | 4 / 0 / 2 / 2 / 3 | 4 / 0 / 2 / 2 / 3 | 0 | yes | Named Approvers are ADR 0024, which is not built. The task exists only with Planned features shown, tagged Planned (I4). | Open Workflows; Open Morning new-ticket check; Change who approves; Asked first (decision); Backup (decision); Save |
| T14 | 1280 | 5 / 0 / 0 / 1 / 2 | 6 / 0 / 0 / 1 / 2 | +1 | yes | Changing an agent in plain English is Planned (handover L04) and the agent dialog is read only by default, so the task exists only with Planned features shown, tagged Planned. The Agent library opens on “What it can do” (spec 12), so the agents are one tab away. | Open Agent library; Open the Agents tab; Ticket writer: Details and changes; Pick a suggested change; Suggest a change; Save as version 2 (decision) |
| T15 | 1280 | 1 / 0 / 0 / 1 / 1 | 1 / 0 / 0 / 1 / 1 | 0 | yes |  | Ask the team (decision) |
| H2 | 1280 | not possible | 2 / 0 / 0 / 1 / 2 |  | yes | New in version 4. Version 3 had no way to remove a draft. | Open Workflows; Discard (decision) |
| B-home | 1280 | new | 1 / 0 / 0 / 1 / 2 |  | yes |  | Retry the run (decision) |
| B-home | 390 | new | 1 / 0 / 0 / 1 / 2 |  | yes |  | Retry the run (decision) |
| ASK-status | 1280 | new | 1 / 0 / 0 / 0 / 1 |  | yes |  | Tap Check my workflows |
| ASK-status | 390 | new | 1 / 0 / 0 / 0 / 1 |  | yes |  | Tap Check my workflows |
| ASK-why | 1280 | new | 2 / 1 / 0 / 1 / 2 |  | yes | Home offers no Why chip for a stop that is already the first Needs you row (review item 8), so the question is typed. | Type: Why did Morning new-ticket check stop?; Press Enter to send; Retry the run (decision) |
| ASK-needs | 1280 | new | 1 / 1 / 0 / 0 / 1 |  | yes |  | Type: What needs me?; Press Enter to send |
| OFFLINE | 1280 | new | 1 / 0 / 0 / 0 / 2 |  | yes |  | Connect a model |
| OFFLINE | 390 | new | 1 / 0 / 0 / 0 / 2 |  | yes |  | Connect a model |
| DOWN | 1280 | new | 1 / 1 / 0 / 0 / 1 |  | yes |  | Type: every Friday, sum up the tickets we closed this week; Press Enter to send |
| PREVIEW | 1280 | new | 3 / 0 / 0 / 0 / 4 |  | yes |  | Open Workflows; Open Quarterly access review; Open Software watchlist |
| KEYS-A | 1280 | new | 19 / 2 / 0 / 3 / 1 |  | yes |  | Tab to Skip to main content; Skip to main content; Tab towards the Planner box; Type the request; Send; Tab towards the Jira project choice; Tab towards the Jira project choice; Tab towards the Jira project choice; Type M to choose MOCK (decision); Tab towards the time; Tab towards the time; Tab towards the time; Tab towards the time; Type the time (decision); Tab towards Turn it on; Tab towards Turn it on; Tab towards Turn it on; Tab towards Turn it on; Tab towards Turn it on; Tab towards Turn it on; Turn it on (decision) |
| KEYS-C | 1280 | new | 12 / 0 / 0 / 1 / 2 |  | yes |  | Tab to Skip to main content; Skip to main content; Tab towards Review and decide; Review and decide; Tab towards Approve; Tab towards Approve; Tab towards Approve; Tab towards Approve; Tab towards Approve; Tab towards Approve; Tab towards Approve; Approve (decision) |
