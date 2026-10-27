# n8n 2.42.6 Community edition: our node pack, pausing, editing and publishing (THROWAWAY prototype)

Path: docs/evidence/prototypes/p6-n8n-node-pack/findings.md

This backs [ADR 0026](../../../adr/0026-every-write-is-checked-when-it-is-made-so-n8n-may-hold-the-wait.md) and [ADR 0027](../../../adr/0027-staff-maintain-each-workflow-in-n8n-and-the-portal-keeps-every-published-version.md).

**Setup.**
- Stack: n8nio/n8n:2.42.6 on its default SQLite database, with no licence key (the free Community edition), and a Python stub standing in for our API.
- Compose project `protop6`, with n8n on port 5683 and the stub on 5693. It ran once on 28 Oct 2026.
- Code:
  - `node-pack/`: three nodes written as plain JavaScript, so there is no build step.
  - `stub.py`, `lib.py`, `setup.py`, `q12.py`, `q34.py`, `q4b_q6.py`, `q5.py` and `q5_manual.py`.
  - `compose.q5.yaml` adds the allow list for Q5.

**Users.** `platform@example.com` is n8n's owner and stands in for our platform's account. `staff@example.com` is an ordinary member and stands in for a CODESparks staff member.

## Setup: the free edition has no admin role: OBSERVED

- Inviting a member worked through the REST API, and so did accepting the invitation. q34_raw.txt shows the member signed in and working.
- Inviting an admin returned 403: "Cannot invite admin user without advanced permissions. Please upgrade to a license that includes this feature."
- That output is not kept, because it printed an invitation token.

## Q1 Our node pack loads: OBSERVED

- Setting `N8N_CUSTOM_EXTENSIONS=/custom`, with the folder mounted, loaded our nodes as `CUSTOM.agent`, `CUSTOM.askForYes` and `CUSTOM.makeApprovedChanges`.
- The Agent node's list came from our API. The editor's own request (`POST /rest/dynamic-node-parameters/options`) returned "Version checker" and "Ticket writer" from the stub's `/agents` (q12_raw.txt line 1). A new agent therefore needs no new node.
- The platform created and published an n8n workflow through the public API (lines 3 to 4). It was made of n8n's Webhook node and our three nodes.
- **Catch:** right after publishing, the webhook answered "The requested webhook "POST p6-run" is not registered" for a moment. This was the first run of q12.py, before q12_raw.txt was rewritten. `GET /rest/workflows/{id}/publication-status` shows each trigger as `activated` once it answers (line 5). Our "Ask for a yes" node counts as a trigger there, because it has a resume webhook.

## Q2 Our node pauses the run, and our API wakes it: OBSERVED

"Ask for a yes" calls the stub's `/ask` with the resume URL, then `putExecutionToWait`. The stub wakes it by calling that URL with `{"decision": ...}`. "Make the approved changes" asks the stub's `/write`, which decides only from the stub's own records.

| Case | What happened | q12_raw.txt |
|---|---|---|
| While asked | Execution `waiting`, `waitTill` 3000-01-01 (no time limit of its own). Resume URL `/webhook-waiting/<execution id>?signature=…` | lines 6 to 7 |
| A. Yes through our API | `success`. All five nodes ran and the change was made | lines 8 to 9 |
| B. Woken with the resume URL only | n8n took the Yes exit, but "Make the approved changes" refused: `No yes for this run.` The execution ended `error` | lines 10 to 11 |
| C. No through our API | The No exit ran ("Declined"). "Make the approved changes" did not run | lines 12 to 13 |
| E. A's resume URL used again | 409: `The execution "2 has finished already."` | line 14 |
| D. Staff delete "Ask for a yes" and publish | `No yes for this run.` | lines 15 to 17 |

The stub's records (last line) show one change made, in run 2. Run 1 is still `pending`: its n8n workflow was deleted while it waited. We did not check what n8n does with a waiting execution of a deleted n8n workflow.

## Q3 Keeping edit apart from publish: NOT POSSIBLE on the free edition: OBSERVED

| Step | Result | q34_raw.txt |
|---|---|---|
| Staff list n8n workflows | Empty | line 1 |
| Staff open the platform's n8n workflow | 403: `User is missing a scope required to perform this action` | line 2 |
| The platform shares it with staff | 403: `Plan lacks license for this feature` | line 3 |
| The platform moves it into staff's own space (`PUT /rest/workflows/{id}/transfer`) | 200 | line 4 |
| Staff open it | 200. It is still published | line 5 |
| Staff save an edit | New `versionId`, `activeVersionId` unchanged, and publication status still shows the old live version. The edit is a draft | lines 6 to 7 |
| Staff publish their edit | 200. The draft is now live | line 8 |
| The platform reads it through the public API after the move | 200 | line 9 |
| Staff create and publish an n8n workflow of their own | 200 and 200 | lines 10 to 11 |

So on the free edition:
- An n8n workflow sits in exactly one person's space. Only the owner account sees every n8n workflow.
- Whoever can edit an n8n workflow can also publish it.

## Q4 Who published each version: OBSERVED

- `GET /rest/workflow-history/workflow/{id}/publish-timeline` lists every publish and unpublish with the user who did it (q4b_q6_raw.txt line 1):
  - the platform published versions 8833626e and 707bcf60;
  - staff unpublished 707bcf60 and published 4971f718.
- The version list names the author of each saved version (q34_raw.txt, last line).

## Q6 Staff can add their own keys: OBSERVED

- An ordinary member created a Jira key (`jiraSoftwareCloudApi`) and an HTTP header key in their own space. Both returned 200 (q4b_q6_raw.txt lines 2 to 3).
- The owner account can list every key, including staff's (line 4).
- So "only n8n's owner role can add keys" is not true on the free edition.

## Q5 An allow list of node types (`NODES_INCLUDE`): OBSERVED

`compose.q5.yaml` restarts n8n with `NODES_INCLUDE` set to these nodes:
- n8n's Webhook, Schedule, Manual and Error triggers;
- IF, Merge, No Op and Sticky Note;
- our three nodes.

| Step | Result | q5_raw.txt |
|---|---|---|
| Before: staff publish an n8n workflow with an HTTP Request node that posts data to an outside address (the stub) | Published, and the data reached the address | lines 1 to 2 |
| After: call that workflow's webhook | 400: `Unrecognized node type: n8n-nodes-base.httpRequest`. Nothing was sent | lines 4 to 5 |
| After: staff's list | Still shows it as published (`true`), but it cannot run | line 6 |
| After: staff make a new one with an HTTP Request node | Saved as a draft. Publishing returned 400, `Unrecognized node type` | lines 7 to 8 |
| After: staff make one with n8n's Jira node, which could use their own key | Saved as a draft | line 9 |
| After: the platform publishes our nodes and runs the software check with a yes | `success` | lines 10 to 11 |
| After: staff run either draft by hand in the editor (`POST /rest/workflows/{id}/run`, from `q5_manual.py`) | 400, `Unrecognized node type` for `httpRequest` and for `jira`. Nothing was sent | lines 16 to 19 |

## Harness notes

- The scripts run with plain `python3`, not `python3 -I`, so they can import `lib.py` beside them.
- The local logins and the API key were kept in `p6-secrets.json` and the n8n encryption key in `p6-encryption-key`. Both are git-ignored and were deleted after the run. `docker compose down -v` removed the containers and the n8n database.
- Raw output shows resume URLs with `signature=<redacted>`.
- q12_raw.txt is from the second run of q12.py. The first run stopped at the webhook timing catch in Q1, and the second waits for `publication-status`.
- q34_raw.txt line 13 shows `"by": null` because q34.py read `userId`, while the timeline returns a nested `user`. `q4b_q6.py` reads it correctly (q4b_q6_raw.txt line 1).
- q5_raw.txt lines 12 to 15 are a first hand-run attempt with no start or end node. n8n refused it for that reason, so they test nothing. Lines 16 to 19 are the real test.

## What this means for ADRs 0026 and 0027

1. **ADR 0026 holds on the free edition.** Our own node can pause a run and our API can wake it. Each of these refused to write, because the write checks our own records:
   - a run woken with only the resume URL;
   - a deleted "Ask for a yes";
   - a reused resume URL.
2. **ADR 0027 needs three changes:**
   - **Editing.** The free edition cannot share an n8n workflow, so each one sits in one person's space. The platform account, as n8n's owner, can always read, move and publish any n8n workflow. "Open in n8n" can move an n8n workflow into the person's own space, one editor at a time.
   - **Publishing.** Whoever edits an n8n workflow can publish it. Safety still holds (ADR 0026). Our API reads the publish timeline to learn who published, so the publisher rule works.
   - **Keys.** Staff can add their own keys, so a daily check of keys is not enough. With `NODES_INCLUDE`, no node exists that could use those keys, call out or run code. That holds even for a draft run by hand. n8n's own Jira, Confluence and GitHub nodes are then not on the list, so reading also goes through our node pack. The Planner's list of allowed nodes becomes the same list, and n8n enforces it for everyone.
3. **Before the Portal says a workflow is on,** it should wait for `publication-status` to show every trigger as `activated`.
