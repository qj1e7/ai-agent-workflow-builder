# Deploy the rebuilt app to Azure (P14)

This is the operator's runbook for P14 of [the rebuild plan](../../design/rebuild-plan.md). The operator is the team lead. Every step here changes cloud resources, signs in to Azure or deploys, so a person does it. The pull request that added this file wrote the code only. Nothing was deployed, planned against Azure or signed in to Azure.

Do the steps in order. [infra/README.md](../../../infra/README.md) explains the infrastructure and the one-time setup. This file adds what the rebuilt app needs.

## 0. Do the one-time setup first

As of 31 Oct 2026 the repository has no `azure-dev` environment and no deploy identity. If that is still true, do `infra/README.md` steps 1 to 7 first, in that order, before anything below. The order matters: the environment and its branch rule must exist before the deploy identity trusts it, or a workflow on any branch could get the deploy token.

## 1. Decide how the deploy reaches the code

Once the setup is done, the `deploy` workflow runs only on `main`, because the `azure-dev` environment accepts only `main`. The plan says the operator lands P14 after the deploy. Both can't be true as things stand, so pick one:

- **A. Land first, then deploy (recommended).** Land P4, then P14, on `main`. Run the deploy on `main`, then the live lanes. If a lane fails, fix it in a new pull request. This keeps the gate as it is: only reviewed code on `main` can deploy.
- **B. Deploy the branch, then land.** Add `rebuild/p14-deploy` to `azure-dev`'s allowed branches, run the deploy on that branch, then remove the branch again at once. This follows the plan's order. While the branch is allowed, anyone who can push to it can deploy unreviewed code with the deploy identity, so do it only for this one run.

## 2. Before the deploy

1. **Check the allowed regions.** Azure for Students subscriptions often allow only a few regions. In the Azure portal, open **Policy**, then **Assignments**, and find "Allowed resource deployment regions". Or run:

   ```sh
   az policy assignment list --query "[?contains(displayName, 'region')].{name:displayName, regions:parameters.listOfAllowedLocations.value}" --output json
   ```

   If `southeastasia` is not on the list, set the environment variable `AZURE_LOCATION` to an allowed region. If only Cosmos DB is refused there, set `COSMOS_LOCATION` instead. Set `AZURE_LOCATION` before the first deploy only: changing it later replaces every resource, PostgreSQL and its data included.
2. **Check that no other free-tier Cosmos DB account exists.** A subscription may have one. ADR 0031 asked the team to make one by hand as a test, so look for it:

   ```sh
   az cosmosdb list --query "[].{name:name, group:resourceGroup, freeTier:enableFreeTier}" --output table
   ```

   If any row has `freeTier` set to `True`, delete that account and wait until the delete finishes. Deleting is yours to decide. If you would rather keep it, set `COSMOS_SERVERLESS=true`, which has no free tier and costs cents at our volume, and record the choice in ADR 0031.
3. **Register Cosmos DB's provider.** The deploy identity can't do it. Run it once:

   ```sh
   az provider register --namespace Microsoft.DocumentDB --wait
   ```

   `infra/bootstrap/setup-azure.sh` now does it too, if you run it again.
4. **Have three test accounts.** In the Entra tenant from [docs/auth/entra-setup.md](../../auth/entra-setup.md), use test accounts, never real people:
   - an **Operator**, who is also the first Approver,
   - a second **Approver**,
   - an **outsider**, who is not on the People list.

   Assign all three to platform-api's enterprise application, so each one can get a token. The outsider gets a token but no place on the People list, which is what lane 9 checks.
5. **Set the `azure-dev` environment's secrets and variables.** On top of [the infra README's list](../../../infra/README.md#steps). The repository is public, so the test accounts' emails go under Secrets, where GitHub masks them in the logs:

   | Secret | Value |
   |---|---|
   | `FIRST_OPERATOR` | the Operator test account's email |
   | `FIRST_APPROVERS` | the Operator's and the Approver's emails, separated by a comma |

   | Variable | Value |
   |---|---|
   | `PRACTICE_JIRA_URL` | leave unset. agent-runtime then reads platform-api's own practice Jira |
   | `AZURE_LOCATION`, `COSMOS_LOCATION`, `COSMOS_SERVERLESS` | only if step 1 or 2 asked for them |

   For example `gh secret set FIRST_APPROVERS --env azure-dev` (it asks for the value). The secret `GH_RELEASE_TOKEN` is optional, but set it for the lanes: each lane's check reads GitHub, and without a token Azure's shared address can run out of GitHub's 60 requests an hour.

   Terraform refuses these values before it changes anything if they would stop platform-api: an Operator with no Approvers, one Approver, the same Approver twice, or an address that is not an email. The addresses are not secret, but Terraform keeps them out of its error output, so they stay out of the deploy log.

## 3. Run the deploy

1. In the Actions tab, run the `deploy` workflow on `main`, or on `rebuild/p14-deploy` if you chose B. Leave `allow_destroy` off.
2. The step "Create the database roles" now also creates the Cosmos DB account, because the job's secrets live in Key Vault and Key Vault holds the account's key. A new account takes about 5 to 10 minutes. That is an estimate.
3. On a first deploy the plan only adds. If the deploy stops because the plan would destroy or replace something, read the counts in the run summary before you run it again with `allow_destroy`.
4. The run summary prints the Portal's address, platform-api's address and the Cosmos DB account's name. Keep all three for the lanes.
5. Add the Portal's two redirect URIs to its app registration, as step 9 of the infra README says. Sign-in works from then on.

## 4. Sign in once per test account

The lanes reuse each test account's sign-in, so nobody types a password during a lane. Set up Playwright on your machine once:

```sh
cd portal && npm ci && npx playwright install chromium && cd ..
export AZURE_PORTAL_URL=https://portal.<domain>   # the address the deploy printed
scripts/checks/p14.sh signin operator
scripts/checks/p14.sh signin approver
scripts/checks/p14.sh signin outsider
```

Each `signin` opens a browser at the Portal. Sign in with that test account, and answer **Yes** to "Stay signed in?". The window closes by itself once the Portal shows a page. The script saves the browser's state in `~/.wab-p14/<who>.json`, readable by you only, and refuses a folder inside the repository.

These files hold Entra ID's sign-in cookies. Never commit them, never copy them into this folder, and delete them with `scripts/checks/p14.sh forget` when the lanes are done. A checker agent gets the folder's path, never the files' contents. If a lane later says the saved sign-in no longer works, run that `signin` again.

## 5. Run the lanes

The lanes are the ten in the plan's P14 section, plus the perf probe. `scripts/checks/p14.sh` runs each one. It reads the addresses from settings, holds no secret, and writes its evidence under `EVID`, which is `/tmp/swarm-p14` unless you set it.

Lane 1 and the perf probe compare Azure with the local stack at head, so start that first, from a worktree at the PR's head:

```sh
export EVID=/tmp/swarm-p14; mkdir -p $EVID/env && cp deploy/make-env.sh $EVID/env/ && $EVID/env/make-env.sh
scripts/checks/p14.sh up "$PWD"    # needs about 3 GB free on the Docker disk; check with df -h first
```

Then run the lanes in this order. `scripts/checks/p14.sh all` runs every lane that needs nobody at the keyboard, in this order, then the perf probe.

| Lane | Command | Who must be there | Evidence in `EVID` |
|---|---|---|---|
| 3 | `p14.sh lane 3` | nobody | `lane-3/p14-ready.json` |
| 7 | `p14.sh lane 7` | nobody | `lane-7/p14-https.txt` |
| 2 | `p14.sh lane 2` | nobody | `lane-2/p14-sign-in.png`, `p14-sign-in-settings.png`, `p14-sign-in.json` |
| 9 | `p14.sh lane 9` | nobody | `lane-9/p14-not-on-list.png`, `p14-not-on-list.json` |
| 1 | `p14.sh lane 1` | nobody | `lane-1/p14-local-azure.png`, `p14-lane1.json`, `trunk.txt` |
| 4 | `p14.sh lane 4` | nobody | `lane-4/p14-approved.png`, `run.json` |
| 5 | `p14.sh lane 5` | your `az login`, with the role below | `lane-5/p14-cosmos.json`, `api-events.json` |
| 10 | `p14.sh lane 10` | nobody. Needs about 3 GB free on the Docker disk for ZAP | `lane-10/p14-zap.txt`, `p14-zap.json`, `p14-zap.html` |
| 8 | `p14.sh lane 8` | you, to say yes to the restart | `lane-8/p14-restart.png`, `p14-restart.json` |
| 6 | `p14.sh lane 6` | you, to type the gateway key | `lane-6/p14-model.png`, `p14-model.json` |
| perf | `p14.sh perf` | nobody | `perf/p14-perf.json` |

Each lane prints PASS or FAIL with its reason, and adds the line to `EVID/summary.txt`.

Notes on the lanes:

- **Lane 1** records that trunk was never deployed with these modules, so the local stack at head stands in for it. It runs the same watchlist check on both and compares the steps up to the approval gate.
- **Lanes 1, 4, 8 and perf** each add one software of their own to the watchlist (FastAPI, Pydantic, HTTPX, Requests) at an old version, so each check stops at the approval gate. A rerun replaces that row. Lane 1 and perf leave their checks waiting at the gate. Decline them afterwards if you want a tidy list.
- **Lane 5** reads the Cosmos DB items with your own sign-in, so you need Cosmos DB's Data Reader role on the `activity` database. Give it to yourself once, and take it away after the lanes:

  ```sh
  az cosmosdb sql role assignment create --account-name <account> --resource-group rg-wab-dev \
    --role-definition-id 00000000-0000-0000-0000-000000000001 --scope /dbs/activity \
    --principal-id "$(az ad signed-in-user show --query id --output tsv)"
  # after the lanes: az cosmosdb sql role assignment list --account-name <account> --resource-group rg-wab-dev,
  # then az cosmosdb sql role assignment delete --account-name <account> --resource-group rg-wab-dev --role-assignment-id <id>
  ```

  The script asks `az` for a token for that one request and hands it to `curl` on standard input. It never writes the token down.
- **Lane 6** opens Settings in a browser window. Pick AI Singapore gateway, paste the gateway key, press Connect, choose Claude Haiku 5.5, then press Test and save. The key goes from your keyboard to the page only. The lane passes when Test and save succeeds, which shows `SETTINGS_ENCRYPTION_KEY` is set.
- **Lane 8** asks before it restarts the platform-api container app with `az containerapp revision restart`. Set `P14_RESTART_OK=yes` to skip the question.
- **Perf** loads Home five times on each side, interleaved, after one load to sign in and warm up. Then it streams one check on each side and reads each event's delay as `scripts/p95.py --stream` does: when the event arrived on the run page's stream, minus its `ts`. Only events made after the stream opened count. The local stack is the baseline, because trunk was never deployed. The rule is the plan's: on Azure, Home's median paint is under 3 s and the 95th percentile event delay is under 2 s.

## 6. Save the evidence here

Copy these files from `EVID` into this folder, after you look at each screenshot. The screenshots show the test accounts' names, which is why the lanes use test accounts.

| From `EVID` | To `docs/evidence/deploy/` |
|---|---|
| `lane-1/p14-local-azure.png`, `lane-1/p14-lane1.json` | `p14-local-azure.png`, `p14-lane1.json` |
| `lane-2/p14-sign-in.png`, `lane-2/p14-sign-in-settings.png` | the same names |
| `lane-3/p14-ready.json` | `p14-ready.json` |
| `lane-4/p14-approved.png` | `p14-approved.png` |
| `lane-5/p14-cosmos.json` | `p14-cosmos.json` |
| `lane-6/p14-model.png` | `p14-model.png` |
| `lane-7/p14-https.txt` | `p14-https.txt` |
| `lane-8/p14-restart.png` | `p14-restart.png` |
| `lane-9/p14-not-on-list.png` | `p14-not-on-list.png` |
| `lane-10/p14-zap.txt` | `p14-zap.txt` |
| `perf/p14-perf.json` | `p14-perf.json` |
| `summary.txt` | `p14-summary.txt` |

Never copy anything from `~/.wab-p14`. The `.json` files not in this table, such as `lane-2/p14-sign-in.json` and `lane-4/run.json`, hold the test accounts' addresses and names. Leave them in `EVID`.

## 7. After the lanes

- Delete the saved sign-ins: `scripts/checks/p14.sh forget`.
- Take away your Cosmos DB Data Reader role, as lane 5's note says.
- Stop the local stack: `scripts/checks/p14.sh down "$PWD"`.
- If you chose B in step 1, check that `rebuild/p14-deploy` is no longer on `azure-dev`'s allowed branches.
- Between demos, take the environment down to save credits, as the infra README's cost section says.

## What the pull request checked without Azure

| # | Check | Result | Output |
|---|---|---|---|
| 1 | `terraform fmt -check -recursive` with Terraform 1.16.5, on this machine | Clean | `terraform-fmt-local.txt` |
| 2 | `terraform init -backend=false` and `terraform validate` on `envs/dev`, on this machine | "Success! The configuration is valid." | `terraform-validate-local.txt` |
| 3 | `infra/scripts/check-variables.sh` on this machine | All 37 cases as expected: 6 accepted, 31 refused, each by the right variable's rule | `terraform-variables-local.txt` |
| 4 | `terraform test` with mocked providers, on a scratch copy of `infra/` with two test files | 4 of 4 runs pass: platform-api's and agent-runtime's new settings, the Key Vault references, the first people only when set, the free tier and the serverless switch | `terraform-wiring-test.txt` |
| 5 | `infra/scripts/check.sh infra-checks` in the `infra` CI workflow: fmt, Terraform and OpenTofu validate, the variable cases, tflint and Checkov | All pass. tflint 0 issues. Checkov passed 7, failed 0, skipped 19 | `infra-checks/` |
| 6 | The Portal's `npm run typecheck` and `npm run lint`, which cover `e2e/checks/p14.check.ts`, on this machine and in CI | Both pass | the PR's `portal` CI job |
| 7 | A self-test of the lanes' stream probe: its own source, compiled, on a fake page reading a fake event stream | It times events 1, 2 and 3, skips the keep-alive, joins an event split across two chunks, and leaves the page every byte of its own copy | `probe-selftest.txt` |
| 8 | `scripts/checks/p14.sh` with an address that does not resolve: `lane 3`, `lane 7`, and a state folder inside the repo | Lanes 3 and 7 fail with their reason, and the script refuses the folder | not saved |

Docker had about 2.4 GB free on the machine that wrote this, so `check.sh` ran in CI instead, which is the same script. OpenTofu, tflint and Checkov were not run locally for the same reason.

What these checks do not cover: anything on Azure, and the lanes themselves. Whether the student subscription allows Southeast Asia and the free tier, how long the Cosmos DB account takes to create, and whether platform-api reads its key through Key Vault are untested until the deploy. The browser lanes have only been typechecked, linted and listed, and the probe self-tested. Their first real run is the checker's, after the deploy. The local stack needs about 3 GB on the Docker disk, so it was not started here either.

## Accepted findings the Cosmos DB account added

Each is written next to its code with its reason, as the infra README describes.

| Tool | Rule | Where | Why we accept it |
|---|---|---|---|
| Checkov | CKV_AZURE_140 | Cosmos DB account | Local auth stays on, because platform-api signs in with the account key today. The key is in Key Vault, and platform-api's identity already has the data role, so turning it off is a code change in platform-api plus one line in `modules/cosmos/main.tf` |
| Checkov | CKV_AZURE_99 | Cosmos DB account | No IP or network filter. Container Apps without a virtual network have no fixed outbound address, and the checker reads items from a laptop. The key and the data roles are the control, as for Key Vault |
| Checkov | CKV_AZURE_101 | Cosmos DB account | Public network access stays on for the same reason. A private endpoint comes with DevNet (ADR 0005) |
| Checkov | CKV_AZURE_100 | Cosmos DB account | Microsoft-managed keys encrypt the data. A customer-managed key needs a Key Vault key and an identity for the account, for an account that holds only a copy of the activity log |
| tflint | `azurerm_resources_missing_prevent_destroy` | Cosmos DB account, database and container | They hold only a copy. PostgreSQL keeps every event, and the copier fills a new account, so `terraform destroy` stays the way to stop spending credits |

One Checkov rule now passes that would not have before: CKV_AZURE_132, because the account key may not create or change databases and containers.
