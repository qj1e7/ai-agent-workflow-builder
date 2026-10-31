# The first deploy to Azure, 31 Oct 2026

The rebuilt app first deployed to Azure on 31 Oct 2026, from `main`, through `.github/workflows/deploy.yml`. It took seven runs. Each failed run stopped at a step the checks without Azure could not reach, and each fix went to `main` through its own pull request before the next run.

The subscription is Azure for Students. Its policy allows five regions, and Southeast Asia is not one of them. So `AZURE_LOCATION` is `eastasia`. Cosmos DB had no capacity left in East Asia that day, so `COSMOS_LOCATION` is `koreacentral`.

| Run | Commit on `main` | Stopped at | What was wrong | Fix |
|---|---|---|---|---|
| [41158792708](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/41158792708) | `8ee417d` | Azure sign-in | GitHub's sign-in token now names the owner and repository by their IDs too, and the deploy identity trusted only the names (AADSTS700213) | A second federated credential with the ID form. `setup-azure.sh` creates both (#84) |
| [41158886844](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/41158886844) | `8ee417d` | Full apply | Cosmos DB refused the account: "high demand in East Asia region". The failed account was deleted by hand | `COSMOS_LOCATION=koreacentral` |
| [41177982440](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/41177982440) | `c637152` | Create the database roles | Azure created the Container Apps environment as an express one, which runs no jobs (`ExpressEnvironmentResourceNotSupported`) | A Consumption workload profile (#87), and the environment deleted by hand |
| [41179247117](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/41179247117) | `88e3b5e` | Create the database roles | Still express. Azure ignores the workload profile unless the request also sets `environmentMode` | The live environment switched to workload profiles mode by hand, then made permanent with the azapi provider (#88, ADR 0033) |
| [41183017526](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/41183017526) | `88e3b5e` | Create the database roles | The db-init job ran but could not reach PostgreSQL: the targeted apply had not created the firewall rule or the databases | The step also targets `module.postgres` (#89) |
| [41184007065](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/41184007065) | `c4fe83f` | Run the bootstrap job | n8n's own migrations failed with "permission denied for schema public". On Azure's PostgreSQL, owning a database does not give its owner the public schema | db-init grants n8n `USAGE` and `CREATE` on it (#90) |
| [41185568874](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/41185568874) | `f78617a` | Passed every step | | |

The plan guard (`infra/scripts/plan-guard.sh`) checked every apply, and none of the seven runs planned a destroy or a replace.

## Checked after the deploy

All ten P14 lanes and the speed check pass against the deployed app (`p14-summary.txt`). Lanes 3, 7 and 10 need no signed-in browser and ran first, on 31 Oct 2026. The others ran later that night, after each test account had signed in once. Lanes 4 and 8 first failed and found two bugs, which were fixed, deployed in run [41215961511](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/41215961511) at `ecaa9c9`, and passed on the rerun.

| Lane | What it shows | Evidence |
|---|---|---|
| 1 | A watchlist check reaches the approval gate with the same steps on the local stack at `main` and on Azure | `p14-local-azure.png`, `p14-lane1.json` |
| 2 | The first Operator signs in with Entra ID. Home names them, and Settings shows them as Operator | `p14-sign-in.png`, `p14-sign-in-settings.png` |
| 3 | `GET /healthz/ready` is 200. The activity log, the copy to Cosmos DB and n8n's three workflows are ready | `p14-ready.json` |
| 4 | The first Operator runs a watchlist check, a first Approver approves it, and the practice Jira holds the ticket | `p14-approved.png` |
| 5 | Each of that run's 23 events is in Cosmos DB, under the run's partition, in the same order as the API | `p14-cosmos.json` |
| 6 | Claude Haiku 5.5 through the AI Singapore gateway passes Test and save, so the settings key works | `p14-model.png` |
| 7 | Plain http to the Portal and to platform-api gets a 301 to https | `p14-https.txt` |
| 8 | platform-api restarts while a run page is open. The page opens a new stream and shows every event once | `p14-restart.png` |
| 9 | Someone not on the People list is told to ask an Operator | `p14-not-on-list.png` |
| 10 | The ZAP baseline scan of the Portal has 0 Medium or High alerts. Its one Low alert, no Strict-Transport-Security header, is issue #91 | `p14-zap.txt` |
| perf | Home's median paint is 160 ms on Azure and 20 ms locally. The run page's 95th percentile event delay is 466 ms on Azure and 31 ms locally. The limits are 3 s and 2 s | `p14-perf.json` |

The Settings screenshot had the test accounts' email addresses, which name the Entra tenant. The repository is public, so those two lines are covered in the saved copy.

### What the lanes found

| Lane | First result | Cause | Fix |
|---|---|---|---|
| 4 | The run stopped: "I could not check Pydantic: No release has a plain version number" | Pydantic tags its releases `v2.14.2`. The only allowed tag pattern took plain `2.14.2`, and the tag parser read the `v` as a family of its own. platform-api and the Portal form refused `v` versions as well | #93 |
| 8 | The page reconnected and showed every event once, but Chromium reported an uncaught `TypeError: network error` | The stream reader's clean-up called `cancel()` on a stream that had failed, which rejects with the same error, and nothing caught it | #94 |

The run page and the AI troubleshooter named lane 4's cause on their own: "The agent was refused by the service it reads from, so retrying would get the same answer."
