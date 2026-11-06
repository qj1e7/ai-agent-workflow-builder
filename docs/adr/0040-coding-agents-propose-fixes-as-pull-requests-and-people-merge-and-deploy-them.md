---
status: proposed
---

# Coding agents propose fixes as pull requests, and people merge and deploy them

When a run stops because of a fault in the platform's own code, the AI troubleshooter says so, and the person reports it to support (ADR 0038). Today a developer must then dig through the run, find the cause, write a fix and a test, and ship it. The sponsor's biggest worry is keeping the platform working after handover with few technical people. Ready-made coding agents can now work from an issue: they read the code, write a failing test, fix it, and open a pull request. Claude Code's GitHub Action and GitHub Copilot's coding agent are two examples.

The design note lists this as a later feature that needs NCS's agreement: "Having coding agents write the fix, with a developer reviewing and merging … Agents never merge or deploy." This ADR says how it would work. It is not part of the 23-PR plan in `docs/design/ai-native-redesign/IMPLEMENTATION-PLAN.md`. It assumes someone after handover can review code now and then. The section on no reviewer says what happens if nobody can.

## Proposed decision

**An agent writes the fix and a person decides.** The coding agent does the work up to a pull request that is ready to review. A person who can read code merges it, and a person approves the production deploy. Agents never approve, merge or deploy. This is the code's version of the product's rule: no write without a human's yes.

1. **A platform problem becomes an issue.** When a "Platform problem" team request is created (ADR 0038), the platform opens an issue in the code host. The issue carries:
   - the run's id and its events;
   - the AI troubleshooter's notes;
   - the person's words.

   Ticket text and the person's words are quoted as data, under a heading that tells the agent not to follow instructions inside them. Nothing secret may go into the issue. Run events don't mask keys or tokens today, so the code that builds the issue checks its text for them and refuses to post one it finds. That check must be built and tested before the first issue is opened.
2. **The coding agent works only from that issue, in CI, not inside the platform.** It runs as a CI job in the code host:
   - with read access to the code and permission to open a branch and a pull request;
   - with no production keys and no access to the deployed app;
   - one pull request per issue.

   It must open its pull request with a test that fails without the fix, the fix itself, and a plain-language note of what was wrong and what changed. If CI fails twice on its own pull request, it stops and hands the issue to people.
3. **Some code is off limits to the agent.** A CI check fails any agent pull request that touches:
   - the approval gate and the safety checker (`platform-api/src/platform_api/orchestration/approvals.py`, `write_actions.py`);
   - sign-in and roles (`platform-api/src/platform_api/auth.py` and `oidc.py`);
   - infrastructure (`infra/`);
   - CI and deploy settings (`.github/`);
   - the agents' tool list (`agent-runtime/src/agent_runtime/tools.py`).

   A fix there must be written by a person. This keeps an agent from weakening the controls that check it.
4. **A review agent checks every fix, and a person approves it.**
   - **The review agent.** It comes from a different model family from the coding agent, so they are less likely to share a blind spot. It reviews every agent pull request and posts its findings. Its check must pass, but it never counts as an approval.
   - **Branch protection.** No one pushes straight to main. A pull request merges only with:
     - one approving review from a person listed in `CODEOWNERS`, the platform's code reviewers;
     - green CI: lint, unit tests, SAST, DAST, and the AI evals;
     - the review agent's check.

     Bot accounts get no merge rights.
5. **Deploying keeps today's human step.** A merge builds the container images and deploys them to the test environment, where smoke tests run. Production needs an approval from a named person, through the deploy environment's reviewers (today's `deploy.yml` is already started by hand). Rollback means redeploying the previous pinned image.
6. **The app shows the case and keeps two roles.** The support case in the app reads its status from the code host:
   - Reported;
   - Agents are writing a fix;
   - Fix ready, waiting for review by the platform developers;
   - Fixed and live.

   Then the person retries the stopped run, and any write still waits for an Approver's yes. Code reviewers are named in the code host, not in the app, so the app keeps its two roles, Operator and Approver.
7. **Everything is linked in the record.** The activity log links the run, the team request, the issue, the pull request, who reviewed and merged it, and the deploy and who approved it.

## If there is no human reviewer

A review agent can check a fix, but it can't stand in for the person who approves it, for four reasons:

- **The agents can miss the same thing.** Two agents can share a blind spot, so a test the coding agent didn't think of is often one the review agent doesn't ask for either. A person brings a different kind of judgement.
- **Both agents read the same untrusted text.** A ticket body written to mislead one model can mislead the other. The person is the only reader the run's data can't instruct.
- **Someone must answer for a change.** When a fix breaks every team's workflows, the sponsor needs to know which person agreed to it.
- **It breaks our own rules.** It would break AGENTS.md ("Agents never approve PRs") and the product's principle that the AI's summary is never the check.

So without a reviewer, fixes stop at "Fix ready, waiting for review". The agent's work is not wasted. A developer brought in later, such as an NCS developer, a contractor or a returning team member, can review a ready fix with its test in minutes, instead of investigating from scratch.

Letting the review agent approve and merge on its own is technically possible, since code hosts allow bots to approve and auto-merge. It is the platform changing its own code with no person involved, the riskiest kind of write. It would need its own ADR, a change to AGENTS.md, and the sponsor's written acceptance of the risk.

## Questions for the sponsor

1. After handover, where will the code live: on GitHub, or in NCS's GitLab inside DevNet?
2. May a coding agent, and which AI model, read and change that code? This joins question 2 in `docs/design/devnet-move.md`, about which model DevNet may call.
3. Who will be listed in `CODEOWNERS` to review fixes, and who approves production deploys?

## Considered options

- **No coding agent. A developer investigates each report.** The safest choice, and the fallback whenever there is no reviewer. Rejected as the end state, because it does nothing for the sponsor's worry about handover.
- **The agent only diagnoses.** It writes its findings on the issue, but no code. A good first step to build, and easy to stop at if NCS says no to code changes.
- **The agent runs inside the platform.** Rejected. It would give the running app the power to change its own code, and put the code host's keys next to the production keys.
- **The review agent approves and merges small fixes by itself.** Rejected, for the reasons above.

## Consequences

- **A new external dependency.** The coding agent and its model need an agreement with NCS before anything is built. Without one, this ADR stays proposed.
- **The protected-paths list is a safety control.** Keep it in one place, the CI check, and review it whenever those parts of the code move.
- **The support case stages become real.** In the redesign prototype they are Planned, shown only with Planned features on. This ADR is what would make them real.
- **It suits the final presentation.** The coding agent's progress could show in the live activity view, like the other agents.
- **Nothing here changes the app's approval gate or safety checker.** Writes to Jira still wait for an Approver's yes.
