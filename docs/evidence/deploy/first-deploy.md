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

These P14 lanes need no signed-in browser, so they ran straight after the deploy. The README's step 5 lists all ten.

| Lane | Result | Evidence |
|---|---|---|
| 3 | PASS. `GET /healthz/ready` is 200. The activity log, the copy to Cosmos DB and n8n's workflows (`run_failure_reporter`, `run`, `schedule_tick`) are all ready | `p14-ready.json` |
| 7 | PASS. Plain http to the Portal and to platform-api gets a 301 to https | `p14-https.txt` |
| 10 | PASS. The ZAP baseline scan of the Portal has 0 Medium or High alerts. Its one Low alert, no Strict-Transport-Security header, is issue #91 | `p14-zap.txt` |

The other lanes need each test account signed in once, after the Portal's address is on its app registration (infra README step 9).
