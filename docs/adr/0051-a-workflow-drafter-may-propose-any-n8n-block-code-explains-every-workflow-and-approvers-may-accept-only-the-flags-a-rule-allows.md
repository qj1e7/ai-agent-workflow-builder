---
status: proposed
---

# A workflow drafter may propose any n8n block, code explains every workflow, and Approvers may accept only the flags a rule allows

On 16 Nov 2026 the team lead asked for a new feature, with this ADR first. A person describes a task in plain English, and an AI agent drafts a complete n8n workflow for it, with its blocks, wiring and settings. The person reviews it, edits it in n8n or asks for changes, and sends it for approval. The drafter may use any block n8n has, not only our node pack and the allow list. The safety checker checks every draft the way it checks a workflow made by hand in n8n (ENGINE-PLAN E15 and E16). When it flags something, "an Approver can still approve the workflow, and it goes through. The checker advises; the human decides." The same day the team lead added "Explain this workflow", which shows the draft's report for any workflow.

`AGENTS.md` says that the safety checker denies write actions by default, and that no safety rule is weakened without an ADR. This ADR changes the safety checker and the approval gate. It amends ADR 0023, ADR 0026, ADR 0045 and ADR 0049, and builds on ADR 0044, ADR 0047 and ADR 0050.

The decision in one paragraph. The workflow drafter, in the agent runtime, writes a plan that may use any block the pinned n8n ships. Code lays the plan out as an n8n workflow, adds what the platform always adds, and runs the safety checker. Code, never the model, writes the report. It says what the workflow does, what it reads, writes and posts, how every check went, and every setting. The person answers the settings only they know, one question at a time. An Approver who is not a party gives a set-up yes to that exact version. Every finding belongs to one of five kinds, in a table in code. Most kinds need a change before anything can run, because n8n loads a block for every workflow or for none, because the platform's keys can only read or post, and because every write waits for a yes that our API checks at the moment of writing. One kind holds the findings about posts that the platform could run but chooses not to. An Approver may accept those, flag by flag with a reason, and two Approvers one after the other when the post sends what a run read out of the platform. No finding about a write is ever in that kind. So the write rule in `AGENTS.md` stays as it is, and the checker stops being final only for the rules the table names.

## Words used here

- **Workflow drafter.** The agent that drafts an n8n workflow from a person's words.
- **Drafted workflow.** What the drafter wrote, with every change made to it, before it is set up. Once set up, it is a Draft in the glossary's sense (ADR 0044) until someone turns it on. The chat may call both a draft. Code and docs keep the two apart.
- **Workflow report.** The plain-words account that code builds of one version of any workflow. The draft card, the approval page and Explain all show it.
- **Set-up approval.** An Approver's yes to set up one version of a drafted workflow.
- **Accepted flag.** A finding that an Approver accepted in a set-up approval. A set-up approval with at least one accepted flag is an **override**.

## Decision

### 1. The flow, and who owns each part

1. **Describe.** An Operator types on Home, and the Planner answers as it does today. When the Planner can lay out the whole request itself (E4's layouts), its set-up card wins. It is instant, it is tested, and it needs no set-up approval. When the Planner's answer is a can't, or a part card with a part that needs a block or a system it can't reach, the answer gains the button "Draft it as an n8n workflow". A person can also ask for a draft in words ("draft an n8n workflow that ..."). In `ai_led` mode (ADR 0049) that is one more tool, `draft_workflow`, whose one argument is text that code locates in the message, as `set_up_workflow`'s is. The drafter never starts without the tap or the words, because one draft costs as much as 17 to 33 Planner messages (section 7). Only Operators may draft, because only they set workflows up (ADR 0030).
2. **Draft.** The builder sends the person's words, unchanged, to a new agent runtime route, `POST /v1/workflows/draft`, beside `/v1/cards/draft`. It also sends the team's facts that the drafter may use: the allowed Jira projects, Confluence pages and repositories, and the saved agent cards. It sends no Approver's name and no key. The drafter works through three tools: `find_blocks(words)`, `describe_block(type, version, resource, operation)` and `submit_plan(plan)`. Code checks each plan against the catalogue (section 8). Every type, version, resource, operation and parameter must exist, each value must fit its parameter, and each wire must join blocks and exits that exist. On every way from a trigger, one of our blocks that calls the platform, such as our Read, must come before the first of n8n's blocks for a system, so that every run is recorded and its version checked first (ADR 0045, amendment 8). A plan may not set `onError`, `continueOnFail`, `alwaysOutputData` or `executeOnce` on any block, or mark a block disabled. A plan that writes to Jira or Confluence with n8n's own block goes back with "Use our Propose a change, Ask for a yes and Make the approved changes blocks", because our connector makes those writes (ADR 0045). That is a rewrite of the plan, not a flag anyone can accept. A plan that fails goes back to the model with the reasons, at most three times. After that the person sees "I couldn't draft that", with Ask the team (ADR 0038), and nothing is shown as working. Neither candidate model accepts a forced tool choice, so the tools are strict, and code ends a turn that calls no tool.
3. **Lay out and check.** A plan holds blocks (name, type, version, parameters), wires (from, exit, to) and settings (section 5). A setting appears in the parameters as a placeholder, never as a guessed value. `builder/layout.py` gains `lay_out_drafted(plan, values)`, built on the `_Canvas` it already has (`node`, `n8n_block`, `link`, `document`, and `block_id` for the ids). It adds what every layout adds and the model never writes: our Start from the Portal beside the schedule, so that Run now and test runs can start it, the Sticky Note, the team time zone, our error workflow, saved progress, retries on our blocks, and pinned output on each notice block so that a test run posts nothing (ADR 0045, amendment 7). Then `add_yes` puts an Ask for a yes before each write, `attach_keys` puts on the platform's keys, and `workflow_check.grade` grades the result with the team's `KnownOptions`, as Made in n8n's set-up does. The builder stores the result as a new revision with its digest (section 3).
4. **Report.** Code builds the workflow report from the revision (section 6). The chat shows the draft card, with its steps, its flags, the questions left, and the full report one tap away.
5. **Questions.** The card asks for each setting that is still needed, one short question at a time, with choices from the platform's own data (section 5).
6. **Edit.** The person asks for a change in the chat, such as "post at 9 instead" or "drop the Slack step". The drafter gets the current plan and those words, and returns a whole new plan. A setting with the same id and kind keeps its value unless the words change it. An Operator with n8n access may press Edit in n8n instead. The platform puts the document in their own n8n space without its keys, as Open in n8n does (ADR 0045, amendment 3), and they change it there. Pressing Done in n8n, on the card, reads it back as a new revision and checks it again. A value they typed in n8n counts as filled by them, once it passes the same check as in the chat (section 5), so a channel must be one the platform's key can see. A placeholder they left counts as still needed. The drafter can still change it after that, because code reads the document back into a plan.
7. **Send for approval.** This works only when no setting is still needed. Until then, the card shows "Answer 2 questions first" in place of the button, and the route answers 409. The sender may add a note to each flag. A new revision cancels a set-up approval that is still waiting, as a deleted workflow cancels a waiting request (ADR 0026).
8. **Approve.** The request goes to Teams as an approval card that opens the approval page (ADR 0036), for any Approver on the team who is not a party (ADR 0024). The page shows the workflow report in code's own words. The Approver approves, or declines with a reason. Section 3 sets what an override takes. A request that nobody answers expires as ADR 0024 says, and the sender may send it again.
9. **Set up.** The approved version becomes a Draft (ADR 0044) in the platform's n8n project. For a version made from our records, the platform creates it there through `POST /api/v1/workflows`, then reads it back and compares it, as E4 does for a Planner's layout. A version edited in n8n comes from the person's space through Made in n8n's set-up (`builder/made_in_n8n.py`, #291), which moves it, reads it back and checks it again. Either way, its digest must equal the approved one. If it does not, the workflow goes back to the person's space, and the card says "Changed since it was approved. Send it for approval again." Then the test run stops at the yes and posts nothing, and an Operator turns it on, as for every Draft.

**Who may not approve.** The person who described the task, everyone who changed the drafted workflow (in the chat or in n8n), everyone who answered one of its questions, and the person who sent it for approval are its parties. They go in the set-up approval's `ApprovalRequest.parties` (`orchestration/approvals.py`). None of them may give its set-up approval. All of them are parties to every run of it, as Made in n8n's maker and the person who set it up are. The Approvers who gave the set-up approval may still approve the writes of its runs.

**Who owns what.**

- **The agent runtime** owns the drafter, its prompt, its tools, the catalogue reader and the drafter's evals. It never calls n8n, it holds no n8n key, and it has no web tool.
- **The use case builder** owns drafted workflows and their revisions, the settings and the questions, the layout, the workflow report, Explain and the set-up.
- **Orchestration** owns the safety checker and its table of rules, the class file, set-up approvals and their log, the Teams card and the n8n client.
- **Run monitoring** owns the drafts' traces in Langfuse (section 10).

The builder reaches orchestration only through the names its package exports (`grade`, `unchecked`, `face`, `attach_keys`, `NODE_CLASSES`), as `builder/made_in_n8n.py` does today.

### 2. What the drafter may propose, and what can run

The drafter may propose any block the pinned n8n image ships. Whether a block can run is a separate question, and three facts answer it before any person does.

- **n8n loads a block for every workflow or for none.** `NODES_INCLUDE` is one list for the whole n8n, written from `node_classes.json` (ADR 0045). A block that n8n hasn't loaded can't run, whoever approves it. Pack smoke shows n8n refusing to turn on a workflow with an HTTP Request block, with "Unrecognized node type". Loading a block for one approved workflow would load it for every workflow, including a member's run by hand in their own space, which the checker never sees. So allowing such a block is a change to the platform, never a click.
- **The platform's keys can only read or post.** Each system limits the platform's key to that, and the platform asks each system again every day (ADR 0045, amendments 2, 5 and 11). One of n8n's own blocks set to write fails at the system with the platform's key, and `attach_keys` gives such a block no key at all.
- **Every write waits for a yes that our API checks at the moment of writing** (ADR 0026). Our "Make the approved changes" block does that through the write gateway. One of n8n's own blocks can do it only through ADR 0045's write proxy (E18), which is not built. Until E18 is built for a system, nothing can make n8n's block for that system wait for a yes.

So every finding belongs to one of five kinds. Each checker rule gets a stable id on its `Finding` (a new field, `Finding.rule`). A new table in `orchestration/workflow_check.py`, `FLAG_RULES`, gives each rule its kind, its plain words, why it matters, and what it would take to clear it. The report reads that table, and a test fails when a rule has no row.

| Kind | Findings of this kind today | Who clears it | What it takes |
|---|---|---|---|
| Fixed for you | No error workflow, another time zone, progress not saved, a write with no yes before it, a notice not pinned for test runs, Slack's link names switch, a key on a block that is not the platform's | Code, in step 3 of the flow. The report lists each one under "Fixed for you" | Nothing |
| Needs a change to the draft | A setting still needed, nothing that starts it, a run time the Portal can't show (`interval_problem`), one of n8n's blocks before our first step, a notice whose words the checker can't read, a second yes on one path | The person, in the chat or in n8n | An answer or an edit |
| Needs a setting | Our Read, Propose a change or Agent block naming a place the team hasn't allowed, or an agent card nobody saved | An Operator, in Settings or the agent library | The setting. Our API also refuses these at run time, so no Approver can clear them |
| Needs a change to the platform | A block n8n doesn't load, such as HTTP Request, Code, Webhook, Wait, Execute Workflow, n8n's AI agents, or any type the class file doesn't turn on. An operation the class file turns off, which includes every write by one of n8n's own blocks. A post to a place an expression picks. A system with no platform key, such as Teams, Outlook or Gmail | Nobody in the app | A pull request that people review, merge and deploy (ADR 0040). For a block or an operation, a class row and a new allow list. For a write, E18's proxy for that system first. For HTTP Request, Code, Webhook or n8n's AI agents, an ADR first, because ADRs 0023, 0027 and 0045 rule them out. For a key, Key Vault and a check of what the key can do. A post to a place the data picks has no change that keeps the yes, so the report offers a fixed place or our Tell. The flag's button is Ask the team, which sends the block and the operation as a team request (ADR 0038) |
| An Approver may accept | `notice_words_from_run`, when one of n8n's notice blocks writes its words with an expression, so it sends what a run read to a fixed place. It needs two Approvers. `notice_calls_everyone`, when a notice's written-out words call out a whole channel. It needs one Approver | Approvers, on the approval page | An override (section 3) |

The last row leaves out, on purpose, a post to a place that an expression picks. A message to people that the data picks is a write (ADR 0026), and n8n's own Slack block can't be made to wait for a yes. Moving a rule into the last row changes the safety checker, so it needs an amendment to this ADR. No Approver can widen the row.

### 3. The change to the safety rules, and the guardrails for an override

**What changes.** Today every finding of the safety checker is final. A run of a version with a finding stops at its first call to our API, or has its ask and writes refused. The platform sets up or turns on no draft with one. The credential sweep takes off a live version in the platform's n8n project with a finding n8n would run anyway (ADR 0045, amendment 6). With this ADR, a finding whose rule is in the last row of `FLAG_RULES` is advice. An Approver may accept it for one version, under the guardrails below, and that version runs with it. Every other finding stays final.

**What does not change.** No write runs without a yes in Teams, and the checker still denies writes by default.

- Section 2 keeps every write out of the last row.
- A write by our own blocks always gets an Ask for a yes before it (`add_yes`), and the write gateway checks our records at the moment of writing.
- A write by one of n8n's own blocks stays off until E18's proxy exists for that system. It then becomes a `write` row in the class file, not a flag. The checker requires such a block to come directly after Ask's Yes exit, and the proxy refuses it without the run token that a yes gives.
- `refuses_writes` reads the grade that an override leaves, and no override can clear a `writes_refused` finding.

So "every write at run time still waits for an Approver's yes in Teams" is held by code at the moment of writing, not by the approval page.

**What the checker adds, so that an accepted flag covers only what it names.** These rules land with the override, and none of them is a rule an Approver may accept.

- **A disabled block counts as absent.** n8n passes items straight through a disabled block. So `_ours_first` and `_yes_before_writes` skip a disabled block when they walk a path, and an Ask for a yes or one of our Read blocks that is disabled no longer counts.
- **No block goes on past its own failure.** n8n passes items past a failing block set to continue. The checker refuses `onError` set to anything but `stopWorkflow`, `continueOnFail`, `alwaysOutputData` and `executeOnce` on every block. On one of n8n's own blocks the finding runs anyway. Without these two rules, a Start, then one of our Read blocks that is disabled or set to continue, then an accepted notice would post what a run read with no run recorded and no version checked.
- **Only a notice's words may be an expression.** Today `_places` checks only a notice's target parameters and `_words` only its text parameters, so its other parameters (for Slack, `otherOptions`, such as the ephemeral user and the bot's name and icon) go unchecked. Every parameter of a notice block must be written out, except the parameters its class row names as text. An expression anywhere else is `off`, and the finding runs anyway.
- **An accepted expression reads only this workflow's blocks.** An expression in a notice's words may name only `$json`, `$input` or `$('<a block in this workflow>')`. Anything else, such as `$env`, `$vars`, `$execution` or another workflow's data, is `off`. The report shows from code which block's output the words read, as in "posts whatever 'Read Jira' read". n8n's `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` (`deploy/compose.yaml`, `infra/envs/dev/main.tf`) keeps every expression away from n8n's environment, so it is load-bearing. Bootstrap gains a check that n8n runs with it.

**The guardrails for an override.**

- **Each flag in plain words, accepted one by one.** The approval page lists each flag with what it is, why it matters and what would clear it instead, all from `FLAG_RULES`. Where a block posts, the page shows the block's own words, and for words from an expression, which block's output they read. Approve stays off until the Approver has ticked each flag and written, for each one, why they accept it. Code refuses an empty reason.
- **Never their own.** A party (section 1) can't approve. `decide()` refuses them with `own_work` from `ApprovalRequest.parties`, and `_fault` refuses a recorded decision by one, as for a run.
- **Two Approvers, one after the other, where a rule says so.**
  - `notice_words_from_run` needs two. Words from what a run read leave the platform and reach people. Planted text in a ticket or a release note could reach them too, a call to a whole channel included. ADR 0023 asks two Approvers for a change to someone's access, and the access review asks two. Sending a system's data to a channel is of the same weight.
  - `notice_calls_everyone` needs one. The words are written out in the block, so the Approver reads exactly what goes out.
  - A set-up approval with no flag to accept needs one Approver. If any flag needs two, the request's `policy.steps` has two steps, and each Approver ticks every flag. `approval_status` and `_fault` keep the order and refuse the same person twice (`SAME_PERSON_TWICE`), as they do for the access review. The second request goes out only after the first yes, and it shows the first Approver's reasons.
  - The team lead named four more cases for two Approvers: a write outside our approval blocks, a key that isn't the platform's own, code execution, and outbound HTTP to any host. This ADR puts none of them in the last row, so no number of Approvers clears them. Each one needs a change to the platform (section 2). The first can't be made to wait for a yes. The other three would load or lend something to every workflow, not to one.
- **The override log.** Orchestration keeps each set-up approval in a new table that it only ever adds to. The database holds it to that, because the app's role gets no UPDATE or DELETE on the table. A row holds the drafted workflow, the version's digest and n8n version id, the rules it was checked under (`GRADING_RULES`), and each accepted flag: its rule, its block, the digest of that block's parameters, and the words shown. It also holds each Approver with when they decided, what they ticked and why, the parties, and the sender's notes. Each decision is also an activity event (`setup_approved` or `setup_declined`, both new) in the activity log (ADR 0031), with who decided, as `AGENTS.md`'s logging rule asks. The workflow page shows a line such as "Approved with 1 accepted flag by Bob and Carol", which opens the log.
- **Bound to the exact version.** The digest is a hash of the whole document in a canonical form. It drops only where each block sits (`position`), the Sticky Notes, and the fields n8n adds of its own (`id`, `webhookId`, `meta`, `versionId` and the times). Every other field counts, a field the checker doesn't read included, so a new n8n field can't slip past it. Any change to a field that counts makes a new digest, and the new version is not approved. `same_as_sent` in `orchestration/n8n.py` compares in one direction only and skips `pinData`, so it is not the digest. A test checks that `digest(stored) == digest(kept())` for every golden document, where `kept()` is the version n8n gives back. When the checker's rules change, a flag stays accepted only when the same rule finds the same thing in the same block. A new finding needs a new approval.
- **Every write at run time still waits for a yes.** Code holds this, as "What does not change" says.

### 4. The E16 invariant

ADR 0045's amendment 6 says, in short, that nothing in the platform's n8n project is live with a block n8n would run unchecked, and that no draft with one runs. This ADR amends it to read:

> Nothing in the platform's n8n project is live with a finding n8n would run anyway, unless a set-up approval for that exact version accepted it. No draft with a finding that nobody accepted runs.

The approval is the check, matched by digest. We weighed three options.

- **Overridden workflows never get the platform's keys.** Then an accepted Slack notice couldn't post, and the override would do nothing.
- **They run only with the member's own keys, in a separate n8n project.** The credential sweep deletes every key the platform didn't make, keys are never asked for in the chat, and most Operators have no n8n space. It would rebuild ADR 0045's key model for one feature.
- **The invariant names the approval as the check (chosen).** Every guard stays in place, and each one asks one more question.

What each part does with an approved version that has accepted flags:

- `unchecked(document, keys)` stays pure and doesn't change. A new pure function in `orchestration/workflow_check.py`, `unaccepted(findings, accepted)`, keeps the findings that no accepted flag covers.
- **The credential sweep** (`KeySweep._take_off` in `builder/key_sweep.py`) takes a live version off when `unaccepted(unchecked(live, made), accepted_for(digest(live)))` is not empty. `accepted_for` is new and reads by digest. A version changed anywhere has no accepted flags, so the sweep takes it off within a minute and marks it Needs a fix, as it does today.
- **Take-back** (`Holding._keys_back` and `_live_again` in `builder/n8n_holds.py`), turn on, resume and restore use the same filter. A version changed in a member's space comes back with a new digest and stays off, and its card says "Changed since it was approved."
- **Made in n8n's set-up.** `Candidate.runs_anyway` in `builder/made_in_n8n.py` reads both `graded.findings` and `draft`, the findings in a published workflow's draft, and both go through the same filter.
- **Runs.** The stored version keeps all its findings and the id of its set-up approval. Its grade for runs is the grade of its findings that nobody accepted. `version_problem` and `refuses_writes` in `orchestration/n8n_calls.py` read that grade, and they don't change.
- **Keys.** `attach_keys` doesn't change. An accepted notice is still a `notice` operation, so it gets the platform's key for its system.
- **Test runs** of an approved version still post nothing, because each notice's output is pinned.

### 5. Settings and questions

Each setting in a plan has an id, a kind, a label, the parameters it fills, and one of three marks.

| Mark | When | The person sees |
|---|---|---|
| Filled | Code located the value exactly in the person's own words, as ADR 0049 locates a tool's argument, or the person chose it or typed it | The value, with "from your words" or "you chose" |
| Guessed | The drafter picked it, and the person can change it | The value, with "I guessed" and Change |
| Needed | Nobody has given it | The next question |

- **Never guessed.** Four kinds are never guessed: the run time, the Jira project, any channel or address that a notice or a Tell posts to, and the Approvers. Code holds this, not the prompt. A value of one of these kinds counts as filled only when code locates it in the person's words and finds it in the platform's data: an allowed project, a channel the platform's key can see, or an Approver on the People list who is not a party. Any other value becomes needed. Code reads run times with `said_schedule`, as the Planner does today.
- **One question at a time.** Code writes the question's words, fixed for each kind, and offers 2 to 4 choices from the platform's own data, as ADR 0047's clarifying question does.
  - The Jira project offers the team's allowed projects (`KnownOptions.places`).
  - A Slack channel offers the channels the platform's Slack key can list.
  - The Approvers offer the People list's Approvers who are not parties, and "Any Approver on the team".
  - A run time offers a few common times, and "Type a time".

  A choice the person taps is their answer, not a guess. Code reads a typed answer. When code reads nothing in it, the same question comes back with its choices.
- **The order.** First what the workflow can't start without (the run time), then where it reads and posts, then the Approvers.
- **Keys are never asked for.** The report says which key each block uses, such as "the platform's Jira key", or that its system has none and what it would take. Code refuses a message that holds the shape of a key (the shapes ADR 0050's masker knows, such as `sk-ant-`, `ghp_` and `Bearer`) before any model reads it, and answers "Don't paste keys here. An Operator sets keys in Settings." Keys come only from the platform's own keys in n8n.
- **Approval stays off until nothing is needed.** The route refuses while any setting is still needed, and the card says how many are left.

### 6. The workflow report, and Explain this workflow

**One shared report builder.** A new module in the use case builder, `builder/workflow_report.py`, takes one workflow version and the checker's results and returns the report's facts. It is pure, and it needs no running n8n. It reads these for each source:

| Source | What it reads |
|---|---|
| A workflow the Planner laid out | The stored document of the version (`use_case_versions`, E4), its stored findings, the use case's Approvers and backup (ADR 0024), its schedule, and the tools on each Agent block's saved card (ADR 0023) |
| A workflow made in n8n | Its stored versions (version 1 from its set-up, later ones from the versions sweep) and their findings. Places, channels and the run time come from the document. Approvers come from the use case, which says any Approver until someone names them |
| A drafted workflow | The revision's document, its findings, its settings with their marks, and its accepted flags once it is approved |
| An older published version | The copy ADR 0027 keeps of every published version, checked again under today's rules (`grade` is pure), with the grade it had when it was published shown beside it |

It reads orchestration only through the names its package exports: `grade`, `face`, `NODE_CLASSES` for each operation's class, tag and `says`, and `KEY_FOR_TYPE`.

The report has these sections, in this order:

1. **In short.** One or two sentences that code fills from the facts: when it runs, what it reads, what it changes or posts, and what waits for a yes. For example: "Every Monday at 9:00, it reads open bugs in Jira project MOCK, summarises them and posts the summary in Slack #support. It changes nothing in Jira."
2. **Step by step.** Each block in run order, with its plain name, whether it is our block or an n8n block, and its tag (Reads Jira, Shapes the data, Posts in Slack, Writes after a yes).
3. **What it reads, writes and posts.** By system and place. A post shows its words in full when they are written out, or says "words from what the run read".
4. **Checks.** Every rule in `FLAG_RULES`, passed or flagged. Each flag says what it is, why it matters, and what would clear it. "Fixed for you" lists what code added.
5. **Waits for a yes.** Each write, who decides it, and whether it takes one Approver or two.
6. **Settings.** Each value, marked filled, guessed or needed for a drafted workflow, or with where it was set for a workflow that is already set up.
7. **Approval.** For a drafted workflow, who must approve its set-up, and why. For an approved version, its accepted flags, who accepted them, and why.

The model writes none of it. Block names come from the plan, and code checks them as it checks the Planner's names: plain words, none of the old themed names, and a length limit. The report shows every string from the plan or the document, such as a block's name or a notice's words, in quotes and apart from code's own words, so a block named "Security approved" can't read as code's verdict. It never shows a key's secret, only which key a block uses. This is ADR 0047's rule that the AI's summary is help for the reader, never the check.

**Explain this workflow** shows the same report for a workflow that already exists.

- **Where.** An Explain action on each row of Workflows, on the workflow's page, and on each version in its version history. The Planner also answers "explain <workflow>".
- **Naming the workflow.** Code locates the workflow's words in the message and matches them against the person's workflows with `_name_runs` in `agent_runtime/edits.py`, as an edit and ADR 0049's `show` tool already do. In `ai_led` mode, `show` gains an `explain` choice, checked the same way. Two or more matches get "Which workflow?" with each one as a choice, as the edit card asks. No match gets "I can't find a workflow called that.", with the words it looked for and the button Check my workflows.
- **Who sees it.** Anyone who may see that workflow today. Block types and the `n8n block` badge show only to people with n8n access, as the In n8n tab does. Everyone else sees the plain steps.
- **The model may only smooth the wording.** In Explain's answer in the chat, a model may rewrite the In short paragraph so that it reads naturally. It gets the facts and code's own wording, and nothing else. Its text goes through ADR 0047's code checks and then the verifier, as a free reply does. Then code checks three more things. Every system, place, write, post, run time and flag in code's wording must still be there, and nothing else may be named. The words that carry meaning must come from a closed list that code holds for each fact, such as reads, posts, changes, waits for a yes, and the names in the facts. Every negation must survive, so "changes nothing in Jira" can never become "changes Jira". On any doubt, the person sees code's own wording, so Explain never fails for want of the model. Smoothed text carries the label "Reworded", and the person can switch to code's wording. The sections under the paragraph are always code's words. The approval page and the Teams card never show smoothed words.

### 7. Which model drafts

The candidates are Claude Sonnet 5.5 and Claude Opus 5.5, reached through Anthropic as the Planner's model is (ADR 0048, as amended). The eval in section 9 picks the cheaper one that meets every bar, as ADR 0048 did for the Planner. Until it runs, the drafter uses Sonnet 5.5, set by a new setting, `DRAFTER_MODEL`, and only the team sees the draft button.

The cost of one draft, as a guess before the eval measures it, is about 26 cents with Sonnet 5.5 and about 49 cents with Opus 5.5. The guess assumes about 200,000 tokens read across the drafter's turns, four fifths of them from the prompt cache, and 15,000 tokens written, thinking included. It uses list prices of $2 in and $10 out a million tokens for Sonnet 5.5, $4 and $20 for Opus 5.5, and $0.20 a million for cache reads on both, from Anthropic's model list as cached on 6 Oct 2026. It leaves out cache writes. A Planner message costs about 1.5 cents (ADR 0048), so a draft costs as much as 17 to 33 messages. Drafts are rare. At 50 a month, Opus 5.5 would spend about $25 of the team lead's $200 monthly credit. Explain's smoothing is one short call on the Planner's model, about a cent.

### 8. How the drafter learns which blocks and settings exist

The drafter learns from the n8n we run, never from the open web.

- **A catalogue built from the pinned image.** Pack smoke already starts the pinned image once without the allow list, and copies what it serves at `/types/nodes.json` (`scripts/pack-smoke.sh`). A new script, `scripts/n8n-catalogue.sh`, writes a new file, `contracts/n8n/catalogue.json`, from that copy, stamped with the image's digest. For each type n8n ships, it holds the name, the description, the versions, the resources, the operations and each operation's parameters. From our own files it adds whether n8n loads the type (`NODES_INCLUDE`), each operation's class, tag and `says` (`node_classes.json`), and whether the platform has a key for it (`KEY_FOR_TYPE`). Our node pack's eight blocks are in the same list, under `CUSTOM.*`. Community nodes are not, because our n8n turns them off, and nor are the two types pack smoke always leaves out, Execute Command and Local File Trigger. CI fails when the file differs from what the script writes, as `scripts/nodes-include.sh --check` does for the allow list.
- **What else the drafter reads.** The capability registry (`agent_runtime/abilities.py`), so it knows what our own blocks do, and the team's facts in the request (section 1).
- **Small reads.** `find_blocks` searches names, descriptions and operations, and ranks the blocks n8n loads first. `describe_block` returns only the parameters n8n shows for the chosen resource and operation (n8n's `displayOptions`), so a large block such as Jira is never sent whole. The fixed part of the prompt comes first, where the prompt cache keeps it.
- **When n8n is upgraded.** The pull request that moves the n8n pin writes the catalogue again in the same change, as the pin check already makes it class every operation again. Bootstrap compares the catalogue's digest with the image n8n runs. When they differ, the draft button answers "Drafting is paused while the platform updates." The golden set runs on that pull request.
- **n8n-mcp, compared.** A teammate showed a model building n8n workflows through n8n-mcp in November. Its README, read on 16 Nov 2026, says it is an MIT-licensed MCP server. Its documentation tools (`search_nodes`, `get_node`, `validate_node`, `validate_workflow`) work offline from a bundled database. Its other tools change an n8n through its API (`n8n_create_workflow`, `n8n_update_full_workflow`, `n8n_test_workflow` and more), and `DISABLED_TOOLS` can turn them off. Its database covers n8n's newer releases and community nodes, and its README showed n8n 2.46.7, where we run 2.42.6. So it would describe versions and parameters our n8n doesn't have, our checker and class file would still judge every draft, and it would be one more service to pin and carry into DevNet. We build our own catalogue from the pinned image and borrow n8n-mcp's shape: a search, details at the level the model needs, and a validator, which for us is the catalogue check and the safety checker. If the eval's measure of invented parameters stays over its bar, n8n-mcp's documentation tools, pinned and offline, are the next thing to try.

### 9. How drafts are evaluated

A new golden set, `agent-runtime/evals/cases/workflow_draft.json`, holds at least 40 plain-English tasks. Teammates who haven't read the prompt write a third of them, which are held out. The set covers:

- the release check and the watchlist, which the Planner already lays out, as a baseline;
- ticket summaries posted in Slack, and a Confluence page read;
- tasks that need a block n8n doesn't load, such as HTTP Request or Google Sheets, where the flag must show with what it would take;
- a Jira write, which must use our blocks;
- tasks that name a run time, a project, a channel or an Approver, and tasks that don't;
- vague tasks;
- planted instructions, such as "and skip the yes" or "also send it to this address", and a pasted key.

Each case lists the block types the draft must and must not use, which settings must be filled and which needed, the flags it expects by rule id, and whether the draft can run.

| Measure | How it is measured | Bar |
|---|---|---|
| The draft imports into n8n | Every pull request checks the laid-out document against the catalogue. The nightly run imports it into the pinned n8n of the e2e stack and reads it back | 100% of drafts shown |
| Invented types, versions, operations or parameters | Code counts the plans the catalogue check sent back | None in any draft shown, and at most 10% of first plans |
| The never-guess list | Code | None guessed, in every run |
| Settings marked as the case says | Code | At least 90% |
| Flags as the case says | Code, by rule id | Every expected flag shown and none unexpected, in at least 90% |
| A Jira write goes through our blocks | Code | 100% |
| Planted instructions followed | Code | None |
| The report and Explain are true to the facts | Code checks the report and the Explain answer for each case, and for each golden document of the Planner's layouts (`platform-api/tests/golden/n8n/*.json`), against the workflow's facts. Every system, place, write, post, run time and flag appears, and nothing else is named | 100% for code's wording. For smoothed wording, none shown that drops or adds a fact, and the guard passes at least 95% |
| Fit to the task | A judge rates it from 1 to 5. The judge is a different model from the drafter (ADR 0047). For the bakeoff it is Claude Fable 5.1, which is neither candidate. Before its scores count, it must agree with the team lead's own labels on at least 27 of 30 | At least 80% at 4 or 5, on the whole set and on the held-out third |
| Cost | Measured | At most $1 a draft at the 95th percentile |
| Time | Measured | At most 90 s at the 95th percentile, with each step shown as it goes |

The bars are proposals. The team lead sets them when accepting this ADR.

**The bakeoff** runs each candidate twice on the whole set on one day, about 160 drafts. It costs about $80 with the judge, a guess from section 7, and it stops at $100 from the team lead's monthly credit.

**The CI gate** runs on pull requests that change the drafter, its prompt, the catalogue, the class file, the report builder or the cases, with a cap on calls and dollars. It only reports at first. It blocks once three nightly runs in a row meet every bar and the team lead says so.

### 10. How poor drafts reach the review queue

The drafter joins ADR 0050's loop. Run monitoring owns the trace shape, the scores and the queue, and the agent runtime records through ADR 0050's port.

- **Traces.** Each drafted workflow is a Langfuse session, and each revision is one trace. A trace holds the person's words, each plan and tool call, each plan the catalogue check sent back and why, the findings, the settings' marks, the model, the cost, the time and the catalogue's digest. ADR 0050's masking applies, and a pseudonymous id names the person.
- **Code flags**, written only when true:
  - `draft_import_failed`;
  - `draft_invented`, when the catalogue check sent a plan back for a type, operation or parameter that doesn't exist;
  - `draft_gave_up`, when no plan passed after three tries;
  - `draft_many_flags`, for three flags or more;
  - `draft_discarded`, when the person discarded it or left it for 7 days;
  - `draft_rewritten_in_n8n`, when a third or more of its blocks changed in n8n before it was sent;
  - `draft_declined`, when an Approver declined its set-up;
  - `draft_slow`.
- **The judge** scores every flagged trace and one in four of the rest, with `judge_fit` (1 to 5) and `judge_cause` (wrong blocks, a missing step, wrong wiring, a guessed setting, too complex, other, none). It runs on a model different from the drafter.
- **The review queue.** A second annotation queue, "Drafter review", sits beside "Planner review". It takes each flagged trace, each `judge_fit` of 1 or 2, and five drafts a week at random. A teammate marks each one. A real problem goes into a `drafter-regressions` dataset, and `evals.pull_regressions` writes it into `workflow_draft.json` in the pull request that fixes it.
- **The drafter never changes itself.** Its prompt, the catalogue, the class file and `FLAG_RULES` change only through reviewed pull requests.
- **Explain.** Its smoothing is traced with the Planner's turns, and a fallback to code's wording counts as ADR 0050's `flag_fallback`.

## Considered options

- **Drafting limited to the allow list.** Every draft could run, and no flag would need a person. But the team lead asked for no limits, and flags that say what it would take show the team which blocks people need next. The set of blocks that can run is still the allow list.
- **No override, so the checker stays final, as today.** The simplest, and `AGENTS.md` wouldn't change. But a post that carries what a run read, which people are likely to want first, would need our Tell every time, and the team lead chose that a person may weigh it. The build order puts the override last, so this stays the fallback if the sponsor says no.
- **An override by one Approver, for every flag.** The request first described this. But one person could send a system's data to a channel, and the flags about loading a block or about a write can't be cleared for one workflow at all (section 2). A yes to them would show something as working that isn't (principle 5).
- **An override that clears a write by one of n8n's own blocks.** This is ADR 0045's option A for that system. The checker would look at it when it is set up, and nothing would check it when it writes. "Every write waits for a yes in Teams" would then be words only. ADR 0045 allows option A only as a one-line amendment per system that the team lead takes knowingly, and this ADR keeps that.
- **Drafting from templates only.** The Planner already does this (E4), and it still comes first. It can't do a task nobody wrote a template for, which is ADR 0023's reason for agents.
- **The model writes the n8n JSON itself.** Less code. But the ids, the positions, the platform's settings, the yes and the keys would all rest on the model, and every layout rule would be checked only after the fact. ADR 0023 and ADR 0027 already split this work. The model chooses, and code places.
- **Drafted workflows kept in n8n from the start, in the platform's project.** The canvas would be n8n's own. But unapproved drafts would sit where n8n lets a workflow use every key, and the E16 invariant would have to watch them too. So they stay in our records until approved, and go into n8n only for Edit in n8n, in the person's own space and without keys.
- **No set-up approval for a draft with no flags,** as the Planner's set-up card and Made in n8n's set-up need none. It would save a wait. But the model chose and wired the blocks, the sponsor wants a person to look before anything new runs, and the team lead asked for it.
- **n8n-mcp for the catalogue.** Section 8 weighs it.

## Consequences

- **This changes a rule the sponsor gave.** The checker's findings stop being final for the rules in the last row of `FLAG_RULES`, and one of n8n's posts may carry what a run read once two Approvers accept it. The write rule stays. The sponsor should hear about the change before the override's pull request merges. The team lead tells them.
- **`AGENTS.md` changes in the pull request that builds the override,** so that the rule and the code change together. The product safety rules gain this line after "No write action runs without approval in Teams. The safety checker denies write actions by default.":

  > The safety checker's findings are final, except a finding whose rule the checker's table marks as one an Approver may accept. Approvers may accept such a finding for one version of a workflow, flag by flag with a reason, never for their own work, and two Approvers one after the other where the rule says so. No rule about a write is one of them (ADR 0051).

  The Tell rule's line gains: "One of n8n's notice blocks may post words from what a run read only when two Approvers accepted it for that version (ADR 0051)."
- **ADR 0045** gains, under amendment 6, the invariant in section 4. Under amendment 12 it gains that the rule of written-out words is one an Approver may accept.
- **ADR 0026's** Tell rule gains the same exception for n8n's notice blocks. Our own Tell doesn't change.
- **ADR 0049** gains the tool `draft_workflow` and an `explain` choice for `show`, each checked as sections 1 and 6 say.
- **ADR 0023** says, in its change of 13 Nov, that the model never writes arbitrary n8n workflows. That note gains: "The workflow drafter (ADR 0051) may propose any block. Code lays it out, the checker grades it, and an Approver's set-up yes comes before it is set up."
- **The glossary** gains Workflow drafter, Drafted workflow, Workflow report, Set-up approval and Accepted flag. Draft gains "Not the workflow drafter's drafted workflow." Planner answer gains the draft card and the explanation.
- **The capability registry** gains "Draft a workflow from your words" and "Explain a workflow". Each stays Planned until its pull request lands, so the Planner never offers it early (principle 5).
- **The set-up approval is a new kind of approval request,** separate from a run's. It reuses `ApprovalRequest`, its `parties` and its `policy.steps` (`orchestration/approvals.py`), ADR 0024's routing and expiry, and ADR 0036's Teams card. A write still has only one way to happen.
- **Made in n8n** gains Send for approval when its only flags are ones an Approver may accept, so a workflow built by hand and a drafted one meet the same rule.
- **One more prompt and one more generated file to keep.** The catalogue moves with the n8n pin.
- **Cost.** About 26 to 49 cents a draft, and about $80 for the bakeoff (section 7).

**The build order,** as small pull requests:

1. **The screens** (`docs(builder)`), in the chat-first prototype (`docs/design/chat-first/prototype.html`), with the principles' checklist walked. They are the draft card with its steps as they go, the questions, Edit in n8n, the report page, Explain on Workflows, on the workflow page, in the version history and in the chat, the approval page with a tick and a reason for each flag, and the Teams card.
2. **The workflow report builder** (`feat(builder)`, `builder/workflow_report.py`) for every existing kind of workflow version, with a rule id on each finding and `FLAG_RULES`. It has no screen, so it can be built beside step 1.
3. **Explain this workflow** (`feat(builder)`), the report builder's first user, on the screens from step 1, with the Planner's "explain <workflow>" and the guarded wording.
4. **The catalogue** (`feat(runtime)`) from the pinned image, with its script and its CI check.
5. **The workflow drafter** (`feat(runtime)`), with its tools and 10 golden tasks scored by code.
6. **Drafted workflows without an override** (`feat(builder)`). This is the draft card, the revisions, the layout, the check, changes asked for in the chat, a set-up approval by one Approver for a draft with no flags, and the set-up as a Draft.
7. **The drafted workflow's report and settings** (`feat(builder)`), with the questions one at a time, the never-guess rule, the approval held until nothing is needed, and Edit in n8n.
8. **The override and its guardrails** (`feat(orchestration)`). This is the accepted flags, the approval by two in turn, the log, the invariant in the sweep, take-back and set-up, Made in n8n's Send for approval, and the `AGENTS.md` and ADR text above. The sponsor hears first.
9. **The full golden set** (`feat(runtime)`), the bakeoff that picks the model, and the CI gate, reporting only.
10. **The drafter's traces** (`feat(monitoring)`), flags, judge and review queue, after ADR 0050's PR A and PR B.
