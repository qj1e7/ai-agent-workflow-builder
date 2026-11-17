# n8n 2.42.6: can a block that runs code, or uses n8n's disk, reach n8n's secrets? (spike P9)

Path: docs/evidence/prototypes/p9-n8n-code-isolation/README.md

This answers spike P9 in [ADR 0051](../../../adr/0051-a-workflow-drafter-may-propose-any-n8n-block-code-explains-every-workflow-and-an-approvers-yes-sets-up-a-flagged-workflow.md), section 2 ("Spike P9") and build step 11. It ran on 17 Nov 2026, on a throwaway n8n that held made-up canary values only. Nothing here is product code.

## The question

On n8n 2.42.6, set up as the platform runs it:

1. Can a block that runs code a workflow gives it reach n8n's environment, n8n's own files under `~/.n8n`, or the Container Apps identity endpoint? The blocks are the ones in ADR 0051's code list: Code (JavaScript and Python), AI Transform, the Code Tool, LangChain Code, Function, Function Item, Sort and Item Lists in their code mode, and Merge in its SQL mode.
2. Can each block in ADR 0051's disk list reach n8n's own files? They are Read/Write Files from Disk, Read Binary File, Read Binary Files, Write Binary File, Git, and Execute Sub-workflow loading a file.
3. Does n8n's external task runner, in its own container, close what the internal runner leaves open?
4. What do `N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES` and `N8N_RESTRICT_FILE_ACCESS_TO` do on 2.42.6?
5. When n8n saves a token it got for a Gmail or Outlook key, does the key's `updatedAt` change, so that the credential sweep would delete a valid key?

## Short answers

1. **Code blocks.** With the platform's settings, no block in the task runner (Code in JavaScript and Python, AI Transform, the Code Tool, Sort's and Item Lists' code modes) reached n8n's environment, its files or the identity header, with either runner. But the internal runner is a child of n8n in n8n's own container, so code that gets out of its JavaScript sandbox reads every secret n8n holds; the spike showed that with Node's modules allowed. Function, Function Item and LangChain Code don't use the runner at all: they run inside n8n's own process, and n8n 2.42.6 refuses them by default as deprecated. Let in, **LangChain Code read every secret in n8n's environment with no escape**, and got a token from the identity endpoint. Merge's SQL mode refused every file and URL.
2. **Disk blocks.** With n8n 2.42.6's defaults, none reached n8n's files, `/proc`, or anything outside `~/.n8n-files`.
3. **The external runner** closes what the internal one leaves open for the runner's blocks: even with every module allowed, code there found only the runner's own auth token. It changes nothing for the blocks that run in n8n's own process (Function, Function Item, LangChain Code, Merge's SQL mode, and every disk block), and Code's HTTP helper still sends from n8n's process, where the identity endpoint is.
4. **The file-access settings.** `N8N_RESTRICT_FILE_ACCESS_TO` defaults to `~/.n8n-files` on 2.42.6, and that default is what keeps the disk blocks off n8n's environment: set empty, every read block read all of n8n's secrets from `/proc/self/environ`. `N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES` is on unless set to `false`, blocks n8n's own folders (not `/proc`), and wins over the allowed list. With it off and the list naming `~/.n8n`, the disk blocks read the encryption key and wrote into the folder n8n loads blocks from.
5. **Token refresh.** Yes. n8n sets a key's `updatedAt` each time it saves a token it got, so the sweep would delete a valid Outlook key at its first run and about hourly after, and a Gmail or Outlook sign-in key at each refresh. Gmail's service-account key never saves a token.

## How it ran

**The stack** (`compose.yaml`, project `p9`):

- `wab/n8n:dev` (local image `e225ee887fb7`), the platform's own image: `n8nio/n8n:2.42.6` with our node pack (`deploy/n8n/Dockerfile`). PostgreSQL 17 pinned as in `deploy/compose.yaml`. n8n on `127.0.0.1:15790`, the stand-in on `127.0.0.1:15791`. Nothing of the running `wab` stack was touched.
- n8n's environment is the one `deploy/compose.yaml` and `infra/envs/dev/main.tf` give it, without `NODES_INCLUDE`, which step 12 removes. So `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`, `NODES_EXCLUDE` names Execute Command and Local File Trigger, community packages are off, and no file-access setting is set.
- Each secret the platform gives n8n holds a made-up canary instead: `DB_POSTGRESDB_PASSWORD`, `N8N_ENCRYPTION_KEY`, `WAB_NODE_KEY`, `WAB_START_SECRET`, and, as Azure adds them for a managed identity, `IDENTITY_ENDPOINT` and `IDENTITY_HEADER`. `N8N_RUNNERS_AUTH_TOKEN` holds one too; the platform leaves it unset and n8n then makes one. `run.py` writes the values to `p9.env`, which git ignores. Each value is `P9CANARY-<NAME>-` and 8 random hex digits, so a probe only asks whether text it reached contains `P9CANARY-<NAME>`.
- **The stand-in** (`fake.py`) shares n8n's network, as Azure's identity endpoint sits on the app's own `localhost:42356`. `IDENTITY_ENDPOINT` is `http://localhost:42356/msi/token`. For each probe tag it records whether a request came and whether its `X-IDENTITY-HEADER` equalled the canary. It answers 400 without that header and 200 with it, and never stores or prints the header. It also stands in for a model, so n8n's AI Agent calls the Code Tool with no real model, and for a key's token endpoint (question 5). It answers on n8n's network address too, but every probe called it at `localhost`, the address `IDENTITY_ENDPOINT` names.
- **The external runner** is `n8nio/runners:2.42.6`, in its own container with no managed identity, as a separate Container App would be. It gets only the broker's address and the runner auth token.
- Setup files, made with `docker compose exec` as n8n's user: `~/.n8n-files/p9-control.txt` (marker `P9MARKER-CONTROL`), `~/p9-outside.txt` (marker `P9MARKER-OUTSIDE`, outside both n8n's folder and the allowed folder), the symlink `~/.n8n-files/p9-link` to `~/.n8n/config`, and the folder `~/.n8n/custom`. Besides that `custom` folder, `~/.n8n` held only `config`, `crash.journal`, n8n's event logs (`n8nEventLog*.log`) and `storage` (names only, `raw/<variant>.txt` line 2).

**The variants** (`variants/*.env`). n8n restarted for each, and every probe ran again.

| Variant | What changes |
|---|---|
| `internal` | Nothing. The platform's settings and the internal task runner |
| `external` | `N8N_RUNNERS_MODE=external`, with the runner container |
| `internal-escape` | `NODE_FUNCTION_ALLOW_BUILTIN=*`: code in the internal runner may load Node's own modules. It stands for code that got out of the runner's sandbox, to show what such code would reach |
| `external-escape` | The external runner, whose own config (`runners-escape.json`) lets JavaScript load every Node module and Python import every module and use every built-in. The same stand-in, for the external runner |
| `deprecated-allowed` | `N8N_DEPRECATED_NODES_BLOCK=false`, so n8n takes Function, Function Item and LangChain Code |
| `ssrf-on` | `N8N_SSRF_PROTECTION_ENABLED=true` |
| `files-block-off` | `N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES=false` |
| `files-restrict-empty` | `N8N_RESTRICT_FILE_ACCESS_TO=` (empty) |
| `files-restrict-n8n` | `N8N_RESTRICT_FILE_ACCESS_TO=/home/node/.n8n` |
| `files-restrict-n8n-block-off` | Both: the allowed folder is n8n's own, and the n8n-files block is off |

**How each probe works.** Every probe ran through n8n's own execution: `run.py` creates the workflow with the public API (`POST /api/v1/workflows`), runs it by hand as the editor's Execute does (`POST /rest/workflows/{id}/run`), reads the execution (`GET /api/v1/executions/{id}?includeData=true`), keeps only booleans, HTTP statuses and error classes, and deletes the execution and the workflow.

- The JavaScript probe (`probes.py`) is the same for every block that runs JavaScript. It asks whether `process` is there and whether its environment holds a canary; whether `$env` answers; four common ways out of a `vm` sandbox to the host's `process`; which of `fs`, `child_process`, `http` and `process` load; where `fs` loads, whether `/proc/self/environ`, `/proc/1/environ`, the parent process's environment and `~/.n8n/config` hold a canary; whether `@langchain/core/utils/env` loads; where n8n's file helper is there, whether it reads each target file; and whether n8n's HTTP helper, or Node's `http` where it loads, reaches the identity endpoint. If any text it reached held the identity header, it calls the endpoint with it, and the stand-in records whether the header matched.
- Python's runner checks code before it runs it and refuses a whole task for one forbidden import, so the Python probe is three blocks: one with no import that tries `open('/proc/1/environ')`, one that imports `os` and reads the environment and `/proc`, and one that reaches for `().__class__.__base__.__subclasses__()`.
- A disk read goes on to Extract from File and an Edit Fields block whose expressions only say whether the text holds a canary or a marker. A disk write writes the text `P9 harmless marker`, and `run.py` checks with `test -f` whether the file is there, then deletes it.
- `lib.Raw` refuses to write a raw line that holds `P9CANARY`, any canary value, the owner's password or the API key, and an error message is saved only as its class (`run.category`). A scan of every file in this folder for those values found none.

**Source reads.** Where an answer says READ, it was read in n8n 2.42.6's compiled code, copied out of the pinned image with `docker create` and `docker cp` (no container ran). Paths are under `/usr/local/lib/node_modules/n8n/`.

**Run it again.** `python3 run.py` runs every variant (or name some), and `python3 refresh.py` runs question 5 on the stack that is up. `python3 summarize.py > raw/summary.md` writes the tables below. `python3 run.py down` removes the containers, the network and the volumes. `run.py` makes fresh canaries the first time.

## Where each block's code runs (READ)

| Block | Where its code runs | Evidence |
|---|---|---|
| Code, JavaScript | n8n's task runner, a `vm` context with no `process`, no `fetch` and no `require` of Node's modules unless `NODE_FUNCTION_ALLOW_BUILTIN` names them | `node_modules/n8n-nodes-base/dist/nodes/Code/Code.node.js` lines 190 to 197; `node_modules/@n8n/task-runner/dist/js-task-runner/js-task-runner.js` lines 151 to 168 and 376 to 387 |
| Code, Python | n8n's task runner, Python. The n8n image has no Python, so with the internal runner Python can't run at all | `Code.node.js` lines 198 to 205; `dist/task-runners/task-runner-process-py.js` lines 56 to 66 |
| AI Transform | The task runner, as Code. It runs the code saved in `jsCode` and calls no model at run time | `node_modules/n8n-nodes-base/dist/nodes/AiTransform/AiTransform.node.js` lines 70 to 84 |
| Code Tool | The task runner, JavaScript or Python | `node_modules/@n8n/n8n-nodes-langchain/dist/nodes/tools/ToolCode/ToolCode.node.js` lines 40 and 46 |
| Sort (code mode), Item Lists (code sort, every version) | The task runner, in its narrowest mode (`runCode`), whose context holds only the items: no `require`, no helpers, no `$env` | `node_modules/n8n-nodes-base/dist/nodes/Transform/Sort/utils.js` lines 14 to 17; `ItemLists/V3/helpers/utils.js` lines 30 to 32; `js-task-runner.js` lines 169 to 183 |
| Function, Function Item | Inside n8n's own process, in `vm2` 3.12.2 (`NodeVM`), with n8n's full helper set in the sandbox | `node_modules/n8n-nodes-base/dist/nodes/Function/Function.node.js` lines 83 to 130; `FunctionItem/FunctionItem.node.js` line 138 |
| LangChain Code | Inside n8n's own process, in `vm2`, with n8n's helpers, `executeWorkflow`, and `langchain` and `@langchain/*` loaded in n8n's own context (`vm2`'s default `context: 'host'`) | `node_modules/@n8n/n8n-nodes-langchain/dist/nodes/code/Code.node.js` lines 110 to 149; `node_modules/.pnpm/vm2@3.12.2/node_modules/vm2/lib/resolver-compat.js` line 531 |
| Merge, SQL mode | Inside n8n's own process, AlaSQL's browser bundle in an `isolated-vm` isolate, whose file and network functions throw | `node_modules/n8n-nodes-base/dist/nodes/Merge/v3/helpers/sandbox-utils.js` lines 17, 50 and 65 |

Two more facts from the code decide the rest:

- **The runner's helpers run in n8n.** Code in the runner may call `helpers.httpRequest` and `helpers.request`, and n8n runs each call in its own process, with the block's own context (`node_modules/@n8n/task-runner/dist/runner-types.js` lines 4 to 12; `dist/task-runners/task-managers/task-requester.js` lines 279 to 320). So code in the external runner still sends HTTP requests from n8n's network, where Azure's identity endpoint is. File helpers are not offered in the runner.
- **What the internal runner gets.** n8n starts it as a child process with a short list of variables, none of them a secret (`dist/task-runners/task-runner-process-js.js` lines 66 to 108). `$env` is empty in the runner while `N8N_BLOCK_ENV_ACCESS_IN_NODE` is anything but `false` (`node_modules/n8n-workflow/dist/cjs/workflow-data-proxy-env-provider.js` lines 10 to 21). With it `false`, n8n sends its whole environment to the runner (`dist/task-runners/task-managers/data-request-response-stripper.js` lines 81 to 90).

## Results

### Blocks that run code (OBSERVED)

| Block | `internal` | `external` | `internal-escape` | `external-escape` | `deprecated-allowed` | `ssrf-on` |
|---|---|---|---|---|---|---|
| Code (JavaScript) | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity 400 | env YES, config YES, runner token YES, identity 200 | env no, config no, runner token YES, identity 400 | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity not reached (blocked by n8n) |
| AI Transform | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity 400 | env YES, config YES, runner token YES, identity 200 | env no, config no, runner token YES, identity 400 | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity not reached (blocked by n8n) |
| Sort, code mode | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached |
| Item Lists, code sort | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached |
| Function | refused by n8n | refused by n8n | refused by n8n | refused by n8n | env no, config no, runner token no, identity 400 | refused by n8n |
| Function Item | refused by n8n | refused by n8n | refused by n8n | refused by n8n | env no, config no, runner token no, identity 400 | refused by n8n |
| LangChain Code | refused by n8n | refused by n8n | refused by n8n | refused by n8n | env YES, config no, runner token YES, identity 200 | refused by n8n |
| Code Tool (JavaScript), called by an AI Agent | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity 400 | env YES, config YES, runner token YES, identity 200 | env no, config no, runner token YES, identity 400 | env no, config no, runner token no, identity 400 | did not run |
| Code (Python), no import, `open()` | python runner unavailable | ran, env no, runner token no, `open` refused | python runner unavailable | ran, env no, runner token YES | python runner unavailable | python runner unavailable |
| Code (Python), `import os` | python runner unavailable | refused before running | python runner unavailable | ran, env no, runner token YES | python runner unavailable | python runner unavailable |
| Code (Python), `__subclasses__` | python runner unavailable | refused before running | python runner unavailable | refused before running | python runner unavailable | python runner unavailable |
| Code Tool (Python), no import, `open()` | timed out | ran, env no, runner token no, `open` refused | timed out | ran, env no, runner token YES | timed out | did not run |
| Merge, SQL `control` | 1 row(s) | 1 row(s) | 1 row(s) | 1 row(s) | 1 row(s) | 1 row(s) |
| Merge, SQL `allowed_folder` | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox |
| Merge, SQL `n8n_config` | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox |
| Merge, SQL `proc_self_environ` | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox |
| Merge, SQL `url` | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox |
| HTTP Request to the identity endpoint, no header | 400 | 400 | 400 | 400 | 400 | blocked by n8n's SSRF protection |

Left out, and the same as `internal` in every row: `files-block-off`, `files-restrict-empty`, `files-restrict-n8n`, `files-restrict-n8n-block-off`.

Each JavaScript cell says whether the block's code reached a canary of n8n's own secrets (env), the encryption key in `~/.n8n/config` (config), and the runner auth token, and what the identity endpoint gave it: 400 means it reached the endpoint with no header to send, 200 means a token, sent with the canary header. `python3 summarize.py` builds both tables from `raw/<variant>.json`, which holds every boolean behind each cell.

What the table rests on:

- **In the runner, with the platform's settings** (`internal`, `external`, and the file-access variants), JavaScript had no `process` and no `fetch`, `$env` refused to answer, no Node module loaded, and the file helper answered that it isn't supported in the Code block. Of the four ways out of the sandbox, three were refused before they ran. The fourth, `(async () => {}).constructor('return process')()`, did make a function in the sandbox's own realm despite `--disallow-code-generation-from-strings`, but the function threw, because that realm has no `process` (`raw/<variant>.json`, `escape.async_function`). Sort and Item Lists had even less: no `require`, no helpers and no `$env`.
- **The internal runner is n8n's container.** In `internal-escape`, the same JavaScript, given Node's own modules, read every canary from `/proc/1/environ` and from its parent process's environment, which is n8n itself; read the encryption key from `~/.n8n/config`; found the identity header there; and got a token (200) from the identity endpoint, both through n8n's HTTP helper and directly. Its own `process.env` held no canary, as n8n starts it with a short list.
- **The external runner holds only its own token.** In `external-escape`, the same JavaScript and Python, given every module, found no canary of n8n's, no `~/.n8n/config` (the file isn't in that container), and couldn't reach the identity endpoint directly, since n8n's `localhost` isn't the runner's. They did read the runner auth token from the launcher's environment (`/proc/1/environ` and the parent process). That token lets a client ask n8n's broker for a grant token and register as a runner (`dist/task-runners/task-broker/auth/task-broker-auth.controller.js` lines 22 to 31, READ), so code that took over the runner could register another one and be offered other workflows' tasks. That wasn't tried.
- **Python.** The n8n image has no Python, so with the internal runner the Code block says the Python runner is unavailable, and the Code Tool's Python task waits until it times out. With the external runner, the Python runner refused `open` (a denied built-in), and refused `import os` and the `__subclasses__` reach before running them (`/opt/runners/task-runner-python/build/lib/src/constants.py` line 121, `task_analyzer.py` lines 45 to 118, in `n8nio/runners:2.42.6`). The runner image's own config allows no standard-library or outside module (`/etc/n8n-task-runners.json`, `N8N_RUNNERS_STDLIB_ALLOW` and `N8N_RUNNERS_EXTERNAL_ALLOW` both empty), and allows JavaScript only `crypto` and `moment`.
- **Merge's SQL mode** answered the control query, and refused every file and URL with "Network and file system access is disabled in the SQL sandbox", in every variant.
- **Function, Function Item and LangChain Code** were refused before they could run. n8n 2.42.6 answers 400 "Cannot use a ... node: this node type is deprecated" to a new workflow, an update, an import or a sub-workflow's code that adds one, while `N8N_DEPRECATED_NODES_BLOCK` is anything but `false` (`dist/workflows/deprecated-nodes-validation.service.js` lines 29 to 38 and 81 to 89; called from `dist/workflows/workflow-creation.service.js` line 185, `dist/workflows/workflow.service.js` line 376, `dist/services/import.service.js` lines 116 to 119 and `dist/workflow-execute-additional-data.js` line 124; the default is in `node_modules/@n8n/config/dist/configs/nodes.config.js` line 38).
- **Let in, they run inside n8n.** With `N8N_DEPRECATED_NODES_BLOCK=false` (`deprecated-allowed`), all three ran in n8n's own process. Function and Function Item found no canary: `vm2` gave them its own `process` with an empty environment, every way out returned that same object, `require` loaded nothing, and n8n's file helper, which they hold, read only `~/.n8n-files`. **LangChain Code read every canary in n8n's environment with no escape at all.** It loaded `@langchain/core/utils/env` in n8n's own context, called `getEnvironmentVariable` for each of n8n's secrets, found the identity header among them, and got a token (200) from the identity endpoint. Function and Function Item would read n8n's environment too wherever `N8N_RESTRICT_FILE_ACCESS_TO` is empty, since their file helper is the disk blocks' helper in the same process (see below).

### Blocks that use n8n's disk (OBSERVED)

| Block | `internal` | `external` | `files-block-off` | `files-restrict-empty` | `files-restrict-n8n` | `files-restrict-n8n-block-off` |
|---|---|---|---|---|---|---|
| Execute Sub-workflow, from a file, `~/.n8n-files` | read, but not a workflow | read, but not a workflow | read, but not a workflow | read, but not a workflow | blocked by n8n | blocked by n8n |
| Execute Sub-workflow, from a file, `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | other error (52 chars) |
| Execute Sub-workflow, from a file, a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | read, but not a workflow | blocked by n8n | blocked by n8n |
| Git, clone from, `~/.n8n` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n |
| Git, clone into, `~/.n8n/custom` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n |
| Git, status, `~/.n8n-files` | not a git repository | not a git repository | not a git repository | not a git repository | blocked by n8n | blocked by n8n |
| Git, status, `~/.n8n` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | not a git repository |
| Read Binary File, read `~/.n8n-files` | READ (control marker) | READ (control marker) | READ (control marker) | READ (control marker) | blocked by n8n | blocked by n8n |
| Read Binary File, read a symlink to `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read Binary File, read `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read Binary File, read a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | READ (outside marker) | blocked by n8n | blocked by n8n |
| Read Binary File, read `/proc/1/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read Binary File, read `/proc/self/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read Binary Files, read `~/.n8n-files` | READ (control marker) | READ (control marker) | READ (control marker) | READ (control marker) | blocked by n8n | blocked by n8n |
| Read Binary Files, read a symlink to `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read Binary Files, read `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read Binary Files, read a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | READ (outside marker) | blocked by n8n | blocked by n8n |
| Read Binary Files, read `/proc/1/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read Binary Files, read `/proc/self/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, read `~/.n8n-files` | READ (control marker) | READ (control marker) | READ (control marker) | READ (control marker) | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, read a symlink to `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read/Write Files from Disk, read `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read/Write Files from Disk, read a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | READ (outside marker) | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, read `/proc/1/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, read `/proc/self/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, write `~/.n8n-files` | WROTE | WROTE | WROTE | WROTE | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, write `~/.n8n/custom` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | WROTE |
| Read/Write Files from Disk, write a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | WROTE | blocked by n8n | blocked by n8n |
| Write Binary File, write `~/.n8n-files` | WROTE | WROTE | WROTE | WROTE | blocked by n8n | blocked by n8n |
| Write Binary File, write `~/.n8n/custom` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | WROTE |
| Write Binary File, write a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | WROTE | blocked by n8n | blocked by n8n |

Left out, and the same as `internal` in every row: `internal-escape`, `external-escape`, `deprecated-allowed`, `ssrf-on`.

READ means the block read the file, followed by the canaries and markers its text held. WROTE means the file was there afterwards.

What the table rests on:

- **n8n's defaults close n8n's files.** In every variant that leaves both file-access settings unset (`internal`, `external`, both escapes, `ssrf-on`, `deprecated-allowed`) and in `files-block-off`, each disk block read and wrote only in `~/.n8n-files`. It couldn't read `~/.n8n/config`, `/proc/self/environ`, `/proc/1/environ`, the file outside both folders, or the symlink to n8n's config, and couldn't write into `~/.n8n/custom` or outside. Git and Execute Sub-workflow were blocked on n8n's folder and outside it. In the allowed folder they passed n8n's check and stopped at git's "Could not determine the git repository" and at "The file content is not valid JSON".
- **The runner mode doesn't matter here.** The disk blocks run in n8n's own process, so `internal` and `external` gave the same answers.
- **An empty allowed list opens n8n's environment.** In `files-restrict-empty`, every read block read `/proc/self/environ` and `/proc/1/environ`, which held all six canaries, and the file outside; Execute Sub-workflow read the outside file; both write blocks wrote outside. n8n's own folder stayed blocked, and so did the symlink to its config.
- **The block on n8n's folders wins.** In `files-restrict-n8n`, which names `~/.n8n` as the only allowed folder, every block was refused everywhere: `~/.n8n` by the block on n8n's folders, and the rest because it isn't on the list.
- **With the block off, n8n's folder opens.** In `files-restrict-n8n-block-off`, every read block read `~/.n8n/config` and the encryption key in it, also through the symlink, and both write blocks wrote into `~/.n8n/custom`, from which n8n loads blocks at its next start. Git's status got past n8n's check on `~/.n8n` and stopped at git. Execute Sub-workflow got past the check, read n8n's config, which is valid JSON, and failed only because it isn't a workflow (an error of 52 characters, kept as its length only). Everything outside `~/.n8n` was refused, `/proc` included.

### What the two file-access settings do (READ, then OBSERVED above)

The code is `node_modules/n8n-core/dist/execution-engine/node-execution-context/utils/file-system-helper-functions.js` and `node_modules/@n8n/config/dist/configs/security.config.js`.

- **One check for every disk block.** n8n first resolves a path to its real path, following symlinks (lines 30 to 44), then checks it (`isFilePathBlocked`, lines 84 to 98). Reads go through `createReadStream` (line 209) and writes through `writeContentToFile` (line 257). Git and Execute Sub-workflow call the same check. The file blocks run in n8n's own process, so the runner mode doesn't change any of this.
- **`N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES`.** Anything but `false`, the default, blocks n8n's own folders: `~/.n8n`, n8n's static cache, `N8N_CONFIG_FILES`, each `N8N_CUSTOM_EXTENSIONS` folder (ours is `/opt/wab/n8n-nodes-wab`), the binary data folder and the email templates (lines 324 to 343). It doesn't name `/proc`. n8n reads it from the environment on each check (line 86).
- **`N8N_RESTRICT_FILE_ACCESS_TO`.** The folders the file blocks may use, separated by `;`. On 2.42.6 it defaults to `~/.n8n-files` (security.config.js line 41), so with neither setting set, a file block reaches only that folder. An empty value means no limit at all (lines 14 to 24), and n8n takes an empty value as set (`node_modules/@n8n/config/dist/decorators.js` lines 10 and 11).
- **The block on n8n's folders wins.** A path in them is blocked even when the allowed list names it (line 88 runs before line 94).
- **`N8N_BLOCK_FILE_PATTERNS`** blocks any path through a `.git` folder by default (security.config.js line 43).
- **Why `~/.n8n` matters.** n8n writes its encryption key into `~/.n8n/config` at its first start, also when the key comes from `N8N_ENCRYPTION_KEY` (`node_modules/n8n-core/dist/instance-settings/instance-settings.js` lines 158 to 188). And it loads blocks from `~/.n8n/custom` at every start, besides the `N8N_CUSTOM_EXTENSIONS` folders (`dist/load-nodes-and-credentials.js` lines 279 to 290). So a read of `~/.n8n` gets the key, and a write there is code that n8n runs, with its whole environment, at its next start.
- **File names leak a little.** Read/Write Files from Disk and Read Binary Files list a pattern's matches with `fast-glob` before the check (`node_modules/n8n-nodes-base/dist/nodes/Files/ReadWriteFile/actions/read.operation.js` lines 105 to 107 and 122). A missing file answers "No file(s) found" and a blocked one "Access to the file is not allowed", so a workflow can tell whether a path outside the allowed folder exists. It can't read it.

The disk table above shows each of these at work: the default keeps every block in `~/.n8n-files`, `files-block-off` alone changes nothing because the default allowed folder still applies, an empty list opens `/proc`, a list naming `~/.n8n` opens nothing while the block is on, and both together open n8n's folder.

### The identity endpoint

- **Its address is open to any block that sends from n8n.** With SSRF protection off, n8n's default, HTTP Request reached `localhost:42356` in every variant, and so did Code, AI Transform and the Code Tool through `helpers.httpRequest`, with the internal runner and with the external one, since n8n sends that call itself. Without the header the stand-in answered 400 (`raw/<variant>.json`, `identity_record`).
- **The header is the guard, and it sits in n8n's environment.** Only code that read n8n's environment found it: the internal runner given Node's modules, and LangChain Code. Each then got a token (200), and the stand-in recorded the canary header. In the external runner, code with every module neither found the header nor reached n8n's `localhost` directly.
- **SSRF protection closes the address.** With `N8N_SSRF_PROTECTION_ENABLED=true` (`ssrf-on`), HTTP Request was refused by n8n's SSRF check, Code's and AI Transform's helper call failed with the same error (`SsrfBlockedIpError`, `node_modules/@n8n/backend-network/dist/ssrf/ssrf-blocked-ip.error.js`), and the stand-in saw no request at all. The AI Agent's call to the stand-in model on `localhost` failed too, so the Code Tool didn't run in that variant. The setting is off by default, and its default list blocks `127.0.0.0/8`, `169.254.0.0/16` and the private ranges (`node_modules/@n8n/config/dist/configs/ssrf-protection.config.js` lines 16 to 32 and 44). Our own blocks call platform-api through the same helper (`n8n-node-pack/src/api.ts` line 58), so with it on, platform-api's address would need to be on `N8N_SSRF_ALLOWED_HOSTNAMES` or `N8N_SSRF_ALLOWED_IP_RANGES`. That wasn't tried.

## Verdicts, in ADR 0051's terms

ADR 0051 says a block that can reach n8n's secrets "stays in 'Can't run on this platform' until it runs where none of n8n's secrets are". The internal runner is a child of n8n, in n8n's container, as n8n's user, so it runs where all of them are, and only its JavaScript sandbox stands between a workflow's code and them. The external runner is such a place: with every module allowed, code there found none of n8n's secrets.

| Block | Verdict for step 12 | What would let it run, if it stays |
|---|---|---|
| Code (JavaScript) | Can load, with the external runner only. With the internal runner it stays in "Can't run on this platform" | n8n's external runner in its own app, with no managed identity and none of n8n's secrets |
| Code (Python) | Can load, with the external runner only. With the internal runner it can't run at all, as the n8n image has no Python | The same |
| AI Transform | As Code (JavaScript): the same runner, the same probe answers | The same |
| Code Tool (JavaScript and Python) | As Code, in each language | The same |
| Sort, code mode, and Item Lists, code sort | As Code (JavaScript). They run in the runner's narrowest mode, and reached even less | The same |
| Function and Function Item | Stay in "Can't run on this platform". n8n 2.42.6 refuses them by default, and they run inside n8n's own process, where the external runner doesn't help | Nothing on this pin. Keep `N8N_DEPRECATED_NODES_BLOCK` at its default |
| LangChain Code | Stays in "Can't run on this platform", as Function | The same |
| Merge, SQL mode | Can load. Its isolate refused every file and URL in every variant | |
| Read/Write Files from Disk, Read Binary File, Read Binary Files, Write Binary File | Can load, with `N8N_RESTRICT_FILE_ACCESS_TO` unset or naming only folders that hold nothing of n8n's, and `N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES` not `false` | |
| Git | Can load, with the same two settings. It reached no path in n8n's folders, and n8n 2.42.6 pins git's command settings and turns hooks off (`Git.node.js` lines 22 to 33 and 455 to 475) | |
| Execute Sub-workflow, from a file | Its disk part passes, with the same two settings. It still waits for section 2's sub-workflow amendment | That amendment |

The settings these verdicts rest on, each of which this spike either changed and watched, or read:

| Setting on n8n | Keep it | Because |
|---|---|---|
| `N8N_RUNNERS_MODE` | `external`, for the runner's blocks | `internal-escape` against `external-escape` |
| `N8N_DEPRECATED_NODES_BLOCK` | unset (on) | `deprecated-allowed`: LangChain Code read n8n's environment |
| `N8N_RESTRICT_FILE_ACCESS_TO` | unset (`~/.n8n-files`), or folders that hold nothing of n8n's. Never empty, never `/` or `/proc` | `files-restrict-empty`: `/proc/self/environ` read |
| `N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES` | unset (on) | `files-restrict-n8n-block-off`: n8n's config read, `~/.n8n/custom` written |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE` | `true`, as section 2 already says | With `false`, n8n sends its whole environment to the runner as `$env` (READ, see above) |
| `NODE_FUNCTION_ALLOW_BUILTIN`, `NODE_FUNCTION_ALLOW_EXTERNAL` | unset | `internal-escape`. n8n also hands them to `vm2` in its own process (`Code/JavaScriptSandbox.js` lines 9 to 18, READ). With the external runner, the runner's own config sets them |
| `N8N_RUNNERS_INSECURE_MODE` | unset | It drops the runner's `--disallow-code-generation-from-strings` and `--disable-proto=delete` (`task-runner-process-js.js` lines 68 to 70, READ). Not run |
| `N8N_PYTHON_ENABLED` | the team's choice | On by default. `false` turns Python off in Code (`nodes.config.js` line 36, `Code.node.js` line 184, READ). Not run |

## Gmail and Outlook: does a token refresh look like a changed key?

**Yes. Every time n8n saves a token it got, it sets the key's `updatedAt` to now.** The sweep's `_vouched()` (`platform-api/src/platform_api/orchestration/n8n_credentials.py` lines 618 to 627) keeps a key only while `n8n_updated_at` equals the `updatedAt` n8n lists, so on its next pass `_remove_foreign` (lines 380 to 395) deletes the key as changed, and `_ensure` makes a platform key anew. The sweep reads nothing else that could tell the two apart: n8n's public API lists only a key's id, name, type, times and sharing (`platform-api/src/platform_api/orchestration/n8n.py` lines 711 to 717).

READ, in n8n 2.42.6:

- `dist/credentials-helper.js` lines 414 to 426. `updateCredentials` writes the key's data with `updatedAt: new Date()` (line 419) through `credentialsRepository.update` (line 425).
- The same file, lines 427 to 456. `updateCredentialsOauthTokenData` writes `oauthTokenData` with `updatedAt: new Date()` (line 449) through `credentialsRepository.update` (line 455).
- Lines 102 to 134. `preAuthentication` gets a token for a key whose type has an expirable field, when that field is empty or a request failed with 401, and saves it with `updateCredentials` (line 127). `node_modules/n8n-core/dist/execution-engine/node-execution-context/utils/request-helpers/authentication.js` calls it before each request (line 41) and again after a 401 (lines 50 to 54).
- `node_modules/n8n-core/dist/execution-engine/node-execution-context/utils/request-helpers/oauth.js` saves an OAuth2 key's token with `updateCredentialsOauthTokenData` after a refresh (line 153) and when a client-credentials key gets its first token (line 243).

Which keys this touches:

- **Outlook.** All three keys the block takes save tokens (`node_modules/n8n-nodes-base/dist/nodes/Microsoft/Outlook/v2/actions/node.description.js` lines 66, 75 and 84). The app key, `microsoftEntraServicePrincipalApi`, has an expirable `accessToken` (`credentials/MicrosoftEntraServicePrincipalApi.credentials.js` lines 116 to 119) that `preAuthentication` fills on first use and after each 401 (lines 223 to 228), so its `updatedAt` changes at its first run and about once an hour after. The two sign-in keys, `microsoftOutlookOAuth2Api` and `microsoftOAuth2Api`, are OAuth2 and save on each refresh.
- **Gmail.** Its sign-in key, `gmailOAuth2`, saves on each refresh. Its service-account key, `googleApi`, gets a new token for each request from a signed JWT and never saves it (`node_modules/n8n-nodes-base/dist/nodes/Google/GenericFunctions.js` lines 103 to 135, called from `nodes/Google/Gmail/GenericFunctions.js` lines 46 to 54), so its `updatedAt` stays. It asks Google for the scopes in lines 61 to 68 of the first file, which need a Google Workspace domain that grants domain-wide delegation.

OBSERVED (`refresh.py`, `raw/refresh.txt`, run on the stack the last variant left up, `deprecated-allowed`, which differs from `internal` only in the deprecated blocks). A generic OAuth2 key (`oAuth2Api`, client credentials) pointed at the stand-in's token URL runs the same save path (`updateCredentialsOauthTokenData`) as Gmail's and Outlook's sign-in keys. An HTTP Request block used it three times:

| Step | What the stand-in saw | Tokens it gave | `updatedAt` after (UTC) | Changed |
|---|---|---|---|---|
| The key as made | | 0 | 06:12:26.274 | |
| First run: no token yet | one call, 200 | 1 | 06:12:26.366 | yes |
| Second run: the saved token works | one call, 200 | 1 | 06:12:26.366 | no |
| Third run: the stand-in refuses that token | 401, then n8n got a new token and called again, 200 | 2 | 06:12:27.625 | yes |

So a key changes `updatedAt` when n8n gets its first token and after each refresh, and not while its saved token still works. `createdAt` never changed.

**What a live sign-in test would still need.** The Entra app key's `preAuthentication` path was read, not run, because its token URL is always `login.microsoftonline.com`. A live test needs, for Outlook, a test Entra tenant with an app registration, a client secret or certificate, and Graph's `Mail.Send` application permission with admin consent, plus a mailbox. For Gmail, it needs a Google Cloud OAuth client and a person signing in through n8n's credential page, whose OAuth callback must be reachable, or a Workspace domain that grants domain-wide delegation for the service-account key. The test would make the key as the platform does, run an Outlook or Gmail block, read `updatedAt` before the first token, after it, and after the token expires (about an hour), run the sweep once, and watch what happens to a run that uses the key while the sweep deletes and remakes it. It uses real accounts and real tokens, so the team decides whether and where it runs.

## What stays open

**Only Azure can settle these.**

- **Sidecar or its own app.** The spike ran the runner in its own container with its own network, as a separate Container App would be. If Container Apps gives a sidecar the app's `IDENTITY_ENDPOINT` and `IDENTITY_HEADER`, and it shares the app's `localhost`, a runner beside n8n in the same app would have the identity header in its launcher's environment, which `external-escape` showed code can read. Whether Container Apps does that is untested here.
- **How the runner reaches n8n's broker.** In external mode n8n's broker listens on port 5679 on every address. n8n's app exposes one port today (`infra/modules/container_app/main.tf` line 50, 5678). Whether the runner app can reach 5679 on n8n's internal address, and who else in the environment then can, is untested. Only `N8N_RUNNERS_AUTH_TOKEN` guards the broker, and the runner's own environment holds it.
- **The real identity endpoint.** The stand-in answered 400 without the header. n8n's Node resolved `localhost` to `::1` first, so the stand-in had to listen on IPv6 as well as IPv4. Azure's own answer, and the addresses it listens on, weren't observed.
- **What else n8n's process reaches on Azure.** Code's HTTP helper and HTTP Request send from n8n's process. What that reaches in the Container Apps environment is ADR 0051's "Code and HTTP Request" part, not this spike.

**Not tried here.**

- **A real way out of a sandbox.** The escape variants stand for code that got out of n8n's `vm` sandbox (or the Python runner's checks). They show what such code would reach, not that a way out exists. Node's own documentation says its `vm` module is not a security mechanism. Function, Function Item and LangChain Code use `vm2` 3.12.2 inside n8n's own process, and no `vm2` escape was tried.
- **Runs that aren't by hand.** Every probe ran by hand (mode `manual`), as a test run does. Where each block's code runs doesn't depend on the mode (READ), but no trigger or webhook run was probed.
- **Python's Code Tool** ran only the plain probe. Python's imports were probed through the Code block.
- **Git with a real repository.** The tool that ran the spike refused to run `git` inside the container, so no repository was made. The Git probes show n8n's path check, and git's answer where the check let them through.
- **The Entra app key's token save** was read, not run (question 5).

**For step 13.** n8n's public API lists only a key's id, name, type, times and sharing, and a token save and a person's edit both change `updatedAt`. So the sweep, as it reads n8n today, can't tell a refresh from a change, and Gmail's and Outlook's write keys still wait for another way.

## What git does not hold

- `p9.env` (the canaries) and `p9-secrets.json` (the throwaway owner's login and API key). `run.py` makes fresh ones, `.gitignore` keeps them out, and they worked only on the p9 containers, which were removed after the run.
- No raw file holds a canary, a file's text, or an error message. Errors are kept as their class only.
