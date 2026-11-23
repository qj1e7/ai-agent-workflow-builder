---
status: proposed
---

# Simulation mode tries each workflow on mock systems in a separate n8n, before the real test run

On 23 and 24 Nov 2026 the team lead asked for Simulation mode as an upgrade to the Check step (ADR 0053), with 2 to 4 options and this ADR before any code. The proposal: before a workflow version is turned on, it runs through a few short scenarios against mock systems, in a separate n8n that holds no real key. The AI writes the scenarios and explains the results. Code builds the mock setup, runs the scenarios and decides pass or fail. One real test run, which writes nothing, stays the final check.

It builds on ADR 0044 (the test run), ADR 0045 (the node allow list and pinned output), ADR 0051 (the drafter and the digest) and ADR 0053 (Describe, Check, Turn on). It adds a new service, so `AGENTS.md` asks for this ADR. It doesn't change the approval gate, the safety checker, the test run or the digest. ADR 0055 ("Fix it for me") uses it to prove a fix.

Sentences in quotes marked "(needs OK)" are proposed words for people to see. They need the team lead's OK.

## Words used here

These terms are new. They go in `GLOSSARY.md` once this ADR is accepted.

- **Simulation.** Runs of a copy of one workflow version in the simulation n8n, one run for each scenario. Nothing in a simulation can reach a real system. A simulation is not a run: it isn't in Recent runs, and it never counts as a test run.
- **Simulation n8n.** A second n8n, on the same pinned image and node pack as the platform's n8n. It has only mock keys, and it reaches only the mock systems and the simulation gateway.
- **Scenario.** One situation a workflow should handle, written as data: what each mock system answers, and what the Approver says. There are six kinds: happy path, nothing new, source not found, timeout, Approver says no, and odd data.
- **Mock setup.** The mock keys, mock systems and pinned output that code builds for one version from the node allow list.
- **Recorded sample.** A real answer from a system, scrubbed of personal data, that a scenario replays or varies.
- **Coverage gap.** A block or branch that no scenario reached, or a scenario kind that applies to the workflow but has no scenario. Code finds it.

## Context

**What the Check step proves today.** In Check the person reviews the card. Turn on then runs a test run and turns the workflow on if it passes (ADR 0053). The test run runs n8n's draft of the workflow by hand, through `POST /rest/workflows/{id}/run` from Start from the Portal (`run_draft` in `orchestration/n8n.py`, and `orchestration/n8n_starts.py`). It doesn't start if the draft changed or a notice block has no pinned output. It reads real data and stops at the approval gate (`stops_at_gate` in `orchestration/service.py` answers `test_passed`). It posts nothing and writes nothing. So it proves the happy path on today's data. It can't show what the workflow does when nothing is new, the source is gone, a system is slow, the data is odd, or the Approver says no. Those are the cases that stop runs on day 100.

**What n8n gives us.** n8n 2.42.6 uses pinned output (`pinData`) only in a run by hand or in evaluation mode (`resolvePinData` in `workflow-runner.ts`, and `webhook-helpers.ts`). n8n's docs say pins are not for production runs. Pins already keep a test run from posting (ADR 0045, amendment 7, and ADR 0051, section 4), and they work live in test runs (`e2e/tests/test_n8n_keys.py`). Pins are part of the approval digest (`orchestration/version_digest.py`), so a pin added for a scenario would change the version an Approver sees. A pin replaces a block's output. It can't make the block fail or time out.

**What mocks we have.** `deploy/compose.e2e.yaml` runs mock GitHub (port 8200), mock Confluence (8400), the mock model (8300) and mock Slack (8500). Mock Slack sits under the DNS alias `slack.com` with its own CA, because n8n's Slack block always calls `https://slack.com`. `scripts/e2e.sh` and CI start them. platform-api has the practice Jira when `JIRA_BASE_URL` is unset (ADR 0035), a Teams stub (`orchestration/teams.py`) and mock sign-in. The agent runtime has recorded model replies (`agent-runtime/evals/cases/recorded_replies.json`). n8n reaches a mock through a credential's address, as `wab-github-read` does. The runtime reaches one through its env addresses.

**What we don't have.** There is no test n8n and no test project. The platform keeps its workflows in the n8n owner's own project (`platform_project` in `orchestration/n8n.py`). On n8n's free edition a credential can't be shared across projects, each member has one personal space, and a workflow in the owner's project can use every key there is (ADR 0045, amendment 6). Our blocks call only one address, `WAB_API_URL`, with `WAB_NODE_KEY` (`n8n-node-pack/README.md`). Both are set on the container, so one n8n has one of each. HTTP Request and Code reach whatever n8n can reach (ADR 0051).

## Decision

We recommend option C: a separate simulation n8n with only mock keys. Each part says whether code or the AI does it.

1. **Simulation runs in Check, before the real test run.** Once the safety checker has graded a version, code runs it through its scenarios in the simulation n8n, in the background. The Check card shows the results first, for example "Tried 6 cases on practice systems: 5 passed." (needs OK). Turn on then runs the one real test run, which writes nothing, as today (ADR 0053). A passed simulation never turns anything on and never stands in for that test run. A failed scenario doesn't block Turn on: the card leads with what failed and why, and the person decides, because a mock can be wrong and the real test run is the check. The team lead may prefer that a failed scenario blocks Turn on until the person accepts it.

2. **The simulation n8n (code).** It runs the same pinned image, node pack, node allow list and bootstrap as the platform's n8n, with its own database and encryption key. Code makes only mock credentials there. It holds no real key and no write key. Its network reaches only the mock systems and the simulation gateway. On a laptop and in CI that is a compose network with aliases, as mock Slack has today. On Azure it is its own Container App with no route out (spike item S6). Its `WAB_API_URL` points at the simulation gateway, with its own `WAB_NODE_KEY` and `WAB_START_SECRET`.

3. **The simulation gateway (code).** A small part of orchestration, with its own routes and tables, kept apart from runs. It answers our blocks in the simulation n8n as the real API does, with five differences. It records simulated runs apart, so none shows in Recent runs or in the activity log as a run. Our Read block gets the scenario's data, since our blocks call only `WAB_API_URL`. Our Agent block runs on the mock model or recorded replies, never on a paid model, so a simulation tests the workflow around the agent, not the agent's own judgement. Ask for a yes gets the scenario's answer, yes or no, and asks nobody. Every write is refused, as the write gateway refuses a test run's write, and Tell sends nothing. It holds no Jira, Teams or Slack key.

4. **Code builds the mock setup from the node allow list.** For each of n8n's own blocks in the version, its row in `node_classes.json` gives its system and its class (read, notice or write). For a system with a mock (GitHub, Confluence, Jira through the practice Jira, and Slack), code makes a mock credential of the block's own type that points at that mock. For a block whose system has no mock, and for HTTP Request and Code, code pins the block's output from the scenario's data. The simulation runs by hand, so the pins apply. Such a block can't play "source not found" or "timeout", so those pairs show as "Not tried" (needs OK), never as passed. A block the class file doesn't class is not simulated, and the card says so. The model never builds or changes the mock setup.

5. **The AI writes scenarios, and code checks and grades them.**
   - **Which kinds apply (code).** Code picks the kinds that fit the version. A version with no Ask for a yes gets no "Approver says no". A version with no outside read gets no "source not found" or "timeout".
   - **The scenarios (AI).** The scenario writer, a model in the agent runtime, writes one scenario for each kind that applies. A scenario is data in a schema that code owns: for each mocked system, which recorded sample it serves and how (as recorded, varied, empty, not found, or too slow), and the Approver's answer. The writer picks and varies recorded samples, for example a version string with a suffix, an empty field, or very long text. It can't add a block, a system or a key. Code refuses a scenario that names one the version doesn't have.
   - **Pass or fail (code).** Code holds the expected outcome for each kind. The happy path reaches the yes with the expected change. Nothing new ends as Nothing new and proposes nothing. Source not found and timeout stop with a reason the troubleshooter can name, and never write. Approver says no ends as Declined with nothing written. Odd data ends in one of those, never in a failure with no reason. Code reads each simulated run's events and n8n's execution data, and decides pass or fail.
   - **The explanation (AI).** The model explains each failure in one plain sentence. Its words help the reader. They are never the verdict.
   - **Without a model.** Code's own six scenarios, built from templates, still run, with the recorded samples as they are.

6. **Recorded samples are scrubbed first (code).** A sample comes from a mock's own fixtures, or from what a read block returned in a real run of the same workflow (n8n's execution data). Before code stores one, it keeps only the fields on an allow list for that system's answer, such as `tag_name`, `name`, `published_at`, `html_url`, `prerelease` and `draft` for a GitHub release. It replaces every other text field with a fixed fake value. Names, emails, user and account ids, avatars, and text that people wrote are never kept. Key shapes are masked, as traces are (`monitoring/masking.py`). Until the DevNet move, samples come only from open-internet sources and the practice Jira, never from NCS data (ADR 0050). It is an allow list, not a deny list, because deny lists leaked in four review rounds on 18 Nov.

7. **Refining a new workflow's Check.** For a drafted workflow (ADR 0051), the coordinator in ADR 0055 runs the same loop it runs for a fix.
   - The drafter drafts, code checks it, the simulation runs, and code reads which scenarios failed and why.
   - The coordinator sends one targeted follow-up. Either the drafter refines the same draft with that evidence ("change only block X"), or the scenario writer adds a scenario for a coverage gap that code found. Code finds gaps from n8n's execution data (which blocks ran in each scenario) and from the kinds that apply.
   - The loop has ADR 0055's step limit, cost cap and timeout, and each round counts toward them. It stops early when a round makes no progress or widens the change.
   - Every round goes in the activity log and the live activity view. The activity log keys events by run today, and a Check has no run, so its rounds need a stream keyed by the drafted workflow (PR 8 settles its shape).
   - When all scenarios pass, the person sees the final draft with the rounds tried, and Turn on runs the one real test run.
   - A workflow the Planner builds from our own blocks is simulated too, but not refined. Its layout is our tested code, so a failure there is a bug for the team, reported to support.

8. **What stays the same.** The real test run, its pins and its refusal rules (ADR 0044, and ADR 0045, amendment 7). The safety checker and its grade. The digest: the simulation runs a copy in the simulation n8n, so a scenario's pins never touch the version an Approver approves. The approval gate. Nothing in a simulation is ever a write to a real system.

## Considered options

- **A. Pinned data on the test run's manual path, in the platform's n8n.** Code copies the version, pins each outside block's output with scenario data, and runs the copy by hand through the test run's path (`run_draft` with `triggerToStartFrom`). For: no new service. The test-run path, pins and `stops_at_gate` exist and work live. Against: a pin can't fail or time out, so "source not found" and "timeout" can't be played. The test run stops at the gate, so "Approver says no" needs a second path through the real gate. The copy sits in the owner's project, where a workflow can use every key there is, and every sweep (versions, keys, holds) would see it. Pins are in the digest, so they can't go on the version itself. Unknown: whether a pin on one of our blocks keeps the run linked (Record the run's nonce), whether pins work with `triggerToStartFrom`, and what evaluation mode adds. Kept inside C, for blocks with no mock.
- **B. A separate n8n project in the same instance, with mock credentials.** On the free edition that is the personal space of a simulation account, as staff spaces are. For: no new container. Against: one container has one `WAB_API_URL` and one node key, so our blocks there would call the real API, and Ask for a yes would reach the real gate. n8n's own blocks with a fixed host, such as Slack, can be pointed at a mock only by a DNS alias, which would catch the live workflows too. HTTP Request and Code reach whatever the real n8n reaches. The credential sweep, holds and staff guards would each need an exception for that space. One mistake puts a scenario next to real keys.
- **C. A separate n8n instance with no real keys and only mock credentials (recommended).** For: nothing in it can reach a real system or the real gate, even when a scenario or a fix is wrong. It can play all six kinds, since a mock can answer "not found" or answer slowly, and the gateway can say no. It reuses the e2e mocks and the Slack alias that CI already proves. It runs the same image, so a pass says something about the real n8n. Against: one more container and database to run, deploy and keep on the same pin, a mock to build for each new system, and the gateway is new code.
- **D. Our own interpreter that plays the workflow without n8n.** For: fast, needs no n8n, and we control it fully. Against: we would rebuild n8n's expression language, item pairing, error settings and each block's behaviour, and it would drift from the pinned image. It would prove our model of n8n, not n8n. Rejected.

## Consequences

- **Running cost.** One more n8n container and its database, with the mocks deployed beside it (today they run only in CI and on laptops). Deploying it changes cloud resources, so it waits for the team lead.
- **Model cost.** Writing scenarios and explaining failures are paid calls. A guess before any measurement: about 3 cents to write a version's scenarios and 1 cent for each failure explained, on Claude Sonnet 5.5 at ADR 0051's prices. In a fix they count toward ADR 0055's cap.
- **Upkeep.** Each new system a workflow can reach needs a mock. Until it has one, its blocks get pinned output only, and its "not found" and "timeout" show as not tried. Both n8n instances move together when the pin moves. `scripts/pack-smoke.sh` and `pin_check` already run against the one image they share.
- **DevNet.** The simulation n8n needs no outside network, so it moves easily.
- **ADR 0055** depends on this ADR, its spike, and PRs 2 to 5.

### Before acceptance: a live spike

These are unknown on `origin/main` and need a live spike, with no paid model calls:

- **S1.** A second n8n from our image boots with our node pack and bootstrap, with only mock credentials, on its own compose network, and `scripts/pack-smoke.sh` passes against it.
- **S2.** For each system on the allow list today, a credential of n8n's own type can point at our mock (GitHub's server address, Jira's and Confluence's domains), or it needs a DNS alias and CA, as Slack does.
- **S3.** Our blocks work against a simulation gateway: Start from the Portal with its own start secret, Record the run's link, Ask for a yes answered no, and a refused write.
- **S4.** Pins work in a run by hand with `triggerToStartFrom` in the simulation n8n, on a read block and on one of our blocks, and the run stays linked.
- **S5.** A timeout can be played quickly. Find whether a mock that holds or drops the connection makes n8n's block fail as a real timeout does, within the block's own timeout and retries.
- **S6.** On Azure, a Container App can be kept from reaching anything but the mocks and the gateway. If it can't, isolation rests on holding no real key, and this ADR says so.
- **S7.** n8n's execution data shows which blocks ran in each scenario, so code can find coverage gaps.

#### Spike results, 24 Nov 2026

The spike ran S1 to S5 and S7 on a laptop, with no paid model call, and S6 from Azure's docs, with no cloud change. Its compose file, scripts and results are in `docs/evidence/2026-11-24-simulation-spike/`. The simulation gateway was a small stub (`stub.py`), not platform-api. **No result changes the recommended option, C.** Some change details below, for the team lead to take into the sections they name before acceptance.

| Item | Result | What we saw |
|---|---|---|
| S1 | Pass | A second n8n from `wab/n8n:dev` ran on its own internal network, with its own Postgres, keys and secrets. Bootstrap ended "ready: all workflows loaded, active and linted". `scripts/pack-smoke.sh` passed on the same image, and the pin check passed on what it served. It held only mock keys, and could not reach the internet or the platform's stack. |
| S2 | Pass for read systems, partial for notice-only ones | GitHub (`server`) and both Jira keys (`domain`) point at a mock by their own field, tried live. Slack needs the DNS alias and CA, tried live. Teams, Outlook and Gmail have fixed hosts and OAuth keys, so they would need an alias, a CA and a mock sign-in service. They were read in code only. |
| S3 | Pass | Start from the Portal took a start signed with the simulation's own secret and refused one signed with another (401). Every call linked by the start's nonce. Ask for a yes, woken with a signed no, left by its No exit. The write got 403 "A simulation never writes." and the run ended with those words. |
| S4 | Pass | In a run by hand with `triggerToStartFrom`, pins held on n8n's GitHub block and on our Read block: neither the GitHub stand-in nor the gateway got a call. The first call, from Agent, linked by the nonce. From a signed start, n8n ignored both pins. |
| S5 | Partial | A mock that drops the connection fails n8n's GitHub or Jira block in about 1 s for each try, with a reason. A real timeout takes 300 s for each try: against a mock that held, the GitHub block gave up at 300 s with "The connection was aborted", and it has no setting to shorten that. With `executionTimeout: 10` on the workflow, n8n ended the run at 10 s as `canceled`, with no error, and its record left out the block that was waiting. |
| S6 | Not possible in full | Today's environment is on Azure's default network, which can't change, so the simulation n8n needs a new environment on its own subnet. A network security group can keep it off the internet and away from the platform's environment, but must allow Azure-wide service tags for system images, our registry (Basic, no private endpoint) and storage. So isolation rests on holding no real key, with the network rules as a second layer. Only Azure Firewall, a paid service, could narrow it to named hosts. |
| S7 | Pass, with limits | `runData` names each block that ran, its status, its error words and the items on each exit, so code finds blocks no scenario reached. Pinned blocks look as if they ran, and a run cut by its time limit leaves out the waiting block. |

What the results change in this ADR:

1. **Section 4.** Confluence needs no mock key: n8n's own Confluence block is not on the allow list, so a Confluence read comes only through our Read block, which the gateway answers. Teams, Outlook and Gmail need no mock while they are notice-only, because a run by hand pins every notice block.
2. **Sections 4 and 5, "source not found" and "timeout".** A faithful timeout of n8n's own block takes 300 s for each try, which would use up most of ADR 0055's 20 minutes. So a mock plays a timeout by dropping the connection, or by holding while the simulation's copy carries a short time limit. In the second case code grades a `canceled` run, and names the held block from the mock's own record. For our blocks, the gateway answers "not found" or "timed out" at once.
3. **Section 5, grading.** n8n runs the error workflow only for runs it did not start by hand. A simulation runs by hand, so code reads every failure from n8n's execution data, never from Report a failure.
4. **Sections 5 and 7, coverage gaps.** The refused write ends the run, so a block after Make the approved changes, such as Tell, never runs in a simulation. Code reports it as not tried for that reason, or the gateway answers a write with "would have made", as Tell answers "would have sent" (PR 3 chooses). Code also keeps its own list of the blocks it pinned.
5. **Section 2, Azure.** The simulation n8n, the mocks and the gateway's address need their own Container Apps environment and subnet. Isolation rests on holding no real key. PR 2 and PR 3 choose whether the gateway runs in that environment or stays in platform-api, where the simulation's node key would be the only guard on the real API.

Outside this ADR: no real workflow has a time limit of its own (no `EXECUTIONS_TIMEOUT` and no `executionTimeout`), so a hung source holds a real run for 300 s for each try of the block. Whether real workflows get a shorter one is for the team lead.

### Pull requests, in order

1. The spike, with its results in `docs/evidence/` and an amendment to this ADR (`orchestration`).
2. The simulation n8n and the mocks in compose and CI, bootstrapped, with a test that it holds no real key. The Terraform for Azure goes in the same PR and is applied only after the team lead's OK (`infra`).
3. The simulation gateway (`orchestration`).
4. The mock setup from `node_classes.json`, with pins for blocks that have no mock (`orchestration`).
5. Scenarios: the schema, code's expected outcomes and grader, the six templates, and the recorded-sample store with its allow lists (`orchestration`, `runtime`).
6. The scenario writer and the explainer, with evals on recorded replies (`runtime`).
7. The Check card shows the results, with the words OK'd and the AI-native principles walked (`builder`, Portal).
8. Refinement for a drafted workflow's Check, after ADR 0055's coordinator lands (`runtime`, `monitoring`).
