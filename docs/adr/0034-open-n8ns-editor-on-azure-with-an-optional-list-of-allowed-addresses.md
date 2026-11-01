---
status: proposed
---

# Open n8n's editor on Azure, with an optional list of allowed addresses

ADR 0027 (proposed) has staff maintain each workflow in n8n, through "Open in n8n". On Azure, n8n has internal ingress, so nobody outside the Container Apps environment can open its editor. The team needs the editor on Azure to try that flow and to fix n8n workflows during tests.

So the deploy gets a switch, `N8N_EDITOR_EXTERNAL`. When it is on, n8n's ingress becomes external, at `https://n8n.<domain>`. n8n then gets its public address (`N8N_PROTOCOL`, `N8N_HOST`, `N8N_EDITOR_BASE_URL`), and platform-api and the bootstrap job call n8n at that address. When it is off, nothing changes from before.

An optional allow list, `N8N_EDITOR_ALLOWED_IPS`, goes with the switch. When it holds addresses, Container Apps lets in only those, plus the inside ranges below, and answers everyone else with "RBAC: access denied" ([IP ingress restrictions](https://learn.microsoft.com/en-us/azure/container-apps/ip-restrictions)). When it is empty, every address reaches n8n's sign-in page.

**The operator's choice, 1 Nov 2026: open the editor with no address limit for now.** Only n8n's own sign-in protects it: the owner account, with a 48-character random password kept in Key Vault (`n8n-owner-password`). The allow list is built and tested, and one setting turns it on.

**The approval gate does not change.** n8n holds no key that writes to Jira, Confluence or Teams. Before every write, platform-api's write gateway checks its own records: the proposal was approved under the rules, by nobody whose work it is, and its digest still matches what the Approvers saw (`write_actions.check`, ADR 0008, kept by ADR 0026). So someone who edits an n8n workflow can change the route a run takes, but cannot make a write happen without a yes in Teams. Nothing here touches the approval gate or the safety checker.

**The inside ranges.** With an allow list on, platform-api's and the bootstrap job's calls to `https://n8n.<domain>` must still get in, or every run breaks. Here is what Microsoft documents:
- A call from one app to another in the same environment "never leaves the environment" and always passes through the environment's proxy ([Communicate between container apps](https://learn.microsoft.com/en-us/azure/container-apps/connect-apps)).
- The same page lists IP restrictions among the features that affect calls between apps. It does not say which source address such a call has.
- A workload profiles environment, which ours is, reserves 100.100.0.0/17, 100.100.128.0/19, 100.100.160.0/19 and 100.100.192.0/19 ([Restrictions for subnet address ranges](https://learn.microsoft.com/en-us/azure/container-apps/custom-virtual-networks#restrictions-for-subnet-address-ranges)).

platform-api's own logs on Azure show callers at 100.100.0.51 and 100.100.0.164. uvicorn logs the proxy's address there, not the caller's. A [published test](https://zenn.dev/georgeosddev/articles/azure-container-apps-ip-restrictions?locale=en) from January 2026 saw the same pattern: a calling app at 100.100.205.191 and the proxy at 100.100.0.x. It also found that IP rules did not block calls between apps to an app with internal ingress. It did not test an external app.

So the allow list also lets in those four ranges, through the setting `N8N_INTERNAL_ALLOWED_CIDRS`. If the deploy shows the calls come from somewhere else, that setting changes without a code change. These ranges are in shared address space (100.64.0.0/10), which is never routed on the internet. In the same test, an allow rule for 100.100.0.0/24 did not let an outside client in.

**What the bootstrap overwrites.** Every deploy runs the bootstrap job. It reloads the platform's own three n8n workflows from git: `run`, `schedule_tick` and `run_failure_reporter`. Hand edits to those three are lost on the next deploy. It leaves every other n8n workflow alone. The one exception is the old `release_check`, which it removes by that exact name.

## Considered options

- **Open with the allow list on from the start.** Strangers could not reach n8n at all. The operator chose to start without a limit, so the team can open the editor from any network while testing.
- **Keep n8n internal, and reach it through a virtual machine or a bastion.** Nothing would face the internet. But both need a virtual network, which the environment cannot join after it is created, and they cost money every month.
- **Container Apps' built-in sign-in (Easy Auth) with Entra ID, instead of addresses.** Anyone in the tenant could sign in from anywhere. But it guards the whole app, including the n8n webhooks that platform-api calls and n8n's API that the bootstrap uses. Those paths would have to stay open, and the webhooks take any call today. It fits later, as the last consequence below says.

## Consequences

- **With no address limit, these risks stand until the allow list is on:**
  - n8n's sign-in page is on the internet. It is only as strong as the owner's password and n8n's own code. The password is random and in Key Vault, so the remaining risk is a flaw in n8n. The pinned n8n version (`infra/public-images.json`) must be kept up to date.
  - n8n holds the key it uses to call platform-api, the `X-Step-Key` credential. Anyone who signs in to n8n can put it in a node and call our step API. The write gateway still refuses any write that has no yes.
  - ADR 0027's node allow list (`NODES_INCLUDE`) is not built yet. So whoever signs in can add any n8n node, such as HTTP Request, and send what a run read to an outside address.
  - The `run` workflow's two webhooks take calls from anyone. Each call starts an n8n execution that asks our API to run a step. Our API refuses a run it does not know, and run IDs carry 80 random bits. So a stranger can make noise, but cannot touch a run without its ID.
- **Recommendation: turn the allow list on before the sponsor demo, and before any real credentials go into n8n.** It is one secret, `N8N_EDITOR_ALLOWED_IPS`, and one deploy.
- **A race for the owner, closed twice.** Until n8n has an owner, its setup page (`/rest/owner/setup`) lets the first visitor become the owner. The deploy applies everything first and runs the bootstrap job, which creates the owner, after that. So on a new environment, after a destroy or at handover, an open n8n would wait on the internet with no owner, and whoever reached it first would own it. Two things close this:
  - **The deploy's gate.** Before the full apply, `infra/scripts/n8n-editor-gate.sh` lets n8n open only if the `bootstrap` job has a Succeeded execution in the resource group. Otherwise n8n stays internal for that deploy, and the run summary says to run the deploy again. Later deploys pass, so ingress does not flip. If `az` fails, the deploy stops instead. Microsoft says only that a job keeps a history of recent executions ([Jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs#get-job-execution-history)). If that history ever empties, n8n stays internal for one deploy, which is the safe side.
  - **n8n's own setting.** While the switch is on, n8n gets `N8N_INSTANCE_OWNER_MANAGED_BY_ENV=true`, the owner's email and names, and `N8N_INSTANCE_OWNER_PASSWORD_HASH`. In the pinned n8n 2.42.6, `start.js` runs this owner setup in `init()`, before `server.start()`, and rewrites the owner on every start (`OwnerInstanceSettingsLoader`, `overwriteExisting: true`). So the owner exists before n8n answers anyone. The bootstrap's own setup call then gets "Instance owner already setup" and signs in, as on every deploy since the first. The hash is the random provider's stored bcrypt hash of `n8n-owner-password`. An offline check showed it passes n8n's hash pattern, and n8n's own password check accepts the password with it. It is the n8n app's own secret, not a Key Vault secret, because a new Key Vault secret would replace the app identity's role wait, and the plan guard stops on that.
- **The owner's password stays as Key Vault holds it.** While the editor is open, n8n refuses to change that account's password or email, because its settings manage the account. Staff accounts come with ADR 0027.
- **Switching on or off is an in-place update.** In azurerm 5.7.0, no field in the ingress or secret blocks forces a replace, so the plan guard lets the deploy go ahead. n8n restarts once with its new address. For about a minute of the apply, platform-api can still call the old one, so deploy while no run is in progress.
- **The allow list covers all of n8n,** not only the editor: its webhooks and its API too.
- **What dropping the allow list for good would take:**
  - the `run` workflow's webhooks give way to ADR 0027's "Start from the Portal" trigger, which checks our API's signature;
  - n8n's Webhook node leaves the node allow list;
  - something signs people in before they reach n8n, such as Easy Auth with Entra ID, with only the signed paths left open. n8n's own single sign-on is a paid feature.
- **If this ADR is accepted,** ADR 0027's "Open in n8n" can link to `n8n_editor_url`, a new Terraform output.
