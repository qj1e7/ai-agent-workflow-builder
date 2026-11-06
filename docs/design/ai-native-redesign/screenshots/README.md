# Screenshots, version 3 and version 4

`before/` is version 3 (`docs/design/portal-routines/prototype.html`). `after/` is version 4 (`docs/design/ai-native-redesign/prototype.html`). Both were shot by `checks/shots.cjs` with the same sample data, at 1280 by 1000 (desktop) and 390 by 844 (phone), full page, light theme, with the test controls and messages hidden. The screen set is `screens` in `checks/paths-v3.cjs` and `checks/paths-v4.cjs`.

A full-page phone shot shows the fixed tab bar once, where the page was when it was taken. Content under it in the image is not hidden on a real phone.

## The same screens

| Screen | Desktop | Phone | What changed |
|---|---|---|---|
| Home, day one | [before](before/day-one-home-desktop.png), [after](after/day-one-home-desktop.png) | [before](before/day-one-home-phone.png), [after](after/day-one-home-phone.png) | The starting points no longer ask for tickets with no update, the Not yet list names each planned item, and the Workflows tab no longer warns about a key on day one. |
| Home, a normal week | [before](before/home-desktop.png), [after](after/home-desktop.png) | [before](before/home-phone.png), [after](after/home-phone.png) | Home now greets Alice, says 4 things need her, suggests from her state and lists the three most urgent with one button each. |
| Home, Approver only | [before](before/approver-home-desktop.png), [after](after/approver-home-desktop.png) | [before](before/approver-home-phone.png), [after](after/approver-home-phone.png) | Bob sees today’s approval rule, with no backup and no stop time, and no “Open in Teams” button. |
| Planner, set-up card | [before](before/planner-setup-card-desktop.png), [after](after/planner-setup-card-desktop.png) | [before](before/planner-setup-card-phone.png), [after](after/planner-setup-card-phone.png) | The card is one sentence with chips, When, What needs a yes and a collapsed How this workflow works, and the chat line no longer repeats a count. |
| Planner, can’t email | [before](before/planner-cant-email-desktop.png), [after](after/planner-cant-email-desktop.png) | [before](before/planner-cant-email-phone.png), [after](after/planner-cant-email-phone.png) | The reply says what it can make before what it can’t, and Set that up is the one main button. |
| Planner, Kubernetes on the watchlist | [before](before/planner-watch-kubernetes-desktop.png), [after](after/planner-watch-kubernetes-desktop.png) | [before](before/planner-watch-kubernetes-phone.png), [after](after/planner-watch-kubernetes-phone.png) | Who says yes is today’s rule, any Approver except Carol, instead of Bob with Alice as backup, and the reply is shorter. |
| Workflows | [before](before/workflows-desktop.png), [after](after/workflows-desktop.png) | [before](before/workflows-phone.png), [after](after/workflows-phone.png) | Stopped runs come first with the troubleshooter’s answer and Retry in place, the list drops agent faces and the always-on filters, and the access review is gone by default. |
| Workflow page | [before](before/workflow-page-desktop.png), [after](after/workflow-page-desktop.png) | [before](before/workflow-page-phone.png), [after](after/workflow-page-phone.png) | Five buttons became one banner action and a More actions menu, and the steps and agents moved into Technical details. |
| Run page, stopped | [before](before/run-stopped-desktop.png), [after](after/run-stopped-desktop.png) | [before](before/run-stopped-phone.png), [after](after/run-stopped-phone.png) | The troubleshooter gives four answers and Retry the run, and the agents’ conversation is behind Show what each agent did. |
| Run page, approval | [before](before/run-approval-desktop.png), [after](after/run-approval-desktop.png) | [before](before/run-approval-phone.png), [after](after/run-approval-phone.png) | The panel is What will change, Why, Who asked, What happens and Your part, with no vulnerability scores, because those sources are planned. |
| Software watchlist | [before](before/software-desktop.png), [after](after/software-desktop.png) | [before](before/software-phone.png), [after](after/software-phone.png) | Needs attention comes first with the LangServe address fix, every source is GitHub, and other sources show as Planned. |
| Agent library | [before](before/agent-library-desktop.png), [after](after/agent-library-desktop.png) | [before](before/agent-library-phone.png), [after](after/agent-library-phone.png) | The Agents tab (version 4 opens on What it can do) shows six agents instead of nine, without the planned ones. |
| Agent library, Tools | [before](before/agent-library-tools-desktop.png), [after](after/agent-library-tools-desktop.png) | [before](before/agent-library-tools-phone.png), [after](after/agent-library-tools-phone.png) | Four tools instead of twelve, matching the built agents, and asking for a new tool goes to the team. |
| Settings, Connections | [before](before/settings-connections-desktop.png), [after](after/settings-connections-desktop.png) | [before](before/settings-connections-phone.png), [after](after/settings-connections-phone.png) | Each connection says what uses it in plain words, and Teams only sends approval requests. |
| Teams drawer | [before](before/teams-drawer-desktop.png), [after](after/teams-drawer-desktop.png) | [before](before/teams-drawer-phone.png), [after](after/teams-drawer-phone.png) | Approve and Decline are gone, and the card has one button that opens the approval page. |
| Drafts on Workflows | [before](before/drafts-desktop.png), [after](after/drafts-desktop.png) | [before](before/drafts-phone.png), [after](after/drafts-phone.png) | A draft now says what it still needs and has Resume and Discard. |

## New in version 4

| Screen | Desktop | Phone | What it shows |
|---|---|---|---|
| Home, Needs you | [after](after/home-needs-you-desktop.png) | [after](after/home-needs-you-phone.png) | The same state as Home, a normal week. The two files are the same image, because `shots.cjs` scrolls to the top before it shoots. |
| Planner, check my workflows | [after](after/planner-check-workflows-desktop.png) | [after](after/planner-check-workflows-phone.png) | One row per workflow with its status, next run and one action. |
| Planner, why it stopped | [after](after/planner-why-stopped-desktop.png) | [after](after/planner-why-stopped-phone.png) | The troubleshooter’s four answers in the chat, with Retry the run. |
| Workflow page, More actions | [after](after/workflow-more-menu-desktop.png) | [after](after/workflow-more-menu-phone.png) | Run now, Pause, Change schedule, Open in n8n, then Delete in red after a divider. |
| Run page, detailed activity | [after](after/run-detailed-activity-desktop.png) | [after](after/run-detailed-activity-phone.png) | The agents’ conversation and the replay controls, opened on request. |
| Software watchlist, Needs attention | [after](after/software-attention-desktop.png) | [after](after/software-attention-phone.png) | The same state as Software watchlist. The files are the same image, for the same reason as Home, Needs you. |
| Agent library, What it can do | [after](after/library-what-it-can-do-desktop.png) | [after](after/library-what-it-can-do-phone.png) | The capability list the library opens on: I can, and Not yet with Planned marks. |
| Home with no AI model | [after](after/offline-home-desktop.png) | [after](after/offline-home-phone.png) | The Planner’s sorry face, Connect a model, Needs you and the capability lists. Connect a model shows twice. |
| Software watchlist, Planned shown | [after](after/preview-software-desktop.png) | [after](after/preview-software-phone.png) | Security risks, support end dates and other sources, each tagged Planned. |
| Home, Mark what isn’t built | [after](after/mark-unbuilt-home-desktop.png) | [after](after/mark-unbuilt-home-phone.png) | Dashed outlines on the parts the built Portal doesn’t have yet. |

## What the judge saw in the after images

Every after image was opened and looked at. None is blank or half-typed, and quality.cjs measured no sideways scroll at 390 px. These are visible problems:

- At 390 px the Planner box’s placeholder is cut off (“What would you like to automate, chec”) on `home-phone`, `day-one-home-phone`, `home-needs-you-phone` and `mark-unbuilt-home-phone`. The offline box is cut off the same way.
- At 390 px the Settings tabs run off the right edge: AI model and Usage are out of view on `settings-connections-phone`.
- On `planner-check-workflows-phone` the rows are cramped: names wrap and centre, and the “Waiting for a yes” pill touches the Review and decide button.
- On `mark-unbuilt-home` (both widths) the “Not built: Report to sup...” label is cut short and sits over the top edge of the Report to support button.
- On `planner-cant-email-desktop` the answer sits further right and narrower than the other answers, probably caught mid-animation.
- `software-desktop` shows FastAPI’s newest version as 0.120.2, while `run-approval-desktop`, `approver-home-desktop` and `teams-drawer-desktop` propose 0.120.1.
