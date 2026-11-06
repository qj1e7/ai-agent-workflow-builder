# Screenshots, version 3 and version 4

`before/` is version 3 (`docs/design/portal-routines/prototype.html`). `after/` is version 4 (`docs/design/ai-native-redesign/prototype.html`) at commit b6cc589. Both were shot by `checks/shots.cjs` with the same sample data, at 1280 by 1000 (desktop) and 390 by 844 (phone), full page, light theme, with the test controls and messages hidden. The screen set is `screens` in `checks/paths-v3.cjs` and `checks/paths-v4.cjs`.

A full-page phone shot shows the fixed tab bar once, where the page was when it was taken. Content under it in the image is not hidden on a real phone.

## The same screens

| Screen | Desktop | Phone | What changed |
|---|---|---|---|
| Home, day one | [before](before/day-one-home-desktop.png), [after](after/day-one-home-desktop.png) | [before](before/day-one-home-phone.png), [after](after/day-one-home-phone.png) | The starting points no longer ask for tickets with no update. The Not yet list is folded under “What can’t I do yet?”, and the Workflows tab has no badge on day one. |
| Home, a normal week | [before](before/home-desktop.png), [after](after/home-desktop.png) | [before](before/home-phone.png), [after](after/home-phone.png) | Home greets Alice with a line that has no count, suggests from her state, and lists the three most urgent of five things with one main button. “See all on Workflows” has no number. The bot, the greeting and the box keep version 3’s centred layout, with Needs you under the suggestions. |
| Home, Approver only | [before](before/approver-home-desktop.png), [after](after/approver-home-desktop.png) | [before](before/approver-home-phone.png), [after](after/approver-home-phone.png) | Bob sees today’s approval rule, with no backup and no stop time, and no “Open in Teams” button. |
| Planner, set-up card | [before](before/planner-setup-card-desktop.png), [after](after/planner-setup-card-desktop.png) | [before](before/planner-setup-card-phone.png), [after](after/planner-setup-card-phone.png) | The card is one sentence with chips, When, What needs a yes and a collapsed How this workflow works. The chat line has no count. |
| Planner, can’t email | [before](before/planner-cant-email-desktop.png), [after](after/planner-cant-email-desktop.png) | [before](before/planner-cant-email-phone.png), [after](after/planner-cant-email-phone.png) | Email is “not on the team’s plan”, and the only next step is Ask the team, because a list of bugs needs the ticket type. The reply still opens with “I can make that list”, which isn’t true. |
| Planner, Kubernetes on the watchlist | [before](before/planner-watch-kubernetes-desktop.png), [after](after/planner-watch-kubernetes-desktop.png) | [before](before/planner-watch-kubernetes-phone.png), [after](after/planner-watch-kubernetes-phone.png) | Who says yes is today’s rule, any Approver except Carol, instead of Bob with Alice as backup. The reply is shorter. |
| Workflows | [before](before/workflows-desktop.png), [after](after/workflows-desktop.png) | [before](before/workflows-phone.png), [after](after/workflows-phone.png) | Needs you comes first with five items, the LangServe move among them. The list drops agent faces and the always-on filters, and the access review is gone by default. |
| Workflow page | [before](before/workflow-page-desktop.png), [after](after/workflow-page-desktop.png) | [before](before/workflow-page-phone.png), [after](after/workflow-page-phone.png) | Five buttons became Pause, a More actions menu and one banner action. The steps and agents moved into Technical details. |
| Run page, stopped | [before](before/run-stopped-desktop.png), [after](after/run-stopped-desktop.png) | [before](before/run-stopped-phone.png), [after](after/run-stopped-phone.png) | The AI troubleshooter gives four answers and Retry the run. The agents’ conversation is behind Show what each agent did. |
| Run page, approval | [before](before/run-approval-desktop.png), [after](after/run-approval-desktop.png) | [before](before/run-approval-phone.png), [after](after/run-approval-phone.png) | The panel is What will change, Why, Who asked, What happens and Your part. It has no vulnerability scores, because those sources are planned. |
| Software watchlist | [before](before/software-desktop.png), [after](after/software-desktop.png) | [before](before/software-phone.png), [after](after/software-phone.png) | Needs attention comes first with the LangServe address fix. Every source is GitHub, the other sources say Not yet, and FastAPI’s newest version is 0.120.1 everywhere. |
| Agent library | [before](before/agent-library-desktop.png), [after](after/agent-library-desktop.png) | [before](before/agent-library-phone.png), [after](after/agent-library-phone.png) | The Agents tab (version 4 opens on What it can do) shows six agents instead of nine, each with Details only. Its footer says only what works today. Changing an agent in plain English shows only with Planned features on, tagged. |
| Agent library, Tools | [before](before/agent-library-tools-desktop.png), [after](after/agent-library-tools-desktop.png) | [before](before/agent-library-tools-phone.png), [after](after/agent-library-tools-phone.png) | Four tools instead of twelve, matching the built agents. Asking for a new tool goes to the team. |
| Settings, Connections | [before](before/settings-connections-desktop.png), [after](after/settings-connections-desktop.png) | [before](before/settings-connections-phone.png), [after](after/settings-connections-phone.png) | Each connection says what uses it in plain words. A running-out key says who to ask, with no Replace button, and there is no Usage tab. |
| Teams drawer | [before](before/teams-drawer-desktop.png), [after](after/teams-drawer-desktop.png) | [before](before/teams-drawer-phone.png), [after](after/teams-drawer-phone.png) | Approve and Decline are gone. The card says who can decide and who can’t, and its one button opens the approval page. |
| Drafts on Workflows | [before](before/drafts-desktop.png), [after](after/drafts-desktop.png) | [before](before/drafts-phone.png), [after](after/drafts-phone.png) | A draft says what it still needs and has Resume and Discard. |

## New in version 4

| Screen | Desktop | Phone | What it shows |
|---|---|---|---|
| Home, Needs you | [after](after/home-needs-you-desktop.png) | [after](after/home-needs-you-phone.png) | The same state as Home, a normal week. `shots.cjs` scrolls to the top before it shoots, so it looks the same. |
| Planner, check my workflows | [after](after/planner-check-workflows-desktop.png) | [after](after/planner-check-workflows-phone.png) | One row per workflow with its status, next run and one action. Only the first action is the main button. |
| Planner, why it stopped | [after](after/planner-why-stopped-desktop.png) | [after](after/planner-why-stopped-phone.png) | The question is typed, because Home has no Why chip for the stop that is already the first Needs you row. The troubleshooter’s four answers follow, with Retry the run. |
| Workflow page, More actions | [after](after/workflow-more-menu-desktop.png) | [after](after/workflow-more-menu-phone.png) | Run now, Change schedule, then Delete in red after a divider. Pause is a button beside the menu. Open in n8n shows only with Planned features. |
| Run page, detailed activity | [after](after/run-detailed-activity-desktop.png) | [after](after/run-detailed-activity-phone.png) | The agents’ conversation and the replay controls, opened on request. |
| Software watchlist, Needs attention | [after](after/software-attention-desktop.png) | [after](after/software-attention-phone.png) | The same state as Software watchlist. The files are the same image, for the same reason as Home, Needs you. |
| Agent library, What it can do | [after](after/library-what-it-can-do-desktop.png) | [after](after/library-what-it-can-do-phone.png) | I can, and Not yet with a plain reason for each, with no Planned marks by default. |
| Home with no AI model | [after](after/offline-home-desktop.png) | [after](after/offline-home-phone.png) | The Planner’s sorry face and one Connect a model button. Needs you counts six but shows three rows without the model row, which the hero already is. Read Jira tickets, Sum up what I find and Create a Jira ticket are Needs setup. |
| Software watchlist, Planned shown | [after](after/preview-software-desktop.png) | [after](after/preview-software-phone.png) | Security risks, support end dates and other sources, each tagged Planned. |
| Home, Mark what isn’t built | [after](after/mark-unbuilt-home-desktop.png) | [after](after/mark-unbuilt-home-phone.png) | Dashed outlines on the parts the built Portal doesn’t have yet. Needs you has no mark of its own, but it sits inside the outline of the Planner’s box. |

## What the judge saw in the after images

At b6cc589, the judge opened every after image. None was blank or half-typed, and quality.cjs measured no sideways scroll at 390 px. Since the first pass, the phone placeholder fits, the Settings tabs wrap instead of running off the edge, the check-my-workflows rows stack, and the “Not built” label is no longer cut short.

The judge saw the problems below at b6cc589. Fix round C (513b95a) fixed each one, and all 52 after images were shot again on 513b95a. The lead opened the six images these problems were in (`planner-cant-email-desktop`, `planner-check-workflows-desktop`, `offline-home-phone`, `software-attention-desktop`, `run-approval-desktop`, `agent-library-desktop`) and saw each one fixed. The Resume problem is not in a shot. Scenario H in `checks/results/v4.json` now passes, and so does every check in `v4-validate.json`.

- The Planner’s answers start at different places. Measured at 0, 900 and 3900 ms after the reply, the set-up card sits at x 294 to 1040, the can’t-email answer at 304 to 1030 and the check-my-workflows answer at 409 to 925. It is a layout difference, not an animation caught mid-way (`planner-check-workflows-desktop`, `planner-why-stopped-desktop`, `planner-cant-email-desktop`).
- On `offline-home-phone` the Ask the team box’s placeholder is cut off (“Ask the team for something that isn’t”).
- On `software-desktop` and `software-phone`, Needs attention has two main buttons, Review and decide and Use the new address.
- On `run-approval`, What happens says “nothing is written” three times in one paragraph.
- On `planner-cant-email`, “Ask the team if you need it.” appears in the reply and again in the card.
- On `agent-library`, the footer says “Open an agent to see how it works and to change it in plain English”, but changing an agent is Planned and hidden by default.
- Not in a shot: a paused workflow’s page shows two Resume buttons, one beside More actions and one in the banner (scenario H in `checks/results/v4.json`).
