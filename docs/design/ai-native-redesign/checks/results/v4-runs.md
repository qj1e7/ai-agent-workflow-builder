# Interaction counts, v4

Prototype: `docs/design/ai-native-redesign/prototype.html`. Paths: `docs/design/ai-native-redesign/checks/paths-v4.cjs`.

Real scenarios: 127 passed, 0 failed, 1 not possible. Control (must fail): failed, as it should.

| Id | Width | Task | Passed | Clicks | Fields | Selects | Decisions | Screens | Notes |
|---|---|---|---|---|---|---|---|---|---|
| A | 1280 | First-time Operator sets up a weekly Jira summary and turns it on | yes | 4 | 1 | 0 | 3 | 1 | plannerQuestions 2 |
| A | 390 | First-time Operator sets up a weekly Jira summary and turns it on | yes | 4 | 1 | 0 | 3 | 1 | plannerQuestions 2 |
| B | 1280 | Experienced Operator finds what needs attention and fixes the stopped Morning new-ticket check | yes | 2 | 0 | 0 | 1 | 3 |  |
| B | 390 | Experienced Operator finds what needs attention and fixes the stopped Morning new-ticket check | yes | 2 | 0 | 0 | 1 | 3 |  |
| C | 1280 | Bob, an Approver only, opens the upgrade request, sees what changes and the evidence, and approves | yes | 2 | 0 | 0 | 1 | 2 |  |
| C | 390 | Bob, an Approver only, opens the upgrade request, sees what changes and the evidence, and approves | yes | 2 | 0 | 0 | 1 | 2 |  |
| C-self | 1280 | Alice turns on a workflow, does a test run, and cannot approve her own test run | yes | 5 | 1 | 0 | 3 | 2 |  |
| D | 1280 | An Operator asks to email a weekly list, and the limit is explained with a next step | yes | 1 | 1 | 0 | 0 | 1 |  |
| E | 1280 | The user corrects the Planner’s guess of project and schedule on the card, without starting again | yes | 3 | 1 | 2 | 2 | 1 |  |
| F | 1280 | Recover the stop the user can fix, and report the platform bug to support | yes | 6 | 0 | 0 | 2 | 3 |  |
| G | 1280 | Monitor Kubernetes releases from Home ends with Kubernetes on the Software watchlist | yes | 4 | 1 | 0 | 2 | 1 |  |
| H | 1280 | Pause a workflow, change its schedule, and delete one with its confirmation | yes | 10 | 1 | 2 | 5 | 3 |  |
| T1 | 1280 | Set up a workflow from example 1: example, time, Jira project, Turn it on | not possible | - | - | - | - | - | Since 8 Nov the starting points under “Set up another workflow” are software versioning only (Keep track of the React version). None sets up a general Jira workflow, so there is no example to tap. Typing the same request is scenario T2. |
| T2 | 1280 | Set up a typed workflow with every part stated: type, Enter, Turn it on | yes | 2 | 1 | 0 | 1 | 1 |  |
| T3 | 1280 | Do a test run after turning one on | yes | 1 | 0 | 0 | 0 | 2 |  |
| T4 | 1280 | Add software from Home with example 3: example, Looks right, Start from the newest, Add React | yes | 5 | 1 | 0 | 2 | 1 |  |
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
| ASK-status | 1280 | “Check my workflows” typed to the Planner | yes | 1 | 1 | 0 | 0 | 1 |  |
| ASK-status | 390 | “Check my workflows” typed to the Planner | yes | 1 | 1 | 0 | 0 | 1 |  |
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
| ANS-cross | 1280 | A clause the Planner can’t read gets a cross that quotes it, and the button sets up the part it can | yes | 4 | 1 | 0 | 3 | 1 |  |
| ANS-cross | 390 | A clause the Planner can’t read gets a cross that quotes it, and the button sets up the part it can | yes | 4 | 1 | 0 | 3 | 1 |  |
| ANS-left-out | 1280 | After “Set up the part I can”, the card and the workflow’s page still say what was left out | yes | 6 | 1 | 0 | 3 | 3 |  |
| ANS-verbs | 1280 | A clause of verbs and little words, such as “let me know”, still gets a cross, and never “Nothing is unclear” | yes | 3 | 3 | 0 | 0 | 1 |  |
| ANS-whole-clause | 1280 | A cross quotes the whole clause, not one word of it | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-stale | 1280 | Every wording of “not updated for a while” gets the honest can’t, never a silent drop | yes | 3 | 3 | 0 | 0 | 1 |  |
| ANS-none-hers | 1280 | A request with no part in her own words gets no set-up card of guesses | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-leftover-everywhere | 1280 | A part answer and an edit card mark the clauses they didn’t read too | yes | 2 | 2 | 0 | 0 | 1 |  |
| ANS-cant-clause | 1280 | A can’t answer never crosses the clause it answered | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-cant-runs | 1280 | A can’t answer reads only its can’t phrase, so the rest of that clause is still marked | yes | 3 | 3 | 0 | 0 | 1 |  |
| ANS-phrase-runs | 1280 | A summary’s describing words are read, and a quote keeps its object and the phrase it names | yes | 3 | 3 | 0 | 0 | 1 |  |
| ANS-cant-alternative | 1280 | The alternative to an email request sets up cleanly, with the email clause gone | yes | 1 | 0 | 0 | 1 | 1 |  |
| ANS-ticked-runs | 1280 | In a clause a rule read, a cross quotes only the unread words, and the gaps are read | yes | 4 | 4 | 0 | 0 | 1 |  |
| ANS-narrow-cards | 901 | Beside the panel, a narrow chat gives the cards two-column rows, and a chip stays on one line | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-narrow-cards | 1024 | Beside the panel, a narrow chat gives the cards two-column rows, and a chip stays on one line | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-clash-day | 1280 | Two days in a set-up request ask which one, and an edit card takes focus at its heading | yes | 2 | 2 | 0 | 0 | 1 |  |
| ANS-clash-time | 1280 | Two times in a set-up request ask which one, never the first picked | yes | 2 | 1 | 0 | 1 | 1 |  |
| ANS-testctl | 1280 | The test controls never cover the product, scrolled or not, chatting or not | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-testctl | 900 | The test controls never cover the product, scrolled or not, chatting or not | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-testctl | 390 | The test controls never cover the product, scrolled or not, chatting or not | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-edit-days | 1280 | Two days for one schedule get a cross, and Save change waits | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-name-words | 1280 | A schedule word in a workflow’s name is neither a schedule nor a command | yes | 3 | 3 | 0 | 0 | 1 |  |
| ANS-questions | 1280 | Asking when a workflow runs gets its state and next run, never “I can only change” | yes | 4 | 4 | 0 | 0 | 1 |  |
| ANS-edit-missing | 1280 | A workflow that doesn’t exist is named, and a change it can’t make keeps the question asked with it | yes | 2 | 2 | 0 | 0 | 1 |  |
| ANS-edit-after | 1280 | After Save change: the watchlist says who owns it, a paused workflow says so, and a later change elsewhere is named | yes | 4 | 2 | 0 | 2 | 1 |  |
| ANS-asks | 1280 | A bare hour is asked, “make it daily” after a draft offers the draft, and three more questions are answered from state | yes | 6 | 5 | 0 | 1 | 1 |  |
| ANS-one-question | 1280 | With nothing said about when, the card asks how often, then the day, then the time, one at a time | yes | 4 | 1 | 0 | 3 | 1 |  |
| ANS-one-question | 390 | With nothing said about when, the card asks how often, then the day, then the time, one at a time | yes | 4 | 1 | 0 | 3 | 1 |  |
| ANS-no-time | 1280 | A request that names a day but no time is asked for the time, never given one | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-watch-parts | 1280 | Watching software marks each part, and a time the watchlist doesn’t keep gets a cross | yes | 2 | 2 | 0 | 0 | 1 |  |
| ANS-watch-parts | 390 | Watching software marks each part, and a time the watchlist doesn’t keep gets a cross | yes | 2 | 2 | 0 | 0 | 1 |  |
| ANS-edit-save | 1280 | Change a schedule by asking: Save change publishes version 2, the page lists it, and Undo goes back | yes | 6 | 1 | 0 | 2 | 3 |  |
| ANS-edit-save | 390 | Change a schedule by asking: Save change publishes version 2, the page lists it, and Undo goes back | yes | 6 | 1 | 0 | 2 | 3 |  |
| ANS-edit-never | 1280 | The review’s “every day instead of every Monday” gets an edit card, and Never mind changes nothing | yes | 3 | 1 | 0 | 1 | 2 |  |
| ANS-edit-honest | 1280 | A change the card can’t make gets an honest answer, and a check that doesn’t exist is named | yes | 2 | 2 | 0 | 0 | 1 |  |
| ANS-status | 1280 | Questions in other words get answers from platform state | yes | 6 | 6 | 0 | 0 | 1 |  |
| ANS-status | 390 | Questions in other words get answers from platform state | yes | 6 | 6 | 0 | 0 | 1 |  |
| ANS-status-commands | 1280 | A question with a change word in it is a command, never a status answer | yes | 4 | 4 | 0 | 0 | 1 |  |
| ANS-live | 1280 | An older answer reads current state: a pause in the panel and an approval on another page show in it | yes | 8 | 1 | 0 | 2 | 3 |  |
| ANS-live-done | 1280 | A workflow turned on in the chat, then paused on its page, reads as paused back in the chat | yes | 4 | 0 | 0 | 1 | 3 |  |
| ANS-panel | 1280 | While the Planner builds, the panel opens by itself with the steps going in, but never on a phone | yes | 2 | 1 | 0 | 0 | 1 |  |
| ANS-panel | 880 | While the Planner builds, the panel opens by itself with the steps going in, but never on a phone | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-panel | 390 | While the Planner builds, the panel opens by itself with the steps going in, but never on a phone | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-panel-focus | 1440 | Focus stays on the card’s heading while the panel opens by itself and the steps go in | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-panel-focus | 1280 | Focus stays on the card’s heading while the panel opens by itself and the steps go in | yes | 1 | 1 | 0 | 0 | 1 |  |
| ANS-scroll-390 | 390 | On a phone, answering the card’s questions and saving a change never scrolls the app out of place | yes | 5 | 2 | 0 | 3 | 1 |  |
| KEYS-A | 1280 | Scenario A with the keyboard only | yes | 12 | 1 | 0 | 3 | 1 |  |
| KEYS-C | 1280 | Scenario C with the keyboard only | yes | 12 | 0 | 0 | 1 | 2 |  |
| RUN-three | 1280 | A stopped run answers what happened, what was affected and whether a retry is safe, the same in Needs you, the chat, the side panel and the run page | yes | 5 | 1 | 0 | 0 | 3 |  |
| RUN-three | 390 | A stopped run answers what happened, what was affected and whether a retry is safe, the same in Needs you, the chat, the side panel and the run page | yes | 5 | 1 | 0 | 0 | 3 |  |
| RUN-three-approver | 1280 | An Approver sees a stopped run’s three answers with no buttons, and the note that says who can act | yes | 3 | 0 | 0 | 0 | 4 |  |
| RUN-line | 1280 | The FLOW run line: red into the stop, amber and slow into a waiting yes, dashes into the working step, faint into skipped ones, solid once the next step is done | yes | 6 | 0 | 0 | 0 | 3 |  |
| RUN-line | 861 | The FLOW run line: red into the stop, amber and slow into a waiting yes, dashes into the working step, faint into skipped ones, solid once the next step is done | yes | 6 | 0 | 0 | 0 | 3 |  |
| RUN-line | 390 | The FLOW run line: red into the stop, amber and slow into a waiting yes, dashes into the working step, faint into skipped ones, solid once the next step is done | yes | 6 | 0 | 0 | 0 | 3 |  |
| RUN-retry-from-chat | 1280 | A retry on a run page opened from the chat keeps Back to the chat, and the chat card follows | yes | 5 | 1 | 0 | 1 | 2 |  |
| RUN-retry-from-chat | 390 | A retry on a run page opened from the chat keeps Back to the chat, and the chat card follows | yes | 5 | 1 | 0 | 1 | 2 |  |
| RUN-line-panel | 1280 | The side panel’s run line is the same line, small, with the same links | yes | 2 | 1 | 0 | 0 | 1 |  |
| RUN-line-panel | 901 | The side panel’s run line is the same line, small, with the same links | yes | 2 | 1 | 0 | 0 | 1 |  |
| RUN-line-panel | 390 | The side panel’s run line is the same line, small, with the same links | yes | 2 | 1 | 0 | 0 | 1 |  |
| APPR-not-checked | 1280 | The approval names what wasn’t checked, from the run and the capability registry, and the side panel trims nothing that will be written | yes | 3 | 1 | 0 | 0 | 2 |  |
| APPR-not-checked | 390 | The approval names what wasn’t checked, from the run and the capability registry, and the side panel trims nothing that will be written | yes | 3 | 1 | 0 | 0 | 2 |  |
| APPR-not-checked-jira | 1280 | A ticket summary’s approval says the agents can’t see a ticket’s type, priority or owner | yes | 0 | 0 | 0 | 0 | 1 |  |
| APPR-ask | 1280 | An Approver asks the requester a question: the request stays open, the answer shows on it, and nothing is decided | yes | 4 | 1 | 0 | 1 | 2 |  |
| APPR-ask | 390 | An Approver asks the requester a question: the request stays open, the answer shows on it, and nothing is decided | yes | 4 | 1 | 0 | 1 | 2 |  |
| APPR-answer | 1280 | The requester finds the question in Needs you and answers it on the request, which still waits for someone else’s yes | yes | 4 | 1 | 0 | 1 | 2 |  |
| APPR-decline | 1280 | Decline asks why, with quick reasons and none needed, and the reason shows with the declined record | yes | 4 | 0 | 0 | 2 | 2 |  |
| APPR-decline | 390 | Decline asks why, with quick reasons and none needed, and the reason shows with the declined record | yes | 4 | 0 | 0 | 2 | 2 |  |
| APPR-decline-none | 1280 | A decline needs no reason, and then the record has none | yes | 3 | 0 | 0 | 1 | 2 |  |
| APPR-panel | 1280 | Deciding in the side panel: focus goes to the panel’s heading, #app stays put, and the card in the chat follows | yes | 6 | 1 | 0 | 2 | 1 |  |
| APPR-panel | 901 | Deciding in the side panel: focus goes to the panel’s heading, #app stays put, and the card in the chat follows | yes | 6 | 1 | 0 | 2 | 1 |  |
| APPR-panel | 390 | Deciding in the side panel: focus goes to the panel’s heading, #app stays put, and the card in the chat follows | yes | 6 | 1 | 0 | 2 | 1 |  |
| DECLINED-sw | 1280 | A declined upgrade check says Declined, shows no write and gives the reason: on its line, in its agents’ chat, in Teams and on the watchlist | yes | 4 | 0 | 0 | 0 | 2 |  |
| DECLINED-test-run | 1280 | A declined test run reads the same in Needs you, on its workflow page, in the chat’s side panel and in Teams | yes | 8 | 1 | 0 | 0 | 4 |  |
| KEYS-APPR | 1280 | Ask, the decline reasons and Decline with the keyboard only, each with a visible focus | yes | 24 | 0 | 0 | 3 | 2 |  |
| MARK-approval | 1280 | With Mark what isn’t built on, Not checked, Ask, the question box, the questions and the decline reasons each carry a label | yes | 4 | 1 | 0 | 0 | 2 |  |
| RUN-retry-panel | 1280 | A retry in the side panel puts focus on the panel’s heading, and #app stays put | yes | 3 | 1 | 0 | 1 | 1 |  |
| RUN-retry-panel | 390 | A retry in the side panel puts focus on the panel’s heading, and #app stays put | yes | 3 | 1 | 0 | 1 | 1 |  |
| APPR-decide-nav | 1280 | A half-picked decline reason doesn’t survive leaving the page | yes | 5 | 0 | 0 | 0 | 3 |  |
| APPR-thread-kept | 1280 | Once a request is decided its questions stay on the record, read only, for the Approver and the requester | yes | 5 | 1 | 0 | 1 | 2 |  |
| DECLINED-access | 1280 | When the second Approver declines after the first said yes, the record says both, in the run and in Teams | yes | 5 | 0 | 0 | 2 | 2 |  |
| WF-last-run | 1280 | Workflows rows and the chat’s check card give each workflow’s last run from one source, a declined run included, each on one line | yes | 3 | 1 | 0 | 0 | 3 |  |
| WF-last-run | 390 | Workflows rows and the chat’s check card give each workflow’s last run from one source, a declined run included, each on one line | yes | 3 | 1 | 0 | 0 | 3 |  |

A click includes a key press on a button. Menu steps and page changes are included. A decision is also counted as a click, a select or a field. Test controls are never counted.
