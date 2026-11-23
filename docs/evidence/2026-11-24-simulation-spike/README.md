# Simulation mode spike, 24 Nov 2026

The live spike for proposed ADR 0054 (Simulation mode), items S1 to S7 under "Before acceptance: a live spike". S1, S2, S3, S4, S5 and S7 ran on the team lead's laptop. S6 is reading of Azure's docs only. No cloud resource was changed, no `az` command was run, and no paid model was called.

**None of the results changes the recommended option (C).** Several change details in the ADR's sections 2 to 5. They are listed at the end and in the ADR's spike section.

| Item | Result | In short |
|---|---|---|
| S1 | Pass | A second n8n from our image boots with our blocks, bootstrap and guards, holds only mock keys, and reaches nothing outside its own network. `pack-smoke.sh` passes on its image. |
| S2 | Pass for the read systems, partial for notice-only ones | GitHub and Jira keys point at a mock by their own address field. Slack needs the DNS alias and CA. Teams, Outlook and Gmail would too, plus a mock sign-in service, but they were read in code only. |
| S3 | Pass | Our blocks work against a gateway stand-in: a start signed with the simulation's own secret, every call linked by the start's nonce, Ask for a yes answered no, and a refused write. |
| S4 | Pass | Pins on n8n's GitHub block and on our Read block hold in a run by hand from Start from the Portal, and the run stays linked. |
| S5 | Partial | A mock that drops the connection fails n8n's block in about 1 s, with a reason. A real timeout takes 300 s for each try, so a mock that holds plays it faithfully but far too slowly. |
| S6 | Not possible in full (docs only) | On Azure the simulation n8n can be kept off the internet and away from the platform, but not away from Azure-wide services. Isolation rests on holding no real key. |
| S7 | Pass | n8n's execution data names each block that ran, its status and which exit it took, so code can find coverage gaps. Two limits are noted below. |

## How it ran

Run it from the repo root on a laptop with Docker, `jq` and `uv`:

```sh
docs/evidence/2026-11-24-simulation-spike/run.sh <out-dir>
```

| File | What it is |
|---|---|
| `compose.yaml` | The compose project `simspike`: its own Postgres (in memory), the simulation n8n from `wab/n8n:dev` with the platform's n8n guards, n8n's task runner, platform-api's bootstrap from `wab/platform-api:dev`, mock GitHub, mock Slack (as `slack.com`), the gateway stand-in, and the driver. Both networks are `internal: true`, and nothing publishes a port. |
| `stub.py` | The gateway stand-in (port 8600) and an outside system that can answer, answer not found, hold or drop (port 8700). Python's standard library only. |
| `drive.py` | Runs every item from inside the network and writes `results.json`. |
| `run.sh` | Makes every key at run time with `openssl rand`, starts the stack, runs the driver, checks what n8n reaches, runs the pin check and `scripts/pack-smoke.sh`, then removes the stack. |
| `probe-credentials.mjs` | S2's code half: reads n8n's credential types and the hosts in each block's code, inside our image with no network. |
| `results.json` | What the driver saw. S1 to S4 come from the full run, and S5 from its rerun (see S5). S7 is worked out from both. It holds no key. |
| `driver.log`, `driver-s5.log`, `isolation.txt`, `pack-smoke.txt`, `bootstrap.log` | The other outputs of the full run and the S5 rerun. |
| `credential-types.json` | What `probe-credentials.mjs` printed. |

**The gateway stand-in.** For S3 the smallest stand-in was a stub (`stub.py`), not a platform-api with its own Postgres. It checks the simulation's node key, and links each call to its execution the way platform-api's `_link` does: it reads n8n's record of the execution through n8n's public API, and takes the nonce from Start from the Portal's item. It answers Read with scenario data, answers Agent with one recorded reply, wakes Ask for a yes with the scenario's decision signed with the node key, refuses every write with 403 "A simulation never writes.", and answers Tell with `would_have_sent`. The mock model was not needed and was not started.

**Images.** Only images already on the laptop: `wab/n8n:dev` (n8n 2.42.6 with our node pack, built 17 Nov; the pack has not changed since 16 Nov), `n8nio/runners:2.42.6`, `postgres:17` and `python:3.12-slim` at their pinned digests, `wab/platform-api:dev`, `wab/mock-github:dev` and `wab/mock-slack:dev`. Nothing was pulled or built.

**Keys.** Every key, password and secret was made at run time and lived only in the containers' environment. The GitHub and Jira keys were random strings. The Slack key was mock Slack's own published test token. `results.json` and the logs hold none of them.

## S1. A second n8n boots on its own network

**Pass.**

- Bootstrap, on the simulation's own Postgres, ended with `bootstrap: ready: all workflows loaded, active and linted` (`bootstrap.log`). That run includes its checks of n8n's blocks and guards, and it loaded and turned on the error workflow and the self-test.
- n8n served all 8 of our blocks among 846 types, and none of the blocks `NODES_EXCLUDE` leaves out.
- `platform_api.pin_check` on what the simulation n8n served: "each of the 56 types the class file names still matches the image".
- `scripts/pack-smoke.sh`, run on the same image with `PACK_SMOKE_IMAGE=wab/n8n:dev`, passed all 10 checks, the catalogue check included (`pack-smoke.txt`). The script boots its own container from an image, so it checks the image the simulation n8n runs, not the running container.
- The simulation n8n held 4 keys, all mock: GitHub and Slack pointed at the mocks, and two Jira keys pointed at the stand-in. Its environment has no `GITHUB_TOKEN`, Jira, Teams, Slack or model key. `WAB_API_URL` is `http://gateway:8600` (`isolation.txt`).
- From inside the simulation n8n, `wget` could not reach `api.github.com` ("bad address"), `platform-api` or `wab-platform-api-1`. It reached mock GitHub and the gateway. `slack.com` led to mock Slack.

## S2. Can each allowed system's key point at a mock?

**Pass for GitHub, Jira and Slack, tried live. Partial for Teams, Outlook and Gmail, read in code only.**

The live run (`results.json`, S2) made one key of n8n's own type for each system and ran one workflow by hand with no pins:

| System | n8n key type | Points at the mock by | Live result |
|---|---|---|---|
| GitHub (read) | `githubApi` | its `server` field | The block read releases 1.2.16, 1.2.15 and 1.2.14 from mock GitHub. |
| Jira Data Center (read) | `jiraSoftwareServerPatApi` | its `domain` field | The stand-in got `GET /rest/api/2/issue/MOCK-1` with a Bearer key. |
| Jira Cloud (read) | `jiraSoftwareCloudApi` | its `domain` field | The stand-in got the same request with Basic auth. |
| Slack (notice) | `slackApi` | no field: the DNS alias `slack.com` and the mock's CA in `NODE_EXTRA_CA_CERTS`, as in CI | Mock Slack recorded `chat.postMessage` to `C0SUPPORT`. |

`probe-credentials.mjs` read the rest in our image (`credential-types.json`):

- **Teams** (`channelMessage.create`) and **Outlook** (`message.send`) call `https://graph.microsoft.com`, which is fixed in the block's code. Their key, `microsoftOAuth2Api`, has no address field, and gets its token from Microsoft's sign-in service.
- **Gmail** (`message.send`) calls `https://www.googleapis.com`, fixed in code, with `gmailOAuth2Api` or `googleApi`, which gets its token from `https://oauth2.googleapis.com/token`.
- So each of the three would need a DNS alias, a CA and a mock sign-in service. All three are notice-only on the allow list, and a run by hand pins each notice block's output (ADR 0045, amendment 7). A simulation can leave them pinned and needs no mock for them, unless the team wants to play their failures.
- **Confluence:** n8n 2.42.6 has its own Confluence block (key `confluenceCloudOAuth2Api`, host `api.atlassian.com`), but `node_classes.json` has no row for it, so the allow list keeps it out. A workflow reads Confluence only through our Read block, which the simulation gateway answers. No Confluence key is needed in the simulation n8n.

## S3. Our blocks against a simulation gateway

**Pass**, with the stub described above (`results.json`, S3). The workflow was Start from the Portal, Read, Agent, Propose a change, Ask for a yes, then Make the approved changes and Tell on Yes, and an end block on each other exit.

| Run | What happened |
|---|---|
| a. Start signed with the simulation's own `WAB_START_SECRET`, the Approver says no | The trigger answered 200 and n8n ran it as `webhook`. All 4 calls (Read, Agent, Propose, Ask) were linked: n8n's record said `running`, and the nonce in the start item was the one sent. The stub woke Ask for a yes with a signed `no` at the first try. The run ended `success` at the No exit. Make the approved changes and Tell did not run. |
| b. The same start signed with another secret | The trigger answered 401 "The signature does not match." No execution started. |
| c. Run by hand, as a simulation runs, the Approver says yes | The write call got 403 "A simulation never writes." n8n tried it 3 times, as the block's retry settings say, and the run ended `error` with those words on Make the approved changes, after 5.1 s. Every call was linked by the nonce, in mode `manual`. |
| d. As c, from a signed start | The same refusal. The error workflow's Report a failure then reached the gateway, naming execution 7, mode `webhook`. Run c, by hand, sent no report: n8n runs the error workflow only for runs it did not start by hand. |
| e. Read answers "not found", "timeout" and "nothing new" | Not found (404) and timeout (504) each failed Read after 3 tries in 4.1 s, with the gateway's words. An empty answer gave Read 0 items, and n8n ran nothing after it: the run ended `success` at Read. |

One step the platform's own code also takes: right after it turns a workflow on, n8n answered 404 for the new start address until it read the workflow as published (0.5 s). The driver waited for that, as `wait_published` in `orchestration/n8n.py` does.

## S4. Pins in a run by hand

**Pass** (`results.json`, S4). The workflow put n8n's GitHub block (key pointed at the stand-in) before Read, with both blocks' output pinned, and ran by hand with `triggerToStartFrom`, as `run_draft` does.

- The GitHub stand-in got no request, and the gateway got no Read call. Both pins held.
- The first call came from Agent. It linked by the nonce (`running`, mode `manual`), and so did each call after it. The run ended at the No exit.
- The same workflow from a signed start ran as `webhook`, and n8n ignored both pins: the stand-in got `GET /repos/langchain-ai/langgraph/releases?per_page=3`, and the gateway got a Read call. So a simulation must run by hand, as the ADR says.

## S5. Can a timeout be played quickly?

**Partial** (`results.json`, S5, and `driver-s5.log`). n8n's GitHub and Jira blocks, keys pointed at the stand-in, retries set to 2 tries 1 s apart unless the row says otherwise:

| The stand-in | What n8n did |
|---|---|
| drops the connection after reading the request | Both blocks failed after 1.1 s with "The connection to the server was closed unexpectedly, perhaps it is offline. You can retry the request immediately or wait and retry later." The stand-in got requests at 0.1 s and 1.1 s, so the retry ran. |
| answers 404 | GitHub failed after 1.1 s with "The resource you are requesting could not be found", after 2 tries. |
| holds for 90 s | GitHub waited 90 s and then succeeded with the answer. |
| holds for 400 s, one try | GitHub gave up at 300.05 s with "The connection was aborted, perhaps the server is offline". So n8n's own request helper has a 300 s limit for each try. The block has no setting to change it. |
| holds for 120 s, with `executionTimeout: 10` in the workflow's settings | n8n ended the run at 10.0 s as `canceled`, with no error message. Its record shows Start from the Portal as the last block, and the GitHub block that was waiting is missing from it. |

The first full run held for 330 s with 2 tries. That run had not ended when the driver stopped waiting at 600 s, as two 300 s tries would explain. S5 was then run again on its own, with the rows above (`results.json` keeps both).

What this means:

- A real timeout of n8n's own GitHub block takes 300 s for each try, and then fails with "The connection was aborted". A mock that holds plays it faithfully, but only that slowly. With 3 tries that is 15 minutes, most of the 20 minutes ADR 0055 gives a whole fix.
- A mock that drops plays a dead source in about 1 s for each try, with a reason n8n shows on the block. Its words differ from a real timeout's ("closed unexpectedly", not "aborted"), but both name a connection that failed.
- A time limit on the copy in the simulation n8n also ends the run fast. Code then grades a `canceled` run, and names the held block from the mock's own record of the request it held, because n8n's record leaves it out.
- No real workflow has a time limit of its own today: neither `deploy/` nor `infra/` sets `EXECUTIONS_TIMEOUT`, and the layout sets no `executionTimeout`. So a hung source holds a real run for 300 s for each try.
- For our own blocks the gateway plays a timeout as an answer at once (S3, run e).

## S6. Can an Azure Container App reach only the mocks and the gateway?

**Not possible in full, from the docs. Nothing was tried on Azure.**

- Today's environment (`infra/modules/container_env/main.tf`) is a workload profiles environment on Azure's default network. Microsoft says: "After you create an environment with either the default Azure network or an existing virtual network, you can't change the network type." Outbound control needs an existing virtual network. So the simulation n8n needs a new environment on its own subnet ([Networking in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/networking)).
- A network security group on that subnet can deny the internet. It must still allow, for a workload profiles environment ([Securing a virtual network](https://learn.microsoft.com/en-us/azure/container-apps/firewall-integration)): `MicrosoftContainerRegistry` and `AzureFrontDoor.FirstParty` on 443 for system containers, all traffic inside the subnet, and Azure DNS. It must also allow our registry. Our registry is Azure Container Registry Basic, which can't have a private endpoint, so that means the `AzureContainerRegistry` and `Storage.<region>` service tags, and `AzureActiveDirectory` for the managed identity that pulls. Those tags cover every customer's registries and storage, not only ours.
- Apps in one environment share its subnet, and traffic inside the subnet must stay allowed. So the mocks and the gateway must run in the simulation's environment, and nothing of the platform's may.
- Only a route to Azure Firewall could narrow what it reaches to named hosts. That is a paid service, billed by the hour.
- So on Azure the simulation n8n can be kept off the internet and away from the platform's environment, but not away from Azure-wide services. As the ADR asks, isolation rests on holding no real key, and the network rules are a second layer.
- Where the gateway runs on Azure is still open. If it stays inside platform-api, the simulation's subnet must be allowed to reach the platform's public address, and the simulation's node key is the only guard on the real API. If it runs as its own app in the simulation's environment, the platform reads its results from there. PR 2 and PR 3 choose.

## S7. Can code find coverage gaps from n8n's execution data?

**Pass, with two limits** (`results.json`, S7, and each run's `ran` and `not_ran`).

- `GET /api/v1/executions/{id}?includeData=true` lists each block that ran under `resultData.runData`, with its status, its error words, and how many items left by each exit. Ask for a yes showed `[0, 0, 1, 0]` when the Approver said no (exits: No answer, Yes, No, Nothing to change) and `[0, 1, 0, 0]` for yes. A block that is not there did not run.
- Over the S3 scenarios, code would name "No answer", "Nothing to change" and Tell as blocks no scenario reached.
- **Limit 1, a block after a write never runs.** The refused write ends the run, so Tell can never run in a simulation. Code must report such blocks as not tried for that reason. Or the gateway could answer a write with "would have made", as Tell answers "would have sent". This is a choice for PR 3.
- **Limit 2, pins look like runs.** Pinned blocks show in `runData` as if they ran, and the record's `resultData.pinData` was empty. So code keeps its own list of the blocks it pinned. Also, as S5 shows, a run that its time limit cut short leaves out the block that was running.

## What the results change in ADR 0054

None changes option C. They are in the ADR's spike section for the team lead.

1. **Section 4, mocks.** Confluence needs no mock key: n8n's Confluence block is not on the allow list, so the gateway answers Confluence reads. Teams, Outlook and Gmail need no mock while they are notice-only, because a run by hand pins them.
2. **Sections 4 and 5, timeout.** A faithful timeout of n8n's own block takes 300 s for each try, too slow for a simulation. Play it with a mock that drops (about 1 s for each try, with a reason), or with a time limit on the copy and a mock that holds, graded as a `canceled` run and naming the held block from the mock's record.
3. **Section 5, failures.** n8n runs no error workflow for a run by hand, so code reads every simulated failure from n8n's execution data, never from Report a failure.
4. **Sections 5 and 7, coverage.** Blocks after a refused write never run, and pinned blocks look as if they ran. Code keeps its own list of pins, and either reports blocks after a write as not tried, or the gateway answers writes as "would have made".
5. **Section 2, Azure.** The simulation n8n needs its own environment and subnet. Isolation rests on holding no real key, with the network rules as a second layer.

One question outside this ADR: no real workflow has a time limit of its own, so a hung source holds a real run for 300 s for each try of the block. Whether real workflows should get a shorter one is for the team lead.

ADR 0055 needs no change. Its 20 minutes for a fix holds as long as a simulation plays timeouts fast, as point 2 says.

## Clean-up

`run.sh` ends with `docker compose -p simspike down --volumes --remove-orphans`, then lists anything left with the simspike label or the pack-smoke name. Both runs left nothing. Afterwards `docker system df` showed the same 107 images, 45 containers and 28 volumes as before the spike, and no container, network, volume or image named simspike or pack-smoke. The spike touched nothing named `wab*`, and the wab stack kept running throughout.
