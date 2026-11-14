# Security of the app and platform

This page lists each security concern, what we do about it, and where the proof is. It describes `main` at commit `a7ba7673`, on 14 Nov 2026. Each row links to the file, test, pull request (PR), CI run or scan that shows it. Anything we cannot prove yet is in [Known gaps and open items](#known-gaps-and-open-items).

## The short version

- **The main risk is an AI agent changing Jira without a person agreeing.** So agents only propose changes. An Approver who is not part of the run says yes under their own sign-in. Then our own write gateway checks that yes against our database at the moment of each write.
- **n8n runs each workflow but holds no key that can write.** Someone who edits a workflow in n8n and deletes the approval step still cannot make a write happen.
- **Keys live in Azure Key Vault and GitHub secrets, never in git.** CI scans for leaked secrets and for weak code on every PR and every push to `main`.
- **Each engine PR that touches safety had a review by a separate AI model before merge**, as the table near the end shows. Most also proved that removing any one safety guard makes a test fail.

## How one write stays safe

1. An agent proposes a change. It holds no write tool and no write key ([ADR 0008][a08]).
2. Our API ties the change to its target and stores a digest, a fingerprint of the exact change.
3. The "Ask for a yes" block pauses the run in n8n. The request goes to Teams, and the Approver decides on our approval page under their own sign-in ([ADR 0009][a09], [ADR 0036][a36]).
4. Our API wakes n8n with a signed message that carries the decision.
5. The "Make the approved changes" block asks the write gateway. The gateway checks our own records, then calls Jira ([ADR 0026][a26]).

## The approval gate

These are the sponsor's rules from [`AGENTS.md`][agents]. Tests marked e2e run against the whole stack with real n8n.

| Concern | What stops it | Proof |
|---|---|---|
| A write with no yes | Only the write gateway writes, and only for a yes in our records. A run whose "Ask for a yes" was deleted in n8n fails with "No yes for this run" | e2e [`test_gate_removed`][e2e]. [`test_safety_a_write_before_any_yes_stops_the_run_and_writes_nothing`][t-write] |
| An Approver approves their own work | `decide()` refuses `own_work`. The run's parties are whoever started, owns, published or retried it | [`test_safety_no_party_to_the_run_can_approve_its_request`][t-wait]. e2e [`test_publisher_cannot_approve`][e2e]. In the ZAP scan, 432 requests reached the decision check and all 432 got 403 ([DAST, 31 Oct][dast2]) |
| The access review with only one Approver | Two Approvers, one after the other. One person cannot decide both steps (`same_person_twice`) | [`test_safety_the_access_review_writes_only_after_two_approvers_in_turn`][t-write]. [`test_safety_the_access_review_needs_two_approvers_in_turn_before_n8n_wakes`][t-wait] |
| An approval keyed off n8n's execution id | Decisions key off our own request id. There is no approval token to steal, because the Approver decides under their own sign-in ([ADR 0009][a09]) | [`test_safety_the_wake_keys_off_our_request_id_not_n8ns_execution_id`][t-wait] |
| A request nobody answers approves itself | It expires after a set wait, counted in working hours, and nothing is written. A yes after the expiry is refused ([ADR 0024][a24]) | e2e [`test_expiry_wakes_no_answer`][e2e]. [`test_safety_a_yes_after_the_expiry_is_refused_and_recorded_nowhere`][t-write] |
| A yes for one Jira used in another Jira | The Jira site is part of what the Approver approves. The checker refuses `target_changed` ([ADR 0041][a41], found in [issue #166][i166]) | [`test_a_write_approved_on_the_practice_jira_is_not_made_on_jira_b_after_the_switch`][t-jira] |
| The Approver trusts the AI's summary instead of the change | The approval page shows every field that will be written. It labels the AI summary "Decide on the change above, not this." | [PR #260][pr260] |
| A test run writes | A draft's test run stops at the yes, asks nobody and writes nothing ([ADR 0044][a44]) | [`test_safety_a_test_run_never_writes_even_with_a_yes_on_record`][t-write]. [`test_safety_a_test_run_runs_the_draft_by_hand_asks_nobody_and_writes_nothing`][t-engine] |

## The write gateway

`check()` in [`write_actions.py`][wa] is the only code that can create the `AuthorizedWrite` value the gateway needs ([`test_authorized_write_cannot_be_built_directly`][t-wa]). It denies by default. It refuses the whole proposal for any of these reasons.

| Reason | What it stops |
|---|---|
| `run_mismatch` | A yes for one run used by another run |
| `test_run` | Any write from a test run |
| `invalid_decisions` | Decisions that break the approval rules |
| `expired` | A write after the request expired |
| `not_approved` | A write without every required yes |
| `digest_mismatch` | A change edited after the Approver saw it |
| `unregistered_action` | Any kind of write not on our list |
| `target_changed` | A write to a Jira other than the one approved |

- **Never written twice.** An action can name a subject, such as `{repo}@{tag}` for a release. Its write key is `subject/<sha256(use case + subject)[:40]>`, so every later run skips a change one run already made ([PR #247][pr247], [PR #253][pr253]). PR #247 reports five gateways racing on one change called Jira once. Test [`test_safety_a_subject_made_by_one_run_is_never_made_again_by_another`][t-gw].
- **A part-done write says so.** If one write of three fails, the block reports "2 of 3 made" and n8n shows it red. A retry makes only the rest ([`test_safety_a_part_done_write_says_2_of_3_and_a_retry_makes_only_the_rest`][t-write]).
- **Only the run's own n8n execution writes.** Two "Make" blocks after one yes write once ([`test_safety_only_the_execution_the_run_acts_in_writes`][t-write], [`test_safety_two_make_blocks_after_one_yes_write_once`][t-write]).

## n8n, the engine

Since 13 Nov each workflow is its own n8n workflow, built from our node pack ([ADR 0026][a26], [ADR 0027][a27], both accepted). Staff may edit workflows in n8n, so we never trust n8n to keep the gate. [ENGINE-PLAN section 4.2][plan] lists each threat and its guard.

| Control | What it stops | Proof | Status |
|---|---|---|---|
| Our blocks have no address field and no credential. They call only `WAB_API_URL`, with `WAB_NODE_KEY` from the container | Someone editing a block points it at another system or reads the key | [Node pack README][pack], [PR #241][pr241] | Built |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`. Execute Command and Local File Trigger excluded. Community packages off | An expression reads keys from the environment, or a node runs shell commands | [`deploy/compose.yaml`][compose] lines 85 to 87, [`infra/envs/dev/main.tf`][tf] lines 349 to 351 | On in both |
| Node allow list (`NODES_INCLUDE`) | Any node not on the list, such as HTTP Request or Code. n8n refuses to save or turn on a workflow with one | [`scripts/pack-smoke.sh`][smoke] in CI's `n8n-node-pack` job. Spike P7 ([PR #240][pr240], [findings][p7]) | Built and tested, not yet switched on (E11) |
| Signed start. An HMAC-SHA256 with `WAB_START_SECRET` over the workflow id, webhook id, nonce, kind and expiry. Our API issues each nonce for one run and uses it once | A forged or replayed Run now, or a start for one workflow used on another | [`startFromPortal.test.ts`][t-start], [`test_safety_a_start_is_signed_for_its_own_workflow_and_no_other_takes_it`][t-engine] | Built |
| Signed wake. A `mac`, an HMAC-SHA256 with `WAB_NODE_KEY` over the execution id, request id and decision. A wrong mac gets 401 and picks no exit. An error lands on "No answer", never on Yes | A forged wake, or n8n's resume URL used alone | [`askForYes.test.ts`][t-ask], e2e [`test_resume_url_alone_writes_nothing`][e2e] | Built |
| The resume URL is sealed at rest and never returned by any route | Someone reads it from our database or API | [PR #246][pr246] | Built |
| Grading. `grade()` walks every path and puts "Ask for a yes" before every write. It refuses HTTP, Code, Webhook and unknown nodes. Only a version graded Safe goes live | A workflow published without the gate | [`workflow_check.py`][wc], [`test_safety_only_a_version_graded_safe_ever_goes_live`][t-life] | Built ([PR #253][pr253], [PR #261][pr261]) |
| The Tell rule. A notice goes only to recipients fixed in settings. Our API writes it from what the run read, escaped, and its only link goes back to the run. A test run sends nothing | A notice used to send data to an address someone chose | [`test_n8n_tell.py`][t-tell], [PR #249][pr249], [PR #252][pr252] | Built |
| Failure reports from n8n. Our API answers 403 unless the report comes from our error workflow, and 409 unless n8n's own record says the run failed | A forged report fails a run | [PR #249][pr249], [node pack README][pack] | Built |
| n8n's own nodes are classed `read`, `notice`, `write` or `off` in `node_classes.json`. Unknown means off. The `write` class is empty | n8n's built-in nodes writing with their own credentials | [ADR 0045][a45], accepted 14 Nov | Decided, not built |

## Keys and secrets

| What | How we handle it | Proof |
|---|---|---|
| App secrets on Azure | Terraform generates each one with `random_password` and writes it to Key Vault. No secret value is in any `.tf` or tfvars file. Each app reads its secrets through its own managed identity | [`infra/README.md`][infra] (Secrets), [`main.tf`][tf] |
| The Terraform state | It holds the generated secrets in plain text. It lives in Azure Storage with access keys turned off | [`infra/README.md`][infra] (Secrets) |
| Deploy credentials | The deploy signs in to Azure with GitHub's OpenID Connect token in the `azure-dev` environment. Tokens such as Jira's come from GitHub secrets | [`deploy.yml`][deploy] |
| `WAB_NODE_KEY` and `WAB_START_SECRET` | Random values in Key Vault, set only on n8n and platform-api. Never logged or returned | [PR #241][pr241], [`test_safety_nothing_logs_or_returns_the_node_key_or_the_resume_signature`][t-wait] |
| AI model keys saved in Settings | Encrypted at rest by `KeyBox`, under a key made from `SETTINGS_ENCRYPTION_KEY`. The Settings view never holds the key | [`model_settings.py`][ms], [`test_the_key_is_stored_sealed_and_never_in_plain_text`][t-ms] |
| GitHub, Confluence, Tell flow and n8n owner keys | The GitHub token stays in the agent runtime only. The n8n API key asks for nine scopes and expires in three days. The Confluence token and the Tell flow URL are never logged or returned | [PR #253][pr253], [PR #259][pr259], [PR #252][pr252] |
| `.env` files | Git ignores `.env` and `.env.*`, except `.env.example`. `deploy/make-env.sh` makes local secrets | [`.gitignore`][gi], [`make-env.sh`][mkenv] |
| A secret committed by mistake | gitleaks runs with its default rules on every PR and push to `main`. The only exceptions are two public Azure role ids | [`.gitleaks.toml`][gl], [`ci.yml`][ci] `scans` job, [`gitleaks.txt`][gltxt] |

## Sign-in and roles

- **Sign-in is OpenID Connect, with Entra ID on Azure** ([ADR 0018][a18]). platform-api checks the signature (RS256 or ES256 only), the issuer, the audience and the expiry of every token itself. [`test_oidc.py`][t-oidc] covers each refusal, for example `test_a_token_from_another_issuer_is_refused` and `test_hs256_signed_with_the_public_key_is_refused_without_asking_the_issuer`.
- **The dev sign-in stub runs only on localhost.** [`auth.py`][auth] refuses to start it on any other host, and OIDC mode ignores its header (`test_x_dev_user_is_ignored_in_oidc_mode`).
- **Two roles, Operator and Approver, kept by the platform** ([ADR 0029][a29]). Entra only says who someone is. Someone not on the People list is told to ask an Operator and gets 403. A new Approver waits for a second person to confirm. There are always at least two Approvers, and nobody removes their own Operator role. Tests in [`test_people_http.py`][t-people], such as `test_a_new_approver_waits_for_another_approver` and `test_a_removed_approver_cannot_decide_a_run_in_the_same_minute`.
- **Every change route needs the right role.** [`test_operators_only.py`][t-ops] walks every route and fails on a change with no role check.
- **On Azure, on 31 Oct and 1 Nov 2026**, the deployed app passed all eleven P14 lanes, the performance lane included. They include the first Operator signing in and seeing their role, someone not on the People list being turned away, and plain http refused or sent to https ([first deploy][first], [`p14-summary.txt`][p14]).

## Scans in CI

| Scan | Tool | When it runs | Latest saved result | Evidence |
|---|---|---|---|---|
| SAST | Semgrep 1.179.0, eight rule packs | Every PR and push to `main`. Any finding fails the job | 14 Nov at `a7ba7673`. 313 rules on 625 files, 0 open findings, 1 suppressed in the source with its reason | [SAST README][sast] |
| Secrets | gitleaks 8.21.2 | Every PR and push to `main` | 23 Oct. No leaks in the files or in the history of the review-fix commits | [IaC README][iac], row 14 |
| Infrastructure as code | Checkov 3.3.20, TFLint 0.64.0, Terraform and OpenTofu validate | Every PR that touches `infra/` | 31 Oct. Checkov passed 7, failed 0, skipped 19. TFLint 0 issues. Each skip has its reason next to the code | [IaC README][iac], [`infra-checks/`][infrachecks] |
| DAST | OWASP ZAP 2.17.0 against the whole running stack | Every push to `main`, and on demand | 31 Oct, two runs. No High or Medium finding. One Low, a recorded false positive | [DAST README][dast2], [first scan][dast1] |
| DAST on Azure | ZAP baseline of the deployed Portal | P14 lane 10 | 1 Nov. 0 Medium or High. The missing HSTS header ([#91][i91]) was fixed by [#96][pr96] | [`p14-zap-rerun.txt`][zapaz] |
| n8n allow list | Our pack smoke on the pinned n8n image | Every PR, in the `n8n-node-pack` job | n8n loads exactly the listed types and refuses an HTTP Request node | [`pack-smoke.sh`][smoke] |

## Security reviews on the engine PRs

Each review was by a separate AI model, named in the PR, and the table quotes what the PR body says. The mutation check removes each safety guard in turn and confirms a test fails. Each CI run listed passed every job, live e2e included.

| PR | What the review found | What changed | Mutation check, CI run |
|---|---|---|---|
| [#238][pr238] | A safety review of the engine plan found 6 must-fix and 8 should-fix. A re-check found three small gaps the fixes opened | All resolved, listed in [ENGINE-PLAN][plan] section 8 | Docs only |
| [#239][pr239] | A Fable review found no blocker | Doc nits fixed. The approval gate's files have no diff | 3 tests fail with the stop at the gate off. Run 43384611860 |
| [#241][pr241] | A Fable security review found 1 must-fix, to close the environment and Execute Command paths to the keys before the allow list is on. Also 4 should-fixes, including two-sided clock skew, a smoke that proves refusal, and a wake bound to its request | All fixed. The re-check found nothing new | 18 guards. Run 43401205331 |
| [#244][pr244] | A Fable review found no must-fix. An automated review flagged a webhook credited fail-open and unchecked agent inputs | Nothing stored before n8n vouches. A changed repeat gets 409. Both flags closed with tests | 23 guards. Run 43412795465 |
| [#246][pr246] | A Fable review found no must-fix. Its fixes are in the next column | A one-request lock, expired steps, no echo on a 422 (the routes did echo the resume address before), and the logging setup | 19 guards. Run 43420096196 |
| [#247][pr247] | A Fable review found no must-fix | A late yes is refused at decide time. A direct test covers the per-change key | 21 guards. Run 43437420348 |
| [#249][pr249] | A Fable review found no must-fix. An automated review flagged a failure report trusted as sent, and a fail that slipped through when no execution held the run | A Tell after No or No answer. No failure mid-write. Both flags closed with tests | 23 guards. Run 43448605365 |
| [#252][pr252] | A Fable review found no must-fix | The Tell rule's text names the run link. The email list is a plain variable end to end | Run 43464810730 |
| [#253][pr253] | A Fable review found no must-fix | The n8n API key's scopes and expiry. New drafts graded against the allowed options | 19 guards. Run 43467020374 |
| [#259][pr259] | A Fable review confirmed exact page scope and no SSRF (settings-only address, no redirects, 10 s timeout, 1 MB cap). Its must-fix was in the cert parser | The cert parser was removed | Run 43491283138 |
| [#260][pr260] | An Opus review found no must-fix. It confirmed Approve shows only for someone the server accepts | One pill, the refusal said once, every field shown | Run 43557700455 |
| [#261][pr261] | A Fable review found no must-fix. Separately, live runs on real n8n found retries refused for a missing key scope | One retry per press, status-only sweep reads, the grade checked before going live. The scope was added | 20 guards. Run 43564835051 |

## Moving into DevNet

- **The lock-down test, 31 Oct.** The stack ran with no route out except a proxy that allowed three hosts. The proxy refused and logged every call to any other host. Calls that skipped the proxy failed. A Software watchlist check still ran to Done ([lock-down test][lock]).
- **What broke.** Connecting the AI model failed, because the address guard does not use the proxy ([issue #86][i86]). The fix waits for NCS to say which model DevNet uses and whether there is a proxy. Two n8n problems were fixed on 1 Nov.
- **What NCS must answer.** [The DevNet move][devnet] lists nine questions, such as private endpoints in NCS's Azure, which AI model DevNet may call, and whether traces may go to LangSmith.

## Known gaps and open items

1. **The n8n node allow list is built and tested, not yet switched on.** [`deploy/compose.yaml`][compose] line 86 and [`main.tf`][tf] line 350 set only `NODES_EXCLUDE`. Engine PR E11 turns it on. The plan creates no staff n8n accounts before E11 ([ENGINE-PLAN][plan] section 6).
2. **n8n's editor on Azure is open to any address.** Only the owner's sign-in, with a 48-character random password in Key Vault, protects it. The address allow list is built, and one setting turns it on ([ADR 0034][a34]).
3. **No evidence yet of the engine on Azure.** The Azure evidence here is from 31 Oct and 1 Nov. Each engine PR says merging deploys nothing, so the engine's controls are proven in CI and on the local stack.
4. **Some engine steps are not built yet** ([ENGINE-PLAN][plan] section 6). E3 is the error workflow through "Report a failure" and its daily self-test. E9 and E10 move the Software watchlist and older workflows off the old shared n8n workflow. E16 and E17 add n8n's own read and notice nodes, and the sweep that deletes keys staff add in n8n. E18, the write proxy, is deferred.
5. **Two weaker points if a built-in write node is ever added** ([ADR 0045][a45] section 2). The digest would cover only the mapped fields, and a staff key would have up to a minute before the sweep removes it. The `write` class is empty, so neither applies today.
6. **The wake's mac uses the node key.** A separate wake secret is a later improvement ([PR #241][pr241]).
7. **No backup Approver yet.** Every step is "any Approver" today, and expiry does not update the Teams card yet. Its link answers "not open" ([PR #246][pr246]).
8. **Some ADRs whose design is built still say proposed.** They are [0008][a08], [0009][a09], [0018][a18], [0029][a29], [0034][a34] and [0044][a44]. ADR 0008 also asks the sponsor to confirm that the safety checker covers writes, while reads are safe because agents cannot write.
9. **Azure has no private network, to save credits.** Key Vault, PostgreSQL and Cosmos DB use public endpoints. The PostgreSQL rule lets in any Azure customer's services, and TLS plus a 48-character password per role keep others out. The team lead accepted this for the demo on 23 Oct ([`infra/README.md`][infra], Known risk). Key Vault secrets do not expire and nothing rotates them yet ([IaC README][iac]).
10. **What the DAST scan does not cover.** It signs in only as Alice. It does not test internal routes past their key, the live event stream, the Portal's screens in a browser, n8n, or TLS ([DAST README][dast2]). The Azure scan still shows one Low warning, a missing Cross-Origin-Embedder-Policy header ([`p14-zap-rerun.txt`][zapaz]).
11. **DevNet is not tested for real.** The lock-down test is a model on a laptop, and the nine questions to NCS are open ([DevNet move][devnet]).

[agents]: ../../../AGENTS.md
[a08]: ../../adr/0008-agents-propose-writes-the-platform-executes.md
[a09]: ../../adr/0009-approvers-decide-under-their-own-sign-in.md
[a18]: ../../adr/0018-sign-in-with-openid-connect.md
[a24]: ../../adr/0024-each-use-case-names-its-approvers-and-unanswered-requests-go-to-a-backup-then-expire.md
[a26]: ../../adr/0026-every-write-is-checked-when-it-is-made-so-n8n-may-hold-the-wait.md
[a27]: ../../adr/0027-staff-maintain-each-workflow-in-n8n-and-the-portal-keeps-every-published-version.md
[a29]: ../../adr/0029-entra-id-signs-people-in-and-the-platform-keeps-their-roles.md
[a34]: ../../adr/0034-open-n8ns-editor-on-azure-with-an-optional-list-of-allowed-addresses.md
[a36]: ../../adr/0036-the-approval-request-goes-to-teams-as-an-adaptive-card-that-opens-our-approval-page.md
[a41]: ../../adr/0041-an-approved-jira-write-is-made-only-in-the-jira-it-was-approved-for.md
[a44]: ../../adr/0044-a-draft-is-tried-with-a-test-run-that-stops-at-the-yes-then-turned-on.md
[a45]: ../../adr/0045-n8ns-own-nodes-join-the-allow-list-classed-by-operation-and-a-write-still-needs-a-yes-our-api-checked.md
[plan]: ../../design/chat-first/ENGINE-PLAN.md
[devnet]: ../../design/devnet-move.md
[pack]: ../../../n8n-node-pack/README.md
[t-start]: ../../../n8n-node-pack/test/startFromPortal.test.ts
[t-ask]: ../../../n8n-node-pack/test/askForYes.test.ts
[smoke]: ../../../scripts/pack-smoke.sh
[compose]: ../../../deploy/compose.yaml
[mkenv]: ../../../deploy/make-env.sh
[tf]: ../../../infra/envs/dev/main.tf
[infra]: ../../../infra/README.md
[ci]: ../../../.github/workflows/ci.yml
[deploy]: ../../../.github/workflows/deploy.yml
[gl]: ../../../.gitleaks.toml
[gi]: ../../../.gitignore
[wa]: ../../../platform-api/src/platform_api/orchestration/write_actions.py
[wc]: ../../../platform-api/src/platform_api/orchestration/workflow_check.py
[ms]: ../../../platform-api/src/platform_api/orchestration/model_settings.py
[auth]: ../../../platform-api/src/platform_api/auth.py
[e2e]: ../../../e2e/tests/test_n8n_engine.py
[t-write]: ../../../platform-api/tests/test_n8n_write.py
[t-wait]: ../../../platform-api/tests/test_n8n_wait.py
[t-engine]: ../../../platform-api/tests/test_n8n_engine.py
[t-life]: ../../../platform-api/tests/test_n8n_lifecycle.py
[t-tell]: ../../../platform-api/tests/test_n8n_tell.py
[t-gw]: ../../../platform-api/tests/test_write_gateway.py
[t-wa]: ../../../platform-api/tests/test_write_actions.py
[t-jira]: ../../../platform-api/tests/test_jira_target_switch.py
[t-ms]: ../../../platform-api/tests/test_model_settings.py
[t-oidc]: ../../../platform-api/tests/test_oidc.py
[t-people]: ../../../platform-api/tests/test_people_http.py
[t-ops]: ../../../platform-api/tests/test_operators_only.py
[sast]: ../sast/README.md
[iac]: ../iac/README.md
[gltxt]: ../iac/gitleaks.txt
[infrachecks]: ../deploy/infra-checks/
[dast1]: ../dast/README.md
[dast2]: ../dast/2026-11-rebuild/README.md
[zapaz]: ../deploy/p14-zap-rerun.txt
[first]: ../deploy/first-deploy.md
[p14]: ../deploy/p14-summary.txt
[lock]: ../devnet/lockdown.md
[p7]: ../prototypes/p7-n8n-engine-facts/findings.md
[i86]: https://github.com/qj1e7/ai-agent-workflow-builder/issues/86
[i91]: https://github.com/qj1e7/ai-agent-workflow-builder/issues/91
[pr96]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/96
[i166]: https://github.com/qj1e7/ai-agent-workflow-builder/issues/166
[pr238]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/238
[pr239]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/239
[pr240]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/240
[pr241]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/241
[pr244]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/244
[pr246]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/246
[pr247]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/247
[pr249]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/249
[pr252]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/252
[pr253]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/253
[pr259]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/259
[pr260]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/260
[pr261]: https://github.com/qj1e7/ai-agent-workflow-builder/pull/261
