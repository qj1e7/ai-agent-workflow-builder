---
status: accepted
---

# A workflow drafter may propose any n8n block, code explains every workflow, and an Approver's yes sets up a flagged workflow

On 16 Nov 2026 the team lead asked for a new feature, with this ADR first. A person describes a task in plain English, and an AI agent drafts a complete n8n workflow for it, with its blocks, wiring and settings. The person reviews it, edits it in n8n or asks for changes, and sends it for approval. The drafter may use any block n8n has, not only our node pack and the allow list. The safety checker checks every draft the way it checks a workflow made by hand in n8n (ENGINE-PLAN E15 and E16). The same day the team lead added "Explain this workflow", which shows the draft's report for any workflow. Later that day they decided what an Approver's yes may let through, in their words: "i just need it simply to get approved by approver for workflow that flagged by the safety checker agent. as long as approver approved, anything can go through". They then kept two Approvers for a workflow that changes someone's access, and accepted the exceptions in section 2.

`AGENTS.md` says that no write action runs without approval in Teams, that the safety checker denies write actions by default, and that no safety rule is weakened without an ADR. This ADR changes all three. The first rule came from the sponsor. It amends ADR 0023, ADR 0026, ADR 0027, ADR 0045 and ADR 0049, and builds on ADR 0044, ADR 0047 and [ADR 0050](0050-trace-the-planner-in-self-hosted-langfuse-and-people-decide-what-it-learns.md).

The decision in one paragraph. The workflow drafter, in the agent runtime, writes a plan that may use any block n8n ships. Code lays the plan out as an n8n workflow, adds what the platform always adds, and runs the safety checker. Code, never the model, writes the report. It says what the workflow does, what it reads, writes and posts, every flag, and every setting. The person answers the settings only they know, one question at a time. The checker's findings are advice. The Approver sees every flag in plain words and ticks each one, and one Approver who is not a party approves that exact version. A workflow that changes someone's access needs two Approvers, one after the other, as the sponsor's access review does. It then runs with everything it was flagged for. A write through our own blocks still waits for a yes in Teams on each run. A write by one of n8n's own blocks, or by HTTP Request or Code, has no yes of its own. The approval at set-up is its approval. To make that possible, n8n loads all its built-in blocks, Operators add write keys in Settings that go only on the blocks of an approved version, and HTTP Request and Code reach what n8n can reach. The team lead accepted a short list of exceptions, mostly blocks that would open the platform itself, such as Execute Command. Code waits for a spike that shows it can't read n8n's secrets.

## Words used here

- **Workflow drafter.** The agent that drafts an n8n workflow from a person's words.
- **Drafted workflow.** What the drafter wrote, with every change made to it, before it is set up. Once set up, it is a Draft in the glossary's sense (ADR 0044) until someone turns it on. The chat may call both a draft. Code and docs keep the two apart.
- **Workflow report.** The plain-words account that code builds of one version of any workflow. The draft card, the approval page and Explain all show it.
- **Set-up approval.** An Approver's yes to set up one version of a drafted workflow.
- **Accepted flag.** A finding that an Approver ticked in a set-up approval. A set-up approval with at least one accepted flag is an **override**.
- **Write key.** A key that can change data in a system. An Operator adds it in Settings, and it goes only on a block that a set-up approval names it for.

## Decision

### 1. The flow, and who owns each part

1. **Describe.** An Operator types on Home, and the Planner answers as it does today. When the Planner can lay out the whole request itself (E4's layouts), its set-up card wins. It is instant, it is tested, and it needs no set-up approval. When the Planner's answer is a can't, or a part card with a part that needs a block or a system it can't reach, the answer gains the button "Draft it as an n8n workflow". A person can also ask for a draft in words ("draft an n8n workflow that ..."). In `ai_led` mode (ADR 0049) that is one more tool, `draft_workflow`, whose one argument is text that code locates in the message, as `set_up_workflow`'s is. The drafter never starts without the tap or the words, because one draft costs as much as 17 to 33 Planner messages (section 7). Only Operators may draft, because only they set workflows up (ADR 0030).
2. **Draft.** The builder sends the person's words, unchanged, to a new agent runtime route, `POST /v1/workflows/draft`, beside `/v1/cards/draft`. It also sends the team's facts that the drafter may use: the allowed Jira projects, Confluence pages and repositories, the saved agent cards, and the names and systems of the write keys. It sends no Approver's name and no secret. The drafter works through three tools: `find_blocks(words)`, `describe_block(type, version, resource, operation)` and `submit_plan(plan)`. Code checks each plan against the catalogue (section 8). Every type, version, resource, operation and parameter must exist, each value must fit its parameter, and each wire must join blocks and exits that exist. A plan that writes to Jira or Confluence with n8n's own block goes back with "Use our Propose a change, Ask for a yes and Make the approved changes blocks", because our blocks give that write a yes on each run. That is the drafter's rule, not a limit on people. A person who puts such a block in through Edit in n8n gets a flag that the Approver may accept. A plan that fails goes back to the model with the reasons, at most three times. After that the person sees "I couldn't draft that", with Ask the team (ADR 0038), and nothing is shown as working. Neither candidate model accepts a forced tool choice, so the tools are strict, and code ends a turn that calls no tool.
3. **Lay out and check.** A plan holds blocks (name, type, version, parameters), wires (from, exit, to) and settings (section 5). A setting appears in the parameters as a placeholder, never as a guessed value. `builder/layout.py` gains `lay_out_drafted(plan, values)`, built on the `_Canvas` it already has (`node`, `n8n_block`, `link`, `document`, and `block_id` for the ids). It adds what every layout adds and the model never writes: our Start from the Portal beside the schedule, so that Run now and test runs can start it, our new Record the run block after each trigger (section 3), the Sticky Note, the team time zone, our error workflow, saved progress, retries on our blocks, and pinned output on every block that could change or send something, so that a test run changes and sends nothing (section 4). Then `add_yes` puts an Ask for a yes before each write by our blocks, `attach_keys` puts on the keys, and `workflow_check.grade` grades the result with the team's `KnownOptions`, as Made in n8n's set-up does. The builder stores the result as a new revision with its digest (section 3).
4. **Report.** Code builds the workflow report from the revision (section 6). The chat shows the draft card, with its steps, its flags, the questions left, and the full report one tap away.
5. **Questions.** The card asks for each setting that is still needed, one short question at a time, with choices from the platform's own data (section 5).
6. **Edit.** The person asks for a change in the chat, such as "post at 9 instead" or "drop the Slack step". The drafter gets the current plan and those words, and returns a whole new plan. A setting with the same id and kind keeps its value unless the words change it. An Operator with n8n access may press Edit in n8n instead. The platform puts the document in their own n8n space without its keys, as Open in n8n does (ADR 0045, amendment 3), and they change it there. Pressing Done in n8n, on the card, reads it back as a new revision and checks it again. A value they typed in n8n counts as filled by them, once it passes the same check as in the chat (section 5), so a channel must be one the platform's key can see. A placeholder they left counts as still needed. The drafter can still change it after that, because code reads the document back into a plan.
7. **Send for approval.** This works only when no setting is still needed. Until then, the card shows "Answer 2 questions first" in place of the button, and the route answers 409. The sender may add a note to each flag. A new revision cancels a set-up approval that is still waiting, as a deleted workflow cancels a waiting request (ADR 0026).
8. **Approve.** The request goes to Teams as an approval card that opens the approval page (ADR 0036), for any Approver on the team who is not a party (ADR 0024). One Approver decides, or two, one after the other, when the workflow changes someone's access (section 3). The page shows the workflow report in code's own words. The Approver approves, or declines with a reason. Section 3 sets what an approval of a flagged version takes. A request that nobody answers expires as ADR 0024 says, and the sender may send it again.
9. **Set up.** The approved version becomes a Draft (ADR 0044) in the platform's n8n project. For a version made from our records, the platform creates it there through `POST /api/v1/workflows`, then reads it back and compares it, as E4 does for a Planner's layout. A version edited in n8n comes from the person's space through Made in n8n's set-up (`builder/made_in_n8n.py`, #291), which moves it, reads it back and checks it again. Either way, its digest must equal the approved one. If it does not, the workflow goes back to the person's space, and the card says "Changed since it was approved. Send it for approval again." Then the test run stops at our yes, changes nothing and sends nothing, and an Operator turns it on, as for every Draft.

**Who may not approve.** The person who described the task, everyone who changed the drafted workflow (in the chat or in n8n), everyone who answered one of its questions, and the person who sent it for approval are its parties. They go in the set-up approval's `ApprovalRequest.parties` (`orchestration/approvals.py`). None of them may give its set-up approval. All of them are parties to every run of it, as Made in n8n's maker and the person who set it up are. The Approver who gave the set-up approval may still approve the writes that its runs make through our blocks.

**Who owns what.**

- **The agent runtime** owns the drafter, its prompt, its tools, the catalogue reader and the drafter's evals. It never calls n8n, it holds no n8n key, and it has no web tool.
- **The use case builder** owns drafted workflows and their revisions, the settings and the questions, the layout, the workflow report, Explain and the set-up.
- **Orchestration** owns the safety checker and its table of rules, the class file, set-up approvals and their log, write keys, the Teams card and the n8n client.
- **Run monitoring** owns the drafts' traces in Langfuse (section 10).

The builder reaches orchestration only through the names its package exports (`grade`, `unchecked`, `face`, `attach_keys`, `NODE_CLASSES`), as `builder/made_in_n8n.py` does today.

### 2. What the drafter may propose, and what the Approver decides

The drafter may propose any block the pinned n8n image ships. The checker grades the draft, and every finding is a flag in the report. Each checker rule gets a stable id on its `Finding` (a new field, `Finding.rule`). A new table in `orchestration/workflow_check.py`, `FLAG_RULES`, gives each rule its kind, its plain words, why it matters, and, for a rule the Approver may accept, what the Approver agrees to by accepting it. The report reads that table, and a test fails when a rule has no row.

| Kind | Findings of this kind | Who clears it |
|---|---|---|
| Fixed for you | No error workflow, another time zone, progress not saved, a write by our blocks with no yes before it, no Record the run after a trigger, a block that could change or send something without pinned output for test runs, keys on blocks, redirects on an HTTP Request block that names a generic write key, and, on our own blocks, a disabled mark or the fields that skip a failure (`onError`, `continueOnFail`, `alwaysOutputData`, `executeOnce`) | Code, in step 3 of the flow. The report lists each one under "Fixed for you" |
| Needs an answer | A setting still needed, nothing that starts it, a document the checker can't read | The person, in the chat or in n8n |
| Needs a setting | Our Read, Propose a change or Agent block naming a place the team hasn't allowed, or an agent card nobody saved | An Operator, in Settings or the agent library. Our API refuses these at run time whatever an approval says, so an Approver can't clear them |
| Can't run on this platform | Execute Command, Local File Trigger and community nodes, which n8n doesn't load (section 2, "All of n8n's built-in blocks load"). The sub-workflow blocks, until a version's digest covers the workflows it calls (section 2, "Sub-workflows"). The n8n block, because Settings refuses a key to n8n's own API (section 2, "Write keys"). Microsoft Teams' block, which posts only with a person's own sign-in (ADR 0045, amendment 1). Until spike P9 passes, the blocks that run code and the blocks that read or write n8n's disk, as section 2 names them | Nobody in the app. A new ADR, or spike P9 |
| An Approver may accept | Every other finding. Among them: a write by one of n8n's own blocks, with a write key; HTTP Request to any address; Code, after P9; a post whose place an expression picks, whose words come from what a run read, or that calls out a whole channel; any other parameter of a notice set by an expression, or an expression that reads anything but this workflow's blocks; Webhook and Wait, which a call from outside can start or wake; n8n's AI agent blocks, which can't go into NCS's agent hub (ADR 0023), though the Code Tool and LangChain Code they can call wait for P9 like every block that runs code; an operation the class file doesn't class, and Custom API Call; one of n8n's blocks that is disabled or set to go on past a failure; a run time the Portal can't show | One Approver, on the approval page, or two, one after the other, when the workflow changes someone's access (section 3) |

The last row is "anything" in the team lead's words. The rows above it are not checks an Approver could clear. Fixed for you is what keeps the platform's own guarantees, such as recording each run. Needs an answer and needs a setting are things that can't run as drafted, whoever approves them. The fourth row would open n8n itself, as the next part says.

**The team lead's accepted exceptions to "anything can go through" (16 Nov 2026).** The team lead accepted each of these as written here. Each one is a block or a key that would open the platform itself, or bind an approval to less than what runs.

1. Execute Command, Local File Trigger and community nodes stay off.
2. The four sub-workflow blocks (Execute Sub-workflow, Execute Workflow Trigger, Call n8n Sub-Workflow Tool and Workflow Retriever) can't run until a version's digest covers the workflows they call, and each called workflow is approved itself.
3. The `n8n` block can't run, because Settings refuses a key to n8n's own API.
4. Microsoft Teams' block can't run, because it posts only with a person's own sign-in.
5. The blocks that run code and the blocks that read or write n8n's disk wait for spike P9.
6. Write keys for Gmail and Outlook wait for spike P9.
7. The drafter sends a native write to Jira or Confluence back, to use our Propose a change, Ask for a yes and Make the approved changes blocks.

**What it takes to make anything run.**

*All of n8n's built-in blocks load.*

- `NODES_INCLUDE` goes. n8n loads every built-in block except the two in `NODES_EXCLUDE`, Execute Command and Local File Trigger, and `N8N_COMMUNITY_PACKAGES_ENABLED` stays `false`. Execute Command runs shell commands inside n8n's container, and Local File Trigger watches its disk. n8n's environment there holds the platform's node key, the start secret, the database password and the key that encrypts every credential, write keys included. So one workflow with either block could read every key the platform holds and undo every check in this ADR, for every workflow. n8n leaves both out by default for the same reason. Community nodes are code from npm that nobody here has reviewed, installed into n8n while it runs, and DevNet can't fetch them.
- `node_classes.json` no longer decides what n8n loads. It keeps classing the blocks it knows, for their tags, their `says` and their keys. `_runs_anyway` in `workflow_check.py` then treats every built-in type but the two left out as loaded. A type or an operation it doesn't class is a flag: "Does something the platform hasn't classed". `scripts/nodes-include.sh` and its CI check go. Bootstrap's check (`bootstrap.py`, which compares with `NODE_CLASSES.loaded()` today) becomes "n8n loads every built-in type except the two left out, and no community type", and E7's staff gate reads that check. The pin check keeps checking that each classed row still matches the image, and it no longer asks for a row for every type.
- **The consequence.** Every workflow in n8n can use any of these blocks. In the platform's n8n project the checker flags them, and the credential sweep with `unaccepted()` keeps only approved versions live there (section 4). In a member's own space, n8n runs what they build by hand, as it does today, but now with every block. That includes HTTP Request to any address, a Webhook that a call from outside can start, and, after P9, Code. The credential sweep still deletes any key a member adds within a minute. Nothing stops them typing a token into a block's parameters, which no sweep sees. Only Operators with n8n access have a space (ADR 0027).
- It is one infra pull request and one deploy.

*Sub-workflows.* Execute Sub-workflow (`executeWorkflow`) runs another workflow inside its own execution, and so do Call n8n Sub-Workflow Tool (`@n8n/n8n-nodes-langchain.toolWorkflow`) and Workflow Retriever (`@n8n/n8n-nodes-langchain.retrieverWorkflow`). Execute Workflow Trigger (`executeWorkflowTrigger`) is what the called workflow starts with. The digest binds the calling workflow, not the one it calls, yet the called workflow's blocks run in the caller's execution in the platform's project, where n8n lets a workflow use every key, and n8n may run the called workflow's saved draft whether or not anyone published or approved it. Execute Sub-workflow can also load a workflow from a file on n8n's disk. So these four blocks can't run on this platform until a version's digest includes the digest of each workflow it calls, and each called workflow is itself approved. That needs its own amendment. The pin check names any other block that calls `helpers.executeWorkflow`.

*Blocks that run code, and blocks that use n8n's disk.* The author checked every block in the pinned image, `n8nio/n8n:2.42.6`: 444 in `n8n-nodes-base` and 125 in `@n8n/n8n-nodes-langchain`. The check read each block's own folder for `child_process`, `process.env`, Node's `fs`, n8n's file helpers (`createReadStream`, `writeContentToFile`, `resolvePath`), n8n's code sandboxes and `helpers.executeWorkflow`. It found these:

- **Blocks that run code** are Code (`code`, whose languages include Python, so 2.42.6 has no separate Python Code block), LangChain Code (`@n8n/n8n-nodes-langchain.code`), Code Tool (`@n8n/n8n-nodes-langchain.toolCode`), Function (`function`), Function Item (`functionItem`), AI Transform (`aiTransform`, which runs code a model writes), Sort and Item Lists in their code sort mode (`sort`, `itemLists`), and Merge in its SQL mode (`combineBySql`, which runs AlaSQL).
- **Blocks that read or write a path on n8n's disk** are Read/Write Files from Disk (`readWriteFile`), Read Binary File (`readBinaryFile`), Read Binary Files (`readBinaryFiles`), Write Binary File (`writeBinaryFile`), Git (`git`), and Execute Sub-workflow when it loads a workflow from a file.
- **Blocks that read `process.env`** are, besides Execute Command and the code blocks, Airtop and Microsoft Agent 365 Trigger. Each reads only settings of its own (`AIRTOP_BASE_URL`, `N8N_VERSION`, `ENABLE_OBSERVABILITY`), never a name a workflow picks.
- Edit Image, Form, n8n Form Trigger, FTP, SSH, Webhook and AI Agent use `fs` only for files of their own in n8n's temporary folder.

The blocks in the first two lists wait for spike P9. Nothing else in n8n's built-in blocks reads n8n's environment or a path on its disk, as far as this check shows. The catalogue script repeats the check on each new pin, and the pin check fails on a new block that matches.

*Write keys.*

The platform's keys (E16, E17) can only read or post, and the credential sweep deletes every key the platform didn't make. An approved write needs a key that can write.

- **The store.** A new port in orchestration, `WriteKeys`, has two adapters. On Azure it is a second Key Vault, only for write keys, which platform-api's identity alone may read and write. n8n's identity has no role on it. Locally it is a table sealed with `SETTINGS_ENCRYPTION_KEY`.
- **Adding one.** An Operator adds a write key in Settings, Connections, with its system, n8n's credential type, a name, and its secret fields. The fields are write-only, and the Portal shows only their last two characters (ADR 0030). For a generic credential, such as Header Auth, the Operator also names the one host it may be sent to. Settings refuses a key to n8n's own API (`n8nApi`), because a workflow holding one could change or publish other workflows past their approvals. The settings history records who added it (ADR 0029). A member who wants to use their own key gives it to an Operator, who adds it there. No key is kept in n8n by a member, and none is typed in the chat, which refuses a key's shape (section 5).
- **Choosing one.** A block that writes with a key has a setting of kind `key`, which is never guessed (section 5). Its choices are the write keys for the block's system. The set-up approval names the key for each block, and the report shows it, as in "Closes GitLab issues with the key 'GitLab ops', added by Alice".
- **In n8n.** The platform makes the n8n credential from the store, in its own n8n project, when it sets up an approved version that names the key. It deletes the credential when no approved version in its project names it. `attach_keys` puts a write key only on a block that the version's set-up approval names it for, matched by digest, and takes every other reference to it off. It never puts a key on a block of another type, so an HTTP Request block can't send the Jira key to another address. A generic key goes on an HTTP Request block only when the block's address is written out and is on the key's host, and when the block doesn't follow redirects, since a redirect would send the key to another host. Code turns redirects off on any HTTP Request block that names a generic write key (Fixed for you), and `attach_keys` puts no key on one that follows them.
- **The sweep.** It treats a write key as it treats a platform key. It keeps the key while n8n holds it exactly as the platform made it, deletes it and makes it anew on any difference, and deletes it when no approved version names it. A version that names a write key its approval doesn't name has a finding that n8n would run anyway and nobody accepted, so the sweep takes it off within a minute. A workflow opens in a member's space without its write keys, as it does without every other key (ADR 0045, amendment 3).
- **Checked each day.** The daily check of what a key can do (ADR 0045, amendment 11) doesn't apply to write keys, which are meant to write. Each write key's connection test runs daily instead, and a failing key marks the workflows that name it Needs a fix.
- **Gmail and Outlook.** n8n rewrites an Outlook key each time it gets a token, and Gmail's block needs a key that can change mail (ADR 0045, amendment 1). Their write keys work only once spike P9 shows that the sweep can tell n8n refreshing a token from someone changing the key. Until then their blocks can't run.

*Code and HTTP Request.*

- **What they reach today.** n8n has an open route to the internet on the local stack and on Azure. `deploy/compose.lockdown.yaml` is the DevNet lock-down test, not a deploy. It sends n8n's traffic through a proxy that lets through only `login.microsoftonline.com`, `api.github.com` and the model gateway. So an approved HTTP Request or Code block can reach any address on the internet. It can also reach every service on n8n's own network: platform-api, the agent runtime and, locally, PostgreSQL, or on Azure the Container Apps environment's internal addresses. Each of those asks for its own key. platform-api's node routes want `WAB_NODE_KEY`, the agent runtime wants its key, n8n's own API wants its owner's key, and PostgreSQL wants its password. n8n holds the first of these, and `WAB_START_SECRET`, in its environment.
- **What keeps n8n's secrets from a block.** `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` (`deploy/compose.yaml`, `infra/envs/dev/main.tf`) keeps expressions from reading n8n's environment. That setting is load-bearing, and bootstrap gains a check that n8n runs with it. On Azure, n8n's identity can read only n8n's own secrets (`infra/README.md`), and none of the write keys.
- **Spike P9, before any of those blocks loads.** On n8n 2.42.6, can a block that runs code, in n8n's task runner, read `process.env`, n8n's own files (`~/.n8n`), or the Container Apps identity endpoint, whose header sits in the environment? The spike asks this of each block in the code list above, and asks of each block in the disk list whether it can reach n8n's own files. If any can, that block stays in "Can't run on this platform" until it runs where none of n8n's secrets are. n8n's external task runner, in its own container, is one such place, as the author understands n8n. Bootstrap also checks n8n's file-access settings (`N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES` and `N8N_RESTRICT_FILE_ACCESS_TO`) once P9 confirms them.
- **In DevNet,** the lock-down proxy's list is what an approved HTTP Request block can reach, and a new address is a change to that list.
- The report says it plainly for each such block, as in "Can send what the run read to any address on the internet" or "Runs code that a person wrote".

### 3. The change to the safety rules, and the guardrails

**The amended rule.** The team lead's decision becomes this rule in `AGENTS.md`, ADR 0026 and ADR 0045:

> No write runs without a person's approval: a write through our blocks waits for a yes in Teams on each run; a write by one of n8n's own blocks runs on an Approver's approval of that exact workflow version, given at set-up.

What that means, plainly:

- **For n8n's own write blocks there is no yes on each run.** Nobody sees what a run will change before it changes it. Nothing checks our records at the moment of writing, so ADR 0026's guarantee doesn't hold for those writes. ADR 0045's write proxy (E18) is no longer needed for them to run. It stays the way to add a yes on each run for one system later.
- **HTTP Request and Code count as n8n's own write blocks,** because they can change or send anything. They run on the same approval.
- **A notice that breaks the Tell rule is approved once the same way.** That covers a notice whose words come from what a run read, and one that posts to a place the data picks. ADR 0026's Tell rule still holds for our own Tell.
- **The safety checker no longer denies anything by default.** It flags, and the Approver decides. The write gateway still denies by default for our own blocks.

**What does not change.**

- A write through our blocks gets an Ask for a yes before it (`add_yes`). The write gateway checks our records at the moment of writing, and `refuses_writes` refuses it in a version graded `writes_refused`, which no approval clears.
- An Approver never approves their own work. The access review's two Approvers, one after the other, still apply on each run, because it writes through our blocks, where `approvers_min` and `policy.steps` ask for two (ADR 0023). Its set-up needs two as well (below).
- Every run is recorded. Our node pack gains a ninth block, Record the run, which only makes the call that every block of ours makes first. That call links the run and checks its version, and then the block passes its items on. Code puts it after each trigger, so `_ours_first` always holds. The activity log shows every run of an approved version, with who approved that version. What n8n's own blocks changed in a run is in n8n's execution, which the In n8n tab shows (E8), not in our log.
- Our Read, Propose a change and Agent blocks still reach only the team's allowed places.

**The guardrails.** The team lead asked for each of these in the first request, and none adds a step.

- **Each flag in plain words, ticked one by one.** The approval page lists each flag with what it is, why it matters and what the Approver agrees to by accepting it, all from `FLAG_RULES`. Where a block posts, the page shows the block's own words, and for words from an expression, which block's output they read. Approve stays off until the Approver has ticked each flag and written, for each one, why they accept it. Code refuses an empty reason.
- **Never their own.** A party (section 1) can't approve. `decide()` refuses them with `own_work` from `ApprovalRequest.parties`, and `_fault` refuses a recorded decision by one, as for a run.
- **Two Approvers, one after the other, for a workflow that changes someone's access.** This is the one exception to one Approver, and it keeps the sponsor's rule for the access review. It applies however the write is built: through our blocks, through one of n8n's own blocks, or through HTTP Request. The set-up approval's `policy.steps` then has two steps. `approval_status` and `_fault` keep the order and refuse the same person twice (`SAME_PERSON_TWICE`), and `ApprovalRequest.parties` refuses a party at either step. The second request goes out only after the first yes, and it shows the first Approver's ticks and reasons. Each Approver ticks every flag. Code, not the drafter or a person, decides that a workflow changes access. It counts a block as access-changing when:
  - its operation's class row has `approvers_min: 2`, the field ADR 0045 gave the class file for an operation that changes someone's access, or, for our Agent block, a tool on its card asks for two (ADR 0023);
  - it is one of n8n's own blocks, in a write, for a system the class file marks as an identity or access system, a new mark on a type's row (`access: true`). Microsoft Entra ID, Okta, Google Workspace Admin, LDAP, AWS IAM and AWS Cognito get it, and so does GitLab for its membership operations;
  - it is an HTTP Request or HTTP Request Tool block that writes, unless its host is on the "not access" host list. A list of access hosts could never be complete (GitHub's, Atlassian's and Slack's admin APIs, Graph's sovereign hosts such as `graph.microsoft.us`, the Entra portal's API, or a forwarding service a person controls), so code counts an HTTP write as access-changing by default, as it does whenever it can't tell. The "not access" list starts empty, lives beside the class file, and grows only by a pull request or when an Operator adds a host in Settings, with the reason shown in the log;
  - code can't tell. That covers an HTTP Request whose address is an expression, a block that runs code, and a write by a type or operation the class file doesn't class. A class row that marks a type `access: false` moves that type's *classed* write operations back to one Approver. An unclassed operation and Custom API Call stay at two whatever the type's mark, because code can't tell what they do (Custom API Call on Slack with a write key can reach `admin.users.*`).

  Everything else needs one Approver.
- **The override log.** Orchestration keeps each set-up approval in a new table that it only ever adds to. The database holds it to that, because the app's role gets no UPDATE or DELETE on the table. A row holds the drafted workflow, the version's digest and n8n version id, the rules it was checked under (`GRADING_RULES`), and each accepted flag: its rule, its block, the digest of that block's parameters, and the words shown. It also holds the Approver, when they decided, what they ticked and why, the write key named for each block, the parties, and the sender's notes. Each decision is also an activity event (`setup_approved` or `setup_declined`, both new) in the activity log (ADR 0031), with who decided, as `AGENTS.md`'s logging rule asks. The workflow page shows a line such as "Approved with 3 accepted flags by Bob", which opens the log.
- **Bound to the exact version.** The digest is a hash of the whole document in a canonical form. It drops only where each block sits (`position`), the Sticky Notes, and the fields n8n adds of its own (`id`, `webhookId`, `meta`, `versionId` and the times). Every other field counts, a field the checker doesn't read included, so a new n8n field can't slip past it. Any change to a field that counts makes a new digest, and the new version is not approved. `same_as_sent` in `orchestration/n8n.py` compares in one direction only and skips `pinData`, so it is not the digest. A test checks that `digest(stored) == digest(kept())` for every golden document, where `kept()` is the version n8n gives back. When the checker's rules change, a flag stays accepted only when the same rule finds the same thing in the same block. A new finding needs a new approval.
- **Any edit makes it unapproved again,** and `unaccepted()` stands wherever `unchecked()` stands today (section 4).

**What the checker adds, so that every flag the Approver ticks is the whole truth.** These come from the safety review of this ADR. Each one makes a finding the Approver sees, not a refusal, except on our own blocks, where code fixes it.

- **A disabled block counts as absent.** n8n passes items straight through a disabled block. So `_ours_first` and `_yes_before_writes` skip a disabled block when they walk a path.
- **A block that goes on past its own failure is flagged.** n8n passes items past a failing block set to continue. The checker flags `onError` set to anything but `stopWorkflow`, `continueOnFail`, `alwaysOutputData` and `executeOnce` on every block, and on one of n8n's own blocks the finding runs anyway. On our own blocks, code turns them off.
- **Every parameter of a notice is checked.** Today `_places` checks only a notice's target parameters and `_words` only its text parameters, so its other parameters (for Slack, `otherOptions`, such as the ephemeral user and the bot's name and icon) go unchecked. Every parameter of a notice block must be written out, except the parameters its class row names as text. An expression anywhere else is a flag, and the finding runs anyway.
- **An expression is checked for what it reads.** An expression may name `$json`, `$input` or `$('<a block in this workflow>')`. Anything else, such as `$env`, `$vars`, `$execution` or another workflow's data, is a flag. The report shows from code which block's output each expression reads, as in "posts whatever 'Read Jira' read". `$('<block>')` on an Execute Workflow Trigger reads the items the calling workflow sent, so it carries the caller's data. That is moot while the sub-workflow blocks can't run, and the report must say so once they can.

### 4. The E16 invariant

ADR 0045's amendment 6 says, in short, that nothing in the platform's n8n project is live with a block n8n would run unchecked, and that no draft with one runs. This ADR amends it to read:

> Nothing in the platform's n8n project is live with a finding n8n would run anyway, unless a set-up approval for that exact version accepted it. No draft with a finding that nobody accepted runs.

The approval is the check, matched by digest. We weighed three options.

- **Overridden workflows never get the platform's keys.** Then an approved write or notice couldn't run, and the approval would do nothing.
- **They run only with the member's own keys, in a separate n8n project.** The credential sweep deletes every key the platform didn't make, keys are never asked for in the chat, and most Operators have no n8n space. It would rebuild ADR 0045's key model for one feature.
- **The invariant names the approval as the check (chosen).** Every guard stays in place, and each one asks one more question.

`unchecked(document, keys)` stays pure and doesn't change. A new pure function in `orchestration/workflow_check.py`, `unaccepted(findings, accepted)`, keeps the findings that no accepted flag covers. A new `accepted_for(digest)` reads the accepted flags of the version with that digest, so a version changed anywhere has none. `unaccepted()` goes wherever `unchecked()` is used today:

- **The credential sweep** (`KeySweep._take_off` in `builder/key_sweep.py`) takes a live version off when `unaccepted(unchecked(live, made), accepted_for(digest(live)))` is not empty. A changed version is taken off within a minute and marked Needs a fix, as today.
- **Take-back** (`Holding._live_again` and `Holding._keys_back` in `builder/n8n_holds.py`). A version changed in a member's space comes back with a new digest and stays off, and its card says "Changed since it was approved."
- **The check before a version goes live** on turn on, resume and restore, and **the check before a test run** (both in `builder/service.py`).
- **Made in n8n's set-up.** `_draft` in `builder/made_in_n8n.py` feeds `Candidate.runs_anyway`, which reads both `graded.findings` and `draft`, the findings in a published workflow's draft. Both go through the filter.

Two more places read the result.

- **Runs.** The stored version keeps all its findings and the id of its set-up approval. Its grade for runs is the grade of its findings that nobody accepted. `version_problem` and `refuses_writes` in `orchestration/n8n_calls.py` read that grade, and they don't change.
- **Keys.** `attach_keys` puts platform keys on as today, and write keys only as section 2 says. An accepted notice is still a `notice` operation, so it gets the platform's key for its system.

**Test runs change nothing.** A test run is a run by hand, and n8n uses a block's pinned output only in a run by hand (ADR 0045, amendment 7). So code pins the output of each of n8n's own blocks that isn't classed `read`, or that the class file doesn't know. That covers n8n's write blocks, its notices, HTTP Request and Code. Our own blocks are not pinned, because they already change nothing in a test run: Ask for a yes stops there (ADR 0044), the write gateway refuses a test run's write, and Tell sends nothing. The pins are in the approved digest. A test run of a draft with such a block unpinned does not start.

### 5. Settings and questions

Each setting in a plan has an id, a kind, a label, the parameters it fills, and one of three marks.

| Mark | When | The person sees |
|---|---|---|
| Filled | Code located the value exactly in the person's own words, as ADR 0049 locates a tool's argument, or the person chose it or typed it | The value, with "from your words" or "you chose" |
| Guessed | The drafter picked it, and the person can change it | The value, with "I guessed" and Change |
| Needed | Nobody has given it | The next question |

- **Never guessed.** Five kinds are never guessed: the run time, the Jira project, any channel or address that a notice or a Tell posts to, the Approvers, and the key a block writes with. Code holds this, not the prompt. A value of one of these kinds counts as filled only when code locates it in the person's words and finds it in the platform's data: an allowed project, a channel the platform's key can see, an Approver on the People list who is not a party, or a write key for the block's system. Any other value becomes needed. Code reads run times with `said_schedule`, as the Planner does today.
- **One question at a time.** Code writes the question's words, fixed for each kind, and offers 2 to 4 choices from the platform's own data, as ADR 0047's clarifying question does.
  - The Jira project offers the team's allowed projects (`KnownOptions.places`).
  - A Slack channel offers the channels the platform's Slack key can list.
  - The Approvers offer the People list's Approvers who are not parties, and "Any Approver on the team".
  - A key offers the write keys for the block's system, and "Ask an Operator to add one", which sends a team request (ADR 0038).
  - A run time offers a few common times, and "Type a time".

  A choice the person taps is their answer, not a guess. Code reads a typed answer. When code reads nothing in it, the same question comes back with its choices.
- **The order.** First what the workflow can't start without (the run time), then where it reads, writes and posts, then the keys, then the Approvers.
- **Keys are never asked for in the chat.** The report says which key each block uses, such as "the platform's Jira key" or "the write key 'GitLab ops'". Code refuses a message that holds the shape of a key (the shapes ADR 0050's masker knows, such as `sk-ant-`, `ghp_` and `Bearer`) before any model reads it, and answers "Don't paste keys here. An Operator adds keys in Settings." Keys come only from the platform's keys and the write keys that Operators add.
- **Approval stays off until nothing is needed.** The route refuses while any setting is still needed, and the card says how many are left.

### 6. The workflow report, and Explain this workflow

**One shared report builder.** A new module in the use case builder, `builder/workflow_report.py`, takes one workflow version and the checker's results and returns the report's facts. It is pure, and it needs no running n8n. It reads these for each source:

| Source | What it reads |
|---|---|
| A workflow the Planner laid out | The stored document of the version (`use_case_versions`, E4), its stored findings, the use case's Approvers and backup (ADR 0024), its schedule, and the tools on each Agent block's saved card (ADR 0023) |
| A workflow made in n8n | Its stored versions (version 1 from its set-up, later ones from the versions sweep) and their findings. Places, channels and the run time come from the document. Approvers come from the use case, which says any Approver until someone names them |
| A drafted workflow | The revision's document, its findings, its settings with their marks, and its set-up approval once it has one |
| An older published version | The copy ADR 0027 keeps of every published version, checked again under today's rules (`grade` is pure), with the grade it had when it was published shown beside it |

It reads orchestration only through the names its package exports: `grade`, `face`, `NODE_CLASSES` for each operation's class, tag and `says`, and `KEY_FOR_TYPE`.

The report has these sections, in this order:

1. **In short.** One or two sentences that code fills from the facts: when it runs, what it reads, what it changes or posts, and what waits for a yes. For example: "Every Monday at 9:00, it reads open bugs in Jira project MOCK, summarises them and posts the summary in Slack #support. It changes nothing in Jira."
2. **Step by step.** Each block in run order, with its plain name, whether it is our block or an n8n block, and its tag (Reads Jira, Shapes the data, Posts in Slack, Writes after a yes, Writes on the set-up approval).
3. **What it reads, writes and posts.** By system and place. A post shows its words in full when they are written out, or says which block's output they read.
4. **Flags.** Every rule in `FLAG_RULES`, passed or flagged. Each flag says what it is, why it matters, and who can clear it. "Fixed for you" lists what code added.
5. **Who approves each write.** Each write through our blocks, and who decides it on each run, one Approver or two. Each write by n8n's own blocks, HTTP Request or Code, marked "Runs on the set-up approval, with no yes on each run".
6. **Settings.** Each value, marked filled, guessed or needed for a drafted workflow, or with where it was set for a workflow that is already set up.
7. **Approval.** For a drafted workflow, whether its set-up needs one Approver or two, and for two, which blocks change someone's access and why code counts them so. For an approved version, who approved it, in order, and each accepted flag with why.

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

- **A catalogue built from the pinned image.** Pack smoke already starts the pinned image once without the allow list, and copies what it serves at `/types/nodes.json` (`scripts/pack-smoke.sh`). A new script, `scripts/n8n-catalogue.sh`, writes a new file, `contracts/n8n/catalogue.json`, from that copy, stamped with the image's digest. For each type n8n ships, it holds the name, the description, the versions, the resources, the operations and each operation's parameters. From our own files it adds each operation's class, tag and `says` where `node_classes.json` has them, and whether the platform has a key for it (`KEY_FOR_TYPE`). Our node pack's blocks are in the same list, under `CUSTOM.*`. Community nodes are not, because our n8n turns them off, and nor are Execute Command and Local File Trigger. CI fails when the file differs from what the script writes.
- **What else the drafter reads.** The capability registry (`agent_runtime/abilities.py`), so it knows what our own blocks do, and the team's facts in the request (section 1).
- **Small reads.** `find_blocks` searches names, descriptions and operations, and ranks our own blocks and the blocks the class file knows first. `describe_block` returns only the parameters n8n shows for the chosen resource and operation (n8n's `displayOptions`), so a large block such as Jira is never sent whole. The fixed part of the prompt comes first, where the prompt cache keeps it.
- **When n8n is upgraded.** The pull request that moves the n8n pin writes the catalogue again in the same change. Bootstrap compares the catalogue's digest with the image n8n runs. When they differ, the draft button answers "Drafting is paused while the platform updates." The golden set runs on that pull request.
- **n8n-mcp, compared.** A teammate showed a model building n8n workflows through n8n-mcp in November. Its README, read on 16 Nov 2026, says it is an MIT-licensed MCP server. Its documentation tools (`search_nodes`, `get_node`, `validate_node`, `validate_workflow`) work offline from a bundled database. Its other tools change an n8n through its API (`n8n_create_workflow`, `n8n_update_full_workflow`, `n8n_test_workflow` and more), and `DISABLED_TOOLS` can turn them off. Its database covers n8n's newer releases and community nodes, and its README showed n8n 2.46.7, where we run 2.42.6. So it would describe versions and parameters our n8n doesn't have, our checker would still judge every draft, and it would be one more service to pin and carry into DevNet. We build our own catalogue from the pinned image and borrow n8n-mcp's shape: a search, details at the level the model needs, and a validator, which for us is the catalogue check and the safety checker. If the eval's measure of invented parameters stays over its bar, n8n-mcp's documentation tools, pinned and offline, are the next thing to try.

### 9. How drafts are evaluated

A new golden set, `agent-runtime/evals/cases/workflow_draft.json`, holds at least 40 plain-English tasks. Teammates who haven't read the prompt write a third of them, which are held out. The set covers:

- the release check and the watchlist, which the Planner already lays out, as a baseline;
- ticket summaries posted in Slack, and a Confluence page read;
- tasks that need HTTP Request, Code or a write to a system we have no connector for, where every flag must show with what the Approver would agree to;
- a Jira write, which must use our blocks;
- tasks that change someone's access, through our blocks, through n8n's own blocks and through HTTP Request, which must ask two Approvers at set-up;
- tasks that name a run time, a project, a channel, a key or an Approver, and tasks that don't;
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
| A workflow that changes someone's access asks two Approvers at set-up | Code, against the case's mark | 100%, and none marked for one |
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

- **Drafting limited to the allow list.** Every draft could run with today's guarantees. But the team lead asked for no limits.
- **No override, so the checker stays final, as today.** The simplest, and `AGENTS.md` wouldn't change. But nothing the checker flags could run, and the team lead chose that the Approver decides.
- **Accept only a named set of flags (this ADR's first version, 16 Nov).** Only posts could be accepted, with two Approvers for a post of what a run read, and every write kept its yes on each run. Writes by n8n's own blocks, HTTP Request and Code would have needed a pull request and a deploy each. The team lead chose "anything can go through" instead.
- **Two Approvers, one after the other, for every risky flag.** For example any write by one of n8n's own blocks, a write key from a member, Code, HTTP Request, or sending a run's data out of the platform. A second person would see each such workflow before it runs. Chosen only for a workflow that changes someone's access, because that is the sponsor's rule for the access review. For the rest the team lead wants one simple approval. More rules can ask for two later, as a column in `FLAG_RULES`, with `policy.steps` asking for two, without changing the rest of this design.
- **A yes on each run for n8n's own writes, through ADR 0045's write proxy (E18).** It keeps ADR 0026's check at the moment of writing for those writes. But it needs a proxy for each system, a system with a fixed address can't use one, and the team lead asked for it simple. It stays the way to add a yes on each run for one system later.
- **Load only the blocks a team asks for, as a growing allow list.** Members' own spaces would stay narrower. But each new block would need a pull request and a deploy before anyone could approve a workflow with it, which is not "anything".
- **Load Execute Command and Local File Trigger too.** That would be literally everything. But either one gives a workflow n8n's own environment, which holds the key that decrypts every credential, so one approved workflow could undo every guard here. Section 2 keeps them off, as n8n does by default.
- **Let the sub-workflow blocks run now.** A workflow could call shared steps. But the approval binds only the caller, and the called workflow's draft runs with every key in the platform's project. Section 2 holds them until the digest covers what they call.
- **Overridden workflows run with members' own keys, in their own project.** Section 4 weighs it.
- **Drafting from templates only.** The Planner already does this (E4), and it still comes first. It can't do a task nobody wrote a template for, which is ADR 0023's reason for agents.
- **The model writes the n8n JSON itself.** Less code. But the ids, the positions, the platform's settings, the yes and the keys would all rest on the model, and every layout rule would be checked only after the fact. ADR 0023 and ADR 0027 already split this work. The model chooses, and code places.
- **Drafted workflows kept in n8n from the start, in the platform's project.** The canvas would be n8n's own. But unapproved drafts would sit where n8n lets a workflow use every key, and the E16 invariant would have to watch them too. So they stay in our records until approved, and go into n8n only for Edit in n8n, in the person's own space and without keys.
- **No set-up approval for a draft with no flags,** as the Planner's set-up card and Made in n8n's set-up need none. It would save a wait. But the model chose and wired the blocks, the sponsor wants a person to look before anything new runs, and the team lead asked for it.
- **n8n-mcp for the catalogue.** Section 8 weighs it.

## Consequences

- **This changes rules the sponsor gave.** "No write action runs without approval in Teams" came from the sponsor. After this ADR, a write by one of n8n's own blocks, HTTP Request or Code runs with no yes on each run, on one Approver's approval at set-up. The sponsor's other rule stays: a workflow that changes someone's access needs two Approvers, one after the other, at set-up, and the access review's writes through our blocks still ask two on each run. The team lead tells the sponsor before the override's pull request merges. Nobody else writes to the sponsor about it.
- **`AGENTS.md`'s product safety rules change** in the pull requests that make each part true (build order, steps 10 and 13):
  - "No write action runs without approval in Teams. The safety checker denies write actions by default." becomes "No write runs without a person's approval: a write through our blocks waits for a yes in Teams on each run; a write by one of n8n's own blocks runs on an Approver's approval of that exact workflow version, given at set-up. HTTP Request and Code count as n8n's own write blocks. The safety checker flags, and the Approver decides. The write gateway still denies by default for our blocks (ADR 0051)."
  - "n8n holds no write key. Only our own node writes to Jira or Confluence, through the write gateway ..." becomes "n8n holds a write key only while an approved version needs it, and only on the blocks that approval names. Our own node writes to Jira and Confluence through the write gateway, which checks every approval against our records at the moment of writing (ADR 0026)."
  - "n8n's own nodes may only read, or post a notice under the Tell rule ..." becomes "n8n loads all its built-in blocks except Execute Command and Local File Trigger, and no community nodes. In the platform's n8n project, a version runs with a block the checker flagged only when an Approver approved that exact version at set-up. Only the platform creates credentials in n8n: read and post keys from Key Vault, and write keys that Operators add in Settings (ADR 0051)."
  - The Tell rule's line gains: "One of n8n's notice blocks that breaks the Tell rule runs on the set-up approval instead (ADR 0051)."
  - "An Approver can never approve their own work. The access review needs two Approvers, one after the other." stays, and gains: "A workflow that changes someone's access, however it is built, needs two Approvers, one after the other, at set-up. When code can't tell whether a write changes access, it counts it as one that does (ADR 0051)."
- **ADR 0026** gains the amended rule from section 3. Its consequence "n8n holds no keys for other systems, and it loads only an allowed list of node types" is replaced by section 2.
- **ADR 0045** gains the amended rule. Its allow list is no longer the class file, the `write` class and the write proxy become optional, amendment 6 gains the invariant in section 4, and amendment 12's written-out words become a flag.
- **ADR 0027** said the Planner may draft n8n workflows because the allow list limits them to our node pack. That reason is replaced by the set-up approval.
- **ADR 0023** said the model never writes arbitrary n8n workflows, and ruled out n8n's AI agent blocks. Its change note gains: "The workflow drafter (ADR 0051) may propose any block. Code lays it out, the checker flags it, and an Approver's set-up yes comes before it runs, or two Approvers' when it changes someone's access. n8n's AI agent blocks load, and the report flags that they can't go into NCS's agent hub."
- **ADR 0049** gains the tool `draft_workflow` and an `explain` choice for `show`, each checked as sections 1 and 6 say.
- **ADR 0034 now guards every Webhook a member builds.** n8n's sign-in protects only its editor. A published Webhook, Form Trigger, Wait on a call, or MCP Server Trigger answers anyone who can reach n8n's address, at the paths n8n gives them: `/webhook`, `/webhook-test`, `/webhook-waiting`, `/form`, `/form-test`, `/form-waiting`, `/mcp` and `/mcp-test`. On Azure, ADR 0034's address list is the only guard, and the operator chose on 1 Nov 2026 to run with no list. Locally, compose publishes n8n's port on the host. So the deploy that loads every built-in block refuses to open n8n's editor on Azure without `N8N_EDITOR_ALLOWED_IPS`, and a deploy check calls each of those paths from outside the list and expects "RBAC: access denied". The check also covers `/webhook-waiting` after a Wait resumes. Locally, compose publishes n8n's port on every address today (`"${N8N_HOST_PORT:-5678}:5678"`), so the same PR binds it to the laptop only (`127.0.0.1`). Without that, a Webhook is an open door from the internet into n8n.
- **ENGINE-PLAN** E11's generated allow list and its CI check go, and E17's credential sweep gains write keys.
- **Members with n8n access can do more in their own spaces.** They can run any built-in block by hand, call any address, publish a Webhook that ADR 0034's address list must guard, and, after P9, run Code. The sweep still takes their keys, but not a token typed into a block. The sponsor should hear this too.
- **The glossary** gains Workflow drafter, Drafted workflow, Workflow report, Set-up approval, Accepted flag and Write key. Draft gains "Not the workflow drafter's drafted workflow." Safety checker changes from "denies write actions by default" to "flags, and an Approver decides". n8n block loses "may only read or post a notice". Planner answer gains the draft card and the explanation.
- **The capability registry** gains "Draft a workflow from your words" and "Explain a workflow". Each stays Planned until its pull request lands, so the Planner never offers it early (principle 5).
- **The set-up approval is a new kind of approval request,** separate from a run's. It reuses `ApprovalRequest`, its `parties` and its `policy.steps` (`orchestration/approvals.py`), ADR 0024's routing and expiry, and ADR 0036's Teams card.
- **Made in n8n** gains Send for approval for a workflow with flags, so a workflow built by hand and a drafted one meet the same rule.
- **One more prompt, one more generated file, and one more vault to keep.** The catalogue moves with the n8n pin.
- **Cost.** About 26 to 49 cents a draft, and about $80 for the bakeoff (section 7).

**The build order,** as small pull requests. The safe parts ship first. The approval of flagged workflows and the infra that lets "anything" run come last.

1. **The screens** (`docs(builder)`), in the chat-first prototype (`docs/design/chat-first/prototype.html`), with the principles' checklist walked. They are the draft card with its steps as they go, the questions, Edit in n8n, the report page, Explain on Workflows, on the workflow page, in the version history and in the chat, the approval page with a tick and a reason for each flag, the Teams card, and adding a write key in Settings.
2. **The workflow report builder** (`feat(builder)`, `builder/workflow_report.py`) for every existing kind of workflow version, with a rule id on each finding and `FLAG_RULES`. It has no screen, so it can be built beside step 1.
3. **Explain this workflow** (`feat(builder)`), the report builder's first user, on the screens from step 1, with the Planner's "explain <workflow>" and the guarded wording.
4. **The catalogue** (`feat(runtime)`) from the pinned image, with its script and its CI check.
5. **The workflow drafter** (`feat(runtime)`), with its tools and 10 golden tasks scored by code.
6. **Drafted workflows without flags** (`feat(builder)`). This is the draft card, the revisions, the layout, the check, changes asked for in the chat, a set-up approval for a draft with no flags, and the set-up as a Draft. A draft that changes someone's access waits for step 10, which brings its second Approver.
7. **The drafted workflow's report and settings** (`feat(builder)`), with the questions one at a time, the never-guess rule, the approval held until nothing is needed, and Edit in n8n.
8. **The full golden set** (`feat(runtime)`), the bakeoff that picks the model, and the CI gate, reporting only.
9. **The drafter's traces** (`feat(monitoring)`), flags, judge and review queue, after ADR 0050's PR A and PR B.
10. **The approval of flagged workflows** (`feat(orchestration)`). This is Record the run in the node pack, the checker's new rules, accepted flags, two Approvers for a workflow that changes access, the access marks and host list, the log, `unaccepted()` in the six places, the pins for test runs, Made in n8n's Send for approval, and `AGENTS.md`'s checker and Tell lines. At this step it covers the blocks n8n loads today. The sponsor hears first.
11. **Spike P9** (`docs(orchestration)`), on Code, n8n's files, its identity endpoint, and Gmail's and Outlook's token refresh.
12. **All of n8n's built-in blocks** (`feat(infra)`), with bootstrap's and the pin check's new checks and the file-access settings. Code and the other blocks P9 names load in this step only if P9 passed.
13. **Write keys** (`feat(orchestration)`), with their store, their Settings card, `attach_keys` and the sweep. `AGENTS.md`'s write lines change with them.
