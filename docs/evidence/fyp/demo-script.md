# Live demo script, first presentation

For the team lead, to edit. First presentation, 27 Nov 2026. The rubric slot is "Live demo of application, and CICD (6 to 8 min)". This script runs 6 minutes, with up to 1 minute of slack.

It was written against `main` at `a7ba7673` (14 Nov 2026). Every button, card line and screen name in quotes is the app's own wording, taken from `portal/src/`, `platform-api/src/` and the browser tests in `portal/e2e/live/`. The app writes its apostrophes curly (’), so search the code with that character. A value that depends on the AI model or on GitHub is shown in braces, such as `{newest}`.

## Read this first

Three facts change the flow you may expect.

1. **A release request never makes a set-up card.** The Planner sends any request about software versions or releases to the Software watchlist (`agent-runtime/src/agent_runtime/answers.py`). So the builder part of the demo uses a Jira request, and the release check runs from the Watchlist page.
2. **Two engines run side by side.** A workflow set up from Home is its own n8n workflow, saved as an n8n draft (engine PRs E4 and E5, merged). The Software watchlist and older workflows still run on the shared n8n workflow until E9 and E10. Say "new workflows are built in n8n", never "every workflow".
3. **Azure runs an older build.** The last deploy ran on 13 Nov at `2ea47c16` ([deploy run 43323016933](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/43323016933)). The set-up card's build panel, its test run and Turn it on landed on 14 Nov (#261, #262). Redeploy `main` before the demo, or Azure will not match this script. A person starts the deploy.

## Who is who

- **Alice** is the Operator. On Azure she is the Operator test account, which is also an Approver. On the local stack she is the dev user `alice`.
- **Bob** is an Approver. On Azure he is the second Approver test account. Locally he is `bob`.

On Azure, sign each account in to its own browser profile and put the two windows side by side. On the local stack, use one window and switch people with "Test controls", then "Act as". Azure shows the test accounts' own names, so read "Alice" and "Bob" here as those names.

## Run sheet

| # | Starts at | Step | Budget |
|---|---|---|---|
| 1 | 0:00 | Open on Home | 0:20 |
| 2 | 0:20 | Ask in plain words | 0:50 |
| 3 | 1:10 | Build it in n8n | 0:50 |
| 4 | 2:00 | Test run, then Turn it on | 0:30 |
| 5 | 2:30 | The release check runs to the yes | 0:50 |
| 6 | 3:20 | Bob approves, and the ticket is made | 1:00 |
| 7 | 4:20 | A stopped run, the troubleshooter, Retry | 0:50 |
| 8 | 5:10 | CI/CD | 0:50 |
| | 6:00 | End | |

If step 6 ends after 4:30, do step 7 with the two screenshots only, in 20 seconds.

## The steps

### 1. Open on Home (0:00 to 0:20)

**Do.** Start on Alice's Home, empty. If the chat has messages, press "New chat" before you begin.

**Say.** "CODESparks support staff repeat the same Jira work every week. Here they say what they want in plain words, and AI agents do the work. Nothing is written until a person says yes."

**They see.** The greeting ("Good morning, Alice", or afternoon), the heading "What should run by itself?", the Planner's face, the box "Ask, or describe a task", and three chips under it.

### 2. Ask in plain words (0:20 to 1:10)

**Do.** Type this and press Enter.

> Find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them

When the card asks "How often?", press "Every week". At "Which day?", press "Friday". At "Fridays, at what time?", press "17:00". If the "Jira project" box is empty, type `MOCK`.

**Say.** "The Planner shows what it understood, one part at a time. It never guesses a time, so it asks."

**They see.** "Here’s what I understood." and a card with the pill "Draft". The card has three parts, "Watch", "When" and "Then", each with a tick or a question mark. "Then" ends with "After a yes". The foot says "1 question to answer" until the time is set. Then "When" reads "Every Friday at 17:00, Singapore time".

The sentence is the one the browser test uses (scenario A in `portal/e2e/live/08-planner-home.live.ts`). That test runs with a stand-in model, and its card was titled "Find bug tickets in MOCK". The real model may word the card differently, so rehearse this sentence on Azure.

### 3. Build it in n8n (1:10 to 2:00)

**Do.** Press "Set up". Point at the panel that opens on the right.

**Say.** "Set up builds a real n8n workflow. Before it saves anything, the safety checker puts a yes in front of every write. A draft that isn't safe is never saved, and the builder can't publish it by itself."

**They see.** The card's pill turns "Building". The panel shows "Building in n8n" and "Draft" over a canvas. Its status line moves through "Adding blocks in n8n…", "Safety checker is checking the write…" and "Saved as a draft in n8n." The blocks appear one by one: the schedule ("Fri 17:00"), "Start from the Portal", the agent, "Ask for a yes", "Create ticket" and "Nothing to change". Our own blocks carry the badge "Our block". Under the canvas are the checks "The blocks fit together." and "Every write waits for a yes." In the card, beside the safety checker's face, is "Added a yes before the ticket." The panel's last line is "The builder saves a draft. It can’t publish by itself."

The panel opens by itself only when the window is wider than 900 CSS pixels (`portal/src/ui/media.ts`). Check the zoom on the projector.

### 4. Test run, then Turn it on (2:00 to 2:30)

**Do.** Wait. The test run starts by itself. When "Turn it on" shows, press it.

**Say.** "It tests itself first. A test run stops at the yes, so it asks nobody and writes nothing. Only after it passes can I turn it on."

If the test run is slow, add: "The Tester runs the same blocks, up to the yes."

**They see.** "Test run…" beside the Tester's face, then "Test run passed up to the yes. Nothing was written." (or "Test run passed. There was nothing new to write."). The pill turns "Ready". After "Turn it on", the card says "On. First run {day}, 17:00." with the pill "On", and the panel says "On. Version 1, published in n8n."

Do not say it runs now. It runs on Fridays at 17:00.

### 5. The release check runs to the yes (2:30 to 3:20)

**Do.** In the rail on the left, press "Watchlist". Show the LangGraph row. Press "Check now".

**Say.** "Our first use case for the sponsor is the release check. The team lists the software it runs, and a check reads each one's releases on GitHub. This is the live activity view. Each step lights up as the agents work."

When it stops at the yes, add: "I started this run, so I can't approve it. Nobody approves their own work."

**They see.** The run page, titled "Software watchlist", with the pill "Running" and then "Waiting for a yes". The line has four steps: "Started by Alice", "Read every source" (with the Version checker's face and "Working, {n} s"), "Ask for a yes" (amber dashes march into it) and "Create Jira tickets". Under it, "Step by step" lists what each agent did. Alice gets no Approve button. Her "Why not you" line ends with "so another Approver must decide. Nobody approves their own work."

### 6. Bob approves, and the ticket is made (3:20 to 4:20)

**Do.** Switch to Bob. Press "Teams" in the top bar, which now shows a count. In the drawer, on the newest message, press "Open in AI Workflow Builder". Read the summary line out. Press "Approve". When the pill says "Done", press the ticket key under "Create Jira tickets".

**Say.** "Bob gets the request in Teams. Its one button opens the exact change, and he decides there. He decides on what will be written, not on the AI's summary. Only after his yes is the ticket made."

**They see.** The drawer, headed "Microsoft Teams", with "Practice copy. Nothing reaches the real Teams." Then the approval:

- "Approval, from Alice’s Software watchlist" over "Create 1 Jira ticket".
- Under "What will be written", the rows "Where" ("Jira project MOCK on the practice Jira") and "Summary" ("Upgrade LangGraph from {our version} to {newest}").
- A "Not checked" line naming what the run could not check.
- "Summary by AI. {summary} Decide on the change above, not this."
- "Why you", with "No one can approve their own work."
- The buttons "Ask Alice", "Approve" and "Decline".

After the yes, the pill turns "Done". The log says "Bob said yes." and "Created MOCK-{n} in Jira." The line under the steps reads "Done at {time} · MOCK-{n} created after Bob’s yes". The ticket key opens the "Practice Jira" page, which says "Practice copy. Nothing reaches a real Jira."

If asked whether that is the real Teams, say: "It's our practice copy. With the Teams webhook set, the same card goes to a real channel." Azure keeps the practice copy while `teams_webhook_url` is empty (`infra/envs/dev/variables.tf`). The Teams card has no Approve button on purpose. The decision is always made in the app.

### 7. A stopped run, the troubleshooter, Retry (4:20 to 5:10)

Azure has no safe way to stop a run on purpose, because it reads the real GitHub. The browser tests stop one by switching the stand-in GitHub off (`POST /_admin/mode` on `mock-github`), and that stand-in runs only on the test stack. So prepare the stop before the demo, with one of these plans.

- **A. A stop already on Azure.** If Alice's Needs you shows "{Workflow} stopped at {time}", open it from there or from "Workflows". Press "Retry" only if "Safe to retry" starts with "Yes".
- **B. The screenshots.** Show `n15-b-stopped.png`, then `n15-b-retried.png` (see Backup). They show this build's screens. Say the stop came from the test suite, which switches GitHub off on purpose.
- **C. The local stack. Untested.** Before the demo, turn Wi-Fi off, press "Check now", and wait for "Stopped". Then turn Wi-Fi back on. In the demo, open that run and press "Retry". In CI the stop took 4 seconds with a stand-in GitHub that answered 503. Without Wi-Fi it may take longer.

**Do.** Open the stopped run. Point at the three answers. Press "Retry".

**Say.** "When a run stops, the AI troubleshooter answers three questions: what happened, what was affected, and whether a retry is safe. Nothing was written, so a retry is safe. It waits a short time, runs again, and the write still needs a new yes."

**They see.** The pill "Stopped", red dashes into "Read every source", and three answers: "What happened" ("GitHub didn't answer at {time}."), "Affected" ("Nothing. No ticket was written.") and "Safe to retry" ("Yes. Nothing was written, so a retry is safe."). "Details" opens the failure text. After "Retry", the dashes move again, and the pill returns to "Waiting for a yes".

### 8. CI/CD (5:10 to 6:00)

**Do.** Switch to the GitHub tab on the `ci` run for `a7ba7673`, [run 43590669307](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/43590669307). Open the "e2e" job. Then show the newest run of the `deploy` workflow.

**Say.** "Every push to main runs seven jobs at once. They lint, type-check and unit-test the code, Semgrep looks for security bugs, and gitleaks looks for leaked secrets. Then the whole stack starts, and our tests drive the real app in a browser. OWASP ZAP scans the running app, and k6 load-tests it. A deploy to Azure is a separate workflow that a person starts, and Terraform refuses to destroy anything unless we say so."

**They see.** Seven green jobs: "checks (platform-api)", "checks (agent-runtime)", "checks (e2e)", "portal", "n8n-node-pack", "scans" and "e2e". Inside "e2e" are three steps: "Run the API tests, then the browser suite, against the whole stack" (36 minutes on that run), "DAST with OWASP ZAP against the whole stack" (5 minutes) and "Load test with k6 against the whole stack" (2 minutes). The run keeps its reports as artifacts: `semgrep-report`, `zap-reports`, `k6-summary`, `portal-live-evidence` and `e2e-logs`.

If asked, the e2e job runs on pushes to `main` and by hand, not on pull requests (`.github/workflows/ci.yml`). Terraform and OpenTofu validate, tflint and Checkov run in the separate `infra` workflow. The pipeline diagram is `docs/evidence/diagrams/13-ci-cd-pipeline.png`.

## Do not show or claim

These are not built on `main` yet. Showing one as working breaks the "Never" list in `docs/design/ai-native-principles.md`.

- "Open in n8n" and the "In n8n" tab (E7, E8).
- "Changed in n8n", and Undo or roll back of a change made in n8n (E6).
- The Software watchlist as its own n8n workflow (E9, E10).
- n8n's node allow list switched on in the Azure deploy (E11).
- A workflow that emails or posts in a Teams channel. Tell is built in the API (#249, #252), but the Planner does not lay it out in a set-up card yet (`builder/layout.py`). Asked for one, the Planner answers "I can't send email yet".
- The sponsor's access review with two Approvers. That is Phase 2.

## Honest answers if asked

- **Is the troubleshooter an AI model?** No. Its three answers come from fixed rules over the run's own events (`platform-api/src/platform_api/monitoring/troubleshooter.py`), so it can't invent a cause. The AI model reads requests for the Planner and writes the run's summary.
- **Does the AI write the Planner's replies?** The model reads the request. Code decides which answer to give, and the sentences are fixed text (ADR 0037).
- **Are Teams and Jira real?** They are practice copies inside the app. Each answers the same API as the real system, so moving to the real one is a change of settings (ADR 0035).
- **Which AI model is it?** Whatever Settings shows on the day. On 31 Oct it was Claude Haiku 5.5 through the AI Singapore gateway (P14 lane 6). The final choice is still open.

## Backup plan

If a step fails twice, move to its backup and keep talking.

| What fails | What you notice | What to do |
|---|---|---|
| Azure | The Portal doesn't load, sign-in hangs, or an action errors | Switch to the local stack, already running (backup 2). Same script, with "Test controls" for Alice and Bob. |
| AI model gateway | The Planner can't answer, or Home says "I can’t read new requests until an AI model is connected" | Show steps 2 to 4 with `n11-card-1440.png`, `n11-ready-1440.png` and `n11-on-1440.png`. Steps 5 to 7 still run live. The check reads GitHub without the model, and only its summary uses the model, with a fixed template when the model doesn't answer (`agent-runtime/src/agent_runtime/summary.py`). |
| n8n | Set up says n8n did not take the draft, or a run stops with "A step in the workflow engine failed." | Try once more after a minute. Then switch to the local stack, or to the video. |
| Wi-Fi | Nothing loads. Azure and the local stack both need the internet, for GitHub and the AI model | Use your phone's hotspot. If that fails too, play the video, then show the screenshots. |
| GitHub, for CI/CD | The Actions page doesn't load | Show `docs/evidence/diagrams/13-ci-cd-pipeline.png` and the reports in `docs/evidence/sast/2026-11-14/`, `docs/evidence/dast/` and `docs/evidence/load-test/2026-11-rebuild/`. |

### Backup 1, a recorded video

There is none yet. The browser tests record no video (`video: 'off'` in `portal/e2e/live/playwright.config.ts`). Record the dry run as two clips, the app (3 to 4 minutes) and CI/CD (up to 3 minutes). Together they are also the rubric's other option, "MVP videos of the working app (3 to 4 min) and CICD (3 to 4 min)".

### Backup 2, the local stack

From an up-to-date `main`, run `scripts/up.sh`. It prints the Portal (http://localhost:8080), platform-api and n8n addresses. It needs Docker and about 3 GB free on Docker's disk (`docs/evidence/deploy/README.md`).

- It reads the real GitHub, and it needs the AI model connected in Settings, on the "Model" tab ("Connect", then "Test and save"). Bob confirms a new model address.
- Add LangGraph to its watchlist, as on Azure.
- Dev sign-in, and so "Test controls", work only on localhost.
- `scripts/down.sh` deletes the stack's data (it runs `docker compose down -v`). Never run it between setting up and the demo.

### Backup 3, screenshots of this build

The latest green CI run keeps them in its `portal-live-evidence` artifact until 12 Feb 2027. Download it with `gh run download 43590669307 -n portal-live-evidence -D ~/Desktop/demo-shots`. From `shots/`, keep these, in demo order:

1. `n11-card-1440.png`, the set-up card asking "How often?"
2. `n11-ready-1440.png`, built in n8n, test run passed
3. `n11-on-1440.png`, turned on
4. `p5-02-alice-own-run.png`, Alice can't approve her own run
5. `p5-02-teams-drawer.png`, the Teams practice copy
6. `p5-02-bob-waiting.png`, the approval Bob sees
7. `p5-02-bob-done.png`, done, with the ticket
8. `n15-b-stopped.png`, the troubleshooter's three answers
9. `n15-b-retried.png`, after Retry

They come from the test stack, with a stand-in GitHub and model, so say so. The screenshots already in `docs/evidence/` (`rebuild/`, `n16-workflow-page/`, `n21-fix/`, `usability/`) predate the 13 Nov chat-first redraw. Use them only as a last resort.

## Pre-flight checklist

### The day before

- [ ] Redeploy `main` to Azure with the `deploy` workflow, `allow_destroy` off. Check that its commit has a green `ci` run.
- [ ] Do a full, timed dry run on Azure, and record it (backup 1).
- [ ] Rehearse the release check with a software other than LangGraph, such as FastAPI at an older version. A check proposes no new ticket for a software while an earlier one waits for a yes (`agent-runtime/src/agent_runtime/contract.py`). What it does once a ticket exists is not confirmed here. So LangGraph should meet its first check in the demo.
- [ ] After each rehearsal, delete the workflow that step 2 made. Otherwise the Planner may answer "You already have this one."
- [ ] Start the local stack (backup 2) and walk the script on it once.
- [ ] Download the screenshots (backup 3) to the laptop.

### The morning of the demo

- [ ] The Portal on Azure loads. Alice and Bob are signed in, each in their own browser profile.
- [ ] Each window is wider than 900 CSS pixels at the zoom you will project.
- [ ] Settings shows the AI model connected. Home shows the box, not "I can’t read new requests until an AI model is connected".
- [ ] With `AZURE_PORTAL_URL` set to the Portal's address, `scripts/checks/p14.sh lane 3` passes. It checks that platform-api is ready, with the activity log, the Cosmos DB copy and n8n's workflows ([deploy README](../deploy/README.md), section 5).
- [ ] LangGraph is on the Watchlist at an older "Version we run", a real LangGraph release a few versions back, written as three numbers. Its "Upgrade ticket" says "None yet", and nothing waits for a yes.
- [ ] No other rows are on the Watchlist. Remove the rest, such as any left from the P14 lanes (FastAPI, Pydantic, HTTPX, Requests), so the approval reads "Create 1 Jira ticket".
- [ ] The Watchlist's schedule is off until after the demo. Press "Turn off schedule" at the foot of the page. A scheduled check that morning would take LangGraph's first check. While its request waits, your "Check now" run ends with "Skipped. An earlier run is still waiting for a yes."
- [ ] No request waits for Bob in the Teams drawer, so the newest message is the demo's.
- [ ] On Alice's Home, press "New chat". Needs you is empty, or holds only the stopped run for step 7, plan A.
- [ ] Plan A, B or C for step 7 is chosen and ready.
- [ ] GitHub is signed in, with one tab on the CI run and one on the `deploy` run.
- [ ] Local stack running and checked, with LangGraph added.
- [ ] Video and screenshots on the desktop, playable offline.
- [ ] Phone hotspot ready. Notifications off. Other tabs closed. A timer running on your phone.

### After the demo

- [ ] Pause or delete the workflow from step 2 on its workflow page. It is set to run every Friday at 17:00, and 27 Nov is a Friday.
- [ ] Set the watchlist's schedule again with "Set a schedule".
